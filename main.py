import yfinance as yf
import pandas as pd
import requests
import os
import feedparser
import matplotlib.pyplot as plt
from datetime import datetime

# --- 設定區 ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# 你的策略筆記本
STOCK_CONFIG = {
    "2330": {"fast": 15, "slow": 60, "name": "台積電"},  # 穩健型
    "3711": {"fast": 10, "slow": 60, "name": "日月光"},  # 攻擊型
    "1605": {"fast": 5,  "slow": 20, "name": "華新"},    # 投機/波段型 (假設)
    "3037": {"fast": 10, "slow": 20, "name": "欣興"},    # 飆股型 (假設)
    "2379": {"fast": 15, "slow": 60, "name": "瑞昱"},    # 穩健型
    "0050": {"fast": 15, "slow": 60, "name": "元大50"},
    "3481": {"fast": 20, "slow": 50, "name": "群創"},
}

plt.switch_backend('Agg')

# --- 1. 抓取大盤新聞 (通用) ---
def get_general_news():
    """抓取台股大盤重點新聞"""
    try:
        # 搜尋關鍵字：台股、大盤
        rss_url = "https://news.google.com/rss/search?q=台股+大盤&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(rss_url)
        news_list = []
        for entry in feed.entries[:3]: # 只抓前 3 則
            title = entry.title
            link = entry.link
            news_list.append(f"📰 <a href='{link}'>{title}</a>")
        return "\n".join(news_list)
    except:
        return "無法取得新聞"

# --- 2. 計算 RSI ---
def calculate_rsi(data, window=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- 3. 繪圖 (保留給訊號用) ---
def generate_chart(stock_id, data, fast_p, slow_p):
    filename = f"{stock_id}_chart.png"
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), gridspec_kw={'height_ratios': [3, 1]})
    
    col_fast = f'MA{fast_p}'
    col_slow = f'MA{slow_p}'

    ax1.set_title(f"{stock_id} Analysis")
    ax1.plot(data.index, data['Close'], label='Price', color='black', alpha=0.6)
    ax1.plot(data.index, data[col_fast], label=f'MA{fast_p}', color='magenta', linewidth=1.5)
    ax1.plot(data.index, data[col_slow], label=f'MA{slow_p}', color='blue', linewidth=2)
    ax1.legend()
    ax1.grid(True)
    
    ax2.plot(data.index, data['RSI'], label='RSI', color='purple')
    ax2.axhline(70, color='red', linestyle='--', alpha=0.5)
    ax2.axhline(30, color='green', linestyle='--', alpha=0.5)
    ax2.set_ylim(0, 100)
    ax2.grid(True)
    
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()
    return filename

# --- 4. 發送 Telegram ---
def send_telegram_msg(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    requests.post(url, data=payload)

def send_telegram_photo(msg, image_path):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(image_path, 'rb') as img_file:
        try: 
            requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'caption': msg, 'parse_mode': 'HTML'}, files={'photo': img_file})
        except: pass

# --- 5. 核心邏輯 (蒐集資料並判斷) ---
def analyze_stock(stock_id, config):
    ticker = f"{stock_id}.TW"
    FAST_MA = config['fast']
    SLOW_MA = config['slow']
    NAME = config['name']
    
    # 抓取資料
    data = yf.Ticker(ticker).history(period="6mo")
    if len(data) < SLOW_MA: return None # 資料不足跳過

    # 計算指標
    col_fast = f'MA{FAST_MA}'
    col_slow = f'MA{SLOW_MA}'
    data[col_fast] = data['Close'].rolling(window=FAST_MA).mean()
    data[col_slow] = data['Close'].rolling(window=SLOW_MA).mean()
    data['RSI'] = calculate_rsi(data)
    data['VolMA5'] = data['Volume'].rolling(window=5).mean()

    today = data.iloc[-1]
    yesterday = data.iloc[-2]
    
    ma_short_today = today[col_fast]
    ma_long_today = today[col_slow]
    ma_short_yesterday = yesterday[col_fast]
    ma_long_yesterday = yesterday[col_slow]
    
    # 判斷趨勢狀態
    trend_status = "盤整"
    if today['Close'] > ma_long_today:
        trend_status = "多頭📈"
    else:
        trend_status = "空頭📉"

    # 判斷訊號 (黃金/死亡交叉)
    signal = None
    if ma_short_today > ma_long_today and ma_short_yesterday <= ma_long_yesterday:
        signal = "🔥 黃金交叉"
    elif ma_short_today < ma_long_today and ma_short_yesterday >= ma_long_yesterday:
        signal = "🧊 死亡交叉"
    
    # 回傳整理好的數據 (給日報用)
    info = {
        "id": stock_id,
        "name": NAME,
        "close": today['Close'],
        "rsi": today['RSI'],
        "trend": trend_status,
        "signal": signal,
        "ma_diff": (today['Close'] - ma_long_today) / ma_long_today * 100, # 乖離率
        "data_obj": data, # 保留原始資料供畫圖用
        "fast": FAST_MA,
        "slow": SLOW_MA
    }
    return info

# --- 主程式 ---
if __name__ == "__main__":
    print("--- 產生盤後日報中 ---")
    
    daily_report_list = [] # 存放所有股票的狀態
    alert_triggered = False

    # 1. 逐一分析股票
    for stock_id, config in STOCK_CONFIG.items():
        result = analyze_stock(stock_id, config)
        if result:
            daily_report_list.append(result)
            
            # 如果有特殊訊號，先發送個別通知 (含圖)
            if result['signal']:
                print(f"🚨 {result['name']} 出現訊號: {result['signal']}")
                img_path = generate_chart(stock_id, result['data_obj'], result['fast'], result['slow'])
                msg = f"{result['signal']} - {result['name']} ({stock_id})\n收盤: {result['close']:.1f}\nRSI: {result['rsi']:.1f}"
                send_telegram_photo(msg, img_path)
                if os.path.exists(img_path): os.remove(img_path)
                alert_triggered = True

    # 2. 製作「盤後日報」 (無論有無訊號都發送)
    print("📊 正在彙整日報...")
    
    # A. 抓大盤新聞
    general_news = get_general_news()
    
    # B. 製作監控列表表格
    # 使用 Telegram 的 <pre> 標籤製作等寬字體表格
    table_str = "股名   收盤   RSI   趨勢\n"
    table_str += "-" * 26 + "\n"
    
    for item in daily_report_list:
        # 格式化每一行 (靠左對齊)
        # 股名(4) 收盤(6) RSI(3) 趨勢(2)
        name_short = item['name'][:3] # 名字最多取3字
        trend_icon = "📈" if "多" in item['trend'] else "📉"
        row = f"{name_short:<4} {item['close']:<6.0f} {item['rsi']:<3.0f} {trend_icon}\n"
        table_str += row

    # C. 組合最終訊息
    today_date = datetime.now().strftime("%Y-%m-%d")
    final_report = (
        f"📅 <b>盤後戰情日報 ({today_date})</b>\n\n"
        f"<b>【監控名單概況】</b>\n"
        f"<pre>{table_str}</pre>\n" # <pre> 是關鍵，讓文字排版整齊
        f"💡 <b>觀察重點：</b>\n"
        f"RSI > 80: 過熱注意\n"
        f"RSI < 30: 超賣機會\n\n"
        f"<b>【今日大盤頭條】</b>\n"
        f"{general_news}"
    )
    
    # 3. 發送日報
    send_telegram_msg(final_report)
    print("✅ 日報已發送！")
