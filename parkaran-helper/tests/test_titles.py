"""Display titles written by the graph build: one verse in two scripts."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import build_graph as bg

MOOL_MANTAR = (
    "ੴ ਸਤਿ ਨਾਮੁ ਕਰਤਾ ਪੁਰਖੁ ਨਿਰਭਉ ਨਿਰਵੈਰੁ ॥",
    "ikOankaar sat naam karataa purakh nirabhau niravair ||",
)
JAP = ("॥ ਜਪੁ ॥", "|| jap ||")
AADH = ("ਆਦਿ ਸਚੁ ਜੁਗਾਦਿ ਸਚੁ ॥", "aadh sach jugaadh sach ||")


def shabad(*rows):
    return {
        "verses": [
            {"index": i, "gurmukhi": g, "transliteration": t}
            for i, (g, t) in enumerate(rows)
        ]
    }


class DisplayLineTests(unittest.TestCase):
    def lines(self, sid, shown, *rows):
        with patch.object(bg.corpus, "shabad", return_value=shabad(*rows)):
            return bg.display_lines(sid, shown)

    def test_title_transliterates_the_shown_verse(self):
        rows = (
            ("ਗਉੜੀ ਮਹਲਾ ੧ ॥", "gauRee mahalaa pehilaa ||"),
            ("ਭੈ ਭਉ ਰਾਖਿਆ ਭੈ ਸਵਾਰਿ ॥੧॥", "bhai bhau raakhiaa bhai savaar ||1||"),
        )
        self.assertEqual(
            self.lines("9", "ਭੈ ਭਉ ਰਾਖਿਆ ਭੈ ਸਵਾਰਿ", *rows),
            ("ਭੈ ਭਉ ਰਾਖਿਆ ਭੈ ਸਵਾਰਿ", "bhai bhau raakhiaa bhai savaar"),
        )

    def test_a_heading_line_moves_to_the_first_verse(self):
        rows = (
            ("ਸਾਰਗ ਛੰਤ ਮਹਲਾ ੫", "saarag chha(n)t mahalaa panjavaa"),
            ("ਸਭ ਦੇਖੀਐ ਅਨਭੈ ਕਾ ਦਾਤਾ ॥੧॥", "sabh dhekheeaai anabhai kaa dhaataa ||1||"),
        )
        self.assertEqual(
            self.lines("9", "ਸਾਰਗ ਛੰਤ ਮਹਲਾ", *rows),
            ("ਸਭ ਦੇਖੀਐ ਅਨਭੈ ਕਾ ਦਾਤਾ", "sabh dhekheeaai anabhai kaa dhaataa"),
        )

    def test_a_bare_marker_is_not_a_display_verse(self):
        self.assertEqual(
            self.lines("9", MOOL_MANTAR[0], MOOL_MANTAR, JAP, AADH),
            (AADH[0], "aadh sach jugaadh sach"),
        )

    def test_japji_keeps_the_mool_mantar(self):
        self.assertEqual(
            self.lines("1", MOOL_MANTAR[0], MOOL_MANTAR, JAP, AADH),
            (MOOL_MANTAR[0], "aadh sach jugaadh sach"),
        )

    def test_a_heading_only_entry_keeps_its_line(self):
        with patch.object(
            bg.corpus, "shabad", return_value=shabad(("ਛਕਾ ੧ ॥", "chhakaa 1 ||"))
        ):
            self.assertTrue(bg.heading_only("9"))
            self.assertEqual(bg.display_lines("9", "ਛਕਾ ੧ ॥"), ("ਛਕਾ ੧ ॥", "chhakaa 1"))
        with patch.object(bg.corpus, "shabad", return_value=shabad(MOOL_MANTAR, AADH)):
            self.assertFalse(bg.heading_only("9"))


if __name__ == "__main__":
    unittest.main()
