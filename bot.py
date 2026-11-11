"""Telegram bot: /start, Stars to'lovlari, menyu tugmasi (long polling)."""
import asyncio, os, aiohttp

def _env():
    for f in (".env", "_env"):
        if os.path.exists(f):
            for ln in open(f, encoding="utf-8-sig"):
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    k, v = ln.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
_env()

TOKEN = os.getenv("BOT_TOKEN", "")
URL = os.getenv("WEBAPP_URL", "").rstrip("/")
API = f"https://api.telegram.org/bot{TOKEN}/"
_s = None

async def call(method, **p):
    global _s
    if _s is None or _s.closed:
        _s = aiohttp.ClientSession()
    async with _s.post(API + method, json=p, timeout=aiohttp.ClientTimeout(total=70)) as r:
        j = await r.json()
    if not j.get("ok"):
        raise RuntimeError(f"{method}: {j.get('description')}")
    return j["result"]

async def me():
    try:
        return (await call("getMe"))["username"]
    except Exception as e:
        print("getMe:", e); return ""

async def setup():
    """Bot menyusidagi 'Arena' tugmasini Mini App ga ulaydi."""
    if URL.startswith("https://"):
        try:
            await call("setChatMenuButton", menu_button={"type": "web_app", "text": "Arena", "web_app": {"url": URL}})
        except Exception as e:
            print("menu:", e)
    else:
        print("DIQQAT: WEBAPP_URL https:// bilan boshlanishi kerak, aks holda Telegram ochmaydi")

async def poll(credit):
    off = 0
    while True:
        try:
            ups = await call("getUpdates", offset=off, timeout=50,
                             allowed_updates=["message", "pre_checkout_query"]) or []
            for u in ups:
                off = u["update_id"] + 1
                if "pre_checkout_query" in u:
                    await call("answerPreCheckoutQuery", pre_checkout_query_id=u["pre_checkout_query"]["id"], ok=True)
                m = u.get("message")
                if not m:
                    continue
                sp = m.get("successful_payment")
                if sp and sp["invoice_payload"].startswith("stars:"):
                    await credit(sp["invoice_payload"][6:], "star", sp["total_amount"],
                                 "tg:" + sp["telegram_payment_charge_id"])
                elif (m.get("text") or "").startswith("/start"):
                    arg = m["text"][6:].strip()
                    url = URL + ("?ref=" + arg[4:] if arg.startswith("ref_") else "")
                    await call("sendMessage", chat_id=m["chat"]["id"],
                               text="🎮 Arena — aqlli o'yinlar / умные игры / smart games",
                               reply_markup={"inline_keyboard": [[{"text": "▶ Play", "web_app": {"url": url}}]]})
        except Exception as e:
            print("bot:", e)
            await asyncio.sleep(3)
