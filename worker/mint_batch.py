"""Mint a batch of license keys and send them to the license desk.

Run this on Chris's PC, where the signing seed lives. It signs the keys here
and posts only the finished, signed keys to the Worker - the seed itself never
leaves this machine and is never sent anywhere.

    python worker\\mint_batch.py              25 keys, one year each
    python worker\\mint_batch.py 50           50 keys
    python worker\\mint_batch.py 25 --days 730

It reads:
    C:\\_CLAUDE\\PST_Build\\dist\\ig_admin_key.igk   the Ed25519 signing seed
    C:\\_CLAUDE\\cp-worker-url.txt                  the license desk's address
    C:\\_CLAUDE\\cp-admin-token.txt                 the license desk's password

The password comes from the file deploy_worker.py writes, which is the same
string it sets as the Worker's ADMIN_TOKEN secret - so the two cannot drift
apart, and neither copy is in this repository. Nothing here needs a Cloudflare
API token.

Every key minted is also written to the local ledger, so the roster on this
machine stays the record of what was issued, exactly as KeyMaker's is.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

PST_BUILD = r"C:\_CLAUDE\PST_Build"
SEED_FILE = os.path.join(PST_BUILD, "dist", "ig_admin_key.igk")
LEDGER = os.path.join(PST_BUILD, "dist", "issued_licenses.json")
URL_FILE = r"C:\_CLAUDE\cp-worker-url.txt"
ADMIN_FILE = r"C:\_CLAUDE\cp-admin-token.txt"

# A key sits in the pool from the moment it is minted until somebody asks for
# it, and its term has been running the whole time - the last key out of a
# 100-key batch can be months down. Two things keep that small: mint modest
# batches often (the default below), and add this much to every term to cover
# the wait. A year means a year, not "a year minus however long it queued".
POOL_PAD_DAYS = 30

LICENSE_PUB_HEX = "ae9c54aa2aa376227186fa2d418d39704ab3365f8364e96661f8532f69acb2b1"

sys.path.insert(0, PST_BUILD)


def die(message):
    print("")
    print("STOPPED: " + message)
    sys.exit(1)


def load_ed25519():
    """The app's own Ed25519, so a key minted here is signed by exactly the
    code that will verify it. Importing rather than reimplementing is the
    whole point - two implementations is one too many for a signature."""
    try:
        import importlib
        ig = importlib.import_module("inspector_gadgets")
        return ig
    except Exception as e:
        die("Could not load inspector_gadgets from %s: %s" % (PST_BUILD, e))


def load_seed():
    if not os.path.isfile(SEED_FILE):
        die("The signing key is not at %s.\nWithout it no key can be made."
            % SEED_FILE)
    raw = open(SEED_FILE, encoding="utf-8").read().strip()
    seed = base64.b64decode(raw)
    if len(seed) != 32:
        die("The signing key is not 32 bytes.")
    return seed


def worker_password():
    """The password, from the one file that holds it.

    It used to be read out of worker\\cxpaper-license.js, where it sat as a
    constant. Two things were wrong with that. The password for the customer
    list was in the repository that publishes cxpaper.com - one click of
    "make public" and it was on the internet. And deploy_worker.py sets a
    RANDOM ADMIN_TOKEN secret on Cloudflare, which the Worker prefers, so
    deploying the license desk silently locked Chris out of stocking it: the
    constant here and the secret up there were never the same string.

    Now there is one copy, in the file deploy_worker.py writes.
    """
    if not os.path.isfile(ADMIN_FILE):
        die("The license desk password is not at %s.\n\n"
            "That file is made by:\n"
            "    python worker\\deploy_worker.py\n\n"
            "Run that once and the password will be there for both of us."
            % ADMIN_FILE)
    value = open(ADMIN_FILE, encoding="utf-8").read().strip()
    if not value:
        die("%s is empty. Delete it and run worker\\deploy_worker.py again."
            % ADMIN_FILE)
    return value


def read_or_make(path, what, maker=None):
    if os.path.isfile(path):
        value = open(path, encoding="utf-8").read().strip()
        if value:
            return value, False
    if maker is None:
        return None, True
    value = maker()
    with open(path, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    return value, True


def post(url, path, admin, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url.rstrip("/") + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-CP-Admin", admin)
    # Cloudflare turns away urllib's default "Python-urllib/3.x" with a 403
    # and error code 1010 - a bot check, refused in front of the Worker, which
    # never sees the request at all. So the FIRST batch could not be stocked:
    # the desk was deployed and working, and this said "the license desk said
    # no". Everything else that talks to the desk already names itself; this
    # was the one caller that did not.
    req.add_header("User-Agent", "ConstructionPaper-mint/1 (key batch)")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        if e.code == 401:
            die("The license desk refused the password.\n\n"
                "The desk is running with a different password than the one\n"
                "in %s.\n"
                "Run worker\\deploy_worker.py: it sets the password up there\n"
                "and writes the same one down here." % ADMIN_FILE)
        die("The license desk said no (HTTP %s): %s" % (e.code, text[:300]))
    except Exception as e:
        die("Could not reach %s: %s" % (url, e))


def record(rows):
    """The local ledger stays the record of what was issued, the same file
    KeyMaker and the Admin tab write."""
    existing = []
    if os.path.isfile(LEDGER):
        try:
            existing = json.load(open(LEDGER, encoding="utf-8"))
        except Exception:
            existing = []
    existing.extend(rows)
    with open(LEDGER, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=1)


def main():
    # 25, not 100. A batch is stock sitting on a shelf with its clock already
    # running; a few weeks' worth at a time keeps the shelf life short. Ask
    # for more explicitly if a big batch is really wanted.
    count = 25
    days = 365
    args = sys.argv[1:]
    if args and args[0].isdigit():
        count = int(args[0])
    if "--days" in args:
        days = int(args[args.index("--days") + 1])
    if count < 1 or count > 500:
        die("Ask for between 1 and 500 keys.")

    url, made_url = read_or_make(URL_FILE, "worker address")
    if not url:
        die("I do not know the license desk's address.\n\n"
            "Put it in %s - one line, like:\n"
            "    https://cxpaper-license.something.workers.dev\n\n"
            "It is on the Worker's page under Settings -> Domains & Routes."
            % URL_FILE)

    admin = worker_password()

    ig = load_ed25519()
    seed = load_seed()
    if ig._ed25519.publickey(seed).hex() != LICENSE_PUB_HEX:
        die("The signing key does not match the public key the program checks "
            "against.\nStop: keys minted with it would be refused by every copy.")

    term = days + POOL_PAD_DAYS
    print("Minting %d keys, %d days each (%d asked for, plus %d to cover the "
          "wait in the pool)." % (count, term, days, POOL_PAD_DAYS))
    if count > 50:
        print("")
        print("That is a big batch. Every key's term starts NOW, so the last")
        print("one handed out will have spent a long time on the shelf.")
    now = int(time.time())
    keys, rows = [], []
    for _ in range(count):
        payload = {"format": 1, "id": uuid.uuid4().hex[:12].upper(),
                   "licensee": "", "email": "", "machine": "",
                   "issued": now, "expires": now + term * 86400,
                   # "online": 0 is deliberate, and is the difference between
                   # a working key and a support call. A key minted here sits
                   # in the pool until somebody asks for it, which can be
                   # weeks. With "online": 1 the 30-day check-in clock ran
                   # from THIS moment, so a customer who bought a month later
                   # and opened the program in a truck with no signal was told
                   # their brand-new key was overdue. 0 starts that clock at
                   # the copy's first successful check-in instead, which is
                   # what it was always meant to measure. A lenient key that
                   # HAS checked in is still cut off 30 days after its last
                   # check-in, by the same code.
                   "online": 0}
        sig = ig._ed25519.sign(ig._license_canon(payload), seed,
                               bytes.fromhex(LICENSE_PUB_HEX))
        blob = {"payload": payload, "sig": base64.b64encode(sig).decode()}
        code = base64.urlsafe_b64encode(
            json.dumps(blob, separators=(",", ":")).encode()).decode()
        keys.append({"id": payload["id"], "code": code})
        rows.append({"id": payload["id"], "licensee": "(unissued - from the website)",
                     "email": "", "machine": "", "issued": now,
                     "expires": payload["expires"], "online": 0,
                     "job": "", "batch": now})

    print("Sending them to the license desk...")
    doc = post(url, "/admin/stock", admin, {"keys": keys})
    record(rows)

    print("")
    print("Added:   %d" % doc.get("added", 0))
    if doc.get("skipped"):
        print("Skipped: %d (already known)" % doc["skipped"])
    print("In stock now: %d" % doc.get("keys_in_stock", 0))
    print("")
    print("The ledger on this machine has the new rows: %s" % LEDGER)


if __name__ == "__main__":
    main()
