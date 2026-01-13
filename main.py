import yfinance as yf
import pandas as pd
import requests
import os
import feedparser
import matplotlib.pyplot as plt

# --- 設定區 ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# 🔥 重點修改：策略筆記本 (STOCK_CONFIG)
# 這裡你可以根據 optimize.py 跑出來的結果，為每一支股票設定不同的均線
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

# --- 1. 抓取新聞 ---
def get_stock_news(stock_id):
    try:
        rss_url = f"https://news.google.com/rss/search?q={stock_id}+TW&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(rss_url)
        news_list = []
        for entry in feed.entries[:3]:
            title = entry.title
            link = entry.link
            news_list.append(f"📰 <a href='{link}'>{title}</a>")
        return "\n".join(news_list) if news_list else "無相關近期新聞"
    except:
        return "新聞抓取失敗"

# --- 2. 計算 RSI ---
def calculate_rsi(data, window=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- 3. 動態繪圖 (支援不同參數) ---
def generate_chart(stock_id, data, fast_p, slow_p):
    filename = f"{stock_id}_chart.png"
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), gridspec_kw={'height_ratios': [3, 1]})
    
    # 動態取得欄位名稱
    col_fast = f'MA{fast_p}'
    col_slow = f'MA{slow_p}'

    ax1.set_title(f"{stock_id} Strategy (MA{fast_p} vs MA{slow_p})")
    ax1.plot(data.index, data['Close'], label='Price', color='black', alpha=0.6)
    ax1.plot(data.index, data[col_fast], label=f'MA{fast_p} (Short)', color='magenta', linewidth=1.5)
    ax1.plot(data.index, data[col_slow], label=f'MA{slow_p} (Trend)', color='blue', linewidth=2)
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
def send_telegram_photo(msg, image_path):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(image_path, 'rb') as img_file:
        try: 
            requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'caption': msg, 'parse_mode': 'HTML'}, files={'photo': img_file})
        except: pass

# --- 5. 核心邏輯 (讀取個股專屬參數) ---
def check_stock_signal(stock_id, config):
    ticker = f"{stock_id}.TW"
    
    # 讀取這支股票專屬的參數
    FAST_MA = config['fast']
    SLOW_MA = config['slow']
    NAME = config['name']
    
    print(f"🔍 檢查 {NAME}({stock_id}) 使用策略: MA{FAST_MA}/MA{SLOW_MA}...")
    
    # 根據最長均線決定要抓多少資料 (至少要比長均線多一些)
    data = yf.Ticker(ticker).history(period="6mo")
    if len(data) < SLOW_MA: return

    # 動態計算指標
    col_fast = f'MA{FAST_MA}'
    col_slow = f'MA{SLOW_MA}'
    
    data[col_fast] = data['Close'].rolling(window=FAST_MA).mean()
    data[col_slow] = data['Close'].rolling(window=SLOW_MA).mean()
    data['RSI'] = calculate_rsi(data)
    data['VolMA5'] = data['Volume'].rolling(window=5).mean()

    today = data.iloc[-1]
    yesterday = data.iloc[-2]
    
    # 取得今日數值
    ma_short_today = today[col_fast]
    ma_long_today = today[col_slow]
    ma_short_yesterday = yesterday[col_fast]
    ma_long_yesterday = yesterday[col_slow]
    
    vol_ratio = (today['Volume'] / today['VolMA5']) if today['VolMA5'] > 0 else 0
    is_volume_surge = vol_ratio >= 1.5

    msg = ""
    signal_triggered = False

    # A. 黃金交叉
    if ma_short_today > ma_long_today and ma_short_yesterday <= ma_long_yesterday:
        status = "🔥 <b>黃金交叉 (買進訊號)</b>" if is_volume_surge else "⚠️ <b>黃金交叉 (量不足)</b>"
        msg = (f"{status}\n"
               f"股票: {NAME} ({stock_id})\n"
               f"策略: MA{FAST_MA} 穿過 MA{SLOW_MA}\n"
               f"收盤: {today['Close']:.2f}\n"
               f"均量比: {vol_ratio:.2f} 倍")
        signal_triggered = True

    # B. 死亡交叉
    elif ma_short_today < ma_long_today and ma_short_yesterday >= ma_long_yesterday:
        msg = (f"📉 <b>死亡交叉 (賣出訊號)</b>\n"
               f"股票: {NAME} ({stock_id})\n"
               f"策略: MA{FAST_MA} 跌破 MA{SLOW_MA}\n"
               f"收盤: {today['Close']:.2f}\n"
               f"建議出場觀望")
        signal_triggered = True

    if signal_triggered:
        print(f"🚨 發現訊號: {stock_id}")
        news = get_stock_news(stock_id)
        final_msg = f"{msg}\n\n<b>==== 相關新聞 ====</b>\n{news}"
        # 傳入參數給繪圖函數
        img_path = generate_chart(stock_id, data, FAST_MA, SLOW_MA)
        send_telegram_photo(final_msg, img_path)
        if os.path.exists(img_path): os.remove(img_path)
    else:
        print(f"{stock_id} 無訊號")

if __name__ == "__main__":
    print("--- 智慧量化機器人啟動 (多策略版) ---")
    
    # 迴圈讀取每一支股票的設定檔
    for stock_id, config in STOCK_CONFIG.items():
        check_stock_signal(stock_id, config)
            
    print("--- 檢查完畢 ---")
