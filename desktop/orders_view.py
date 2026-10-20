"""Панель из двенадцати карточек в ряд с разделителями дней поступления."""
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
    def __init__(self, parent, on_print, on_select=None, on_error=None):
        super().__init__(parent)
        self.on_print = on_print; self.groups = []; self.hitboxes = []; self.enabled = True
        self.on_select=on_select; self.selection_mode=False; self.selected=set(); self.selection_boxes=[]
        self.on_error=on_error; self.error_boxes=[]
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
        c=self.canvas; c.delete('all'); self.hitboxes=[]; self.selection_boxes=[]; self.error_boxes=[]
        width=max(c.winfo_width(),1040); gap=6; left=8; columns=12
        cardw=(width-2*left-(columns-1)*gap)/columns; cardh=154; y=10
        if not self.groups:
            c.create_text(width/2,110,text='Пока нет заказов',font=('Segoe UI',24,'bold'),fill=INK)
            c.create_text(width/2,154,text=self.empty,font=('Segoe UI',11),fill=MUTED)
        index=0; current_day=None
        day_counts={}
        for group in self.groups:
            day_counts[group.get('day')]=day_counts.get(group.get('day'),0)+len(group['items'])
        for group in self.groups:
            day=group.get('day')
            if day is not None and day!=current_day:
                y+=((index+columns-1)//columns)*(cardh+gap)
                index=0; current_day=day
                c.create_text(left,y+14,anchor='w',text=f'{day} · Заявок: {day_counts[day]}',font=('Segoe UI',16,'bold'),fill=INK,tags='day-heading')
                c.create_line(left,y+40,width-left,y+40,fill='#dce2ed')
                y+=58
            color,fg=group['colors']
            for item in group['items']:
                col=index%columns; row=index//columns; x=left+col*(cardw+gap); top=y+row*(cardh+gap)
                self.card(x,top,cardw,cardh,item,color,fg)
                index+=1
        y+=((index+columns-1)//columns)*(cardh+gap)
        c.configure(scrollregion=(0,0,width,max(y,c.winfo_height())))
    @staticmethod
    def fit(text, length):
        return text if len(text)<=length else text[:length-1]+'…'
    def card(self,x,y,w,h,item,color,fg):
        c=self.canvas
        rounded(c,x,y+2,w,h,8,fill='#e5e9f2',outline='')
        rounded(c,x,y,w,h,8,fill=color,outline='')
        secondary='#d6e5ff' if fg=='#ffffff' else '#45516b'
        cx=x+w-10; cy=y+10
        c.create_oval(cx-6,cy-6,cx+6,cy+6,fill='#00a854' if item['confirmed'] else '#ef2345',outline='white')
        c.create_text(cx,cy,text='✓' if item['confirmed'] else '!',font=('Segoe UI',7,'bold'),fill='white')
        c.create_text(x+6,y+11,anchor='w',text=str(item['id']),font=('Segoe UI',6),fill=secondary)
        number=order_title(item); size=9
        while size>6 and tkfont.Font(family='Segoe UI',size=size,weight='bold').measure(number)>w-12: size-=1
        c.create_text(x+w/2,y+28,text=number,font=('Segoe UI',size,'bold'),fill=fg)
        sku='; '.join(item['skus']) or 'Без артикула'
        maxchars=max(8,int((w-12)/6)); lines=[]; remainder=sku
        while remainder and len(lines)<2:
            lines.append(remainder[:maxchars]); remainder=remainder[maxchars:]
        if remainder: lines[-1]=self.fit(lines[-1],maxchars-1)+'…'
        c.create_text(x+6,y+43,anchor='nw',text='\n'.join(lines),font=('Segoe UI',8,'bold'),fill=fg)
        carrier={'cdek':'СДЭК','yandex':'Яндекс','unknown':'Без доставки'}[delivery_service(item)]
        c.create_text(x+6,y+78,anchor='w',text=carrier,font=('Segoe UI',7,'bold'),fill=secondary)
        date=datetime.fromtimestamp(item['createdAt'],MOSCOW).strftime('%d.%m %H:%M')
        c.create_text(x+6,y+92,anchor='w',text=date,font=('Segoe UI',7),fill=fg)
        status='Отправлено' if item['confirmed'] else ('К печати' if item['canPrint'] else 'Нет PDF/артикула')
        c.create_text(x+6,y+106,anchor='w',text=status,font=('Segoe UI',6),fill=secondary)
        by=y+h-30; bh=24; bx=x+6
        show_reason=not item['confirmed'] and self.on_error is not None
        bw=w-12-(28 if show_reason else 0)
        active=item['canPrint'] and self.enabled
        rounded(c,bx,by,bw,bh,6,fill='#ffffff' if active else '#dce2eb',outline='')
        px=bx+bw/2-8; py=by+6
        c.create_rectangle(px+3,py-2,px+13,py+3,outline=INK,width=1)
        c.create_rectangle(px,py+2,px+16,py+10,outline=INK,width=1)
        c.create_rectangle(px+3,py+7,px+13,py+14,fill='white',outline=INK,width=1)
        if active: self.hitboxes.append((bx,by,bx+bw,by+bh,item))
        if show_reason:
            rx=x+w-28
            rounded(c,rx,by,22,bh,6,fill='white',outline='')
            c.create_text(rx+11,by+12,text='?',font=('Segoe UI',10,'bold'),fill=INK)
            self.error_boxes.append((rx,by,rx+22,by+bh,item))
        if self.selection_mode:
            checked=str(item['id']) in self.selected
            c.create_rectangle(x+5,y+4,x+18,y+17,fill=INK if checked else 'white',outline='white')
            if checked: c.create_text(x+11,y+10,text='✓',font=('Segoe UI',8,'bold'),fill='white')
            if self.enabled and item['canPrint']: self.selection_boxes.append((x+3,y+2,x+21,y+19,item))
    def hit(self,event):
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        return next((v[4] for v in self.hitboxes if v[0]<=x<=v[2] and v[1]<=y<=v[3]),None)
    def selection_hit(self,event):
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        return next((v[4] for v in self.selection_boxes if v[0]<=x<=v[2] and v[1]<=y<=v[3]),None)
    def error_hit(self,event):
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        return next((v[4] for v in self.error_boxes if v[0]<=x<=v[2] and v[1]<=y<=v[3]),None)
    def click(self,event):
        error=self.error_hit(event)
        if error and self.on_error: return self.on_error(error)
        selection=self.selection_hit(event)
        if selection and self.on_select: return self.on_select(selection)
        item=self.hit(event)
        if item: self.on_print(item)
    def motion(self,event):
        self.canvas.configure(cursor='hand2' if self.hit(event) or self.selection_hit(event) or self.error_hit(event) else '')
