"""Mint a batch of licence keys and send them to the licence desk.

Run this on Chris's PC, where the signing seed lives. It signs the keys here
and posts only the finished, signed keys to the Worker - the seed itself never
leaves this machine and is never sent anywhere.

    python worker\\mint_batch.py              100 keys, one year each
    python worker\\mint_batch.py 25           25 keys
    python worker\\mint_batch.py 25 --days 730

It reads:
    C:\\_CLAUDE\\PST_Build\\dist\\ig_admin_key.igk   the Ed25519 signing seed
    C:\\_CLAUDE\\cp-worker-url.txt                  the licence desk's address

The password is read out of worker\\cxpaper-license.js, which is the same file
the licence desk is running, so the two cannot drift apart. Nothing here needs
a Cloudflare API token.

Every key minted is also written to the local ledger, so the roster on this
machine stays the record of what was issued, exactly as KeyMaker's is.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

PST_BUILD = r"C:\_CLAUDE\PST_Build"
SEED_FILE = os.path.join(PST_BUILD, "dist", "ig_admin_key.igk")
LEDGER = os.path.join(PST_BUILD, "dist", "issued_licenses.json")
URL_FILE = r"C:\_CLAUDE\cp-worker-url.txt"

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
    """The password is the ADMIN_FALLBACK line in the worker's own source, so
    there is only ever one copy of it and nothing to keep in step by hand."""
    js = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "cxpaper-license.js")
    if not os.path.isfile(js):
        die("%s is missing - it is where the password lives." % js)
    text = open(js, encoding="utf-8").read()
    found = re.search(r'ADMIN_FALLBACK\s*=\s*"([^"]+)"', text)
    if not found:
        die("No ADMIN_FALLBACK line in %s." % js)
    return found.group(1)


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
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        if e.code == 401:
            die("The licence desk refused the password.\n"
                "The copy running at that address is older than the\n"
                "worker\\cxpaper-license.js here. Paste the current file into\n"
                "the Cloudflare editor, deploy it, then run this again.")
        die("The licence desk said no (HTTP %s): %s" % (e.code, text[:300]))
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
    count = 100
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
        die("I do not know the licence desk's address.\n\n"
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

    print("Minting %d keys, %d days each." % (count, days))
    now = int(time.time())
    keys, rows = [], []
    for _ in range(count):
        payload = {"format": 1, "id": uuid.uuid4().hex[:12].upper(),
                   "licensee": "", "email": "", "machine": "",
                   "issued": now, "expires": now + days * 86400,
                   "online": 1}
        sig = ig._ed25519.sign(ig._license_canon(payload), seed,
                               bytes.fromhex(LICENSE_PUB_HEX))
        blob = {"payload": payload, "sig": base64.b64encode(sig).decode()}
        code = base64.urlsafe_b64encode(
            json.dumps(blob, separators=(",", ":")).encode()).decode()
        keys.append({"id": payload["id"], "code": code})
        rows.append({"id": payload["id"], "licensee": "(unissued - from the website)",
                     "email": "", "machine": "", "issued": now,
                     "expires": payload["expires"], "online": 1,
                     "job": "", "batch": now})

    print("Sending them to the licence desk...")
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
