"""Stamp assets/site.css and assets/site.js with a version taken from their
own contents, so a page never runs against a stale copy of either.

WHY THIS EXISTS

GitHub Pages serves everything with `cache-control: max-age=600`. The HTML and
the assets expire independently, so for ten minutes after a deploy a returning
visitor can hold new HTML and an old site.js at the same time. On 2026-09-16
that shipped a tab strip whose tabs did nothing: the markup was new, the
JavaScript that drives it was the previous copy. Nothing in the console, no
error, just a dead control - the worst kind of broken, because it looks fine.

A query string carrying a hash of the file fixes it at the root. The URL
changes exactly when the file changes, so new HTML always asks for the
matching asset and an unchanged asset stays cached.

USE

    python tools/stamp_assets.py            rewrite the stamps, report what moved
    python tools/stamp_assets.py --check    exit 1 if any stamp is stale

Run it after touching site.css or site.js and BEFORE committing. --check is
for release.bat, so a deploy cannot go out unstamped.
"""

import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ["site.css", "site.js"]

# Every page, whatever depth it sits at: the href may be "assets/site.js",
# "../assets/site.js" or "/assets/site.js", and may already carry a stamp.
LINK = re.compile(r'((?:\.\./|/)?assets/site\.(?:css|js))(\?v=[0-9a-f]+)?')


def stamp(name):
    """Eight hex characters of the asset's own sha256. Short enough to read in
    a URL, long enough that a real edit never collides."""
    data = (ROOT / "assets" / name).read_bytes()
    return hashlib.sha256(data).hexdigest()[:8]


def pages():
    for p in sorted(ROOT.glob("*.html")) + sorted(ROOT.glob("*/*.html")):
        # _workshop is gitignored scratch and is not part of the site.
        if "_workshop" in p.parts:
            continue
        yield p


def main(argv):
    check_only = "--check" in argv
    want = {name: stamp(name) for name in ASSETS}

    changed, stale = [], []
    for page in pages():
        text = page.read_text(encoding="utf-8")

        def fix(m):
            href = m.group(1)
            name = href.rsplit("/", 1)[-1]
            return "%s?v=%s" % (href, want[name])

        new = LINK.sub(fix, text)
        if new != text:
            rel = page.relative_to(ROOT).as_posix()
            if check_only:
                stale.append(rel)
            else:
                page.write_text(new, encoding="utf-8")
                changed.append(rel)

    for name in ASSETS:
        print("  %-9s v=%s" % (name, want[name]))

    if check_only:
        if stale:
            print("\nSTALE - these pages point at an old asset version:")
            for r in stale:
                print("    " + r)
            print("\nRun: python tools/stamp_assets.py")
            return 1
        print("\nEvery page is stamped with the current assets.")
        return 0

    if changed:
        print("\nRestamped:")
        for r in changed:
            print("    " + r)
    else:
        print("\nEvery page was already current. Nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
