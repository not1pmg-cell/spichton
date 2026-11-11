"""Admin panel API: /admin (sahifa) va /api/admin/* . Parol: .env dagi ADMIN_PASSWORD."""
import asyncio, hashlib, hmac, os, secrets, time
from aiohttp import web
import bot

PASS = os.getenv("ADMIN_PASSWORD", "")
SECRET = (os.getenv("ADMIN_SECRET") or secrets.token_hex(32)).encode()
BASE = os.path.dirname(os.path.abspath(__file__))
FAILS = {}  # ip -> [vaqtlar]

def _sign(exp): return hmac.new(SECRET, str(exp).encode(), hashlib.sha256).hexdigest()
def make_token(): exp = int(time.time()) + 12 * 3600; return f"{exp}.{_sign(exp)}"
def ok_token(t):
    try:
        exp, sig = t.split("."); return int(exp) > time.time() and hmac.compare_digest(sig, _sign(exp))
    except Exception: return False
def ip(r): return r.headers.get("X-Real-IP") or r.remote or "?"

def setup(app, S):
    db = S.db
    def guard(fn):
        async def w(r):
            if not PASS or not ok_token(r.headers.get("X-Admin", "")): return web.json_response({"error": "auth"}, status=401)
            try: return await fn(r)
            except web.HTTPException: raise
            except Exception as e: return web.json_response({"error": str(e)}, status=400)
        return w
    def rows(q, a=()): return [dict(x) for x in db.execute(q, a)]
    def one(q, a=()): return db.execute(q, a).fetchone()[0] or 0
    J = web.json_response

    async def page(r): return web.FileResponse(os.path.join(BASE, "admin", "index.html"), headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    async def login(r):
        if not PASS: return J({"error": "ADMIN_PASSWORD .env da yo'q"}, status=503)
        now, a = time.time(), ip(r); FAILS[a] = [x for x in FAILS.get(a, []) if now - x < 300]
        if len(FAILS[a]) >= 5: return J({"error": "Ko'p urinish. 5 daqiqa kuting"}, status=429)
        pw = (await r.json()).get("password", "")
        if not hmac.compare_digest(hashlib.sha256(pw.encode()).digest(), hashlib.sha256(PASS.encode()).digest()):
            FAILS[a].append(now); await asyncio.sleep(1); return J({"error": "Parol noto'g'ri"}, status=401)
        return J({"token": make_token()})

    @guard
    async def stats(r):
        now = int(time.time()); day = now - 86400
        days = []
        for i in range(6, -1, -1):
            a, b = now - (i + 1) * 86400, now - i * 86400
            days.append({"d": time.strftime("%d.%m", time.localtime(b)),
                         "games": one("SELECT COUNT(*) FROM games WHERE ts>? AND ts<=?", (a, b)),
                         "users": one("SELECT COUNT(*) FROM users WHERE created>? AND created<=?", (a, b))})
        top = rows("SELECT g, COUNT(*) n FROM games GROUP BY g ORDER BY n DESC")
        return J({"users": one("SELECT COUNT(*) FROM users"), "guests": one("SELECT COUNT(*) FROM users WHERE guest=1"),
                  "online": len(S.conns), "tables": len(S.ACTIVE), "queued": sum(len(q) for q in S.queues.values()),
                  "new24": one("SELECT COUNT(*) FROM users WHERE created>?", (day,)), "dau": one("SELECT COUNT(*) FROM users WHERE last>?", (day,)),
                  "games": one("SELECT COUNT(*) FROM games"), "games24": one("SELECT COUNT(*) FROM games WHERE ts>?", (day,)),
                  "bal_star": one("SELECT SUM(star) FROM users"), "bal_ton": one("SELECT SUM(ton) FROM users"),
                  "dep_star": one("SELECT SUM(amt) FROM log WHERE kind='deposit' AND cur='star'"), "dep_ton": one("SELECT SUM(amt) FROM log WHERE kind='deposit' AND cur='ton'"),
                  "fee_star": one("SELECT SUM(amt) FROM log WHERE kind='fee' AND cur='star'"), "fee_ton": one("SELECT SUM(amt) FROM log WHERE kind='fee' AND cur='ton'"),
                  "days": days, "byGame": top, "cfg": S.CFG, "bot": S.BOT_NAME, "tg": bool(S.TOKEN)})

    @guard
    async def users(r):
        q = r.query.get("q", "").strip(); pg = max(0, int(r.query.get("page", 0))); sort = r.query.get("sort", "last")
        order = {"last": "last DESC", "created": "created DESC", "star": "star DESC", "ton": "ton DESC", "wins": "wins DESC", "games": "games DESC"}.get(sort, "last DESC")
        w, a = ("WHERE uid LIKE ? OR name LIKE ?", (f"%{q}%", f"%{q}%")) if q else ("", ())
        total = one(f"SELECT COUNT(*) FROM users {w}", a)
        lst = rows(f"SELECT * FROM users {w} ORDER BY {order} LIMIT 30 OFFSET ?", a + (pg * 30,))
        for u in lst: u["online"] = u["uid"] in S.conns
        return J({"total": total, "list": lst})

    @guard
    async def user_act(r):
        m = await r.json(); uid = str(m.get("uid")); act = m.get("action"); u = S.user(uid)
        if not u: return J({"error": "Topilmadi"}, status=404)
        if act == "adjust":
            cur, amt = m.get("cur"), float(m.get("amount"))
            if cur not in ("star", "ton") or not -1e6 < amt < 1e6: return J({"error": "noto'g'ri"}, status=400)
            if u[cur] + amt < 0: return J({"error": "Balans manfiy bo'lib qoladi"}, status=400)
            S.add(uid, cur, amt); S.logx(uid, "admin", cur, amt, str(m.get("note", ""))[:60])
        elif act in ("ban", "unban"):
            db.execute("UPDATE users SET banned=? WHERE uid=?", (1 if act == "ban" else 0, uid)); db.commit()
            c = S.conns.get(uid)
            if act == "ban" and c:
                await S.send(c, {"t": "banned"}); await S.drop(c); await c.ws.close()
        elif act == "rename":
            db.execute("UPDATE users SET name=? WHERE uid=?", (str(m.get("name", ""))[:20], uid)); db.commit()
        elif act == "kick":
            c = S.conns.get(uid)
            if c: await S.drop(c); await c.ws.close()
        else: return J({"error": "action?"}, status=400)
        c = S.conns.get(uid)
        if c: await S.send(c, {"t": "me", "user": S.pub(S.user(uid))})
        return J({"ok": True, "user": S.user(uid)})

    @guard
    async def log(r):
        kind = r.query.get("kind", ""); pg = max(0, int(r.query.get("page", 0)))
        w, a = ("WHERE kind=?", (kind,)) if kind else ("", ())
        return J({"list": rows(f"SELECT l.*,u.name FROM log l LEFT JOIN users u ON u.uid=l.uid {w} ORDER BY l.id DESC LIMIT 40 OFFSET ?", a + (pg * 40,))})

    @guard
    async def games(r):
        pg = max(0, int(r.query.get("page", 0)))
        return J({"list": rows("""SELECT g.*,a.name n0,b.name n1 FROM games g LEFT JOIN users a ON a.uid=g.p0 LEFT JOIN users b ON b.uid=g.p1
                                  ORDER BY g.id DESC LIMIT 40 OFFSET ?""", (pg * 40,)),
                  "live": [{"g": t["g"], "cur": t["cur"], "stake": t["stake"], "p": [(p.name if p else "Bot") for p in t["p"]]} for t in S.ACTIVE]})

    @guard
    async def online(r):
        return J({"list": [{"uid": u, "name": c.name, "in_game": bool(c.t and not c.t["done"]), "queue": bool(c.q)} for u, c in S.conns.items()]})

    @guard
    async def settings(r):
        if r.method == "POST":
            m = await r.json()
            if "fee" in m:
                f = float(m["fee"])
                if not 0 <= f <= 0.5: return J({"error": "Komissiya 0–50% oralig'ida"}, status=400)
                S.setcfg("fee", f)
            if "test" in m: S.setcfg("test", 1 if m["test"] else 0)
            if "maint" in m: S.setcfg("maint", 1 if m["maint"] else 0)
            if "notice" in m:
                S.setcfg("notice", str(m["notice"])[:200]); await S.bcast({"t": "notice", "text": S.CFG["notice"]})
        return J(S.CFG)

    @guard
    async def broadcast(r):
        m = await r.json(); text = str(m.get("text", "")).strip()[:500]
        if not text: return J({"error": "Matn bo'sh"}, status=400)
        n = 0
        if m.get("telegram") and S.TOKEN:
            ids = [x["uid"][2:] for x in rows("SELECT uid FROM users WHERE uid LIKE 'tg%' AND banned=0")]
            async def run():
                for i in ids:
                    try: await bot.call("sendMessage", chat_id=i, text=text)
                    except Exception: pass
                    await asyncio.sleep(.05)
            asyncio.create_task(run()); n = len(ids)
        else:
            for c in list(S.conns.values()): await S.send(c, {"t": "notice", "text": text})
            n = len(S.conns)
        return J({"ok": True, "sent": n})

    app.add_routes([web.get("/admin", page), web.post("/api/admin/login", login), web.get("/api/admin/stats", stats),
        web.get("/api/admin/users", users), web.post("/api/admin/user", user_act), web.get("/api/admin/log", log),
        web.get("/api/admin/games", games), web.get("/api/admin/online", online),
        web.get("/api/admin/settings", settings), web.post("/api/admin/settings", settings), web.post("/api/admin/broadcast", broadcast)])
