"""Keep historical and candidate writers away from the active dataset."""
import os
from pathlib import Path
import config


def require_build_target(legacy=False):
    target = Path(config.DATA_DIR).resolve()
    if target == (Path(config.BASE_DIR) / 'data').resolve() or os.getenv('SHABADVERSE_BUILD') != '1':
        raise RuntimeError('Use bootstrap/setup.py with a new --output directory; active data is protected.')
    if legacy and os.getenv('SHABADVERSE_ALLOW_LEGACY') != '1':
        raise RuntimeError('Historical pipeline. Set SHABADVERSE_ALLOW_LEGACY=1 only for an isolated historical rebuild.')
