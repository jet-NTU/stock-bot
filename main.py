import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import os
from datetime import datetime
import pytz

# --- 設定區 ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# 您原本的設定 (完美保留，不用重打)
STOCK_CONFIG = {
    "2330": {"fast": 15, "slow": 60, "name": "台積電"},
    "3711": {"fast": 10, "slow": 60, "name": "日月光"},
    "1605": {"fast": 5,  "slow": 20, "name": "華新"},
    "3037": {"fast": 10, "slow": 20, "name": "欣興"},
    "2379": {"fast": 15, "slow": 60, "name": "瑞昱"},
    "0050": {"fast": 15, "slow": 60, "name": "元大50"},
    "3481": {"fast": 20, "slow": 50, "name": "群創"},
    "3661": {"fast": 10, "slow": 60, "name": "世芯-KY"}, # 您有興趣的 IP 股也可以加在這
}

# --- 1. 發送 Telegram ---
def send_telegram_msg(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'})
    except Exception as e:
        print(f"發送失敗: {e}")

# --- 2. 核心技術分析 ---
def check_buy_signal(stock_id, config):
    ticker = f"{stock_id}.TW"
    name = config['name']
    slow_ma_period = config['slow'] # 取用您設定的慢速均線 (例如 60 或 20)
    
    try:
        # 抓取最近 5 天的 15分K
        stock = yf.Ticker(ticker)
        df = stock.history(period="5d", interval="15m")
        
        if df.empty: return None

        # --- 計算指標 ---
        # 1. 計算您的慢速均線 (作為趨勢保護傘)
        # 這裡會動態抓取您 STOCK_CONFIG 裡的 'slow' 數值
        df['Trend_MA'] = df['Close'].rolling(window=slow_ma_period).mean()

        # 2. MACD (標準參數 12, 26, 9)
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        
        # 3. KD (標準參數 9, 3, 3)
        kd = df.ta.stoch(k=9, d=3, smooth_k=3)
        df = pd.concat([df, kd], axis=1)

        df.dropna(inplace=True)

        # 取最新一筆
        today = df.iloc[-1]
        prev = df.iloc[-2]

        # 欄位名稱
        k_col = 'STOCHk_9_3_3'
        d_col = 'STOCHd_9_3_3'
        hist_col = 'MACDh_12_26_9'

        # --- 訊號判斷 ---
        
        # 條件 A: KD 黃金交叉
        kd_golden_cross = (today[k_col] > today[d_col]) and (prev[k_col] < prev[d_col])
        
        # 條件 B: KD 在低檔 (小於 40)
        kd_low = today[k_col] < 40

        # 條件 C (新增): 趨勢過濾！
        # 只有當「收盤價」大於「您設定的慢速均線」時才做多
        # 這能確保您是在回檔時買進，而不是在崩盤時接刀
        trend_is_up = today['Close'] > today['Trend_MA']

        # 條件 D: MACD 轉強
        macd_improving = today[hist_col] > prev[hist_col]

        # 時間標記
        tw_tz = pytz.timezone('Asia/Taipei')
        time_tag = today.name.astimezone(tw_tz).strftime('%H:%M')

        # --- 組合邏輯 ---
        # 必須符合：趨勢向上 + KD金叉 + KD低檔
        if trend_is_up and kd_golden_cross and kd_low:
            msg = f"⚡ <b>{name} ({stock_id})</b> 15分K買點！\n"
            msg += f"⏰ 時間: {time_tag}\n"
            msg += f"📈 價格: {today['Close']:.1f} (站上 {slow_ma_period}MA)\n"
            msg += f"📊 KD值: {today[k_col]:.1f} / {today[d_col]:.1f}\n"
            msg += f"----------------------\n"
            msg += f"✅ <b>趨勢多頭 (股價 > {slow_ma_period}MA)</b>\n"
            msg += f"✅ <b>KD低檔黃金交叉</b>"
            
            if macd_improving:
                msg += f"\n🔥 <b>MACD同步轉強 (強烈訊號)</b>"
            
            return msg

        return None

    except Exception as e:
        print(f"Error {stock_id}: {e}")
        return None

# --- 主程式 ---
if __name__ == "__main__":
    print("--- 開始盤中掃描 (KD+MACD+均線濾網) ---")
    
    # 直接跑您的 STOCK_CONFIG 迴圈
    for stock_id, config in STOCK_CONFIG.items():
        msg = check_buy_signal(stock_id, config)
        if msg:
            print(f"發送訊號: {config['name']}")
            send_telegram_msg(msg)
        else:
            print(f"{config['name']} 無訊號")




