"""Обмен подтверждениями печати. Сетевой сбой никогда не повторяет печать."""
import hashlib
import json
from print_journal import read_entries


def sync_history(worker):
    folder=worker.DATA
    ack_path=folder/'server-history-ack.json'
    try: ack=set(json.loads(ack_path.read_text(encoding='utf-8')))
    except FileNotFoundError: ack=set()
    pending=[]
    for entry in read_entries(folder):
        if entry.get('status')!='submitted': continue
        value={key:entry.get(key) for key in ('id','at','printer','mode','receipt')}
        value['id']=str(value['id']); value['at']=int(value['at'] or 0)
        value['printer']=value['printer'] or ''
        event_id=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if event_id not in ack:
            pending.append({**value,'eventId':event_id,'status':'submitted'})
    for offset in range(0,len(pending),100):
        batch=pending[offset:offset+100]
        worker.request('history',{'entries':batch})
        ack.update(e['eventId'] for e in batch)
        worker.atomic_json(ack_path,sorted(ack))
    remote=json.loads(worker.request('history'))
    if not isinstance(remote.get('printed'),dict) or not isinstance(remote.get('uncertain'),dict):
        raise ValueError('Некорректная серверная история')
    worker.atomic_json(folder/'server-history.json',remote)
    (folder/'history-sync-error.json').unlink(missing_ok=True)
    return remote


def merge_history(folder,state):
    # Не меняем state.json и не снимаем локальную неопределённую попытку.
    try: remote=json.loads((folder/'server-history.json').read_text(encoding='utf-8'))
    except FileNotFoundError: return state
    printed={**state.get('printed',{})}
    for key,value in remote.get('printed',{}).items():
        printed[key]={**value,'serverConfirmed':True}
    for key,value in remote.get('uncertain',{}).items():
        printed.setdefault(key,value)
    return {**state,'printed':printed}
