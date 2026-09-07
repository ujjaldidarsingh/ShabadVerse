import json
from urllib.parse import urlencode
from app import app
from pathlib import Path
import release
client=app.test_client()
paths=['/health/ready','/api/graph/init','/about','/api/topics/Naam','/api/topics/Naam/review',
       '/api/graph/shabad/970/verses','/api/graph/semantic-search?'+urlencode({'q':'humility'}),
       '/api/graph/neighbors/970?max_neighbors=6',
       '/api/graph/neighbors/970?match=line&max_neighbors=6']
for path in paths:
    response=client.get(path)
    assert response.status_code==200,(path,response.status_code,response.data[:300])
    data=response.get_json(silent=True)
    if 'neighbors' in path:
        assert 'source_mode' not in data
        assert all('is_amrit_keertan' not in n for group in data['by_tag'].values() for n in group)
    print('PASS',path,flush=True)
recorded=json.loads(Path('/app/data/release-manifest.json').read_text())
assert release.assets(Path('/app/data'))==recorded['assets']
assert release.code_digest()==recorded['code_sha256']
print('PASS manifest unchanged after offline queries',flush=True)
