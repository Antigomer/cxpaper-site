# cxpaper.com

The Construction Paper website and the license status host. Static, served by
GitHub Pages from this repository. No server, no monthly bill, nothing to patch.

    index.html            overview
    download/             download page — reads the current build live from
                          the Releases API, so it cannot go stale
    license/              how licensing works
    license/status.json   THE SIGNED STATUS FILE the program checks
    assets/               css, js, the mark (also the favicon)
    tools/publish_status.py   re-sign status.json from tools/revoked.txt
    tools/release.bat         publish a build to GitHub Releases
    CNAME                 cxpaper.com

Two repositories, on purpose:

| repo | holds |
| --- | --- |
| `antigomer/cxpaper-site` | this site. Pages serves it at cxpaper.com |
| `antigomer/cxpaper-releases` | the `.exe` releases only, nothing else |

Keeping the binaries out of the Pages repo means the site's history stays small
and a bad release never touches the site.

---

## Deploying — done 2026-09-09

Recorded because the order matters if this is ever rebuilt.

1. **GitHub first.** Create both repos. On `cxpaper-site`, Settings → Pages →
   source *Deploy from a branch*, branch `main`, folder `/ (root)`. The `CNAME`
   file in the repo sets the custom domain automatically. Doing this before DNS
   is what lets GitHub issue the certificate the moment DNS lands.
2. **DreamHost DNS.** The trap: DreamHost will not accept apex A records while
   the domain is set to hosting — take cxpaper.com to **DNS Only** first
   (Websites → Manage → Hosting). Then, under Custom Records:

   | type | host | value |
   | --- | --- | --- |
   | A | *(blank / @)* | `185.199.108.153` |
   | A | *(blank / @)* | `185.199.109.153` |
   | A | *(blank / @)* | `185.199.110.153` |
   | A | *(blank / @)* | `185.199.111.153` |
   | CNAME | `www` | `antigomer.github.io.` |

   Paste carefully — DreamHost reports a leading space in the value as
   "Invalid IPv4 address" without saying why. Type them by hand if in doubt.

   Then wait. An hour is normal. When GitHub's Pages settings stop showing the
   DNS warning, tick **Enforce HTTPS**.

   ```
   nslookup cxpaper.com
   curl -sI https://cxpaper.com/license/status.json
   ```

3. **Point the program at it.** In `inspector_gadgets.py`:

   ```python
   LICENSE_STATUS_URL_DEFAULT = "https://cxpaper.com/license/status.json"
   ```

   **Test before committing that line.** A file called `status_url.txt` beside
   `ConstructionPaper.exe` containing the URL overrides the compiled-in default.
   Confirm Help ▸ License… reports a good check-in, then change the default and
   rebuild.

---

## Publishing a new build

```
tools\release.bat 1.0.1 "Build 4"
```

Computes the SHA-256, writes it into the release notes, uploads the exe. The
download page picks it all up on the next load. Nothing here needs editing.

## Revoking a key

1. Add the license id to `tools/revoked.txt`.
2. `python tools\publish_status.py`
3. Commit and push `license/status.json`.

The script prints the public key it derived from the seed — it must match
`LICENSE_PUB_HEX` in `inspector_gadgets.py`. If it does not, stop: you signed
with the wrong key and every client will reject the file.

Copies with a strict check-in stop at their next check. Lenient copies stop when
they next reach the host successfully.

### The serialization rule

The signature covers exactly

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"))
```

verified against the 2026-08-24 file with the public key, not assumed. Any other
form — a space after a colon, unsorted keys, a trailing newline inside the
signed bytes — produces a file every client rejects. Do not tidy that call.

### The `updated` stamp, and the note beside the key

`updated` must be strictly greater than the `updated` of the file it replaces —
always, not usually. The app orders Chris's signed files by that number and by
nothing else (never by the machine clock, which a customer can move), so a
reinstatement stamped below the revocation it is meant to supersede never
lands, and the customer stays locked out offline.

`publish_status.py` takes the floor for the next stamp as the **higher of two
readings**:

* the `updated` in `license/status.json`, and
* `dist\ig_admin_key.igk.laststamp` — one decimal integer, written by this
  script beside the signing key, **outside this repository**.

Neither alone is enough. The published file gets truncated by a full disk,
rolled back by a `git checkout`, or is simply absent in a fresh clone; the note
survives all of those but knows nothing about a publish made from another
machine. `.gitignore` already excludes `ig_admin_key*`, so the note cannot be
committed by accident.

A damaged file is read **upward**. Every stamp is Unix seconds — ten digits for
any date between 2001 and 2286 — so if `status.json` is cut off in the middle
of its `updated` (a full disk, a half-written copy), the surviving digits are
padded with trailing 9s to ten digits and *that* is the file's floor:
`200000000` becomes `2000000009`, `2` becomes `2999999999`, and a cut exactly
at the end of the number recovers the number itself. A whole `updated` shorter
than ten digits in a file that will not parse is treated the same way (one
corrupted byte can make a cut number look finished), every `updated` found in
the raw text competes and the highest wins, and the padding widens to match the
note beside the key if the field has ever passed ten digits. The result competes
with the note like any other floor and the script warns, naming the padded
value. This is deliberate: a floor too high costs one number (the next publish
is floor + 1, with a warning); a floor too low publishes a stamp the field has
already passed, and a reinstatement stamped that way never lands.

If the script warns, read the warning — every fallback that could emit a stamp
below what is already published says so. **It never refuses to publish**: a
publisher that will not run leaves a customer locked out, and the file it most
often publishes is the one that puts somebody back.

### The seed

`tools/publish_status.py` reads the Ed25519 seed from `dist\ig_admin_key.igk`
(accepts raw 32 bytes, base64, hex, or JSON with a `seed` key). **It must never
enter this repository.** `.gitignore` excludes `*.igk` and `*.igl`; leave those
lines alone. If a real `.igk` is shaped differently, `load_seed()` is the only
function to adjust.

---

## Deliberately not built

Activation counting and the Tier-3 AI relay. Both need a real endpoint and a
static host cannot serve one. When they are wanted, the answer is a Cloudflare
Worker on the same domain with this site unchanged — not a move off Pages.

## Contact address

The pages use `chris@chrisputnam.me`. DreamHost mail forwarding is not free on a
DNS-Only domain, so `hello@cxpaper.com` would need either a paid forward or a
move of DNS to Cloudflare (free email routing). Three files carry the address:
`index.html`, `download/index.html`, `license/index.html`.

## The ream edge

The thin banded strip under the header is one 200-stop sequence read off the
mark's own side face and laid flat — derived from the mark rather than being a
second variant of it. To remove it: delete `.ream` from `assets/site.css` and
the `<div class="ream">` from the three pages.
