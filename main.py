import yfinance as yf
import pandas as pd
import requests
import os
import feedparser
import matplotlib.pyplot as plt
import html
from datetime import datetime

# --- 設定區 ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

STOCK_CONFIG = {
    "2330": {"fast": 15, "slow": 60, "name": "台積電"},
    "3711": {"fast": 10, "slow": 60, "name": "日月光"},
    "1605": {"fast": 5,  "slow": 20, "name": "華新"},
    "3037": {"fast": 10, "slow": 20, "name": "欣興"},
    "2379": {"fast": 15, "slow": 60, "name": "瑞昱"},
    "0050": {"fast": 15, "slow": 60, "name": "元大50"},
    "3481": {"fast": 20, "slow": 50, "name": "群創"},
}

plt.switch_backend('Agg')

# --- 1. 抓取大盤新聞 ---
def get_news_data():
    try:
        rss_url = "https://news.google.com/rss/search?q=台股+大盤&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(rss_url)
        news_data = []
        for entry in feed.entries[:3]:
            news_data.append({
                "title": entry.title,
                "link": entry.link
            })
        return news_data
    except:
        return []

# --- 2. 計算 RSI ---
def calculate_rsi(data, window=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- 3. 繪圖 ---
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

# --- 4. 發送 Telegram (修復連結轉義問題) ---
def send_report(html_msg, text_msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Token 或 Chat ID 未設定")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # 嘗試發送 HTML 版
    payload_html = {
        'chat_id': TELEGRAM_CHAT_ID, 
        'text': html_msg, 
        'parse_mode': 'HTML', 
        'disable_web_page_preview': True
    }
    
    try:
        print("📤 嘗試發送 HTML 日報...")
        resp = requests.post(url, data=payload_html)
        
        if resp.status_code == 200:
            print("✅ HTML 日報發送成功！")
            return
        else:
            print(f"⚠️ HTML 失敗 ({resp.status_code})，原因: {resp.text}")
            print("🔄 轉用純文字版重試...")

        # 失敗則發送純文字版
        payload_text = {
            'chat_id': TELEGRAM_CHAT_ID, 
            'text': text_msg,
            'disable_web_page_preview': True
        }
        
        resp_text = requests.post(url, data=payload_text)
        if resp_text.status_code == 200:
            print("✅ 純文字日報救援發送成功！")
        else:
            print(f"❌ 全部失敗: {resp_text.text}")

    except Exception as e:
        print(f"❌ 連線錯誤: {e}")

def send_telegram_photo(msg, image_path):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(image_path, 'rb') as img_file:
        try: 
            requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'caption': msg, 'parse_mode': 'HTML'}, files={'photo': img_file})
        except: pass

# --- 5. 核心分析 ---
def analyze_stock(stock_id, config):
    ticker = f"{stock_id}.TW"
    FAST_MA = config['fast']
    SLOW_MA = config['slow']
    NAME = config['name']
    
    data = yf.Ticker(ticker).history(period="6mo")
    if len(data) < SLOW_MA: return None

    col_fast = f'MA{FAST_MA}'
    col_slow = f'MA{SLOW_MA}'
    data[col_fast] = data['Close'].rolling(window=FAST_MA).mean()
    data[col_slow] = data['Close'].rolling(window=SLOW_MA).mean()
    data['RSI'] = calculate_rsi(data)
    
    today = data.iloc[-1]
    yesterday = data.iloc[-2]
    
    ma_short_today = today[col_fast]
    ma_long_today = today[col_slow]
    ma_short_yesterday = yesterday[col_fast]
    ma_long_yesterday = yesterday[col_slow]
    
    trend_status = "多" if today['Close'] > ma_long_today else "空"

    signal = None
    if ma_short_today > ma_long_today and ma_short_yesterday <= ma_long_yesterday:
        signal = "🔥黃金交叉"
    elif ma_short_today < ma_long_today and ma_short_yesterday >= ma_long_yesterday:
        signal = "🧊死亡交叉"
    
    return {
        "id": stock_id,
        "name": NAME,
        "close": today['Close'],
        "rsi": today['RSI'],
        "trend": trend_status,
        "signal": signal,
        "data_obj": data,
        "fast": FAST_MA,
        "slow": SLOW_MA
    }

# --- 主程式 ---
if __name__ == "__main__":
    print("--- 產生盤後日報中 ---")
    
    daily_report_list = []
    taiex_data = None  # 用來存 0050 的資料

    for stock_id, config in STOCK_CONFIG.items():
        try:
            result = analyze_stock(stock_id, config)
            if result:
                daily_report_list.append(result)
                
                # --- 新增：如果是 0050，把資料存起來等一下畫圖 ---
                if stock_id == "0050":
                    taiex_data = result
                
                # 個股訊號通知 (維持原樣)
                if result['signal']:
                    print(f"🚨 {result['name']} 出現訊號")
                    img_path = generate_chart(stock_id, result['data_obj'], result['fast'], result['slow'])
                    msg = f"{result['signal']} - {result['name']} ({stock_id})\n收盤: {result['close']:.1f}\nRSI: {result['rsi']:.1f}"
                    send_telegram_photo(msg, img_path)
                    if os.path.exists(img_path): os.remove(img_path)
        except Exception as e:
            print(f"❌ {stock_id} 錯誤: {e}")
            continue

    print("📊 正在彙整日報...")
    
    if not daily_report_list:
        print("❌ 無資料，取消發送。")
    else:
        # --- 新增：先發送 0050 大盤圖當作封面 ---
        if taiex_data:
            print("🖼️ 正在繪製 0050 大盤趨勢圖...")
            img_path = generate_chart("0050", taiex_data['data_obj'], taiex_data['fast'], taiex_data['slow'])
            send_telegram_photo("📊 <b>今日大盤 (0050) 走勢圖</b>", img_path)
            if os.path.exists(img_path): os.remove(img_path)

        # 接著發送原本的文字報表 (維持原樣)
        news_items = get_news_data()
        today_date = datetime.now().strftime("%Y-%m-%d")

        # ... (下面產生 html_msg 和 text_msg 的程式碼不用動) ...
        # (請保留原本產生 HTML 和純文字報表的邏輯)
        
        # 為了完整性，這裡補上原本的報表產生邏輯
        html_news_section = ""
        for item in news_items:
            safe_title = html.escape(item['title'], quote=True)
            safe_link = html.escape(item['link'], quote=True)
            html_news_section += f"📰 <a href=\"{safe_link}\">{safe_title}</a>\n\n"
        if not html_news_section: html_news_section = "無重點新聞"

        html_table = "股名   收盤  RSI 趨\n"
        html_table += "-" * 23 + "\n"
        for item in daily_report_list:
            name_short = item['name'][:3]
            trend_icon = "📈" if item['trend'] == "多" else "📉"
            html_table += f"{name_short:<4} {item['close']:<5.0f} {item['rsi']:<3.0f} {trend_icon}\n"

        html_msg = (
            f"📅 <b>盤後戰情 ({today_date})</b>\n\n"
            f"<pre>{html_table}</pre>\n"
            f"💡 <b>觀察重點：</b>\n"
            f"RSI > 80 過熱 | RSI < 30 超賣\n\n"
            f"<b>【今日頭條】</b>\n"
            f"{html_news_section}"
        )

        text_news_section = ""
        for item in news_items:
            text_news_section += f"📰 {item['title']}\n------------------\n"
        if not text_news_section: text_news_section = "無重點新聞"

        text_table = "股名   收盤   RSI  趨勢\n"
        text_table += "------------------------\n"
        for item in daily_report_list:
            name_short = item['name'][:3]
            trend_txt = "多" if item['trend'] == "多" else "空"
            text_table += f"{name_short}   {item['close']:.0f}    {item['rsi']:.0f}   {trend_txt}\n"

        text_msg = (
            f"📅 盤後戰情 ({today_date})\n\n"
            f"{text_table}\n"
            f"【今日頭條】\n"
            f"{text_news_section}"
            f"(純文字模式)"
        )

        send_report(html_msg, text_msg)


