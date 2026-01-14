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

# 您原本的設定
STOCK_CONFIG = {
    "2330": {"fast": 15, "slow": 60, "name": "台積電"},
    "3711": {"fast": 10, "slow": 60, "name": "日月光"},
    "1605": {"fast": 5,  "slow": 20, "name": "華新"},
    "3037": {"fast": 10, "slow": 20, "name": "欣興"},
    "2379": {"fast": 15, "slow": 60, "name": "瑞昱"},
    "0050": {"fast": 15, "slow": 60, "name": "元大50"},
    "3481": {"fast": 20, "slow": 50, "name": "群創"},
    "3661": {"fast": 10, "slow": 60, "name": "世芯-KY"},
}

# --- 1. 發送 Telegram ---
def send_telegram_msg(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'})
    except Exception as e:
        print(f"發送失敗: {e}")

# --- 2. 核心技術分析 (雙向訊號) ---
def check_stock_signal(stock_id, config):
    ticker = f"{stock_id}.TW"
    name = config['name']
    slow_ma_period = config['slow'] 
    
    try:
        # 抓取最近 5 天的 15分K
        stock = yf.Ticker(ticker)
        df = stock.history(period="5d", interval="15m")
        
        if df.empty: return None

        # --- 計算指標 ---
        # 1. 趨勢均線
        df['Trend_MA'] = df['Close'].rolling(window=slow_ma_period).mean()

        # 2. MACD (12, 26, 9)
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        
        # 3. KD (9, 3, 3)
        kd = df.ta.stoch(k=9, d=3, smooth_k=3)
        df = pd.concat([df, kd], axis=1)

        df.dropna(inplace=True)

        # 取最新一筆與前一筆
        today = df.iloc[-1]
        prev = df.iloc[-2]

        # 欄位對應
        k_col = 'STOCHk_9_3_3'
        d_col = 'STOCHd_9_3_3'
        hist_col = 'MACDh_12_26_9'

        # --- 判斷邏輯 ---

        # 共通數據
        k_val = today[k_col]
        d_val = today[d_col]
        close_price = today['Close']
        trend_ma = today['Trend_MA']
        
        # 時間標記
        tw_tz = pytz.timezone('Asia/Taipei')
        time_tag = today.name.astimezone(tw_tz).strftime('%H:%M')

        # ====== 買進訊號 (Buy Logic) ======
        # 1. 趨勢多頭 (股價 > 慢速均線)
        trend_is_up = close_price > trend_ma
        # 2. KD 金叉 (K > D 且 前K < 前D)
        golden_cross = (k_val > d_val) and (prev[k_col] < prev[d_col])
        # 3. 位處低檔 (K < 40)
        is_low_level = k_val < 40

        if trend_is_up and golden_cross and is_low_level:
            msg = f"⚡ <b>{name} ({stock_id})</b> 15分K買點！\n"
            msg += f"⏰ 時間: {time_tag}\n"
            msg += f"📈 價格: {close_price:.1f} (站上 {slow_ma_period}MA)\n"
            msg += f"📊 KD值: {k_val:.1f} / {d_val:.1f} (低檔金叉)\n"
            msg += f"----------------------\n"
            msg += f"✅ 趨勢多頭確認\n"
            msg += f"✅ KD低檔黃金交叉"
            if today[hist_col] > prev[hist_col]:
                msg += f"\n🔥 MACD同步轉強"
            return msg

        # ====== 賣出訊號 (Sell Logic) ======
        # 1. KD 死叉 (K < D 且 前K > 前D)
        death_cross = (k_val < d_val) and (prev[k_col] > prev[d_col])
        # 2. 位處高檔 (K > 70) - 這代表過熱，適合獲利了結
        is_high_level = k_val > 70
        # 3. 趨勢轉弱 (MACD 綠柱變長/紅柱縮短)
        macd_weakening = today[hist_col] < prev[hist_col]
        # 4. (選用) 跌破均線
        trend_broken = close_price < trend_ma and prev['Close'] > prev['Trend_MA']

        # 情況 A: 高檔死亡交叉 (獲利了結訊號)
        if death_cross and is_high_level:
            msg = f"🔻 <b>{name} ({stock_id})</b> 高檔賣壓警示！\n"
            msg += f"⏰ 時間: {time_tag}\n"
            msg += f"📉 價格: {close_price:.1f}\n"
            msg += f"📊 KD值: {k_val:.1f} / {d_val:.1f} (高檔死叉)\n"
            msg += f"----------------------\n"
            msg += f"⚠️ KD > 70 死亡交叉 (短線過熱)\n"
            if macd_weakening:
                msg += f"⚠️ MACD 動能轉弱"
            return msg

        # 情況 B: 跌破重要均線 (停損/離場訊號)
        if trend_broken:
            msg = f"💀 <b>{name} ({stock_id})</b> 趨勢破壞警報！\n"
            msg += f"⏰ 時間: {time_tag}\n"
            msg += f"📉 價格: {close_price:.1f} (跌破 {slow_ma_period}MA)\n"
            msg += f"----------------------\n"
            msg += f"❌ 收盤價跌破趨勢線，多頭結構受損\n"
            msg += f"建議檢查是否停損或離場。"
            return msg

        return None

    except Exception as e:
        print(f"Error {stock_id}: {e}")
        return None

# --- 主程式 ---
if __name__ == "__main__":
    print("--- 開始盤中雙向掃描 (買/賣) ---")
    
    for stock_id, config in STOCK_CONFIG.items():
        msg = check_stock_signal(stock_id, config)
        if msg:
            print(f"發送訊號: {config['name']}")
            send_telegram_msg(msg)
        else:
            print(f"{config['name']} 無訊號")




