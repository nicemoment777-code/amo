"""Только явно подтверждённая печать с карточки; без сброса очереди/истории."""
import json
import time
import uuid

def manual_print(worker, item_id, expected_printer=None):
    key=str(int(item_id))
    with worker.agent_lock():
        item=json.loads(worker.request('item/'+key))
        if not item.get('hasLabel') or not item.get('composition'):
            raise ValueError('Не заполнены этикетка или состав заказа')
        printer=worker.select_printer(item)
        if expected_printer is not None and printer!=expected_printer:
            raise ValueError('Назначение принтера изменилось. Обновите карточку и подтвердите печать ещё раз.')
        _,image,details=worker.prepare(item,for_print=True,variant='-manual')
        path=worker.DATA/'state.json'
        # A first manual job also establishes a safe automatic activation boundary.
        now=int(time.time())
        state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
            'activatedAt':now,'scanFrom':now,'pending':{},'printed':{},'uncertain':{}}
        # Claim before spooler handoff; a previous claim is allowed ONLY here,
        # because the owner has confirmed this exact manual copy in the UI.
        worker.request('claim',{'id':int(key)})
        receipt=worker.DATA/f'manual-reprint-{key}-{uuid.uuid4().hex}.json'
        record={'id':int(key),'at':now,'status':'submitting','authorizedByOwner':True,'printer':printer}
        worker.atomic_json(receipt,record)
        state['uncertain'][key]={'at':now,'status':'submitting','manual':True,'printer':printer}
        state['pending'].pop(key,None)
        worker.atomic_json(path,state)
        worker.print_label(image,details,printer)
        # Driver confirmation is recorded locally even if server acknowledgement fails.
        state['printed'][key]={'at':int(time.time()),'status':'submitted','manual':True,'printer':printer}
        state['uncertain'].pop(key,None)
        worker.atomic_json(path,state)
        server_recorded=True
        try: worker.request('complete',{'id':int(key)})
        except Exception: server_recorded=False
        worker.atomic_json(receipt,{**record,'status':'submitted','serverRecorded':server_recorded})
