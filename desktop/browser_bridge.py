"""Исходящее подключение сайта к тому же worker и истории Windows, без открытых портов."""
import json
import os
import secrets
import socket
import sys
import threading
import time
from server_history import merge_history
from orders_model import read_json, sku_set, sku_color, print_status, receipt_statuses
from order_diagnostics import error_reasons
from printer_routing import load_routes, normalize_routes, PrinterRoutingError
from auto_print import auto_print_enabled
from print_journal import read_entries
from print_order import group_key


class BrowserBridge:
    def __init__(self, app):
        self.app=app; self.worker=app.worker; self.plans={}; self.view_from=None

    def ui(self, fn):
        event=threading.Event(); cancelled=threading.Event(); box={}
        def invoke():
            if cancelled.is_set(): return
            try: box['value']=fn()
            except Exception as error: box['error']=error
            finally: event.set()
        self.app.ui(invoke)
        if not event.wait(15):
            cancelled.set(); raise RuntimeError('Программа Windows занята')
        if 'error' in box: raise box['error']
        return box.get('value')

    def snapshot(self):
        app=self.app; worker=self.worker
        local=self.ui(lambda:{'items':list(app.catalog),'printers':list(app.printer_names),
            'printer':app.printer.get(),'startup':app.startup.get(),'historyStart':app.history_start.get(),
            'connection':app.connection.get(),'archive':app.archive_status.get(),'busy':app.busy or (worker.DATA/'browser-result-outbox.json').exists(),
            'articles':list(app.known_skus())})
        state=merge_history(worker.DATA,read_json(worker.DATA/'state.json',{})); receipts=receipt_statuses(worker.DATA)
        try: routes=load_routes(worker.DATA)
        except PrinterRoutingError: routes={'enabled':True,'routes':[],'error':'Назначения повреждены. Сохраните принтеры и артикулы заново.'}
        last=read_json(worker.DATA/'last-run.json',{})
        items=[]
        for item in local.pop('items'):
            skus=sku_set(item); confirmed,status=print_status(item['id'],state,receipts)
            blocked=str(item['id']) in state.get('uncertain',{}) or state.get('printed',{}).get(str(item['id']),{}).get('status')=='reserved-on-server'
            items.append({'id':item['id'],'orderNumber':item.get('orderNumber'),'createdAt':item.get('createdAt',0),
                'deliveryService':item.get('deliveryService','unknown'),'hasLabel':bool(item.get('hasLabel')),'skus':skus,'colors':sku_color(skus),
                'confirmed':confirmed,'statusText':status,'canPrint':bool(skus and item.get('hasLabel') and not blocked),
                'reasons':error_reasons(item,state,routes,local['printer'],last,receipts,local['printers'])})
        return {**local,'items':items,'routes':routes,'autoPrint':auto_print_enabled(worker.DATA),
                'journal':read_entries(worker.DATA),'at':int(time.time()),'version':1,
                'standalone':'--panel-only' not in sys.argv,'loopActive':bool(app.thread and app.thread.is_alive())}

    def plan(self, args):
        if callable(getattr(self.worker,'sync_history',None)): self.worker.sync_history()
        if hasattr(self.app,'printer'): self.worker.PRINTER=self.ui(lambda:self.app.printer.get())
        ids=args.get('ids',[])
        if not isinstance(ids,list) or not ids or len(ids)>1000: raise ValueError('Выберите от 1 до 1000 заявок')
        ids=list(dict.fromkeys(str(int(i)) for i in ids))
        state=merge_history(self.worker.DATA,read_json(self.worker.DATA/'state.json',{}))
        items=[]; printers={}; counts={}; repeats=0
        names=self.ui(lambda:list(self.app.printer_names))
        for key in ids:
            if key in state.get('uncertain',{}) or state.get('printed',{}).get(key,{}).get('status')=='reserved-on-server':
                raise ValueError('Есть неподтверждённая печать. Проверьте очередь Windows и журнал.')
            item=json.loads(self.worker.request('item/'+key)); group_key(item)
            if not item.get('hasLabel'): raise ValueError('В партии есть заявка без этикетки')
            printer=self.worker.select_printer(item)
            if printer not in names: raise ValueError('Назначенный принтер не установлен в Windows')
            items.append(item); printers[key]=printer; counts[printer]=counts.get(printer,0)+1
            repeats+=int(print_status(key,state,receipt_statuses(self.worker.DATA))[0])
        mode=args.get('mode','selected')
        if mode not in ('selected','article','carrier'): raise ValueError('Некорректный режим печати')
        if mode=='carrier' and (len({v.get('deliveryService') for v in items})!=1 or items[0].get('deliveryService') not in ('cdek','yandex')):
            raise ValueError('Выберите одну доставку')
        groups=len({group_key(v) for v in items})
        separators=0
        self.plans={k:v for k,v in self.plans.items() if v['until']>time.time()}
        token=secrets.token_urlsafe(24)
        self.plans[token]={'items':items,'printers':printers,'mode':mode,'until':time.time()+300}
        return {'plan':token,'count':len(items),'repeats':repeats,'printers':counts,'separators':separators,'groups':groups}

    def print_plan(self,args):
        plan=self.plans.pop(args.get('plan'),None)
        if not plan or plan['until']<=time.time(): raise ValueError('Подтверждение истекло. Выберите партию ещё раз.')
        # Every mode validates the WHOLE batch before the first driver call.
        from print_actions import _manual_batch_locked
        with self.worker.agent_lock():
            state=merge_history(self.worker.DATA,read_json(self.worker.DATA/'state.json',{}))
            for item in plan['items']:
                key=str(item['id'])
                if key in state.get('uncertain',{}) or state.get('printed',{}).get(key,{}).get('status')=='reserved-on-server':
                    raise ValueError('Печать не подтверждена. Проверьте очередь и журнал.')
                fresh=json.loads(self.worker.request('item/'+key))
                if group_key(fresh)!=group_key(item) or fresh.get('deliveryService')!=item.get('deliveryService') or self.worker.select_printer(fresh)!=plan['printers'][key] or not fresh.get('hasLabel'):
                    raise ValueError('Карточка или принтер изменились. Обновите и подтвердите партию ещё раз.')
                self.worker.prepare(fresh,for_print=True,variant='-browser-check')
            result=_manual_batch_locked(self.worker,plan['items'],plan['printers'],
                separate_delivery=plan['mode']=='article',separate_articles=plan['mode']=='carrier')
        self.app.ui(self.app.render)
        return {'submitted':len(result['submitted']),'failed':bool(result['failed'])}

    def execute(self,action,args):
        if action=='refresh':
            start=args.get('historyStart')
            if start:
                from datetime import datetime
                datetime.strptime(start,'%d.%m.%Y')
                self.view_from=None
                self.ui(lambda:(self.app.history_start.set(start),self.app.apply_history_start()))
            else:
                if 'from' in args:
                    value=args['from']
                    if not isinstance(value,(float,int)) or not 0<=value<=253402289999: raise ValueError('Некорректная дата')
                    self.view_from=int(value)
                self.ui(self.app.reload)
            return {'message':'Обновление карточек запрошено'}
        if action=='articles': self.ui(self.app.refresh_articles); return {'message':'Обновление артикулов запрошено'}
        if action=='printers': self.app.background(self.app.refresh_printers); return {'message':'Список принтеров обновляется'}
        if action=='archive': self.ui(lambda:self.app.start_archive(list(self.app.catalog))); return {'message':'Архивация запрошена'}
        if action=='openArchive': self.ui(self.app.open_archive); return {'message':'Архив открыт на выбранном компьютере'}
        if action in ('auto','startup'):
            if type(args.get('enabled')) is not bool: raise ValueError('Не задано состояние переключателя')
            if action=='auto':
                self.ui(self.app.start if args['enabled'] else self.app.stop)
                if auto_print_enabled(self.worker.DATA)!=args['enabled']: raise ValueError('Не удалось изменить автопечать. Проверьте принтер Windows.')
            else: self.ui(lambda:(self.app.startup.set(args['enabled']),self.app.autostart()))
            return {'message':'Настройка сохранена'}
        if not self.app.operation_lock.acquire(False): raise ValueError('На компьютере выполняется другое действие')
        try:
            if action=='plan': return self.plan(args)
            if action=='print':
                self.app.busy=True
                try: return self.print_plan(args)
                finally: self.app.busy=False
            if action=='settings':
                config=normalize_routes(args.get('routes'))
                names=self.ui(lambda:list(self.app.printer_names))
                if any(p and p not in names for p in config.get('deliveryPrinters',{}).values()): raise ValueError('Принтер доставки не установлен')
                if any(s['printer'] and s['printer'] not in names for s in config.get('slots',config['routes'])): raise ValueError('Выбранный принтер не установлен')
                printer=args.get('printer')
                if printer not in names: raise ValueError('Выберите принтер Windows')
                if not self.ui(lambda:self.app.store_routes(config)): raise ValueError('Назначения не сохранены')
                self.worker.PRINTER=printer
                self.ui(lambda:(self.app.printer.set(printer),self.app.save()))
                return {'message':'Назначения принтеров сохранены'}
            raise ValueError('Неизвестное действие')
        finally: self.app.operation_lock.release()

    def publish(self):
        while not self.app.closing.is_set():
            try:
                self.worker.request('browser/snapshot',{'name':socket.gethostname(),'snapshot':self.snapshot()})
            except Exception:
                pass
            self.app.closing.wait(5)

    def run(self):
        outbox=self.worker.DATA/'browser-result-outbox.json'
        while not self.app.closing.is_set():
            try:
                if outbox.exists():
                    pending=read_json(outbox,{})
                    self.worker.request('browser/result',pending)
                    outbox.unlink(missing_ok=True)
                command=json.loads(self.worker.request('browser/poll')).get('command')
                if command:
                    try: result=self.execute(command['action'],command['args']); ok=True
                    except (ValueError,RuntimeError) as error:
                        result={'message':'Действие остановлено: '+str(error) if type(error) is ValueError and not any(t in str(error) for t in ('http','\\','.pdf')) else 'Не удалось выполнить действие. Проверьте данные заявки, вес, назначения и очередь Windows.'}; ok=False
                    except Exception:
                        result={'message':'Действие не подтверждено. Проверьте связь, назначения и очередь Windows. Автоматического повтора нет.'}; ok=False
                    pending={'id':command['id'],'ok':ok,'result':result}
                    self.worker.atomic_json(outbox,pending)
                    self.worker.request('browser/result',pending)
                    outbox.unlink(missing_ok=True)
            except Exception:
                pass
            self.app.closing.wait(3)

    def start(self):
        threading.Thread(target=self.publish,daemon=True).start()
        threading.Thread(target=self.run,daemon=True).start()
