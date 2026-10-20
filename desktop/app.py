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

TITLE = 'Снегострой — печать этикеток'
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
from orders_model import MOSCOW, read_json, order_groups, parse_period, merge_catalog, receipt_statuses, sku_set, order_title, sku_color, print_tab_groups, group_by_day, pending_by_article
from orders_view import OrdersBoard, DatePicker, BG, INK, MUTED
from printer_routing import load_routes, normalize_routes, choose_printer, PrinterRoutingError
from printer_panel import PrinterPanel
from rounded_controls import RoundedNotebook, RoundedArticleCards
from order_diagnostics import error_reasons
from auto_print import auto_print_enabled, set_auto_print
from pdf_archive import archive_directory, archive_labels
from orders_model import VISIBLE_FROM
from print_journal import read_entries

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
        self.smoke=smoke; self.archive_lock=threading.Lock(); self.closing=threading.Event()
        self.config = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}
        self.worker = load_worker()
        self.auto_print=tk.BooleanVar(value=auto_print_enabled(self.worker.DATA))
        self.printer=tk.StringVar(value=self.config.get('printer','4BARCODE 3B-T361U')); self.printer_names=[]
        routing_error=None
        try: self.routes=load_routes(self.worker.DATA)
        except PrinterRoutingError as e:
            self.routes={'enabled':True,'routes':[]}; routing_error=str(e)
        self.card_filter=None; self.carrier=tk.StringVar(value='Все доставки'); self.search_query=''
        self.selection_mode=False; self.selected_ids=set(); self.visible_cards=[]; self.article_pending={}
        self.article_catalog=set(read_json(self.worker.DATA/'article-catalog.json',[]))
        self.catalog=[item for item in read_json(self.worker.DATA/'order-catalog.json',[]) if item.get('createdAt',0)>=VISIBLE_FROM]
        self.worker.POPPLER = Path(os.environ['SNOWBRICK_POPPLER'])
        self.token = os.environ.get('PRINT_AGENT_TOKEN') or device_token(); os.environ['PRINT_AGENT_TOKEN'] = self.token
        root.title(TITLE); root.geometry('1440x1000'); root.minsize(1120,850); root.configure(bg=BG)
        style=ttk.Style(); style.theme_use('clam'); style.configure('.',font=('Segoe UI',10))
        style.configure('TButton',padding=(12,8),background='#ffffff',foreground=INK,borderwidth=0)
        style.map('TButton',background=[('active','#e8edf8')])
        style.configure('Accent.TButton',background='#142346',foreground='white')
        style.map('Accent.TButton',background=[('active','#294576')])
        style.configure('TNotebook',background=BG,borderwidth=0)
        style.configure('TNotebook.Tab',padding=(22,12),font=('Segoe UI',12,'bold'))
        style.map('TNotebook.Tab',background=[('selected','#142346')],foreground=[('selected','white')])
        style.configure('TFrame',background=BG); style.configure('TLabel',background=BG,foreground=INK)
        frame=ttk.Frame(root,padding=(28,20,28,12)); frame.pack(fill='x')
        title=ttk.Frame(frame); title.pack(fill='x')
        ttk.Label(title,text='Заказы',font=('Segoe UI',30,'bold')).pack(side='left')
        ttk.Button(title,text='Настройки',command=self.settings).pack(side='right')
        ttk.Checkbutton(title,text='Автоматическая печать',variable=self.auto_print,command=self.toggle_auto_print).pack(side='right',padx=16)
        ttk.Label(title,text='СНЕГОСТРОЙ',foreground=MUTED,font=('Segoe UI',11,'bold')).pack(side='right',padx=24)
        self.connection=tk.StringVar(value='Соединение с amoCRM: ещё не проверено')
        self.connection_label=ttk.Label(title,textvariable=self.connection,foreground=MUTED,font=('Segoe UI',9),wraplength=350)
        self.connection_label.pack(side='left',padx=24)
        self.archive_status=tk.StringVar(value='PDF: постоянный архив на рабочем столе → Этикетки доставка')
        self.browse_actions=ttk.Frame(frame); self.browse_actions.pack(fill='x',pady=(0,10))
        self.select_button=ttk.Button(self.browse_actions,text='Выбрать несколько',command=self.toggle_selection)
        self.select_button.pack(side='left')
        ttk.Label(self.browse_actions,text='Доставка').pack(side='left',padx=(12,8))
        self.delivery_buttons={}
        for value,label in [('Яндекс','Яндекс'),('СДЭК','СДЭК'),('Все доставки','Все заявки')]:
            button=ttk.Button(self.browse_actions,text=label,command=lambda v=value:self.carrier.set(v))
            button.pack(side='left',padx=(0,6)); self.delivery_buttons[value]=button
        self.carrier.trace_add('write',lambda *_:self.render(True))
        self.all_time=tk.BooleanVar(value=True)
        ttk.Checkbutton(self.browse_actions,text='С 1 октября',variable=self.all_time,command=lambda:self.reload(True)).pack(side='left',padx=16)
        self.batch_controls=ttk.Frame(frame)
        ttk.Button(self.batch_controls,text='Выбрать все в списке',command=self.select_all_visible).pack(side='left')
        ttk.Button(self.batch_controls,text='Снять выделение',command=self.clear_selection).pack(side='left',padx=8)
        self.batch_button=ttk.Button(self.batch_controls,text='Печать выбранных (0)',style='Accent.TButton',command=self.print_selected)
        self.batch_button.pack(side='left')
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
        ttk.Button(filters,text='Показать период',style='Accent.TButton',command=self.show_period).pack(side='left')
        ttk.Button(filters,text='Сегодня',command=self.today).pack(side='left',padx=6)
        ttk.Button(filters,text='Последние 2 часа',command=self.last_two_hours).pack(side='left')
        search_row=ttk.Frame(frame); search_row.pack(fill='x',pady=(8,0))
        ttk.Label(search_row,text='Номер заявки').pack(side='left',padx=(0,8))
        self.search_text=tk.StringVar()
        self.search_entry=ttk.Entry(search_row,textvariable=self.search_text,width=25)
        self.search_entry.pack(side='left'); self.search_entry.bind('<Return>',lambda _:self.search_orders())
        ttk.Button(search_row,text='Поиск',command=self.search_orders).pack(side='left',padx=6)
        ttk.Button(search_row,text='Сбросить',command=self.clear_search).pack(side='left')
        article_heading=ttk.Frame(frame); article_heading.pack(fill='x',pady=(10,0))
        ttk.Label(article_heading,text='Карточки по артикулу · не напечатано').pack(side='left')
        ttk.Button(article_heading,text='Обновить артикулы',command=self.refresh_articles).pack(side='right')
        self.article_filters=RoundedArticleCards(frame)
        self.article_filters.pack(fill='x',pady=(4,0))
        self.printer_panel=None
        summary=ttk.Frame(frame); summary.pack(fill='x',pady=(16,0))
        self.counts=tk.StringVar(value='Загружаем заказы…')
        ttk.Label(summary,textvariable=self.counts,font=('Segoe UI',11,'bold')).pack(side='left')
        ttk.Label(summary,text='✓ Отправлено     ! Нет подтверждения',foreground=MUTED).pack(side='right')
        self.tabs=RoundedNotebook(root); self.tabs.pack(fill='both',expand=True,padx=28)
        self.boards=[]
        for label in ['Все заявки','✓ Напечатанные','! Ошибки / не напечатаны']:
            page=ttk.Frame(self.tabs); self.tabs.add(page,text=label)
            board=OrdersBoard(page,self.reprint,self.toggle_card,self.show_error); board.pack(fill='both',expand=True)
            self.boards.append(board)
        self.board=self.boards[0]
        self.tabs.bind('<<NotebookTabChanged>>',self.tab_changed,add='+')
        footer=ttk.Frame(root,padding=(28,10)); footer.pack(side='bottom',fill='x',before=frame)
        self.status=tk.StringVar(value='Выберите принтер в настройках. Проверка заявок каждые 5 минут.')
        ttk.Label(footer,textvariable=self.status,foreground=MUTED).pack(side='left')
        ttk.Button(footer,text='Проверить связь и обновить',command=lambda:self.reload()).pack(side='right')
        self.startup=tk.BooleanVar(value=self.config.get('startup',False))
        self.settings_log=[]
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.pump(); self.render()
        if routing_error: self.note(routing_error)
        if not smoke:
            self.background(self.refresh_printers); self.reload(); root.after(300000,self.periodic_view)
            if not self.article_catalog: root.after(600,lambda:self.refresh_articles(True))

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
        return sorted(self.article_catalog|{sku for item in self.catalog for sku in sku_set(item)})
    def refresh_articles(self,automatic=False):
        if not self.operation_lock.acquire(False):
            if automatic: self.root.after(1000,lambda:self.refresh_articles(True))
            else: self.note('Дождитесь завершения текущего действия.')
            return
        self.busy=True; self.note('Загружаем список артикулов из заявок amoCRM…')
        def work():
            try:
                items=json.loads(self.worker.request('leads?from=0'))['items']
                skus=sorted({sku for item in items for sku in sku_set(item)})
                self.worker.atomic_json(self.worker.DATA/'article-catalog.json',skus)
                def loaded():
                    self.article_catalog=set(skus); self.render()
                    self.note(f'Список amoCRM обновлён: {len(skus)} артикулов. Заказы не отправлялись на печать.')
                self.ui(loaded)
            except Exception: self.ui(lambda:self.note('Не удалось загрузить полный список артикулов. Сохранённый список доступен; повторите обновление позже.'))
            finally: self.busy=False; self.operation_lock.release()
        self.background(work)
    def toggle_selection(self):
        self.selection_mode=not self.selection_mode
        if self.selection_mode:
            self.batch_controls.pack(fill='x',pady=(0,10),after=self.browse_actions)
        else: self.batch_controls.pack_forget(); self.selected_ids.clear()
        self.select_button.configure(text='Завершить выбор' if self.selection_mode else 'Выбрать несколько')
        self.render()
    def toggle_card(self,item):
        key=str(item['id'])
        if key in self.selected_ids: self.selected_ids.remove(key)
        else: self.selected_ids.add(key)
        self.render()
    def select_all_visible(self):
        self.selected_ids={str(v['id']) for v in self.visible_cards if v['canPrint']}; self.render()
    def clear_selection(self): self.selected_ids.clear(); self.render()
    def toggle_article_filter(self,sku):
        selected=set(self.card_filter or ())
        if sku in selected: selected.remove(sku)
        else: selected.add(sku)
        self.card_filter=selected
        self.render(True)
    def reset_article_filter(self):
        self.card_filter=None; self.render(True)
    def refresh_article_buttons(self):
        from orders_model import delivery_service
        source=self.search_catalog()
        carrier={'СДЭК':'cdek','Яндекс':'yandex'}.get(self.carrier.get())
        if carrier:
            start,end=self.period()
            source=[item for item in source if delivery_service(item)==carrier and start<=item.get('createdAt',0)<=end]
        values={sku for item in source for sku in sku_set(item)}
        choices=[((), 'Все артикулы', self.card_filter is None, True, ('#ffffff',INK), self.reset_article_filter)]
        unknown=any(not sku_set(item) for item in source)
        for sku in sorted(values)+([None] if unknown or self.card_filter and None in self.card_filter else []):
            label=(sku or 'Без артикула')+' · '+str(len(self.article_pending.get(sku,[])))
            choices.append((sku,label,self.card_filter is not None and sku in self.card_filter,
                            True,sku_color((sku,)) if sku else sku_color(()),lambda s=sku:self.toggle_article_filter(s)))
        self.article_filters.set_choices(choices)
        self.article_filters.set_actions({sku:(bool(self.article_pending.get(sku)) and not self.busy,lambda s=sku:self.print_article(s)) for sku in values})
    def tab_changed(self,_=None):
        self.board=self.boards[self.tabs.index('current')]
        self.render(True)
    def store_routes(self,config,automatic=False):
        if self.busy:
            if not automatic: self.note('Дождитесь завершения текущего действия.')
            return False
        try:
            config=normalize_routes(config)
            with self.worker.agent_lock(): self.worker.atomic_json(self.worker.DATA/'printer-routes.json',config)
            self.routes=config; self.render()
            if not automatic: self.note('Назначения сохранены. Артикулы закреплены за выбранными принтерами.')
            return True
        except PrinterRoutingError as e:
            if not automatic: self.note(str(e))
        except OSError:
            if not automatic: self.note('Сейчас выполняется печать. Дождитесь завершения и сохраните назначение ещё раз.')
        return False
    def period(self):
        if self.all_time.get(): return VISIBLE_FROM, 253402289999
        start,end=parse_period(self.day_from.get(),self.time_from.get(),self.day_to.get(),self.time_to.get())
        return max(start,VISIBLE_FROM),end
    def show_period(self):
        self.all_time.set(False); self.reload(True)
    def search_catalog(self):
        if not self.search_query: return self.catalog
        return [item for item in self.catalog if self.search_query in str(item.get('orderNumber') or '') or self.search_query in str(item['id'])]
    def search_orders(self):
        raw=self.search_text.get().strip()
        digits=''.join(char for char in raw if char in '0123456789')
        if raw and not digits: return self.note('Введите номер заявки или его последние цифры.')
        self.search_query=digits; self.card_filter=None; self.all_time.set(True)
        self.carrier.set('Все доставки'); self.tabs.select(0); self.render(True)
        self.note('Найдено заявок: '+str(len(self.visible_cards)))
    def clear_search(self):
        self.search_text.set(''); self.search_query=''; self.render(True)
    def render(self,reset=False):
        try: start,end=self.period()
        except ValueError as e: return self.note(str(e))
        state=read_json(self.worker.DATA/'state.json',{})
        catalog=self.search_catalog()
        carrier={'СДЭК':'cdek','Яндекс':'yandex','Не указана':'unknown'}.get(self.carrier.get())
        from orders_model import delivery_service
        delivery_counts={'cdek':0,'yandex':0,'all':0}
        for item in catalog:
            if start<=item.get('createdAt',0)<=end:
                delivery_counts['all']+=1
                service=delivery_service(item)
                if service in delivery_counts: delivery_counts[service]+=1
        for value,label,key in [('Яндекс','Яндекс','yandex'),('СДЭК','СДЭК','cdek'),('Все доставки','Все заявки','all')]:
            self.delivery_buttons[value].configure(text=f'{label} · {delivery_counts[key]}',style='Accent.TButton' if value==self.carrier.get() else 'TButton')
        receipts=receipt_statuses(self.worker.DATA)
        self.article_pending=pending_by_article(order_groups(catalog,start,end,state,receipts,carrier=carrier))
        all_groups=group_by_day(order_groups(catalog,start,end,state,receipts,self.card_filter,carrier=carrier))
        grouped_tabs=[all_groups,print_tab_groups(all_groups,True),print_tab_groups(all_groups,False)]
        totals=[sum(len(g['items']) for g in groups) for groups in grouped_tabs]
        self.tabs.tab(0,text=f'Все заявки · {totals[0]}')
        self.tabs.tab(1,text=f'✓ Напечатанные · {totals[1]}')
        self.tabs.tab(2,text=f'! Ошибки / не напечатаны · {totals[2]}')
        active=self.tabs.index('current'); self.board=self.boards[active]; groups=grouped_tabs[active]
        cards=[item for group in groups for item in group['items']]
        self.visible_cards=cards
        self.selected_ids.intersection_update(str(v['id']) for v in cards if v['canPrint'])
        self.batch_button.configure(text=f'Печать выбранных ({len(self.selected_ids)})',state='normal' if self.selected_ids and not self.busy else 'disabled')
        confirmed=sum(v['confirmed'] for v in cards)
        days=len({g['day'] for g in groups})
        self.counts.set(f'Заказов: {len(cards)}   ·   Дней: {days}   ·   Отправлено: {confirmed}   ·   Без подтверждения: {len(cards)-confirmed}')
        self.refresh_article_buttons()
        if self.printer_panel: self.printer_panel.refresh_articles()
        for index,board in enumerate(self.boards):
            board.selection_mode=self.selection_mode; board.selected=set(self.selected_ids); board.enabled=not self.busy
            board.set_groups(grouped_tabs[index],reset_scroll=reset,empty='Нет заказов для этой вкладки и выбранных фильтров. Измените период, доставку или артикулы.')
        if self.settings_window and self.settings_window.winfo_exists(): self.refresh_journal()
    def today(self):
        self.all_time.set(False)
        value=datetime.now(MOSCOW).strftime('%d.%m.%Y')
        self.day_from.set(value); self.day_to.set(value); self.time_from.set('00:00'); self.time_to.set('23:59'); self.reload(True)
    def last_two_hours(self):
        self.all_time.set(False)
        end=datetime.now(MOSCOW); start=end-timedelta(hours=2)
        self.day_from.set(start.strftime('%d.%m.%Y')); self.day_to.set(end.strftime('%d.%m.%Y'))
        self.time_from.set(start.strftime('%H:%M')); self.time_to.set(end.strftime('%H:%M')); self.reload(True)
    def reload(self,reset=False):
        try: start,end=self.period()
        except ValueError as e: return self.note(str(e))
        if not self.operation_lock.acquire(False): return self.note('Дождитесь завершения текущего действия.')
        self.busy=True; self.board.set_enabled(False); self.note('Получаем заказы из amoCRM…')
        self.connection.set('Соединение с amoCRM: проверяем…')
        self.connection_label.configure(foreground=MUTED)
        def work():
            try:
                # Полный каталог только для просмотра; автоочередь и история печати отдельно.
                incoming=json.loads(self.worker.request(f'leads?from={VISIBLE_FROM}'))['items']
                catalog=merge_catalog([],[item for item in incoming if item.get('createdAt',0)>=VISIBLE_FROM])
                self.worker.atomic_json(self.worker.DATA/'order-catalog.json',catalog)
                def loaded():
                    self.catalog=catalog; self.render(reset)
                    self.connection.set('Есть соединение с amoCRM · Обновлено '+datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M:%S')+' МСК')
                    self.connection_label.configure(foreground='#008a44')
                    self.note('Заказы обновлены. Зелёная отметка — подтверждение отправки драйверу.')
                    if not self.smoke: self.start_archive(catalog)
                self.ui(loaded)
            except Exception:
                def failed():
                    self.connection.set('Нет соединения с amoCRM · Не удалось обновить карточки')
                    self.connection_label.configure(foreground='#c5203e')
                    self.note('Показана сохранённая история. Для повторной проверки нажмите «Проверить связь и обновить».')
                self.ui(failed)
            finally:
                self.busy=False; self.operation_lock.release(); self.ui(lambda:self.board.set_enabled(True))
        self.background(work)
    def open_archive(self):
        try:
            folder=archive_directory(); folder.mkdir(parents=True,exist_ok=True); os.startfile(folder)
        except OSError: self.note('Не удалось открыть архив PDF на рабочем столе.')
    def start_archive(self,catalog):
        if not self.archive_lock.acquire(False): return
        self.archive_status.set('PDF: сохраняем этикетки в архив на рабочем столе…')
        def progress(result):
            text=f"PDF: сохранено новых {result['saved']}, уже в архиве {result['existing']}, без доступного PDF {result['waiting']}"
            if result['errors']: text+=f" · Ошибок скачивания: {result['errors']}; повтор при следующем обновлении"
            self.ui(lambda:self.archive_status.set(text))
        def work():
            try: archive_labels(archive_directory(),catalog,self.worker.request,self.closing.is_set,progress)
            except Exception:
                self.ui(lambda:self.archive_status.set('PDF: не удалось сохранить архив. Проверьте доступ к рабочему столу и свободное место.'))
            finally: self.archive_lock.release()
        self.background(work)
    def periodic_view(self):
        if not self.busy: self.reload()
        self.root.after(300000,self.periodic_view)
    def settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.refresh_journal(); self.settings_window.deiconify(); return self.settings_window.lift()
        window=tk.Toplevel(self.root); self.settings_window=window; window.title('Настройки печати'); window.geometry('1120x700'); window.minsize(1000,650); window.transient(self.root)
        window.protocol('WM_DELETE_WINDOW',window.withdraw)
        container=ttk.Frame(window,padding=24); container.pack(fill='both',expand=True)
        ttk.Label(container,text='Настройки печати',font=('Segoe UI',20,'bold')).pack(anchor='w',pady=(0,16))
        self.settings_tabs=ttk.Notebook(container); self.settings_tabs.pack(fill='both',expand=True)
        routes_page=ttk.Frame(self.settings_tabs,padding=16)
        frame=ttk.Frame(self.settings_tabs,padding=16)
        self.settings_tabs.add(routes_page,text='Принтеры и артикулы')
        self.settings_tabs.add(frame,text='Общие настройки')
        archive_page=ttk.Frame(self.settings_tabs,padding=16)
        self.settings_tabs.add(archive_page,text='Архив PDF')
        ttk.Label(archive_page,text='Заявки с 01.10.2026 · по дням поступления · московское время',font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(0,20))
        ttk.Label(archive_page,textvariable=self.archive_status,wraplength=850).pack(anchor='w',pady=(0,16))
        ttk.Label(archive_page,text='Рабочий стол → Этикетки доставка → СДЭК / Яндекс\nPDF сохраняются постоянно, независимо от автопечати.\nПри печати сначала используется местный PDF, при его отсутствии — загрузка из amoCRM.',wraplength=850).pack(anchor='w',pady=(0,20))
        ttk.Button(archive_page,text='Открыть папку PDF',command=self.open_archive).pack(anchor='w')
        journal_page=ttk.Frame(self.settings_tabs,padding=16)
        self.settings_tabs.add(journal_page,text='Журнал печати')
        journal_top=ttk.Frame(journal_page); journal_top.pack(fill='x',pady=(0,10))
        self.journal_summary=tk.StringVar()
        ttk.Label(journal_top,textvariable=self.journal_summary,font=('Segoe UI',11,'bold')).pack(side='left')
        ttk.Button(journal_top,text='Обновить журнал',command=self.refresh_journal).pack(side='right')
        ttk.Label(journal_page,text='Время МСК. Успех — передача драйверу; фактический отпечаток проверяется у принтера. Записи сохраняются после закрытия.',foreground=MUTED).pack(anchor='w',pady=(0,10))
        journal_body=ttk.Frame(journal_page); journal_body.pack(fill='both',expand=True)
        columns=('time','order','skus','printer','mode','status')
        self.journal_tree=ttk.Treeview(journal_body,columns=columns,show='tree headings',selectmode='browse')
        self.journal_tree.heading('#0',text='День / всего'); self.journal_tree.column('#0',width=190)
        for key,label,width in [('time','Время',70),('order','Заявка',125),('skus','Артикулы',180),('printer','Принтер',170),('mode','Печать',90),('status','Результат',130)]:
            self.journal_tree.heading(key,text=label); self.journal_tree.column(key,width=width,minwidth=60)
        journal_scroll=ttk.Scrollbar(journal_body,orient='vertical',command=self.journal_tree.yview)
        self.journal_tree.configure(yscrollcommand=journal_scroll.set)
        journal_scroll.pack(side='right',fill='y'); self.journal_tree.pack(fill='both',expand=True)
        self.journal_tree.tag_configure('success',foreground='#128348'); self.journal_tree.tag_configure('uncertain',foreground='#c5203e')
        self.settings_tabs.bind('<<NotebookTabChanged>>',lambda _:self.refresh_journal())
        self.refresh_journal()
        self.printer_panel=PrinterPanel(routes_page,self.routes,self.known_skus,self.store_routes,self.note)
        self.printer_panel.pack(fill='x')
        self.printer_panel.set_printers(self.printer_names)
        ttk.Label(routes_page,text='Назначения применяются к автоматической и ручной печати.\nОдин артикул может быть закреплён только за одним принтером.',foreground=MUTED).pack(anchor='w',pady=16)
        ttk.Button(routes_page,text='Обновить принтеры Windows',command=lambda:self.background(self.refresh_printers)).pack(anchor='w')
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
    def refresh_journal(self):
        if not hasattr(self,'journal_tree'): return
        try: entries=read_entries(self.worker.DATA)
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            self.journal_summary.set('Не удалось прочитать журнал печати.'); return
        self.journal_tree.delete(*self.journal_tree.get_children())
        catalog={str(item['id']):item for item in self.catalog}; days={}
        for entry in entries:
            day=datetime.fromtimestamp(entry.get('at',0),MOSCOW).strftime('%Y-%m-%d')
            days.setdefault(day,[]).append(entry)
        count=sum(entry.get('status')=='submitted' for entry in entries)
        self.journal_summary.set(f'Отправлено этикеток: {count} · Дней: {len(days)}')
        for index,(day,values) in enumerate(sorted(days.items(),reverse=True)):
            total=sum(entry.get('status')=='submitted' for entry in values)
            parent=self.journal_tree.insert('', 'end',text=f'{datetime.strptime(day,"%Y-%m-%d"):%d.%m.%Y} · {total} шт.',open=index==0)
            for entry in values:
                item=catalog.get(str(entry['id']),{})
                number=entry.get('orderNumber') or item.get('orderNumber')
                order=('№ '+str(number)) if number else 'amo '+str(entry['id'])
                skus=entry.get('skus') or sku_set(item)
                success=entry.get('status')=='submitted'
                self.journal_tree.insert(parent,'end',values=(datetime.fromtimestamp(entry.get('at',0),MOSCOW).strftime('%H:%M:%S'),order,'; '.join(skus),entry.get('printer') or 'Не записан','Ручная' if entry.get('mode')=='manual' else 'Авто','Передано драйверу' if success else 'Нет подтверждения'),tags=('success' if success else 'uncertain',))
    def save(self):
        self.config.update(printer=self.printer.get(),startup=self.startup.get(),enabled=self.running)
        temp=CONFIG.with_suffix('.tmp'); temp.write_text(json.dumps(self.config,ensure_ascii=False),encoding='utf-8'); os.replace(temp,CONFIG)
    def refresh_printers(self):
        try:
            data=json.loads(powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8; @(Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name) | ConvertTo-Json -Compress"))
            names=data if isinstance(data,list) else [data]
            def loaded():
                self.printer_names=names
                if self.printer_panel: self.printer_panel.set_printers(names)
                if self.settings_window and self.settings_window.winfo_exists(): self.printers.configure(values=names)
                if self.auto_print.get(): self.start()
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
        if self.thread and self.thread.is_alive():
            self.auto_print.set(auto_print_enabled(self.worker.DATA)); return self.note('Дождитесь завершения предыдущей проверки.')
        if self.printer.get() not in self.printer_names:
            self.stop(); return self.note('Выберите установленный принтер в настройках.')
        try: set_auto_print(self.worker.DATA,True)
        except OSError:
            self.auto_print.set(auto_print_enabled(self.worker.DATA)); return self.note('Не удалось сохранить включение автоматической печати.')
        self.running=True; self.auto_print.set(True); self.stop_event.clear(); self.save(); self.note('Автоматическая печать включена. Проверка новых заявок каждые 5 минут.')
        if '--panel-only' in sys.argv: return
        def loop():
            while not self.stop_event.is_set():
                self.pass_once()
                if self.stop_event.wait(300): break
        self.thread=threading.Thread(target=loop,daemon=True); self.thread.start()
    def stop(self):
        try: set_auto_print(self.worker.DATA,False)
        except OSError:
            self.auto_print.set(auto_print_enabled(self.worker.DATA)); return self.note('Не удалось сохранить отключение автоматической печати. Повторите действие.')
        self.running=False; self.auto_print.set(False); self.stop_event.set(); self.save(); self.note('Автоматическая печать выключена. Уже отправленные задания остаются в очереди Windows.')
    def toggle_auto_print(self):
        if self.auto_print.get(): self.start()
        else: self.stop()
    def pass_once(self):
        if not self.operation_lock.acquire(False): return
        self.busy=True
        try:
            self.worker.PRINTER=self.config.get('printer','')
            with contextlib.redirect_stdout(io.StringIO()), self.worker.agent_lock(): result=self.worker.run_once()
            if result.get('paused'):
                self.ui(lambda:self.note('Автоматическая печать выключена.'))
            else:
                self.ui(lambda:self.note(f"Проверено. Отправлено: {result['submitted']}; ожидают данных: {result['waiting']}."))
        except SystemExit:
            self.ui(lambda:self.note('Есть ошибка или неопределённое задание. Проверьте историю; повторная печать заблокирована.'))
        except Exception:
            self.ui(lambda:self.note('Проверка не выполнена. Проверьте подключение, доступ устройства и принтер.'))
        finally:
            self.busy=False; self.operation_lock.release(); self.ui(self.render)
    def reprint(self,item):
        if self.busy: return self.note('Дождитесь завершения текущего действия.')
        if self.printer_panel and self.printer_panel.dirty and not self.printer_panel.save(): return
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
    def show_error(self,item):
        try:
            state=read_json(self.worker.DATA/'state.json',{})
            last_run=read_json(self.worker.DATA/'last-run.json',{})
            routing=load_routes(self.worker.DATA)
            reasons=error_reasons(item,state,routing,self.printer.get(),last_run,
                                  receipt_statuses(self.worker.DATA),self.printer_names or None,
                                  self.connection.get().startswith('Нет соединения'))
        except (OSError,ValueError,TypeError,AttributeError,KeyError):
            reasons=['Не удалось прочитать локальные сведения о печати или назначения принтеров. Откройте настройки и проверьте сохранённые назначения.']
        text='По данным последнего обновления карточки:\n\n'+'\n\n'.join('• '+reason for reason in reasons)
        messagebox.showinfo('Причина / состояние — '+order_title(item),text,parent=self.root)
    def manual_print(self,item_id,expected_printer=None):
        from print_actions import manual_print
        manual_print(self.worker,item_id,expected_printer)
    def print_selected(self):
        items=[v for v in self.visible_cards if str(v['id']) in self.selected_ids]
        self.print_items(items)
    def print_article(self,sku):
        if self.busy: return self.note('Дождитесь завершения текущего действия.')
        self.render()
        items=self.article_pending.get(sku,[])
        ready=[item for item in items if item['canPrint']]
        if not ready:
            return messagebox.showinfo('Печать артикула','Готовых этикеток нет. Проверьте кнопку «Причина» на красных карточках.',parent=self.root)
        self.print_items(ready,f'Артикул: {sku}',len(items)-len(ready))
    def print_items(self,items,context='',skipped=0):
        if self.busy: return self.note('Дождитесь завершения текущего действия.')
        if self.printer_panel and self.printer_panel.dirty and not self.printer_panel.save(): return
        if not items: return
        self.worker.PRINTER=self.printer.get()
        try:
            printers={str(item['id']):self.worker.select_printer(item) for item in items}
            if any(name not in self.printer_names for name in printers.values()):
                return self.note('Один из назначенных принтеров не установлен в Windows.')
        except PrinterRoutingError as e: return self.note(str(e))
        by_printer={name:sum(v==name for v in printers.values()) for name in set(printers.values())}
        prompt=f'Напечатать выбранные этикетки: {len(items)} шт.?\nПо одному экземпляру каждой заявки.\n\n'+'\n'.join(f'{name}: {count}' for name,count in sorted(by_printer.items()))
        if any(v['confirmed'] for v in items): prompt+='\n\nСреди выбранных есть уже отправленные этикетки: будет дополнительный экземпляр.'
        if context: prompt=context+'\n\n'+prompt
        if skipped: prompt+=f'\n\nБез готовой этикетки: {skipped}. Эти заявки останутся в счётчике и не будут напечатаны.'
        state=read_json(self.worker.DATA/'state.json',{})
        if any(str(v['id']) in state.get('uncertain',{}) or state.get('printed',{}).get(str(v['id']),{}).get('status')=='reserved-on-server' for v in items):
            prompt+='\n\nЕсть заявки с неопределённой или зарезервированной печатью. Сначала проверьте физические отпечатки и очереди других устройств: возможен дополнительный экземпляр.'
        if not messagebox.askyesno('Печать выбранных этикеток',prompt,parent=self.root): return
        if not self.operation_lock.acquire(False): return
        self.busy=True; self.board.set_enabled(False); self.render()
        def submitted(key):
            def update():
                self.selected_ids.discard(key); self.render()
            self.ui(update)
        def work():
            try:
                from print_actions import manual_batch
                result=manual_batch(self.worker,items,printers,submitted)
                def completed():
                    text=f"Отправлено этикеток: {len(result['submitted'])}."
                    if result['failed']: text+=' Партия остановлена из-за ошибки. Проверьте статус и очередь; автоматического повтора нет.'
                    self.note(text)
                self.ui(completed)
            except Exception: self.ui(lambda:self.note('Не удалось завершить партию. Проверьте статусы карточек и очередь принтера.'))
            finally:
                self.busy=False; self.operation_lock.release(); self.ui(lambda:(self.board.set_enabled(True),self.render()))
        self.background(work)
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
        if self.printer_panel and self.printer_panel.dirty and not self.printer_panel.save(): return messagebox.showinfo(TITLE,'Дождитесь сохранения выбранных принтеров и артикулов.')
        if self.running and not messagebox.askyesno(TITLE,'Закрыть приложение и остановить проверку до следующего запуска?'): return
        if self.running:
            self.stop()
            if self.running: return
        self.closing.set(); self.stop_event.set(); self.root.destroy()

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
    assert app.printer_panel is None
    app.settings(); app.settings_window.withdraw(); root.update_idletasks()
    assert app.printer_panel.winfo_toplevel()==app.settings_window
    assert len(app.printer_panel.rows)==4
    app.printer_panel.set_printers(['Self-test printer'])
    assert all('Self-test printer' in row['combo']['values'] for row in app.printer_panel.rows)
    timestamp=int(datetime.now(MOSCOW).timestamp())
    samples=[{'id':90000000+n,'createdAt':timestamp,'composition':f'(CHECK_{n//3})','hasLabel':True,'deliveryService':'cdek' if n%2==0 else 'yandex'} for n in range(8)]
    grid_probe=[{**samples[0],'id':91000000+n} for n in range(13)]
    grid_probe[0]['orderNumber']='00001234'
    app.board.set_groups(order_groups(grid_probe,timestamp,timestamp,{})); root.update_idletasks()
    assert len({round(value[0]) for value in app.board.hitboxes})==12
    assert len({round(value[1]) for value in app.board.hitboxes})==2
    assert '1234' in [app.board.canvas.itemcget(tag,'text') for tag in app.board.canvas.find_withtag('order-suffix')]
    app.board.set_groups(order_groups(samples,timestamp,timestamp,{}))
    root.update_idletasks()
    assert len(app.board.hitboxes)==8
    assert len({round(value[0]) for value in app.board.hitboxes})==8
    assert len({round(value[1]) for value in app.board.hitboxes})==1
    app.catalog=samples; app.tabs.select(2); root.update(); app.render()
    assert len(app.boards[1].groups)==0 and len(app.board.hitboxes)==8
    app.article_filters.buttons['CHECK_0'].invoke()
    assert len(app.board.hitboxes)==3
    root.update_idletasks()
    assert all(box[2]<=app.article_filters.canvas.winfo_width()+1 for box in app.article_filters.boxes)
    assert len(app.article_filters.print_boxes)==3
    assert app.tabs.boxes[2][1]<app.tabs.boxes[0][1]
    assert app.article_filters.printer_colors['CHECK_0']=='#dc2844'
    app.card_filter={'NOT_SELECTED'}; app.render(); assert not app.board.hitboxes
    app.reset_article_filter(); assert len(app.board.hitboxes)==8
    app.carrier.set('Яндекс'); assert len(app.board.hitboxes)==4 and len(app.article_pending['CHECK_0'])==1
    assert str(app.delivery_buttons['Яндекс'].cget('text')).endswith('4')
    app.carrier.set('СДЭК'); assert len(app.board.hitboxes)==4 and len(app.article_pending['CHECK_0'])==2
    app.carrier.set('Все доставки'); assert len(app.board.hitboxes)==8
    app.search_text.set('0003'); app.search_orders()
    assert len(app.visible_cards)==1 and app.visible_cards[0]['id']==90000003
    app.clear_search(); assert len(app.visible_cards)==8
    app.toggle_selection(); app.select_all_visible()
    assert len(app.selected_ids)==8 and len(app.board.selection_boxes)==8
    app.clear_selection(); assert not app.selected_ids
    app.toggle_selection()
    app.catalog=samples+[{'id':90000099,'createdAt':timestamp-86400,'composition':'(CHECK_0)','hasLabel':False}]
    app.tabs.select(0); root.update(); app.render()
    assert app.all_time.get() and len(app.visible_cards)==9
    assert len(app.board.canvas.find_withtag('day-heading'))==2
    assert len(app.board.hitboxes)==8
    assert len({round(value[1]) for value in app.board.hitboxes[:4]})==1
    app.all_time.set(False); app.render(); assert len(app.visible_cards)==8
    app.all_time.set(True)
    # Реальные переходы ошибки/повторного чтения с mock API, без печати и сети.
    app.background=lambda callback:callback()
    original_request=app.worker.request
    def offline_request(*_): raise OSError('offline test')
    app.worker.request=offline_request
    app.reload()
    while not app.actions.empty(): app.actions.get_nowait()()
    assert app.connection.get().startswith('Нет соединения') and len(app.catalog)==9
    requests=[]
    def online_request(path):
        requests.append(path); return json.dumps({'items':samples+[{'id':99999999,'createdAt':VISIBLE_FROM-1,'composition':'(SEPTEMBER)','hasLabel':True}]}).encode()
    app.worker.request=online_request
    app.reload()
    while not app.actions.empty(): app.actions.get_nowait()()
    assert requests==[f'leads?from={VISIBLE_FROM}'] and len(app.catalog)==8
    assert app.connection.get().startswith('Есть соединение')
    assert not (app.worker.DATA/'state.json').exists()
    app.worker.request=original_request
    from unittest.mock import patch
    assert len(app.board.error_boxes)==8
    with patch.object(messagebox,'showinfo') as popup:
        item={'id':90000100,'createdAt':timestamp,'composition':'','hasLabel':False}
        app.show_error(item)
        assert 'артикула' in popup.call_args.args[1] and 'PDF' in popup.call_args.args[1]
    original_read=read_json
    with patch.object(sys.modules[__name__],'read_json',side_effect=lambda path,default: {'printed':{'90000000':{'status':'submitted'}}} if Path(path).name=='state.json' else original_read(path,default)):
        app.render()
        assert sum(len(g['items']) for g in app.boards[1].groups)==1
        assert sum(len(g['items']) for g in app.boards[2].groups)==7
        assert len(app.board.error_boxes)==7
        assert len(app.article_pending['CHECK_0'])==2
    from rounded_controls import RoundedArticleCards
    icon_probe=RoundedArticleCards(root)
    icon_probe.set_choices([('DONE','DONE · 0',False,True,('#ffffff',INK),lambda:None)])
    assert icon_probe.printer_colors['DONE']=='#959eaa'
    icon_probe.destroy()
    app.render()
    assert len(app.article_pending['CHECK_0'])==3
    with patch.object(app,'print_items') as batch:
        app.article_filters.action_buttons['CHECK_0'].invoke()
        assert len(batch.call_args.args[0])==3
    app.printer_names=['Self-test printer']; app.printer.set('Self-test printer')
    with patch.object(threading,'Thread'):
        app.auto_print.set(True); app.toggle_auto_print()
        assert auto_print_enabled(app.worker.DATA) and app.auto_print.get()
        app.auto_print.set(False); app.toggle_auto_print()
        assert not auto_print_enabled(app.worker.DATA) and not app.auto_print.get()
    saved=[]
    probe=PrinterPanel(root,{'enabled':False,'routes':[]},lambda:['CHECK_SKU'],lambda cfg,auto:saved.append(cfg) or True,lambda _:None)
    probe.set_printers(['Self-test printer'])
    probe.rows[1]['printer'].set('Self-test printer'); probe.printer_changed(1)
    probe.rows[1]['articles'].buttons['CHECK_SKU'].invoke()
    assert probe.selected(1)==['CHECK_SKU']
    assert all('CHECK_SKU' not in row['articles'].buttons for i,row in enumerate(probe.rows) if i!=1)
    probe.rows[1]['articles'].buttons['CHECK_SKU'].invoke()
    assert all('CHECK_SKU' in row['articles'].buttons for row in probe.rows)
    assert probe.dirty and probe.save(True)
    restored=PrinterPanel(root,saved[-1],lambda:['CHECK_SKU'],lambda *_:True,lambda _:None)
    assert restored.rows[1]['printer'].get()=='Self-test printer'
    probe.destroy(); restored.destroy()
    app.settings(); root.update_idletasks()
    assert app.printers.winfo_exists() and app.log.winfo_exists()
    from print_journal import append_entry
    assert append_entry(app.worker.DATA,{'id':90000000,'orderNumber':'00001234','composition':'(CHECK_0)'},'Self-test printer','manual')
    app.refresh_journal()
    assert '1' in app.journal_summary.get() and len(app.journal_tree.get_children())==1
    root.destroy()
    out=Path(sys.argv[sys.argv.index('--self-test')+1])
    out.write_text(json.dumps({'ok':True,'dpapi':True,'pdf':True,'barcode':True,'printerHelper':True,'windowControls':True,'printerRows':4,'printersInSettings':True,'articleWrap':True,'articleButtons':True,'continuousGrid':True,'printTabs':True,'allOrders':True,'dayGroups':True,'connectionIndicator':True,'errorDetails':True,'autoPrintSwitch':True,'articleCounters':True,'articleBatch':True,'movesToPrinted':True,'articleFilter':True,'printerPersistence':True,'multiSelect':True}),encoding='utf-8')

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
