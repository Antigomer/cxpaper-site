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
// The licence page carries the file, the hash and the first-run steps.
// There is no separate download page as of 2026-09-16.
const DOWNLOAD_PAGE = SITE + "/license/";

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

/* ---- the DIR relay ------------------------------------------------------
 *
 * POST /v1/dir/detect     one field photo -> which classes are in it
 * POST /v1/dir/validate   a finished DIR slot -> findings about its caption
 *
 * WHY IT IS HERE AND NOT SOMEWHERE ELSE. Construction Paper's whole point is
 * that a customer needs no API key: the relay holds the one key, checks the
 * licence, meters, and forwards. Until 2026-09-21 the relay did not exist -
 * the site README said so under "Deliberately not built" - so `make_backend`
 * fell through to the Anthropic SDK, which the exe does not carry. Vision has
 * therefore never worked for anybody. Chris: "construction paper doesn't use
 * the API. That's the whole point."
 *
 * NOTHING ABOUT A PHOTOGRAPH IS STORED. The image arrives, goes to the model,
 * and the reply goes back. What is kept is a per-licence counter and nothing
 * else - no image, no station, no caption, no folder name.
 *
 * NO KEY, NO SERVICE, NO FALLBACK. If ANTHROPIC_API_KEY is unset these routes
 * answer 503, exactly as the admin routes do without ADMIN_TOKEN. A fallback
 * constant in this file would be an API key in a public repository.
 */

const DIR_MAX_DETECTS_PER_DAY = 400;   // ~12 working days of his 32-photo days
const DIR_MAX_BODY_BYTES = 12 * 1024 * 1024;
const DIR_MAX_EXAMPLES = 8;
const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION = "2023-06-01";
const ANTHROPIC_BETA = "server-side-fallback-2026-07-01";
const DIR_MODELS = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"];
const DIR_MEDIA = ["image/jpeg", "image/png", "image/webp", "image/gif"];

/* THE PROMPT IS BUILT HERE, AND THAT IS A LIABILITY THIS FILE HAS TO CARRY.
 *
 * The relay builds the prompt so it controls what it is paying for - a
 * caller-supplied prompt would be a blank cheque. The cost is that these
 * words now exist twice: here, and in `dir_writer.vision.detect.prompt_text`
 * on the direct path. Two copies of a rule is how they come to disagree.
 *
 * So `dir_writer_test` reads THIS FILE and fails if either block below stops
 * matching what prompt_text produces. Change one and the gate makes you
 * change the other. Do not reword either in isolation. */
const DIR_PROMPT_HEAD =
  "You are looking at one field photo from a pipeline construction " +
  "right-of-way, taken by the environmental inspector. List which of the " +
  "following object classes are visibly present. Report only what is in " +
  "the picture; if a class is not visible, leave it out. Confidence is " +
  "your own estimate from 0 to 1.";

const DIR_PROMPT_TAIL = [
  "ONE ENTRY PER OBJECT, not one entry per kind. Two survey stakes standing in the frame are TWO entries. This matters: on a pipeline right-of-way a stake stands on EACH side of the corridor, and the pair is what defines the boundary - reporting one is half an answer.",
  "For every entry give `where`: `left`, `top`, `right`, `bottom` for a box round that one object, and `ground_x`, `ground_y` for the point where it MEETS THE GROUND. All six are fractions of the picture's width and height, measured from the top left corner.",
  "The ground point is the useful one, so take care over it. For a survey stake it is the BOTTOM of the lath, where the wood enters the soil - not the coloured flagging at the top. The bottom is the surveyed position; the top merely leans.",
  "`top_x` and `top_y` are the OTHER end of the object - for a survey stake the tip of the lath, where the flagging is tied. That point and the ground point together are the stake's AXIS, and the axis is what says whether it is standing or lying down. Give both even when the object is not a stake: use the highest point of it.",
  "A SURVEY STAKE MUST BE STANDING. A lath lying flat on the ground has been knocked down, and a stake that is down marks nothing at all - its position is meaningless, because it is no longer where the surveyor put it. Do NOT report a fallen lath as a survey_stake, and never stand one back up by giving it a ground point as though it were upright. If the only lath in the picture is lying down, then there is no survey stake in that picture.",
  "Where the flagging colour is visible, say so in `evidence`. Colour separates a boundary stake from a centreline stake on any one job, though the colours themselves differ from job to job.",
  "Then give `scene`: one plain sentence saying what the photo shows, and `activity`: the single best word for the work in progress from this list: excavation, tie_in, lower_in, backfill, topsoil, restoration, riprap, ecd, dewatering, wet, mats, none."
];

function dirPrompt(classes) {
  const lines = [DIR_PROMPT_HEAD, "", "Classes:"];
  for (const c of classes) {
    // `label` is sent from build 14 on. Older copies send id and cues only,
    // and for those the id stands in - a prompt slightly thinner than the
    // direct path's, which is better than refusing a customer's request.
    lines.push("- " + c.id + " (" + (c.label || c.id) + "): " + (c.cues || ""));
  }
  for (const p of DIR_PROMPT_TAIL) lines.push("", p);
  return lines.join("\n");
}

function dirSchema(classIds) {
  const frac = (d) => (d ? { type: "number", description: d } : { type: "number" });
  return {
    type: "object",
    properties: {
      detections: {
        type: "array",
        items: {
          type: "object",
          properties: {
            class: { type: "string", enum: classIds },
            confidence: { type: "number", description: "how sure you are, from 0.0 to 1.0" },
            evidence: { type: "string" },
            where: {
              type: "object",
              description: "where this one object sits in the picture, as fractions of the width and height measured from the top left corner",
              properties: {
                left: frac(), top: frac(), right: frac(), bottom: frac(),
                ground_x: frac("across the picture, where this object meets the ground"),
                ground_y: frac("down the picture, where this object meets the ground"),
                top_x: frac("across the picture, the far end or top of this object - for a survey stake, the tip of the lath"),
                top_y: frac("down the picture, the far end or top of this object")
              },
              required: ["left", "top", "right", "bottom", "ground_x", "ground_y", "top_x", "top_y"],
              additionalProperties: false
            }
          },
          required: ["class", "confidence", "evidence", "where"],
          additionalProperties: false
        }
      },
      scene: { type: "string" },
      activity: { type: "string" }
    },
    required: ["detections", "scene", "activity"],
    additionalProperties: false
  };
}

const DIR_FINDINGS_SCHEMA = {
  type: "object",
  properties: {
    findings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          slot: { type: "string" },
          level: { type: "string", enum: ["error", "warn", "confirm", "ok"] },
          message: { type: "string" },
          suggested_caption: { type: "string" }
        },
        required: ["slot", "level", "message", "suggested_caption"],
        additionalProperties: false
      }
    }
  },
  required: ["findings"],
  additionalProperties: false
};

/* The licence has to be one this desk issued. Same rule as /activate: an id
 * nobody has claimed gets nothing, because the id travels in the open. */
async function dirLicenceOk(env, id) {
  if (!id) return false;
  return !!(await env.CP.get("claim:" + id));
}

async function overDirRate(env, id) {
  const key = "drate:" + id + ":" + new Date().toISOString().slice(0, 10);
  const seen = parseInt((await env.CP.get(key)) || "0", 10);
  if (seen >= DIR_MAX_DETECTS_PER_DAY) return true;
  await env.CP.put(key, String(seen + 1), { expirationTtl: 172800 });
  return false;
}

function dirImageBlock(media_type, data) {
  return { type: "image", source: { type: "base64", media_type, data } };
}

/* Ask the model, and hand back parsed JSON or null. Anthropic's own words
 * travel out on a failure: a relay that says "upstream error" and swallows
 * the reason makes every fault look the same from the field. */
async function askAnthropic(env, model, content, schema, effort, maxTokens) {
  const res = await fetch(ANTHROPIC_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": ANTHROPIC_VERSION,
      "anthropic-beta": ANTHROPIC_BETA
    },
    body: JSON.stringify({
      model,
      max_tokens: maxTokens,
      fallbacks: "default",
      output_config: { effort, format: { type: "json_schema", schema } },
      messages: [{ role: "user", content }]
    })
  });
  const text = await res.text();
  if (!res.ok) {
    let said = "HTTP " + res.status;
    try {
      const doc = JSON.parse(text);
      if (doc && doc.error && doc.error.message) said = doc.error.message;
    } catch (e) { /* the status is all there is */ }
    return { error: said, status: res.status };
  }
  let doc;
  try { doc = JSON.parse(text); } catch (e) { return { error: "upstream sent no JSON", status: 502 }; }
  if (doc.stop_reason === "refusal") return { value: null };
  const block = (doc.content || []).find((b) => b.type === "text");
  if (!block) return { value: null };
  try { return { value: JSON.parse(block.text) }; } catch (e) { return { value: null }; }
}

async function handleDirDetect(request, env) {
  if (!env.ANTHROPIC_API_KEY) {
    return reply(request, 503, { error: "The vision relay is not configured yet." });
  }
  const id = clean(request.headers.get("X-CP-License") || "", 40).toUpperCase();
  if (!(await dirLicenceOk(env, id))) {
    return reply(request, 403, { error: "This license desk has no record of that key." });
  }
  if (await overDirRate(env, id)) {
    return reply(request, 429, { error: "Daily photo limit reached for this license." });
  }

  let body;
  try { body = await readObject(request); }
  catch (e) { return reply(request, 400, { error: "bad request" }); }

  const img = body.image || {};
  if (!img.data || DIR_MEDIA.indexOf(img.media_type) < 0) {
    return reply(request, 400, { error: "bad image" });
  }
  if (img.data.length > DIR_MAX_BODY_BYTES) {
    return reply(request, 413, { error: "image too large" });
  }
  const classes = Array.isArray(body.classes) ? body.classes.filter((c) => c && c.id) : [];
  if (!classes.length) return reply(request, 400, { error: "no classes" });
  const model = DIR_MODELS.indexOf(body.model) >= 0 ? body.model : DIR_MODELS[0];

  /* THE ORDER IS THE WHOLE THING, AND GETTING IT HALF RIGHT IS WORSE THAN
   * NOT DOING IT. Marks give a position; a position is a fraction; a
   * fraction means nothing until the model is told which photograph it is a
   * fraction OF. Measured 2026-09-20 on the direct path: four marks with the
   * frame named only in words scored 34 of 48, against 47 of 48 with no
   * marks at all - every coordinate came back at about 0.765 of true,
   * because the examples and the target are different pixel sizes. So:
   * examples first, each caption then its picture, then `frame`, then the
   * photograph being asked about. Reading `marks` and skipping `frame` is
   * the 34-of-48 configuration. */
  const content = [{ type: "text", text: dirPrompt(classes) }];
  const examples = Array.isArray(body.examples) ? body.examples.slice(0, DIR_MAX_EXAMPLES) : [];
  for (let i = 0; i < examples.length; i++) {
    const ex = examples[i] || {};
    if (!ex.data || DIR_MEDIA.indexOf(ex.media_type) < 0) continue;
    const marks = Array.isArray(ex.marks) ? ex.marks : [];
    const text = marks.length
      ? "Example " + (i + 1) + " - the inspector MARKED these in the next photo, and he is the authority: " + marks.join("; ")
      : "Example " + (i + 1) + " - the inspector confirmed these objects in the next photo: " +
        ((ex.classes || []).join(", ") || "none") + ". (" + (ex.note || "") + ")";
    content.push({ type: "text", text });
    content.push(dirImageBlock(ex.media_type, ex.data));
  }
  if (content.length > 1 && body.frame) {
    content.push({ type: "text", text: String(body.frame) });
  }
  content.push(dirImageBlock(img.media_type, img.data));

  const out = await askAnthropic(
    env, model, content, dirSchema(classes.map((c) => c.id)), "medium", 4000);
  if (out.error) return reply(request, 502, { error: out.error });
  return reply(request, 200, out.value || {
    detections: [], scene: "", activity: "none", error: "no usable reply"
  });
}

async function handleDirValidate(request, env) {
  if (!env.ANTHROPIC_API_KEY) {
    return reply(request, 503, { error: "The vision relay is not configured yet." });
  }
  const id = clean(request.headers.get("X-CP-License") || "", 40).toUpperCase();
  if (!(await dirLicenceOk(env, id))) {
    return reply(request, 403, { error: "This license desk has no record of that key." });
  }
  if (await overDirRate(env, id)) {
    return reply(request, 429, { error: "Daily limit reached for this license." });
  }

  let body;
  try { body = await readObject(request); }
  catch (e) { return reply(request, 400, { error: "bad request" }); }

  const img = body.image || {};
  const model = DIR_MODELS.indexOf(body.model) >= 0 ? body.model : DIR_MODELS[0];
  const content = [];
  if (img.data && DIR_MEDIA.indexOf(img.media_type) >= 0) {
    content.push(dirImageBlock(img.media_type, img.data));
  }
  // The client composes this sentence; the relay does not second-guess a
  // caption check it cannot see the report for.
  content.push({ type: "text", text: String(body.prompt || "") });
  if (!body.prompt) return reply(request, 400, { error: "no prompt" });

  const out = await askAnthropic(env, model, content, DIR_FINDINGS_SCHEMA, "high", 4000);
  if (out.error) return reply(request, 502, { error: out.error });
  return reply(request, 200, { findings: (out.value || {}).findings || [] });
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
      if (request.method === "POST" && path === "/v1/dir/detect") return handleDirDetect(request, env);
      if (request.method === "POST" && path === "/v1/dir/validate") return handleDirValidate(request, env);
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
