"""Phase 3/4 unit tests: card candidate field logic + language detection."""
import sys
import unittest

sys.path.insert(0, r"C:\user_data\Repos\AnkiExt")

from cards.builder import CardCandidate  # noqa: E402
from detect_lang import detect_language  # noqa: E402
from ui.preview import _split_article  # noqa: E402


class TestCardCandidate(unittest.TestCase):
    def test_word_field_with_article(self):
        c = CardCandidate(source="pies", source_lang="pl", german="Hund",
                          article="der", plural="Hunde", plural_article="die")
        self.assertEqual(c.word_field, "der Hund")
        self.assertEqual(c.plural_field, "die Hunde")

    def test_word_field_neuter(self):
        c = CardCandidate(source="house", source_lang="en", german="Haus",
                          article="das", plural="Häuser", plural_article="die")
        self.assertEqual(c.word_field, "das Haus")
        self.assertEqual(c.plural_field, "die Häuser")

    def test_word_field_no_double_article(self):
        c = CardCandidate(source="x", source_lang="en", german="der Hund",
                          article="der", plural="", plural_article="")
        self.assertEqual(c.word_field, "der Hund")

    def test_word_field_no_article(self):
        c = CardCandidate(source="go", source_lang="en", german="gehen", article="", plural="")
        self.assertEqual(c.word_field, "gehen")

    def test_mixed_article(self):
        c = CardCandidate(source="x", source_lang="en", german="Sedna", article="die/der", plural="")
        self.assertEqual(c.word_field, "Sedna")  # ambiguous → no article prefix


class TestSplitArticle(unittest.TestCase):
    def test_split(self):
        self.assertEqual(_split_article("der Hund", "der"), ("der", "Hund"))
        self.assertEqual(_split_article("die Katze", "die"), ("die", "Katze"))
        self.assertEqual(_split_article("das Haus", "das"), ("das", "Haus"))
        self.assertEqual(_split_article("Hund", "der"), ("", "Hund"))


class TestDetect(unittest.TestCase):
    def test_diacritics(self):
        self.assertEqual(detect_language("samochód"), "pl")
        self.assertEqual(detect_language("żółw"), "pl")

    def test_english_simple(self):
        self.assertEqual(detect_language("house"), "en")
        self.assertEqual(detect_language("window"), "en")

    def test_polish_stopwords(self):
        self.assertEqual(detect_language("to jest pies"), "pl")
        self.assertEqual(detect_language("nie wiem"), "pl")

    def test_verbs(self):
        self.assertEqual(detect_language("czytać"), "pl")

    def test_empty(self):
        self.assertEqual(detect_language(""), "en")


if __name__ == "__main__":
    unittest.main(verbosity=2)