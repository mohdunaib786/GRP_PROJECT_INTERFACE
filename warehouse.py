#!/usr/bin/env python3
"""Smart Warehouse Interface (Tkinter, standard library only).
8 aisles x 8 bays, 4 AMRs, orders, restocking, send to charge, event log.
Run:  python warehouse.py
"""
import math
import random
import time
import tkinter as tk
from tkinter import ttk

BG, PANEL, INK = "#e8eae8", "#f6f7f6", "#1c2631"
BLUE, AMBER, GREEN, RED, FLOOR = "#2457a6", "#d98e04", "#25804f", "#c43d2c", "#dfe2df"
ITEMS = ["Shipping carton M", "Pallet wrap", "Label rolls", "Bubble mailers", "Tape 48mm",
         "Pallet collars", "Foam inserts", "Cable ties", "Gloves L", "Sealed bins",
         "Scanner batteries", "Strapping band", "Corner guards", "Thermal paper",
         "Return bags", "Mixed hardware"]
COL = [40 + 80 * i for i in range(8)]
BAYS_PER_AISLE, W, H, TOP, GAP, DOCK, AX, CHG = 8, 44, 34, 46, 41, 425, 18, 662


def blend(a, b, t):
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))


def sign(v):
    return (v > 0) - (v < 0)


class Bay:
    def __init__(self, c, r, item, cap, qty):
        self.id = f"{'ABCDEFGH'[c]}-{r + 1:02d}"
        self.c, self.r, self.item, self.cap, self.qty = c, r, item, cap, qty
        self.warned, self.rect = False, None

    @property
    def low(self):
        return self.qty / self.cap < 0.15


class Robot:
    def __init__(self, i, battery):
        self.n = f"R{i + 1}"
        self.x = self.tx = COL[i * 2] - AX
        self.y = self.ty = DOCK
        self.bat, self.st, self.job = battery, "idle", "Idle at dock"
        self.wait, self.bay, self.full = 0, None, False


class App:
    def __init__(self, root):
        self.root = root
        root.title("Smart Warehouse - Floor control")
        root.configure(bg=BG)
        root.geometry("1280x900")
        random.seed(7)
        self.bays = []
        for c in range(8):
            for r in range(BAYS_PER_AISLE):
                cap = random.choice([120, 200, 400, 600])
                fill = random.random() * 0.12 if random.random() < 0.14 else 0.2 + random.random() * 0.8
                self.bays.append(Bay(c, r, random.choice(ITEMS), cap, round(cap * fill)))
        self.robots = [Robot(i, b) for i, b in enumerate([86, 64, 23, 92])]
        self.orders = [["SO-4821", "Hartog Retail", "12 lines", "Picking", 60],
                       ["SO-4822", "Nord Parcel", "5 lines", "Packing", 85],
                       ["SO-4823", "Delft Supplies", "24 lines", "Queued", 5],
                       ["SO-4824", "Bakker & Zn", "8 lines", "Picking", 35],
                       ["SO-4825", "Maas Logistics", "16 lines", "Queued", 0],
                       ["SO-4819", "Visser BV", "3 lines", "Ready to ship", 100]]
        self.next_order, self.sel, self.toast_job = 4826, None, None
        self.build_ui()
        self.log("Shift started. 8 aisles, 64 bays, 4 robots online.", GREEN)
        self.refresh_all()
        self.step()
        self.slow_tick()

    # ---------- UI ----------
    def build_ui(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("Treeview", rowheight=24, font=("Segoe UI", 10))
        st.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(head, text="Warehouse floor", bg=BG, fg=INK, font=("Segoe UI", 22, "bold")).pack(side="left")
        self.kpis = {}
        for key, label in [("orders", "Orders open"), ("picks", "Picks per hour"),
                           ("robots", "Robots active"), ("low", "Bays running low")]:
            f = tk.Frame(head, bg=BG)
            f.pack(side="right", padx=14)
            v = tk.StringVar(value="0")
            tk.Label(f, textvariable=v, bg=BG, fg=INK, font=("Segoe UI", 20, "bold")).pack(anchor="e")
            tk.Label(f, text=label, bg=BG, fg="#5d6a75").pack(anchor="e")
            self.kpis[key] = v
        tk.Frame(self.root, bg=INK, height=3).pack(fill="x", padx=16)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=8)
        left = tk.Frame(body, bg=PANEL, bd=1, relief="solid")
        left.pack(side="left", fill="both")
        self.canvas = tk.Canvas(left, width=700, height=450, bg=FLOOR, highlightthickness=0)
        self.canvas.pack(padx=8, pady=8)
        self.draw_map()
        det = tk.Frame(left, bg=PANEL)
        det.pack(fill="x", padx=8, pady=(0, 8))
        self.detail = tk.StringVar(value="No bay selected. Click a rack on the map.")
        tk.Label(det, textvariable=self.detail, bg=PANEL, fg=INK, justify="left",
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        self.qty_var = tk.StringVar(value="50")
        self.btn_add = ttk.Button(det, text="Add stock", command=self.add_stock)
        self.btn_add.pack(side="right")
        ttk.Entry(det, textvariable=self.qty_var, width=6).pack(side="right", padx=6)
        self.btn_send = ttk.Button(det, text="Send nearest robot", command=self.send_nearest)
        self.btn_send.pack(side="right", padx=6)

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)
        # robots
        t1 = tk.Frame(nb, bg=PANEL)
        nb.add(t1, text="Robots")
        self.rtree = ttk.Treeview(t1, columns=("n", "bat", "job"), show="headings", height=6, selectmode="browse")
        for c, t, w in [("n", "Robot", 60), ("bat", "Battery", 70), ("job", "Task", 220)]:
            self.rtree.heading(c, text=t)
            self.rtree.column(c, width=w)
        self.rtree.pack(fill="x", padx=8, pady=8)
        for r in self.robots:
            self.rtree.insert("", "end", iid=r.n, values=(r.n, "", ""))
        ttk.Button(t1, text="Send selected robot to charge", command=self.charge_selected).pack(padx=8, anchor="w")
        # orders
        t2 = tk.Frame(nb, bg=PANEL)
        nb.add(t2, text="Orders")
        ttk.Button(t2, text="Place an order", command=self.order_dialog).pack(padx=8, pady=8, anchor="w")
        self.otree = ttk.Treeview(t2, columns=("id", "cust", "detail", "status", "pct"), show="headings", height=9)
        for c, t, w in [("id", "Order", 70), ("cust", "Customer", 110), ("detail", "Items", 110),
                        ("status", "Status", 90), ("pct", "Done", 50)]:
            self.otree.heading(c, text=t)
            self.otree.column(c, width=w)
        self.otree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        # alerts
        t3 = tk.Frame(nb, bg=PANEL)
        nb.add(t3, text="Alerts")
        ttk.Button(t3, text="Restock all low bays", command=self.restock_all).pack(padx=8, pady=8, anchor="w")
        self.alerts = tk.Listbox(t3, height=12, bd=0, font=("Segoe UI", 10))
        self.alerts.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        lf = tk.LabelFrame(bottom, text="Event log", bg=PANEL, fg=INK)
        lf.pack(side="left", fill="both", expand=True)
        self.logbox = tk.Listbox(lf, height=9, bd=0, font=("Consolas", 10))
        self.logbox.pack(fill="both", expand=True, padx=6, pady=6)
        inf = tk.LabelFrame(bottom, text="Inventory", bg=PANEL, fg=INK)
        inf.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tools = tk.Frame(inf, bg=PANEL)
        tools.pack(fill="x", padx=6, pady=6)
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self.refresh_inv())
        ttk.Entry(tools, textvariable=self.q, width=24).pack(side="left")
        self.only_low = tk.BooleanVar()
        ttk.Checkbutton(tools, text="Low stock only", variable=self.only_low, command=self.refresh_inv).pack(side="left", padx=8)
        self.inv_count = tk.StringVar()
        tk.Label(tools, textvariable=self.inv_count, bg=PANEL, fg="#5d6a75").pack(side="right")
        self.inv = ttk.Treeview(inf, columns=("bay", "item", "qty", "cap", "status"), show="headings", height=8)
        for c, t, w in [("bay", "Bay", 60), ("item", "Item", 150), ("qty", "On hand", 70), ("cap", "Capacity", 70), ("status", "Status", 90)]:
            self.inv.heading(c, text=t)
            self.inv.column(c, width=w)
        self.inv.tag_configure("low", foreground=AMBER)
        self.inv.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.inv.bind("<<TreeviewSelect>>", self.on_inv_select)
        self.status = tk.StringVar()
        tk.Label(self.root, textvariable=self.status, bg=INK, fg="white", anchor="w", padx=10).pack(fill="x", side="bottom")

    def draw_map(self):
        c = self.canvas
        for i, x in enumerate(COL):
            c.create_line(x - AX, 20, x - AX, DOCK, fill="#aab1ad", dash=(5, 5))
            c.create_text(x + W / 2, 34, text=f"Aisle {'ABCDEFGH'[i]}", fill="#5d6a75", font=("Segoe UI", 8, "bold"))
        c.create_line(10, DOCK, 690, DOCK, fill="#aab1ad", dash=(5, 5))
        c.create_rectangle(10, 432, 690, 446, fill=INK, outline=INK)
        c.create_text(350, 439, text="Packing and dispatch docks", fill="white", font=("Segoe UI", 8, "bold"))
        for b in self.bays:
            y = TOP + b.r * GAP
            b.rect = c.create_rectangle(COL[b.c], y, COL[b.c] + W, y + H, outline=INK, width=1)
            c.tag_bind(b.rect, "<Button-1>", lambda e, b=b: self.select(b))
            c.tag_bind(b.rect, "<Enter>", lambda e: c.config(cursor="hand2"))
            c.tag_bind(b.rect, "<Leave>", lambda e: c.config(cursor=""))
            self.paint(b)
        for r in self.robots:
            r.oval = c.create_oval(0, 0, 0, 0, fill=INK, outline="white", width=2)
            r.label = c.create_text(0, 0, text=r.n, fill="white", font=("Segoe UI", 7, "bold"))
            self.place(r)

    def place(self, r):
        self.canvas.coords(r.oval, r.x - 9, r.y - 9, r.x + 9, r.y + 9)
        self.canvas.coords(r.label, r.x, r.y)

    def paint(self, b):
        fill = AMBER if b.low else blend(FLOOR, BLUE, 0.25 + 0.65 * b.qty / b.cap)
        self.canvas.itemconfig(b.rect, fill=fill)

    # ---------- helpers ----------
    def log(self, msg, color=INK):
        self.logbox.insert(0, f"{time.strftime('%H:%M:%S')}  {msg}")
        self.logbox.itemconfig(0, fg=color)
        if self.logbox.size() > 80:
            self.logbox.delete(80, "end")

    def toast(self, msg):
        self.status.set(msg)
        if self.toast_job:
            self.root.after_cancel(self.toast_job)
        self.toast_job = self.root.after(2800, lambda: self.status.set(""))

    def check(self, b):
        if b.low and not b.warned:
            b.warned = True
            self.log(f"Bay {b.id} is running low ({b.qty} left)", AMBER)

    # ---------- robots ----------
    def go(self, r, b, why):
        r.tx, r.ty = COL[b.c] - AX, TOP + b.r * GAP + H / 2
        r.job, r.st, r.wait, r.bay = f"{why} {b.id}", "moving", 0, b
        self.log(f"{r.n} {why.lower()} bay {b.id}")

    def charge(self, r, full):
        r.st, r.full, r.job = "charging", full, "Charging at dock"
        r.tx, r.ty = CHG - (int(r.n[1:]) - 1) * 18, DOCK
        self.log(f"{r.n} sent to charge at {round(r.bat)}%" + (" (full charge)" if full else ""), BLUE)

    def step(self):
        for r in self.robots:
            if r.bat < 20 and r.st != "charging":
                self.charge(r, False)
            dx, dy, sp = r.tx - r.x, r.ty - r.y, 2.2
            if abs(dx) > 2 and abs(r.y - DOCK) > 2:
                r.y += sign(DOCK - r.y) * sp
            elif abs(dx) > 2:
                r.x += sign(dx) * sp
            elif abs(dy) > 2:
                r.y += sign(dy) * sp
            else:
                self.arrive(r)
            self.place(r)
        self.root.after(50, self.step)

    def arrive(self, r):
        if r.st == "charging":
            r.bat = min(100, r.bat + 0.15)
            r.job = f"Charging {round(r.bat)}%"
            if r.bat >= (100 if r.full else 60):
                r.st, r.full, r.job = "idle", False, "Idle at dock"
                self.log(f"{r.n} finished charging at {round(r.bat)}%", GREEN)
        elif r.st == "moving":
            r.st, r.wait, r.job = "picking", 40, f"Picking at {r.bay.id}"
        elif r.st == "picking":
            r.wait -= 1
            if r.wait <= 0:
                if r.bay.qty > 0:
                    r.bay.qty -= 1
                    self.paint(r.bay)
                    self.log(f"{r.n} picked 1 unit from {r.bay.id} ({r.bay.item})")
                    self.check(r.bay)
                r.st, r.tx, r.ty, r.job = "back", r.x, DOCK, "Returning to dock"
        elif r.st == "back":
            r.st, r.job, r.wait = "idle", "Idle at dock", 30
        elif r.st == "idle":
            r.wait -= 1
            if r.wait <= 0:
                b = random.choice(self.bays)
                if b.qty > 0 and r.bat > 25:
                    self.go(r, b, "Heading to")
                r.wait = 20

    def send_nearest(self):
        b = self.sel
        free = [r for r in self.robots if r.st == "idle" and r.bat > 25]
        if not b:
            return self.toast("Select a bay first.")
        if not free:
            return self.toast("All robots are busy. Try again in a moment.")
        r = min(free, key=lambda r: abs(r.x - COL[b.c]))
        self.go(r, b, "Dispatched to")
        self.toast(f"{r.n} sent to bay {b.id}")

    def charge_selected(self):
        s = self.rtree.selection()
        if not s:
            return self.toast("Select a robot in the list first.")
        r = next(x for x in self.robots if x.n == s[0])
        if r.st == "charging":
            return self.toast(f"{r.n} is already charging")
        self.charge(r, True)
        self.toast(f"{r.n} is heading to charge")

    # ---------- stock and orders ----------
    def select(self, b):
        if self.sel:
            self.canvas.itemconfig(self.sel.rect, width=1)
        self.sel = b
        self.canvas.itemconfig(b.rect, width=3)
        self.qty_var.set(str(max(1, min(50, b.cap - b.qty))))
        self.refresh_detail()
        if self.inv.exists(b.id):
            self.inv.selection_set(b.id)
            self.inv.see(b.id)

    def on_inv_select(self, _):
        s = self.inv.selection()
        if s:
            b = next(x for x in self.bays if x.id == s[0])
            if b is not self.sel:
                self.select(b)

    def refresh_detail(self):
        b = self.sel
        if b:
            pct = round(100 * b.qty / b.cap)
            self.detail.set(f"Bay {b.id}  {b.item}\n{b.qty} of {b.cap} units ({pct}%)  "
                            f"{'LOW STOCK' if b.low else 'Healthy'}")

    def add_stock(self):
        b = self.sel
        if not b:
            return self.toast("Select a bay first.")
        room = b.cap - b.qty
        try:
            n = int(self.qty_var.get())
        except ValueError:
            return self.toast("Enter how many units to add.")
        if not room:
            return self.toast(f"Bay {b.id} is already full.")
        if n < 1:
            return self.toast("Enter how many units to add.")
        n = min(n, room)
        b.qty += n
        b.warned = False
        self.paint(b)
        self.log(f"Restocked bay {b.id}: +{n} {b.item}", GREEN)
        self.toast(f"Added {n} units to bay {b.id}")
        self.refresh_all()

    def restock_all(self):
        low = [b for b in self.bays if b.low]
        for b in low:
            b.qty, b.warned = round(b.cap * 0.8), False
            self.paint(b)
        if low:
            self.log(f"Restock request: {len(low)} low bays refilled to 80%", GREEN)
            self.toast(f"{len(low)} bays restocked")
        self.refresh_all()

    def order_dialog(self):
        d = tk.Toplevel(self.root)
        d.title("Place an order")
        d.transient(self.root)
        d.grab_set()
        d.configure(padx=16, pady=14)
        cust, item, qty = tk.StringVar(value="Hartog Retail"), tk.StringVar(value=ITEMS[0]), tk.StringVar(value="10")
        for i, (lab, w) in enumerate([("Customer", ttk.Entry(d, textvariable=cust, width=30)),
                                      ("Item", ttk.Combobox(d, textvariable=item, values=ITEMS, state="readonly", width=28)),
                                      ("Quantity", ttk.Spinbox(d, textvariable=qty, from_=1, to=999, width=10))]):
            ttk.Label(d, text=lab).grid(row=i * 2, column=0, sticky="w", pady=(8, 0))
            w.grid(row=i * 2 + 1, column=0, sticky="w")
        err = tk.Label(d, fg=RED, text="", wraplength=260, justify="left")
        err.grid(row=6, column=0, sticky="w", pady=6)

        def submit():
            try:
                q = int(qty.get())
            except ValueError:
                q = 0
            have = [b for b in self.bays if b.item == item.get()]
            total = sum(b.qty for b in have)
            if q < 1:
                return err.config(text="Enter a quantity of at least 1.")
            if q > total:
                return err.config(text=f"Only {total} units of {item.get()} are on hand. "
                                       "Lower the quantity or restock first.")
            need = q
            for b in sorted(have, key=lambda b: -b.qty):
                t = min(b.qty, need)
                b.qty -= t
                need -= t
                self.paint(b)
                self.check(b)
            oid, name = f"SO-{self.next_order}", cust.get().strip() or "Walk-in"
            self.next_order += 1
            self.orders.insert(0, [oid, name, f"{q} x {item.get()}", "Queued", 0])
            self.log(f"Order {oid} placed by {name}: {q} x {item.get()}", BLUE)
            self.toast(f"Order {oid} placed")
            d.destroy()
            self.refresh_all()

        row = tk.Frame(d)
        row.grid(row=7, column=0, sticky="e")
        ttk.Button(row, text="Cancel", command=d.destroy).pack(side="left", padx=6)
        ttk.Button(row, text="Place order", command=submit).pack(side="left")

    def advance_orders(self):
        open_ = sorted((o for o in self.orders if o[4] < 100), key=lambda o: o[0])[:2]
        for o in open_:
            was = o[3]
            o[4] = min(100, o[4] + 4 + random.randint(0, 6))
            o[3] = "Queued" if o[4] == 0 else "Picking" if o[4] <= 60 else "Packing" if o[4] < 100 else "Ready to ship"
            if o[3] != was:
                self.log(f"Order {o[0]}: {o[3].lower()}", GREEN if o[4] == 100 else INK)

    # ---------- refresh ----------
    def slow_tick(self):
        for r in self.robots:
            if r.st != "charging":
                r.bat = max(0, r.bat - 0.4)
        self.advance_orders()
        self.refresh_all()
        self.root.after(2000, self.slow_tick)

    def refresh_inv(self):
        q, only = self.q.get().strip().lower(), self.only_low.get()
        self.inv.delete(*self.inv.get_children())
        n = 0
        for b in self.bays:
            if (only and not b.low) or (q and q not in b.id.lower() and q not in b.item.lower()):
                continue
            self.inv.insert("", "end", iid=b.id, tags=("low",) if b.low else (),
                            values=(b.id, b.item, b.qty, b.cap, "Low stock" if b.low else "Healthy"))
            n += 1
        self.inv_count.set(f"{n} of {len(self.bays)} bays")
        if self.sel and self.inv.exists(self.sel.id):
            self.inv.selection_set(self.sel.id)

    def refresh_all(self):
        active = sum(r.st not in ("idle", "charging") for r in self.robots)
        self.kpis["orders"].set(sum(o[4] < 100 for o in self.orders))
        self.kpis["picks"].set(round(310 + math.sin(time.time() / 9) * 14))
        self.kpis["robots"].set(f"{active} of {len(self.robots)}")
        self.kpis["low"].set(sum(b.low for b in self.bays))
        for r in self.robots:
            self.rtree.item(r.n, values=(r.n, f"{round(r.bat)}%", r.job))
        for o in reversed(self.orders):
            vals = (o[0], o[1], o[2], o[3], f"{o[4]}%")
            if self.otree.exists(o[0]):
                self.otree.item(o[0], values=vals)
            else:
                self.otree.insert("", 0, iid=o[0], values=vals)
        self.alerts.delete(0, "end")
        for r in self.robots:
            if r.bat < 30 and r.st != "charging":
                self.alerts.insert("end", f"URGENT  {r.n} battery low. Send to charge.")
        for b in [b for b in self.bays if b.low][:12]:
            self.alerts.insert("end", f"Bay {b.id} almost empty: {b.item}, {b.qty} left.")
        if self.alerts.size() == 0:
            self.alerts.insert("end", "No alerts. Everything is running normally.")
        self.refresh_detail()
        self.refresh_inv()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
