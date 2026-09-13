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
 *   report:<id>:<ts>
 *
 * The admin password is the constant below rather than a Cloudflare secret.
 * Setting a secret is another trip through a dashboard that has already cost
 * an evening, and a Worker's source is not public - workers.dev serves the
 * compiled worker, not this file. An ADMIN_TOKEN secret still wins if one is
 * ever set. To change the password, edit this one line: mint_batch.py reads
 * it straight out of this file, so there is nothing to keep in step.
 */

const SITE = "https://cxpaper.com";
const DOWNLOAD_PAGE = SITE + "/download/";

// A person asking for a licence does it once. Anything past this in an hour
// from one address is a machine working through the form.
const MAX_REQUESTS_PER_HOUR = 3;

// The password for /admin/stock and /admin/data. Not a licence secret: the
// worst it can do is add keys to the pool or read the customer list. The
// signing seed, which is the thing that actually matters, stays on Chris's PC.
const ADMIN_FALLBACK = "cp-OLD-CONSTANT-NO-LONGER-ACCEPTED";

const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };

function cors(request) {
  // The form is served from cxpaper.com and this runs somewhere else, so the
  // browser will not let it post without being told that is allowed. Only
  // that origin - this endpoint hands out licence keys and has no business
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

/* ---- POST /request ------------------------------------------------------ */

async function handleRequest(request, env) {
  let body;
  try {
    body = await request.json();
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

  // One key out of the batch. list() returns them in whatever order KV keeps
  // them in, which is fine - a key is a key. If the batch is empty the visitor
  // is told the truth rather than being handed a broken key.
  const waiting = await env.CP.list({ prefix: "pool:", limit: 1 });
  if (!waiting.keys.length) {
    return reply(request, 503, {
      error: "No keys are in stock this minute. Email chris@chrisputnam.me and you will get one today."
    });
  }

  const poolKey = waiting.keys[0].name;
  const id = poolKey.slice("pool:".length);
  const code = await env.CP.get(poolKey);
  if (!code) {
    return reply(request, 503, { error: "That key could not be read. Try once more." });
  }

  const now = Math.floor(Date.now() / 1000);
  const claim = {
    id, name, email, phone, project,
    issued_at: now,
    ip,
    machine: null,          // filled in by /activate, once, forever
    activated_at: null
  };

  // Claim BEFORE handing it over. A key given out but not written down is a
  // key with no owner and no way to switch it off.
  await env.CP.put("claim:" + id, JSON.stringify(claim));
  await env.CP.put("req:" + now + ":" + id, JSON.stringify(claim));
  await env.CP.delete(poolKey);

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
    body = await request.json();
  } catch (e) {
    return reply(request, 400, { error: "bad request" });
  }

  const id = clean(body.id, 40).toUpperCase();
  const machine = clean(body.machine, 40).toUpperCase();
  if (!id || !machine) return reply(request, 400, { error: "bad request" });

  const raw = await env.CP.get("claim:" + id);
  const now = Math.floor(Date.now() / 1000);

  // No record can mean a key Chris minted by hand in KeyMaker rather than one
  // from the batch. Those are real keys and must work, so the first machine
  // that presents one is recorded exactly as a batch key would be.
  const claim = raw ? JSON.parse(raw) : {
    id, name: "", email: "", phone: "", project: "(issued by hand)",
    issued_at: now, ip: null, machine: null, activated_at: null
  };

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
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return reply(request, 400, { error: "bad request" });
  }

  const id = clean(body.id, 40).toUpperCase();
  if (!id) return reply(request, 400, { error: "bad request" });

  const now = Math.floor(Date.now() / 1000);
  // Stored as sent. Crops arrive already encrypted by the program, to a key
  // only Chris's PC holds - this Worker cannot read them and is not supposed
  // to be able to. Reports expire after a year; the point is trends, not a
  // permanent record of somebody's working day.
  await env.CP.put("report:" + id + ":" + now, JSON.stringify(body),
                   { expirationTtl: 31536000 });

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
  const given = request.headers.get("X-CP-Admin") || "";
  if (given !== (env.ADMIN_TOKEN || ADMIN_FALLBACK)) {
    return reply(request, 401, { error: "no" });
  }

  let body;
  try {
    body = await request.json();
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

  const pool = await env.CP.list({ prefix: "pool:" });
  return reply(request, 200, {
    ok: true, added, skipped, keys_in_stock: pool.keys.length
  });
}

/* ---- GET /admin/data ---------------------------------------------------- */

async function handleAdminData(request, env) {
  const given = request.headers.get("X-CP-Admin") || "";
  if (given !== (env.ADMIN_TOKEN || ADMIN_FALLBACK)) {
    return reply(request, 401, { error: "no" });
  }

  const claims = [];
  let cursor;
  do {
    const page = await env.CP.list({ prefix: "claim:", cursor });
    for (const k of page.keys) {
      const raw = await env.CP.get(k.name);
      if (raw) claims.push(JSON.parse(raw));
    }
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);

  const pool = await env.CP.list({ prefix: "pool:" });

  return reply(request, 200, {
    ok: true,
    keys_in_stock: pool.keys.length,
    issued: claims.length,
    activated: claims.filter(c => c.machine).length,
    claims: claims.sort((a, b) => b.issued_at - a.issued_at)
  });
}

/* ---- the door ----------------------------------------------------------- */

export default {
  async fetch(request, env) {
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

    if (request.method === "GET" && path === "/") {
      return reply(request, 200, { ok: true, service: "cxpaper license desk" });
    }

    return reply(request, 404, { error: "no such thing here" });
  }
};
