"""Topic counts, complete browsing, random starts and review evidence."""
import json
import random
import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from flask import jsonify, request
import config
from database import corpus
from api.graph_api import graph_bp, _get_graph, _get_tag_vocab, _get_concepts


@lru_cache(maxsize=1)
def _weights():
    """(shabad, concept) -> (central, weight, lexical, strength) from the assignments."""
    table = {}
    for sid, group in _get_concepts().items():
        for a in group:
            table[(sid, a['concept'])] = (bool(a.get('central')), a.get('weight') or 0.0, bool(a['lexical']), a.get('strength') or 0.0)
    return table


@lru_cache(maxsize=1)
def statistics():
    graph, concepts = _get_graph(), _get_concepts()
    with closing(sqlite3.connect((Path(config.DATA_DIR) / 'chroma_db/chroma.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
        denominator = db.execute("select count(distinct string_value) from embedding_metadata where key='shabad_id'").fetchone()[0]
    policy = _get_tag_vocab().get('generation_policy', {})
    denominator = policy.get('indexed_shabads', denominator)
    result = {}
    for tag, value in _get_tag_vocab().get('theme_tags', {}).items():
        assignments = [a for group in concepts.values() for a in group if a['concept'] == tag]
        lexical = sum(bool(a['lexical']) for a in assignments)
        inferred = len(assignments) - lexical
        result[tag] = {**value, 'tag': tag, 'count': len(graph['tag_index'].get(tag, [])),
                       'central': len(central(tag)),
                       'lexical': lexical, 'inferred': inferred, 'policy': policy,
                       'indexed_shabads': denominator}
    return result


@lru_cache(maxsize=64)
def eligible(tag):
    """Every member of a topic in reading order: shabads that center on it first.
    Within each tier, shabads that use the word come before inferred ones, which
    are less reliable until reviewed, and heavier weights come first."""
    weights = _weights()

    def key(sid):
        is_central, weight, lexical, strength = weights.get((sid, tag), (False, 0.0, False, 0.0))
        return (not is_central, not lexical, -weight, -strength, int(sid))
    return tuple(sorted(_get_graph()['tag_index'].get(tag, []), key=key))


@lru_cache(maxsize=64)
def central(tag):
    """Members where this topic is one of the shabad's central concepts."""
    weights = _weights()
    return tuple(sid for sid in eligible(tag) if weights.get((sid, tag), (False,))[0])


def member(sid, tag):
    is_central, weight = _weights().get((sid, tag), (False, 0.0))[:2]
    return {'central': is_central, 'weight': weight}


def detail(sid):
    meta = _get_graph()['metadata'][sid]
    info = corpus.shabad(sid) or {}
    return {'id': sid, 'gurmukhi': meta.get('gurmukhi', ''), 'title': meta.get('title', ''),
            'raag': info.get('raag', meta.get('raag', '')), 'writer': info.get('writer', ''),
            'ang': info.get('ang', meta.get('ang', 0))}


@graph_bp.route('/topics')
def topics():
    return jsonify(list(statistics().values()))


@graph_bp.route('/topics/<tag>')
def topic(tag):
    if tag not in statistics(): return jsonify({'error': 'Unknown topic'}), 404
    ids = eligible(tag)
    offset = max(0, request.args.get('offset', 0, type=int))
    limit = max(1, min(50, request.args.get('limit', 20, type=int)))
    return jsonify({'topic': statistics()[tag], 'total': len(ids), 'central_total': len(central(tag)), 'offset': offset,
                    'next_offset': offset + limit if offset + limit < len(ids) else None,
                    'shabads': [{**detail(sid), **member(sid, tag)} for sid in ids[offset:offset+limit]]})


@graph_bp.route('/topics/<tag>/random')
def topic_random(tag):
    if tag not in statistics(): return jsonify({'error': 'Unknown topic'}), 404
    ids = eligible(tag)
    # Start from a shabad that centers on the topic when one exists.
    source = central(tag) or ids
    excluded = set(request.args.get('exclude', '')[:2000].split(','))
    pool = [sid for sid in source if sid not in excluded] or list(source)
    if not pool: return jsonify({'error': 'No shabads in this topic', 'total': 0}), 404
    return jsonify({'shabad': detail(random.SystemRandom().choice(pool)), 'total': len(ids), 'central_total': len(central(tag)), 'tag': tag})


@graph_bp.route('/topics/<tag>/review')
def topic_review(tag):
    if tag not in statistics(): return jsonify({'error': 'Unknown topic'}), 404
    review = json.loads((Path(config.DATA_DIR) / 'concept_review.json').read_text())
    record = review['concepts'][tag]
    reveal = request.args.get('reveal') == '1'
    samples = []
    for row in record['samples']:
        sample = {**detail(row['id']), 'line_index': row['line_index'], 'line_gurmukhi': row['line_gurmukhi']}
        if reveal: sample.update(category=row['category'], strength=row['strength'])
        samples.append(sample)
    manifest = json.loads((Path(config.DATA_DIR) / 'release-manifest.json').read_text())
    return jsonify({'topic': tag, 'dataset_id': manifest['dataset_id'], 'baseline_sha256': review['baseline_sha256'],
                    'note': 'Judge each example in its full shabad before revealing its previous assignment status. These selected examples do not estimate accuracy.',
                    'samples': samples, 'revealed': reveal})
