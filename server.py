"""Arena server: python server.py"""
import sys, asyncio, json, os, random, re, sqlite3, hmac, hashlib, secrets, time
from urllib.parse import parse_qsl
from aiohttp import web
import bot, wallet, durak, admin

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.getenv("PORT", "3000")); TOKEN = bot.TOKEN
BOT_NAME = ""; TURN = 40
DURAK = {"durak": False, "perev": True}                       # perev = perevodnoy durak
GAMES = {"chess", "checkers", "connect4", "gomoku", "reversi", "ttt"} | set(DURAK)
STAKES = {"star": [10, 50, 100, 250], "ton": [0.1, 0.25, 0.5, 1]}

db = sqlite3.connect(os.getenv("DB_PATH") or os.path.join(BASE, "arena.db"), check_same_thread=False); db.row_factory = sqlite3.Row
db.executescript("""CREATE TABLE IF NOT EXISTS users(uid TEXT PRIMARY KEY,name TEXT,star REAL DEFAULT 0,
ton REAL DEFAULT 0,games INT DEFAULT 0,wins INT DEFAULT 0,refs INT DEFAULT 0,ref_by TEXT,guest INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS tx(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT,ts INT,uid TEXT,kind TEXT,cur TEXT,amt REAL,note TEXT);
CREATE TABLE IF NOT EXISTS games(id INTEGER PRIMARY KEY AUTOINCREMENT,ts INT,g TEXT,cur TEXT,stake REAL,p0 TEXT,p1 TEXT,w INT);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY,v TEXT);""")
for col in ("banned INT DEFAULT 0", "created INT DEFAULT 0", "last INT DEFAULT 0"):
    try: db.execute("ALTER TABLE users ADD COLUMN " + col)
    except sqlite3.OperationalError: pass
db.commit()
conns, queues, ACTIVE = {}, {}, []

# ---- sozlamalar (admin paneldan o'zgaradi, kv jadvalida saqlanadi)
CFG = {"fee": 0.10, "test": 1 if os.getenv("TEST_MODE") == "1" else 0, "maint": 0, "notice": ""}
for r in db.execute("SELECT k,v FROM kv"):
    if r["k"] in CFG: CFG[r["k"]] = type(CFG[r["k"]])(float(r["v"])) if r["k"] != "notice" else r["v"]
def setcfg(k, v):
    CFG[k] = v; db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, str(v))); db.commit()
def logx(uid, kind, cur, amt, note=""):
    db.execute("INSERT INTO log(ts,uid,kind,cur,amt,note) VALUES(?,?,?,?,?,?)", (int(time.time()), uid, kind, cur, amt, note)); db.commit()

def user(uid):
    r = db.execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
    return dict(r) if r else None
def pub(u): return {k: u[k] for k in ("star", "ton", "games", "wins", "refs")}
def add(uid, cur, amt):
    assert cur in ("star", "ton")
    db.execute(f"UPDATE users SET {cur}=ROUND({cur}+?,2) WHERE uid=?", (amt, uid)); db.commit()

class C:
    def __init__(s, ws): s.ws = ws; s.uid = None; s.name = ""; s.q = None; s.t = None; s.seat = 0
async def send(c, o):
    if c is None: return
    try: await c.ws.send_str(json.dumps(o))
    except Exception: pass
async def bcast(o):
    for c in list(conns.values()): await send(c, o)

def verify(m):
    init = m.get("init") or ""
    if TOKEN and init:
        d = dict(parse_qsl(init)); h = d.pop("hash", "")
        chk = "\n".join(f"{k}={d[k]}" for k in sorted(d))
        key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        fresh = time.time() - int(d.get("auth_date") or 0) < 86400
        if fresh and hmac.compare_digest(hmac.new(key, chk.encode(), hashlib.sha256).hexdigest(), h):
            u = json.loads(d.get("user", "{}"))
            if u.get("id"): return "tg%s" % u["id"], u.get("first_name", "Player"), 0
    return "g" + re.sub(r"\W", "", str(m.get("uid", "x")))[:20], "", 1   # mehmon: depozit/stavka yo'q

async def credit(uid, cur, amt, txid):
    if not user(uid) or db.execute("SELECT 1 FROM tx WHERE id=?", (txid,)).fetchone(): return
    db.execute("INSERT INTO tx VALUES(?)", (txid,)); db.commit(); add(uid, cur, amt); logx(uid, "deposit", cur, amt, txid[:24])
    c = conns.get(uid)
    if c: await send(c, {"t": "dep", "ok": True, "user": pub(user(uid)), cur: amt})

def stop(t):
    tm = t.get("tm")
    if tm and tm is not asyncio.current_task(): tm.cancel()

async def settle(t, w):
    if t["done"]: return
    t["done"] = True; stop(t); cur, st = t["cur"], t["stake"]
    if t in ACTIVE: ACTIVE.remove(t)
    ids = [("bot" if u is None else u) for u in t["u"]]
    db.execute("INSERT INTO games(ts,g,cur,stake,p0,p1,w) VALUES(?,?,?,?,?,?,?)", (int(time.time()), t["g"], cur, st, ids[0], ids[1], w)); db.commit()
    if cur != "free" and w != -1: logx(t["u"][w], "fee", cur, round(st * 2 * CFG["fee"], 2), t["g"])
    for i, uid in enumerate(t["u"]):
        if uid is None: continue
        amt = 0
        if cur != "free":
            amt = st if w == -1 else round(st * 2 * (1 - CFG["fee"]), 2) if w == i else 0
            if amt: add(uid, cur, amt)
        if not t.get("bot"):
            db.execute("UPDATE users SET games=games+1,wins=wins+? WHERE uid=?", (1 if w == i else 0, uid)); db.commit()
        c = conns.get(uid)
        if c: await send(c, {"t": "paid", "user": pub(user(uid)), "amount": amt})

# ---------- durak (server hakam) ----------
async def dpush(t, bad=None):
    dk = t["dk"]
    for i, p in enumerate(t["p"]):
        if p: await send(p, {"t": "dv", "v": dk.view(i), "left": TURN, "bad": bad == i})
    if dk.winner is not None: return await settle(t, dk.winner)
    old = t.get("tm")
    if old and old is not asyncio.current_task(): old.cancel()
    t["tm"] = asyncio.create_task(tick(t))

async def tick(t):
    dk = t["dk"]; w = dk.waiting()
    if w is None or t["done"]: return
    if t["p"][w] is None: await asyncio.sleep(random.uniform(.9, 1.7)); a = dk.bot(w)   # bot o'ylaydi
    else: await asyncio.sleep(TURN); a = dk.auto(w)                                      # vaqt tugadi
    if not t["done"]:
        if not dk.act(w, *a): dk.act(w, *dk.auto(w))
        await dpush(t)

def mk_table(ps, g, cur, st, bot_game=False):
    t = {"u": [p.uid if p else None for p in ps], "p": ps, "cur": cur, "stake": st, "done": False, "res": {}, "g": g, "bot": bot_game}
    if g in DURAK: t["dk"] = durak.Durak(DURAK[g])
    return t

async def begin(t):
    ACTIVE.append(t)
    names = [{"name": p.name if p else "🤖 Bot"} for p in t["p"]]
    for i, p in enumerate(t["p"]):
        if not p: continue
        p.t, p.seat = t, i
        await send(p, {"t": "me", "user": pub(user(p.uid))})
        await send(p, {"t": "start", "seat": i, "players": names, "game": t["g"], "cur": t["cur"], "stake": t["stake"], "max": 2})
    if "dk" in t: await dpush(t)

def dequeue(c):
    if c.q and c in queues.get(c.q, []): queues[c.q].remove(c)
    c.q = None

async def pair(key):
    q = queues[key]; g, cur, st = key
    while len(q) >= 2:
        a, b = q.pop(0), q.pop(0); ok = []
        for p in (a, b):
            if cur == "free" or user(p.uid)[cur] >= st: ok.append(p)
            else: await send(p, {"t": "err", "code": "balance"}); p.q = None
        if len(ok) < 2:
            for p in ok: q.insert(0, p)
            continue
        for p in ok:
            p.q = None
            if cur != "free": add(p.uid, cur, -st)
        await begin(mk_table(ok, g, cur, st))
    if len(q) == 1: await send(q[0], {"t": "wait", "have": 1, "max": 2})

async def timeout(t):
    await asyncio.sleep(15); await settle(t, -1)   # rakib tasdiqlamasa — stavka qaytariladi

async def leave(c):
    t = c.t; c.t = None
    if t and not t["done"]:
        await send(t["p"][1 - c.seat], {"t": "opp_left"}); await settle(t, 1 - c.seat)

async def drop(c):
    if not c.uid: return
    dequeue(c); await leave(c)
    if conns.get(c.uid) is c: del conns[c.uid]
    c.uid = None; await bcast({"t": "online", "n": len(conns)})

async def on_msg(c, m):
    k = m.get("t")
    if k == "hello":
        uid, nm, guest = verify(m)
        name = re.sub(r"[<>]", "", m.get("name") or nm or "Player")[:20]
        if (user(uid) or {}).get("banned"): await send(c, {"t": "banned"}); await c.ws.close(); return
        if not user(uid):
            ref = str(m.get("ref") or "")[:24]; okref = ref != uid and user(ref)
            db.execute("INSERT INTO users(uid,name,guest,ref_by,created) VALUES(?,?,?,?,?)", (uid, name, guest, ref if okref else None, int(time.time())))
            if okref: db.execute("UPDATE users SET refs=refs+1 WHERE uid=?", (ref,))
        else: db.execute("UPDATE users SET name=?,last=? WHERE uid=?", (name, int(time.time()), uid))
        db.commit()
        old = conns.get(uid)
        if old and old is not c: await drop(old); await old.ws.close()
        c.uid, c.name = uid, name; conns[uid] = c
        await send(c, {"t": "me", "uid": uid, "user": pub(user(uid)), "bot": BOT_NAME, "test": CFG["test"], "online": len(conns), "notice": CFG["notice"]})
        await bcast({"t": "online", "n": len(conns)}); return
    if not c.uid: return
    if k == "name":
        c.name = re.sub(r"[<>]", "", str(m.get("name", "")))[:20] or c.name
        db.execute("UPDATE users SET name=? WHERE uid=?", (c.name, c.uid)); db.commit()
    elif k == "quick":
        g, cur = m.get("game"), m.get("cur"); st = float(m.get("stake") or 0)
        if g not in GAMES or c.t and not c.t["done"]: return
        if CFG["maint"]: return await send(c, {"t": "err", "code": "maint"})
        dequeue(c)
        if m.get("bot") and g in DURAK:                       # botga qarshi mashq (pulsiz)
            return await begin(mk_table([c, None], g, "free", 0, True))
        if cur == "free": st = 0
        elif st not in STAKES.get(cur, []): return
        elif user(c.uid)[cur] < st: return await send(c, {"t": "err", "code": "balance"})
        key = (g, cur, st); queues.setdefault(key, []).append(c); c.q = key
        await send(c, {"t": "wait", "have": 1, "max": 2}); await pair(key)
    elif k == "cancel": dequeue(c)
    elif k == "dmove" and c.t and "dk" in c.t and not c.t["done"]:
        try: ok = c.t["dk"].act(c.seat, str(m.get("a")), int(m["c"]) if m.get("c") is not None else None, int(m["i"]) if m.get("i") is not None else None)
        except Exception: ok = False
        await dpush(c.t, None if ok else c.seat)
    elif k == "move" and c.t and not c.t["done"] and "dk" not in c.t:
        await send(c.t["p"][1 - c.seat], {"t": "move", "d": m.get("d"), "from": c.seat})
    elif k == "chat" and c.t:
        txt = str(m.get("text", ""))[:20]
        for p in c.t["p"]: await send(p, {"t": "chat", "from": c.seat, "name": c.name, "text": txt})
    elif k == "result" and c.t and not c.t["done"] and "dk" not in c.t:
        w, t = m.get("winner"), c.t
        if w not in (-1, 0, 1): return
        t["res"][c.seat] = w
        if len(t["res"]) == 2: await settle(t, w if t["res"][0] == t["res"][1] else -1)
        else: asyncio.create_task(timeout(t))
    elif k == "leave": await leave(c)
    elif k == "lb":
        rows = db.execute("SELECT uid,name,wins,games FROM users WHERE games>0 ORDER BY wins DESC,games ASC LIMIT 50")
        await send(c, {"t": "lb", "list": [dict(r) for r in rows]})
    elif k == "deposit":
        meth, amt = m.get("method"), float(m.get("amount") or 0)
        if not 0 < amt <= 10000: return
        if CFG["test"]: return await credit(c.uid, "ton" if meth == "ton" else "star", amt, secrets.token_hex(8))
        no = {"t": "dep", "ok": False}
        if not TOKEN or user(c.uid)["guest"]: return await send(c, no)
        if meth == "star":
            link = await wallet.stars_link(c.uid, int(amt)); await send(c, {**no, "link": link} if link else no)
        elif meth == "ton" and wallet.TON_ADDR:
            await send(c, {**no, "ton": {"addr": wallet.TON_ADDR, "comment": "dep:" + c.uid, "amount": amt}})
        else: await send(c, no)

async def ws_handler(req):
    ws = web.WebSocketResponse(heartbeat=25); await ws.prepare(req); c = C(ws)
    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT: continue
            try: await on_msg(c, json.loads(msg.data))
            except Exception as e: print("ws:", repr(e))
    finally: await drop(c)
    return ws

async def on_start(app):
    global BOT_NAME
    if TOKEN:
        BOT_NAME = await bot.me() or ""; await bot.setup()
        app["tasks"] = [asyncio.create_task(bot.poll(credit)), asyncio.create_task(wallet.ton_poll(credit))]

async def on_stop(app):
    for t in app.get("tasks", []): t.cancel()

async def index(r):
    return web.FileResponse(os.path.join(BASE, "static", "index.html"), headers={"Cache-Control": "no-cache"})

app = web.Application(); app.on_startup.append(on_start); app.on_cleanup.append(on_stop)
admin.setup(app, sys.modules[__name__])
app.add_routes([web.get("/ws", ws_handler), web.get("/health", lambda r: web.Response(text="ok")), web.get("/", index)])
app.router.add_static("/", os.path.join(BASE, "static"))
HOST = os.getenv("HOST", "127.0.0.1")
if __name__ == "__main__":
    print(f"Arena: http://localhost:{PORT}  TEST_MODE={CFG["test"]}"); web.run_app(app, host=HOST, port=PORT)
