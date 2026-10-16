"""Локальный агент: данные заявок и PDF хранятся только в игнорируемом data/."""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data' / 'printing'
ORIGIN = 'https://snowbrick.ru'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def request(path):
    token = os.environ['PRINT_AGENT_TOKEN']
    req = Request(ORIGIN + '/api/print-agent/' + path, headers={'Authorization': 'Bearer ' + token})
    with build_opener(NoRedirect()).open(req, timeout=60) as response:
        content = response.read(10_000_001)
        if len(content) > 10_000_000:
            raise RuntimeError('Ответ превышает допустимый размер')
        return content

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    if args.probe:
        data = json.loads(request('leads?from=0&sample=1'))
        (DATA / 'sample.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        ready = [v for v in data['items'] if v['hasLabel'] and v['composition']]
        print(json.dumps({'scanned': len(data['items']), 'ready': len(ready), 'hosts': sorted(set(v['labelHost'] for v in data['items'] if v['labelHost'])), 'fieldNames': data['fieldNames'], 'sampleIds': [v['id'] for v in ready[:3]]}, ensure_ascii=False))

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Не удалось выполнить проверку печати: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
