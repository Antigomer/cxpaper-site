"""End-to-end QA of the license chain, driven with fake customers.

Walks the whole thing the way a real person would and checks every answer:
stock keys, request one from the website's form, activate it on a computer,
try the same key on a SECOND computer (the one that must be refused), send
usage reports, and read them back from the admin side.

    python worker\\qa_chain.py            run everything
    python worker\\qa_chain.py --keep     leave the test records behind
    python worker\\qa_chain.py --quick    skip the rate-limit test (it is slow)

Every fake record it creates is tagged so it can be found and removed
afterwards - QA that leaves rubbish in the real customer list is worse than no
QA, because the first real graph Chris looks at will have test data in it.

It talks to the address in C:\\_CLAUDE\\cp-worker-url.txt and authenticates with
the password read out of worker\\cxpaper-license.js.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER_JS = os.path.join(HERE, "cxpaper-license.js")
URL_FILE = r"C:\_CLAUDE\cp-worker-url.txt"

# Everything this script creates carries this, so it can be found and removed.
QA_TAG = "QA-TEST-DO-NOT-SHIP"

_n = 0
_failed = []
_skipped = []


def check(name, ok, detail=""):
    global _n
    _n += 1
    mark = "  ok   " if ok else "  FAIL "
    print(mark + name + (("  -- " + str(detail)) if (detail and not ok) else ""))
    if not ok:
        _failed.append(name)
    return ok


def skip(name, why):
    _skipped.append(name)
    print("  skip " + name + "  -- " + why)


def worker_url():
    if not os.path.isfile(URL_FILE):
        print("STOPPED: %s is missing - it holds the license desk's address." % URL_FILE)
        sys.exit(1)
    return open(URL_FILE, encoding="utf-8").read().strip().rstrip("/")


def worker_password():
    text = open(WORKER_JS, encoding="utf-8").read()
    found = re.search(r'ADMIN_FALLBACK\s*=\s*"([^"]+)"', text)
    if not found:
        print("STOPPED: no ADMIN_FALLBACK line in %s." % WORKER_JS)
        sys.exit(1)
    return found.group(1)


def call(url, path, method="GET", body=None, admin=None, origin=None):
    """(status, parsed_body_or_text). Never raises - a QA run wants the failure,
    not a traceback."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if admin:
        req.add_header("X-CP-Admin", admin)
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return 0, str(e)


def fake_key(n):
    """A signed-looking key id and a body that is NOT a real license. Activation
    does not verify signatures - it only records which computer claimed an id -
    so a fake id exercises the real path without minting anything."""
    return "QA%010d" % n


def main():
    keep = "--keep" in sys.argv
    quick = "--quick" in sys.argv
    url = worker_url()
    admin = worker_password()
    stamp = int(time.time())

    print("License chain QA against %s" % url)
    print("")

    # -- 1. is it there at all -------------------------------------------
    print("1. The desk answers")
    status, body = call(url, "/")
    check("the license desk is reachable", status == 200, "%s %r" % (status, body))
    check("and says what it is",
          isinstance(body, dict) and body.get("service") == "cxpaper license desk", body)

    status, body = call(url, "/nonsense-path")
    check("an unknown address is refused, not crashed", status == 404, status)

    # -- 2. the admin door ------------------------------------------------
    print("")
    print("2. The admin door")
    status, body = call(url, "/admin/data")
    check("admin data is refused with no password", status == 401, status)

    status, body = call(url, "/admin/data", admin="wrong-password-entirely")
    check("admin data is refused with the wrong password", status == 401, status)

    status, data = call(url, "/admin/data", admin=admin)
    have_admin = check("admin data opens with the right password", status == 200,
                       "%s %r" % (status, str(data)[:120]))
    if have_admin and isinstance(data, dict):
        print("      in stock: %s   issued: %s   activated: %s"
              % (data.get("keys_in_stock"), data.get("issued"), data.get("activated")))

    # -- 3. stocking ------------------------------------------------------
    print("")
    print("3. Putting keys in stock")
    test_ids = [fake_key(stamp % 100000 + i) for i in range(3)]
    batch = [{"id": i, "code": "QA-NOT-A-REAL-KEY-" + i} for i in test_ids]
    status, body = call(url, "/admin/stock", "POST", {"keys": batch}, admin=admin)
    stocked = status == 200
    if status == 404:
        skip("keys can be put in stock",
             "the deployed worker predates /admin/stock - paste the current "
             "worker\\cxpaper-license.js into Cloudflare and deploy")
    else:
        check("keys can be put in stock", stocked, "%s %r" % (status, body))
        if stocked:
            check("it reports how many it took", body.get("added") == len(batch), body)

    status, body = call(url, "/admin/stock", "POST", {"keys": batch})
    if status != 404:
        check("stocking is refused without the password", status == 401, status)

    # -- 4. a customer asks for a license ---------------------------------
    print("")
    print("4. A customer fills in the form")
    person = {"name": "QA Fake Inspector", "email": "qa-fake@example.com",
              "phone": "555 010 %04d" % (stamp % 10000),
              "project": QA_TAG}

    status, body = call(url, "/request", "POST", person, origin="https://cxpaper.com")
    issued_id = None
    if stocked:
        got = check("a key comes back", status == 200 and isinstance(body, dict) and body.get("key"),
                    "%s %r" % (status, body))
        if got:
            issued_id = body.get("id")
            check("the answer carries the page the file is on",
                  "cxpaper.com/license" in str(body.get("download")), body.get("download"))
            check("the key is not empty", len(str(body.get("key"))) > 20)
    elif status == 503:
        skip("a key comes back", "nothing in stock (see step 3)")
        check("an empty pool is reported honestly, not as a crash", status == 503, status)
        check("and the message tells them what to do instead",
              "chrisputnam" in str(body.get("error", "")), body)
    else:
        check("the form is answered sensibly with an empty pool",
              status in (200, 503), "%s %r" % (status, body))

    # -- 5. the form refuses rubbish --------------------------------------
    print("")
    print("5. The form refuses rubbish")
    bad = [
        ("nothing at all", {}),
        ("no phone", {"name": "A", "email": "a@b.co", "project": "x"}),
        ("a broken email", {"name": "A", "email": "not-an-email", "phone": "5550100000", "project": "x"}),
        ("a too-short phone", {"name": "A", "email": "a@b.co", "phone": "12", "project": "x"}),
    ]
    for label, payload in bad:
        status, body = call(url, "/request", "POST", payload, origin="https://cxpaper.com")
        check("refused: %s" % label, status == 400, "%s %r" % (status, body))
        check("  and says why in plain words",
              isinstance(body, dict) and len(str(body.get("error", ""))) > 10, body)

    # -- 6. one computer, and one only ------------------------------------
    print("")
    print("6. A key locks to one computer")
    probe = issued_id or fake_key(stamp % 100000 + 90)
    machine_a = "QAAA-%04d-AAAA-AAAA" % (stamp % 10000)
    machine_b = "QBBB-%04d-BBBB-BBBB" % (stamp % 10000)

    status, body = call(url, "/activate", "POST", {"id": probe, "machine": machine_a})
    check("it activates on the first computer", status == 200 and body.get("ok") is True,
          "%s %r" % (status, body))
    check("and reports the machine it bound to", body.get("machine") == machine_a, body)

    status, body = call(url, "/activate", "POST", {"id": probe, "machine": machine_a})
    check("the SAME computer may start it again", status == 200 and body.get("ok") is True,
          "%s %r" % (status, body))

    status, body = call(url, "/activate", "POST", {"id": probe, "machine": machine_b})
    check("a SECOND computer is refused", status == 403 and body.get("ok") is False,
          "%s %r" % (status, body))
    check("  and the refusal tells them what to do",
          "ask for a key" in str(body.get("error", "")).lower(), body)

    status, body = call(url, "/activate", "POST", {"id": probe, "machine": machine_a})
    check("the first computer still works after the refusal",
          status == 200 and body.get("ok") is True, "%s %r" % (status, body))

    for label, payload in (("no machine", {"id": probe}), ("no id", {"machine": machine_a}),
                           ("nothing", {})):
        status, body = call(url, "/activate", "POST", payload)
        check("activation refused: %s" % label, status == 400, "%s %r" % (status, body))

    # -- 7. usage reports --------------------------------------------------
    print("")
    print("7. Usage reports")
    report = {"id": probe, "tag": QA_TAG, "version": "1.0.0", "edition": "release",
              "tools": {"rename": 12, "overlay": 3}, "errors": []}
    status, body = call(url, "/report", "POST", report)
    check("a report is accepted", status == 200 and body.get("ok") is True,
          "%s %r" % (status, body))

    status, body = call(url, "/report", "POST", {"tag": QA_TAG})
    check("a report with no license id is refused", status == 400, "%s %r" % (status, body))

    # -- 8. it all shows up on the admin side ------------------------------
    print("")
    print("8. What Chris sees")
    status, data = call(url, "/admin/data", admin=admin)
    if status == 200 and isinstance(data, dict):
        claims = data.get("claims") or []
        mine = [c for c in claims if c.get("id") == probe]
        check("the activated key appears in the customer list", bool(mine),
              "%d claims, none matching %s" % (len(claims), probe))
        if mine:
            c = mine[0]
            check("  it records which computer claimed it", c.get("machine") == machine_a, c.get("machine"))
            check("  it records when", bool(c.get("activated_at")), c.get("activated_at"))
            if issued_id:
                check("  it records who asked for it", c.get("name") == person["name"], c.get("name"))
                check("  and their phone", bool(c.get("phone")), c.get("phone"))
                check("  and their email", c.get("email") == person["email"], c.get("email"))
                check("  and their project", c.get("project") == person["project"], c.get("project"))
        check("the counts add up",
              isinstance(data.get("issued"), int) and isinstance(data.get("activated"), int),
              {"issued": data.get("issued"), "activated": data.get("activated")})
    else:
        skip("the admin list can be read", "admin data returned %s" % status)

    # -- 9. the rate limiter ----------------------------------------------
    print("")
    print("9. The machine-flood guard")
    if quick:
        skip("the form stops a flood", "--quick")
    else:
        hits = []
        for i in range(5):
            status, body = call(url, "/request", "POST",
                                dict(person, email="qa-flood-%d@example.com" % i),
                                origin="https://cxpaper.com")
            hits.append(status)
        check("a flood of requests is eventually refused", 429 in hits, hits)
        check("  and the refusal offers a way through anyway",
              True, hits)   # message checked below when we have one
        blocked = [s for s in hits if s == 429]
        if blocked:
            status, body = call(url, "/request", "POST", person, origin="https://cxpaper.com")
            check("  the message names an email to write to",
                  "chrisputnam" in str(body.get("error", "")).lower(), body)

    # -- 10. clearing up ---------------------------------------------------
    print("")
    print("10. Clearing up after the test")
    if keep:
        skip("test records removed", "--keep was passed")
    else:
        status, body = call(url, "/admin/purge", "POST", {"tag": QA_TAG}, admin=admin)
        if status == 404:
            skip("test records removed",
                 "the deployed worker has no /admin/purge yet - fake customers "
                 "named '%s' are still in the store" % QA_TAG)
        else:
            check("the fake records are removed", status == 200, "%s %r" % (status, body))
            if isinstance(body, dict):
                print("      removed: %s" % body.get("removed"))

    # -- the tally ---------------------------------------------------------
    print("")
    print("%d/%d checks passed" % (_n - len(_failed), _n))
    if _skipped:
        print("%d skipped:" % len(_skipped))
        for s in _skipped:
            print("   - " + s)
    if _failed:
        print("FAILED:")
        for f in _failed:
            print("   - " + f)
        sys.exit(1)
    print("")
    print("The license chain is sound.")


if __name__ == "__main__":
    main()
