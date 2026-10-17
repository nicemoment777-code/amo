"""Панель из четырёх карточек в ряд с прокруткой по группам артикулов."""
import calendar
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from orders_model import MOSCOW, order_title, delivery_service

BG = '#f4f6fb'
INK = '#111936'
MUTED = '#737d94'

def rounded(canvas, x, y, w, h, radius, **kwargs):
    points = [x+radius,y, x+w-radius,y, x+w,y, x+w,y+radius,
              x+w,y+h-radius, x+w,y+h, x+w-radius,y+h,
              x+radius,y+h, x,y+h, x,y+h-radius, x,y+radius, x,y]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

class DatePicker:
    def __init__(self, parent, variable):
        self.variable = variable
        try: date = datetime.strptime(variable.get(), '%d.%m.%Y')
        except ValueError: date = datetime.now(MOSCOW)
        self.year, self.month = date.year, date.month
        self.window = tk.Toplevel(parent); self.window.title('Выберите дату'); self.window.resizable(False,False)
        self.window.transient(parent.winfo_toplevel())
        self.frame = ttk.Frame(self.window, padding=14); self.frame.pack()
        self.draw()
    def draw(self):
        for child in self.frame.winfo_children(): child.destroy()
        months = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь']
        ttk.Button(self.frame,text='‹',width=3,command=lambda:self.move(-1)).grid(row=0,column=0)
        ttk.Label(self.frame,text=f'{months[self.month-1]} {self.year}',anchor='center').grid(row=0,column=1,columnspan=5)
        ttk.Button(self.frame,text='›',width=3,command=lambda:self.move(1)).grid(row=0,column=6)
        for col, name in enumerate(['Пн','Вт','Ср','Чт','Пт','Сб','Вс']):
            ttk.Label(self.frame,text=name,anchor='center').grid(row=1,column=col,pady=8)
        for row, week in enumerate(calendar.monthcalendar(self.year,self.month),2):
            for col, day in enumerate(week):
                if day: ttk.Button(self.frame,text=str(day),width=3,command=lambda d=day:self.select(d)).grid(row=row,column=col,padx=1,pady=1)
    def move(self, amount):
        month = self.year*12+self.month-1+amount
        self.year,self.month = month//12,month%12+1; self.draw()
    def select(self, day):
        self.variable.set(f'{day:02}.{self.month:02}.{self.year}'); self.window.destroy()

class OrdersBoard(ttk.Frame):
    def __init__(self, parent, on_print, on_select=None):
        super().__init__(parent)
        self.on_print = on_print; self.groups = []; self.hitboxes = []; self.enabled = True
        self.on_select=on_select; self.selection_mode=False; self.selected=set(); self.selection_boxes=[]
        self.canvas = tk.Canvas(self,bg=BG,highlightthickness=0,bd=0)
        self.scroll = ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side='right',fill='y'); self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda _:self.draw())
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        self.canvas.bind('<Button-1>',self.click)
        self.canvas.bind('<Motion>',self.motion)
        self.canvas.configure(yscrollincrement=26)
        self.empty = 'Выберите период и нажмите «Показать».'
    def set_groups(self, groups, reset_scroll=False, empty=None):
        self.groups=groups
        if empty: self.empty=empty
        self.draw()
        if reset_scroll: self.canvas.yview_moveto(0)
    def set_enabled(self, enabled):
        self.enabled=enabled; self.draw()
    def set_selection(self, mode, selected):
        self.selection_mode=mode; self.selected=set(selected); self.draw()
    def draw(self):
        c=self.canvas; c.delete('all'); self.hitboxes=[]; self.selection_boxes=[]
        width=max(c.winfo_width(),1040); gap=18; left=28
        cardw=(width-2*left-3*gap)/4; cardh=278; y=18
        if not self.groups:
            c.create_text(width/2,110,text='Пока нет заказов',font=('Segoe UI',24,'bold'),fill=INK)
            c.create_text(width/2,154,text=self.empty,font=('Segoe UI',11),fill=MUTED)
        index=0
        for group in self.groups:
            color,fg=group['colors']
            for item in group['items']:
                col=index%4; row=index//4; x=left+col*(cardw+gap); top=y+row*(cardh+gap)
                self.card(x,top,cardw,cardh,item,color,fg)
                index+=1
        y+=((index+3)//4)*(cardh+gap)
        c.configure(scrollregion=(0,0,width,max(y,c.winfo_height())))
    @staticmethod
    def fit(text, length):
        return text if len(text)<=length else text[:length-1]+'…'
    def card(self,x,y,w,h,item,color,fg):
        c=self.canvas; light=fg!=INK and fg=='#ffffff'
        rounded(c,x,y+4,w,h,16,fill='#e5e9f2',outline='')
        rounded(c,x,y,w,h,16,fill=color,outline='')
        number=order_title(item)
        number_font=23 if w>=285 else 19
        while number_font>13 and tkfont.Font(family='Segoe UI',size=number_font,weight='bold').measure(number)>w-98:
            number_font-=1
        title_y=y+47 if self.selection_mode else y+40
        c.create_text(x+22,title_y,anchor='w',text=number,font=('Segoe UI',number_font,'bold'),fill=fg)
        if self.selection_mode:
            checked=str(item['id']) in self.selected
            c.create_rectangle(x+17,y+10,x+36,y+29,fill=INK if checked else '#ffffff',outline='#ffffff',width=2)
            if checked: c.create_line(x+21,y+19,x+26,y+24,x+33,y+14,fill='white',width=3)
            c.create_text(x+44,y+19,anchor='w',text='Выбрано' if checked else 'Выбрать',font=('Segoe UI',9),fill=fg)
            if self.enabled and item['canPrint']: self.selection_boxes.append((x+12,y+6,x+120,y+32,item))
        cx=x+w-36; cy=y+34
        c.create_oval(cx-25,cy-25,cx+25,cy+25,fill='#ffffff',outline='')
        c.create_oval(cx-21,cy-21,cx+21,cy+21,fill='#00b85b' if item['confirmed'] else '#ff123b',outline='')
        if item['confirmed']:
            c.create_line(cx-10,cy,cx-3,cy+8,cx+11,cy-9,fill='white',width=5,capstyle='round',joinstyle='round')
        else:
            c.create_line(cx,cy-11,cx,cy+3,fill='white',width=5,capstyle='round')
            c.create_oval(cx-3,cy+9,cx+3,cy+15,fill='white',outline='')
        secondary='#d6e5ff' if light else '#45516b'
        c.create_text(x+22,y+66,anchor='w',text='Заявка amoCRM · '+str(item['id']),font=('Segoe UI',8),fill=secondary)
        c.create_text(x+22,y+86,anchor='w',text='Артикул',font=('Segoe UI',10),fill=secondary)
        sku='; '.join(item['skus']) or 'Не указан'
        # Keep the exact article visible on two lines where possible.
        maxchars=max(16,int((w-44)/10)); lines=[]; remainder=sku
        while remainder and len(lines)<2:
            if len(remainder)<=maxchars: lines.append(remainder); remainder=''
            else:
                split=remainder.rfind(' ',0,maxchars)
                if split<maxchars//2: split=maxchars
                lines.append(remainder[:split]); remainder=remainder[split:].lstrip()
        if remainder: lines[-1]=self.fit(lines[-1],maxchars-1)+'…'
        c.create_text(x+22,y+100,anchor='nw',text='\n'.join(lines),font=('Segoe UI',14,'bold'),fill=fg)
        carrier={'cdek':'СДЭК','yandex':'Яндекс','unknown':'Доставка не указана'}[delivery_service(item)]
        c.create_text(x+22,y+146,anchor='w',text=carrier,font=('Segoe UI',9,'bold'),fill=secondary)
        c.create_text(x+22,y+164,anchor='w',text='Дата поступления · МСК',font=('Segoe UI',9),fill=secondary)
        date=datetime.fromtimestamp(item['createdAt'],MOSCOW).strftime('%d.%m.%Y · %H:%M')
        c.create_text(x+22,y+184,anchor='w',text=date,font=('Segoe UI',12,'bold'),fill=fg)
        status=item['statusText'] if item['canPrint'] else 'Нет этикетки или артикула'
        c.create_text(x+22,y+207,anchor='w',text=status,font=('Segoe UI',9),fill=secondary)
        bx=x+16; by=y+h-52; bw=w-32; bh=36
        active=item['canPrint'] and self.enabled
        rounded(c,bx,by,bw,bh,9,fill='#ffffff' if active else '#e0e6ee',outline='',stipple='' if active else 'gray75')
        label='Повторная печать' if item['confirmed'] else 'Напечатать этикетку'
        c.create_text(bx+bw/2+8,by+bh/2,text=label if self.enabled else 'Подождите…',font=('Segoe UI',10,'bold'),fill=INK if active else '#78849b')
        px=bx+15; py=by+10
        c.create_rectangle(px+3,py-3,px+15,py+3,outline=INK,width=1.5)
        c.create_rectangle(px,py+2,px+18,py+12,outline=INK,width=1.5)
        c.create_rectangle(px+3,py+8,px+15,py+17,fill='#ffffff',outline=INK,width=1.5)
        if active: self.hitboxes.append((bx,by,bx+bw,by+bh,item))
    def hit(self,event):
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        return next((v[4] for v in self.hitboxes if v[0]<=x<=v[2] and v[1]<=y<=v[3]),None)
    def selection_hit(self,event):
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        return next((v[4] for v in self.selection_boxes if v[0]<=x<=v[2] and v[1]<=y<=v[3]),None)
    def click(self,event):
        selection=self.selection_hit(event)
        if selection and self.on_select: return self.on_select(selection)
        item=self.hit(event)
        if item: self.on_print(item)
    def motion(self,event):
        self.canvas.configure(cursor='hand2' if self.hit(event) or self.selection_hit(event) else '')
