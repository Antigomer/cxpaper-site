/* cxpaper.com license desk - a Cloudflare Worker.
 *
 * The website is files on GitHub Pages and nothing else: it can show a form
 * but cannot receive one. This is the only piece that runs. It does four
 * jobs, and deliberately no more than four:
 *
 *   POST /request    a visitor's four answers -> one key from the batch,
 *                    returned to the page and recorded here.
 *   POST /activate   the program, on first run, saying which computer it is.
 *                    THIS is what makes "locks to one computer" true. The
 *                    bind file inside the program is local to each install,
 *                    so a forwarded key opened in a fresh folder on a second
 *                    machine used to sail straight through. Now the first
 *                    machine to activate a key is the only machine that can.
 *   POST /report     what the program has been doing, and encrypted crops.
 *   POST /admin/stock a batch of freshly minted keys, from Chris's PC.
 *   GET  /admin/data  everything above, for the private dashboard.
 *   GET  /admin/reports the usage totals, for the same dashboard.
 *
 * WHAT IS NOT HERE, ON PURPOSE: the signing seed. Keys are minted on Chris's
 * PC in KeyMaker and uploaded as a finished batch. If this Worker is ever
 * broken into, the worst case is a handful of unissued keys, each revocable
 * in one step. Had the seed been up here, a break-in would mean replacing
 * every key ever issued and re-licensing every customer.
 *
 * Storage is one KV namespace, bound as CP, with prefixed keys:
 *   pool:<id>     an unissued key code, waiting
 *   claim:<id>    who got it, and which computer claimed it
 *   req:<ts>:<id> the request log, newest sorting last
 *   rate:<ip>     a short-lived counter
 *   report:<id>:<ts>-<rand>
 *
 * THE ADMIN PASSWORD IS NOT IN THIS FILE. It is the ADMIN_TOKEN secret, which
 * deploy_worker.py creates and stores in C:\_CLAUDE\cp-admin-token.txt. That
 * one file is the only copy: the dashboard is opened with it and mint_batch.py
 * reads it to stock a batch. It used to be a constant here, which meant the
 * password for the customer list was sitting in the public repository that
 * publishes cxpaper.com, and meant deploying the Worker (which sets a random
 * secret) silently locked Chris out of his own desk. If ADMIN_TOKEN is not
 * set, the admin routes answer 503 rather than falling back to anything.
 */

const SITE = "https://cxpaper.com";
const DOWNLOAD_PAGE = SITE + "/download/";

// A person asking for a license does it once. Anything past this in an hour
// from one address is a machine working through the form.
const MAX_REQUESTS_PER_HOUR = 3;

// A running copy reports its usage once a day. More than this from one license
// is a loop, not a working day, and the store is not there to absorb it.
const MAX_REPORTS_PER_DAY = 24;

// Big enough for a day of counters and a few encrypted crops, small enough
// that nobody can post the store full. KV's own ceiling is 25 MB per value.
const MAX_REPORT_BYTES = 256 * 1024;

const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };

function cors(request) {
  // The form is served from cxpaper.com and this runs somewhere else, so the
  // browser will not let it post without being told that is allowed. Only
  // that origin - this endpoint hands out license keys and has no business
  // answering a form on somebody else's site.
  const origin = request.headers.get("Origin") || "";
  const allowed = origin === SITE || origin === "https://www.cxpaper.com";
  return {
    "Access-Control-Allow-Origin": allowed ? origin : SITE,
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-CP-Admin",
    "Access-Control-Max-Age": "86400"
  };
}

function reply(request, status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...JSON_HEADERS, ...cors(request) }
  });
}

function clean(v, max) {
  return String(v == null ? "" : v).replace(/\s+/g, " ").trim().slice(0, max || 200);
}

function looksLikeEmail(v) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v);
}

function digitsIn(v) {
  return (String(v).match(/\d/g) || []).length;
}

async function overRate(env, ip) {
  const key = "rate:" + ip;
  const seen = parseInt((await env.CP.get(key)) || "0", 10);
  if (seen >= MAX_REQUESTS_PER_HOUR) return true;
  await env.CP.put(key, String(seen + 1), { expirationTtl: 3600 });
  return false;
}

async function overReportRate(env, id) {
  const key = "rrate:" + id;
  const seen = parseInt((await env.CP.get(key)) || "0", 10);
  if (seen >= MAX_REPORTS_PER_DAY) return true;
  await env.CP.put(key, String(seen + 1), { expirationTtl: 86400 });
  return false;
}

/* A body that parses but is not an object - `null`, a bare number, a string -
 * used to reach `body.name` and throw, which Cloudflare turns into a 500. The
 * handler was already trying to say 400; this lets it. */
async function readObject(request) {
  const body = await request.json();
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("not an object");
  return body;
}

/* list() stops at 1,000 keys and says so in list_complete. Counting keys.length
 * without following the cursor reports "1000 in stock" forever once the pool
 * passes a thousand, and reports it to the one screen Chris uses to decide
 * whether to mint more. */
async function countPrefix(env, prefix) {
  let total = 0, cursor;
  do {
    const page = await env.CP.list({ prefix, cursor });
    total += page.keys.length;
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);
  return total;
}

/* A license key is base64url over {payload, sig}. The signature inside it is
 * the one part the program can hand back byte for byte: it reads it straight
 * out of license.igl and never re-encodes it, so hashing THAT rather than the
 * whole key means the two sides cannot disagree over JSON spacing or field
 * order. Returns null for anything that is not a key this desk can read. */
function signatureOf(code) {
  try {
    let b64 = String(code).replace(/-/g, "+").replace(/_/g, "/");
    while (b64.length % 4) b64 += "=";
    const blob = JSON.parse(atob(b64));
    const sig = blob && blob.sig;
    if (typeof sig === "string" && sig) return sig;
  } catch (e) { /* not a key, or not one we can read */ }
  return null;
}

/* The claim records what a key's signature hashes to, never the key. That is
 * enough to check that whoever calls /activate is holding the key, and not
 * enough to reconstruct it if this store is ever read by someone else. */
async function sha256hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
}

/* One password, and it has to be set. There is no constant to fall back to:
 * a fallback in this file is a fallback in the repository. */
function adminOk(request, env) {
  const given = request.headers.get("X-CP-Admin") || "";
  return Boolean(env.ADMIN_TOKEN) && given === env.ADMIN_TOKEN;
}

function adminRefusal(request, env) {
  if (!env.ADMIN_TOKEN) {
    return reply(request, 503, {
      error: "This license desk has no admin password set. Run deploy_worker.py."
    });
  }
  return reply(request, 401, { error: "no" });
}

/* ---- POST /request ------------------------------------------------------ */

async function handleRequest(request, env) {
  let body;
  try {
    body = await readObject(request);
  } catch (e) {
    return reply(request, 400, { error: "Send the four answers as JSON." });
  }

  const name = clean(body.name, 120);
  const email = clean(body.email, 160);
  const phone = clean(body.phone, 40);
  const project = clean(body.project, 160);

  if (!name || !email || !phone || !project) {
    return reply(request, 400, { error: "All four answers are needed." });
  }
  if (!looksLikeEmail(email)) {
    return reply(request, 400, { error: "That email address is missing something." });
  }
  if (digitsIn(phone) < 10) {
    return reply(request, 400, { error: "That looks short for a phone number." });
  }

  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  if (await overRate(env, ip)) {
    // Deliberately not "you have had too many". Somebody who genuinely needs a
    // second key should write, not be told to wait an hour and guess why.
    return reply(request, 429, {
      error: "Too many requests from here. Email chris@chrisputnam.me and it will be sorted out by hand."
    });
  }

  // One key out of the batch.
  //
  // This used to list with limit:1 and take keys[0]. KV returns keys in
  // lexicographic order, so that is not "whatever order KV keeps them in" -
  // it is the SAME key for every caller, every time. Two people sending the
  // form in the same minute both got it, the second claim:<id> overwrote the
  // first, and the customer it overwrote vanished from the roster entirely:
  // a key sold, and no record that Chris had ever sold it.
  //
  // So: take a page of candidates, pick one at random, and refuse to write
  // over a claim that already exists. Honest limits - KV has no
  // compare-and-swap, so this narrows the window, it does not close it. Two
  // requests in the same instant can still both read an unclaimed key; the
  // check below means the loser is told to send the form again instead of
  // quietly erasing the winner. Closing it properly needs a Durable Object,
  // which is a bigger change than this file.
  const waiting = await env.CP.list({ prefix: "pool:", limit: 50 });
  if (!waiting.keys.length) {
    return reply(request, 503, {
      error: "No keys are in stock this minute. Email chris@chrisputnam.me and you will get one today."
    });
  }

  const now = Math.floor(Date.now() / 1000);
  let id = null, code = null;

  for (let tries = 0; tries < 3 && !code; tries++) {
    const pick = waiting.keys[Math.floor(Math.random() * waiting.keys.length)];
    const candidate = pick.name.slice("pool:".length);
    if (await env.CP.get("claim:" + candidate)) continue;   // gone already
    const value = await env.CP.get(pick.name);
    if (!value) continue;                                    // taken mid-read
    id = candidate;
    code = value;
  }

  if (!code) {
    return reply(request, 503, {
      error: "That key was taken while you were sending. Send the form once more."
    });
  }

  const claim = {
    id, name, email, phone, project,
    issued_at: now,
    ip,
    machine: null,          // filled in by /activate, once, forever
    activated_at: null,
    // Not the key. Enough to prove a caller is holding the key, and useless
    // to anybody who reads this store - see /activate.
    sig_sha256: await sha256hex(signatureOf(code) || code)
  };

  // Claim BEFORE handing it over. A key given out but not written down is a
  // key with no owner and no way to switch it off.
  await env.CP.put("claim:" + id, JSON.stringify(claim));
  await env.CP.put("req:" + now + ":" + id, JSON.stringify(claim));
  await env.CP.delete("pool:" + id);

  const left = await env.CP.list({ prefix: "pool:", limit: 25 });
  const low = left.keys.length < 20;

  return reply(request, 200, {
    ok: true,
    id,
    key: code,
    download: DOWNLOAD_PAGE,
    pool_low: low            // the dashboard turns this into "top the batch up"
  });
}

/* ---- POST /activate ----------------------------------------------------- */

async function handleActivate(request, env) {
  let body;
  try {
    body = await readObject(request);
  } catch (e) {
    return reply(request, 400, { error: "bad request" });
  }

  const id = clean(body.id, 40).toUpperCase();
  const machine = clean(body.machine, 40).toUpperCase();
  // The program sends the signature out of its license file. A whole key is
  // accepted too, for anything that has the key but not the file.
  const sig = String(body.sig == null ? "" : body.sig).trim() ||
              signatureOf(body.key) || "";
  if (!id || !machine) return reply(request, 400, { error: "bad request" });

  const raw = await env.CP.get("claim:" + id);
  const now = Math.floor(Date.now() / 1000);

  // An id this desk has never issued gets nothing. This used to invent a
  // claim on the spot for any unknown id, which meant anyone who guessed or
  // typed an id could have it bound to their machine - and then the real
  // customer, arriving later with the real key, was told their key was
  // already in use on another computer. Keys minted by hand in KeyMaker go
  // into the pool through /admin/stock like every other key, so a key that
  // is genuinely Chris's always has a claim here.
  if (!raw) {
    return reply(request, 404, {
      ok: false,
      error: "This license desk has no record of that key. Email chris@chrisputnam.me."
    });
  }

  const claim = JSON.parse(raw);

  // Proof that the caller holds the key, not just its id. The id travels in
  // the open - it is printed on the dashboard and in the reply to /request -
  // so binding on the id alone let anybody who saw one burn the customer's
  // single activation. Claims written before this field existed have nothing
  // to check against; they keep the old first-come behaviour rather than
  // locking out customers who are already running.
  if (claim.sig_sha256) {
    if (!sig) return reply(request, 400, { error: "bad request" });
    if (await sha256hex(sig) !== claim.sig_sha256) {
      return reply(request, 403, { ok: false, error: "That key does not match." });
    }
  }

  if (claim.machine && claim.machine !== machine) {
    return reply(request, 403, {
      ok: false,
      error: "This license key is already in use on another computer. Ask for a key for this machine."
    });
  }

  if (!claim.machine) {
    claim.machine = machine;
    claim.activated_at = now;
    await env.CP.put("claim:" + id, JSON.stringify(claim));
  }

  return reply(request, 200, { ok: true, machine: claim.machine });
}

/* ---- POST /report ------------------------------------------------------- */

async function handleReport(request, env) {
  // Read as text first, so an enormous body is refused before it is parsed
  // rather than after. This route used to accept anything from anyone at any
  // size: every usage chart on the dashboard was forgeable by hand, and a
  // loop posting junk could burn the KV day-quota, which would take /request
  // down with it - the form would stop handing out keys because somebody was
  // spamming a route that has nothing to do with it.
  let text;
  try {
    text = await request.text();
  } catch (e) {
    return reply(request, 400, { error: "bad request" });
  }
  if (text.length > MAX_REPORT_BYTES) {
    return reply(request, 413, { error: "That report is too big." });
  }

  let body;
  try {
    body = JSON.parse(text);
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("not an object");
  } catch (e) {
    return reply(request, 400, { error: "bad request" });
  }

  const id = clean(body.id, 40).toUpperCase();
  const machine = clean(body.machine, 40).toUpperCase();
  if (!id || !machine) return reply(request, 400, { error: "bad request" });

  // Only a license this desk issued, and only from the computer it was bound
  // to. Anything else is somebody else's traffic and does not belong in
  // Chris's numbers.
  const raw = await env.CP.get("claim:" + id);
  if (!raw) return reply(request, 404, { error: "no such license" });
  const claim = JSON.parse(raw);
  if (!claim.machine || claim.machine !== machine) {
    return reply(request, 403, { error: "not this computer" });
  }

  if (await overReportRate(env, id)) {
    return reply(request, 429, { error: "too many reports today" });
  }

  const now = Math.floor(Date.now() / 1000);

  // Stored as sent. Crops arrive already encrypted by the program, to a key
  // only Chris's PC holds - this Worker cannot read them and is not supposed
  // to be able to. Reports expire after a year; the point is trends, not a
  // permanent record of somebody's working day.
  //
  // The random tail matters: two reports in the same second used to land on
  // the same key and the second quietly replaced the first.
  const stamp = now + "-" + crypto.randomUUID().slice(0, 8);
  await env.CP.put("report:" + id + ":" + stamp, JSON.stringify(body),
                   { expirationTtl: 31536000 });

  // The check-in used to leave no trace anywhere Chris could read, so "is
  // anyone still using it" had no answer even in principle. Now the roster
  // carries the date of the last time each copy spoke.
  if (claim.last_report_at !== now) {
    claim.last_report_at = now;
    claim.reports = (claim.reports || 0) + 1;
    await env.CP.put("claim:" + id, JSON.stringify(claim));
  }

  return reply(request, 200, { ok: true });
}

/* ---- POST /admin/stock -------------------------------------------------- */

async function handleStock(request, env) {
  // Chris's PC mints keys and posts the batch here. It goes through the
  // Worker rather than Cloudflare's own API on purpose: that API needs a
  // token, and getting one issued turned into an evening. This needs only
  // the address and the dashboard password, both of which he already has.
  // The signing seed still never leaves his machine - what arrives here is
  // finished, signed keys.
  if (!adminOk(request, env)) return adminRefusal(request, env);

  let body;
  try {
    body = await readObject(request);
  } catch (e) {
    return reply(request, 400, { error: "Send {keys: [{id, code}, ...]}." });
  }

  const keys = Array.isArray(body.keys) ? body.keys : [];
  if (!keys.length) return reply(request, 400, { error: "No keys in that batch." });

  let added = 0, skipped = 0;
  for (const k of keys) {
    const id = clean(k && k.id, 40).toUpperCase();
    const code = String((k && k.code) || "").trim();
    if (!id || !code) { skipped++; continue; }
    // Never overwrite a key that has already gone out to somebody.
    if (await env.CP.get("claim:" + id)) { skipped++; continue; }
    await env.CP.put("pool:" + id, code);
    added++;
  }

  return reply(request, 200, {
    ok: true, added, skipped, keys_in_stock: await countPrefix(env, "pool:")
  });
}

/* ---- GET /admin/data ---------------------------------------------------- */

async function handleAdminData(request, env) {
  if (!adminOk(request, env)) return adminRefusal(request, env);

  const claims = [];
  let cursor;
  do {
    const page = await env.CP.list({ prefix: "claim:", cursor });
    for (const k of page.keys) {
      const raw = await env.CP.get(k.name);
      if (!raw) continue;
      const claim = JSON.parse(raw);
      // The hash is proof-of-key machinery, not something the dashboard has
      // any use for. It does not need to travel to a browser.
      delete claim.sig_sha256;
      claims.push(claim);
    }
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);

  return reply(request, 200, {
    ok: true,
    keys_in_stock: await countPrefix(env, "pool:"),
    issued: claims.length,
    activated: claims.filter(c => c.machine).length,
    claims: claims.sort((a, b) => b.issued_at - a.issued_at)
  });
}

/* ---- GET /admin/reports ------------------------------------------------- */

async function handleAdminReports(request, env) {
  // The dashboard has always called this. Until now there was no such route:
  // reports went in and nothing could read them back out, so the usage chart
  // was permanently hidden and the desk's own advice said "no copy has
  // reported its usage yet" no matter how many had.
  if (!adminOk(request, env)) return adminRefusal(request, env);

  const tools = {};
  const seen = {};
  let counted = 0, cursor;
  do {
    const page = await env.CP.list({ prefix: "report:", cursor });
    for (const k of page.keys) {
      const raw = await env.CP.get(k.name);
      if (!raw) continue;
      let doc;
      try { doc = JSON.parse(raw); } catch (e) { continue; }
      counted++;
      const id = String(doc.id || "");
      if (id) seen[id] = Math.max(seen[id] || 0, Number(doc.at) || 0);
      const used = doc.tools;
      if (used && typeof used === "object" && !Array.isArray(used)) {
        for (const name of Object.keys(used)) {
          const n = Number(used[name]);
          if (!Number.isFinite(n) || n < 0) continue;
          tools[clean(name, 60)] = (tools[clean(name, 60)] || 0) + n;
        }
      }
    }
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);

  return reply(request, 200, {
    ok: true,
    tools,
    reports: counted,
    copies_reporting: Object.keys(seen).length
  });
}

/* ---- the door ----------------------------------------------------------- */

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      const path = url.pathname.replace(/\/+$/, "") || "/";

      if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: cors(request) });
      }

      if (request.method === "POST" && path === "/request") return handleRequest(request, env);
      if (request.method === "POST" && path === "/activate") return handleActivate(request, env);
      if (request.method === "POST" && path === "/report") return handleReport(request, env);
      if (request.method === "POST" && path === "/admin/stock") return handleStock(request, env);
      if (request.method === "GET" && path === "/admin/data") return handleAdminData(request, env);
      if (request.method === "GET" && path === "/admin/reports") return handleAdminReports(request, env);

      if (request.method === "GET" && path === "/") {
        return reply(request, 200, { ok: true, service: "cxpaper license desk" });
      }

      return reply(request, 404, { error: "no such thing here" });
    } catch (e) {
      // Anything unforeseen still leaves the caller with a sentence and the
      // CORS headers, rather than Cloudflare's bare 500 - which the form
      // reads as a network failure and reports as "could not be reached".
      return reply(request, 500, {
        error: "The license desk hit a problem. Email chris@chrisputnam.me."
      });
    }
  }
};
