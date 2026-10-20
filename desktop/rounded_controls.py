"""Закруглённые вкладки и карточки артикулов основного окна."""
import tkinter as tk
from tkinter import ttk, font as tkfont
from orders_view import BG, INK, rounded


class RoundedButton(tk.Canvas):
    """Кнопка с постоянным цветом и видимой рамкой выбранного фильтра."""
    def __init__(self,parent,text,command,color='#dce0e6',foreground=INK):
        super().__init__(parent,bg=BG,height=38,highlightthickness=0,takefocus=True,cursor='hand2')
        self.label=text; self.command=command; self.color=color; self.ink=foreground; self.selected=False
        self.bind('<Configure>',lambda _:self.draw())
        self.bind('<Button-1>',lambda _:self.invoke())
        self.bind('<Return>',lambda _:self.invoke())
        self.bind('<space>',lambda _:self.invoke())
        self.bind('<FocusIn>',lambda _:self.draw()); self.bind('<FocusOut>',lambda _:self.draw())
        self.configure(text=text)

    def configure(self,cnf=None,**kw):
        if 'text' in kw:
            self.label=kw.pop('text')
            kw['width']=tkfont.Font(family='Segoe UI',size=10,weight='bold').measure(self.label)+28
        if 'selected' in kw: self.selected=kw.pop('selected')
        result=super().configure(cnf,**kw)
        if hasattr(self,'label'): self.draw()
        return result

    config=configure

    def cget(self,key):
        return self.label if key=='text' else super().cget(key)

    def invoke(self):
        self.focus_set(); return self.command()

    def draw(self):
        self.delete('all')
        width=max(self.winfo_width(),int(super().cget('width')))
        rounded(self,2,2,width-4,34,11,fill=self.color,
                outline=INK if self.selected or self.focus_get()==self else '',width=2)
        self.create_text(width/2,19,text=self.label,font=('Segoe UI',10,'bold'),fill=self.ink)


class RoundedNotebook(ttk.Notebook):
    def __init__(self,parent):
        style=ttk.Style(parent)
        style.layout('Rounded.TNotebook.Tab',[])
        self.header=tk.Canvas(parent,bg=BG,height=64,highlightthickness=0,takefocus=False)
        self.header.pack(fill='x',padx=28)
        super().__init__(parent,style='Rounded.TNotebook')
        self.boxes=[]
        self.header.bind('<Configure>',lambda _:self.draw())
        self.header.bind('<Button-1>',self.click)
        self.bind('<<NotebookTabChanged>>',lambda _:self.draw(),add='+')

    def add(self,child,**kw):
        super().add(child,**kw); self.draw()

    def tab(self,tab_id,option=None,**kw):
        result=super().tab(tab_id,option,**kw)
        if kw: self.draw()
        return result

    def draw(self):
        self.header.delete('all'); self.boxes=[]
        tabs=self.tabs()
        if not tabs: return
        active=self.index('current'); x=0
        font=tkfont.Font(family='Segoe UI',size=12,weight='bold')
        for index,tab in enumerate(tabs):
            text=super().tab(tab,'text'); selected=index==active
            width=font.measure(text)+(52 if selected else 36)
            y=3 if selected else 18; height=60-y
            rounded(self.header,x,y,width,height,13,fill='#199653' if selected else '#dce0e6',outline='')
            self.header.create_text(x+width/2,y+height/2,text=text,font=('Segoe UI',13 if selected else 11,'bold'),fill='white' if selected else '#5e6878')
            self.boxes.append((x,y,x+width,60,index)); x+=width+8

    def click(self,event):
        for x,y,right,bottom,index in self.boxes:
            if x<=event.x<=right and y<=event.y<=bottom:
                self.select(index); self.focus_set(); self.draw(); return


class CardCommand:
    def __init__(self,callback): self.callback=callback
    def invoke(self): return self.callback()


class RoundedArticleCards(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.choices=[]; self.actions={}; self.buttons={}; self.action_buttons={}
        self.boxes=[]; self.print_boxes=[]; self.printer_colors={}; self.focus_index=0
        self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0,height=1,takefocus=True)
        self.canvas.pack(fill='x')
        self.canvas.bind('<Configure>',lambda _:self.draw())
        self.canvas.bind('<Button-1>',self.click)
        self.canvas.bind('<Motion>',self.motion)
        self.canvas.bind('<Left>',lambda _:self.focus_card(-1))
        self.canvas.bind('<Right>',lambda _:self.focus_card(1))
        self.canvas.bind('<space>',lambda _:self.filter_focused())
        self.canvas.bind('<Return>',lambda _:self.filter_focused())
        self.canvas.bind('<Shift-Return>',lambda _:self.print_focused())
        self.canvas.bind('<FocusIn>',lambda _:self.draw())
        self.canvas.bind('<FocusOut>',lambda _:self.draw())

    def set_choices(self,choices):
        self.choices=choices
        self.buttons={key:CardCommand(command) for key,_,_,_,_,command in choices}
        self.action_buttons={key:CardCommand(lambda k=key:self.print_article(k)) for key, *_ in choices if key not in ((),None)}
        self.draw()

    def set_actions(self,actions): self.actions=actions; self.draw()

    def print_article(self,key):
        enabled,command=self.actions.get(key,(False,None))
        if enabled and command: return command()

    def focus_card(self,offset):
        self.focus_index=(self.focus_index+offset)%max(1,len(self.choices)); self.draw(); return 'break'

    def filter_focused(self):
        if self.choices: self.buttons[self.choices[self.focus_index%len(self.choices)][0]].invoke()
        return 'break'

    def print_focused(self):
        if self.choices: self.print_article(self.choices[self.focus_index%len(self.choices)][0])
        return 'break'

    def draw(self):
        c=self.canvas; c.delete('all'); self.boxes=[]; self.print_boxes=[]; self.printer_colors={}
        available=max(1,c.winfo_width()); gap=8
        preferred=tkfont.Font(family='Segoe UI',size=12,weight='bold').measure('Артикул · 000000')+65
        columns=max(1,int((available+gap)//(preferred+gap)))
        width=(available-gap*(columns-1))/columns
        y=3
        for start in range(0,len(self.choices),columns):
            row=self.choices[start:start+columns]; labels=[]; text_height=24
            for key,label,selected,enabled,(color,ink),command in row:
                title,sep,count=label.rpartition(' · ')
                if not sep or not count.isdigit(): title=label; count=''
                probe=c.create_text(0,0,anchor='n',text=title,font=('Segoe UI',12,'bold'),width=max(1,width-24))
                bounds=c.bbox(probe); c.delete(probe)
                text_height=max(text_height,bounds[3]-bounds[1] if bounds else 24)
                labels.append((title,count))
            height=text_height+70
            for col,choice in enumerate(row):
                key,label,selected,enabled,(color,ink),command=choice
                title,count=labels[col]; x=col*(width+gap)
                fill='#142346' if selected else color; foreground='white' if selected else ink
                focused=c.focus_get()==c and start+col==self.focus_index
                rounded(c,x,y,width,height,14,fill=fill,outline='#199653' if focused else '',width=2)
                c.create_text(x+width/2,y+13,anchor='n',text=title,font=('Segoe UI',12,'bold'),fill=foreground,width=max(1,width-24))
                if count:
                    c.create_text(x+14,y+height-27,anchor='w',text=count,font=('Segoe UI',15,'bold'),fill=foreground)
                self.boxes.append((x,y,x+width,y+height,key))
                if key in self.action_buttons:
                    px=x+width-49; py=y+height-47
                    pending=bool(count and int(count)>0)
                    rounded(c,px,py,40,38,10,fill='#fff0f1' if pending else '#edf0f3',outline='')
                    self.printer_colors[key]='#dc2844' if pending else '#959eaa'
                    self.printer(px+9,py+8,self.printer_colors[key])
                    self.print_boxes.append((px,py,px+40,py+38,key))
            y+=height+gap
        c.configure(height=max(1,y))

    def printer(self,x,y,color):
        c=self.canvas
        c.create_rectangle(x+4,y,x+18,y+7,outline=color,width=2)
        rounded(c,x,y+6,22,12,3,fill=color,outline='')
        c.create_rectangle(x+4,y+13,x+18,y+23,fill='white',outline=color,width=2)
        c.create_line(x+7,y+17,x+15,y+17,fill=color,width=2)
        c.create_oval(x+16,y+9,x+18,y+11,fill='white',outline='')

    def click(self,event):
        self.canvas.focus_set()
        for left,top,right,bottom,key in self.print_boxes:
            if left<=event.x<=right and top<=event.y<=bottom:
                self.print_article(key); return
        for index,(left,top,right,bottom,key) in enumerate(self.boxes):
            if left<=event.x<=right and top<=event.y<=bottom:
                self.focus_index=index; self.buttons[key].invoke(); return

    def motion(self,event):
        self.canvas.configure(cursor='hand2' if any(x<=event.x<=r and y<=event.y<=b for x,y,r,b,_ in self.boxes) else '')
