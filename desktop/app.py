"""Личное Windows-приложение Снегострой. В установщике нет ключей и заказов."""
import base64
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import queue
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox
from urllib.request import Request, build_opener, HTTPRedirectHandler
import webbrowser
import winreg

TITLE = 'Снегострой — печать СДЭК'
ORIGIN = 'https://snowbrick.ru'
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
HOME = Path(os.environ.get('SNOWBRICK_HOME', str(Path(os.environ['LOCALAPPDATA'])/'SnowbrickPrinter')))
HOME.mkdir(parents=True, exist_ok=True)
CONFIG = HOME/'settings.json'
TOKEN = HOME/'device-key.bin'
os.environ.setdefault('SNOWBRICK_DATA_DIR', str(HOME/'printing'))
runtime = Path(os.environ['USERPROFILE'])/'.cache/codex-runtimes/codex-primary-runtime/dependencies'
os.environ.setdefault('SNOWBRICK_POPPLER', str(BASE/'poppler'/'pdftoppm.exe' if getattr(sys,'frozen',False) else runtime/'native/poppler/Library/bin/pdftoppm.exe'))
os.environ.setdefault('SNOWBRICK_PRINT_SCRIPT', str(BASE/'ops'/'print-image.ps1'))
sys.path.insert(0, str(BASE/'ops'))
from orders_model import MOSCOW, read_json, order_groups, parse_period, merge_catalog, receipt_statuses, sku_set, order_title
from orders_view import OrdersBoard, DatePicker, BG, INK, MUTED
from printer_routing import load_routes, normalize_routes, choose_printer, PrinterRoutingError
from printer_panel import PrinterPanel, checkbox_popup

class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]

def protect(data, decrypt=False):
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise OSError('Не удалось открыть защищённый ключ этого пользователя Windows')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(target.data, ctypes.c_void_p))

def device_token():
    if not TOKEN.exists():
        value = secrets.token_urlsafe(32)
        TOKEN.write_bytes(protect(value.encode()))
    return protect(TOKEN.read_bytes(), decrypt=True).decode()

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def pair_request(path, body):
    req = Request(ORIGIN+'/api/print-pair/'+path, data=json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    with build_opener(NoRedirect()).open(req, timeout=30) as response:
        return json.loads(response.read(4096))

def powershell(command):
    result = subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError('Не удалось обратиться к принтерам Windows')
    return result.stdout.strip()

def load_worker():
    spec = importlib.util.spec_from_file_location('snowbrick_worker', BASE/'ops'/'print-agent.py')
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    worker.DATA.mkdir(parents=True, exist_ok=True)
    return worker

class App:
    def __init__(self, root, smoke=False):
        self.root = root; self.running = False; self.busy = False; self.stop_event = threading.Event(); self.thread = None
        self.actions = queue.Queue(); self.operation_lock = threading.Lock(); self.settings_window = None
        self.config = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}
        self.worker = load_worker()
        self.printer=tk.StringVar(value=self.config.get('printer','4BARCODE 3B-T361U')); self.printer_names=[]
        routing_error=None
        try: self.routes=load_routes(self.worker.DATA)
        except PrinterRoutingError as e:
            self.routes={'enabled':True,'routes':[]}; routing_error=str(e)
        self.card_filter=None; self.filter_checks={}
        self.worker.POPPLER = Path(os.environ['SNOWBRICK_POPPLER'])
        self.token = os.environ.get('PRINT_AGENT_TOKEN') or device_token(); os.environ['PRINT_AGENT_TOKEN'] = self.token
        root.title(TITLE); root.geometry('1440x1000'); root.minsize(1120,850); root.configure(bg=BG)
        style=ttk.Style(); style.theme_use('clam'); style.configure('.',font=('Segoe UI',10))
        style.configure('TButton',padding=(12,8),background='#ffffff',foreground=INK,borderwidth=0)
        style.map('TButton',background=[('active','#e8edf8')])
        style.configure('Accent.TButton',background='#142346',foreground='white')
        style.map('Accent.TButton',background=[('active','#294576')])
        style.configure('TFrame',background=BG); style.configure('TLabel',background=BG,foreground=INK)
        frame=ttk.Frame(root,padding=(28,20,28,12)); frame.pack(fill='x')
        title=ttk.Frame(frame); title.pack(fill='x')
        ttk.Label(title,text='Заказы',font=('Segoe UI',30,'bold')).pack(side='left')
        ttk.Button(title,text='Настройки',command=self.settings).pack(side='right')
        ttk.Label(title,text='СНЕГОСТРОЙ',foreground=MUTED,font=('Segoe UI',11,'bold')).pack(side='right',padx=24)
        ttk.Label(frame,text='Этикетки СДЭК  /  Группировка по артикулам',foreground=MUTED).pack(anchor='w',pady=(0,14))
        filters=ttk.Frame(frame); filters.pack(fill='x')
        now=datetime.now(MOSCOW); today=now.strftime('%d.%m.%Y')
        self.day_from=tk.StringVar(value=today); self.day_to=tk.StringVar(value=today)
        self.time_from=tk.StringVar(value='00:00'); self.time_to=tk.StringVar(value='23:59')
        for label,day,clock in [('С',self.day_from,self.time_from),('По',self.day_to,self.time_to)]:
            ttk.Label(filters,text=label).pack(side='left',padx=(0,8))
            ttk.Entry(filters,textvariable=day,width=11).pack(side='left')
            ttk.Button(filters,text='▦',width=2,command=lambda v=day:DatePicker(root,v)).pack(side='left',padx=(2,6))
            ttk.Spinbox(filters,textvariable=clock,values=[f'{h:02}:{m:02}' for h in range(24) for m in (0,30)],width=6,wrap=True).pack(side='left',padx=(0,16))
        ttk.Label(filters,text='МСК',foreground=MUTED).pack(side='left',padx=(0,12))
        ttk.Button(filters,text='Показать',style='Accent.TButton',command=lambda:self.reload(True)).pack(side='left')
        ttk.Button(filters,text='Сегодня',command=self.today).pack(side='left',padx=6)
        ttk.Button(filters,text='Последние 2 часа',command=self.last_two_hours).pack(side='left')
        article_filters=ttk.Frame(frame); article_filters.pack(fill='x',pady=(10,0))
        ttk.Label(article_filters,text='Карточки по артикулу').pack(side='left',padx=(0,10))
        self.article_filter_button=ttk.Button(article_filters,text='Все артикулы ▾',width=35,command=self.article_filter_menu)
        self.article_filter_button.pack(side='left')
        ttk.Button(article_filters,text='Показать все',command=self.reset_article_filter).pack(side='left',padx=8)
        self.printer_panel=PrinterPanel(frame,self.routes,self.known_skus,self.store_routes,self.note)
        self.printer_panel.pack(fill='x',pady=(14,0))
        summary=ttk.Frame(frame); summary.pack(fill='x',pady=(16,0))
        self.counts=tk.StringVar(value='Загружаем заказы…')
        ttk.Label(summary,textvariable=self.counts,font=('Segoe UI',11,'bold')).pack(side='left')
        ttk.Label(summary,text='✓ Отправлено     ! Нет подтверждения',foreground=MUTED).pack(side='right')
        self.board=OrdersBoard(root,self.reprint); self.board.pack(fill='both',expand=True)
        footer=ttk.Frame(root,padding=(28,10)); footer.pack(fill='x')
        self.status=tk.StringVar(value='Выберите принтер в настройках. Проверка заявок каждые 5 минут.')
        ttk.Label(footer,textvariable=self.status,foreground=MUTED).pack(side='left')
        ttk.Button(footer,text='Обновить',command=lambda:self.reload()).pack(side='right')
        self.startup=tk.BooleanVar(value=self.config.get('startup',False))
        self.catalog=read_json(self.worker.DATA/'order-catalog.json',[])
        self.settings_log=[]
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.pump(); self.render()
        if routing_error: self.note(routing_error)
        if not smoke:
            self.background(self.refresh_printers); self.reload(); root.after(300000,self.periodic_view)

    def note(self,text):
        self.status.set(text); self.settings_log.append(datetime.now(MOSCOW).strftime('%H:%M:%S')+'  '+text)
        self.settings_log=self.settings_log[-100:]
        if self.settings_window and self.settings_window.winfo_exists():
            self.log.configure(state='normal'); self.log.delete('1.0','end'); self.log.insert('end','\n'.join(self.settings_log)); self.log.see('end'); self.log.configure(state='disabled')
    def ui(self,callback): self.actions.put(callback)
    def pump(self):
        while True:
            try: callback=self.actions.get_nowait()
            except queue.Empty: break
            try: callback()
            except Exception: self.note('Не удалось прочитать или обновить панель. Проверьте локальный журнал; история не сбрасывалась.')
        self.root.after(70,self.pump)
    def background(self,callback): threading.Thread(target=callback,daemon=True).start()
    def known_skus(self):
        return sorted({sku for item in self.catalog for sku in sku_set(item)})
    def article_filter_menu(self):
        try: start,end=self.period()
        except ValueError as e: return self.note(str(e))
        available={sku for item in self.catalog if start<=item.get('createdAt',0)<=end for sku in sku_set(item)}
        unknown=any(not sku_set(item) for item in self.catalog if start<=item.get('createdAt',0)<=end)
        # Preserve the active choice even when switching to a period without it.
        if self.card_filter is not None: available.update(s for s in self.card_filter if s is not None)
        values=sorted(available)+([None] if unknown or self.card_filter is not None and None in self.card_filter else [])
        self.filter_checks={sku:tk.BooleanVar(value=self.card_filter is not None and sku in self.card_filter) for sku in values}
        entries=[(sku if sku is not None else 'Без артикула',var,False,self.article_filter_changed) for sku,var in self.filter_checks.items()]
        checkbox_popup(self.root,self.article_filter_button,entries,[('Показать все артикулы',self.reset_article_filter)])
    def article_filter_changed(self):
        self.card_filter={sku for sku,var in self.filter_checks.items() if var.get()}
        self.render(True)
    def reset_article_filter(self):
        self.card_filter=None; self.filter_checks={}; self.render(True)
    def store_routes(self,config):
        if self.busy:
            self.note('Дождитесь завершения текущего действия.'); return False
        try:
            config=normalize_routes(config)
            with self.worker.agent_lock(): self.worker.atomic_json(self.worker.DATA/'printer-routes.json',config)
            self.routes=config; self.render()
            self.note('Назначения сохранены. Артикулы закреплены за выбранными принтерами.')
            return True
        except PrinterRoutingError as e: self.note(str(e))
        except OSError: self.note('Сейчас выполняется печать. Дождитесь завершения и сохраните назначение ещё раз.')
        return False
    def period(self): return parse_period(self.day_from.get(),self.time_from.get(),self.day_to.get(),self.time_to.get())
    def render(self,reset=False):
        try: start,end=self.period()
        except ValueError as e: return self.note(str(e))
        state=read_json(self.worker.DATA/'state.json',{})
        groups=order_groups(self.catalog,start,end,state,receipt_statuses(self.worker.DATA),self.card_filter)
        cards=[item for group in groups for item in group['items']]
        confirmed=sum(v['confirmed'] for v in cards)
        self.counts.set(f'Заказов: {len(cards)}   ·   Групп: {len(groups)}   ·   Отправлено: {confirmed}   ·   Без подтверждения: {len(cards)-confirmed}')
        if self.card_filter is None: label='Все артикулы ▾'
        elif not self.card_filter: label='Артикулы не выбраны ▾'
        elif len(self.card_filter)==1:
            value=next(iter(self.card_filter)) or 'Без артикула'
            label=(value if len(value)<=38 else value[:35]+'…')+' ▾'
        else: label=f'Выбрано артикулов: {len(self.card_filter)} ▾'
        self.article_filter_button.configure(text=label)
        self.board.set_groups(groups,reset_scroll=reset,empty='Нет заказов для выбранных дат и артикулов. Измените фильтр или нажмите «Показать все».')
    def today(self):
        value=datetime.now(MOSCOW).strftime('%d.%m.%Y')
        self.day_from.set(value); self.day_to.set(value); self.time_from.set('00:00'); self.time_to.set('23:59'); self.reload(True)
    def last_two_hours(self):
        end=datetime.now(MOSCOW); start=end-timedelta(hours=2)
        self.day_from.set(start.strftime('%d.%m.%Y')); self.day_to.set(end.strftime('%d.%m.%Y'))
        self.time_from.set(start.strftime('%H:%M')); self.time_to.set(end.strftime('%H:%M')); self.reload(True)
    def reload(self,reset=False):
        try: start,end=self.period()
        except ValueError as e: return self.note(str(e))
        if not self.operation_lock.acquire(False): return self.note('Дождитесь завершения текущего действия.')
        self.busy=True; self.board.set_enabled(False); self.note('Получаем заказы из amoCRM…')
        def work():
            try:
                incoming=json.loads(self.worker.request('leads?from='+str(start)))['items']
                # Replace this interval with the fresh API result; no stale moved/deleted cards.
                cached=[v for v in self.catalog if v.get('createdAt',0)<start]
                catalog=merge_catalog(cached,incoming)
                self.worker.atomic_json(self.worker.DATA/'order-catalog.json',catalog)
                def loaded():
                    self.catalog=catalog; self.render(reset)
                    self.note('Заказы обновлены. Зелёная отметка — подтверждение отправки драйверу.')
                self.ui(loaded)
            except Exception:
                self.ui(lambda:self.note('Не удалось обновить заказы. Показана сохранённая история; проверьте подключение.'))
            finally:
                self.busy=False; self.operation_lock.release(); self.ui(lambda:self.board.set_enabled(True))
        self.background(work)
    def periodic_view(self):
        if not self.busy: self.reload()
        self.root.after(300000,self.periodic_view)
    def settings(self):
        if self.settings_window and self.settings_window.winfo_exists(): return self.settings_window.lift()
        window=tk.Toplevel(self.root); self.settings_window=window; window.title('Настройки печати'); window.geometry('650x610'); window.transient(self.root)
        frame=ttk.Frame(window,padding=24); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Настройки печати',font=('Segoe UI',20,'bold')).pack(anchor='w')
        ttk.Label(frame,text='snegostroy.amocrm.ru · проверка каждые 5 минут',foreground=MUTED).pack(anchor='w',pady=(4,16))
        row=ttk.Frame(frame); row.pack(fill='x')
        ttk.Button(row,text='Подключить компьютер',command=self.pair).pack(side='left')
        ttk.Button(row,text='Доступ на сайте',command=lambda:webbrowser.open(ORIGIN+'/integrations/amocrm')).pack(side='left',padx=8)
        ttk.Label(frame,text='Принтер Windows').pack(anchor='w',pady=(20,4))
        self.printers=ttk.Combobox(frame,textvariable=self.printer,state='readonly',values=self.printer_names); self.printers.pack(fill='x')
        self.printers.bind('<<ComboboxSelected>>',lambda _:self.save())
        ttk.Checkbutton(frame,text='Запускать при входе в Windows',variable=self.startup,command=self.autostart).pack(anchor='w',pady=12)
        row=ttk.Frame(frame); row.pack(fill='x')
        ttk.Button(row,text='Включить автопечать',command=self.start).pack(side='left')
        ttk.Button(row,text='Остановить',command=self.stop).pack(side='left',padx=8)
        ttk.Button(row,text='Открыть журнал',command=lambda:os.startfile(str(self.worker.DATA))).pack(side='left')
        ttk.Label(frame,text='Этикетка 1:1 · верхняя полоса 70 × 15 мм · только артикулы.\nПовторная печать — с карточки конкретного заказа.\nЗелёный значок подтверждает передачу драйверу, а не выход бумаги.',foreground=MUTED).pack(anchor='w',pady=18)
        self.log=tk.Text(frame,height=8,wrap='word',font=('Segoe UI',10),bd=0,padx=10,pady=10)
        self.log.pack(fill='both',expand=True); self.log.insert('end','\n'.join(self.settings_log)); self.log.configure(state='disabled')
    def save(self):
        self.config.update(printer=self.printer.get(),startup=self.startup.get(),enabled=self.running)
        temp=CONFIG.with_suffix('.tmp'); temp.write_text(json.dumps(self.config,ensure_ascii=False),encoding='utf-8'); os.replace(temp,CONFIG)
    def refresh_printers(self):
        try:
            data=json.loads(powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8; @(Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name) | ConvertTo-Json -Compress"))
            names=data if isinstance(data,list) else [data]
            def loaded():
                self.printer_names=names
                self.printer_panel.set_printers(names)
                if self.settings_window and self.settings_window.winfo_exists(): self.printers.configure(values=names)
                if self.config.get('enabled') and '--panel-only' not in sys.argv: self.start()
            self.ui(loaded)
        except Exception: self.ui(lambda:self.note('Не удалось получить список принтеров. Проверьте драйвер Windows.'))
    def pair(self):
        if self.running or self.busy: return self.note('Сначала остановите печать и дождитесь завершения задания.')
        self.note('Получаем код подключения…')
        def work():
            try:
                data=pair_request('start',{'tokenHash':hashlib.sha256(self.token.encode()).hexdigest()})
                code=data['code']
                def show():
                    self.note('Код подключения: '+code[:4]+'-'+code[4:])
                    webbrowser.open(ORIGIN+'/integrations/amocrm')
                    messagebox.showinfo(TITLE,'Войдите на snowbrick.ru. В разделе «Компьютеры печати» введите код '+code[:4]+'-'+code[4:]+'. Разрешите доступ своему компьютеру.')
                self.ui(show)
                for _ in range(120):
                    time.sleep(5)
                    if pair_request('poll',{'requestId':data['requestId'],'pollSecret':data['pollSecret']})['approved']:
                        self.ui(lambda:self.note('Компьютер подключён. В настройках выберите принтер и включите автопечать.')); return
                self.ui(lambda:self.note('Код истёк. Нажмите «Подключить компьютер» ещё раз.'))
            except Exception: self.ui(lambda:self.note('Не удалось подключить компьютер. Проверьте интернет и повторите.'))
        self.background(work)
    def start(self):
        if self.running: return
        if self.thread and self.thread.is_alive(): return self.note('Дождитесь завершения предыдущей проверки.')
        if self.printer.get() not in self.printer_names: return self.note('Выберите установленный принтер в настройках.')
        self.running=True; self.stop_event.clear(); self.save(); self.note('Автоматическая печать включена.')
        def loop():
            while not self.stop_event.is_set():
                self.pass_once()
                if self.stop_event.wait(300): break
        self.thread=threading.Thread(target=loop,daemon=True); self.thread.start()
    def stop(self):
        self.running=False; self.stop_event.set(); self.save(); self.note('Остановлено. Уже отправленные задания остаются в очереди Windows.')
    def pass_once(self):
        if not self.operation_lock.acquire(False): return
        self.busy=True
        try:
            self.worker.PRINTER=self.config.get('printer','')
            with contextlib.redirect_stdout(io.StringIO()), self.worker.agent_lock(): self.worker.run_once()
            result=json.loads((self.worker.DATA/'last-run.json').read_text(encoding='utf-8'))
            self.ui(lambda:self.note(f"Проверено. Отправлено: {result['submitted']}; ожидают данных: {result['waiting']}."))
        except SystemExit:
            self.ui(lambda:self.note('Есть ошибка или неопределённое задание. Проверьте историю; повторная печать заблокирована.'))
        except Exception:
            self.ui(lambda:self.note('Проверка не выполнена. Проверьте подключение, доступ устройства и принтер.'))
        finally:
            self.busy=False; self.operation_lock.release(); self.ui(self.render)
    def reprint(self,item):
        if self.busy: return self.note('Дождитесь завершения текущего действия.')
        self.worker.PRINTER=self.printer.get()
        try: actual_printer=self.worker.select_printer(item)
        except PrinterRoutingError as e: return self.note(str(e))
        if actual_printer not in self.printer_names: return self.note('Для артикула назначен принтер, который не установлен в Windows.')
        repeat=item['confirmed'] or str(item['id']) in read_json(self.worker.DATA/'state.json',{}).get('uncertain',{})
        prompt=f"{'Повторно отправить' if repeat else 'Отправить'} этикетку заказа {order_title(item)}?\n\nПринтер: {actual_printer}\nКоличество: 1 экземпляр."
        if repeat: prompt+='\nПроверьте, нужен ли дополнительный экземпляр.'
        if not messagebox.askyesno('Печать этикетки',prompt,parent=self.root): return
        if not self.operation_lock.acquire(False): return
        self.busy=True; self.board.set_enabled(False); self.note(f"Готовим этикетку заказа {order_title(item)}…")
        def work():
            try:
                self.manual_print(item['id'],actual_printer)
                self.ui(lambda:self.note(f"Этикетка заказа {order_title(item)} отправлена: 1 экземпляр. Проверьте отпечаток."))
            except Exception: self.ui(lambda:self.note('Печать не подтверждена. Проверьте очередь Windows и журнал. Автоматического повтора не будет.'))
            finally:
                self.busy=False; self.operation_lock.release()
                self.ui(lambda:(self.board.set_enabled(True),self.render()))
        self.background(work)
    def manual_print(self,item_id,expected_printer=None):
        from print_actions import manual_print
        manual_print(self.worker,item_id,expected_printer)
    def autostart(self):
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                if self.startup.get():
                    command='"'+sys.executable+'"'
                    if not getattr(sys,'frozen',False): command+=' "'+str(Path(__file__).resolve())+'"'
                    winreg.SetValueEx(key,'SnowbrickPrinter',0,winreg.REG_SZ,command)
                else:
                    try: winreg.DeleteValue(key,'SnowbrickPrinter')
                    except FileNotFoundError: pass
            self.save()
        except OSError: self.note('Не удалось изменить автозапуск Windows.')
    def close(self):
        if self.busy: return messagebox.showinfo(TITLE,'Дождитесь завершения текущего задания.')
        if self.running and not messagebox.askyesno(TITLE,'Закрыть приложение и остановить проверку до следующего запуска?'): return
        self.stop_event.set(); self.root.destroy()

def self_test():
    assert protect(protect(b'test-only'),decrypt=True)==b'test-only'
    assert (BASE/'ops'/'print-image.ps1').is_file()
    assert Path(os.environ['SNOWBRICK_POPPLER']).is_file()
    worker=load_worker()
    from print_order import article_text,grouped_print_order
    assert article_text('Товар (A); Товар (B)')=='A; B'
    import zxingcpp, pypdf, reportlab, PIL
    root=tk.Tk(); root.withdraw()
    app=App(root,smoke=True); root.update_idletasks()
    assert app.board.winfo_exists()
    assert len(app.printer_panel.rows)==4
    app.printer_panel.set_printers(['Self-test printer'])
    assert all('Self-test printer' in row['combo']['values'] for row in app.printer_panel.rows)
    timestamp=int(datetime.now(MOSCOW).timestamp())
    samples=[{'id':90000000+n,'createdAt':timestamp,'composition':'(CHECK_SKU)','hasLabel':True} for n in range(8)]
    app.board.set_groups(order_groups(samples,timestamp,timestamp,{}))
    root.update_idletasks()
    assert len(app.board.hitboxes)==8
    assert len({round(value[0]) for value in app.board.hitboxes})==4
    app.catalog=samples; app.card_filter={'CHECK_SKU'}; app.render()
    assert len(app.board.hitboxes)==8
    app.card_filter={'NOT_SELECTED'}; app.render(); assert not app.board.hitboxes
    app.reset_article_filter(); assert len(app.board.hitboxes)==8
    app.settings(); root.update_idletasks()
    assert app.printers.winfo_exists() and app.log.winfo_exists()
    root.destroy()
    out=Path(sys.argv[sys.argv.index('--self-test')+1])
    out.write_text(json.dumps({'ok':True,'dpapi':True,'pdf':True,'barcode':True,'printerHelper':True,'windowControls':True,'printerRows':4,'articleFilter':True}),encoding='utf-8')

if __name__=='__main__':
    if '--self-test' in sys.argv: self_test()
    else:
        # One control window per Windows user; periodic worker also holds a lock.
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        kernel.CreateMutexW.restype=wintypes.HANDLE
        mutex=kernel.CreateMutexW(None,False,'Local\\SnowbrickPrinter')
        duplicate=ctypes.get_last_error()==183
        root=tk.Tk()
        if duplicate:
            root.withdraw(); messagebox.showinfo(TITLE,'Приложение уже запущено. Найдите его окно на панели задач.'); root.destroy()
        else:
            try: App(root); root.mainloop()
            except Exception: root.withdraw(); messagebox.showerror(TITLE,'Не удалось открыть приложение. Проверьте права доступа и переустановите его.'); root.destroy()
