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
        for target,value in [('_graph_data',self.graph),('_sggs_lookup',{})]:
            p=patch.object(api,target,value);p.start();self.addCleanup(p.stop)
        p=patch.object(api,'_get_sggs_vector_store',return_value=Mock());p.start();self.addCleanup(p.stop)

    def test_legacy_source_parameters_cannot_filter_or_rerank(self):
        expected=self.client.get('/api/graph/neighbors/1').get_json()
        for query in ['source=ak-only','source=prefer-ak','ak_boost=1']:
            self.assertEqual(self.client.get('/api/graph/neighbors/1?'+query).get_json(),expected)
        self.assertEqual([n['id'] for n in expected['by_tag']['Naam']],['2'])
        self.assertNotIn('source_mode',expected)
        self.assertNotIn('is_amrit_keertan',expected['by_tag']['Naam'][0])


class TopicTests(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client()
        ids=[str(i) for i in range(1,61)]
        for target,value in [('statistics',{'Naam':{'tag':'Naam','count':60}}),('eligible',ids)]:
            p=patch.object(topics,target,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(topics,'detail',side_effect=lambda sid:{'id':sid});p.start();self.addCleanup(p.stop)
        p=patch.object(topics,'central',return_value=());p.start();self.addCleanup(p.stop)
        p=patch.object(topics,'member',side_effect=lambda sid,tag:{'central':False,'weight':0.0});p.start();self.addCleanup(p.stop)

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

    def test_random_starts_from_shabads_centered_on_the_topic(self):
        with patch.object(topics,'central',return_value=('3','5')), patch('api.topics.random.SystemRandom') as rng:
            rng.return_value.choice.side_effect=lambda pool:pool[0]
            data=self.client.get('/api/topics/Naam/random?exclude=3').get_json()
            pool=rng.return_value.choice.call_args.args[0]
        self.assertEqual(pool,['5'])
        self.assertEqual((data['shabad']['id'],data['central_total']),('5',2))

    def test_empty_intersection_never_falls_back_to_all(self):
        with patch.object(topics,'eligible',return_value=[]):
            response=self.client.get('/api/topics/Naam/random?source=ak-only')
        self.assertEqual(response.status_code,404)

    def test_unknown_topic_and_source(self):
        self.assertEqual(self.client.get('/api/topics/Unknown/random').status_code,404)
        self.assertEqual(self.client.get('/api/topics/Naam/random?source=ak-only').status_code,200)


class TopicOrderTests(unittest.TestCase):
    """A shabad that only brushes a topic must not lead its list, as the Mool Mantar did under Kaam.
    Within each tier, shabads that use the word lead inferred ones."""
    def setUp(self):
        weights={('1','Kaam'):(False,4.0,True,.9),('2','Kaam'):(True,90.0,False,.5),('3','Kaam'):(True,80.0,True,0.0),('4','Kaam'):(False,4.0,False,.6)}
        for target,value in [('_weights',weights),('_get_graph',{'tag_index':{'Kaam':['1','2','3','4']}})]:
            p=patch.object(topics,target,return_value=value);p.start();self.addCleanup(p.stop)
        for cached in (topics.eligible,topics.central):
            cached.cache_clear();self.addCleanup(cached.cache_clear)

    def test_central_members_lead_by_weight(self):
        self.assertEqual(topics.eligible('Kaam'),('3','2','1','4'))
        self.assertEqual(topics.central('Kaam'),('3','2'))


class RahaoTests(unittest.TestCase):
    def test_span_runs_back_to_the_previous_stanza(self):
        verses=['ਗਉੜੀ ਮਹਲਾ ੫ ॥','ਪਹਿਲੀ ਤੁਕ ॥','ਦੂਜੀ ਤੁਕ ॥੧॥','ਰਹਾਉ ਦੀ ਪਹਿਲੀ ਤੁਕ ॥','ਰਹਾਉ ਦੀ ਦੂਜੀ ਤੁਕ ॥੧॥ ਰਹਾਉ ॥','ਅਗਲੀ ਤੁਕ ॥੨॥']
        self.assertEqual(corpus.rahao_span(verses),{3,4})

    def test_rahao_meaning_remain_is_not_a_marker(self):
        self.assertEqual(corpus.rahao_span(['ਗੁਰਮਤਿ ਸਾਚਿ ਰਹਾਉ ॥']),set())


if __name__=='__main__': unittest.main()
