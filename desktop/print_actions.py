"""Только явно подтверждённая печать с карточки; без сброса очереди/истории."""
import json
import time
import uuid
from print_order import grouped_print_order, group_key
from print_journal import append_entry
from orders_model import delivery_service

def manual_print(worker, item_id, expected_printer=None):
    with worker.agent_lock():
        return _manual_print_locked(worker,item_id,expected_printer)

class PreparationError(ValueError):
    """No claim, receipt or driver call has happened."""

def preparation_error(worker, key, error=None):
    path=worker.DATA/'manual-preparation-errors.json'
    errors=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if error is None: errors.pop(str(key),None)
    else:
        message='Не удалось подготовить этикетку: проверьте PDF, артикулы и назначения принтеров, затем повторите ручную печать.'
        if getattr(error,'code',None)==404: message='Исходная этикетка недоступна (404). Обновите PDF в amoCRM и карточки заявки.'
        errors[str(key)]={'at':int(time.time()),'type':type(error).__name__,'message':message}
    worker.atomic_json(path,errors)

def prepare_manual(worker,item_id,expected_printer=None,expected_service=None,expected_skus=None,variant='-manual'):
    try:
        item=json.loads(worker.request('item/'+str(int(item_id))))
        group_key(item)
        if expected_service is not None and delivery_service(item)!=expected_service:
            raise ValueError('Доставка заявки изменилась. Обновите карточки.')
        if expected_skus is not None and group_key(item)!=expected_skus:
            raise ValueError('Артикулы заявки изменились. Обновите карточки.')
        if not item.get('hasLabel'): raise ValueError('Нет этикетки')
        printer=worker.select_printer(item)
        if expected_printer is not None and printer!=expected_printer:
            raise ValueError('Назначение принтера изменилось. Обновите карточку.')
        _,image,details=worker.prepare(item,for_print=True,variant=variant)
        preparation_error(worker,item_id)
        return item,printer,image,details
    except Exception as error:
        preparation_error(worker,item_id,error)
        raise PreparationError('Этикетка не подготовлена. Откройте «Причина» на карточке.') from error

def _manual_print_locked(worker, item_id, expected_printer=None, expected_service=None, expected_skus=None):
    key=str(int(item_id))
    item,printer,image,details=prepare_manual(worker,item_id,expected_printer,expected_service,expected_skus)
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
    if callable(getattr(worker,'sync_history',None)):
        try: worker.sync_history()
        except Exception:
            worker.atomic_json(worker.DATA/'history-sync-error.json',{'pending':True,'at':int(time.time())})
    return details

def manual_batch(worker, items, printers, on_submitted=None, separate_delivery=False, separate_articles=False):
    """One explicitly confirmed copy per selected order; skip preparation failures; stop on uncertain driver failure."""
    with worker.agent_lock():
        return _manual_batch_locked(worker,items,printers,on_submitted,separate_delivery,separate_articles)

def _manual_batch_locked(worker, items, printers, on_submitted=None, separate_delivery=False, separate_articles=False):
    values=list({str(item['id']):item for item in items}.values())
    skipped=[]; valid=[]
    for item in values:
        key=str(item['id'])
        try: group_key(item); valid.append(item)
        except (ValueError,KeyError) as error:
            preparation_error(worker,key,error);skipped.append(key)
    ordered=grouped_print_order(valid)
    if separate_articles:
        if len({delivery_service(v) for v in ordered})>1 or any(delivery_service(v)=='unknown' for v in ordered):
            raise ValueError('Печатать всё можно только для одной доставки.')
        ready=[]
        for item in ordered:
            try:
                prepare_manual(worker,item['id'],printers.get(str(item['id'])),delivery_service(item),group_key(item),'-batch-check')
                ready.append(item)
            except PreparationError: skipped.append(str(item['id']))
        ordered=grouped_print_order(ready)
    if separate_delivery:
        # Сохраняем утверждённый порядок групп внутри каждой доставки.
        ordered=sorted(ordered,key=lambda item:{'cdek':0,'yandex':1}.get(delivery_service(item),2))
    path=worker.DATA/f'manual-batch-{uuid.uuid4().hex}.json'
    batch={'at':int(time.time()),'authorizedByOwner':True,'items':[{'id':v['id'],'status':'pending'} for v in ordered]}
    worker.atomic_json(path,batch)
    submitted=[]; failed=None
    for item,record in zip(ordered,batch['items']):
        key=str(item['id'])
        record['status']='working'; worker.atomic_json(path,batch)
        try:
            service=delivery_service(item)
            if separate_articles:
                _manual_print_locked(worker,item['id'],printers[key],service,group_key(item))
            else:
                _manual_print_locked(worker,item['id'],printers[key],service if separate_delivery else None)
        except PreparationError:
            record['status']='skipped';skipped.append(key);worker.atomic_json(path,batch);continue
        except Exception as error:
            record.update(status='failed',errorType=type(error).__name__)
            failed=key; worker.atomic_json(path,batch); break
        record['status']='submitted'; submitted.append(key); worker.atomic_json(path,batch)
        if on_submitted: on_submitted(key)
    batch['status']='failed' if failed else 'submitted'; worker.atomic_json(path,batch)
    result={'submitted':submitted,'failed':failed,'remaining':[str(v['id']) for v in batch['items'] if v['status']=='pending']}

    if skipped: result['skipped']=skipped
    return result
