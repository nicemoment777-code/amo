"""Только явно подтверждённая печать с карточки; без сброса очереди/истории."""
import json
import time
import uuid
import tempfile
from print_order import grouped_print_order
from print_journal import append_entry
from orders_model import delivery_service

def manual_print(worker, item_id, expected_printer=None):
    with worker.agent_lock():
        return _manual_print_locked(worker,item_id,expected_printer)

def _manual_print_locked(worker, item_id, expected_printer=None, expected_service=None):
    key=str(int(item_id))
    item=json.loads(worker.request('item/'+key))
    if expected_service is not None and delivery_service(item)!=expected_service:
        raise ValueError('Доставка заявки изменилась. Обновите карточки и подтвердите партию ещё раз.')
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
    return details

def print_separator(worker,details,printer):
    """Одна белая страница того же размера; без заявки, штрихкодов и состава."""
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix='snowbrick-separator-') as folder:
        from pathlib import Path
        image=Path(folder)/'blank.png'
        with Image.new('RGB',(8,8),'white') as blank: blank.save(image)
        worker.print_label(image,details,printer)

def manual_batch(worker, items, printers, on_submitted=None, separate_delivery=False):
    """One explicitly confirmed copy per selected order; stop on any failure."""
    with worker.agent_lock():
        return _manual_batch_locked(worker,items,printers,on_submitted,separate_delivery)

def _manual_batch_locked(worker, items, printers, on_submitted=None, separate_delivery=False):
    values=list({str(item['id']):item for item in items}.values())
    ordered=grouped_print_order(values)
    if separate_delivery:
        # Сохраняем утверждённый порядок групп внутри каждой доставки.
        ordered=sorted(ordered,key=lambda item:{'cdek':0,'yandex':1}.get(delivery_service(item),2))
        if len({printers[str(item['id'])] for item in ordered})>1:
            raise ValueError('Разделённая партия артикула требует одного назначенного принтера.')
    path=worker.DATA/f'manual-batch-{uuid.uuid4().hex}.json'
    batch={'at':int(time.time()),'authorizedByOwner':True,'items':[{'id':v['id'],'status':'pending'} for v in ordered]}
    worker.atomic_json(path,batch)
    submitted=[]; failed=None; previous_service=None; previous_details=None
    for item,record in zip(ordered,batch['items']):
        key=str(item['id'])
        record['status']='working'; worker.atomic_json(path,batch)
        try:
            service=delivery_service(item)
            if separate_delivery and previous_service=='cdek' and service=='yandex':
                batch['separator']={'status':'submitting','printer':printers[key]}; worker.atomic_json(path,batch)
                print_separator(worker,previous_details,printers[key])
                batch['separator']['status']='submitted'; worker.atomic_json(path,batch)
            details=_manual_print_locked(worker,item['id'],printers[key],service if separate_delivery else None)
        except Exception as error:
            record.update(status='failed',errorType=type(error).__name__)
            failed=key; worker.atomic_json(path,batch); break
        record['status']='submitted'; submitted.append(key); worker.atomic_json(path,batch)
        previous_service=service; previous_details=details
        if on_submitted: on_submitted(key)
    batch['status']='failed' if failed else 'submitted'; worker.atomic_json(path,batch)
    return {'submitted':submitted,'failed':failed,'remaining':[str(v['id']) for v in batch['items'] if v['status']=='pending']}
