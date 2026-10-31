"""Постоянные записи отправки драйверу; чтение старых квитанций без миграции state."""
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import uuid
from print_order import articles

MOSCOW=timezone(timedelta(hours=3))


def append_entry(folder,item,printer,mode,receipt=None):
    at=int(datetime.now(timezone.utc).timestamp())
    try:
        try: skus=articles(item.get('composition',''))
        except ValueError: skus=[]
        entry={'id':str(item['id']),'at':at,'orderNumber':item.get('orderNumber'),
               'skus':skus,'printer':printer,'mode':mode,'status':'submitted','receipt':receipt}
        day=datetime.fromtimestamp(at,MOSCOW).strftime('%Y-%m-%d')
        target=Path(folder)/'print-history'/day; target.mkdir(parents=True,exist_ok=True)
        path=target/(uuid.uuid4().hex+'.json'); temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(entry,ensure_ascii=False),encoding='utf-8'); os.replace(temp,path)
        return True
    except Exception:
        # Сбой журнала после передачи драйверу не должен инициировать повтор печати.
        return False


def read_entries(folder):
    folder=Path(folder); result=[]; receipts=set(); recorded=set()
    def read(path):
        try: return json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError): return {}
    for path in (folder/'print-history').glob('*/*.json'):
        value=read(path)
        if not isinstance(value,dict) or not isinstance(value.get('at'),(int,float)) or not value.get('id'): continue
        result.append(value); recorded.add(str(value['id']))
        if value.get('receipt'): receipts.add(value['receipt'])
    for path in folder.glob('manual-reprint-*.json'):
        if path.name in receipts: continue
        value=read(path)
        if not isinstance(value,dict) or value.get('status')!='submitted': continue
        result.append({**value,'id':str(value['id']),'mode':'manual','legacy':True}); recorded.add(str(value['id']))
    state=read(folder/'state.json')
    if not isinstance(state,dict): state={}
    for key,value in state.get('printed',{}).items():
        if key not in recorded and value.get('status')=='submitted':
            result.append({**value,'id':key,'mode':'manual' if value.get('manual') else 'auto','legacy':True})
    recorded.update(str(v['id']) for v in result)
    for path in folder.glob('test-*.json'):
        value=read(path)
        if not isinstance(value,dict): continue
        for entry in value.get('items',[value]):
            key=str(entry.get('id',''))
            if not key or key in recorded or entry.get('status')!='submitted': continue
            result.append({'id':key,'at':entry.get('at',value.get('at',0)),
                           'printer':entry.get('printer',''),'status':'submitted','mode':'manual','legacy':True,'receipt':path.name})
            recorded.add(key)
    for key,value in state.get('uncertain',{}).items():
        result.append({**value,'id':key,'status':'uncertain','mode':'manual' if value.get('manual') else 'auto'})
    return sorted(result,key=lambda value:value.get('at',0),reverse=True)
