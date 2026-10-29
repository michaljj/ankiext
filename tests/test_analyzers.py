"""Analyzers facade tests: contract, fallback equivalence, real-engine cases."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dictlookup.analyzers import Analyzers  # noqa: E402
from dictlookup.morphology import candidates as heuristic  # noqa: E402

try:
    import spacy  # noqa: F401
    HAS_SPACY = True
except Exception:
    HAS_SPACY = False
try:
    import morfeusz2  # noqa: F401
    HAS_MORFEUSZ = True
except Exception:
    HAS_MORFEUSZ = False


class TestAnalyzersContract(unittest.TestCase):
    def test_available_flags_exist(self):
        a = Analyzers()
        for lang in ("en", "pl", "de"):
            self.assertIn(lang, a.available)
            self.assertIsInstance(a.available[lang], bool)

    def test_disabled_engines_fall_back_to_heuristics(self):
        # The config enable flags must actually disengage the engines (not
        # just be stored): available[*] -> False and candidates() == heuristics.
        a = Analyzers({"en_spacy": False, "pl_morfeusz": False, "dwdsmor": False,
                       "freq_rank": False})
        for lang in ("en", "pl", "de"):
            self.assertFalse(a.available[lang], f"{lang} engine should be off")
        cases = [("went", "en"), ("dogs", "en"), ("psami", "pl"), ("ging", "de")]
        for word, lang in cases:
            self.assertEqual(a.candidates(word, lang),
                             tuple(heuristic(word, lang)),
                             f"candidates({word!r},{lang!r}) must equal heuristics")

    def test_empty_input(self):
        a = Analyzers()
        self.assertEqual(a.candidates("", "en"), ())
        self.assertEqual(a.analyze("  ", "de"), ())

    def test_none_input_is_safe(self):
        # None into the German helpers used to segfault the process through
        # the native sfst transducer — must now return False/None cleanly.
        a = Analyzers()
        self.assertFalse(a.is_german(None))
        self.assertIsNone(a.de_plural(None))
        self.assertIsNone(a.de_gender(None))
        self.assertEqual(a.de_article(None), "")
        self.assertIsNone(a.de_freq(None))
        self.assertEqual(a.analyze(None, "en"), ())
        self.assertEqual(a.candidates(None, "pl"), ())

    def test_analysis_dicts_are_immutable(self):
        # lru_cache must not hand out mutable dicts that callers can poison.
        a = Analyzers()
        an = a.analyze("went", "en")
        with self.assertRaises(TypeError):
            an[0]["lemma"] = "EVIL"
        # cache unaffected by a failed mutation attempt
        self.assertEqual(a.analyze("went", "en"), an)

    def test_nfc_normalized_input(self):
        # composed "Häuser" and decomposed "Ha\u0308user" must hit the same
        # cache entry and produce the same lemma.
        a = Analyzers()
        composed = "Häuser"
        decomposed = "Ha\u0308user"
        self.assertEqual(a.analyze(composed, "de"), a.analyze(decomposed, "de"))


@unittest.skipUnless(HAS_SPACY, "spaCy not installed")
class TestAnalyzerEnglish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = Analyzers()

    def test_went_to_go(self):
        an = self.a.analyze("went", "en")
        self.assertEqual(an[0]["lemma"], "go")
        self.assertEqual(an[0]["pos"], "verb")

    def test_children_to_child(self):
        self.assertEqual(self.a.lemma_of("children", "en"), "child")

    def test_better_supplements_good(self):
        # spaCy gives 'well' (ADV); our override adds 'good' for the lookup
        lemmas = [d["lemma"] for d in self.a.analyze("better", "en")]
        self.assertIn("well", lemmas)
        self.assertIn("good", lemmas)


@unittest.skipUnless(HAS_MORFEUSZ, "morfeusz2 not installed")
class TestAnalyzerPolish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = Analyzers()

    def test_psami_to_pies(self):
        self.assertEqual(self.a.lemma_of("psami", "pl"), "pies")

    def test_dziewczyny_to_dziewczyna(self):
        self.assertEqual(self.a.lemma_of("dziewczyny", "pl"), "dziewczyna")

    def test_position_noun(self):
        an = self.a.analyze("psami", "pl")
        self.assertEqual(an[0]["pos"], "noun")

    def test_movable_clitic_verb_lemma(self):
        # morfeusz2 splits these into (stem, aglt) segments; the analyzer
        # must re-merge them into a whole-token reading, not drop them.
        cases = {"proponowaliśmy": "proponować",
                 "zrobiliście": "zrobić",
                 "widziałem": "widzieć",
                 "poszedłbym": "pójść"}
        for form, lemma in cases.items():
            self.assertEqual(self.a.lemma_of(form, "pl"), lemma,
                             f"lemma_of({form!r}) should be {lemma!r}")

    def test_movable_clitic_is_verb(self):
        an = self.a.analyze("proponowaliśmy", "pl")
        self.assertEqual(an[0]["lemma"], "proponować")
        self.assertEqual(an[0]["pos"], "verb")

    def test_movable_clitic_person_folded_into_tag(self):
        # praet (past) tag + aglt person: 1st pl -> "pri", 2nd pl -> "sec"
        an = self.a.analyze("proponowaliśmy", "pl")
        self.assertIn("pri", an[0]["tag"])
        self.assertEqual(an[0]["morph"].get("person"), "pri")
        an2 = self.a.analyze("zrobiliście", "pl")
        self.assertIn("sec", an2[0]["tag"])
        self.assertEqual(an2[0]["morph"].get("person"), "sec")

    def test_multi_token_input_has_no_whole_token_reading(self):
        # single-word API contract: 'ma kota' must stay an empty analysis
        # (the segments tile two tokens, not one word).
        self.assertEqual(self.a.analyze("ma kota", "pl"), ())


if __name__ == "__main__":
    unittest.main(verbosity=2)