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
import tkinter as tk
from tkinter import ttk, messagebox
from urllib.request import Request, build_opener, HTTPRedirectHandler
import webbrowser
import winreg

TITLE = 'Снегострой — печать СДЭК'
ORIGIN = 'https://snowbrick.ru'
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
HOME = Path(os.environ['LOCALAPPDATA'])/'SnowbrickPrinter'
HOME.mkdir(parents=True, exist_ok=True)
CONFIG = HOME/'settings.json'
TOKEN = HOME/'device-key.bin'
os.environ['SNOWBRICK_DATA_DIR'] = str(HOME/'printing')
os.environ['SNOWBRICK_POPPLER'] = str(BASE/'poppler'/'pdftoppm.exe')
os.environ['SNOWBRICK_PRINT_SCRIPT'] = str(BASE/'ops'/'print-image.ps1')
sys.path.insert(0, str(BASE/'ops'))

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
    def __init__(self, root):
        self.root = root; self.running = False; self.busy = False; self.stop_event = threading.Event(); self.thread = None
        self.config = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}
        self.worker = load_worker()
        self.worker.POPPLER = Path(os.environ['SNOWBRICK_POPPLER'])
        self.token = device_token(); os.environ['PRINT_AGENT_TOKEN'] = self.token
        root.title(TITLE); root.geometry('680x590'); root.minsize(620,540)
        style=ttk.Style(); style.theme_use('clam'); style.configure('.',font=('Segoe UI',10)); style.configure('TButton',padding=9)
        frame=ttk.Frame(root,padding=24); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Печать этикеток СДЭК',font=('Segoe UI',20,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Личный кабинет snegostroy.amocrm.ru • каждые 5 минут').pack(anchor='w',pady=(4,18))
        self.status=tk.StringVar(value='Выберите принтер и подключите компьютер')
        ttk.Label(frame,textvariable=self.status,wraplength=600).pack(anchor='w',pady=(0,12))
        pairrow=ttk.Frame(frame); pairrow.pack(fill='x')
        ttk.Button(pairrow,text='Подключить компьютер',command=self.pair).pack(side='left')
        ttk.Button(pairrow,text='Настройки в amoCRM',command=lambda:webbrowser.open(ORIGIN+'/integrations/amocrm')).pack(side='left',padx=8)
        ttk.Label(frame,text='Принтер Windows').pack(anchor='w',pady=(20,4))
        self.printer=tk.StringVar(value=self.config.get('printer','4BARCODE 3B-T361U'))
        self.printers=ttk.Combobox(frame,textvariable=self.printer,state='readonly'); self.printers.pack(fill='x')
        self.printers.bind('<<ComboboxSelected>>',lambda _:self.save())
        self.startup=tk.BooleanVar(value=self.config.get('startup',False))
        ttk.Checkbutton(frame,text='Запускать при входе в Windows',variable=self.startup,command=self.autostart).pack(anchor='w',pady=12)
        buttons=ttk.Frame(frame); buttons.pack(fill='x')
        ttk.Button(buttons,text='Запустить',command=self.start).pack(side='left')
        ttk.Button(buttons,text='Остановить',command=self.stop).pack(side='left',padx=8)
        ttk.Button(buttons,text='Пробная печать',command=self.test).pack(side='left')
        ttk.Label(frame,text='Формат: этикетка 1:1, сверху 15 мм; только артикулы.\nГруппы печатаются по убыванию количества заявок.',wraplength=600).pack(anchor='w',pady=18)
        self.log= tk.Text(frame,height=9,wrap='word',state='disabled',font=('Segoe UI',10)); self.log.pack(fill='both',expand=True)
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.background(self.refresh_printers)
        if self.config.get('enabled'): root.after(1000,self.start)

    def note(self,text):
        self.status.set(text); self.log.configure(state='normal'); self.log.insert('end',time.strftime('%H:%M:%S')+'  '+text+'\n'); self.log.see('end'); self.log.configure(state='disabled')
    def ui(self,callback): self.root.after(0,callback)
    def background(self,callback): threading.Thread(target=callback,daemon=True).start()
    def save(self):
        self.config.update(printer=self.printer.get(),startup=self.startup.get(),enabled=self.running)
        temp=CONFIG.with_suffix('.tmp'); temp.write_text(json.dumps(self.config,ensure_ascii=False),encoding='utf-8'); os.replace(temp,CONFIG)
    def refresh_printers(self):
        try:
            data=json.loads(powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8; @(Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name) | ConvertTo-Json -Compress"))
            names=data if isinstance(data,list) else [data]
            self.ui(lambda:self.printers.configure(values=names))
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
                        self.ui(lambda:self.note('Компьютер подключён. Выберите принтер и нажмите «Запустить».')); return
                self.ui(lambda:self.note('Код истёк. Нажмите «Подключить компьютер» ещё раз.'))
            except Exception: self.ui(lambda:self.note('Не удалось подключить компьютер. Проверьте интернет и повторите.'))
        self.background(work)
    def start(self):
        if self.running: return
        if self.thread and self.thread.is_alive(): return self.note('Дождитесь завершения предыдущей проверки.')
        if not self.printer.get(): return self.note('Выберите принтер Windows.')
        self.running=True; self.stop_event.clear(); self.save(); self.note('Автоматическая печать включена.')
        def loop():
            while not self.stop_event.is_set():
                self.pass_once()
                if self.stop_event.wait(300): break
        self.thread=threading.Thread(target=loop,daemon=True); self.thread.start()
    def stop(self):
        self.running=False; self.stop_event.set(); self.save(); self.note('Остановлено. Уже отправленные задания остаются в очереди Windows.')
    def pass_once(self):
        if self.busy: return
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
        finally: self.busy=False
    def test(self):
        if self.running or self.busy: return self.note('Перед пробной печатью остановите автоматическую проверку.')
        if not messagebox.askyesno(TITLE,'Отправить одну последнюю доступную этикетку на выбранный принтер? Это пробный экземпляр.'): return
        self.busy=True; self.worker.PRINTER=self.printer.get()
        def work():
            try:
                data=json.loads(self.worker.request('leads?from=0&sample=1'))
                item=next(v for v in data['items'] if v['hasLabel'] and v['composition'])
                with self.worker.agent_lock():
                    _,image,details=self.worker.prepare(item,for_print=True,variant='-desktop-test')
                    self.worker.print_label(image,details)
                self.ui(lambda:self.note('Пробная этикетка отправлена. Проверьте физический отпечаток.'))
            except Exception: self.ui(lambda:self.note('Не удалось отправить пробную этикетку. Проверьте доступ и принтер.'))
            finally: self.busy=False
        self.background(work)
    def autostart(self):
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                if self.startup.get():
                    winreg.SetValueEx(key,'SnowbrickPrinter',0,winreg.REG_SZ,'"'+sys.executable+'"')
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
    out=Path(sys.argv[sys.argv.index('--self-test')+1])
    out.write_text(json.dumps({'ok':True,'dpapi':True,'pdf':True,'barcode':True,'printerHelper':True}),encoding='utf-8')

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
