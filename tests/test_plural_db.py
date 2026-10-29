"""Phase 2 tests: plural DB lookups (requires data/plural.db built)."""
import os
import sys
import unittest

sys.path.insert(0, r"C:\user_data\Repos\AnkiExt")

from config import load_config  # noqa: E402
from german.plural import PluralDB  # noqa: E402


@unittest.skipUnless(
    os.path.exists(load_config()["dictionary"]["plural_db"]),
    "plural.db not built; run python -m german.build_plural_db first",
)
class TestPluralDB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = load_config()
        cls.db = PluralDB(cfg["dictionary"]["plural_db"])

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def _check(self, lemma, article, plural):
        info = self.db.lookup(lemma)
        self.assertIsNotNone(info, f"{lemma} missing from plural DB")
        self.assertEqual(info["article"], article, f"{lemma} article")
        self.assertEqual(info["plural"], plural, f"{lemma} plural")

    def test_haus(self):
        self._check("Haus", "das", "Häuser")

    def test_hund(self):
        self._check("Hund", "der", "Hunde")

    def test_katze(self):
        self._check("Katze", "die", "Katzen")

    def test_auto(self):
        self._check("Auto", "das", "Autos")

    def test_frau(self):
        self._check("Frau", "die", "Frauen")

    def test_buch(self):
        self._check("Buch", "das", "Bücher")

    def test_missing(self):
        self.assertIsNone(self.db.lookup("zzzznotawordzzz"))

    def test_reverse_house(self):
        res = self.db.reverse_lookup("house", "en", limit=5)
        self.assertTrue(any(r["lemma"] == "Haus" for r in res),
                        f"no Haus in {res}")

    def test_reverse_pies(self):
        res = self.db.reverse_lookup("pies", "pl", limit=5)
        self.assertTrue(any(r["lemma"] == "Hund" for r in res),
                        f"no Hund in {res}")

    def test_reverse_window(self):
        res = self.db.reverse_lookup("window", "en", limit=5)
        self.assertTrue(any(r["lemma"] == "Fenster" for r in res),
                        f"no Fenster in {res}")

    def test_mann_plural(self):
        # Mann has multiple plurals (Männer/Mannen) — must be non-empty
        info = self.db.lookup("Mann")
        self.assertTrue(info["has_plural"])

    def test_resolve_inflected_form(self):
        # 'ging' is the past tense of 'gehen'; 'Häuser' is plural of 'Haus'.
        # resolve_form returns the display-cased lemma (Haus), not the folded key.
        if "inflections" not in [r[0] for r in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]:
            self.skipTest("inflections index not present (rebuild plural.db)")
        self.assertEqual(self.db.resolve_form("ging"), "gehen")
        self.assertEqual(self.db.resolve_form("Häuser"), "Haus")
        self.assertEqual(self.db.resolve_form("Händen"), "Hand")
        self.assertEqual(self.db.resolve_form("roten"), "rot")
        self.assertEqual(self.db.resolve_form("bessere"), "gut")


if __name__ == "__main__":
    unittest.main(verbosity=2)