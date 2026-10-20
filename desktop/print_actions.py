"""Только явно подтверждённая печать с карточки; без сброса очереди/истории."""
import json
import time
import uuid
from print_order import grouped_print_order
from print_journal import append_entry

def manual_print(worker, item_id, expected_printer=None):
    with worker.agent_lock():
        return _manual_print_locked(worker,item_id,expected_printer)

def _manual_print_locked(worker, item_id, expected_printer=None):
    key=str(int(item_id))
    item=json.loads(worker.request('item/'+key))
    if not item.get('hasLabel') or not item.get('composition'):
        raise ValueError('Не заполнены этикетка или состав заказа')
    printer=worker.select_printer(item)
    if expected_printer is not None and printer!=expected_printer:
        raise ValueError('Назначение принтера изменилось. Обновите карточку и подтвердите печать ещё раз.')
    _,image,details=worker.prepare(item,for_print=True,variant='-manual')
    path=worker.DATA/'state.json'
    now=int(time.time())
    state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
        'activatedAt':now,'scanFrom':now,'pending':{},'printed':{},'uncertain':{}}
    worker.request('claim',{'id':int(key)})
    receipt=worker.DATA/f'manual-reprint-{key}-{uuid.uuid4().hex}.json'
    record={'id':int(key),'at':now,'status':'submitting','authorizedByOwner':True,'printer':printer}
    worker.atomic_json(receipt,record)
    state['uncertain'][key]={'at':now,'status':'submitting','manual':True,'printer':printer}
    state['pending'].pop(key,None)
    worker.atomic_json(path,state)
    worker.print_label(image,details,printer)
    state['printed'][key]={'at':int(time.time()),'status':'submitted','manual':True,'printer':printer}
    state['uncertain'].pop(key,None)
    worker.atomic_json(path,state)
    append_entry(worker.DATA,item,printer,'manual',receipt.name)
    server_recorded=True
    try: worker.request('complete',{'id':int(key)})
    except Exception: server_recorded=False
    worker.atomic_json(receipt,{**record,'status':'submitted','serverRecorded':server_recorded})

def manual_batch(worker, items, printers, on_submitted=None):
    """One explicitly confirmed copy per selected order; stop on any failure."""
    with worker.agent_lock():
        return _manual_batch_locked(worker,items,printers,on_submitted)

def _manual_batch_locked(worker, items, printers, on_submitted=None):
    values=list({str(item['id']):item for item in items}.values())
    ordered=grouped_print_order(values)
    path=worker.DATA/f'manual-batch-{uuid.uuid4().hex}.json'
    batch={'at':int(time.time()),'authorizedByOwner':True,'items':[{'id':v['id'],'status':'pending'} for v in ordered]}
    worker.atomic_json(path,batch)
    submitted=[]; failed=None
    for item,record in zip(ordered,batch['items']):
        key=str(item['id'])
        record['status']='working'; worker.atomic_json(path,batch)
        try:
            _manual_print_locked(worker,item['id'],printers[key])
        except Exception as error:
            record.update(status='failed',errorType=type(error).__name__)
            failed=key; worker.atomic_json(path,batch); break
        record['status']='submitted'; submitted.append(key); worker.atomic_json(path,batch)
        if on_submitted: on_submitted(key)
    batch['status']='failed' if failed else 'submitted'; worker.atomic_json(path,batch)
    return {'submitted':submitted,'failed':failed,'remaining':[str(v['id']) for v in batch['items'] if v['status']=='pending']}
