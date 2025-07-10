"""
Ultra Email Validator PLUS — ttkbootstrap GUI  (stable, message‑box fix)

Dependencies:
    pip install ttkbootstrap dnspython matplotlib
"""

# ---------- std‑lib ----------
import datetime as dt
import difflib
import sqlite3
import csv
from concurrent.futures import ThreadPoolExecutor
import re

# ---------- 3rd‑party ----------
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import tkinter.messagebox as mb          # ← correct message‑box import
import dns.resolver
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt

# ---------- config ----------
ALLOWED_TLDS = {"com","org","net","in","co","edu","io","dev","tech","gov"}
COMMON_DOMAINS = [
    "gmail.com","yahoo.com","outlook.com","hotmail.com","icloud.com",
    "protonmail.com","aol.com","live.com"
]
DISPOSABLE_DOMAINS = {
    "mailinator.com","10minutemail.com","guerrillamail.com",
    "tempmail.com","trashmail.com"
}
EMAIL_REGEX = re.compile(r"^(?P<local>[a-z][\w\.]*?)@(?P<domain>[a-z]+\.[a-z]{2,})$")
DBFILE = "validation_log.db"

def init_db():
    with sqlite3.connect(DBFILE) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS validations(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts TEXT, email TEXT, valid INTEGER, mx_ok INTEGER)"""
        )
init_db()

# ---------- core ----------
def basic_validate(email:str):
    email=email.strip()
    if len(email)<6:
        return False,"Too short (min 6 chars).",None,None,None
    m=EMAIL_REGEX.match(email)
    if not m:
        return False,"Format error (lowercase, digits, . _ ).",None,None,None
    local,domain=m["local"],m["domain"]
    if any(c.isupper() for c in email):
        return False,"Upper‑case letters are not allowed.",None,None,None
    if domain in DISPOSABLE_DOMAINS:
        return False,"Disposable domains are blocked.",None,None,None
    if domain.split(".")[-1] not in ALLOWED_TLDS:
        return False,"TLD not allowed.",None,None,None
    suggestion=None
    if domain not in COMMON_DOMAINS:
        near=difflib.get_close_matches(domain,COMMON_DOMAINS,1,0.8)
        if near: suggestion=f"{local}@{near[0]}"
    return True,"",suggestion,local,domain

def domain_has_mx(domain):
    try: return bool(dns.resolver.resolve(domain,"MX"))
    except dns.exception.DNSException: return False

def log_db(email,valid,mx_ok):
    with sqlite3.connect(DBFILE) as con:
        con.execute(
            "INSERT INTO validations(ts,email,valid,mx_ok) VALUES(?,?,?,?)",
            (dt.datetime.now().isoformat(timespec="seconds"),email,int(valid),
             None if mx_ok is None else int(mx_ok)))
        con.commit()

# ---------- GUI ----------
class ChartWindow(tb.Toplevel):
    def __init__(self,master):
        super().__init__(master); self.title("Validation Statistics"); self.geometry("500x400")
        with sqlite3.connect(DBFILE) as con:
            v=con.execute("SELECT COUNT(*) FROM validations WHERE valid=1").fetchone()[0]
            i=con.execute("SELECT COUNT(*) FROM validations WHERE valid=0").fetchone()[0]
        fig,ax=plt.subplots(figsize=(5,4)); ax.bar(["Valid","Invalid"],[v,i])
        ax.set_ylabel("Count"); ax.set_title("Email Validation Results")
        for idx,val in enumerate([v,i]): ax.text(idx,val+0.1,str(val),ha="center")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        FigureCanvasTkAgg(fig,master=self).get_tk_widget().pack(fill=BOTH,expand=True)

class HistoryWindow(tb.Toplevel):
    def __init__(self,master):
        super().__init__(master); self.title("Validation History"); self.geometry("700x420")
        self.filter_var=tb.StringVar(value="All"); self.search_var=tb.StringVar()
        self._ui(); self._populate()

    def _ui(self):
        top=tb.Frame(self); top.pack(fill=X,pady=4,padx=4)
        tb.Label(top,text="Show:").pack(side=LEFT,padx=2)
        tb.Combobox(top,textvariable=self.filter_var,values=["All","Valid","Invalid"],
                    width=10,state="readonly").pack(side=LEFT,padx=4)
        self.filter_var.trace_add("write",lambda *_:self._populate())
        tb.Label(top,text="Search:").pack(side=LEFT,padx=(20,2))
        tb.Entry(top,textvariable=self.search_var,width=25).pack(side=LEFT,padx=4)
        self.search_var.trace_add("write",lambda *_:self._populate())
        tb.Button(top,text="Export CSV",command=self._export).pack(side=RIGHT,padx=4)
        tb.Button(top,text="Stats",command=lambda:ChartWindow(self)).pack(side=RIGHT,padx=4)
        cols=("ts","email","valid","mx")
        self.tree=tb.Treeview(self,columns=cols,show="headings",bootstyle=INFO,height=15)
        for c,w in zip(cols,(150,300,60,60)):
            self.tree.heading(c,text=c.upper()); self.tree.column(c,width=w,anchor=W)
        self.tree.pack(fill=BOTH,expand=True,padx=4,pady=4)

    def _query(self):
        q="SELECT ts,email,valid,mx_ok FROM validations"; params=[]; conds=[]
        if self.filter_var.get()=="Valid": conds.append("valid=1")
        elif self.filter_var.get()=="Invalid": conds.append("valid=0")
        if self.search_var.get():
            conds.append("email LIKE ?"); params.append(f"%{self.search_var.get()}%")
        if conds: q+=" WHERE "+ " AND ".join(conds)
        q+=" ORDER BY id DESC"
        with sqlite3.connect(DBFILE) as con: return con.execute(q,params).fetchall()

    def _populate(self):
        self.tree.delete(*self.tree.get_children())
        for ts,email,val,mx in self._query():
            self.tree.insert("",END,values=(ts,email,"✅" if val else "❌","✅" if mx else "—"))

    def _export(self):
        rows=self._query()
        fn=f"validation_export_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
        with open(fn,"w",newline="",encoding="utf-8") as f:
            csv.writer(f).writerows([("ts","email","valid","mx_ok"),*rows])
        mb.showinfo("Exported",f"Saved {len(rows)} rows to {fn}")   # ← fixed call

class AutoCompleteEntry(tb.Entry):
    def __init__(self,master,domains,**kw):
        super().__init__(master,**kw); self.domains=domains; self.lb=None
        self.bind("<KeyRelease>",self._check)
    def _check(self,_):
        text=self.get()
        if '@' in text:
            local,partial=text.split('@',1)
            matches=[d for d in self.domains if d.startswith(partial)]
            if matches and partial: self._show(matches,local)
            else: self._hide()
        else: self._hide()
    def _show(self,opts,local):
        self._hide()
        self.lb=lb=tb.Listbox(self.master,height=min(5,len(opts)),bootstyle=INFO)
        for m in opts: lb.insert(END,f"{local}@{m}")
        bbox=self.bbox("insert")
        (lb.place(x=bbox[0],y=bbox[1]+bbox[3]+5) if bbox else
         lb.place(relx=0,rely=1,anchor="nw"))
        lb.bind("<<ListboxSelect>>",lambda e:self._select(lb))
    def _select(self,lb):
        self.delete(0,END); self.insert(0,lb.get(lb.curselection())); self.icursor(END); self._hide()
    def _hide(self): 
        if self.lb: self.lb.destroy(); self.lb=None

class App(tb.Window):
    def __init__(self):
        super().__init__(themename="flatly")
        self.title("Ultra Email Validator PLUS"); self.geometry("580x320"); self.resizable(False,False)
        self.executor=ThreadPoolExecutor(max_workers=4)
        self.dark=tb.BooleanVar(value=False)
        self._ui(); self._theme(first=True)

    def _ui(self):
        pad={"padx":12,"pady":8}
        tb.Label(self,text="Enter an e‑mail address:",font=("Segoe UI",12,"bold")).pack(**pad)
        row=tb.Frame(self); row.pack(**pad)
        self.entry=AutoCompleteEntry(row,COMMON_DOMAINS,width=46,font=("Segoe UI",12))
        self.entry.pack(side=LEFT,ipady=3)
        self.entry.bind("<Return>",lambda e:self._validate())
        self.entry.bind("<KeyRelease>",lambda e:self._live())
        import tkinter as tk
        self.lamp=tk.Label(row,text="●",font=("Segoe UI",14)); self.lamp.pack(side=LEFT,padx=6)
        btn=tb.Frame(self); btn.pack(**pad)
        tb.Button(btn,text="Validate Now",command=self._validate,width=18).pack(side=LEFT,padx=6)
        tb.Button(btn,text="History",command=lambda:HistoryWindow(self),width=10).pack(side=LEFT,padx=6)
        self.msg=tb.Label(self,font=("Segoe UI",10)); self.msg.pack(**pad)
        self.sugg=tb.Label(self,font=("Segoe UI",10,"italic"),bootstyle=WARNING); self.sugg.pack()
        tb.Checkbutton(self,text="Dark mode",variable=self.dark,command=self._theme).pack()
        tb.Label(self,text="Data stored in validation_log.db",
                 font=("Segoe UI",8,"italic")).pack(side=BOTTOM,pady=4)

    def _live(self,*_): self.lamp.configure(fg=("green" if basic_validate(self.entry.get())[0] else "red"))

    def _validate(self):
        email=self.entry.get().strip()
        valid,err,sug,_,domain=basic_validate(email); self._live()
        if not valid:
            self.msg.configure(text=err,bootstyle=DANGER); self.sugg.configure(text=f"Did you mean {sug} ?" if sug else "")
            log_db(email,False,None); self._refresh_hist(); return
        self.msg.configure(text="Checking MX records…",bootstyle=INFO); self.sugg.configure(text="")
        fut=self.executor.submit(domain_has_mx,domain)
        fut.add_done_callback(lambda f:self.after(0,self._mx_done,email,f.result()))

    def _mx_done(self,email,mx_ok):
        if mx_ok:
            self.msg.configure(text="Valid! MX record found ✅",bootstyle=SUCCESS); self.lamp.configure(fg="green")
        else:
            self.msg.configure(text="Domain has NO MX record ❌",bootstyle=DANGER); self.lamp.configure(fg="red")
        log_db(email,True,mx_ok); self._refresh_hist()

    def _refresh_hist(self):
        for w in self.winfo_children():
            if isinstance(w,HistoryWindow): w._populate()

    def _theme(self,first=False):
        self.style.theme_use("darkly" if self.dark.get() else "flatly")
        self.lamp.configure(bg=self.cget("background"))
        if first: self.after(100,self._live)

if __name__=="__main__":
    App().mainloop()
