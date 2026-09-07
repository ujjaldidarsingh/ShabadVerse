"""Build a separate curated candidate from a preserved local dataset.

Usage: python bootstrap/setup.py --source data --output releases/candidate
No network, LLM calls, or replacement of the source dataset.
"""
import argparse
import os
import shutil
import sqlite3
from contextlib import closing
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from release import create


def build(source, output):
    source, output = source.resolve(), output.resolve()
    if output.exists() or output == source or source in output.parents:
        raise ValueError('Choose a new output directory outside the source dataset')
    required = ['draft_vocabulary.json', 'sggs_all_shabads.json', 'shabad_cache.db', 'sggs_sources.json', 'chroma_db']
    for name in required:
        if not (source / name).exists(): raise ValueError(f'Missing source asset: {name}. Restore a complete dataset snapshot first.')
    output.mkdir(parents=True)
    (output / 'BUILD_INCOMPLETE').write_text('Do not serve this directory until validation succeeds.\n')
    for name in required:
        src, dst = source / name, output / name
        if src.is_dir(): shutil.copytree(src, dst)
        elif src.suffix == '.db':
            with closing(sqlite3.connect(src.as_uri() + '?mode=ro', uri=True)) as read, closing(sqlite3.connect(dst)) as write: read.backup(write)
        else: shutil.copy2(src, dst)
    env = {**os.environ, 'SHABADVERSE_DATA_DIR': str(output), 'SHABADVERSE_BUILD': '1', 'SHABADVERSE_COMPARISON_SOURCE': str(source), 'ANONYMIZED_TELEMETRY': 'False', 'HF_HUB_OFFLINE': '1', 'PYTHONUNBUFFERED': '1'}
    for script in ('build_concept_tags.py', 'build_graph.py'):
        subprocess.run([sys.executable, '-B', str(ROOT / 'bootstrap' / script)], env=env, check=True)
    create(output)
    (output / 'BUILD_INCOMPLETE').unlink()
    print(f'Validated candidate: {output}\nHuman review and deployment approval remain pending.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try: build(args.source, args.output)
    except (ValueError, OSError, subprocess.CalledProcessError) as error: parser.exit(1, str(error) + '\n')
