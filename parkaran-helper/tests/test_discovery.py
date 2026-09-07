"""Contracts for search, source selection and complete topic exploration."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import app
from api import graph_api as api, topics
from database import corpus
from api.source_candidates import retrieve
import numpy as np


class InitialsTests(unittest.TestCase):
    def test_vowel_carriers_share_search_keys(self):
        for a,b in [('ਆਨ','ਅਨ'),('ਇਮ','ੲਮ'),('ਉਨ','ੳਨ'),('ਏਕ','ੲਕ')]:
            self.assertEqual(corpus.normalize_initials(a),corpus.normalize_initials(b))

    def test_search_keys_do_not_mutate_scripture(self):
        verse={'verse':{'unicode':'ਇਹੁ ਮਨੁ ਸਾਚਿ ਸੰਤੋਖਿਆ'}}
        key=corpus.first_letters(verse['verse']['unicode'])
        self.assertEqual(key,'ੲਮਸਸ')
        self.assertEqual(corpus.verse_record(verse,0)['gurmukhi'],'ਇਹੁ ਮਨੁ ਸਾਚਿ ਸੰਤੋਖਿਆ')


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client()
        self.graph={'metadata':{'1':{'tags':['Naam']},'2':{'tags':['Naam']},'3':{'tags':['Naam']}},
                    'tag_index':{'Naam':['1','2','3']},'neighbors':{'1':[{'id':'2','score':.6,'shared_tags':['Naam']}]}}
        for target,value in [('_graph_data',self.graph),('_sggs_lookup',{}),('_sggs_sources',{'3':{'amrit_keertan':True,'ak_chapters':[2]}})]:
            p=patch.object(api,target,value);p.start();self.addCleanup(p.stop)
        p=patch.object(api,'_get_sggs_vector_store',return_value=Mock());p.start();self.addCleanup(p.stop)
        p=patch('api.source_candidates.retrieve',return_value=[{'id':'3','score':.55,'shared_tags':['Naam']}]);self.retrieve=p.start();self.addCleanup(p.stop)

    def test_all_preserves_existing_pool(self):
        data=self.client.get('/api/graph/neighbors/1?source=all').get_json()
        self.assertEqual([n['id'] for n in data['by_tag']['Naam']],['2'])
        self.retrieve.assert_not_called()

    def test_prefer_retrieves_and_keeps_similarity_separate(self):
        data=self.client.get('/api/graph/neighbors/1?source=prefer-ak').get_json()
        items=data['by_tag']['Naam']
        self.assertEqual([n['id'] for n in items],['3','2'])
        self.assertEqual(items[0]['score'],.55)
        self.assertEqual(items[0]['rank_score'],.7)
        self.assertEqual(items[0]['ak_chapters'],[2])

    def test_only_cannot_leak_non_ak(self):
        data=self.client.get('/api/graph/neighbors/1?source=ak-only').get_json()
        self.assertEqual(data['source_counts'],{'ak':1,'shown':1})
        self.assertTrue(all(n['is_amrit_keertan'] for group in data['by_tag'].values() for n in group))

    def test_empty_source_selection_is_explained(self):
        self.retrieve.return_value=[]
        data=self.client.get('/api/graph/neighbors/1?source=ak-only').get_json()
        self.assertEqual(data['total_shown'],0)
        self.assertTrue(data['source_notice'])

    def test_invalid_or_missing_source_fails_explicitly(self):
        self.assertEqual(self.client.get('/api/graph/neighbors/1?source=unknown').status_code,400)
        with patch.object(api,'_sggs_sources',{}):
            self.assertEqual(self.client.get('/api/graph/neighbors/1?source=ak-only').status_code,503)

    def test_source_retrieval_uses_eligible_vectors(self):
        import api.source_candidates as source
        ids=['1','2','3'];matrix=np.array([[1.,0.],[1.,0.],[.8,.6]])
        with patch.object(source,'_index',(ids,matrix,{sid:i for i,sid in enumerate(ids)})):
            result=retrieve(Mock(),'1',{'3'},self.graph['metadata'],lambda a,b:1)
        self.assertEqual([n['id'] for n in result],['3'])
        self.assertAlmostEqual(result[0]['score'],.9)


class TopicTests(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client()
        ids=[str(i) for i in range(1,61)]
        for target,value in [('statistics',{'Naam':{'tag':'Naam','count':60}}),('eligible',ids)]:
            p=patch.object(topics,target,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(topics,'detail',side_effect=lambda sid:{'id':sid});p.start();self.addCleanup(p.stop)

    def test_pagination_exposes_full_count_and_last_member(self):
        data=self.client.get('/api/topics/Naam?offset=40&limit=20').get_json()
        self.assertEqual(data['total'],60)
        self.assertEqual(data['shabads'][-1]['id'],'60')
        self.assertIsNone(data['next_offset'])

    def test_random_draws_from_full_pool_and_excludes_recent(self):
        with patch('api.topics.random.SystemRandom') as rng:
            rng.return_value.choice.side_effect=lambda pool:pool[-1]
            data=self.client.get('/api/topics/Naam/random?exclude=60').get_json()
            pool=rng.return_value.choice.call_args.args[0]
        self.assertEqual(data['shabad']['id'],'59')
        self.assertEqual(len(pool),59)
        self.assertIn('40',pool)

    def test_empty_intersection_never_falls_back_to_all(self):
        with patch.object(topics,'eligible',return_value=[]):
            response=self.client.get('/api/topics/Naam/random?source=ak-only')
        self.assertEqual(response.status_code,404)

    def test_unknown_topic_and_source(self):
        self.assertEqual(self.client.get('/api/topics/Unknown/random').status_code,404)
        self.assertEqual(self.client.get('/api/topics/Naam/random?source=nope').status_code,400)


if __name__=='__main__': unittest.main()
