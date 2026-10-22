"""Ujjal's word rulings as regression cases against the curated vocabulary."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap.build_concept_tags import compile_senses, load_vocabulary, load_word_senses, sense_concept

VOCABULARY = Path(__file__).resolve().parents[1] / 'data/draft_vocabulary.json'

# (word as written, BaniDB English of its verse, concept it should support)
RULED = [
    ('ਦਇਆ', 'Please, shower me with Your Mercy, and take pity upon me.', 'Daya (divine)'),
    ('ਦਇਆ', 'Be kind to all beings-this is more meritorious than bathing at the sixty-eight sacred shrines.', 'Daya (human)'),
    ('ਦਇਆ', 'He makes compassion his shovel, his body the firewood.', 'Daya (human)'),
    ('ਦਇਆ', 'Please, be kind to me - I am just a worm. This is my object and purpose.', 'Daya (divine)'),
    ('ਦਇਆ', 'Take pity upon me, and abide within my mind;', 'Daya (divine)'),
    ('ਦਇਆ', 'be merciful, and save the sinners.', 'Daya (divine)'),
    ('ਦਇਆ', 'Let your mind be content, and be kind to all beings.', 'Daya (human)'),
    ('ਦਇਆਲੁ', 'The Merciful Lord God showered me with His Mercy.', 'Daya (divine)'),
    ('ਕਰਮਾ', "Without God's Grace, how can anyone find Him?", 'Kirpa'),
    ('ਕਰਮੀ', 'By the karma of good actions, the robe of this physical body is obtained. By His Grace, the gate of liberation is found.', 'Karma'),
    ('ਕਾਮੁ', 'The conscious mind is engrossed in sexual desire, anger and Maya.', 'Kaam'),
    ('ਕਾਮ', 'All my tasks are perfectly accomplished.', None),
    ('ਕਾਮਣਿ', 'The soul-bride is adorned.', None),
    ('ਕਾਮਨਾ', 'All the desires of my mind are fulfilled.', None),
    ('ਜਨਮੁ', 'Human life is such a precious jewel, but it is being lost in exchange for a mere shell.', None),
    ('ਜਨਮ', 'He dispels the pains of countless incarnations.', 'Janam-Maran'),
    ('ਸਹਜੇ', 'Meeting with the True Guru, you shall easily meet your Lord and Master.', 'Sahaj (ease)'),
    ('ਸਹਜ', 'Celestial peace and bliss have come.', 'Sahaj (poise)'),
    ('ਸਚੁ', 'Those who obey the True One-their minds abide in true meditation.', 'Sach (divine)'),
    ('ਸਚੁ', 'Let Truth be your prayer, and faith your prayer-mat.', 'Sach (human)'),
    ('ਸਚੁ', 'Gazing upon your gold, and your very beautiful wife, you believe that they are permanent.', None),
    ('ਦਾਨੁ', 'Please bless Nanak with the Gift of the Naam.', 'Daan (divine)'),
    ('ਦਾਨੁ', 'The Tenth Day: Meditate on the Naam, give to charity, and purify yourself.', 'Daan (human)'),
    ('ਦਾਨੁ', 'They collect taxes from the world,', None),
]


class WordSenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.senses = compile_senses(load_word_senses(VOCABULARY))

    def test_ruled_examples(self):
        for word, english, concept in RULED:
            with self.subTest(word=word, english=english):
                self.assertEqual(sense_concept(word, english, self.senses), (True, concept))

    def test_other_words_fall_through_to_anchors(self):
        self.assertEqual(sense_concept('ਨਾਮੁ', 'the Naam', self.senses), (False, None))

    def test_every_sense_names_a_defined_concept(self):
        concepts = load_vocabulary(VOCABULARY)
        for word in load_word_senses(VOCABULARY):
            for sense in word['senses']:
                if sense.get('concept'):
                    self.assertIn(sense['concept'], concepts, word['word'])

    def test_enticer_counts_as_maya_not_moh(self):
        concepts = load_vocabulary(VOCABULARY)
        self.assertTrue(any('ਮੋਹਣੀ'.startswith(a) for a in concepts['Maya']['anchors_accept']))
        self.assertTrue(any('ਮੋਹਣੀ'.startswith(r) for r in concepts['Moh']['anchors_reject']))


if __name__ == '__main__': unittest.main()
