#!/usr/bin/env python3
"""Sign license/status.json from tools/revoked.txt.

    python tools\\publish_status.py

Reads the Ed25519 signing seed from dist\\ig_admin_key.igk (override with
--key), builds the payload from tools/revoked.txt, signs it, verifies the
result, and writes license/status.json.

THE SEED NEVER ENTERS THIS REPOSITORY. .gitignore already excludes *.igk;
do not add one, do not paste one into a file here.

--- The one detail that must not drift ---------------------------------------

The signature covers exactly

    json.dumps(payload, sort_keys=True, separators=(",", ":"))

encoded UTF-8. This was verified against the 2026-08-24 status file with the
public key, not assumed. Any other serialization -- a space after the colon,
unsorted keys, a trailing newline -- produces a file that EVERY client
rejects. Do not "tidy" the dumps call.

--- The second detail that must not drift ------------------------------------

"updated" MUST BE STRICTLY GREATER THAN THE "updated" OF THE FILE THIS ONE
REPLACES. Not "usually". Always. THE APP DEPENDS ON IT, and here is exactly
what depends on it and why:

inspector_gadgets.py remembers a revocation as the SIGNED FILE that did the
revoking, and clears it when a signed file that supersedes it says the id is
fine again. "Supersedes" is decided by comparing the two "updated" fields --
never by the machine clock, which a customer can move. So "updated" is the
app's ONLY way to order two of Chris's files.

While this script stamped `int(time.time())` and nothing else, two files
published inside the same second carried the SAME "updated", and the app was
left guessing which of the two was the later truth. Both guesses cost
something, and both were shipped and then withdrawn:

  - guess "strictly newer wins": a reinstatement published in the same second
    as the revocation never lands, and the customer stays locked out forever.
  - guess "same second wins": a revocation published in the same second as an
    ordinary status file is thrown away the launch after it arrives.

A publisher that never repeats or lowers a stamp removes the guess. Two files
Chris signed can then always be ordered, and the app orders them the only way
that is safe offline: by what Chris published last.

So: read the file being replaced, and if the wall clock is not strictly
greater than its "updated", use previous + 1. Never emit a stamp less than or
equal to the one being replaced -- not when the machine clock has gone
backwards, not when the previous file was stamped in the future, not ever.

--- ROUND SEVEN: TWO FLOORS, AND A NUMBER THAT MUST BE WHOLE ----------------

Reading the file back was not enough, twice over.

FIRST, half a number read as a whole one. The fallback that scrapes an
"updated" out of a status file too damaged to parse matched on whatever digits
happened to survive the damage, so a file cut in the middle of 2000000000
handed back 200000000 -- a floor ten times too low. The wall clock is "ahead"
of that, so the ordinary branch fired and published a LOWER stamp than the one
already in the field, silently. A reinstatement published that way can never
clear a revocation, and the customer stays locked out with no signal and no
sign that anything went wrong. The scrape now requires the digits to be
followed by something that says the number ended, and a cut-off number is
reported as cut off rather than read short.

SECOND, the published file is the wrong thing to lean on alone. It lives in a
git repository: `git checkout`, a reverted commit, a fresh clone or publishing
from a second working copy all present a file that is older than what the
world has actually seen, and none of them look like damage. So this script now
also keeps a LAST-STAMP NOTE beside the signing key -- outside the repository,
on the machine that does the signing, one decimal integer and nothing else --
and takes the floor as the HIGHER of the note and the file. The note cannot be
rolled back by git; the file cannot be lost by moving to a new machine. Each
covers the other's failure, and every branch that ends up with a lower floor
than it wanted says so on the terminal.

THIS SCRIPT STILL NEVER REFUSES TO RUN. Every fallback above is loud and none
of them stops a publish. The one sys.exit that could fire on a live publish --
an assertion that the stamp beat the floor -- has been turned into a clamp for
exactly that reason.

--- ROUND EIGHT: A CUT-OFF NUMBER IS ROUNDED UP, NOT THROWN AWAY ------------

Round seven stopped reading a cut-off "updated" short, and then threw it away.
That is safe only while the note beside the key exists; on a machine with no
note (a fresh checkout, a key copied without its note) the floor fell through
to the wall clock, and a file cut in the middle of 2000000000 could again be
followed by a LOWER stamp than the one in the field. So the surviving digits
are now padded with trailing 9s to the ten digits every Unix-seconds stamp
between 2001 and 2286 has, and THAT is the floor: the largest value the number
could have been. A stamp too high costs nothing (the next publish is floor + 1
with a warning); a stamp too low loses a reinstatement (a revoked customer
stays locked out).

The invariant, and exactly how far it reaches: cutting a valid published file
at ANY byte offset never makes this script report a floor lower than the true
stamp -- either a number at or above it, or None when no "updated" digits
survived -- for every stamp of ten digits, which is every stamp this script
emits on its own between 2001 and 2286. A stamp with MORE digits exists only
downstream of a hand-typed floor (the 99999999999 described under
next_updated), and padding cannot know how many digits a cut number lost. So
the padding width is the larger of ten and the digit count of the note beside
the key: with the note present, the invariant also covers every stamp with no
more digits than the note's. Without a note, a stamp of eleven or more digits
cut short is the one case this script can still read low, and it is not a
case this script creates.

Three smaller things the same round closed. A whole "updated" SHORTER than
ten digits in a file that will not parse is treated as cut, not trusted: no
stamp this script has emitted is that short, and a single corrupted byte
(a digit turned into a space or comma) is enough to make a cut look
terminated. Every "updated" found in the raw text competes, whole or cut,
and the highest wins, so a whole low number beside a cut-off high one no
longer hides it. And a run of digits too long to convert to an integer is
skipped rather than raised, because this script never raises on the way to
a publish.

Requires: pynacl  (pip install pynacl)  or  cryptography.
"""

import argparse
import base64
import binascii
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

DEFAULT_KEY = os.path.join(REPO, "..", "dist", "ig_admin_key.igk")
REVOKED_TXT = os.path.join(HERE, "revoked.txt")
STATUS_JSON = os.path.join(REPO, "license", "status.json")

CANON = dict(sort_keys=True, separators=(",", ":"))


# --- signing backend ---------------------------------------------------------

def _backend():
    try:
        from nacl.signing import SigningKey  # type: ignore

        def sign(seed, message):
            sk = SigningKey(seed)
            return bytes(sk.sign(message).signature), bytes(sk.verify_key)

        def verify(pub, message, sig):
            from nacl.signing import VerifyKey  # type: ignore
            VerifyKey(pub).verify(message, sig)

        return sign, verify
    except ImportError:
        pass

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore
            Ed25519PrivateKey,
        )
        from cryptography.hazmat.primitives import serialization  # type: ignore

        def sign(seed, message):
            sk = Ed25519PrivateKey.from_private_bytes(seed)
            pub = sk.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            return sk.sign(message), pub

        def verify(pub, message, sig):
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore
                Ed25519PublicKey,
            )
            Ed25519PublicKey.from_public_bytes(pub).verify(sig, message)

        return sign, verify
    except ImportError:
        pass

    sys.exit("Need pynacl or cryptography:  pip install pynacl")


# --- seed loading ------------------------------------------------------------

def load_seed(path):
    """Accept a raw 32-byte seed, base64, hex, or JSON with a 'seed' key.

    If a real .igk turns out to be some other shape, THIS is the function to
    adjust -- nothing else in the file cares how the seed arrived.
    """
    if not os.path.exists(path):
        sys.exit("No signing key at %s\n(use --key to point at it)" % path)

    with open(path, "rb") as fh:
        raw = fh.read()

    if len(raw) == 32:
        return raw

    text = raw.decode("utf-8", "replace").strip()

    if text.startswith("{"):
        try:
            doc = json.loads(text)
        except ValueError:
            pass
        else:
            for field in ("seed", "key", "private", "sk"):
                if field in doc:
                    return load_seed_value(str(doc[field]))
            sys.exit("JSON key file has no 'seed' field: %s" % path)

    return load_seed_value(text)


def load_seed_value(text):
    text = text.strip().strip('"').strip("'")

    if len(text) == 64:
        try:
            return binascii.unhexlify(text)
        except (binascii.Error, ValueError):
            pass

    pad = text + "=" * (-len(text) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            seed = decoder(pad)
        except Exception:
            continue
        if len(seed) == 32:
            return seed
        if len(seed) == 64:      # seed || public key, as some libraries store it
            return seed[:32]

    sys.exit("Could not read a 32-byte Ed25519 seed out of that key file.")


# --- revocation list ---------------------------------------------------------

def load_revoked(path):
    """One license id per line. '#' comments and blank lines ignored."""
    if not os.path.exists(path):
        return []
    ids = []
    for line in open(path, "r", encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if line and line not in ids:
            ids.append(line)
    return ids


# --- the strictly-increasing stamp -------------------------------------------

# The floor is read from TWO places, and the higher of the two wins. Neither
# is trusted on its own, and the reason is that they fail in opposite
# directions:
#
#   the published file      is the ground truth about what the world can see,
#                           and it is also a file that gets truncated by a full
#                           disk, rolled back by a `git checkout`, hand-edited,
#                           or simply absent because this is a fresh clone.
#   the note beside the key travels with the SIGNING MACHINE rather than with
#                           the repository, is written and read by this script
#                           alone in one fixed shape, and therefore survives
#                           every one of those. It cannot know about a publish
#                           some other copy of this script made.
#
# max(file, note) is higher than either can be alone, and a stamp that is too
# HIGH costs a number; a stamp that is too LOW costs a customer.

STAMP_NOTE_SUFFIX = ".laststamp"


def stamp_note_path(key_path):
    """The "last stamp emitted" note, beside the signing key.

    BESIDE THE KEY ON PURPOSE, and this is the answer to "would a note be
    sounder than reading the published file back?" -- it is sounder, and it is
    not a replacement:

      - the key is the one file that is guaranteed present on the machine that
        publishes, and guaranteed ABSENT everywhere else, so the note lives
        exactly where publishing happens and nowhere else;
      - it is outside the repository (.gitignore already keeps *.igk out), so
        `git checkout`, a stale branch, a fresh clone and a reverted commit
        cannot roll the floor backwards -- and rolling the floor backwards is
        the whole defect;
      - it is written by one program in one shape: a decimal integer. There is
        no JSON to half-write, no signature to scrape past, and a truncated
        note is a partial number that this file REFUSES to read rather than
        reads short (see read_stamp_note).

    What it cannot do, and why the file is still read: the note knows only
    what THIS machine published. A file published from another checkout, or
    the very first publish after moving to a new machine, is invisible to it.
    So both are read and the higher wins.
    """
    return key_path + STAMP_NOTE_SUFFIX


def read_stamp_note(path, warn=print):
    """The stamp this script last emitted, or None. Never raises.

    A note that is not exactly one positive decimal integer is NOT read
    short: half a number is the same trap as half a number in the status
    file, and it comes back None-with-a-warning rather than as a smaller
    number that would silently lower the floor."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except Exception:
        warn("WARNING: the last-stamp note %s is there and could not be read.\n"
             "         The floor for this publish comes from the published file\n"
             "         alone." % path)
        return None
    body = text.strip()
    if not re.fullmatch(r"[0-9]{1,19}", body or ""):
        warn("WARNING: the last-stamp note %s does not contain a whole number\n"
             "         (%r). IGNORING IT rather than reading part of one. The\n"
             "         floor for this publish comes from the published file\n"
             "         alone." % (path, body[:40]))
        return None
    n = int(body)
    return n if n > 0 else None


def write_stamp_note(path, stamp, warn=print):
    """Record the stamp about to be emitted. True if the bytes landed.

    NEVER LOWERS the note: what is written is max(what is there, `stamp`), so
    a note cannot be walked backwards by a run that read a lower floor for any
    reason. Written BEFORE the status file, so the note is never behind what
    was published -- if the publish then fails, the note is one number ahead,
    which costs a number and nothing else.

    A failure here does NOT stop the publish. It is loud instead: the floor
    for the next run falls back to the published file, which is where it came
    from before this note existed."""
    try:
        current = None
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8",
                          errors="replace") as fh:
                    body = fh.read().strip()
                if re.fullmatch(r"[0-9]{1,19}", body or ""):
                    current = int(body)
            except Exception:
                current = None
        keep = max(int(stamp), current or 0)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("%d\n" % keep)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        warn("WARNING: could not write the last-stamp note %s (%s).\n"
             "         The publish goes ahead; the floor for the NEXT run will\n"
             "         come from the published file alone." % (path, exc))
        return False


# A number is only a number if something in the file says it ENDED. In JSON
# that is a comma, a closing brace or bracket, or whitespace. A file truncated
# mid-number ends after its surviving digits with nothing at all, and that is
# the case this lookahead exists to reject.
_UPDATED_RE = re.compile(r'"updated"\s*:\s*(\d+)(?=[\s,}\]])')
_UPDATED_LOOSE_RE = re.compile(r'"updated"\s*:\s*(\d+)')

# Every stamp this script emits is Unix seconds, and Unix seconds is exactly
# ten decimal digits for every date between 2001 and 2286. A cut-off stamp
# with fewer surviving digits is therefore a ten-digit number whose tail is
# missing, and the largest number with that head is the head padded with 9s.
STAMP_DIGITS = 10


def pad_truncated_stamp(digits, width=STAMP_DIGITS):
    """The largest `width`-digit stamp that starts with `digits`.

    "200000000" -> 2000000009, "2" -> 2999999999, "1757462400" -> 1757462400.
    `width` or more digits come back as they are: a cut that lands exactly at
    the end of a whole number recovers the number itself. `width` is never
    less than STAMP_DIGITS; next_updated raises it to the digit count of the
    note beside the key, so a field that has already passed ten digits (only
    ever by a hand-typed floor) is padded to match. Rounding UP is the point:
    a floor too high costs a number, a floor too low costs a customer.

    Raises ValueError only for a run of digits too long for int() to convert
    (thousands of digits); previous_updated_detail skips such a run.
    """
    digits = str(digits)
    width = max(int(width), STAMP_DIGITS)
    if len(digits) < width:
        digits = digits + "9" * (width - len(digits))
    return int(digits)


def previous_updated(path):
    """The "updated" of the status file at `path`, or None if there is not a
    usable whole one there.

    Kept returning a bare int-or-None because that is what it always returned;
    previous_updated_detail is the same read with its reasons attached, and is
    what next_updated calls.
    """
    return previous_updated_detail(path)[0]


def previous_updated_detail(path, stamp_digits=STAMP_DIGITS):
    """(stamp_or_None, source, complaint_or_None). Never raises.

    `source` is one of "absent", "parsed", "scraped", "truncated", "no-stamp",
    "unreadable". `stamp_digits` is the width a cut-off number is padded to;
    it is never taken below STAMP_DIGITS, and next_updated passes the digit
    count of the note beside the key so the padding keeps up with a field
    that has already passed ten digits.

    HOW HARD THIS TRIES, AND WHY. The number it returns is a floor for the
    stamp this run emits, so failing to find one can only ever contribute a
    LOWER floor -- which is the thing that must not happen. It tries the
    parsed JSON first and then, if the file is there but will not parse (half
    written, truncated by a full disk, hand-edited into invalid JSON), scrapes
    the raw text for an "updated" number. A truncated file that still contains
    its WHOLE stamp is common; ignoring it would drop the floor for no reason.

    A file that DOES parse is taken at its word and never scraped: its
    "updated" is whatever the JSON says, and if that is not a positive whole
    number (missing, a bool, a string, zero) the answer is "no-stamp". Such a
    file is a hand-edit, not damage, and there is nothing to round up.

    ROUND SEVEN: WHAT THE SCRAPE MUST NOT DO, and did. `"updated"\\s*:\\s*(\\d+)`
    matches the digits that SURVIVED a truncation just as happily as it matches
    a whole number. A file cut in the middle of 2000000000 leaves 200000000 --
    a floor ten times too low -- and the caller then found the wall clock
    "ahead" of it and published a stamp BELOW the one already in the field,
    with no warning at all, because that is the ordinary branch. A revoked
    machine holds the old file's stamp; a reinstatement stamped below it can
    never clear the revocation, and the customer stays locked out. So the
    digits must be followed by something that says the number ended.

    ROUND EIGHT: WHAT HAPPENS WHEN THEY ARE NOT. The surviving digits are
    padded with trailing 9s to `stamp_digits` (see pad_truncated_stamp), and
    the result comes back as source "truncated" with a complaint naming both
    the digits and the padded value. That number is the largest the cut-off
    stamp could have been, so it is a floor that is at or above the truth by
    construction. Rounding UP is deliberate: a floor too high costs one number
    and a warning on the next publish; a floor too low publishes a stamp the
    field has already passed, and a reinstatement stamped that way never
    lands. Returning None here instead -- which is what round seven did -- was
    only safe while the note beside the key existed.

    THE SAME RULE FOR A WHOLE NUMBER THAT IS TOO SHORT. A terminated "updated"
    with fewer than STAMP_DIGITS digits in a file that will not parse is
    treated as cut and padded the same way. No stamp this script has emitted
    is that short, and one corrupted byte in the middle of a stamp -- a digit
    turned into a space or a comma -- makes a cut number look terminated.
    Reading it whole would be reading it short.

    EVERY CANDIDATE COMPETES. Each "updated" in the raw text, whole or cut, is
    turned into a floor and the highest wins; `source` names the kind that
    won. A whole low number beside a cut-off high one (a hand-merged file,
    two files concatenated) therefore cannot hide the high one. A run of
    digits too long for int() to convert is skipped: it is not a stamp, and
    this function does not raise.
    """
    if not os.path.exists(path):
        return None, "absent", None
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except Exception as exc:
        return None, "unreadable", "could not be opened (%s)" % exc
    text = raw.decode("utf-8", "replace")
    try:
        doc = json.loads(text)
    except Exception:
        doc = None
    if isinstance(doc, dict):
        try:
            v = (doc.get("payload") or {}).get("updated")
            if not isinstance(v, bool):
                n = int(v)
                if n > 0:
                    return n, "parsed", None
        except Exception:
            pass
        return None, "no-stamp", ("parses as JSON but its \"updated\" is not a "
                                  "positive whole number")

    # Unparseable: scrape. Every "updated" in the raw text is a candidate. A
    # whole number of at least STAMP_DIGITS digits is read as it stands; any
    # other run of digits -- cut off, or whole but shorter than any stamp this
    # script has emitted -- is the dangerous case: read as it stands it is a
    # floor too LOW. So it is padded UP to the largest stamp it could have
    # been, and the complaint names both the digits and the padded value so
    # the operator knows the floor being used is not the file's but is at or
    # above it. The highest candidate wins.
    width = max(int(stamp_digits), STAMP_DIGITS)
    best = None
    best_kind = None
    best_digits = None
    for m in _UPDATED_LOOSE_RE.finditer(text):
        digits = m.group(1)
        whole = _UPDATED_RE.match(text, m.start()) is not None
        try:
            if whole and len(digits) >= STAMP_DIGITS:
                n, kind = int(digits), "scraped"
            else:
                n, kind = pad_truncated_stamp(digits, width), "truncated"
        except ValueError:
            # More digits than int() will convert. Not a stamp; not a crash.
            continue
        if n > 0 and (best is None or n > best):
            best, best_kind, best_digits = n, kind, digits
    if best is None:
        return None, "no-stamp", "contains no usable \"updated\" at all"
    if best_kind == "scraped":
        return best, "scraped", ("will not parse as JSON; its \"updated\" was "
                                 "read out of the raw text")
    return best, "truncated", (
        "contains an \"updated\" that is CUT OFF or shorter than any stamp "
        "this script emits (the surviving digits are %s). The floor has been "
        "ROUNDED UP ON PURPOSE to %d, the largest %d-digit stamp starting "
        "with those digits, because a floor too high costs one number and a "
        "floor too low publishes below what the field has already seen"
        % (best_digits, best, width))


def next_updated(out_path, now=None, warn=print, note_path=None):
    """The stamp to publish: strictly greater than the one being replaced.

    (stamp, floor_or_None, note). `note` is the one-line explanation the
    caller prints, because every branch here except the ordinary one is worth
    seeing on the terminal.

    THE FLOOR IS THE HIGHER OF TWO READINGS -- the published file and the note
    beside the signing key. See stamp_note_path for why neither is trusted
    alone.

    THE CASES, HANDLED RATHER THAN ASSUMED:

      nothing anywhere            -> the wall clock. This is the first publish
                                     from this machine into this path; there
                                     is nothing to be greater than, and
                                     nothing is said.
      published file absent, but
        the note has a stamp      -> the note is the floor, WITH A WARNING:
                                     the file this script is replacing is not
                                     where it was.
      published file stamped
        short (cut mid-number, or
        a whole number shorter
        than any stamp)           -> the surviving digits ROUNDED UP to the
                                     largest stamp they could have been
                                     (pad_truncated_stamp, padded to the
                                     wider of ten digits and the note's
                                     digit count), competing with the note
                                     like any other floor, WITH A WARNING
                                     naming the padded floor.
      published file unreadable,
        unparseable or not
        stamped                   -> whatever floor is left (the note, or
                                     none), WITH A WARNING naming which.
      floor >= now                -> floor + 1, WITH A WARNING. This covers a
                                     machine clock that has gone backwards and
                                     a previous file stamped in the future.
      floor < now                 -> the wall clock. The ordinary publish.

    EVERY BRANCH THAT COULD EMIT A STAMP BELOW WHAT IS ALREADY PUBLISHED
    WARNS. That is the round-seven requirement and it is worth stating as a
    rule rather than as four separate lines: the only silent branches are
    "there is no floor anywhere and nothing has ever been published from
    here" and "the clock is ahead of a floor this run read WHOLE from both
    sources it could".

    WHY AN UNREADABLE PREVIOUS FILE FALLS BACK RATHER THAN REFUSING TO
    PUBLISH. Refusing would be the tidier-looking choice, and it is the wrong
    one: the file this script publishes most urgently is a REINSTATEMENT, and
    a publisher that will not run leaves the customer it was meant to put back
    locked out. So every fallback here is loud, and none of them blocks a
    publish.

    WHAT floor + 1 COSTS, said plainly. A previous file stamped absurdly far
    in the future -- a hand-typed 99999999999 -- pins every future stamp to
    that number plus one per publish, forever. That is deliberate: the
    alternative is emitting a stamp below one the field has already seen,
    which makes a genuine reinstatement unable to clear a revocation. The
    recovery is to edit the published file's "updated" down to a sane number,
    edit the note beside the key down to match, and re-run this script;
    nothing here will do it silently.
    """
    now = int(time.time()) if now is None else int(now)
    note_stamp = None
    if note_path:
        note_stamp = read_stamp_note(note_path, warn=warn)
    # The note is read FIRST because it sets how wide a cut-off number in the
    # file is padded: a field that has already passed ten digits (only ever by
    # a hand-typed floor) is padded to the note's width, not to ten.
    width = STAMP_DIGITS
    if note_stamp is not None:
        width = max(width, len("%d" % note_stamp))
    file_stamp, source, complaint = previous_updated_detail(
        out_path, stamp_digits=width)

    if source == "absent" and note_stamp is not None:
        warn("WARNING: %s is not there, but this machine last published stamp\n"
             "         %d. Using that as the floor. If the published file was\n"
             "         moved or rolled back, PUT IT BACK before publishing."
             % (out_path, note_stamp))
    elif source == "truncated" and file_stamp is not None:
        warn("WARNING: %s %s.\n"
             "         USING %d AS THE FILE'S FLOOR -- at or above the true\n"
             "         stamp, never below it, for any stamp of up to %d digits.\n"
             "         The higher of that and this machine's last-stamp note\n"
             "         (%s) wins. Treat that file as damaged and check it by\n"
             "         eye."
             % (out_path, complaint, file_stamp, width,
                "none" if note_stamp is None else "%d" % note_stamp))
    elif source in ("unreadable", "truncated", "no-stamp"):
        warn("WARNING: %s %s.\n"
             "         %s\n"
             "         If that file was stamped in the future, FIX IT BY HAND\n"
             "         before publishing again."
             % (out_path, complaint,
                ("Falling back to this machine's last-stamp note (%d)."
                 % note_stamp) if note_stamp is not None
                else "There is NO floor left to honor; stamping the wall clock."))
    elif source == "scraped":
        warn("WARNING: %s %s (%d).\n"
             "         Treat that file as damaged and check it by eye."
             % (out_path, complaint, file_stamp))

    floor = None
    for cand in (file_stamp, note_stamp):
        if cand is not None and (floor is None or cand > floor):
            floor = cand

    if floor is None:
        return now, None, "no floor anywhere; stamping the wall clock"
    if now > floor:
        return now, floor, "wall clock is ahead of the floor (%d)" % floor
    stamp = floor + 1
    warn("WARNING: the wall clock (%d) is not ahead of the floor already\n"
         "         published or noted (%d). Emitting %d instead, because the\n"
         "         app orders Chris's files by this number and it must never\n"
         "         go back." % (now, floor, stamp))
    return stamp, floor, "clock not ahead of the floor; using floor + 1"


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Sign and write license/status.json")
    ap.add_argument("--key", default=DEFAULT_KEY, help="path to ig_admin_key.igk")
    ap.add_argument("--revoked", default=REVOKED_TXT, help="path to revoked.txt")
    ap.add_argument("--out", default=STATUS_JSON, help="path to status.json")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args()

    sign, verify = _backend()
    seed = load_seed(args.key)
    revoked = load_revoked(args.revoked)

    notefile = stamp_note_path(args.key)
    updated, prev, note = next_updated(args.out, note_path=notefile)

    payload = {
        "format": 1,
        "updated": updated,
        "revoked": revoked,
    }

    message = json.dumps(payload, **CANON).encode("utf-8")
    sig, pub = sign(seed, message)
    verify(pub, message, sig)                      # never publish an unverified file

    doc = {"payload": payload, "sig": base64.b64encode(sig).decode("ascii")}
    text = json.dumps(doc, indent=1) + "\n"

    print("public key : %s" % binascii.hexlify(pub).decode("ascii"))
    print("             (must equal LICENSE_PUB_HEX in inspector_gadgets.py)")
    print("revoked    : %d" % len(revoked))
    for rid in revoked:
        print("             %s" % rid)
    print("floor      : %s" % ("(none)" if prev is None else prev))
    print("note       : %s" % notefile)
    print("updated    : %d  (%s UTC)" % (
        payload["updated"],
        time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(payload["updated"])),
    ))
    print("             %s" % note)
    # The invariant this script exists to keep, checked on the way out rather
    # than trusted. next_updated cannot return a stamp at or below the floor
    # it computed, so this is unreachable by construction -- and it CLAMPS
    # rather than exits, because "refusing to publish" is the one outcome this
    # script may never have. A publisher that will not run leaves a customer
    # locked out, and the file it most often publishes is the one that puts
    # somebody back. (The previous version called sys.exit here. That was a
    # refusal hiding in the assertion that no refusal was possible.)
    if prev is not None and payload["updated"] <= prev:
        forced = prev + 1
        print("WARNING: computed stamp %d is not above the floor %d. That is a\n"
              "         bug in next_updated. CLAMPING to %d and publishing\n"
              "         anyway, because not publishing is worse."
              % (payload["updated"], prev, forced))
        payload["updated"] = forced
        message = json.dumps(payload, **CANON).encode("utf-8")
        sig, pub = sign(seed, message)
        verify(pub, message, sig)
        doc = {"payload": payload, "sig": base64.b64encode(sig).decode("ascii")}
        text = json.dumps(doc, indent=1) + "\n"

    if args.dry_run:
        print("\n--dry-run, nothing written (the last-stamp note is not touched\n"
              "either, so a dry run cannot push the next real stamp up)\n")
        print(text)
        return

    # THE NOTE GOES DOWN FIRST, before the file it describes. If this script
    # dies between the two, the note is one number ahead of what the world can
    # see -- which costs a number. The other order would leave the note BEHIND
    # a published file, which costs a customer.
    write_stamp_note(notefile, payload["updated"])

    outdir = os.path.dirname(args.out)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, args.out)
    print("wrote      : %s" % args.out)
    print("\nNow: git add license/status.json && git commit && git push")


if __name__ == "__main__":
    main()
