"""Phase 1 unit tests: dict.cc entity handling."""
import sys
import unittest

sys.path.insert(0, r"C:\user_data\Repos\AnkiExt")

from dictlookup.entities import clean_term, decode_html, extract_gender, split_line  # noqa: E402


class TestEntities(unittest.TestCase):
    def test_decode_html(self):
        self.assertEqual(decode_html("&#945;-Keratin"), "α-Keratin")
        self.assertEqual(decode_html("&#346;winouj&#347;cie"), "Świnoujście")
        self.assertEqual(decode_html("A &amp; B"), "A & B")

    def test_extract_gender_simple(self):
        cleaned, info = extract_gender("Haus {n} [Gebäude]")
        self.assertEqual(cleaned, "Haus")
        self.assertEqual(info.genders, ["n"])
        self.assertEqual(info.article, "das")

    def test_extract_gender_mixed(self):
        cleaned, info = extract_gender("Sedna {f} {m}")
        self.assertEqual(info.genders, ["f", "m"])
        self.assertEqual(info.article, "die/der")

    def test_extract_gender_plural_only(self):
        cleaned, info = extract_gender("Eltern {pl}")
        self.assertEqual(info.genders, ["pl"])
        self.assertEqual(info.article, "die")

    def test_extract_gender_none(self):
        cleaned, info = extract_gender("Haus")
        self.assertEqual(cleaned, "Haus")
        self.assertEqual(info.genders, [])
        self.assertEqual(info.article, "")

    def test_clean_term(self):
        self.assertEqual(clean_term("(der) Hund {m} [ugs.] [zool.]"), "Hund")
        self.assertEqual(clean_term("Auto {n} <Autos>"), "Auto")

    def test_split_line(self):
        self.assertEqual(split_line("# comment"), ("", "", "", ""))
        s, t, p, tg = split_line("dog\tHund {m}\tnoun\t[zool.] \n")
        self.assertEqual((s, t, p, tg), ("dog", "Hund {m}", "noun", "[zool.]"))


if __name__ == "__main__":
    unittest.main(verbosity=2)