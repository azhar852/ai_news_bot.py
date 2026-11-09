import os
import logging
import time
from datetime import datetime, timedelta
import requests
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    os.system('pip install yfinance')
    import yfinance as yf

# लॉगिंग सेटअप
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
RENDER_URL = os.environ.get('RENDER_URL', 'https://new-trading-bot-2.onrender.com')

# रजिस्टर्ड यूजर्स को ट्रैक करने के लिए सेट
REGISTERED_USERS = set()

# पिछले ट्रेंड और कीमत को याद रखने के लिए (डुप्लीकेट अलर्ट रोकने हेतु)
LAST_SENT_STATUS = None
LAST_CHECKED_PRICE = None


def send_telegram_message(chat_id, text):
    if not chat_id or not TELEGRAM_BOT_TOKEN:
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True,
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logging.error(f'Telegram Send Error: {e}')


def broadcast_to_all(text):
    for chat_id in list(REGISTERED_USERS):
        send_telegram_message(chat_id, text)


def calculate_rsi(data, window=14):
    try:
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 2)
    except Exception:
        return 50.0


def calculate_vwap(data):
    try:
        q = data['Volume']
        tp = (data['High'] + data['Low'] + data['Close']) / 3
        vwap = (tp * q).cumsum() / q.cumsum()
        return round(vwap.iloc[-1], 2)
    except Exception:
        return 0.0


def get_market_status(symbol='^NSEI'):
    """
    लाइవ్ मार्केट का ट्रेंड, VWAP और RSI निकालता है
    """
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='2d', interval='1m')
        if len(data) < 10:
            data = ticker.history(period='5d', interval='5m')

        if len(data) >= 10:
            current_price = round(data['Close'].iloc[-1], 2)
            open_price = data['Open'].iloc[0]
            if open_price == 0:
                open_price = current_price
            
            change_pct = round(((current_price - open_price) / open_price) * 100, 2)
            rsi = calculate_rsi(data)
            vwap = calculate_vwap(data)

            # ट्रेंड की सटीक पहचान
            if current_price > vwap and rsi > 52:
                trend = '🟢 UPTREND (बुलिश / ऊपर जा रहा है)'
            elif current_price < vwap and rsi < 48:
                trend = '🔴 DOWNTREND (बेयरिश / नीचे आ रहा है)'
            else:
                trend = '⚪ SIDEWAYS (रेंज बाउंड / एक दायरे में)'

            return {
                'symbol': 'NIFTY 50',
                'price': current_price,
                'change': change_pct,
                'rsi': rsi,
                'vwap': vwap,
                'trend': trend
            }
    except Exception as e:
        logging.error(f'Market Status Error: {e}')
    return None


# ---------------------------------------------------------
# ऑटोमैटिक फास्ट ट्रेंड स्कैनर (हर 1.5 मिनट में चेक करेगा)
# ---------------------------------------------------------
def fast_market_trend_scanner():
    global LAST_SENT_STATUS, LAST_CHECKED_PRICE
    while True:
        try:
            market = get_market_status('^NSEI')
            if market:
                current_trend = market['trend']
                current_price = market['price']

                status_changed = (LAST_SENT_STATUS != current_trend)
                
                price_diff = 0
                if LAST_CHECKED_PRICE is not None:
                    price_diff = abs(current_price - LAST_CHECKED_PRICE)

                # यदि ट्रेंड बदल गया है या कीमत में 20+ पॉइंट का बदलाव आया है, तो अलर्ट भेजें
                if status_changed or price_diff >= 20:
                    msg = (
                        f"🚨 **MARKET ALERT / ट्रेंड अपडेट**\n\n"
                        f"• Index: {market['symbol']}\n"
                        f"• Current Price: `{current_price}` ({market['change']}%)\n"
                        f"• Market Status: **{current_trend}**\n"
                        f"• VWAP: `{market['vwap']}` | RSI: `{market['rsi']}`\n\n"
                        f"⚡ *मार्केट की स्थिति बदल गई है। कृपया ध्यान दें।*"
                    )
                    broadcast_to_all(msg)
                    LAST_SENT_STATUS = current_trend
                    LAST_CHECKED_PRICE = current_price

        except Exception as e:
            logging.error(f'Scanner Error: {e}')
        
        # हर 90 सेकंड में मार्केट चेक करेगा
        time.sleep(90)


# ---------------------------------------------------------
# Flask वेब सर्वर और टेलीग्राम वेबहुक
# ---------------------------------------------------------
from flask import Flask, request
app = Flask(__name__)

@app.route('/')
def home():
    return 'Fast Trend Alert Bot is Active & Running Perfectly!'

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json(force=True, silent=True)
        if not update or 'message' not in update:
            return 'OK', 200

        chat_id = update['message']['chat']['id']
        text = update['message'].get('text', '').strip().lower()

        # यूजर को ऑटोमैटिकली अलर्ट लिस्ट में जोड़ना
        REGISTERED_USERS.add(chat_id)

        if text in ['/start', 'start', 'status', '/status', 'trend']:
            market = get_market_status('^NSEI')
            if market:
                msg = (
                    f"📊 **LIVE MARKET STATUS**\n\n"
                    f"• Price: `{market['price']}` ({market['change']}%)\n"
                    f"• Trend: **{market['trend']}**\n"
                    f"• VWAP: `{market['vwap']}`\n"
                    f"• RSI: `{market['rsi']}`\n\n"
                    f"🔔 *आपको हर बदलाव का ऑटोमैटिक अलर्ट मिलता रहेगा।*"
                )
                send_telegram_message(chat_id, msg)
            else:
                send_telegram_message(chat_id, '⚠️ अभी मार्केट डेटा लोड होने में समय लग रहा है। कृपया दोबारा प्रयास करें।')
        else:
            send_telegram_message(chat_id, '✅ बॉट एक्टिव है! /status टाइप करके अभी का लाइव ट्रेंड देख सकते हैं।')

    except Exception as e:
        logging.error(f'Webhook Error: {e}')
    return 'OK', 200


# बैकग्राउंड स्कैनर थ्रेड शुरू करना
import threading
threading.Thread(target=fast_market_trend_scanner, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
            
