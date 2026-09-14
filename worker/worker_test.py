"""Run the licence desk's own code against a stand-in KV, on this machine.

There is no Node here, so cxpaper-license.js has never been executed before a
deploy - it went straight from an editor to the thing that hands out licence
keys. This runs the real handlers by translating the file into Python: the
same branches, the same order, the same replies. It is a translation, not the
article, and it says so - but a translation that goes red on the defects the
audit found is worth more than nothing running at all.

    python worker\\worker_test.py

Each check names the finding it stands for.
"""
import hashlib
import json
import random
import sys
import uuid

MAX_REQUESTS_PER_HOUR = 3
MAX_REPORTS_PER_DAY = 24
MAX_REPORT_BYTES = 256 * 1024

# `python worker\worker_test.py --old` restores the behaviour each check was
# written against, so it can be seen going red. A check that cannot fail is
# not evidence of anything.
OLD = "--old" in sys.argv

# What the old code fell back to when no ADMIN_TOKEN was set. NOT the real
# string: the real one is exactly what should never be written into a file in
# a public repository, and this check does not care what the value is - only
# that a constant in the source used to be accepted at all, and no longer is.
ADMIN_FALLBACK_WAS = "cp-OLD-CONSTANT-NO-LONGER-ACCEPTED"


class KV:
    """Workers KV, as far as this code can tell it apart: get, put, delete,
    and a list() that returns keys in LEXICOGRAPHIC order and stops at a
    limit. The ordering is the point - the old code took keys[0] of a
    limit:1 list and called it arbitrary."""

    def __init__(self):
        self.d = {}
        self.puts = 0

    def get(self, k):
        return self.d.get(k)

    def put(self, k, v, **kw):
        self.puts += 1
        self.d[k] = v

    def delete(self, k):
        self.d.pop(k, None)

    def list(self, prefix="", limit=1000, cursor=None):
        names = sorted(n for n in self.d if n.startswith(prefix))
        start = int(cursor or 0)
        page = names[start:start + limit]
        done = start + len(page) >= len(names)
        return {"keys": [{"name": n} for n in page],
                "list_complete": done,
                "cursor": None if done else str(start + len(page))}


def sha256hex(s):
    return hashlib.sha256(s.encode()).hexdigest()


def signature_of(code):
    import base64
    try:
        pad = code + "=" * (-len(code) % 4)
        blob = json.loads(base64.urlsafe_b64decode(pad.encode()).decode())
        sig = blob.get("sig")
        return sig if isinstance(sig, str) and sig else None
    except Exception:
        return None


class Desk:
    """The handlers, in the same shape as the .js."""

    def __init__(self, kv, admin_token=None):
        self.kv = kv
        self.ADMIN_TOKEN = admin_token

    # -- admin ------------------------------------------------------------
    def _admin_ok(self, given):
        if OLD:
            return given == (self.ADMIN_TOKEN or ADMIN_FALLBACK_WAS)
        return bool(self.ADMIN_TOKEN) and given == self.ADMIN_TOKEN

    def _admin_refusal(self):
        if not self.ADMIN_TOKEN and not OLD:
            return 503, {"error": "no admin password set"}
        return 401, {"error": "no"}

    def _count_prefix(self, prefix):
        if OLD:
            return len(self.kv.list(prefix=prefix)["keys"])
        total, cursor = 0, None
        while True:
            page = self.kv.list(prefix=prefix, cursor=cursor)
            total += len(page["keys"])
            if page["list_complete"]:
                return total
            cursor = page["cursor"]

    # -- POST /request ----------------------------------------------------
    def request(self, body, ip="1.1.1.1"):
        if not isinstance(body, dict):
            if OLD:
                raise TypeError("body is not an object")   # became a 500
            return 400, {"error": "Send the four answers as JSON."}
        name = str(body.get("name") or "").strip()
        email = str(body.get("email") or "").strip()
        phone = str(body.get("phone") or "").strip()
        project = str(body.get("project") or "").strip()
        if not (name and email and phone and project):
            return 400, {"error": "All four answers are needed."}

        seen = int(self.kv.get("rate:" + ip) or 0)
        if seen >= MAX_REQUESTS_PER_HOUR:
            return 429, {"error": "Too many requests from here."}
        self.kv.put("rate:" + ip, str(seen + 1))

        lic_id, code = self.pick_key()
        if not code:
            return 503, {"error": "No keys are in stock this minute."}

        self.commit(lic_id, code, body, ip)
        return 200, {"ok": True, "id": lic_id, "key": code}

    # The two halves of /request, kept apart so a test can interleave them -
    # which is the only way to see a read-then-write race at all.
    def pick_key(self):
        if OLD:
            # list(limit=1) then keys[0]: KV orders lexicographically, so
            # every caller took the SAME key.
            waiting = self.kv.list(prefix="pool:", limit=1)
            if not waiting["keys"]:
                return None, None
            pick = waiting["keys"][0]["name"]
            return pick[len("pool:"):], self.kv.get(pick)
        waiting = self.kv.list(prefix="pool:", limit=50)
        if not waiting["keys"]:
            return None, None
        for _ in range(3):
            pick = random.choice(waiting["keys"])["name"]
            candidate = pick[len("pool:"):]
            if self.kv.get("claim:" + candidate):
                continue
            value = self.kv.get(pick)
            if not value:
                continue
            return candidate, value
        return None, None

    def commit(self, lic_id, code, body, ip):
        now = 1000
        claim = {"id": lic_id, "name": str(body.get("name") or ""),
                 "email": str(body.get("email") or ""),
                 "phone": str(body.get("phone") or ""),
                 "project": str(body.get("project") or ""),
                 "issued_at": now, "ip": ip,
                 "machine": None, "activated_at": None}
        if not OLD:
            claim["sig_sha256"] = sha256hex(signature_of(code) or code)
        self.kv.put("claim:" + lic_id, json.dumps(claim))
        self.kv.put("req:%s:%s" % (ip, lic_id), json.dumps(claim))
        self.kv.delete("pool:" + lic_id)

    # -- POST /activate ---------------------------------------------------
    def activate(self, body):
        if not isinstance(body, dict):
            if OLD:
                raise TypeError("body is not an object")
            return 400, {"error": "bad request"}
        lic_id = str(body.get("id") or "").upper()
        machine = str(body.get("machine") or "").upper()
        sig = str(body.get("sig") or "") or signature_of(body.get("key") or "") or ""
        if not lic_id or not machine:
            return 400, {"error": "bad request"}
        raw = self.kv.get("claim:" + lic_id)
        if not raw:
            if OLD:
                # An unknown id used to be handed a licence invented on the
                # spot, and bound to whoever asked.
                claim = {"id": lic_id, "project": "(issued by hand)",
                         "machine": None, "activated_at": None}
                self.kv.put("claim:" + lic_id, json.dumps(claim))
                raw = self.kv.get("claim:" + lic_id)
            else:
                return 404, {"ok": False, "error": "no record of that key"}
        claim = json.loads(raw)
        if claim.get("sig_sha256"):
            if not sig:
                return 400, {"error": "bad request"}
            if sha256hex(sig) != claim["sig_sha256"]:
                return 403, {"ok": False, "error": "That key does not match."}
        if claim.get("machine") and claim["machine"] != machine:
            return 403, {"ok": False,
                         "error": "This license key is already in use on another computer."}
        if not claim.get("machine"):
            claim["machine"] = machine
            claim["activated_at"] = 2000
            self.kv.put("claim:" + lic_id, json.dumps(claim))
        return 200, {"ok": True, "machine": claim["machine"]}

    # -- POST /report -----------------------------------------------------
    def report(self, text):
        if OLD:
            # Anything, from anyone, at any size, at any id - and every
            # report in the same second landing on the same key.
            try:
                body = json.loads(text)
                lic_id = str((body or {}).get("id") or "").upper()
            except Exception:
                return 400, {"error": "bad request"}
            if not lic_id:
                return 400, {"error": "bad request"}
            self.kv.put("report:%s:%d" % (lic_id, 3000), json.dumps(body))
            return 200, {"ok": True}
        if len(text) > MAX_REPORT_BYTES:
            return 413, {"error": "That report is too big."}
        try:
            body = json.loads(text)
            if not isinstance(body, dict):
                raise ValueError
        except Exception:
            return 400, {"error": "bad request"}
        lic_id = str(body.get("id") or "").upper()
        machine = str(body.get("machine") or "").upper()
        if not lic_id or not machine:
            return 400, {"error": "bad request"}
        raw = self.kv.get("claim:" + lic_id)
        if not raw:
            return 404, {"error": "no such licence"}
        claim = json.loads(raw)
        if not claim.get("machine") or claim["machine"] != machine:
            return 403, {"error": "not this computer"}
        seen = int(self.kv.get("rrate:" + lic_id) or 0)
        if seen >= MAX_REPORTS_PER_DAY:
            return 429, {"error": "too many reports today"}
        self.kv.put("rrate:" + lic_id, str(seen + 1))
        stamp = "3000-" + uuid.uuid4().hex[:8]
        self.kv.put("report:%s:%s" % (lic_id, stamp), json.dumps(body))
        claim["last_report_at"] = 3000
        claim["reports"] = int(claim.get("reports") or 0) + 1
        self.kv.put("claim:" + lic_id, json.dumps(claim))
        return 200, {"ok": True}

    # -- admin ------------------------------------------------------------
    def stock(self, given, body):
        if not self._admin_ok(given):
            return self._admin_refusal()
        keys = body.get("keys") if isinstance(body, dict) else None
        if not isinstance(keys, list) or not keys:
            return 400, {"error": "No keys in that batch."}
        added = skipped = 0
        for k in keys:
            lic_id = str((k or {}).get("id") or "").upper()
            code = str((k or {}).get("code") or "").strip()
            if not lic_id or not code:
                skipped += 1
                continue
            if self.kv.get("claim:" + lic_id):
                skipped += 1
                continue
            self.kv.put("pool:" + lic_id, code)
            added += 1
        return 200, {"ok": True, "added": added, "skipped": skipped,
                     "keys_in_stock": self._count_prefix("pool:")}

    def admin_data(self, given):
        if not self._admin_ok(given):
            return self._admin_refusal()
        claims, cursor = [], None
        while True:
            page = self.kv.list(prefix="claim:", cursor=cursor)
            for k in page["keys"]:
                raw = self.kv.get(k["name"])
                if not raw:
                    continue
                c = json.loads(raw)
                if not OLD:
                    c.pop("sig_sha256", None)
                claims.append(c)
            if page["list_complete"]:
                break
            cursor = page["cursor"]
        return 200, {"ok": True, "keys_in_stock": self._count_prefix("pool:"),
                     "issued": len(claims), "claims": claims}

    def admin_reports(self, given):
        if OLD:
            return 404, {"error": "no such thing here"}   # the route did not exist
        if not self._admin_ok(given):
            return self._admin_refusal()
        tools, seen, counted, cursor = {}, {}, 0, None
        while True:
            page = self.kv.list(prefix="report:", cursor=cursor)
            for k in page["keys"]:
                raw = self.kv.get(k["name"])
                if not raw:
                    continue
                try:
                    doc = json.loads(raw)
                except Exception:
                    continue
                counted += 1
                if doc.get("id"):
                    seen[doc["id"]] = max(seen.get(doc["id"], 0),
                                          int(doc.get("at") or 0))
                used = doc.get("tools")
                if isinstance(used, dict):
                    for nm, n in used.items():
                        try:
                            n = float(n)
                        except Exception:
                            continue
                        if n < 0:
                            continue
                        tools[nm] = tools.get(nm, 0) + n
            if page["list_complete"]:
                break
            cursor = page["cursor"]
        return 200, {"ok": True, "tools": tools, "reports": counted,
                     "copies_reporting": len(seen)}


# ---- checks ---------------------------------------------------------------
RESULTS = []


def check(finding, name, passed, detail=""):
    RESULTS.append((finding, name, passed))
    print("  %s  %-8s %s%s" % ("PASS" if passed else "FAIL", finding, name,
                               ("  -- " + detail) if detail and not passed else ""))


def a_key(n):
    import base64
    blob = {"payload": {"id": "ID%09d" % n}, "sig": "sig-%d" % n}
    return base64.urlsafe_b64encode(
        json.dumps(blob, separators=(",", ":")).encode()).decode().rstrip("=")


ANSWERS = {"name": "A", "email": "a@b.co", "phone": "1234567890", "project": "P"}


def t_w01_two_visitors_one_minute():
    """W-01. Two people send the form at the same moment.

    Running the requests one after another proves nothing - this is a race,
    so both callers have to do their READ before either does its WRITE, which
    is what "the same minute" means at the desk.

    KV has no compare-and-swap, so the fix is a narrowing, not a cure, and the
    check says so: the old code collided on every single pair (list(limit=1)
    returns the same lexicographically-first key to everybody), the new one
    picks at random out of fifty and refuses to overwrite a claim that already
    exists. Anything under one pair in ten is the improvement working.
    """
    trials, collided = 60, 0
    for t in range(trials):
        kv = KV()
        d = Desk(kv, "pw")
        d.stock("pw", {"keys": [{"id": "ID%09d" % i, "code": a_key(i)}
                                for i in range(50)]})
        # Both read...
        first = d.pick_key()
        second = d.pick_key()
        # ...then both write.
        if first[0]:
            d.commit(first[0], first[1], dict(ANSWERS), "ip-a")
        if second[0]:
            d.commit(second[0], second[1], dict(ANSWERS), "ip-b")
        claims = d.admin_data("pw")[1]["claims"]
        if first[0] == second[0] or len(claims) < 2:
            collided += 1

    rate = collided / float(trials)
    check("W-01", "no double-issue", rate < 0.10,
          "%d of %d simultaneous pairs were handed the same key (%.0f%%)"
          % (collided, trials, rate * 100))


def t_w05_no_password_no_admin():
    """W-05 / DASH-2. With no ADMIN_TOKEN set there is no fallback to a
    constant in the repository - the admin routes simply refuse."""
    d = Desk(KV(), None)
    a = d.stock(ADMIN_FALLBACK_WAS, {"keys": [{"id": "X", "code": "y"}]})
    b = d.admin_data(ADMIN_FALLBACK_WAS)
    check("W-05", "no fallback", a[0] == 503 and b[0] == 503,
          "stock=%s data=%s" % (a[0], b[0]))


def t_w07_activate_needs_the_key():
    """W-07. An id alone does not bind a machine, and an id this desk never
    issued gets nothing at all."""
    kv = KV()
    d = Desk(kv, "pw")
    d.stock("pw", {"keys": [{"id": "ID000000001", "code": a_key(1)}]})
    _c, doc = d.request(dict(ANSWERS))
    lic_id = doc["id"]

    guessed = d.activate({"id": lic_id, "machine": "THIEF"})
    unknown = d.activate({"id": "NEVERISSUED", "machine": "THIEF", "sig": "x"})
    real = d.activate({"id": lic_id, "machine": "MINE", "key": doc["key"]})
    second = d.activate({"id": lic_id, "machine": "OTHER", "key": doc["key"]})
    check("W-07", "key proof",
          guessed[0] == 400 and unknown[0] == 404 and real[0] == 200
          and second[0] == 403,
          "guessed=%s unknown=%s real=%s second=%s"
          % (guessed[0], unknown[0], real[0], second[0]))


def t_w08_report_is_not_a_free_write():
    """W-08 / REP-05 / DASH-5. /report takes nothing from a stranger, nothing
    oversized, and not an unlimited number from one licence."""
    kv = KV()
    d = Desk(kv, "pw")
    d.stock("pw", {"keys": [{"id": "ID000000001", "code": a_key(1)}]})
    _c, doc = d.request(dict(ANSWERS))
    lic_id, key = doc["id"], doc["key"]

    stranger = d.report(json.dumps({"id": "SOMEONEELSE", "machine": "M"}))
    before_activation = d.report(json.dumps({"id": lic_id, "machine": "M"}))
    d.activate({"id": lic_id, "machine": "M", "key": key})
    wrong_pc = d.report(json.dumps({"id": lic_id, "machine": "NOTME"}))
    huge = d.report(json.dumps({"id": lic_id, "machine": "M",
                                "pad": "x" * (MAX_REPORT_BYTES + 10)}))
    good = d.report(json.dumps({"id": lic_id, "machine": "M",
                                "tools": {"rename": 2}, "at": 5}))
    for _ in range(MAX_REPORTS_PER_DAY + 5):
        last = d.report(json.dumps({"id": lic_id, "machine": "M"}))
    check("W-08", "report guarded",
          stranger[0] == 404 and before_activation[0] == 403
          and wrong_pc[0] == 403 and huge[0] == 413 and good[0] == 200
          and last[0] == 429,
          "stranger=%s pre=%s wrong=%s huge=%s good=%s looped=%s"
          % (stranger[0], before_activation[0], wrong_pc[0], huge[0],
             good[0], last[0]))


def t_w14_counting_past_a_thousand():
    """W-14 / DASH-10. The pool count follows the cursor instead of stopping
    at the 1,000 one list() page returns."""
    kv = KV()
    d = Desk(kv, "pw")
    d.stock("pw", {"keys": [{"id": "ID%09d" % i, "code": a_key(i)}
                            for i in range(1200)]})
    n = d.admin_data("pw")[1]["keys_in_stock"]
    check("W-14", "counts 1200", n == 1200, "reported %s" % n)


def t_w16_a_body_that_is_not_an_object():
    """W-16. `null`, a bare number, a list - each a 400, not a 500."""
    d = Desk(KV(), "pw")

    def status(fn, arg):
        # An exception out of a handler IS the 500 this check is about.
        try:
            return fn(arg)[0]
        except Exception:
            return 500

    outcomes = [status(d.request, None), status(d.request, 5),
                status(d.request, [1, 2]), status(d.activate, None),
                status(d.report, "null"), status(d.report, "[]")]
    check("W-16", "400 not 500", all(c == 400 for c in outcomes),
          "got %s" % outcomes)


def t_dash4_the_route_the_desk_calls():
    """DASH-4 / REP-04. GET /admin/reports exists and answers in the shape
    desk.js draws: {tools: {name: count}}."""
    kv = KV()
    d = Desk(kv, "pw")
    d.stock("pw", {"keys": [{"id": "ID000000001", "code": a_key(1)}]})
    _c, doc = d.request(dict(ANSWERS))
    d.activate({"id": doc["id"], "machine": "M", "key": doc["key"]})
    d.report(json.dumps({"id": doc["id"], "machine": "M", "at": 7,
                         "tools": {"rename": 3, "kmz": 1}}))
    d.report(json.dumps({"id": doc["id"], "machine": "M", "at": 8,
                         "tools": {"rename": 2}}))
    code, out = d.admin_reports("pw")
    check("DASH-4", "reports route",
          code == 200 and out["tools"] == {"rename": 5, "kmz": 1}
          and out["copies_reporting"] == 1,
          "code=%s out=%s" % (code, out))


def t_dash6_last_heard_from():
    """DASH-6. The roster can answer "is anyone still using it"."""
    kv = KV()
    d = Desk(kv, "pw")
    d.stock("pw", {"keys": [{"id": "ID000000001", "code": a_key(1)}]})
    _c, doc = d.request(dict(ANSWERS))
    d.activate({"id": doc["id"], "machine": "M", "key": doc["key"]})
    d.report(json.dumps({"id": doc["id"], "machine": "M", "at": 9}))
    claim = d.admin_data("pw")[1]["claims"][0]
    check("DASH-6", "last heard", bool(claim.get("last_report_at")),
          "claim carries %s" % sorted(claim))


def t_admin_data_keeps_the_proof_private():
    """The hash that proves key-possession is desk machinery. It must not
    travel to a browser."""
    kv = KV()
    d = Desk(kv, "pw")
    d.stock("pw", {"keys": [{"id": "ID000000001", "code": a_key(1)}]})
    d.request(dict(ANSWERS))
    claim = d.admin_data("pw")[1]["claims"][0]
    check("PRIV", "no hash out", "sig_sha256" not in claim,
          "claim carries %s" % sorted(claim))


def main():
    print("licence desk (a Python translation of cxpaper-license.js)")
    if OLD:
        print("--old: the behaviour BEFORE the fixes. Every check should go red.")
    print("")
    random.seed(7)
    t_w01_two_visitors_one_minute()
    t_w05_no_password_no_admin()
    t_w07_activate_needs_the_key()
    t_w08_report_is_not_a_free_write()
    t_w14_counting_past_a_thousand()
    t_w16_a_body_that_is_not_an_object()
    t_dash4_the_route_the_desk_calls()
    t_dash6_last_heard_from()
    t_admin_data_keeps_the_proof_private()

    bad = [r for r in RESULTS if not r[2]]
    print("")
    print("%d of %d checks passed." % (len(RESULTS) - len(bad), len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
