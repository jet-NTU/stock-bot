import yfinance as yf
import pandas as pd
import requests
import schedule
import time
import matplotlib.pyplot as plt
import os # 用來刪除暫存圖片
from datetime import datetime

# --- 設定區 ---
TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
WATCHLIST = ["2330", "0050", "2892"] 

# 設定 Matplotlib 不要在背景執行時跳出視窗 (這行對機器人很重要)
plt.switch_backend('Agg')

# --- 1. 計算 RSI 函數 ---
def calculate_rsi(data, window=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# --- 2. 產生圖表並存檔函數 ---
def generate_chart(stock_id, data):
    """
    畫出 K線圖 + MA + RSI，並存成圖片檔
    """
    filename = f"{stock_id}_chart.png"
    
    # 建立兩個子圖 (上圖股價，下圖 RSI)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), gridspec_kw={'height_ratios': [3, 1]})
    
    # 上圖：股價與均線
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
    
    # 存檔
    plt.tight_layout()
    plt.savefig(filename)
    plt.close() # 關閉圖表釋放記憶體
    
    return filename

# --- 3. 發送圖片到 Telegram 函數 ---
def send_telegram_photo(msg, image_path):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    
    # 開啟圖片檔案
    with open(image_path, 'rb') as img_file:
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'caption': msg, # 圖片下方的文字說明
            'parse_mode': 'HTML'
        }
        files = {
            'photo': img_file
        }
        # 發送請求
        try:
            requests.post(url, data=payload, files=files)
            print(f"圖片發送成功: {image_path}")
        except Exception as e:
            print(f"圖片發送失敗: {e}")

# --- 4. 核心檢查邏輯 ---
def check_stock_signal(stock_id):
    ticker = f"{stock_id}.TW"
    print(f"檢查中: {stock_id}...")
    
    # 抓取資料 (抓 3 個月讓圖表好看一點)
    data = yf.Ticker(ticker).history(period="3mo")
    
    if len(data) < 20:
        return

    # 計算指標
    data['MA5'] = data['Close'].rolling(window=5).mean()
    data['MA20'] = data['Close'].rolling(window=20).mean()
    data['RSI'] = calculate_rsi(data)

    # 取得最新數據
    today_close = data.iloc[-1]['Close']
    today_rsi = data.iloc[-1]['RSI']
    ma5_today = data.iloc[-1]['MA5']
    ma20_today = data.iloc[-1]['MA20']
    
    ma5_yesterday = data.iloc[-2]['MA5']
    ma20_yesterday = data.iloc[-2]['MA20']
    
    date_str = str(data.index[-1].date())
    msg = ""
    signal_triggered = False

    # 訊號判斷
    if ma5_today > ma20_today and ma5_yesterday <= ma20_yesterday:
        msg = (f"🚀 <b>{stock_id} 黃金交叉 (買進)</b>\n"
               f"日期: {date_str}\n"
               f"收盤: {today_close:.2f}\n"
               f"RSI: {today_rsi:.2f}\n"
               f"MA5 穿過 MA20，趨勢向上！")
        signal_triggered = True

    elif ma5_today < ma20_today and ma5_yesterday >= ma20_yesterday:
        msg = (f"📉 <b>{stock_id} 死亡交叉 (賣出)</b>\n"
               f"日期: {date_str}\n"
               f"收盤: {today_close:.2f}\n"
               f"RSI: {today_rsi:.2f}\n"
               f"MA5 跌破 MA20，建議避險。")
        signal_triggered = True

    # 如果有訊號，就產生圖表並發送
    if signal_triggered:
        print(f"發現訊號！正在繪圖...")
        # A. 畫圖並存檔
        img_path = generate_chart(stock_id, data)
        
        # B. 發送圖片 + 文字
        send_telegram_photo(msg, img_path)
        
        # C. 刪除暫存圖片 (保持資料夾乾淨)
        if os.path.exists(img_path):
            os.remove(img_path)
    else:
        print(f"{stock_id} 無訊號")

# --- 5. 排程任務 ---
def job():
    print(f"--- 執行排程檢查 {datetime.now()} ---")
    for stock_id in WATCHLIST:
        try:
            check_stock_signal(stock_id)
        except Exception as e:
            print(f"Error checking {stock_id}: {e}")

# --- 主程式 ---
if __name__ == "__main__":
    job()