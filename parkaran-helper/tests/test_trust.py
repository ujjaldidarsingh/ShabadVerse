"""Regression tests for evidence-preserving discovery, without model calls."""
import json
import sys
import unittest
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
        self.patches = [patch.object(api, '_graph_data', self.graph), patch.object(api, '_sggs_lookup', {}), patch.object(api, '_sggs_sources', {})]
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
