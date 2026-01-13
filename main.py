import yfinance as yf
import pandas as pd
import requests
import os
import feedparser
import matplotlib.pyplot as plt
from datetime import datetime

# --- 設定區 ---
# 從 GitHub Secrets 讀取密碼 (安全模式)
# 如果你在本機測試，請暫時把這兩行改成: TELEGRAM_TOKEN = "你的Token"
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# 監控清單
WATCHLIST = ["2330", "0050", "2892", "3481", "6770"] 

# 設定繪圖後端 (避免雲端執行時報錯)
plt.switch_backend('Agg')

# --- 1. 抓取新聞函數 ---
def get_stock_news(stock_id):
    """
    使用 Google News RSS 抓取個股新聞
    """
    try:
        # 設定搜尋關鍵字 (加上 TW 確保是台股)
        rss_url = f"https://news.google.com/rss/search?q={stock_id}+TW&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(rss_url)
        news_list = []
        
        # 只抓最新的 3 則
        for entry in feed.entries[:3]:
            title = entry.title
            link = entry.link
            # 使用 HTML 格式讓標題變成超連結
            news_item = f"📰 <a href='{link}'>{title}</a>"
            news_list.append(news_item)
            
        if not news_list:
            return "無相關近期新聞"
            
        return "\n".join(news_list)
    except Exception as e:
        return f"新聞抓取失敗: {e}"

# --- 2. 計算 RSI 函數 ---
def calculate_rsi(data, window=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# --- 3. 繪圖與存檔函數 ---
def generate_chart(stock_id, data):
    filename = f"{stock_id}_chart.png"
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), gridspec_kw={'height_ratios': [3, 1]})
    
    # 上圖：股價 + 均線
    ax1.set_title(f"{stock_id} Technical Analysis")
    ax1.plot(data.index, data['Close'], label='Price', color='black', alpha=0.6)
    ax1.plot(data.index, data['MA5'], label='MA5', color='orange')
    ax1.plot(data.index, data['MA20'], label='MA20', color='blue')
    ax1.legend()
    ax1.grid(True)
    
    # 下圖：RSI
    ax2.plot(data.index, data['RSI'], label='RSI', color='purple')
    ax2.axhline(70, color='red', linestyle='--', alpha=0.5)
    ax2.axhline(30, color='green', linestyle='--', alpha=0.5)
    ax2.fill_between(data.index, data['RSI'], 70, where=(data['RSI']>=70), facecolor='red', alpha=0.3)
    ax2.fill_between(data.index, data['RSI'], 30, where=(data['RSI']<=30), facecolor='green', alpha=0.3)
    ax2.set_ylim(0, 100)
    ax2.grid(True)
    
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()
    return filename

# --- 4. 發送圖片到 Telegram ---
def send_telegram_photo(msg, image_path):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 錯誤：找不到 Token 或 Chat ID")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(image_path, 'rb') as img_file:
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'caption': msg,
            'parse_mode': 'HTML' # 支援粗體與超連結
        }
        files = {'photo': img_file}
        try:
            requests.post(url, data=payload, files=files)
            print(f"✅ 成功發送: {image_path}")
        except Exception as e:
            print(f"❌ 發送失敗: {e}")

# --- 5. 核心檢查邏輯 (含量能與新聞) ---
def check_stock_signal(stock_id):
    ticker = f"{stock_id}.TW"
    print(f"🔍 檢查中: {stock_id}...")
    
    # 抓取資料
    data = yf.Ticker(ticker).history(period="3mo")
    if len(data) < 20: return

    # 計算指標
    data['MA5'] = data['Close'].rolling(window=5).mean()
    data['MA20'] = data['Close'].rolling(window=20).mean()
    data['RSI'] = calculate_rsi(data)
    data['VolMA5'] = data['Volume'].rolling(window=5).mean()

    # 取得今日數據
    today = data.iloc[-1]
    today_close = today['Close']
    today_rsi = today['RSI']
    today_vol = today['Volume']
    today_vol_ma = today['VolMA5']
    
    ma5_today = today['MA5']
    ma20_today = today['MA20']
    
    yesterday = data.iloc[-2]
    ma5_yesterday = yesterday['MA5']
    ma20_yesterday = yesterday['MA20']
    
    # 計算量能比
    if today_vol_ma > 0:
        vol_ratio = today_vol / today_vol_ma
    else:
        vol_ratio = 0
    is_volume_surge = vol_ratio >= 1.5

    msg = ""
    signal_triggered = False

    # A. 黃金交叉
    if ma5_today > ma20_today and ma5_yesterday <= ma20_yesterday:
        if is_volume_surge:
            status = "🔥 <b>強勢黃金交叉 (爆量)</b>"
            advice = "主力進場，配合新聞確認利多！"
        else:
            status = "⚠️ <b>弱勢黃金交叉 (無量)</b>"
            advice = "量能不足，需觀察是否為假突破。"
            
        msg = (f"{status}\n"
               f"標的: {stock_id}\n"
               f"收盤: {today_close:.2f}\n"
               f"RSI: {today_rsi:.2f}\n"
               f"量能: {vol_ratio:.2f} 倍\n"
               f"💡 建議: {advice}")
        signal_triggered = True

    # B. 死亡交叉
    elif ma5_today < ma20_today and ma5_yesterday >= ma20_yesterday:
        msg = (f"📉 <b>死亡交叉 (賣出訊號)</b>\n"
               f"標的: {stock_id}\n"
               f"收盤: {today_close:.2f}\n"
               f"MA5 跌破 MA20，建議獲利了結或停損。")
        signal_triggered = True

    # --- 若有訊號，抓新聞並發送 ---
    if signal_triggered:
        print(f"🚨 發現訊號: {stock_id}，正在抓取新聞...")
        
        # 1. 抓新聞
        news_content = get_stock_news(stock_id)
        
        # 2. 組合訊息
        final_msg = f"{msg}\n\n<b>==== 相關新聞 ====</b>\n{news_content}"
        
        # 3. 畫圖
        img_path = generate_chart(stock_id, data)
        
        # 4. 發送
        send_telegram_photo(final_msg, img_path)
        
        # 5. 清理圖片
        if os.path.exists(img_path):
            os.remove(img_path)
    else:
        print(f"{stock_id} 無訊號")

# --- 主程式 ---
if __name__ == "__main__":
    print("--- 雲端機器人啟動 (含新聞功能) ---")
    
    # 這裡我們不傳送「開始巡邏」的訊息，以免每天收到兩次通知很吵
    # 只在有真正的交易訊號時才通知
    
    for stock in WATCHLIST:
        check_stock_signal(stock)
            
    print("--- 檢查完畢 ---")
