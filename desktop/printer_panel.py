"""Четыре строки принтеров с кнопками артикулов и сохранением назначений."""
import tkinter as tk
from tkinter import ttk
from printer_routing import normalize_routes, PrinterRoutingError
from article_buttons import ArticleButtons
from orders_model import sku_color

EMPTY_PRINTER='— Не выбран —'

def routes_from_rows(rows, enabled=True):
    slots=[]
    for printer,skus in rows:
        if not printer or printer==EMPTY_PRINTER:
            if skus: raise PrinterRoutingError('Для выбранных артикулов укажите принтер в этой строке.')
            printer=''
        slots.append({'printer':printer,'skus':skus})
    return normalize_routes({'enabled':enabled,'slots':slots})

def available_articles(known, rows, index):
    occupied={sku for n,(_,skus) in enumerate(rows) if n!=index for sku in skus}
    own=set(rows[index][1])
    return sorted((set(known)|own)-occupied)

class PrinterPanel(ttk.Frame):
    def __init__(self,parent,config,known_skus,on_save,on_note):
        super().__init__(parent)
        self.known_skus=known_skus; self.on_save=on_save; self.on_note=on_note; self.names=[]; self.rows=[]
        self.routing_enabled=config.get('enabled',False); self.dirty=False; self.save_timer=None
        heading=ttk.Frame(self); heading.pack(fill='x',pady=(0,5))
        ttk.Label(heading,text='Принтеры и артикулы',font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(heading,text='Сохранить назначения',style='Accent.TButton',command=self.save).pack(side='right')
        table=ttk.Frame(self); table.pack(fill='x'); self.table=table
        ttk.Label(table,text='Принтер Windows',foreground='#737d94').grid(row=0,column=1,sticky='w',padx=8)
        ttk.Label(table,text='Артикулы для печати',foreground='#737d94').grid(row=0,column=2,sticky='w',padx=8)
        table.columnconfigure(2,weight=1)
        routes=config.get('slots',config.get('routes',[]))
        for index in range(max(4,len(routes))):
            route=routes[index] if index<len(routes) else {}
            self.add_row(route)
        self.refresh_articles()
        self.description=tk.StringVar(value='Выбор принтеров и артикулов сохраняется автоматически. Занятые артикулы скрыты у остальных принтеров.')
        ttk.Label(self,textvariable=self.description,foreground='#737d94',wraplength=1200).pack(anchor='w',pady=(5,0))
    def add_row(self,route):
        index=len(self.rows); y=index+1
        row={'printer':tk.StringVar(value=route.get('printer') or EMPTY_PRINTER),
             'checks':{sku:tk.BooleanVar(value=True) for sku in route.get('skus',[])}}
        row['previous']=row['printer'].get()
        ttk.Label(self.table,text=str(index+1),width=2).grid(row=y,column=0,sticky='w')
        combo=ttk.Combobox(self.table,textvariable=row['printer'],state='readonly',width=27)
        combo.grid(row=y,column=1,sticky='ew',padx=8,pady=3); row['combo']=combo
        combo.bind('<<ComboboxSelected>>',lambda _,i=index:self.printer_changed(i))
        row['articles']=ArticleButtons(self.table)
        row['articles'].grid(row=y,column=2,sticky='ew',padx=8,pady=3)
        ttk.Button(self.table,text='Очистить',command=lambda i=index:self.clear(i)).grid(row=y,column=3,padx=(8,0),pady=3)
        self.rows.append(row)
    def set_printers(self,names):
        self.names=list(names)
        for row in self.rows:
            values=[EMPTY_PRINTER]+self.names
            if row['printer'].get() not in values: values.append(row['printer'].get())
            row['combo'].configure(values=values)
    def selected(self,index):
        return sorted(sku for sku,var in self.rows[index]['checks'].items() if var.get())
    def refresh_articles(self):
        known=set(self.known_skus())
        rows=[(r['printer'].get(),self.selected(i)) for i,r in enumerate(self.rows)]
        for _,skus in rows: known.update(skus)
        for index,row in enumerate(self.rows):
            choices=[]
            for sku in available_articles(known,rows,index):
                var=row['checks'].setdefault(sku,tk.BooleanVar(value=False))
                choices.append((sku,sku,var.get(),row['printer'].get()!=EMPTY_PRINTER,
                                sku_color((sku,)),lambda i=index,s=sku:self.toggle_article(i,s)))
            row['articles'].set_choices(choices)
    def printer_changed(self,index):
        row=self.rows[index]; name=row['printer'].get()
        if name!=EMPTY_PRINTER and any(n!=index and other['printer'].get()==name for n,other in enumerate(self.rows)):
            row['printer'].set(row['previous']); return self.on_note('Этот принтер уже выбран в другой строке.')
        if self.rows[index]['printer'].get()==EMPTY_PRINTER:
            return self.clear(index)
        row['previous']=name; self.refresh_articles(); self.queue_save()
    def clear(self,index):
        row=self.rows[index]; row['printer'].set(EMPTY_PRINTER); row['previous']=EMPTY_PRINTER; row['checks']={}; self.refresh_articles(); self.queue_save()
    def queue_save(self):
        self.dirty=True; self.description.set('Сохраняем выбор…')
        if self.save_timer: self.after_cancel(self.save_timer)
        self.save_timer=self.after(180,lambda:self.save(True))
    def toggle_article(self,index,sku):
        row=self.rows[index]
        if row['printer'].get()==EMPTY_PRINTER: return
        if any(n!=index and sku in self.selected(n) for n in range(len(self.rows))): return
        var=row['checks'].get(sku)
        if var is None: return
        var.set(not var.get()); self.refresh_articles(); self.queue_save()
    def save(self,automatic=False):
        if self.save_timer: self.after_cancel(self.save_timer); self.save_timer=None
        try:
            enabled=self.routing_enabled or any(self.selected(i) for i in range(len(self.rows)))
            config=routes_from_rows([(row['printer'].get(),self.selected(i)) for i,row in enumerate(self.rows)],enabled)
            if self.on_save(config,automatic):
                self.dirty=False; self.routing_enabled=enabled
                self.description.set('Сохранено автоматически. Выбор принтеров и артикулов восстановится при следующем запуске.')
                return True
            self.description.set('Ожидаем завершения текущего действия для сохранения…')
            if automatic: self.save_timer=self.after(1000,lambda:self.save(True))
        except PrinterRoutingError as e:
            self.description.set(str(e))
            if not automatic: self.on_note(str(e))
        return False
