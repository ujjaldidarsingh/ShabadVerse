"""Regression tests for evidence-preserving discovery, without model calls."""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
from api import graph_api as api
from database import corpus


class GraphTruthTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.graph = {
            'metadata': {'1': {'tags': ['Naam']}, '2': {'tags': ['Naam']}, '3': {'tags': ['Hukam']}, '4': {'tags': ['Maya']}},
            'neighbors': {'1': [{'id': '2', 'score': .6, 'shared_tags': ['Naam']}, {'id': '3', 'score': .7, 'shared_tags': []}],
                          '4': [{'id': '3', 'score': .8, 'shared_tags': []}]},
            'tag_index': {'Naam': ['1', '2'], 'Hukam': ['3'], 'Maya': ['4']},
        }
        self.patches = [patch.object(api, '_graph_data', self.graph), patch.object(api, '_sggs_lookup', {})]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_thin_cluster_does_not_invent_a_concept(self):
        data = self.client.get('/api/graph/neighbors/1').get_json()
        self.assertEqual(data['total_shown'], 2)
        for tag, items in data['by_tag'].items():
            for item in items: self.assertIn(tag, item['tags'])

    def test_only_singleton_survives(self):
        data = self.client.get('/api/graph/neighbors/4').get_json()
        self.assertEqual(data['total_shown'], 1)

    def test_unknown_id_is_not_an_empty_success(self):
        self.assertEqual(self.client.get('/api/graph/neighbors/999').status_code, 404)

    def test_line_fallback_is_explicit(self):
        with patch.object(api, '_line_neighbors', return_value=([], None)):
            data = self.client.get('/api/graph/neighbors/1?match=line').get_json()
        self.assertEqual(data['requested_match'], 'line')
        self.assertEqual(data['match'], 'shabad')
        self.assertTrue(data['fallback_reason'])

    def test_missing_selected_line_does_not_silently_change_anchor(self):
        from unittest.mock import Mock
        store = Mock()
        store.collection.get.return_value = {"metadatas": [{"line_index": 1, "english": "one", "gurmukhi": "", "is_rahao": True}]}
        with patch.object(api, "_get_lines_vector_store", return_value=store):
            self.assertIsNone(api._resolve_anchor_line("1", 0))
            self.assertEqual(api._resolve_anchor_line("1", None)[0], 1)

    def test_invalid_threshold_and_batch(self):
        self.assertEqual(self.client.get('/api/graph/neighbors/1?threshold=nan').status_code, 400)
        for value in [None, [], {'ids': '1'}, {'ids': ['1'] * 201}]:
            self.assertEqual(self.client.post('/api/graph/shabads', json=value).status_code, 400)


class LineMatchTests(unittest.TestCase):
    """Line mode compares verse translations. Concepts play no part."""
    def setUp(self):
        self.client = app.test_client()
        ids = [str(i) for i in range(1, 6)]
        graph = {'metadata': {sid: {'tags': ['Naam']} for sid in ids}, 'neighbors': {}, 'tag_index': {'Naam': ids}}
        for p in (patch.object(api, '_graph_data', graph), patch.object(api, '_sggs_lookup', {})):
            p.start()
            self.addCleanup(p.stop)

    def test_score_is_translation_similarity_alone(self):
        from unittest.mock import Mock
        def hit(sid, distance, gurmukhi, english):
            return {'distance': distance, 'metadata': {'shabad_id': sid, 'line_index': 0, 'gurmukhi': gurmukhi, 'english': english}}
        store = Mock()
        store.get_count.return_value = 6
        store.search_similar.return_value = [
            hit('1', .05, 'ਉਹੀ ਸ਼ਬਦ ॥', 'The anchor shabad itself.'),
            hit('2', .2, 'ਸਿਰੀਰਾਗੁ ਮਹਲਾ ੧ ॥', 'Siree Raag, First Mehl:'),
            hit('2', .25, 'ਗਉੜੀ ਕਬੀਰ ਜੀ ॥', 'Gauree, Kabeer Jee:'),
            hit('3', .3, 'ਹਰਿ ਨਾਮੁ ਧਿਆਇ ॥', 'Meditate on the Name.'),
            hit('4', .35, 'ਹਰਿ ਨਾਮੁ ਧਿਆਇ ॥', 'Meditate on the Name.'),
            hit('3', .4, 'ਦੂਜੀ ਤੁਕ ॥', 'A weaker verse of shabad 3.'),
            hit('5', .45, 'ਪ੍ਰਭੁ ਸਿਮਰਿ ॥', 'Remember God.'),
        ]
        with patch.object(api, '_resolve_anchor_line', return_value=(0, 'Meditate.', 'ਨਾਮੁ ਧਿਆਇ ॥')), \
                patch.object(api, '_get_lines_vector_store', return_value=store), \
                patch.object(api, '_get_word_frequency', return_value=(Counter(), 1000)):
            hits, anchor = api._line_neighbors('1', None, 10, .5)
        self.assertEqual([(h['id'], h['score']) for h in hits], [('3', .7), ('5', .55)])
        self.assertEqual([h['shared_word'] for h in hits], ['ਧਿਆਇ', None])
        self.assertEqual(anchor['line_index'], 0)

    def test_groups_by_shared_word_never_by_concept(self):
        hits = [{'id': sid, 'score': score, 'line_score': score, 'matched_line_index': 0, 'matched_line_gurmukhi': '',
                 'matched_line_english': '', 'matched_line_is_rahao': False, 'shared_word': word}
                for sid, score, word in [('2', .8, 'ਧਿਆਇ'), ('3', .7, 'ਧਿਆਇ'), ('4', .6, 'ਸਿਮਰਿ'), ('5', .55, None)]]
        with patch.object(api, '_line_neighbors', return_value=(hits, {'line_index': 0, 'english': '', 'gurmukhi': ''})):
            data = self.client.get('/api/graph/neighbors/1?match=line').get_json()
        self.assertEqual(data['match'], 'line')
        self.assertEqual({tag: [n['id'] for n in items] for tag, items in data['by_tag'].items()},
                         {'ਧਿਆਇ': ['2', '3'], api.SIMILAR_TRANSLATION: ['4', '5']})
        self.assertEqual(data['label_kinds'], {'ਧਿਆਇ': 'shared_word', api.SIMILAR_TRANSLATION: 'similar_translation'})

    def test_default_anchor_is_the_marked_rahao_not_a_heading(self):
        from unittest.mock import Mock
        def metas(*verses):
            return {'metadatas': [{'line_index': i, 'english': str(i), 'gurmukhi': g, 'is_rahao': r} for i, (g, r) in enumerate(verses)]}
        heading = ('ਸਿਰੀਰਾਗੁ ਮਹਲਾ ੧ ॥', False)
        store = Mock()
        with patch.object(api, '_get_lines_vector_store', return_value=store):
            store.collection.get.return_value = metas(heading, ('ਗੁਰਮਤਿ ਸਾਚਿ ਰਹਾਉ ॥', True), ('ਰਹਾਉ ਦੀ ਤੁਕ ॥੧॥ ਰਹਾਉ ॥', True))
            self.assertEqual(api._resolve_anchor_line('1', None)[0], 2)
            store.collection.get.return_value = metas(heading, ('ਪਹਿਲੀ ਤੁਕ ॥੧॥', False))
            self.assertEqual(api._resolve_anchor_line('1', None)[0], 1)
            store.collection.get.return_value = metas(('ਛਕੇ ੨ ॥', False), ('ਪਹਿਲੀ ਤੁਕ ॥੧॥', False))
            self.assertEqual(api._resolve_anchor_line('1', None)[0], 1, 'a set label is not a verse')
            store.collection.get.return_value = metas(('ਛਕਾ ੧ ॥', False))
            self.assertIsNone(api._resolve_anchor_line('1', None), 'a label-only entry has no verse to match from')


class SearchTests(unittest.TestCase):
    def test_start_and_anywhere_are_distinct_offline(self):
        rows = [('1', 0, 'ਹਕਸ'), ('2', 0, 'ਅਹਕਸ')]
        record = {'verses': [{'gurmukhi': 'ਹਰਿ', 'english': 'translation', 'transliteration': 'har', 'translation_source': 'bdb'}], 'ang': 1, 'raag': '', 'writer': ''}
        with patch.object(corpus, 'search_index', return_value=rows), patch.object(corpus, 'shabad', return_value=record):
            self.assertEqual([r['banidb_shabad_id'] for r in corpus.search('ਹ ਕ', 0)], ['1'])
            self.assertEqual([r['banidb_shabad_id'] for r in corpus.search('ਹ ਕ', 1)], ['1', '2'])

    def test_gurmukhi_marks_and_numbers(self):
        self.assertEqual(corpus.first_letters('ਹਰਿ ਕਾ ॥੧॥ ਸਬਦੁ'), 'ਹਕਸ')

    def test_legacy_zero_is_preserved(self):
        import sqlite3
        from enrichment.banidb_matcher import BaniDBMatcher
        matcher = BaniDBMatcher.__new__(BaniDBMatcher)
        matcher.conn = sqlite3.connect(':memory:')
        self.addCleanup(matcher.conn.close)
        matcher.conn.execute('create table search_cache(query text, response text)')
        matcher.conn.executemany('insert into search_cache values(?,?)', [('q||0', '[0]'), ('q||1', '[1]')])
        self.assertEqual(matcher.search('q', searchtype=0), [0])




class RuntimeIsolationTests(unittest.TestCase):
    def test_vector_runtime_uses_a_disposable_copy(self):
        import os
        import tempfile
        from database import vector_store as vs
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'source'
            source.mkdir()
            (source / 'chroma.sqlite3').write_bytes(b'preserved')
            with patch.object(vs, '_runtime_directory', None), patch.object(vs.config, 'CHROMA_DB_PATH', str(source)), patch.dict(os.environ, {'SHABADVERSE_BUILD': '0'}):
                target = Path(vs._vector_path())
                self.assertNotEqual(target, source)
                (target / 'chroma.sqlite3').write_bytes(b'runtime')
                self.assertEqual((source / 'chroma.sqlite3').read_bytes(), b'preserved')
                vs._runtime_directory.cleanup()

    def test_partial_model_cache_does_not_download(self):
        import tempfile
        from database import vector_store as vs
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'onnx').mkdir()
            (Path(root) / 'onnx/model.onnx').write_bytes(b'partial')
            store = vs.ShabadVectorStore.__new__(vs.ShabadVectorStore)
            with patch.object(vs.ONNXMiniLM_L6_V2, 'DOWNLOAD_PATH', root):
                with self.assertRaises(RuntimeError): store.search_similar('humility')


class ConcurrentVectorTests(unittest.TestCase):
    def test_collection_cold_starts_are_serialized(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import Mock
        import time
        from database import vector_store as vs
        active = 0
        peak = 0
        def create_client(**kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(.02)
            active -= 1
            return Mock()
        with patch.object(vs, '_vector_path', return_value='/unused'), patch.object(vs, 'ONNXMiniLM_L6_V2'), patch.object(vs.chromadb, 'PersistentClient', side_effect=create_client):
            with ThreadPoolExecutor(max_workers=4) as pool:
                stores = list(pool.map(vs.ShabadVectorStore, ['a','b','c','d']))
        self.assertEqual(len(stores),4)
        self.assertEqual(peak,1)


if __name__ == '__main__': unittest.main()
