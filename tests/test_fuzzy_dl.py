"""Orthographic-variant + Damerau-Levenshtein fuzzy tests."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dictlookup.matcher import variant_keys, _damerau, _fuzzy_ok
from dictlookup.search import normalize_key


class TestVariantKeys(unittest.TestCase):
    def test_ueber_digraph(self):
        # 'ueber' must reach 'über' (new-style German 'ü' written 'ue').
        self.assertIn("über", variant_keys("ueber"))

    def test_ueber_reverse(self):
        self.assertIn("ueber", variant_keys("über"))

    def test_umlaut_digraph(self):
        self.assertIn("aether", variant_keys("äther"))
        self.assertIn("oesterreich", variant_keys("österreich"))

    def test_empty_and_self_excluded(self):
        self.assertEqual(variant_keys(""), [])
        self.assertNotIn("strasse", variant_keys("strasse"))

    def test_ss_is_not_a_variant(self):
        # 'ß'<->'ss' is handled by casefold ('straße'.casefold()=='strasse'),
        # so it must NOT be an orthographic-variant substitution — an
        # unguarded 'ss'->'ß' would invent junk ('messe'->'meße',
        # 'caesar'->'cäsar').  The strasse->straße match happens through
        # casefolded normalize_key already.
        self.assertNotIn("straße", variant_keys("strasse"))
        self.assertNotIn("meße", variant_keys("messe"))

    def test_normalize_key_handles_eszett(self):
        # 'ß' folds to 'ss' via casefold.
        self.assertEqual(normalize_key("Straße"), "strasse")


class TestDamerauLevenshtein(unittest.TestCase):
    def test_zero_and_identity(self):
        self.assertEqual(_damerau("haus", "haus"), 0)
        self.assertEqual(_damerau("", ""), 0)

    def test_transposition_counts_one(self):
        self.assertEqual(_damerau("huas", "haus"), 1)
        self.assertEqual(_damerau("house", "hosue"), 1)

    def test_substitution(self):
        self.assertEqual(_damerau("cat", "cab"), 1)

    def test_general_edit(self):
        self.assertEqual(_damerau("geschichte", "geschicte"), 1)


class TestFuzzyPolicy(unittest.TestCase):
    def test_short_word_transposition(self):
        # Huas -> Haus: 4 chars, d=1, first char matches -> accepted
        self.assertTrue(_fuzzy_ok("Huas", "Haus", 1))

    def test_medium_word_one_edit(self):
        self.assertTrue(_fuzzy_ok("studies", "studie", 1))

    def test_long_word_needs_prefix(self):
        # 8+ chars, first two chars differ -> rejected even at d<=2
        self.assertFalse(_fuzzy_ok("abcdefghi", "axcdefghi", 1))
        # same 2-char prefix, d=2 -> allowed
        self.assertTrue(_fuzzy_ok("abcdabcd", "abddabcd", 2))

    def test_too_many_edits_rejected(self):
        # 5-7 char band caps at distance 1; d=2 is rejected
        self.assertFalse(_fuzzy_ok("house", "housses", 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)