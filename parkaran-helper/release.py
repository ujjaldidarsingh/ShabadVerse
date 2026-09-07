"""Validate and fingerprint one complete, immutable ShabadVerse dataset."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JSON_ASSETS = ('draft_vocabulary.json', 'sggs_all_shabads.json', 'tag_vocabulary.json', 'concept_tags.json', 'similarity_graph.json', 'sggs_sources.json', 'concept_review.json')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def code_digest():
    paths = [ROOT / name for name in ('app.py', 'wsgi.py', 'config.py', 'release.py', 'requirements.txt', 'requirements.lock')]
    for name in ('api', 'database', 'enrichment', 'llm', 'templates', 'static'):
        paths += [p for p in (ROOT / name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    return hashlib.sha256(json.dumps({str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}, sort_keys=True).encode()).hexdigest()


def assets(directory):
    files = [directory / name for name in JSON_ASSETS + ('shabad_cache.db',)]
    files += sorted(p for p in (directory / 'chroma_db').rglob('*') if p.is_file())
    if not (directory / 'chroma_db/chroma.sqlite3').is_file(): raise ValueError('Missing vector database')
    return {str(p.relative_to(directory)): digest(p) for p in files}


def validate(directory):
    data = {name: json.loads((directory / name).read_text()) for name in JSON_ASSETS}
    rows = data['sggs_all_shabads.json']; ids = {str(s['banidb_shabad_id']) for s in rows}
    if len(rows) != 5542 or len(ids) != 5542: raise ValueError('Expected 5,542 unique SGGS records')
    graph = data['similarity_graph.json']; concepts = data['concept_tags.json']
    if set(graph['metadata']) != ids or set(graph['neighbors']) != ids: raise ValueError('Graph/corpus ID mismatch')
    vocab = data['tag_vocabulary.json']['theme_tags']
    definitions = data['draft_vocabulary.json']['concepts']
    if any(not definitions.get(t, {}).get('confirmed_by_ujjal') for t in vocab): raise ValueError('Unconfirmed concept definition')
    for row in rows:
        sid = str(row['banidb_shabad_id']); tags = set(row.get('tags', []))
        if tags != {a['concept'] for a in concepts.get(sid, [])} or tags != set(graph['metadata'][sid]['tags']): raise ValueError(f'Tag mismatch: {sid}')
        if tags - vocab.keys(): raise ValueError(f'Unknown tag: {sid}')
        for n in graph['neighbors'][sid]:
            if n['id'] not in ids or not 0 <= n['score'] <= 1: raise ValueError(f'Invalid edge: {sid}')
    for tag in vocab:
        expected = {str(row['banidb_shabad_id']) for row in rows if tag in row.get('tags', [])}
        if expected != set(graph['tag_index'].get(tag, [])) or len(expected) != vocab[tag]['count']: raise ValueError(f'Tag index mismatch: {tag}')
    review = data['concept_review.json']['concepts']
    if set(review) != set(vocab): raise ValueError('Review/concept mismatch')
    for tag, record in review.items():
        if not 0 <= record['threshold'] <= 1: raise ValueError(f'Invalid threshold: {tag}')
        for sample in record['samples']:
            matches = [a for a in concepts.get(sample['id'], []) if a['concept'] == tag]
            if not any(a['line_index'] == sample['line_index'] and a['line_gurmukhi'] == sample['line_gurmukhi'] for a in matches):
                raise ValueError(f'Review provenance mismatch: {tag}')
    by_id = {str(s['banidb_shabad_id']): s for s in rows}
    with closing(sqlite3.connect((directory / 'shabad_cache.db').as_uri() + '?mode=ro', uri=True)) as db:
        seen = set()
        for sid, response in db.execute('select shabad_id,response from shabad_cache'):
            sid = str(sid)
            if sid not in ids: continue
            raw = json.loads(response); verses = raw.get('verses', []); seen.add(sid)
            text = '\n'.join(v.get('verse', {}).get('unicode', '') for v in verses if v.get('verse', {}).get('unicode', ''))
            if text != by_id[sid]['gurmukhi_text']: raise ValueError(f'Scripture mismatch: {sid}')
            for assignment in concepts.get(sid, []):
                idx = assignment['line_index']
                if idx < 0 or idx >= len(verses) or assignment['line_gurmukhi'] != verses[idx].get('verse', {}).get('unicode', ''): raise ValueError(f'Provenance mismatch: {sid}')
        if seen != ids: raise ValueError('Incomplete scripture cache')
    with closing(sqlite3.connect((directory / 'chroma_db/chroma.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        counts = dict(db.execute('select c.name,count(e.id) from embeddings e join segments s on e.segment_id=s.id join collections c on s.collection=c.id group by c.name'))
    if counts.get('sggs_shabads') != 5542 or counts.get('sggs_lines', 0) < 1: raise ValueError('Incomplete vector collections')
    ak = sum(bool(s.get('amrit_keertan')) for s in data['sggs_sources.json'].values())
    if ak != 2078: raise ValueError('AK source coverage changed; domain review required')
    return {'shabads': len(ids), 'concepts': len(vocab), 'vectors': counts, 'ak_shabads': ak,
            'assignments': sum(map(len, concepts.values()))}


def create(directory):
    counts = validate(directory)
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    result = {'schema': 1, 'created_utc': datetime.now(timezone.utc).isoformat(), 'code_commit': sha,
              'code_sha256': code_digest(), 'assets': assets(directory), 'counts': counts,
              'cultural_review': 'pending', 'publish_approval': 'pending'}
    result['dataset_id'] = hashlib.sha256(json.dumps(result['assets'], sort_keys=True).encode()).hexdigest()
    temp = directory / 'release-manifest.json.tmp'
    temp.write_text(json.dumps(result, indent=2) + '\n'); temp.replace(directory / 'release-manifest.json')
    return result


def verify(directory):
    recorded = json.loads((directory / 'release-manifest.json').read_text())
    if recorded['assets'] != assets(directory): raise ValueError('Dataset hashes differ from the release manifest')
    if recorded['code_sha256'] != code_digest(): raise ValueError('Application differs from the release manifest')
    if recorded['counts'] != validate(directory): raise ValueError('Dataset counts differ')
    return recorded


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'verify'])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        manifest = (create if args.action == 'create' else verify)(args.directory.resolve())
        print(json.dumps(manifest, indent=2))
    except (ValueError, OSError, KeyError, sqlite3.Error) as error:
        parser.exit(1, str(error) + '\n')
