import os
import logging
import json
import sqlite3
import requests
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler

# ==========================================
# 1. कॉन्फ़िगरेशन और लॉगिंग
# ==========================================
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')  # जैसे: https://your-app.onrender.com/webhook

app = Flask(__name__)

# ==========================================
# 2. SQLite डेटाबेस सेटअप (यूजर्स को सेव रखने के लिए)
# ==========================================
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

def add_user(chat_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (chat_id) VALUES (?)', (chat_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM users')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

init_db()

# ==========================================
# 3. स्टेट मैनेजमेंट (डुप्लीकेट अलर्ट रोकने के लिए)
# ==========================================
STATE_FILE = 'bot_state.json'

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {"last_trend": None, "last_price": 0.0}

def save_state(last_trend, last_price):
    with open(STATE_FILE, 'w') as f:
        json.dump({"last_trend": last_trend, "last_price": last_price}, f)

bot_state = load_state()

# ==========================================
# 4. टेलीग्राम फंक्शन्स
# ==========================================
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
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 429:  # Rate Limit Handling
            logging.warning("Rate limit hit. Sleeping for 5 seconds.")
            time.sleep(5)
            requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f'Telegram Send Error: {e}')

def broadcast_to_all(text):
    users = get_all_users()
    for chat_id in users:
        send_telegram_message(chat_id, text)

# ==========================================
# 5. मार्केट डेटा और इंडिकेटर्स (Pandas_TA के साथ)
# ==========================================
def get_market_status(symbol='^NSEI'):
    try:
        ticker = yf.Ticker(symbol)
        # 5 दिन का 5-मिनट डेटा (1-मिनट की तुलना में ज्यादा रिलायबल और Rate Limit से बचाव)
        data = ticker.history(period='5d', interval='5m')
        
        if data.empty:
            logging.warning("Empty data received from yfinance (Market might be closed).")
            return None

        # इंडिकेटर्स कैलकुलेशन (Pandas_TA का उपयोग)
        data['RSI'] = ta.rsi(data['Close'], length=14)
        data['VWAP'] = ta.vwap(high=data['High'], low=data['Low'], close=data['Close'], volume=data['Volume'])
        data['EMA_9'] = ta.ema(data['Close'], length=9)
        data['SMA_20'] = ta.sma(data['Close'], length=20)
        
        # SuperTrend (Returns: SUPERT_10_3.0, SUPERTd_10_3.0, SUPERTl_10_3.0, SUPERTs_10_3.0)
        st = ta.supertrend(high=data['High'], low=data['Low'], close=data['Close'], length=10, multiplier=3)
        data = pd.concat([data, st], axis=1)

        # latest values
        current_price = round(data['Close'].iloc[-1], 2)
        open_price = data['Open'].iloc[0]
        if open_price == 0: open_price = current_price
        
        change_pct = round(((current_price - open_price) / open_price) * 100, 2)
        
        rsi = round(data['RSI'].iloc[-1], 2) if not pd.isna(data['RSI'].iloc[-1]) else 50.0
        vwap = round(data['VWAP'].iloc[-1], 2) if not pd.isna(data['VWAP'].iloc[-1]) else current_price
        ema_9 = round(data['EMA_9'].iloc[-1], 2) if not pd.isna(data['EMA_9'].iloc[-1]) else current_price
        sma_20 = round(data['SMA_20'].iloc[-1], 2) if not pd.isna(data['SMA_20'].iloc[-1]) else current_price
        
        # SuperTrend Direction (1 = Bullish, -1 = Bearish)
        st_dir = data['SUPERTd_10_3.0'].iloc[-1]
        supertrend_status = "BULLISH 🟢" if st_dir == 1 else "BEARISH 🔴"

        # Trend Logic
        if current_price > vwap and rsi > 50 and ema_9 > sma_20 and st_dir == 1:
            trend = '🟢 UPTREND (मजबूत बुलिश)'
        elif current_price < vwap and rsi < 50 and ema_9 < sma_20 and st_dir == -1:
            trend = '🔴 DOWNTREND (मजबूत बेयरिश)'
        else:
            trend = '⚪ SIDEWAYS (रेंज बाउंड)'

        return {
            'symbol': 'NIFTY 50',
            'price': current_price,
            'change': change_pct,
            'rsi': rsi,
            'vwap': vwap,
            'sma_20': sma_20,
            'ema_9': ema_9,
            'supertrend': supertrend_status,
            'trend': trend
        }
    except Exception as e:
        logging.error(f'Market Status Error: {e}')
        return None

# ==========================================
# 6. ऑटोमैटिक स्कैनर (APScheduler के साथ)
# ==========================================
def fast_market_trend_scanner():
    global bot_state
    try:
        market = get_market_status('^NSEI')
        if not market:
            return

        current_trend = market['trend']
        current_price = market['price']

        status_changed = (bot_state['last_trend'] != current_trend)
        price_diff = abs(current_price - bot_state['last_price']) if bot_state['last_price'] > 0 else 0

        # अलर्ट ट्रिगर: ट्रेंड बदला या 20+ पॉइंट का मूव
        if status_changed or price_diff >= 20:
            msg = (
                f"🚨 **MARKET TREND ALERT**\n\n"
                f"• Index: {market['symbol']}\n"
                f"• Price: `{current_price}` ({market['change']}%)\n"
                f"• Status: **{current_trend}**\n\n"
                f"📊 **Indicators:**\n"
                f"• RSI: `{market['rsi']}` | VWAP: `{market['vwap']}`\n"
                f"• EMA 9: `{market['ema_9']}` | SMA 20: `{market['sma_20']}`\n"
                f"• SuperTrend: `{market['supertrend']}`"
            )
            broadcast_to_all(msg)
            
            # State अपडेट और सेव करें
            bot_state['last_trend'] = current_trend
            bot_state['last_price'] = current_price
            save_state(current_trend, current_price)
            logging.info(f"Alert sent: {current_trend} at {current_price}")

    except Exception as e:
        logging.error(f'Scanner Error: {e}')

# Scheduler सेटअप (हर 90 सेकंड पर चलेगा, केवल 1 बार globally)
scheduler = BackgroundScheduler()
scheduler.add_job(fast_market_trend_scanner, 'interval', seconds=90, max_instances=1)
scheduler.start()

# ==========================================
# 7. Flask वेब सर्वर और टेलीग्राम वेबहुक
# ==========================================
@app.route('/')
def home():
    return '✅ Clean Trend Bot is Active & Running!'

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json(force=True, silent=True)
        if not update or 'message' not in update:
            return 'OK', 200

        chat_id = update['message']['chat']['id']
        text = update['message'].get('text', '').strip().lower()

        # यूजर को डेटाबेस में जोड़ें
        add_user(chat_id)

        if text in ['/start', 'start', 'status', '/status', 'trend']:
            market = get_market_status('^NSEI')
            if market:
                msg = (
                    f"📊 **LIVE MARKET STATUS**\n\n"
                    f"• Index: {market['symbol']}\n"
                    f"• Price: `{market['price']}` ({market['change']}%)\n"
                    f"• Trend: **{market['trend']}**\n\n"
                    f"📈 **Indicators:**\n"
                    f"• RSI: `{market['rsi']}`\n"
                    f"• VWAP: `{market['vwap']}`\n"
                    f"• EMA 9: `{market['ema_9']}` | SMA 20: `{market['sma_20']}`\n"
                    f"• SuperTrend: `{market['supertrend']}`\n\n"
                    f"🔔 *ऑटोमैटिक अलर्ट्स चालू हैं।* लाइव स्टेटस देखने के लिए कभी भी `/status` भेजें।"
                )
                send_telegram_message(chat_id, msg)
            else:
                send_telegram_message(chat_id, '⚠️ मार्केट बंद है या डेटा लोड हो रहा है। कृपया कुछ सेकंड बाद प्रयास करें।')
        else:
            send_telegram_message(chat_id, '✅ बॉट एक्टिव है! लाइव रिपोर्ट देखने के लिए `/status` टाइप करें।')

    except Exception as e:
        logging.error(f'Webhook Error: {e}')
    return 'OK', 200

# ==========================================
# 8. स्टार्टअप सेटअप (Webhook रजिस्टर करना)
# ==========================================
def setup_webhook():
    if WEBHOOK_URL and TELEGRAM_BOT_TOKEN:
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}'
        try:
            response = requests.get(url)
            if response.json().get('ok'):
                logging.info("Webhook successfully set!")
            else:
                logging.error(f"Webhook setup failed: {response.text}")
        except Exception as e:
            logging.error(f"Webhook setup error: {e}")

if __name__ == '__main__':
    setup_webhook()
    # लोकल टेस्टिंग के लिए:
    # port = int(os.environ.get('PORT', 5000))
    # app.run(host='0.0.0.0', port=port, debug=False)
    
    # प्रोडक्शन (Render/Heroku) के लिए Gunicorn का उपयोग करें:
    # gunicorn app:app
