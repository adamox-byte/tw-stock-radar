import os
import time
import random
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import deque
from fugle_marketdata import RestClient, FugleAPIError

TW_TZ = ZoneInfo("Asia/Taipei")

# 從微軟加密保險箱讀取設定
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "my_tw_stock_k82m")
FUGLE_API_KEY = os.environ.get("FUGLE_API_KEY", "")

# 監控自選池
watchlist = [
    ("2606", "裕民", 68.0),
    ("1795", "美時", 102.0),
    ("2882", "國泰金", 105.5),
    ("1326", "台化", 63.0),
    ("3131", "弘塑", 1460.0),
    ("1312", "國喬", 10.3),
    ("1101", "台泥", 25.3),
]

MIN_TURNOVER_TWD = 1_500_000
MIN_OUTER_RATIO = 65.0
BOX_WINDOW_MINS = 15

def is_tw_trading_hours(now_tw: datetime) -> bool:
    if now_tw.weekday() >= 5:
        return False
    hm = now_tw.hour * 100 + now_tw.minute
    return 900 <= hm <= 1335

def send_institutional_alert(code, name, price, vwap, box_high, min_amount, outer_pct):
    title = f"🎯【築底真突破】{code} {name} 穿越 {box_high}！"
    body = (
        f"現價: {price} 元 (穿透 15分箱頂 {box_high})\n"
        f"VWAP均價線: {vwap:.2f} 元 (站穩強勢區)\n"
        f"本分金流: +{min_amount/10000:.1f} 萬 (門檻150萬)\n"
        f"主力外盤推力: {outer_pct:.1f}%\n"
        f"時間: {datetime.now(TW_TZ).strftime('%H:%M:%S')}"
    )
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Priority": "urgent",
                "Tags": "dart,chart_with_upwards_trend,moneybag",
            },
            timeout=5
        )
        print(f"\n  >>> 🚀 【手機推播已響鈴】：{name} 築底真突破！")
    except Exception as e:
        print(f"\n  >>> ⚠️ 推播失敗: {e}")

def main():
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data="微軟雲端伺服器已自動開機接管！今日盤中持續獵殺...".encode("utf-8"),
            headers={"Title": "⚡ GitHub Actions 雲端上線".encode("utf-8"), "Priority": "default", "Tags": "octocat,rocket"},
            timeout=5
        )
    except Exception:
        pass

    client = RestClient(api_key=FUGLE_API_KEY)
    stock_api = client.stock
    prev_snap = {}
    last_alert_time = {}
    price_history = {c: deque(maxlen=BOX_WINDOW_MINS) for c, _, _ in watchlist}

    step = 1
    print("🚀 雲端獵殺引擎啟動...")

    while True:
        now_tw = datetime.now(TW_TZ)
        now_str = now_tw.strftime("%Y-%m-%d %H:%M:%S")
        today_str = now_tw.strftime("%Y-%m-%d")

        if now_tw.hour * 100 + now_tw.minute < 900:
            print(f"[{now_str}] 盤前等待開盤中，休眠 30 秒...")
            time.sleep(30)
            continue

        if now_tw.hour * 100 + now_tw.minute > 1335:
            print(f"[{now_str}] 🏁 13:35 台股收盤，任務圓滿完成，伺服器關機！")
            break

        print(f"\n[第 {step} 輪] 台灣時間: {now_str}")
        for code, name, res_p in watchlist:
            try:
                q = stock_api.intraday.quote(symbol=code)
            except Exception:
                continue

            is_today = (q.get("date", "") == today_str)
            is_trial = q.get("isTrial", False)
            cur_p = q.get("closePrice") or q.get("lastPrice")
            vwap = q.get("avgPrice")
            total = q.get("total") or {}
            cum_val = float(total.get("tradeValue") or 0)
            cum_ask = float(total.get("tradeVolumeAtAsk") or 0)
            cum_bid = float(total.get("tradeVolumeAtBid") or 0)

            min_amount = 0.0
            min_outer_pct = None
            prev_p = prev_snap.get(code, {}).get("price") if code in prev_snap else None

            if is_today and not is_trial and code in prev_snap:
                min_amount = max(0.0, cum_val - prev_snap[code]["val"])
                d_ask = max(0.0, cum_ask - prev_snap[code]["ask_vol"])
                d_bid = max(0.0, cum_bid - prev_snap[code]["bid_vol"])
                d_ab = d_ask + d_bid
                if d_ab > 0:
                    min_outer_pct = (d_ask / d_ab) * 100

            if is_today and not is_trial and cur_p is not None:
                hist = list(price_history[code])
                local_box_high = max(hist) if len(hist) >= 3 else max(res_p, cur_p)
                price_history[code].append(cur_p)
                prev_snap[code] = {"price": cur_p, "val": cum_val, "ask_vol": cum_ask, "bid_vol": cum_bid}
            else:
                local_box_high = res_p

            is_crossing = (prev_p is not None and cur_p is not None and prev_p <= local_box_high and cur_p > local_box_high and cur_p >= res_p)
            is_above_vwap = (cur_p is not None and vwap is not None and cur_p >= vwap)
            has_money_power = (min_amount >= MIN_TURNOVER_TWD and min_outer_pct is not None and min_outer_pct >= MIN_OUTER_RATIO)

            now_ts = time.time()
            cooldown_passed = (code not in last_alert_time or (now_ts - last_alert_time[code]) > 900)

            if is_crossing and is_above_vwap and has_money_power and cooldown_passed:
                send_institutional_alert(code, name, cur_p, vwap, local_box_high, min_amount, min_outer_pct)
                last_alert_time[code] = now_ts

            amt_str = f"+{min_amount/10000:.0f}萬" if min_amount > 0 else "+0萬"
            outer_str = f"{min_outer_pct:.1f}%" if min_outer_pct
