"""Matching tests: matcher scoring tiers + morphology + inflection resolution.

Unit tests for the new scoring logic (dictlookup.matcher, morphology) and the
engine-level inflection flow.  The engine/plural-db tests are guarded because
they need the real dictionary index / rebuilt plural.db.
"""
import os
import sys
import unittest

sys.path.insert(0, r"C:\user_data\Repos\AnkiExt")

from dictlookup.morphology import english_candidates, nfc                  # noqa: E402
from dictlookup.matcher import (                                           # noqa: E402
    EXACT, STEM, PREFIX, ORTHVAR, _prefix_confidence)
from dictlookup.search import normalize_key                                # noqa: E402

from config import load_config                      # noqa: E402
from dictlookup.lookup import Dictionary            # noqa: E402
from dictlookup.analyzers import Analyzers          # noqa: E402
from german.plural import PluralDB                  # noqa: E402
from cards.builder import CardCandidate, CardBuilder  # noqa: E402
from engine import build_candidates, german_candidates  # noqa: E402

try:
    import dwdsmor  # noqa: F401
    HAS_DWDSMOR = True
except Exception:
    HAS_DWDSMOR = False

_DIC = load_config()["dictionary"]
_HAS_FILES = os.path.exists(_DIC["plural_db"])  # config-resolved (not CWD-relative)

# True only when data/plural.db has the rebuilt `inflections` schema with the
# `pos` column (so a stale pre-rebuild db skips the new resolution tests).
def _has_inflection_pos() -> bool:
    if not _HAS_FILES:
        return False
    try:
        import sqlite3
        from config import load_config as _lc
        conn = sqlite3.connect(_lc()["dictionary"]["plural_db"])
        cols = [r[1] for r in conn.execute("PRAGMA table_info(inflections)")]
        conn.close()
        return "pos" in cols and "lemma_display" in cols
    except Exception:
        return False

_HAS_NEW_SCHEME = _HAS_FILES and _has_inflection_pos()



class TestMorphology(unittest.TestCase):
    def test_english_irregular(self):
        self.assertIn("go", english_candidates("went"))
        self.assertIn("go", english_candidates("goes"))
        self.assertIn("child", english_candidates("children"))

    def test_english_regular(self):
        self.assertIn("study", english_candidates("studies"))
        self.assertIn("house", english_candidates("houses"))
        self.assertIn("dog", english_candidates("dogs"))

    def test_nfc(self):
        self.assertEqual(nfc("Häuser"), "Häuser")


class TestMatcherScoring(unittest.TestCase):
    def test_prefix_confidence(self):
        # a prefix that covers most of the key scores higher than a short one
        self.assertGreater(_prefix_confidence("when", "whentweaking"),
                           _prefix_confidence("wh", "whentweaking"))
        self.assertEqual(_prefix_confidence("", "abc"), 0.0)

    def test_card_candidate_defaults(self):
        c = CardCandidate(source="a", source_lang="en", german="b")
        self.assertEqual(c.confidence, 1.0)
        self.assertEqual(c.method, "exact")


@unittest.skipUnless(_HAS_FILES, "plural.db / dict index not present")
class TestEngineInflection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = load_config()
        cls.plural = PluralDB(cfg["dictionary"]["plural_db"])
        cls.dict = Dictionary(cfg, resolve_form=cls.plural.resolve_form)
        cls.builder = CardBuilder(cls.plural)

    @classmethod
    def tearDownClass(cls):
        cls.dict.close()
        cls.plural.close()

    def _lemmas(self, word, lang="en"):
        return [c.german for c in
                build_candidates(word, lang, self.dict, self.plural,
                                 self.builder, wikt=None,
                                 max_candidates=5, total_cap=15)]

    def test_english_irregular_verbs(self):
        # 'drank' is the past of 'drink'; the sentence form has no exact key in
        # the EN index, so it must resolve via morphology (drank->drink) to a
        # German card ("Getränk"/"Trinken").
        cands = build_candidates("drank", "en", self.dict, self.plural,
                                 self.builder, wikt=None,
                                 max_candidates=5, total_cap=15)
        self.assertTrue(cands, "drank produced no candidates")
        self.assertTrue(any(c.source.casefold() == "drink" for c in cands),
                        f"no stemmed drink source in {[c.source for c in cands[:8]]}")

    def test_german_inflected_resolves(self):
        # 'Häuser' (plural) must route to the 'Haus' lemma and its English 'house'
        cands, info = german_candidates("Häuser", self.plural, dictionary=self.dict)
        self.assertEqual(info.get("lemma"), "Haus")
        self.assertTrue(any(c.source.casefold() == "house" for c in cands),
                        f"no house in {[c.source for c in cands]}")

    def test_confidence_tag_present(self):
        cands = build_candidates("dogs", "en", self.dict, self.plural,
                                 self.builder, wikt=None,
                                 max_candidates=5, total_cap=15)
        for c in cands:
            self.assertGreaterEqual(c.confidence, 0.0)



@unittest.skipUnless(_HAS_FILES and _HAS_NEW_SCHEME, "rebuilt plural.db (inflections pos/lemma_display) missing")
class TestGermanBaseResolution(unittest.TestCase):
    """German inflected selections must resolve to their true base word."""

    @classmethod
    def setUpClass(cls):
        cfg = load_config()
        cls.plural = PluralDB(cfg["dictionary"]["plural_db"])
        cls.dict = Dictionary(cfg, resolve_form=cls.plural.resolve_form)

    @classmethod
    def tearDownClass(cls):
        cls.dict.close()
        cls.plural.close()

    def _german(self, word):
        cands, _info = german_candidates(word, self.plural, dictionary=self.dict)
        return cands[0].german if cands else None

    def _cards(self, word):
        cands, _info = german_candidates(word, self.plural, dictionary=self.dict)
        return [(c.word_field, c.pos) for c in cands]

    def test_inflected_adjective_gets_true_base(self):
        for word, want in {"roten": "rot", "bessere": "gut", "besten": "gut",
                          "laufende": "laufend", "viele": "viel"}.items():
            got = self._german(word)
            self.assertEqual(got, want, f"{word!r} -> {got!r} != {want!r}")

    def test_plural_noun_keeps_singular_head(self):
        for word, want in {"Häuser": "Haus", "Hunde": "Hund", "Tagen": "Tag"}.items():
            got = self._german(word)
            self.assertEqual(got, want, f"{word!r} -> {got!r} != {want!r}")

    def test_german_verb_shows_infinitive_with_deverbal_alt(self):
        # 'spricht' must produce 'sprechen' ("to speak"), NOT 'das Sprechen'
        # ("speech"); the deverbal noun is offered as a further group.
        self.assertEqual(self._german("spricht"), "sprechen")
        self.assertEqual(self._german("ging"), "gehen")
        self.assertEqual(self._german("gelaufen"), "laufen")
        cards = self._cards("spricht")
        self.assertEqual(cards[0], ("sprechen", "verb"))
        self.assertTrue(any(f == "das Sprechen" and p == "noun"
                            for f, p in cards),
                        f"no 'das Sprechen' noun alternative in {cards}")

    def test_own_headword_stays_itself(self):
        self.assertEqual(self._german("bereit"), "bereit")


@unittest.skipUnless(_HAS_FILES, "dict index not present")
class TestOrthVariantMatching(unittest.TestCase):
    """Orthographic variants must surface as ORTHVAR hits (fuehlen -> fühlen)."""

    @classmethod
    def setUpClass(cls):
        cfg = load_config()
        cls.plural = PluralDB(cfg["dictionary"]["plural_db"])
        cls.dict = Dictionary(cfg, resolve_form=cls.plural.resolve_form)
        cls.an = Analyzers(cfg.get("morphology"))

    @classmethod
    def tearDownClass(cls):
        cls.dict.close()
        cls.plural.close()

    def test_ue_orthvar_hit(self):
        # 'fuehlen' has no literal 'ue' entry, so the umlaut variant
        # 'fühlen' is the canonical match (method=orthvar).
        hits = self.dict.lookup_german("fuehlen", limit=5)
        self.assertTrue(hits, "no hits for 'fuehlen'")
        self.assertEqual(hits[0].source, "fühlen", msg=f"got {hits[0].source!r}")
        self.assertEqual(hits[0].method, "orthvar")


@unittest.skipUnless(_HAS_FILES, "dict index not present")
class TestAnalyzerEngineFlow(unittest.TestCase):
    """Real-morphology lemmas must reach cards via the engine."""

    @classmethod
    def setUpClass(cls):
        cfg = load_config()
        cls.plural = PluralDB(cfg["dictionary"]["plural_db"])
        cls.an = Analyzers(cfg.get("morphology"))
        cls.dict = Dictionary(cfg, resolve_form=cls.plural.resolve_form,
                              analyzers=cls.an)
        cls.builder = CardBuilder(cls.plural)

    @classmethod
    def tearDownClass(cls):
        cls.dict.close()
        cls.plural.close()

    def test_polish_inflected_via_morfeusz(self):
        if not self.an.available.get("pl"):
            self.skipTest("morfeusz2 not installed")
        cands = build_candidates("dziewczyny", "pl", self.dict, self.plural,
                                 self.builder, wikt=None,
                                 max_candidates=5, total_cap=15,
                                 analyzers=self.an)
        self.assertTrue(any(c.german.casefold() in ("mädchen", "freundin")
                            for c in cands),
                        f"no German girl-word for dziewczyny in {[c.german for c in cands]}")

    @unittest.skipUnless(HAS_DWDSMOR, "dwdsmor not installed")
    def test_german_unseen_form_routes_via_dwdsmor(self):
        # The DWDSmor branch fires only when kaikki does NOT know the form.
        # 'grosse' IS in the current kaikki index, so use a fake analyzers
        # whose dwdsmor resolves a form kaikki misses — this actually crosses
        # engine.py's dwdsmor branch instead of silently passing via kaikki.
        clazz = type(self)

        try:
            from dictlookup.analyzers import Analyzers
        except ImportError:
            self.skipTest("analyzers unavailable")
            return

        class _StubAnalyzers:
            available = {"en": True, "pl": True, "de": True}

            @staticmethod
            def analyze(w, lang="de"):
                if lang == "de" and w.casefold() == "xyzzy":
                    return ({"lemma": "Fenster", "pos": "noun"},)
                return ()

            @staticmethod
            def lemma_of(w, lang="de"):
                a = _StubAnalyzers.analyze(w, lang)
                return a[0]["lemma"] if a else None

            @staticmethod
            def de_gender(lemma):
                return "n" if lemma == "Fenster" else None

            @staticmethod
            def de_article(lemma):
                return "das" if lemma == "Fenster" else ""

            @staticmethod
            def de_plural(lemma):
                return "Fenster" if lemma == "Fenster" else None

            @staticmethod
            def de_freq(lemma):
                return None

        # a word kaikki does not know
        cands, info = german_candidates("xyzzy", self.plural,
                                        dictionary=self.dict, analyzers=_StubAnalyzers())
        # noun branch sets info to the grammar dict (article/plural), not a
        # 'lemma' key — the proof is the card itself.
        self.assertTrue(cands and cands[0].german == "Fenster",
                        f"xyzzy should card Fenster via dwdsmor, got {[c.german for c in cands]}")
        self.assertEqual(cands[0].article, "das")
        self.assertEqual(cands[0].plural_field, "die Fenster")

    def test_german_known_form_still_kaikki_first(self):
        # 'Häuser' / 'grosse' resolve through kaikki when it knows them, even
        # if an analyzer would also resolve them — dwdsmor must not shadow.
        for w, want in {"Häuser": "Haus", "grosse": "groß"}.items():
            cands, info = german_candidates(w, self.plural,
                                            dictionary=self.dict, analyzers=self.an)
            self.assertEqual(info.get("lemma"), want, f"{w} -> {info}")
            self.assertTrue(cands and cands[0].german == want,
                            f"{w} should card {want}, got {[c.german for c in cands]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)