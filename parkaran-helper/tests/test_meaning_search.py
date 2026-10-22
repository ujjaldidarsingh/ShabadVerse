"""Meaning search: local lists, fusion, Claude reordering fallbacks and the endpoint contract."""

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anthropic

import config
from api import graph_api as api
from api import meaning_search as ms
from app import app
from database import corpus

VERSES = (
    (
        "10",
        1,
        " ਤਾਤੀ ਵਾਉ ਨ ਲਗਈ ਪਾਰਬ੍ਰਹਮ ਸਰਣਾਈ ॥",
        ms.roman_needle("taatee vaau na lagiee paarabraham saranaiee ||"),
    ),
    (
        "20",
        4,
        " ਸੋ ਕਿਉ ਮੰਦਾ ਆਖੀਐ ਜਿਤੁ ਜੰਮਹਿ ਰਾਜਾਨ ॥",
        ms.roman_needle("so kiau ma(n)dhaa aakheeaai jit ja(n)meh raajaan ||"),
    ),
    (
        "30",
        2,
        " ਹਉਮੈ ਦੀਰਘ ਰੋਗੁ ਹੈ ਦਾਰੂ ਭੀ ਇਸੁ ਮਾਹਿ ॥",
        ms.roman_needle("haumai dheeragh rog hai dhaaroo bhee is maeh ||"),
    ),
    (
        "30",
        3,
        " ਮਨਮੁਖਿ ਹਉਮੈ ਕਰਮ ਕਮਾਵੈ ॥",
        ms.roman_needle("manamukh haumai karam kamaavai ||"),
    ),
    ("40", 1, " ਨਾਮਦੇਵ ਨਾਮੁ ਜਪਿ ॥", ms.roman_needle("naamadhev naam jap ||")),
)


def reply(results, stop_reason="end_turn"):
    text = SimpleNamespace(type="text", text=json.dumps({"results": results}))
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="thinking"), text]
    )


class SpellingTests(unittest.TestCase):
    def test_banidb_and_typed_spellings_meet(self):
        for typed, banidb in [
            ("tati", "taatee"),
            ("vao", "vaau"),
            ("lagai", "lagiee"),
            ("janda", "jaanadhaa"),
            ("thakur", "Thaakur"),
            ("pachhan", "pachhaan"),
            ("pachan", "pachhaan"),
            ("sang", "sa(n)g"),
        ]:
            self.assertEqual(
                ms.skeleton(ms.roman_words(typed)[0]),
                ms.skeleton(ms.roman_words(banidb)[0]),
                typed,
            )

    def test_nasal_marks_join_the_word(self):
        self.assertEqual(ms.roman_needle("ma(n)dhaa"), ms.roman_needle("manda"))


class LocalListTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(ms, "_verse_index", VERSES)
        p.start()
        self.addCleanup(p.stop)

    def test_typed_line_finds_its_verse(self):
        self.assertEqual(ms.roman_lines("tati vao na lagai")[0][:2], ("10", 1))
        self.assertEqual(
            ms.roman_lines("so kyu manda akhiye jit jameh rajan")[0][:2], ("20", 4)
        )

    def test_english_and_short_input_do_not_count_as_lines(self):
        self.assertEqual(ms.roman_lines("the hot wind cannot touch"), [])
        self.assertEqual(ms.roman_lines("tati vao"), [])

    def test_gurmukhi_words_match_word_starts_and_prefer_returning_shabads(self):
        self.assertEqual([sid for sid, *_ in ms.gurmukhi_words("ਹਉਮੈ")], ["30"])
        self.assertEqual(ms.gurmukhi_words("ਨਾਮੁ")[0][:2], ("40", 1))
        self.assertEqual(ms.gurmukhi_words("ਦੇਵ"), [])


class ConceptTests(unittest.TestCase):
    def setUp(self):
        names = {
            "kaam": {"Kaam"},
            "krodh": {"Krodh"},
            "lobh": {"Lobh"},
            "haumai": {"Haumai"},
        }
        gurmukhi = {"ਹਉਮ": {"Haumai"}, "ਕਾਮ": {"Kaam"}, "ਕਾਮਣ": set()}
        p = patch.object(ms, "_concept_terms", return_value=(names, gurmukhi))
        p.start()
        self.addCleanup(p.stop)

    def test_query_of_concept_names(self):
        self.assertEqual(
            ms.named_concepts("kaam krodh and lobh"), (["Kaam", "Krodh", "Lobh"], True)
        )
        self.assertEqual(ms.named_concepts("haumai in daily life"), (["Haumai"], False))
        self.assertEqual(ms.named_concepts("ਹਉਮੈ"), (["Haumai"], True))

    def test_ruled_out_word_names_no_concept(self):
        self.assertEqual(ms.named_concepts("ਕਾਮਣਿ"), ([], False))

    def test_concept_shabads_hold_more_named_concepts_first(self):
        concepts = {
            "1": [{"concept": "Kaam", "weight": 50, "line_index": 2}],
            "2": [
                {"concept": "Kaam", "weight": 5, "line_index": 1},
                {"concept": "Krodh", "weight": 5, "line_index": 3},
            ],
            "3": [{"concept": "Kaam", "weight": 0, "line_index": 0}],
        }
        with patch.object(api, "_concepts", concepts):
            self.assertEqual(
                ms.concept_shabads(["Kaam", "Krodh"]), [("2", 1, 10.0), ("1", 2, 50.0)]
            )


class FusionTests(unittest.TestCase):
    def test_typed_evidence_outranks_and_supplies_the_verse(self):
        lists = {
            "verse": [("5", 7, 0.8), ("6", 2, 0.7)],
            "line": [("6", 4, 1.0)],
            "shabad": [("5", None, 0.6)],
        }
        fused = ms.fuse(lists, ms.WEIGHTS)
        self.assertEqual(fused[0][:3], ("6", "line", 4))
        self.assertEqual(fused[1], ("5", "verse", 7, 0.8))


class RerankTests(unittest.TestCase):
    POOL = (("1", "line", 0, None), ("2", "verse", 3, 0.7), ("3", "shabad", None, 0.6))

    def setUp(self):
        for target, value in [
            ("_orders", ms.OrderedDict()),
            ("_calls", ms.deque()),
            ("_visitors", ms.defaultdict(ms.deque)),
        ]:
            p = patch.object(ms, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(
            ms, "_candidate_line", side_effect=lambda sid, idx: json.dumps({"id": sid})
        )
        p.start()
        self.addCleanup(p.stop)
        p = patch.dict(
            os.environ, {"SHABADVERSE_RERANK": "1", "ANTHROPIC_API_KEY": "test"}
        )
        p.start()
        self.addCleanup(p.stop)

    def run_with(self, response=None, error=None):
        client = patch("anthropic.Anthropic")
        mocked = client.start()
        self.addCleanup(client.stop)
        create = mocked.return_value.messages.create
        if error:
            create.side_effect = error
        else:
            create.return_value = response
        return ms.rerank("tati vao", self.POOL, "visitor"), create

    def test_order_keeps_only_offered_ids_once(self):
        picks = [
            {"id": "3", "reason": "Rahao on protection."},
            {"id": "9", "reason": "Invented."},
            {"id": "3", "reason": "Again."},
            {"id": "1", "reason": "x" * 400},
        ]
        order, create = self.run_with(reply(picks))
        self.assertEqual([sid for sid, _ in order], ["3", "1"])
        self.assertEqual(len(order[1][1]), ms.REASON_CHARS)
        request = create.call_args.kwargs
        self.assertEqual(request["model"], "claude-haiku-5-5")
        self.assertEqual(request["thinking"], {"type": "disabled"})
        self.assertNotIn("temperature", request)
        self.assertEqual(ms.cached_order("Tati vao"), order)

    def test_refusal_error_and_empty_answers_keep_the_local_order(self):
        self.assertIsNone(
            self.run_with(reply([{"id": "1", "reason": ""}], stop_reason="refusal"))[0]
        )
        self.assertIsNone(
            self.run_with(
                error=anthropic.APIError(
                    "credit balance is too low", request=None, body=None
                )
            )[0]
        )
        self.assertIsNone(
            self.run_with(reply([{"id": "9", "reason": "Not offered."}]))[0]
        )

    def test_disabled_without_flag_or_key(self):
        for env in ({"SHABADVERSE_RERANK": "0"}, {"ANTHROPIC_API_KEY": ""}):
            with patch.dict(os.environ, env):
                order, create = self.run_with(reply([{"id": "1", "reason": ""}]))
                self.assertIsNone(order)
                create.assert_not_called()

    def test_visitor_limit(self):
        with patch.object(ms, "VISITOR_LIMIT", 2):
            self.assertEqual(
                [
                    ms._reserve("a"),
                    ms._reserve("a"),
                    ms._reserve("a"),
                    ms._reserve("b"),
                ],
                [True, True, False, True],
            )


class EndpointTests(unittest.TestCase):
    POOL = (("1", "line", 0, None), ("2", "verse", 3, 0.7))

    def setUp(self):
        self.client = app.test_client()
        for target, kwargs in [
            ("candidates", {"return_value": self.POOL}),
            (
                "_result",
                {
                    "side_effect": lambda sid, *rest, reason=None: {
                        "banidb_shabad_id": sid,
                        "reason": reason,
                    }
                },
            ),
        ]:
            p = patch.object(ms, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(ms, "_orders", ms.OrderedDict())
        p.start()
        self.addCleanup(p.stop)

    def test_local_order_without_claude(self):
        with patch.dict(os.environ, {"SHABADVERSE_RERANK": "0"}):
            data = self.client.get(
                "/api/graph/semantic-search?q=tati+vao&rerank=1"
            ).get_json()
        self.assertEqual([r["banidb_shabad_id"] for r in data["results"]], ["1", "2"])
        self.assertEqual((data["reordered"], data["rerank_available"]), (False, False))

    def test_reordered_results_carry_reasons(self):
        with patch.object(ms, "rerank", return_value=[("2", "Fits.")]):
            data = self.client.get(
                "/api/graph/semantic-search?q=tati+vao&rerank=1"
            ).get_json()
        self.assertEqual(
            data["results"], [{"banidb_shabad_id": "2", "reason": "Fits."}]
        )
        self.assertTrue(data["reordered"])

    def test_short_query(self):
        self.assertEqual(
            self.client.get("/api/graph/semantic-search?q=ab").get_json()["results"], []
        )


@unittest.skipUnless(
    os.getenv("SHABADVERSE_TEST_DATA"), "Set SHABADVERSE_TEST_DATA to run corpus checks"
)
class CorpusSearchTests(unittest.TestCase):
    """Typed lines and Gurmukhi words against the full candidate, without the vector indexes."""

    @classmethod
    def setUpClass(cls):
        path = Path(os.environ["SHABADVERSE_TEST_DATA"]).resolve()

        def read(name):
            return json.loads((path / name).read_text(encoding="utf-8"))

        cls.patches = [
            patch.object(config, "DATA_DIR", str(path)),
            patch.object(config, "CACHE_DB_PATH", str(path / "shabad_cache.db")),
            patch.object(api, "_graph_data", read("similarity_graph.json")),
            patch.object(api, "_tag_vocab", read("tag_vocabulary.json")),
            patch.object(api, "_concepts", read("concept_tags.json")),
            patch.object(ms, "_verse_index", None),
        ]
        for p in cls.patches:
            p.start()
        ms._concept_terms.cache_clear()

    @classmethod
    def tearDownClass(cls):
        for p in reversed(cls.patches):
            p.stop()
        ms._concept_terms.cache_clear()

    def test_remembered_lines_typed_in_english_letters(self):
        self.assertEqual(
            ms.roman_lines("tati vao na lagai parbrahm sarnai")[0][:2], ("3085", 1)
        )
        self.assertEqual(
            ms.roman_lines("so kyu manda akhiye jit jameh rajan")[0][:2], ("1748", 4)
        )
        self.assertEqual(ms.roman_lines("hau aapo bol na janda")[0][0], "2883")

    def test_gurmukhi_words_and_concepts(self):
        self.assertEqual(ms.gurmukhi_words("ਹਉਮੈ ਦੀਰਘ ਰੋਗੁ ਹੈ")[0][:2], ("1706", 5))
        self.assertEqual(
            ms.named_concepts("kaam krodh lobh moh ahankar")[0],
            ["Kaam", "Krodh", "Lobh", "Moh", "Ahankar"],
        )
        self.assertEqual(ms.named_concepts("ਹਉਮੈ"), (["Haumai"], True))
        self.assertEqual(ms.named_concepts("ਕਾਮਣਿ")[0], [])

    def test_no_heading_is_indexed(self):
        self.assertFalse(
            any(corpus.is_heading(text.strip(), idx) for _, idx, text, _ in ms._verses())
        )


if __name__ == "__main__":
    unittest.main()
