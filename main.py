import asyncio, aiohttp, time, logging
from datetime import datetime

TELEGRAM_TOKEN = "8743577437:AAHPw7l-9ZPx58AH1G8Sg-5urxB5oMIOSgM"
TELEGRAM_CHAT_ID = "544448098"
GROWTH_MIN = 15
CHECK_INTERVAL = 60

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

async def get_candles(session, inst_id, bar="1H", limit=100):
    url = f"{BASE_URL}/api/v5/market/candles"
    params = {"instId": inst_id, "bar": bar, "limit": limit}
    async with session.get(url, params=params) as r:
        data = await r.json()
    closes, opens = [], []
    for c in reversed(data.get("data", [])):
        try:
            opens.append(float(c[1]))
            closes.append(float(c[4]))
        except:
            continue
    return closes, opens

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

def rsi_slope(closes, period=14, lookback=3):
    if len(closes) < period + lookback + 1:
        return None
    rsi_values = []
    for i in range(lookback + 1):
        subset = closes[:len(closes)-i] if i > 0 else closes
        rsi_values.append(calc_rsi(subset, period))
    if None in rsi_values:
        return None
    return rsi_values[0] - rsi_values[-1]

async def send_telegram(session, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}) as r:
            pass
    except Exception as e:
        log.error(f"Telegram error: {e}")

def format_alert(coin, change24h, price, rsi6_1h, rsi12_1h, rsi24_1h, rsi6_4h, rsi12_4h, rsi24_4h, slope):
    symbol = coin.replace("-USDT-SWAP", "")
    slope_str = f"↑{slope:.1f}" if slope and slope > 0 else f"↓{abs(slope):.1f}" if slope else "N/A"
    return (
        f"🔴 <b>ШОРТ СЕТАП — {symbol}</b>\n\n"
        f"💰 Цена: <b>${price:,.4f}</b>\n"
        f"📈 Рост за 24ч: <b>+{change24h:.1f}%</b>\n\n"
        f"<b>1H:</b> RSI6: {rsi6_1h} | RSI12: {rsi12_1h} | RSI24: {rsi24_1h}\n"
        f"<b>4H:</b> RSI6: {rsi6_4h} | RSI12: {rsi12_4h} | RSI24: {rsi24_4h}\n"
        f"📊 Импульс: {slope_str}\n\n"
        f"🎯 Цели: ${price*0.93:,.4f} → ${price*0.85:,.4f} → ${price*0.78:,.4f}\n"
        f"🛑 Стоп: выше ${price*1.05:,.4f}\n\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )

alerted = {}

async def run():
    async with aiohttp.ClientSession() as session:
        await send_telegram(session,
            "🤖 <b>OKX Short Bot запущен!</b>\n"
            "Параметры:\n"
            "📈 Рост ≥15% за 24ч\n"
            "📊 RSI6 ≥80 | RSI12 ≥75 | RSI24 ≥70\n"
            "⚡ RSI растёт + свеча зелёная\n"
            "⏱ Проверка каждую минуту"
        )
        while True:
            try:
                tickers = await get_futures_tickers(session)
                candidates = [t for t in tickers if t["change24h"] >= GROWTH_MIN]
                log.info(f"Кандидатов: {len(candidates)}")

                for coin in candidates:
                    inst_id = coin["instId"]
                    if time.time() - alerted.get(inst_id, 0) < 7200:
                        continue

                    closes_1h, opens_1h = await get_candles(session, inst_id, "1H")
                    await asyncio.sleep(0.1)
                    closes_4h, opens_4h = await get_candles(session, inst_id, "4H")
                    await asyncio.sleep(0.1)

                    rsi6_1h = calc_rsi(closes_1h, 6)
                    rsi12_1h = calc_rsi(closes_1h, 12)
                    rsi24_1h = calc_rsi(closes_1h, 24)
                    rsi6_4h = calc_rsi(closes_4h, 6)
                    rsi12_4h = calc_rsi(closes_4h, 12)
                    rsi24_4h = calc_rsi(closes_4h, 24)

                    slope = rsi_slope(closes_1h, 6)

                    rsi_ok = (
                        (rsi6_1h and rsi6_1h >= 80) or
                        (rsi12_1h and rsi12_1h >= 75) or
                        (rsi24_1h and rsi24_1h >= 70) or
                        (rsi6_4h and rsi6_4h >= 80) or
                        (rsi12_4h and rsi12_4h >= 75) or
                        (rsi24_4h and rsi24_4h >= 70)
                    )

                    momentum_ok = slope and slope > 0
                    green_1h = len(closes_1h) > 0 and len(opens_1h) > 0 and closes_1h[-1] > opens_1h[-1]

                    if rsi_ok and momentum_ok and green_1h:
                        msg = format_alert(inst_id, coin["change24h"], coin["last"],
                                         rsi6_1h, rsi12_1h, rsi24_1h,
                                         rsi6_4h, rsi12_4h, rsi24_4h, slope)
                        await send_telegram(session, msg)
                        alerted[inst_id] = time.time()
                        log.info(f"Алерт: {inst_id}")

            except Exception as e:
                log.error(f"Ошибка: {e}")
            await asyncio.sleep(CHECK_INTERVAL)

asyncio.run(run())
