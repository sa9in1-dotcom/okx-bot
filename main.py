import asyncio, aiohttp, time, logging
from datetime import datetime

TELEGRAM_TOKEN = "8743577437:AAHPw7l-9ZPx58AH1G8Sg-5urxB5oMIOSgM"
TELEGRAM_CHAT_ID = "544448098"
GROWTH_MIN = 20
RSI_THRESHOLD = 75
CHECK_INTERVAL = 60
TIMEFRAMES = ["1H", "4H"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger(__name__)
BASE_URL = "https://www.okx.com"

async def get_futures_tickers(session):
    url = f"{BASE_URL}/api/v5/market/tickers?instType=SWAP"
    async with session.get(url) as r:
        data = await r.json()
    tickers = []
    for t in data.get("data", []):
        inst_id = t.get("instId", "")
        if not inst_id.endswith("USDT-SWAP"):
            continue
        try:
            last = float(t["last"])
            open24 = float(t["open24h"])
            change_pct = ((last - open24) / open24) * 100
            tickers.append({"instId": inst_id, "last": last, "change24h": change_pct})
        except:
            continue
    return tickers

async def get_candles(session, inst_id, bar="1H", limit=50):
    url = f"{BASE_URL}/api/v5/market/candles"
    params = {"instId": inst_id, "bar": bar, "limit": limit}
    async with session.get(url, params=params) as r:
        data = await r.json()
    closes = []
    for c in reversed(data.get("data", [])):
        try:
            closes.append(float(c[4]))
        except:
            continue
    return closes

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period-1) + gains[i]) / period
        al = (al * (period-1) + losses[i]) / period
    if al == 0:
        return 100.0
    return round(100 - (100 / (1 + ag/al)), 2)

async def send_telegram(session, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}) as r:
            pass
    except Exception as e:
        log.error(f"Telegram error: {e}")

def format_alert(coin, change24h, price, rsi_1h, rsi_4h):
    symbol = coin.replace("-USDT-SWAP", "")
    return (
        f"🔴 <b>ШОРТ СЕТАП — {symbol}</b>\n\n"
        f"💰 Цена: <b>${price:,.4f}</b>\n"
        f"📈 Рост за 24ч: <b>+{change24h:.1f}%</b>\n\n"
        f"📊 RSI 1H: <b>{rsi_1h}</b>\n"
        f"📊 RSI 4H: <b>{rsi_4h}</b>\n\n"
        f"🎯 Цели: ${price*0.93:,.4f} → ${price*0.85:,.4f} → ${price*0.78:,.4f}\n"
        f"🛑 Стоп: выше ${price*1.05:,.4f}\n\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )

alerted = {}

async def run():
    async with aiohttp.ClientSession() as session:
        await send_telegram(session, "🤖 <b>OKX Short Bot запущен!</b>\nИщу монеты +20% с RSI 75+")
        while True:
            try:
                tickers = await get_futures_tickers(session)
                candidates = [t for t in tickers if t["change24h"] >= GROWTH_MIN]
                log.info(f"Кандидатов: {len(candidates)}")
                for coin in candidates:
                    inst_id = coin["instId"]
                    if time.time() - alerted.get(inst_id, 0) < 7200:
                        continue
                    rsi_1h = calc_rsi(await get_candles(session, inst_id, "1H"))
                    await asyncio.sleep(0.1)
                    rsi_4h = calc_rsi(await get_candles(session, inst_id, "4H"))
                    await asyncio.sleep(0.1)
                    if (rsi_1h and rsi_1h >= RSI_THRESHOLD) or (rsi_4h and rsi_4h >= RSI_THRESHOLD):
                        await send_telegram(session, format_alert(inst_id, coin["change24h"], coin["last"], rsi_1h, rsi_4h))
                        alerted[inst_id] = time.time()
                        log.info(f"Алерт: {inst_id}")
            except Exception as e:
                log.error(f"Ошибка: {e}")
            await asyncio.sleep(CHECK_INTERVAL)

asyncio.run(run())
