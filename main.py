import yfinance as yf
import pandas as pd
import requests
import os
import feedparser
import mplfinance as mpf  # 專業財經繪圖
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

# 設定 K 線圖樣式 (使用類似 Yahoo 財經的風格)
MC_STYLE = mpf.make_mpf_style(base_mpf_style='yahoo', rc={'font.size': 10})

# --- 1. 抓取大盤新聞 ---
def get_news_data():
    try:
        rss_url = "https://news.google.com/rss/search?q=台股+大盤&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(rss_url)
        news_data = []
        for entry in feed.entries[:3]:
            news_data.append({"title": entry.title, "link": entry.link})
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

# --- 3. 專業繪圖 (K線圖 + 均線 + 成交量) ---
def generate_chart(stock_id, data, fast_p, slow_p):
    filename = f"{stock_id}_kline.png"
    
    # 準備均線資料 (mplfinance 需要 list 或 series)
    # 我們只取最後 60 天來畫，比較清楚
    plot_data = data.iloc[-80:] 
    
    # 設定均線 (mav)
    # 設定副圖 (RSI) - 這裡為了版面乾淨，我們先只畫 K線+均線+成交量
    # 如果要畫 RSI 可以用 addplot，但 K 線圖本身資訊量就很大了
    
    apds = [
        mpf.make_addplot(plot_data[f'MA{fast_p}'], color='magenta', width=1.5),
        mpf.make_addplot(plot_data[f'MA{slow_p}'], color='blue', width=2),
    ]

    # 繪圖
    mpf.plot(
        plot_data,
        type='candle',       # K線圖
        style=MC_STYLE,      # 風格
        title=f"\n{stock_id} Trend (MA{fast_p}/MA{slow_p})",
        ylabel='Price',
        volume=True,         # 開啟成交量
        addplot=apds,        # 加入均線
        savefig=filename,    # 存檔
        tight_layout=True,
        figratio=(10, 6),
        figscale=1.2
    )
    
    return filename

# --- 4. 發送 Telegram ---
def send_report(html_msg, text_msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # HTML 版
    try:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': html_msg, 'parse_mode': 'HTML', 'disable_web_page_preview': True})
    except:
        # 失敗轉純文字
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': text_msg, 'disable_web_page_preview': True})

def send_telegram_photo(msg, image_path):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(image_path, 'rb') as img_file:
        try: requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'caption': msg, 'parse_mode': 'HTML'}, files={'photo': img_file})
        except: pass

# --- 5. 核心分析 (含基本面) ---
def analyze_stock(stock_id, config):
    ticker = f"{stock_id}.TW"
    FAST_MA = config['fast']
    SLOW_MA = config['slow']
    NAME = config['name']
    
    # 取得股價資料
    stock_obj = yf.Ticker(ticker)
    data = stock_obj.history(period="6mo")
    if len(data) < SLOW_MA: return None

    # 取得基本面資料 (本益比)
    # 注意：有些 ETF 或虧損公司沒有 PE，需做例外處理
    try:
        pe_ratio = stock_obj.info.get('trailingPE', None)
        pe_str = f"{pe_ratio:.1f}" if pe_ratio else "N/A"
    except:
        pe_str = "N/A"

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
        "pe": pe_str,  # 新增本益比
        "trend": trend_status,
        "signal": signal,
        "data_obj": data,
        "fast": FAST_MA,
        "slow": SLOW_MA
    }

# --- 主程式 ---
if __name__ == "__main__":
    print("--- 產生專業戰情日報中 ---")
    
    daily_report_list = []
    taiex_data = None

    for stock_id, config in STOCK_CONFIG.items():
        try:
            result = analyze_stock(stock_id, config)
            if result:
                daily_report_list.append(result)
                if stock_id == "0050": taiex_data = result
                
                if result['signal']:
                    img_path = generate_chart(stock_id, result['data_obj'], result['fast'], result['slow'])
                    msg = f"{result['signal']} - {result['name']}\n收盤: {result['close']:.1f} | PE: {result['pe']}"
                    send_telegram_photo(msg, img_path)
                    if os.path.exists(img_path): os.remove(img_path)
        except Exception as e:
            print(f"❌ {stock_id}: {e}")
            continue

    if daily_report_list:
        # 1. 發送 0050 K線圖
        if taiex_data:
            img_path = generate_chart("0050", taiex_data['data_obj'], taiex_data['fast'], taiex_data['slow'])
            send_telegram_photo("📊 <b>大盤(0050) K線趨勢</b>", img_path)
            if os.path.exists(img_path): os.remove(img_path)

        # 2. 準備日報
        news_items = get_news_data()
        today_date = datetime.now().strftime("%Y-%m-%d")

        # HTML 表格 (新增 PE 欄位)
        html_table = "股名  收盤  RSI  PE  趨\n"
        html_table += "-" * 26 + "\n"
        for item in daily_report_list:
            name = item['name'][:3]
            trend = "📈" if item['trend'] == "多" else "📉"
            # 調整間距以適應手機畫面
            html_table += f"{name:<3} {item['close']:<5.0f} {item['rsi']:<3.0f} {item['pe']:<4} {trend}\n"

        html_news = ""
        for item in news_items:
            t = html.escape(item['title'], quote=True)
            l = html.escape(item['link'], quote=True)
            html_news += f"📰 <a href=\"{l}\">{t}</a>\n\n"
        if not html_news: html_news = "無新聞"

        html_msg = (
            f"📅 <b>戰情日報 ({today_date})</b>\n\n"
            f"<pre>{html_table}</pre>\n"
            f"💡 PE=本益比 | 📈=多頭\n\n"
            f"<b>【今日頭條】</b>\n{html_news}"
        )

        # 純文字表格 (備用)
        text_table = "股名  收盤   PE   趨勢\n"
        text_table += "----------------------\n"
        for item in daily_report_list:
            name = item['name'][:3]
            text_table += f"{name}  {item['close']:.0f}   {item['pe']}   {item['trend']}\n"

        text_news = ""
        for item in news_items:
            text_news += f"📰 {item['title']}\n------------------\n"

        text_msg = f"📅 戰情 ({today_date})\n\n{text_table}\n【新聞】\n{text_news}(純文字版)"

        send_report(html_msg, text_msg)
        print("✅ 專業日報已發送！")
        send_report(html_msg, text_msg)



