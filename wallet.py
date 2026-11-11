"""Hamyon: Stars invoice havolasi va TON depozitlarini kuzatish."""
import asyncio, os, aiohttp
from bot import call
TON_ADDR = os.getenv("TON_ADDRESS", "")
KEY = os.getenv("TONCENTER_KEY", "")

async def stars_link(uid, n):
    try:
        return await call("createInvoiceLink", title="Arena Stars", description=f"{n} ⭐",
                          payload=f"stars:{uid}", provider_token="", currency="XTR",
                          prices=[{"label": "Stars", "amount": n}])
    except Exception as e:
        print("invoice:", e); return None

async def ton_poll(credit):
    if not TON_ADDR:
        return
    url = f"https://toncenter.com/api/v2/getTransactions?address={TON_ADDR}&limit=30"
    while True:
        try:
            async with aiohttp.ClientSession(headers={"X-API-Key": KEY} if KEY else {}) as s:
                async with s.get(url) as r:
                    for tx in (await r.json()).get("result", []):
                        im = tx.get("in_msg") or {}
                        msg = (im.get("message") or "").strip()
                        val = int(im.get("value") or 0)
                        if msg.startswith("dep:") and val > 0:
                            await credit(msg[4:], "ton", val / 1e9, "ton:" + tx["transaction_id"]["hash"])
        except Exception as e:
            print("ton:", e)
        await asyncio.sleep(20)
