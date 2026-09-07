"""Full candidate checks. Set SHABADVERSE_TEST_DATA to a built candidate."""
import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from api import graph_api as api
from app import app
from database.corpus import first_letters
from release import validate


@unittest.skipUnless(os.getenv('SHABADVERSE_TEST_DATA'), 'Set SHABADVERSE_TEST_DATA to run corpus checks')
class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(os.environ['SHABADVERSE_TEST_DATA']).resolve()
        cls.rows = json.loads((cls.path / 'sggs_all_shabads.json').read_text())
        cls.graph = json.loads((cls.path / 'similarity_graph.json').read_text())

    def test_complete_dataset_contract(self):
        self.assertEqual(validate(self.path)['shabads'], 5542)

    def test_all_cluster_labels_and_nonempty_expansions(self):
        with patch.object(api, '_graph_data', self.graph), patch.object(api, '_sggs_lookup', {}):
            for sid in self.graph['metadata']:
                with app.test_request_context('/api/graph/neighbors/' + sid): data = api.graph_neighbors(sid).get_json()
                if any(n['score'] >= .3 for n in self.graph['neighbors'][sid]): self.assertGreater(data['total_shown'], 0, sid)
                for label, items in data['by_tag'].items():
                    if label in self.graph['tag_index']:
                        for item in items: self.assertIn(label, item['tags'], (sid, item['id']))

    def test_all_lexical_anchors_retained(self):
        from bootstrap.build_concept_tags import lexical_line_positives, load_vocabulary
        with patch.object(config, 'CACHE_DB_PATH', str(self.path / 'shabad_cache.db')):
            anchors = lexical_line_positives(load_vocabulary(self.path / 'draft_vocabulary.json'))
        tags = {str(r['banidb_shabad_id']): set(r['tags']) for r in self.rows}
        for concept, line_ids in anchors.items():
            for line in line_ids: self.assertIn(concept, tags[line.split(':')[0]], line)

    def test_membership_is_not_truncated_by_frequency(self):
        vocab = json.loads((self.path / 'tag_vocabulary.json').read_text())
        self.assertEqual(vocab['generation_policy']['method'], 'concept_threshold')
        self.assertIsNone(vocab['generation_policy']['membership_quota'])
        self.assertGreater(vocab['theme_tags']['Naam']['count'], 1937)
        assignments = json.loads((self.path / 'concept_tags.json').read_text())
        review = json.loads((self.path / 'concept_review.json').read_text())['concepts']
        for sid, group in assignments.items():
            for assignment in group:
                if not assignment['lexical']:
                    self.assertGreaterEqual(assignment['strength'] + .00051, review[assignment['concept']]['threshold'])

    def test_blind_review_hides_status_until_reveal(self):
        from api import topics
        with patch.object(config, 'DATA_DIR', str(self.path)), patch.object(topics, 'statistics', return_value={'Naam': {}}), patch.object(topics, 'detail', side_effect=lambda sid: {'id':sid}):
            client=app.test_client()
            blind=client.get('/api/topics/Naam/review').get_json()
            revealed=client.get('/api/topics/Naam/review?reveal=1').get_json()
            self.assertGreater(len(blind['samples']),0)
            self.assertTrue(all('category' not in row and 'strength' not in row for row in blind['samples']))
            self.assertEqual([r['id'] for r in blind['samples']],[r['id'] for r in revealed['samples']])
            self.assertIn('newly_admitted',{r['category'] for r in revealed['samples']})
            self.assertEqual(blind['dataset_id'],revealed['dataset_id'])

    def test_no_stale_consensus_attribution(self):
        self.assertTrue(all(r['tags_source'] == 'curated_concepts_v2' for r in self.rows))


class BuildSafetyTests(unittest.TestCase):
    def test_existing_target_is_never_replaced(self):
        from bootstrap.setup import build
        with self.assertRaises(ValueError): build(Path(config.DATA_DIR), Path(config.DATA_DIR))

    def test_active_dataset_guard(self):
        from bootstrap.build_guard import require_build_target
        with patch.dict(os.environ, {'SHABADVERSE_BUILD': '1'}), patch.object(config, 'DATA_DIR', str(Path(config.BASE_DIR) / 'data')):
            with self.assertRaises(RuntimeError): require_build_target()
