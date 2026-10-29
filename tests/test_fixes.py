"""Regression tests for previously-identified fixes (no network, no live Anki)."""
import io
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, r"C:\user_data\Repos\AnkiExt")

from config import REPO_ROOT, load_config  # noqa: E402
from detect_lang import detect_language  # noqa: E402
from cards.anki_setup import note_fields, MODEL_FIELDS  # noqa: E402
from cards.builder import CardCandidate  # noqa: E402
from engine import clean_source  # noqa: E402


class TestDetectCollidingStopwords(unittest.TestCase):
    """N4/#6: bare English/German words must not be misdetected as Polish."""

    def test_lone_to(self):
        self.assertEqual(detect_language("to"), "en")

    def test_lone_do(self):
        self.assertEqual(detect_language("do"), "en")

    def test_lone_w(self):
        self.assertEqual(detect_language("w"), "en")

    def test_lone_z(self):
        self.assertEqual(detect_language("z"), "en")

    def test_lone_na(self):
        self.assertEqual(detect_language("na"), "en")

    def test_sie_still_polish(self):
        self.assertEqual(detect_language("się"), "pl")

    def test_unambiguous_signal(self):
        self.assertEqual(detect_language("nie wiem"), "pl")

    def test_no_polish_stopwords_const(self):
        # The unused module constant must be gone.
        import detect_lang as dl
        self.assertFalse(hasattr(dl, "POLISH_STOPWORDS"))


class TestNoteFieldsCasing(unittest.TestCase):
    """#14/#10: note_fields keys use exact MODEL_FIELDS casing."""

    def test_keys_match_model_fields(self):
        c = CardCandidate(source="dog", source_lang="en", german="Hund",
                          article="der", plural="Hunde", plural_article="die")
        f = note_fields(c)
        self.assertEqual(set(f.keys()), set(MODEL_FIELDS))
        self.assertEqual(f["Word"], "der Hund")
        self.assertEqual(f["Plural"], "die Hunde")
        self.assertEqual(f["Source"], "dog")


class TestCleanSource(unittest.TestCase):
    """N2: kaikki translation words must be cleaned before going on a card."""

    def test_strips_brackets(self):
        self.assertEqual(clean_source("Hund [ugs.]"), "Hund")

    def test_strips_gender_markers(self):
        self.assertEqual(clean_source("Dom {m}"), "Dom")

    def test_strips_angle_abbrevs(self):
        self.assertEqual(clean_source("Katze <anat>"), "Katze")

    def test_normalizes_whitespace(self):
        self.assertEqual(clean_source("  Auto   ", ), "Auto")


class TestCliCleanupNoteId(unittest.TestCase):
    """N1: cli_cleanup must use noteId (not id) when deleting tagged notes."""

    def test_default_branch_uses_note_id(self):
        import cli_cleanup
        fake = mock.Mock()
        fake.find_notes.return_value = [100, 101]
        fake.notes_info.return_value = [
            {"noteId": 100, "fields": {"Source": {"value": "dog"},
                                       "Word": {"value": "der Hund"}}},
            {"noteId": 101, "fields": {"Source": {"value": "cat"},
                                       "Word": {"value": "die Katze"}}},
        ]
        argv = ["cli_cleanup.py", "--yes"]
        with mock.patch.object(cli_cleanup, "AnkiConnect", return_value=fake), \
             mock.patch("sys.stdout", new_callable=io.StringIO):
            rc = cli_cleanup.main(argv)
        self.assertEqual(rc, 0)
        # deleteNotes must be called with noteId values, never [None]
        calls = [c for c in fake._request.call_args_list if c.args[0] == "deleteNotes"]
        self.assertTrue(calls, "deleteNotes not called on --yes")
        _, params = calls[-1].args
        self.assertEqual(params["notes"], [100, 101])


if __name__ == "__main__":
    unittest.main(verbosity=2)
