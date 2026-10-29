"""Phase 1 integration tests: real dict.cc lookups (require dict/ + built index)."""
import os
import sys
import unittest

sys.path.insert(0, r"C:\user_data\Repos\AnkiExt")

from config import REPO_ROOT, load_config  # noqa: E402
from dictlookup.lookup import Dictionary  # noqa: E402

_DIC = load_config()["dictionary"]
_HAS_DICT_FILES = (
    os.path.exists(os.path.join(REPO_ROOT, _DIC["dict_dir"], _DIC.get("en_de", "")))
    and os.path.exists(os.path.join(REPO_ROOT, _DIC["dict_dir"], _DIC.get("pl_de", "")))
)


@unittest.skipUnless(_HAS_DICT_FILES,
                     "dict.cc files not present; add them to dict/ before running")
class TestLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = Dictionary(load_config())

    @classmethod
    def tearDownClass(cls):
        cls.d.close()

    def test_english_house(self):
        hits = self.d.lookup("house", lang="en")
        self.assertTrue(any(h.german == "Haus" and h.article == "das" for h in hits),
                        f"no 'Haus' in {[(h.german, h.article) for h in hits]}")

    def test_english_dog(self):
        hits = self.d.lookup("dog", lang="en")
        self.assertTrue(any(h.german == "Hund" and h.article == "der" for h in hits),
                        f"no 'Hund' in {[(h.german, h.article) for h in hits]}")

    def test_polish_pies(self):
        hits = self.d.lookup("pies", lang="pl")
        self.assertTrue(any(h.german == "Hund" and h.article == "der" for h in hits),
                        f"no 'Hund' in {[(h.german, h.article) for h in hits]}")

    def test_polish_dom_haus(self):
        hits = self.d.lookup("dom", lang="pl")
        self.assertTrue(any(h.german == "Haus" and h.article == "das" for h in hits),
                        f"no 'Haus' in {[(h.german, h.article) for h in hits]}")

    def test_polish_kot(self):
        hits = self.d.lookup("kot", lang="pl")
        self.assertTrue(any(h.german == "Katze" and h.article == "die" for h in hits),
                        f"no 'Katze' in {[(h.german, h.article) for h in hits]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)