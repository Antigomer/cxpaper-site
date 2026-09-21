# The DIR vision relay

Built 21 September 2026, on Chris's instruction, after the discovery that
Construction Paper's vision had **never worked for anybody**.

## What was wrong

`dir_writer.relay.make_backend` had no relay URL baked in and `direct`
defaulted to `True`. With nothing configured — which is every machine out of
the box — it reached for the Anthropic SDK:

- **on the exe**, which does not carry the SDK, that is nothing at all, so
  vision was silently off for every customer;
- **on a developer's machine** it spent a personal API credential on work the
  relay exists to do without one, and surfaced as *"your credit balance is
  too low"* — a billing error from a path the product should never be on.

Chris: *"construction paper doesn't use the API. That's the whole point."*

And the relay it should have used did not exist. The site README had said so
all along, under **"Deliberately not built"**.

## What was built

Two routes, added to the **existing licence desk Worker** rather than a new
one — it already has the KV namespace, the deploy script, the secret handling
and a test suite, and the licence check the relay needs is the same
`claim:<id>` lookup `/activate` does.

    POST /v1/dir/detect     one field photo  -> which classes are in it
    POST /v1/dir/validate   a DIR slot       -> findings about its caption

Live at `https://cxpaper-license.chris-73e.workers.dev`, which is now the
baked-in `DEFAULT_RELAY_URL`.

**Not `cxpaper.com/api`.** The first attempt pointed there and it was wrong
twice over: nothing serves `/api` on that domain, and cxpaper.com is not
routed to a Worker at all — even `/request`, a route the desk has always
had, 405s there. A custom domain needs the domain moved onto Cloudflare,
which the README raises as an open question for email routing; not worth
coupling the two.

## What it does and does not keep

**Nothing about a photograph is stored.** The image arrives, goes to the
model, the reply goes back. What is kept is one per-licence per-day counter
(`drate:<id>:<date>`) and nothing else — no image, no station, no caption, no
folder name.

- the licence must be one this desk issued (`claim:<id>`), same rule as
  `/activate`: an id nobody has claimed gets nothing, because the id travels
  in the open
- 400 detections per licence per day
- 12 MB body, 8 examples, model restricted to an allowlist
- **no key, no service, no fallback**: without `ANTHROPIC_API_KEY` the two
  routes answer 503, exactly as the admin routes do without `ADMIN_TOKEN`. A
  fallback constant would be an API key in a public repository.

## The order of the request, which is the whole thing

Marks give a position; a position is a fraction; a fraction means nothing
until the model is told which photograph it is a fraction **of**. Measured
2026-09-20 on the direct path: four marks with the frame named only in words
scored **34 of 48**, against **47 of 48 with no marks at all** — every
coordinate came back at about 0.765 of true, because the examples and the
target are different pixel sizes.

So the content is assembled: prompt → for each example (its caption, then its
picture) → the `frame` sentence → the photograph being asked about. **Reading
`marks` and skipping `frame` is the 34-of-48 configuration** — worse than
sending no examples at all.

## The prompt exists twice, and a test pins them together

The relay builds the prompt so it controls what it is paying for; a
caller-supplied prompt would be a blank cheque against the one key. The cost
is a second copy of those words, and two copies of a rule is how FIXLIST 88
came to contradict SKILL.md within an hour of both being written.

So `dir_writer_test` reads `cxpaper-license.js` off disk and fails if
`DIR_PROMPT_HEAD` or any paragraph of `DIR_PROMPT_TAIL` stops appearing in
what `prompt_text` produces. Proven red by rewording one sentence —
"A SURVEY STAKE MUST BE STANDING" to "SHOULD BE" — and it names the sentence.

The client now also sends each class's `label` alongside `id` and `cues`, so
the relay's class list reads the same as the direct path's. Older copies omit
it and the worker falls back to the id.

## To deploy it

1. Put the Anthropic API key in `C:\_CLAUDE\anthropic-key.txt`, on a line of
   its own. **Chris does this.** The key never goes through a chat window, a
   log, or this repository, and nothing here ever prints it.
2. `python worker\deploy_worker.py`

Safe to run again. Without step 1 the deploy still succeeds and says
`vision relay NOT configured`; the two routes answer 503 until there is a
key. Unlike the admin password, a missing key is **not** invented — a random
string would deploy happily and then fail against Anthropic on the first real
photograph, in the field, with a message that means nothing to an inspector.

## Still not done

- `worker_test.py` does not yet cover these two routes. It is a Python
  translation of the JS, so the handlers need translating into it the way the
  licence handlers were.
- Nothing has been deployed. The code is written and the gate is green; the
  deploy is Chris's to run.
