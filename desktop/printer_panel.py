"""Постоянно видимые строки принтеров и списки артикулов с галочками."""
import tkinter as tk
from tkinter import ttk
from printer_routing import normalize_routes, PrinterRoutingError

EMPTY_PRINTER='— Не выбран —'

def checkbox_popup(parent, anchor, entries, commands=()):
    menu=tk.Menu(parent,tearoff=False,font=('Segoe UI',11))
    for label,callback in commands:
        menu.add_command(label=label,command=callback)
    if commands: menu.add_separator()
    for label,variable,disabled,callback in entries:
        menu.add_checkbutton(label=label,variable=variable,state='disabled' if disabled else 'normal',command=callback)
    if not entries: menu.add_command(label='Артикулов в заявках пока нет',state='disabled')
    def toggle(event):
        index=menu.index('@'+str(event.y))
        if index is not None and menu.type(index)=='checkbutton':
            menu.invoke(index)
            return 'break'
    menu.bind('<ButtonRelease-1>',toggle)
    menu.tk_popup(anchor.winfo_rootx(),anchor.winfo_rooty()+anchor.winfo_height())

def routes_from_rows(rows):
    """Не допускаем случайное удаление выбранных артикулов у пустой строки."""
    routes=[]
    for printer,skus in rows:
        if not printer or printer==EMPTY_PRINTER:
            if skus: raise PrinterRoutingError('Для выбранных артикулов укажите принтер в этой строке.')
            continue
        if not skus: raise PrinterRoutingError('Выберите артикулы или очистите строку принтера.')
        routes.append({'printer':printer,'skus':skus})
    return normalize_routes({'enabled':True,'routes':routes})

class PrinterPanel(ttk.Frame):
    def __init__(self,parent,config,known_skus,on_save,on_note):
        super().__init__(parent)
        self.known_skus=known_skus; self.on_save=on_save; self.on_note=on_note; self.names=[]; self.rows=[]
        heading=ttk.Frame(self); heading.pack(fill='x',pady=(0,5))
        ttk.Label(heading,text='Принтеры и артикулы',font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(heading,text='Сохранить назначения',style='Accent.TButton',command=self.save).pack(side='right')
        table=ttk.Frame(self); table.pack(fill='x'); self.table=table
        ttk.Label(table,text='Принтер Windows',foreground='#737d94').grid(row=0,column=1,sticky='w',padx=8)
        ttk.Label(table,text='Артикулы для печати',foreground='#737d94').grid(row=0,column=2,sticky='w',padx=8)
        table.columnconfigure(1,weight=1); table.columnconfigure(2,weight=2)
        routes=config.get('routes',[])
        for index in range(max(4,len(routes))):
            route=routes[index] if index<len(routes) else {}
            self.add_row(route)
        self.description=tk.StringVar(value='Один артикул закрепляется только за одним принтером. Выбор сохраняется общей кнопкой.')
        ttk.Label(self,textvariable=self.description,foreground='#737d94',wraplength=1200).pack(anchor='w',pady=(5,0))
    def add_row(self,route):
        index=len(self.rows); y=index+1
        row={'printer':tk.StringVar(value=route.get('printer',EMPTY_PRINTER)),
             'checks':{sku:tk.BooleanVar(value=True) for sku in route.get('skus',[])}}
        ttk.Label(self.table,text=str(index+1),width=2).grid(row=y,column=0,sticky='w')
        combo=ttk.Combobox(self.table,textvariable=row['printer'],state='readonly',width=32)
        combo.grid(row=y,column=1,sticky='ew',padx=8,pady=3); row['combo']=combo
        combo.bind('<<ComboboxSelected>>',lambda _,i=index:self.printer_changed(i))
        button=ttk.Button(self.table,width=48,command=lambda i=index:self.sku_menu(i))
        button.grid(row=y,column=2,sticky='ew',padx=8,pady=3); row['button']=button
        ttk.Button(self.table,text='Очистить',command=lambda i=index:self.clear(i)).grid(row=y,column=3,padx=(8,0),pady=3)
        self.rows.append(row); self.caption(index)
    def set_printers(self,names):
        self.names=list(names)
        for row in self.rows:
            values=[EMPTY_PRINTER]+self.names
            if row['printer'].get() not in values: values.append(row['printer'].get())
            row['combo'].configure(values=values)
    def selected(self,index):
        return sorted(sku for sku,var in self.rows[index]['checks'].items() if var.get())
    def caption(self,index):
        selected=self.selected(index)
        text='; '.join(selected)
        if len(text)>64: text=text[:61]+'…'
        self.rows[index]['button'].configure(text=(text+'  ▾') if selected else 'Выбрать артикулы ▾')
    def printer_changed(self,index):
        if self.rows[index]['printer'].get()==EMPTY_PRINTER:
            self.clear(index)
    def clear(self,index):
        row=self.rows[index]; row['printer'].set(EMPTY_PRINTER); row['checks']={}; self.caption(index)
    def sku_menu(self,index):
        row=self.rows[index]
        if row['printer'].get()==EMPTY_PRINTER: return self.on_note('Сначала укажите принтер в этой строке.')
        owners={sku:other['printer'].get() for n,other in enumerate(self.rows) if n!=index for sku in self.selected(n)}
        known=set(self.known_skus())
        for n in range(len(self.rows)): known.update(self.selected(n))
        entries=[]
        for sku in sorted(known):
            other=owners.get(sku); disabled=other is not None
            var=row['checks'].setdefault(sku,tk.BooleanVar(value=False))
            entries.append((sku+(f'  — {other}' if disabled else ''),var,disabled,lambda i=index:self.caption(i)))
        checkbox_popup(self,row['button'],entries)
    def save(self):
        try:
            config=routes_from_rows([(row['printer'].get(),self.selected(i)) for i,row in enumerate(self.rows)])
            for route in config['routes']:
                if route['printer'] not in self.names: raise PrinterRoutingError('Выберите установленный принтер Windows в каждой заполненной строке.')
            if self.on_save(config): self.description.set('Сохранено. Каждый артикул печатается только на назначенном принтере.')
        except PrinterRoutingError as e: self.on_note(str(e))
