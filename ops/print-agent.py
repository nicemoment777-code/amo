"""Локальный агент: данные заявок и PDF хранятся только в игнорируемом data/."""
import argparse
import json
import os
import sys
import time
import subprocess
import msvcrt
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data' / 'printing'
ORIGIN = 'https://snowbrick.ru'
PRINTER = '4BARCODE 3B-T361U'
POPPLER = Path(os.environ.get('USERPROFILE', '')) / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe'
PYTHON_VENDOR = DATA / 'vendor'
sys.path.insert(0, str(PYTHON_VENDOR))

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

def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)

def prepare(item, for_print=False, variant=''):
    from label_pdf import prepare_label
    source = DATA / f"label-{item['id']}-original.pdf"
    target = DATA / f"label-{item['id']}-print{variant}.pdf"
    source.write_bytes(request(f"label/{item['id']}"))
    details = prepare_label(source, target, item['composition'])
    prefix = target.with_suffix('')
    subprocess.run([str(POPPLER), '-r', '203', '-singlefile', '-png', str(target), str(prefix)], check=True, capture_output=True)
    # Check that barcodes which are readable in the original remain readable.
    subprocess.run([str(POPPLER), '-r', '203', '-singlefile', '-png', str(source), str(source.with_suffix(''))], check=True, capture_output=True)
    import zxingcpp
    from PIL import Image
    original_codes = zxingcpp.read_barcodes(Image.open(source.with_suffix('.png')))
    original = {code.text for code in original_codes}
    result_codes = zxingcpp.read_barcodes(Image.open(prefix.with_suffix('.png')))
    result = {code.text for code in result_codes}
    if not original or not original.issubset(result):
        raise RuntimeError('Проверка штрихкодов не пройдена; печать остановлена')
    details['barcodeOverlap'] = any(min(code.position.top_left.y, code.position.top_right.y, code.position.bottom_left.y, code.position.bottom_right.y) < 15/25.4*203 for code in result_codes)
    atomic_json(prefix.with_suffix('.json'), {**details, 'barcodeCount': len(result)})
    if for_print and details['barcodeOverlap']:
        raise RuntimeError('Область состава перекрывает исходный штрихкод; печать остановлена')
    return target, prefix.with_suffix('.png'), details

def print_label(image, details):
    result = subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT/'ops'/'print-image.ps1'), '-ImagePath',str(image),'-WidthMm',str(details['widthMm']),'-HeightMm',str(details['heightMm']),'-PrinterName',PRINTER],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if result.returncode or 'PRINT_SUBMITTED' not in result.stdout:
        raise RuntimeError('Драйвер не подтвердил отправку печати')

def run_once():
    state_path = DATA / 'state.json'
    if not state_path.exists():
        now = int(time.time())
        atomic_json(state_path, {'activatedAt': now, 'scanFrom': now, 'pending': {}, 'printed': {}, 'uncertain': {}})
    state = json.loads(state_path.read_text(encoding='utf-8'))
    scan_started = int(time.time())
    candidates = json.loads(request('leads?from=' + str(max(state['activatedAt'], state['scanFrom']-300))))
    for item in candidates['items']:
        key = str(item['id'])
        if key not in state['printed'] and key not in state['uncertain'] and item['createdAt'] >= state['activatedAt']:
            state['pending'][key] = item
    state['scanFrom'] = scan_started
    atomic_json(state_path, state)
    count = 0; waiting = 0; errors = []
    for key in list(state['pending']):
        try:
            item = json.loads(request('item/' + key))
            if not item['composition'] or not item['hasLabel']:
                waiting += 1
                continue
            _, image, details = prepare(item, for_print=True)
            # Persist BEFORE handing off to spooler: interrupted/ambiguous jobs
            # are never automatically repeated, preventing duplicate labels.
            state['uncertain'][key] = {'at': int(time.time()), 'status': 'submitting'}
            del state['pending'][key]
            atomic_json(state_path, state)
            print_label(image, details)
            state['printed'][key] = {'at': int(time.time()), 'status': 'submitted'}
            del state['uncertain'][key]
            count += 1
            atomic_json(state_path, state)
        except Exception as error:
            errors.append({'id':key,'type':type(error).__name__})
    summary = {'at': datetime.now(timezone.utc).isoformat(), 'submitted':count, 'waiting':waiting,'pending':len(state['pending']), 'uncertain':len(state['uncertain']), 'errors':errors}
    atomic_json(DATA/'last-run.json', summary)
    print(json.dumps(summary, ensure_ascii=True))
    if errors or state['uncertain']:
        sys.exit(2)

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--download', type=int)
    parser.add_argument('--prepare', type=int)
    parser.add_argument('--test-print', type=int)
    parser.add_argument('--run-once', action='store_true')
    parser.add_argument('--sku-only', action='store_true', help='Для пробного отпечатка оставить только значения в круглых скобках')
    args = parser.parse_args()
    if args.probe:
        data = json.loads(request('leads?from=0&sample=1'))
        (DATA / 'sample.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        ready = [v for v in data['items'] if v['hasLabel'] and v['composition']]
        print(json.dumps({'scanned': len(data['items']), 'ready': len(ready), 'hosts': sorted(set(v['labelHost'] for v in data['items'] if v['labelHost'])), 'fieldNames': data['fieldNames'], 'sampleIds': [v['id'] for v in ready[:3]]}, ensure_ascii=False))
    elif args.download:
        path = DATA / f'label-{args.download}-original.pdf'
        path.write_bytes(request(f'label/{args.download}'))
        from pypdf import PdfReader
        reader = PdfReader(path)
        print(json.dumps({'pages': len(reader.pages), 'sizesMm': [[round(float(p.mediabox.width)*25.4/72,2),round(float(p.mediabox.height)*25.4/72,2)] for p in reader.pages]}))
    elif args.prepare or args.test_print:
        selected = args.prepare or args.test_print
        data = json.loads((DATA/'sample.json').read_text(encoding='utf-8'))
        item = next(value for value in data['items'] if value['id'] == selected)
        variant = ''
        if args.sku_only:
            variant = '-sku'
        target, image, details = prepare(item, for_print=bool(args.test_print), variant=variant)
        if args.test_print:
            receipt = DATA / f'test-{selected}{variant}.json'
            if receipt.exists():
                raise RuntimeError('Тест уже отправлялся; повторная печать требует отдельного решения')
            atomic_json(receipt, {'id':selected,'status':'submitting','at':int(time.time())})
            print_label(image, details)
            atomic_json(receipt, {'id':selected,'status':'submitted','at':int(time.time())})
        print(json.dumps({'id':selected,'prepared':True,'submitted':bool(args.test_print),**details}))
    elif args.run_once:
        with open(DATA/'agent.lock','a+b') as lock:
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                run_once()
            finally:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Не удалось выполнить проверку печати: ' + type(error).__name__ + (f' HTTP {error.code}' if isinstance(error, HTTPError) else ''), file=sys.stderr)
        sys.exit(1)
