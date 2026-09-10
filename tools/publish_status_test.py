#!/usr/bin/env python3
"""Tests for the strictly-increasing "updated" stamp in publish_status.py.

    python3 tools/publish_status_test.py

Standard library only. No signing key, no pynacl, no cryptography: the module
is imported and only the floor-reading functions are exercised. The invariant
under test: for a valid published file with true stamp T, cutting the file at
ANY byte offset never makes the script report a floor lower than T -- either a
number at or above T, or None when no "updated" digits survived at all.
"""

import base64
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import publish_status as ps  # noqa: E402

T = 1757462400  # 2026-09-10 00:00:00 UTC, ten digits like every real stamp


def status_text(updated=T, revoked=("IG-4F2A-9C11", "IG-77B0-0D3E"), sig=None):
    """A status.json in exactly the shape main() writes it."""
    if sig is None:
        sig = base64.b64encode(bytes(range(64))).decode("ascii")
    payload = {"format": 1, "updated": updated, "revoked": list(revoked)}
    doc = {"payload": payload, "sig": sig}
    return json.dumps(doc, indent=1) + "\n"


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="publish_status_test_")
        self.status = os.path.join(self.dir, "status.json")
        self.note = os.path.join(self.dir, "ig_admin_key.igk.laststamp")
        self.warnings = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def warn(self, msg):
        self.warnings.append(msg)

    def write_status(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        with open(self.status, "wb") as fh:
            fh.write(data)

    def cut_at(self, text, offset):
        self.write_status(text.encode("utf-8")[:offset])

    def offset_of_updated_digits(self, text):
        """(start, end) byte offsets of the digits after "updated":."""
        raw = text.encode("utf-8")
        key = b'"updated": '
        start = raw.index(key) + len(key)
        end = start
        while chr(raw[end]).isdigit():
            end += 1
        return start, end


class PreviousUpdatedDetail(Sandbox):

    def test_1_cut_mid_number_rounds_up(self):
        text = status_text()
        start, end = self.offset_of_updated_digits(text)
        self.cut_at(text, start + 3)          # "175" survives
        n, source, complaint = ps.previous_updated_detail(self.status)
        self.assertEqual(source, "truncated")
        self.assertEqual(n, 1759999999)
        self.assertGreaterEqual(n, T)
        self.assertIn("175", complaint)
        self.assertIn("1759999999", complaint)
        self.assertIn("ROUNDED UP", complaint)

    def test_1b_documented_examples(self):
        self.assertEqual(ps.pad_truncated_stamp("200000000"), 2000000009)
        self.assertEqual(ps.pad_truncated_stamp("2"), 2999999999)
        self.assertEqual(ps.pad_truncated_stamp("1757462400"), 1757462400)
        self.assertEqual(ps.pad_truncated_stamp("17574624001"), 17574624001)
        self.write_status('{"payload": {"format": 1, "updated": 200000000')
        n, source, _ = ps.previous_updated_detail(self.status)
        self.assertEqual((n, source), (2000000009, "truncated"))

    def test_2_cut_at_end_of_number_recovers_it(self):
        text = status_text()
        start, end = self.offset_of_updated_digits(text)
        self.cut_at(text, end)                # all ten digits, no terminator
        n, source, _ = ps.previous_updated_detail(self.status)
        self.assertEqual(source, "truncated")
        self.assertEqual(n, T)

    def test_3_cut_before_updated_is_none(self):
        text = status_text()
        idx = text.encode("utf-8").index(b'"updated"')
        for offset in (0, 1, idx - 1, idx, idx + 3):
            self.cut_at(text, offset)
            n, source, _ = ps.previous_updated_detail(self.status)
            self.assertIsNone(n, "offset %d gave %r" % (offset, n))
            self.assertEqual(source, "no-stamp")

    def test_4_cut_after_terminator_is_scraped(self):
        text = status_text()
        start, end = self.offset_of_updated_digits(text)
        self.cut_at(text, end + 1)            # the comma survives
        n, source, complaint = ps.previous_updated_detail(self.status)
        self.assertEqual(source, "scraped")
        self.assertEqual(n, T)
        self.assertIsNotNone(complaint)

    def test_5_empty_file_is_none(self):
        self.write_status(b"")
        n, source, _ = ps.previous_updated_detail(self.status)
        self.assertIsNone(n)
        self.assertEqual(source, "no-stamp")

    def test_5b_absent_file_is_absent(self):
        n, source, complaint = ps.previous_updated_detail(self.status)
        self.assertEqual((n, source, complaint), (None, "absent", None))

    def test_6_valid_json_with_unusable_updated(self):
        cases = {
            "missing": {"payload": {"format": 1, "revoked": []}, "sig": "x"},
            "true": {"payload": {"format": 1, "updated": True, "revoked": []}, "sig": "x"},
            "false": {"payload": {"format": 1, "updated": False, "revoked": []}, "sig": "x"},
            "string": {"payload": {"format": 1, "updated": "soon", "revoked": []}, "sig": "x"},
            "null": {"payload": {"format": 1, "updated": None, "revoked": []}, "sig": "x"},
            "zero": {"payload": {"format": 1, "updated": 0, "revoked": []}, "sig": "x"},
            "negative": {"payload": {"format": 1, "updated": -5, "revoked": []}, "sig": "x"},
            "no payload": {"sig": "x"},
        }
        for name, doc in cases.items():
            self.write_status(json.dumps(doc, indent=1) + "\n")
            n, source, _ = ps.previous_updated_detail(self.status)
            self.assertTrue(n is None or n >= T,
                            "%s: reported %r below %d" % (name, n, T))
            self.assertNotEqual(source, "parsed", name)

    def test_6b_parsed_whole_stamp(self):
        self.write_status(status_text())
        n, source, complaint = ps.previous_updated_detail(self.status)
        self.assertEqual((n, source, complaint), (T, "parsed", None))

    def test_7_exhaustive_every_byte_offset(self):
        text = status_text()
        raw = text.encode("utf-8")
        checked = 0
        start, end = self.offset_of_updated_digits(text)
        for offset in range(0, len(raw) + 1):
            self.cut_at(text, offset)
            n, source, complaint = ps.previous_updated_detail(self.status)
            checked += 1
            self.assertTrue(n is None or n >= T,
                            "offset %d (%r): floor %r is below %d"
                            % (offset, raw[max(0, offset - 20):offset], n, T))
            if n is None:
                self.assertLessEqual(offset, start,
                                     "offset %d lost digits that survived" % offset)
            if start < offset < end:
                self.assertEqual(source, "truncated", offset)
            if offset == len(raw):
                self.assertEqual((n, source), (T, "parsed"))
        print("\n[exhaustive] %d byte offsets checked, every floor None or >= %d"
              % (checked, T))
        self.assertEqual(checked, len(raw) + 1)

    def test_7b_exhaustive_with_a_low_stamp_in_the_signature(self):
        # A signature that happens to contain digits must never be read as
        # the stamp; the scrape keys on the literal "updated" key.
        sig = "0000000001" + base64.b64encode(bytes(64)).decode("ascii")
        text = status_text(sig=sig)
        raw = text.encode("utf-8")
        for offset in range(0, len(raw) + 1):
            self.cut_at(text, offset)
            n, _, _ = ps.previous_updated_detail(self.status)
            self.assertTrue(n is None or n >= T, offset)


class RefuterFindings(Sandbox):
    """One test per finding from the round-eight review."""

    def test_f1_eleven_digit_stamp_is_padded_to_the_notes_width(self):
        # This script emits an eleven-digit stamp only downstream of a
        # hand-typed floor, and then the note beside the key carries eleven
        # digits too. The padding width follows the note, so a cut file is
        # never read below the field.
        big = 99999999999                     # eleven digits
        for cut_digits in (1, 3, 10, 11):
            text = status_text(updated=big)
            start, end = self.offset_of_updated_digits(text)
            self.cut_at(text, start + cut_digits)
            n, source, _ = ps.previous_updated_detail(self.status, stamp_digits=11)
            self.assertEqual(source, "truncated", cut_digits)
            self.assertGreaterEqual(n, big, cut_digits)
        # Through next_updated, with the note at an eleven-digit floor and
        # another machine having published five stamps past it (still eleven
        # digits: the bound is "no more digits than the note's").
        big = 10000000000
        text = status_text(updated=big + 5)
        start, _ = self.offset_of_updated_digits(text)
        self.cut_at(text, start + 10)         # ten digits survive of eleven
        ps.write_stamp_note(self.note, big, warn=self.warn)
        stamp, floor, _ = ps.next_updated(self.status, now=T,
                                          warn=self.warn, note_path=self.note)
        self.assertGreaterEqual(floor, big + 5)
        self.assertGreater(stamp, big + 5)
        joined = "\n".join(self.warnings)
        self.assertIn("up to 11 digits", joined)

    def test_f1_exhaustive_eleven_and_twelve_digit_stamps_with_a_note(self):
        for big in (99999999999, 10000000000, 123456789012):
            width = len(str(big))
            text = status_text(updated=big)
            raw = text.encode("utf-8")
            for offset in range(0, len(raw) + 1):
                self.cut_at(text, offset)
                n, _, _ = ps.previous_updated_detail(self.status, stamp_digits=width)
                self.assertTrue(n is None or n >= big,
                                "%d offset %d: floor %r" % (big, offset, n))

    def test_f1_documented_bound_without_a_note(self):
        # The honest limit: with no note, an eleven-digit stamp cut to fewer
        # digits pads to ten, which the docstring says is the one case still
        # read low. The default width is exactly STAMP_DIGITS and nothing in
        # the ten-digit world is affected.
        self.assertEqual(ps.STAMP_DIGITS, 10)
        self.assertEqual(ps.pad_truncated_stamp("999"), 9999999999)
        self.assertEqual(ps.pad_truncated_stamp("999", 11), 99999999999)
        self.assertEqual(ps.pad_truncated_stamp("999", 3), 9999999999)  # never below ten
        self.assertEqual(ps.pad_truncated_stamp("1757462400", 11), 17574624009)

    def test_f2_every_candidate_competes_and_the_highest_wins(self):
        # A whole low number beside a cut-off high one: the cut one wins.
        self.write_status(b'{"payload":{"updated": 1, "updated": 1757462400')
        n, source, _ = ps.previous_updated_detail(self.status)
        self.assertGreaterEqual(n, T)
        self.assertEqual(source, "truncated")
        # A whole ten-digit number beside a cut-off one whose padded value
        # is higher: the padded one wins.
        self.write_status(b'"updated": 1757462400, "x":1, "updated": 17574625')
        n, source, _ = ps.previous_updated_detail(self.status)
        self.assertEqual((n, source), (1757462599, "truncated"))
        # A whole ten-digit number that is HIGHER than the padded one: the
        # whole one wins and is labeled as read whole.
        self.write_status(b'"updated": 1999999999, "x":1, "updated": 17574625')
        n, source, _ = ps.previous_updated_detail(self.status)
        self.assertEqual((n, source), (1999999999, "scraped"))
        # The winner also decides the warning next_updated prints.
        stamp, floor, _ = ps.next_updated(self.status, now=T,
                                          warn=self.warn, note_path=None)
        self.assertEqual((stamp, floor), (2000000000, 1999999999))

    def test_f3_a_corrupted_byte_that_terminates_the_number_early(self):
        # '0' -> ' ' is a one-bit flip; '0' -> ',' one byte. Either makes a
        # cut number look whole. A whole number shorter than any stamp this
        # script emits is treated as cut and rounded up.
        for damaged in (b'"updated": 1757 462400', b'"updated": 1757,462400',
                        b'"updated": 1757\n462400'):
            self.write_status(b'{"payload":{' + damaged + b', "revoked": []}, "sig": "A"}')
            n, source, complaint = ps.previous_updated_detail(self.status)
            self.assertEqual((n, source), (1757999999, "truncated"), damaged)
            self.assertIn("1757999999", complaint)
        stamp, floor, _ = ps.next_updated(self.status, now=T,
                                          warn=self.warn, note_path=None)
        self.assertEqual((stamp, floor), (1758000000, 1757999999))
        self.assertTrue(any("ROUNDED UP" in w for w in self.warnings))
        # A parseable file is not damage: its short stamp is what it says.
        self.write_status(status_text(updated=5))
        self.assertEqual(ps.previous_updated_detail(self.status)[:2], (5, "parsed"))

    def test_f4_a_digit_run_too_long_for_int_does_not_raise(self):
        for run in (4301, 5000, 20000):
            self.write_status(b'{"payload":{"updated": ' + b"1" * run)
            n, source, _ = ps.previous_updated_detail(self.status)
            self.assertEqual((n, source), (None, "no-stamp"), run)
            self.write_status(b'{"payload":{"updated": ' + b"1" * run + b", ")
            n, source, _ = ps.previous_updated_detail(self.status)
            self.assertEqual((n, source), (None, "no-stamp"), run)
        # A sane candidate beside an absurd one is still found.
        self.write_status(b'{"updated": ' + b"1" * 4301 + b', "updated": 1757462400, ')
        n, source, _ = ps.previous_updated_detail(self.status)
        self.assertEqual((n, source), (T, "scraped"))
        self.write_status(b'{"payload":{"updated": ' + b"1" * 4301)
        stamp, floor, _ = ps.next_updated(self.status, now=T,
                                          warn=self.warn, note_path=self.note)
        self.assertEqual((stamp, floor), (T, None))

    def test_f6_parseable_files_are_never_scraped(self):
        # Valid JSON whose "updated" is unusable is a hand-edit, not damage,
        # and a zero in it must not be rounded up to 999999999.
        for doc in ({"payload": {"updated": 0, "revoked": []}, "sig": "x"},
                    {"payload": {"updated": -7, "revoked": []}, "sig": "x"},
                    {"payload": {"updated": "later", "revoked": ["\"updated\": 9"]},
                     "sig": "x"}):
            self.write_status(json.dumps(doc, indent=1) + "\n")
            n, source, complaint = ps.previous_updated_detail(self.status)
            self.assertEqual((n, source), (None, "no-stamp"), doc)
            self.assertIn("parses as JSON", complaint)


class NextUpdated(Sandbox):

    def test_8_monotonic_under_pinned_clock(self):
        now = T
        seen = []
        for _ in range(25):
            stamp, floor, _ = ps.next_updated(self.status, now=now,
                                              warn=self.warn, note_path=self.note)
            if seen:
                self.assertGreater(stamp, seen[-1])
            seen.append(stamp)
            self.assertTrue(ps.write_stamp_note(self.note, stamp, warn=self.warn))
            self.write_status(status_text(updated=stamp))
        self.assertEqual(seen, sorted(set(seen)))
        self.assertEqual(seen[0], T)
        self.assertEqual(seen[-1], T + 24)

    def test_9_backwards_clock(self):
        self.write_status(status_text(updated=T))
        stamp, floor, note = ps.next_updated(self.status, now=T - 3600,
                                             warn=self.warn, note_path=self.note)
        self.assertEqual(floor, T)
        self.assertEqual(stamp, T + 1)
        self.assertTrue(any("not ahead of the floor" in w for w in self.warnings))
        self.assertIn("floor + 1", note)

    def test_9b_ordinary_publish_is_silent(self):
        self.write_status(status_text(updated=T))
        ps.write_stamp_note(self.note, T, warn=self.warn)
        stamp, floor, _ = ps.next_updated(self.status, now=T + 60,
                                          warn=self.warn, note_path=self.note)
        self.assertEqual((stamp, floor), (T + 60, T))
        self.assertEqual(self.warnings, [])

    def test_9c_no_floor_anywhere(self):
        stamp, floor, _ = ps.next_updated(self.status, now=T,
                                          warn=self.warn, note_path=self.note)
        self.assertEqual((stamp, floor), (T, None))
        self.assertEqual(self.warnings, [])

    def test_10_note_wins_over_a_lower_padded_floor(self):
        text = status_text(updated=T)
        start, _ = self.offset_of_updated_digits(text)
        self.cut_at(text, start + 3)          # "175" -> 1759999999
        higher_note = 1760000000
        ps.write_stamp_note(self.note, higher_note, warn=self.warn)
        stamp, floor, _ = ps.next_updated(self.status, now=T,
                                          warn=self.warn, note_path=self.note)
        self.assertEqual(floor, higher_note)
        self.assertEqual(stamp, higher_note + 1)
        self.assertTrue(any("1759999999" in w for w in self.warnings))

    def test_10b_padded_floor_wins_over_a_lower_note(self):
        text = status_text(updated=T)
        start, _ = self.offset_of_updated_digits(text)
        self.cut_at(text, start + 3)          # "175" -> 1759999999
        ps.write_stamp_note(self.note, T - 10, warn=self.warn)
        stamp, floor, _ = ps.next_updated(self.status, now=T,
                                          warn=self.warn, note_path=self.note)
        self.assertEqual(floor, 1759999999)
        self.assertEqual(stamp, 1760000000)
        self.assertGreater(stamp, T)
        joined = "\n".join(self.warnings)
        self.assertIn("1759999999", joined)
        self.assertIn("ROUNDED UP", joined)

    def test_10c_padded_floor_with_no_note_still_beats_the_clock(self):
        # The case round seven left open: no note, clock "ahead" of the
        # digits that survived. The padded floor must still win.
        text = status_text(updated=2000000000)
        start, _ = self.offset_of_updated_digits(text)
        self.cut_at(text, start + 9)          # "200000000" -> 2000000009
        stamp, floor, _ = ps.next_updated(self.status, now=T,
                                          warn=self.warn, note_path=None)
        self.assertEqual(floor, 2000000009)
        self.assertEqual(stamp, 2000000010)
        self.assertGreater(stamp, 2000000000)

    def test_10d_padded_floor_with_no_note_path(self):
        text = status_text(updated=T)
        start, _ = self.offset_of_updated_digits(text)
        self.cut_at(text, start + 5)
        stamp, floor, _ = ps.next_updated(self.status, now=T,
                                          warn=self.warn, note_path=None)
        self.assertGreaterEqual(floor, T)
        self.assertGreater(stamp, floor)


class StampNote(Sandbox):

    def test_round_trip(self):
        self.assertIsNone(ps.read_stamp_note(self.note, warn=self.warn))
        self.assertTrue(ps.write_stamp_note(self.note, T, warn=self.warn))
        self.assertEqual(ps.read_stamp_note(self.note, warn=self.warn), T)
        with open(self.note, "rb") as fh:
            self.assertEqual(fh.read(), ("%d\n" % T).encode("ascii"))

    def test_never_lowers(self):
        ps.write_stamp_note(self.note, T + 100, warn=self.warn)
        ps.write_stamp_note(self.note, T, warn=self.warn)
        self.assertEqual(ps.read_stamp_note(self.note, warn=self.warn), T + 100)

    def test_partial_note_is_refused_not_read_short(self):
        for body in ("", "  ", "17574", "1757462400x", "-5", "0", "1.5", "abc\n"):
            with open(self.note, "w", encoding="utf-8") as fh:
                fh.write(body)
            self.warnings = []
            got = ps.read_stamp_note(self.note, warn=self.warn)
            if body.strip() == "17574":
                # A whole small integer is still a whole integer: the note is
                # not the place where padding applies, and 17574 is a valid
                # (if ancient) stamp. It is simply lower and loses to the file.
                self.assertEqual(got, 17574)
            else:
                self.assertIsNone(got, body)

    def test_write_failure_is_loud_not_fatal(self):
        bad = os.path.join(self.dir, "missing-dir", "note")
        self.assertFalse(ps.write_stamp_note(bad, T, warn=self.warn))
        self.assertTrue(any("could not write" in w for w in self.warnings))


class PublicSurface(unittest.TestCase):

    def test_names_and_shapes(self):
        for name in ("previous_updated", "previous_updated_detail", "next_updated",
                     "read_stamp_note", "write_stamp_note", "stamp_note_path",
                     "pad_truncated_stamp", "STAMP_NOTE_SUFFIX"):
            self.assertTrue(hasattr(ps, name), name)
        self.assertEqual(ps.stamp_note_path("k.igk"), "k.igk.laststamp")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "status.json")
            self.assertIsNone(ps.previous_updated(p))
            self.assertEqual(len(ps.previous_updated_detail(p)), 3)
            self.assertEqual(len(ps.next_updated(p, now=T, warn=lambda m: None)), 3)


if __name__ == "__main__":
    unittest.main(verbosity=1)
