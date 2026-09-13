"""Put cxpaper-license.js on Cloudflare.

Chris runs this. It reads the credential out of C:\\_CLAUDE\\cf-token.txt and
talks to Cloudflare directly, so the token never goes through a chat window, a
log, or this repository. Nothing is installed: no Node, no wrangler, just the
Python already on the machine.

    python worker\\deploy_worker.py

It is safe to run again. Re-running replaces the code and leaves the stored
keys, claims and reports exactly where they are.

WHAT GOES IN THE FILE: the Cloudflare API token, on a line of its own. The
account id is optional - Cloudflare is asked which accounts the token reaches.
Extra lines are tolerated and each one is tried, because working out which
long string is which by looking at it sent this round in circles once already.
Cloudflare is the only thing that actually knows, so it is asked.

The token comes from https://dash.cloudflare.com/profile/api-tokens
    Create Token -> "Edit Cloudflare Workers" -> Continue -> Create Token
The value is shown ONCE, on the screen straight after Create Token.
"""
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request

TOKEN_FILE = r"C:\_CLAUDE\cf-token.txt"
ADMIN_FILE = r"C:\_CLAUDE\cp-admin-token.txt"
SCRIPT_NAME = "cxpaper-license"
KV_TITLE = "cxpaper-license"
COMPAT_DATE = "2025-01-01"
API = "https://api.cloudflare.com/client/v4"

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER_JS = os.path.join(HERE, "cxpaper-license.js")


def die(message):
    print(os.linesep + "STOPPED: " + message)
    sys.exit(1)


def why_not(e):
    """Cloudflare's own words for a refusal, rather than a status code."""
    try:
        doc = json.loads(e.read().decode("utf-8", "replace"))
        said = "; ".join(str(x.get("message")) for x in doc.get("errors", []))
        return said or ("HTTP %s" % e.code)
    except Exception:
        return "HTTP %s" % getattr(e, "code", "?")


def read_lines():
    if not os.path.isfile(TOKEN_FILE):
        die("%s is not there. Put your Cloudflare API token in it." % TOKEN_FILE)
    text = open(TOKEN_FILE, encoding="utf-8").read()
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    if not lines:
        die("%s is empty." % TOKEN_FILE)
    return lines


def probe(headers, path):
    req = urllib.request.Request(API + path)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8")).get("success") is True, ""
    except urllib.error.HTTPError as e:
        return False, why_not(e)
    except Exception as e:
        return False, str(e)


def candidates(line):
    """A token, dug out of whatever came with it when it was copied.

    A copy off the dashboard picks up a stray quote, a "Bearer " in front, or
    the label beside the box. Cloudflare then refuses the whole string and
    says nothing about which part was wrong. So: the line as typed, the line
    with the usual decorations stripped, and every run of token characters in
    it that is the right length. The same trick the program uses on a pasted
    licence key, for the same reason - people select more than the thing.
    """
    out = []

    def add(v):
        v = (v or "").strip()
        if v and v not in out:
            out.append(v)

    add(line)
    bare = line.strip().strip('"').strip("'").strip()
    if bare.lower().startswith("bearer "):
        bare = bare[7:].strip()
    add(bare)
    for run in re.findall(r"[A-Za-z0-9_-]{30,}", line):
        add(run)
    # longest first: the token is the long part, the label around it is short
    return sorted(out, key=len, reverse=True)


def read_credentials():
    """Work out what is in the file by TRYING it, not by measuring it.
    Returns (auth_headers, account_id_or_None)."""
    lines = read_lines()
    tried = []

    for i, line in enumerate(lines, 1):
        for value in candidates(line):
            ok, said = probe({"Authorization": "Bearer " + value}, "/user/tokens/verify")
            how = "line %d" % i if value == line.strip() else "line %d (%d chars of it)" % (i, len(value))
            tried.append("  %s as an API token: %s" % (how, "WORKS" if ok else (said or "refused")))
            if ok:
                print("  %s is a working API token" % how)
                spare = [l for j, l in enumerate(lines, 1) if j != i and len(l) == 32]
                return {"Authorization": "Bearer " + value}, (spare[0] if spare else None)

    # The older Global API Key travels with the account email rather than on
    # its own, and a file holding an email plus a long hex string is exactly
    # what that setup looks like. Worth one try before giving up.
    emails = [l for l in lines if "@" in l]
    keys = [l for l in lines if "@" not in l]
    if emails and keys:
        head = {"X-Auth-Email": emails[0], "X-Auth-Key": keys[0]}
        ok, said = probe(head, "/accounts?per_page=5")
        tried.append("  the email plus the other line as a Global API Key: %s"
                     % ("WORKS" if ok else (said or "refused")))
        if ok:
            print("  the email and Global API Key work")
            return head, None

    die("Nothing in %s is a credential Cloudflare accepts."
        % TOKEN_FILE
        + os.linesep + os.linesep + "What was tried:" + os.linesep
        + os.linesep.join(tried)
        + os.linesep + os.linesep
        + "Make a token at https://dash.cloudflare.com/profile/api-tokens"
        + os.linesep
        + "  Create Token -> 'Edit Cloudflare Workers' -> Continue -> Create Token"
        + os.linesep
        + "The value is shown ONCE, on the screen straight after Create Token."
        + os.linesep
        + "Put that value in the file on a line of its own.")


def call(auth, method, path, body=None, raw=None, ctype=None):
    url = API + path
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in auth.items():
        req.add_header(k, v)
    if ctype:
        req.add_header("Content-Type", ctype)
    elif body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        die("Cloudflare said no to %s %s: %s" % (method, path, why_not(e)))
    except Exception as e:
        die("Could not reach Cloudflare for %s %s: %s" % (method, path, e))


def find_account(auth, account):
    """The account id need not be in the file - Cloudflare will say which
    accounts this credential can reach."""
    if account:
        print("  account id taken from the file")
        return account
    doc = call(auth, "GET", "/accounts?per_page=50")
    accounts = doc.get("result") or []
    if not accounts:
        die("That credential reaches no Cloudflare accounts. If the token was "
            "made with the 'Edit Cloudflare Workers' template it should reach "
            "one - check it was not scoped to a single zone.")
    if len(accounts) > 1:
        print("  %d accounts found; using the first: %s"
              % (len(accounts), accounts[0].get("name")))
    else:
        print("  account: %s" % accounts[0].get("name"))
    return accounts[0]["id"]


def kv_namespace(auth, account):
    doc = call(auth, "GET", "/accounts/%s/storage/kv/namespaces?per_page=100" % account)
    for ns in doc.get("result", []):
        if ns.get("title") == KV_TITLE:
            print("  store found")
            return ns["id"]
    doc = call(auth, "POST", "/accounts/%s/storage/kv/namespaces" % account,
               {"title": KV_TITLE})
    print("  store created")
    return doc["result"]["id"]


def multipart(fields, files):
    """Cloudflare wants the script as multipart. Built by hand rather than
    pulling in a library - this machine has no package manager on PATH."""
    boundary = "----cxpaper" + secrets.token_hex(16)
    crlf = "\r\n"
    out = []
    for name, value in fields.items():
        out.append(("--" + boundary + crlf
                    + 'Content-Disposition: form-data; name="' + name + '"'
                    + crlf + crlf + value + crlf).encode("utf-8"))
    for name, (filename, content, ctype) in files.items():
        out.append(("--" + boundary + crlf
                    + 'Content-Disposition: form-data; name="' + name
                    + '"; filename="' + filename + '"' + crlf
                    + "Content-Type: " + ctype + crlf + crlf).encode("utf-8"))
        out.append(content)
        out.append(crlf.encode("utf-8"))
    out.append(("--" + boundary + "--" + crlf).encode("utf-8"))
    return b"".join(out), "multipart/form-data; boundary=" + boundary


def upload(auth, account, ns_id):
    if not os.path.isfile(WORKER_JS):
        die("%s is missing." % WORKER_JS)
    code = open(WORKER_JS, "rb").read()
    metadata = {
        "main_module": "worker.js",
        "compatibility_date": COMPAT_DATE,
        "bindings": [{"type": "kv_namespace", "name": "CP", "namespace_id": ns_id}]
    }
    raw, ctype = multipart(
        {"metadata": json.dumps(metadata)},
        {"worker.js": ("worker.js", code, "application/javascript+module")})
    call(auth, "PUT", "/accounts/%s/workers/scripts/%s" % (account, SCRIPT_NAME),
         raw=raw, ctype=ctype)
    print("  code uploaded (%d bytes)" % len(code))


def admin_token(auth, account):
    """The password the dashboard uses to read the customer list. Made here,
    kept beside the Cloudflare token, and sent to Cloudflare as a secret - it
    is never written into the worker's source."""
    if os.path.isfile(ADMIN_FILE):
        value = open(ADMIN_FILE, encoding="utf-8").read().strip()
        made = False
    else:
        value = secrets.token_urlsafe(32)
        with open(ADMIN_FILE, "w", encoding="utf-8") as f:
            f.write(value + os.linesep)
        made = True
    call(auth, "PUT", "/accounts/%s/workers/scripts/%s/secrets" % (account, SCRIPT_NAME),
         {"name": "ADMIN_TOKEN", "text": value, "type": "secret_text"})
    print("  dashboard password %s, kept in %s"
          % ("created" if made else "reused", ADMIN_FILE))


def public_address(auth, account):
    call(auth, "POST", "/accounts/%s/workers/scripts/%s/subdomain" % (account, SCRIPT_NAME),
         {"enabled": True, "previews_enabled": False})
    doc = call(auth, "GET", "/accounts/%s/workers/subdomain" % account)
    sub = (doc.get("result") or {}).get("subdomain")
    if not sub:
        return None
    return "https://%s.%s.workers.dev" % (SCRIPT_NAME, sub)


def main():
    print("Putting the licence desk on Cloudflare.")
    print("")
    auth, account = read_credentials()
    account = find_account(auth, account)
    ns_id = kv_namespace(auth, account)
    upload(auth, account, ns_id)
    admin_token(auth, account)
    url = public_address(auth, account)

    print("")
    print("Done.")
    if url:
        print("")
        print("Its address is:")
        print("    " + url)
        print("")
        print("Put that in assets/site.js as:")
        print('    licenseApi: "' + url + '/request",')
        print("")
        print("Open the address in a browser to check it is alive - it should")
        print("answer with one line of text, not an error.")
    else:
        print("")
        print("Uploaded, but Cloudflare did not report the public address.")
        print("Look under Workers & Pages -> " + SCRIPT_NAME + " -> Settings.")
    print("")
    print("No keys are in stock yet, so the form will say so until a batch is minted.")


if __name__ == "__main__":
    main()
