"""DWDSmor adapter tests: contract with a stub + real-FST skipUnless cases."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from german.dwdsmor import DwdsmorMorph  # noqa: E402

try:
    import dwdsmor  # noqa: F401
    HAS_DWDSMOR = True
except Exception:
    HAS_DWDSMOR = False


class _StubDwdsmorMorph(DwdsmorMorph):
    """A fake adapter with a canned analysis table (no real engine)."""

    def __init__(self):
        super().__init__()
        self.available = True
        self._mod = None
        self._freqs = {"Haus": 20.0}
        self._an = object()
        self._table = {
            "ging": [("gehen", "V")],
            "Hunden": [("Hund", "NN")],
            "grosse": [("groß", "ADJ")],
        }

    def _raw_analyses(self, word):
        rows = self._table.get(word.casefold()) or self._table.get(word)
        return tuple((lemma, pos, _FakeT) for lemma, pos in (rows or []))

    def is_german(self, word):
        return word.casefold() in self._table or word in self._table


class _FakeT:
    gender = None
    number = None
    case = None
    nonfinite = None
    auxiliary = None
    tense = None
    degree = None
    metainfo = None
    spec = ""
    pos = None
    analysis = ""


class TestDwdsmorContract(unittest.TestCase):
    def test_available_flag(self):
        m = DwdsmorMorph()
        # on this machine dwdsmor is installed; the flag must reflect reality
        self.assertIsInstance(m.available, bool)

    def test_unavailable_returns_empty(self):
        m = DwdsmorMorph()
        m.available = False
        m._mod = None
        m._an = None
        self.assertEqual(m.analyze("irgendwas"), [])
        self.assertIsNone(m.lemma_of("irgendwas"))
        self.assertIsNone(m.pos_of("irgendwas"))
        self.assertFalse(m.is_german("irgendwas"))

    def test_none_input_is_safe(self):
        # Non-str into the adapter used to raise a NATIVE access violation
        # (0xC0000005) through sfst_transduce — must be guarded.
        m = DwdsmorMorph()
        if m.available:
            self.assertEqual(m.analyze(None), [])
            self.assertIsNone(m.lemma_of(None))
            self.assertIsNone(m.pos_of(None))
            self.assertFalse(m.is_german(None))
            self.assertIsNone(m.plural_of(None))
            self.assertIsNone(m.gender_of(None))
            self.assertIsNone(m.freq(None))
        else:
            self.skipTest("dwdsmor not installed — adapter is inert anyway")

    @unittest.skipUnless(HAS_DWDSMOR, "dwdsmor not installed")
    def test_real_analysis(self):
        m = DwdsmorMorph("")
        an = m.analyze("ging")
        self.assertTrue(an, "no analysis for 'ging'")
        self.assertEqual(an[0]["lemma"], "gehen")
        self.assertEqual(an[0]["pos"], "verb")

    @unittest.skipUnless(HAS_DWDSMOR, "dwdsmor not installed")
    def test_real_gender_and_plural(self):
        m = DwdsmorMorph("")
        # Haus is in the open edition with a generated plural
        self.assertEqual(m.gender_of("Haus"), "n")
        self.assertEqual(m.plural_of("Haus"), "Häuser")
        self.assertEqual(m.article_of("Haus"), "das")


class TestDwdsmorStub(unittest.TestCase):
    def setUp(self):
        self.m = _StubDwdsmorMorph()

    def test_stub_analyze_shape(self):
        an = self.m.analyze("ging")
        self.assertEqual(an[0]["lemma"], "gehen")
        self.assertEqual(an[0]["pos"], "verb")

    def test_stub_lemma_and_pos(self):
        self.assertEqual(self.m.lemma_of("Hunden"), "Hund")
        self.assertEqual(self.m.pos_of("Hunden"), "noun")

    def test_stub_freq(self):
        self.assertEqual(self.m.freq("Haus"), 20.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)