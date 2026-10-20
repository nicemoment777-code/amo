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
from contextlib import contextmanager
from print_order import group_key, grouped_print_order
from printer_routing import load_routes, choose_printer
from auto_print import auto_print_enabled
from pdf_archive import archive_directory, load_pdf
from print_journal import append_entry

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('SNOWBRICK_DATA_DIR', str(ROOT / 'data' / 'printing')))
ORIGIN = 'https://snowbrick.ru'
PRINTER = os.environ.get('SNOWBRICK_PRINTER', '4BARCODE 3B-T361U')
POPPLER = Path(os.environ.get('SNOWBRICK_POPPLER', str(Path(os.environ.get('USERPROFILE', '')) / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe')))
PYTHON_VENDOR = DATA / 'vendor'
sys.path.insert(0, str(PYTHON_VENDOR))

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def request(path, body=None):
    token = os.environ['PRINT_AGENT_TOKEN']
    req = Request(ORIGIN + '/api/print-agent/' + path, data=json.dumps(body).encode() if body is not None else None, headers={'Authorization': 'Bearer ' + token, 'Content-Type':'application/json'})
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
    source.write_bytes(load_pdf(archive_directory(),item,request))
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

def select_printer(item):
    return choose_printer(item,load_routes(DATA),PRINTER)

def print_label(image, details, printer=None):
    script = Path(os.environ.get('SNOWBRICK_PRINT_SCRIPT', str(ROOT/'ops'/'print-image.ps1')))
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy','Bypass','-File', str(script), '-ImagePath',str(image),'-WidthMm',str(details['widthMm']),'-HeightMm',str(details['heightMm']),'-PrinterName',printer or PRINTER],capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or 'PRINT_SUBMITTED' not in result.stdout:
        atomic_json(DATA/'printer-error.json', {'at':int(time.time()), 'exitCode':result.returncode, 'detail':result.stderr[-6000:]})
        raise RuntimeError('Драйвер не подтвердил отправку печати')

@contextmanager
def agent_lock():
    with open(DATA/'agent.lock','a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

def run_once():
    state_path = DATA / 'state.json'
    if not auto_print_enabled(DATA):
        summary={'at':datetime.now(timezone.utc).isoformat(),'submitted':0,'paused':True,'errors':[],'order':[]}
        print(json.dumps(summary,ensure_ascii=True))
        return summary
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
    count = 0; waiting = 0; errors = []; prepared = {}; ready_items = []
    routing=load_routes(DATA)
    for key in list(state['pending']):
        if not auto_print_enabled(DATA): break
        try:
            item = json.loads(request('item/' + key))
            if not item['composition'] or not item['hasLabel']:
                waiting += 1
                continue
            printer=choose_printer(item,routing,PRINTER)
            _, image, details = prepare(item, for_print=True)
            prepared[key] = (image, details, printer)
            ready_items.append(item)
        except Exception as error:
            errors.append({'id':key,'type':type(error).__name__})
    ordered = grouped_print_order(ready_items)
    for item in ordered:
        if not auto_print_enabled(DATA): break
        key = str(item['id'])
        image, details, printer = prepared[key]
        try:
            claim = json.loads(request('claim', {'id':item['id']}))
            if not claim['claimed']:
                state['printed'][key] = {'at':int(time.time()), 'status':'reserved-on-server'}
                del state['pending'][key]; atomic_json(state_path,state)
                continue
            # Persist BEFORE handing off to spooler: interrupted/ambiguous jobs
            # are never automatically repeated, preventing duplicate labels.
            state['uncertain'][key] = {'at': int(time.time()), 'status': 'submitting', 'printer':printer}
            del state['pending'][key]
            atomic_json(state_path, state)
            print_label(image, details, printer)
            append_entry(DATA,item,printer,'auto')
            request('complete', {'id':item['id']})
            state['printed'][key] = {'at': int(time.time()), 'status': 'submitted', 'printer':printer}
            del state['uncertain'][key]
            count += 1
            atomic_json(state_path, state)
        except Exception as error:
            errors.append({'id':key,'type':type(error).__name__})
    summary = {'at': datetime.now(timezone.utc).isoformat(), 'submitted':count, 'waiting':waiting,'pending':len(state['pending']), 'uncertain':len(state['uncertain']), 'errors':errors, 'order':[item['id'] for item in ordered]}
    atomic_json(DATA/'last-run.json', summary)
    print(json.dumps(summary, ensure_ascii=True))
    if errors or state['uncertain']:
        sys.exit(2)
    return summary

def prepare_batch(count):
    if count != 5:
        raise ValueError('Пробная партия должна содержать ровно 5 заявок')
    manifest = DATA/'test-batch-grouped.json'
    if manifest.exists():
        raise RuntimeError('Пробная партия уже подготовлена; используйте её существующий журнал')
    sample = json.loads((DATA/'sample.json').read_text(encoding='utf-8'))
    groups = {}
    for item in sample['items']:
        if not item['hasLabel'] or not item['composition'] or list(DATA.glob(f"test-{item['id']}*.json")):
            continue
        try:
            groups.setdefault(group_key(item), []).append(item)
        except ValueError:
            continue
    keys = sorted(groups, key=lambda key: (-len(groups[key]), key))
    if len(keys) < 2 or len(groups[keys[0]]) < 3 or len(groups[keys[1]]) < 2:
        raise RuntimeError('Не найдены две группы для пробной партии 3 + 2')
    selected = groups[keys[0]][:3] + groups[keys[1]][:2]
    records = []
    for item in grouped_print_order(selected):
        _, image, details = prepare(item, for_print=True, variant='-grouped')
        records.append({'id':item['id'],'articles':list(group_key(item)),'image':str(image),'details':details,'status':'prepared'})
    atomic_json(manifest, {'at':int(time.time()),'items':records})
    print(json.dumps({'prepared':len(records),'order':[{'id':r['id'],'articles':r['articles']} for r in records]}, ensure_ascii=True))

def print_batch():
    manifest = DATA/'test-batch-grouped.json'
    batch = json.loads(manifest.read_text(encoding='utf-8'))
    if len(batch['items']) != 5 or any(record['status'] != 'prepared' for record in batch['items']):
        raise RuntimeError('Партия уже отправлялась или её статус неоднозначен; автоматически не повторять')
    for record in batch['items']:
        record['status'] = 'submitting'
        atomic_json(manifest, batch)
        print_label(Path(record['image']), record['details'])
        record['status'] = 'submitted'
        atomic_json(manifest, batch)
    print(json.dumps({'submitted':5,'order':[r['id'] for r in batch['items']]}))

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--download', type=int)
    parser.add_argument('--prepare', type=int)
    parser.add_argument('--test-print', type=int)
    parser.add_argument('--run-once', action='store_true')
    parser.add_argument('--sku-only', action='store_true', help='Для пробного отпечатка оставить только значения в круглых скобках')
    parser.add_argument('--prepare-batch', type=int)
    parser.add_argument('--print-batch', action='store_true')
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
    elif args.prepare_batch:
        with agent_lock():
            prepare_batch(args.prepare_batch)
    elif args.print_batch:
        with agent_lock():
            print_batch()
    elif args.run_once:
        with agent_lock():
            run_once()

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Не удалось выполнить проверку печати: ' + type(error).__name__ + (f' HTTP {error.code}' if isinstance(error, HTTPError) else ''), file=sys.stderr)
        sys.exit(1)
