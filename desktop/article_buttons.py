"""Видимые кнопки артикулов в одну или несколько строк."""
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

BG = '#f4f6fb'


class ArticleButtons(ttk.Frame):
    def __init__(self, parent, empty='Артикулов в заявках пока нет', rows=1, with_actions=False, wrap=False):
        super().__init__(parent)
        self.empty = empty; self.buttons = {}; self.commands = {}; self.keys = None
        self.rows=max(1,rows)
        self.wrap=wrap; self.flow_columns=0
        self.with_actions=with_actions; self.action_buttons={}; self.action_commands={}; self.cells={}
        self.columnconfigure(1, weight=1)
        self.left = ttk.Button(self, text='‹', width=2, command=lambda: self.move(-1))
        self.left.grid(row=0, column=0, sticky='ns', padx=(0, 4))
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0, height=36, width=80)
        self.canvas.grid(row=0, column=1, sticky='ew')
        self.right = ttk.Button(self, text='›', width=2, command=lambda: self.move(1))
        self.right.grid(row=0, column=2, sticky='ns', padx=(4, 0))
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, anchor='nw', window=self.content)
        self.content.bind('<Configure>', self.layout)
        self.canvas.bind('<Configure>', self.layout)
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.configure(xscrollincrement=40, xscrollcommand=self.scrolled)
        if self.wrap:
            self.left.grid_remove(); self.right.grid_remove()

    def set_choices(self, choices):
        """(key, label, selected, enabled, (background, foreground), command)."""
        keys = tuple(value[0] for value in choices)
        if keys != self.keys:
            for child in self.content.winfo_children(): child.destroy()
            self.buttons = {}; self.action_buttons={}; self.cells={}; self.keys = keys
            font=tkfont.Font(family='Segoe UI',size=10)
            widths=[font.measure('✓ '+value[1])+28+(128 if self.with_actions and value[0] not in ((),None) else 0) for value in choices]
            row_count=min(self.rows,len(keys)); row=0; used=0
            target=sum(widths)/max(1,row_count)
            lines=[] if self.wrap else [ttk.Frame(self.content) for _ in range(row_count)]
            for line in lines: line.pack(anchor='w')
            for index,key in enumerate(keys):
                remaining=len(keys)-index; remaining_rows=row_count-row-1
                if row<row_count-1 and used and (used+widths[index]>target or remaining==remaining_rows):
                    row+=1; used=0
                used+=widths[index]
                has_action=self.with_actions and key not in ((),None)
                cell=tk.Frame(self.content if self.wrap else lines[row],bd=1 if has_action else 0,relief='solid',padx=4 if has_action else 0,pady=4 if has_action else 0)
                if not self.wrap: cell.pack(side='left',padx=(0,10),pady=3)
                self.cells[key]=cell
                button = tk.Button(cell, font=('Segoe UI', 10), relief='flat' if has_action else 'solid', bd=0 if has_action else 1,
                                   padx=10, pady=5, takefocus=True, cursor='hand2',
                                   command=lambda k=key: self.commands[k]())
                button.pack(side='top' if self.wrap else 'left',fill='x' if self.wrap else 'none')
                button.bind('<MouseWheel>', self.wheel)
                self.buttons[key] = button
                if has_action:
                    action=tk.Button(cell,text='Напечатать все',font=('Segoe UI',9),relief='solid',bd=1,
                                     padx=6,pady=6,bg='white',fg='#142346',cursor='hand2',
                                     command=lambda k=key:self.action_commands[k]())
                    action.pack(side='top' if self.wrap else 'left',fill='x' if self.wrap else 'none',padx=0 if self.wrap else (6,0),pady=(3,0) if self.wrap else 0)
                    action.bind('<MouseWheel>',self.wheel)
                    self.action_buttons[key]=action
            if not keys: ttk.Label(self.content, text=self.empty, foreground='#737d94').pack(pady=8)
        self.commands = {key: command for key, _, _, _, _, command in choices}
        for key, label, selected, enabled, (color, ink), _ in choices:
            self.cells[key].configure(bg='#142346' if selected else color)
            self.buttons[key].configure(text=('✓ ' if selected else '') + label,
                bg='#142346' if selected else color, fg='white' if selected else ink,
                activebackground='#294576' if selected else color,
                activeforeground='white' if selected else ink,
                disabledforeground='#7e8796', state='normal' if enabled else 'disabled')
        self.after_idle(self.layout)

    def set_actions(self, actions):
        self.action_commands={key:command for key,(_,command) in actions.items()}
        for key,button in self.action_buttons.items():
            button.configure(state='normal' if actions.get(key,(False,None))[0] else 'disabled')

    def layout(self, _=None):
        if not self.winfo_exists(): return
        if self.wrap:
            available=max(1,self.canvas.winfo_width())
            preferred=tkfont.Font(family='Segoe UI',size=10).measure('Напечатать все')+80
            columns=max(1,available//preferred)
            cell_width=max(1,available//columns)
            for column in range(max(columns,self.flow_columns)):
                self.content.columnconfigure(column,weight=1 if column<columns else 0,minsize=0)
            self.flow_columns=columns
            self.canvas.itemconfigure(self.window,width=available)
            for index,key in enumerate(self.keys or ()):
                self.buttons[key].configure(wraplength=max(1,cell_width-40))
                self.cells[key].grid(row=index//columns,column=index%columns,sticky='nsew',padx=(0,8),pady=3)
            self.canvas.configure(height=self.content.winfo_reqheight(),scrollregion=(0,0,available,self.content.winfo_reqheight()))
            self.canvas.xview_moveto(0)
            return
        width = self.content.winfo_reqwidth()
        self.canvas.configure(height=self.content.winfo_reqheight(),
                              scrollregion=(0, 0, width, self.content.winfo_reqheight()))
        if width <= self.canvas.winfo_width(): self.canvas.xview_moveto(0)

    def scrolled(self, start, end):
        if self.wrap: return
        self.left.configure(state='disabled' if float(start) <= 0 else 'normal')
        self.right.configure(state='disabled' if float(end) >= 1 else 'normal')

    def move(self, direction): self.canvas.xview_scroll(direction * 5, 'units')

    def wheel(self, event):
        if self.wrap: return
        self.move(-1 if event.delta > 0 else 1)
        return 'break'
