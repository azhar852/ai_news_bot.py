import os
import logging
import json
import time
import sqlite3
import requests
import pandas as pd
import yfinance as yf
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
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')

app = Flask(__name__)

# ==========================================
# 2. SQLite डेटाबेस
# ==========================================
def init_db():
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)')
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Init Error: {e}")

def add_user(chat_id):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (chat_id) VALUES (?)', (chat_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Add User Error: {e}")

def get_all_users():
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id FROM users')
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users
    except Exception as e:
        logging.error(f"Get Users Error: {e}")
        return []

init_db()

# ==========================================
# 3. State Management
# ==========================================
STATE_FILE = 'bot_state.json'

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_trend": None, "last_price": 0.0}

def save_state(last_trend, last_price):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({"last_trend": last_trend, "last_price": last_price}, f)
    except Exception as e:
        logging.error(f"Save State Error: {e}")

bot_state = load_state()

# ==========================================
# 4. Telegram Functions (Clean UI with Inline Button)
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
        'reply_markup': {
            'inline_keyboard': [
                [{'text': '🔄 Refresh Status', 'callback_data': 'refresh_status'}]
            ]
        }
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 429:
            logging.warning("Rate limit hit. Sleeping...")
            time.sleep(5)
            requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f'Telegram Send Error: {e}')

def broadcast_to_all(text):
    users = get_all_users()
    for chat_id in users:
        send_telegram_message(chat_id, text)

# ==========================================
# 5. Technical Indicators (Pure Pandas)
# ==========================================
def calculate_rsi(data, window=14):
    delta = data['Close'].diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2) if not pd.isna(rsi.iloc[-1]) else 50.0

def calculate_vwap(data):
    typical_price = (data['High'] + data['Low'] + data['Close']) / 3
    vwap = (typical_price * data['Volume']).cumsum() / data['Volume'].cumsum()
    return round(vwap.iloc[-1], 2) if not pd.isna(vwap.iloc[-1]) else round(data['Close'].iloc[-1], 2)

def calculate_ema(data, span):
    ema = data['Close'].ewm(span=span, adjust=False).mean()
    return round(ema.iloc[-1], 2) if not pd.isna(ema.iloc[-1]) else round(data['Close'].iloc[-1], 2)

def calculate_sma(data, window):
    sma = data['Close'].rolling(window=window).mean()
    return round(sma.iloc[-1], 2) if not pd.isna(sma.iloc[-1]) else round(data['Close'].iloc[-1], 2)

def calculate_supertrend(data, period=10, multiplier=3):
    hl2 = (data['High'] + data['Low']) / 2
    atr = data['High'].rolling(window=period).max() - data['Low'].rolling(window=period).min()
    atr = atr.rolling(window=period).mean()
    
    lower_band = hl2 - (multiplier * atr)
    close = data['Close'].iloc[-1]
    
    if pd.isna(lower_band.iloc[-1]):
        return "NEUTRAL ⚪"
    
    if close > lower_band.iloc[-1]:
        return "BULLISH 🟢"
    else:
        return "BEARISH 🔴"

# ==========================================
# 6. Market Status
# ==========================================
def get_market_status(symbol='^NSEI'):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='5d', interval='5m')
        
        if data.empty or len(data) < 10:
            return None

        current_price = round(data['Close'].iloc[-1], 2)
        open_price = data['Open'].iloc[0]
        if open_price == 0:
            open_price = current_price
        
        change_pct = round(((current_price - open_price) / open_price) * 100, 2)
        
        rsi = calculate_rsi(data)
        vwap = calculate_vwap(data)
        ema_9 = calculate_ema(data, 9)
        sma_20 = calculate_sma(data, 20)
        supertrend = calculate_supertrend(data)

        if current_price > vwap and rsi > 50 and ema_9 > sma_20 and "BULLISH" in supertrend:
            trend = '🟢 UPTREND (मजबूत बुलिश)'
        elif current_price < vwap and rsi < 50 and ema_9 < sma_20 and "BEARISH" in supertrend:
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
            'supertrend': supertrend,
            'trend': trend
        }
    except Exception as e:
        logging.error(f'Market Status Error: {e}')
        return None

# ==========================================
# 7. Auto Scanner (APScheduler)
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

        if status_changed or price_diff >= 20:
            msg = (
                f"🚨 *MARKET TREND ALERT*\n\n"
                f"• Index: {market['symbol']}\n"
                f"• Price: `{current_price}` ({market['change']}%)\n"
                f"• Status: *{current_trend}*\n\n"
                f"📊 *Indicators:*\n"
                f"• RSI: `{market['rsi']}` | VWAP: `{market['vwap']}`\n"
                f"• EMA 9: `{market['ema_9']}` | SMA 20: `{market['sma_20']}`\n"
                f"• SuperTrend: `{market['supertrend']}`"
            )
            broadcast_to_all(msg)
            
            bot_state['last_trend'] = current_trend
            bot_state['last_price'] = current_price
            save_state(current_trend, current_price)

    except Exception as e:
        logging.error(f'Scanner Error: {e}')

scheduler = BackgroundScheduler()
scheduler.add_job(fast_market_trend_scanner, 'interval', seconds=90, max_instances=1)
scheduler.start()

# ==========================================
# 8. Flask Routes
# ==========================================
@app.route('/')
def home():
    return '✅ Clean Trend Bot is Active & Running!'

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json(force=True, silent=True)
        if not update:
            return 'OK', 200

        if 'callback_query' in update:
            callback = update['callback_query']
            chat_id = callback['message']['chat']['id']
            data = callback.get('data', '')
            
            if data == 'refresh_status':
                market = get_market_status('^NSEI')
                if market:
                    msg = (
                        f"📊 *LIVE MARKET STATUS (Refreshed)*\n\n"
                        f"• Index: {market['symbol']}\n"
                        f"• Price: `{market['price']}` ({market['change']}%)\n"
                        f"• Trend: *{market['trend']}*\n\n"
                        f"📈 *Indicators:*\n"
                        f"• RSI: `{market['rsi']}`\n"
                        f"• VWAP: `{market['vwap']}`\n"
                        f"• EMA 9: `{market['ema_9']}` | SMA 20: `{market['sma_20']}`\n"
                        f"• SuperTrend: `{market['supertrend']}`"
                    )
                    send_telegram_message(chat_id, msg)
                else:
                    send_telegram_message(chat_id, 'ℹ️ बाजार अभी बंद है। लाइव डेटा बाजार खुलने पर उपलब्ध होगा।')
            return 'OK', 200

        if 'message' in update:
            chat_id = update['message']['chat']['id']
            text = update['message'].get('text', '').strip().lower()

            add_user(chat_id)

            if text in ['/start', 'start', 'status', '/status', 'trend']:
                market = get_market_status('^NSEI')
                if market:
                    msg = (
                        f"📊 *LIVE MARKET STATUS*\n\n"
                        f"• Index: {market['symbol']}\n"
                        f"• Price: `{market['price']}` ({market['change']}%)\n"
                        f"• Trend: *{market['trend']}*\n\n"
                        f"📈 *Indicators:*\n"
                        f"• RSI: `{market['rsi']}`\n"
                        f"• VWAP: `{market['vwap']}`\n"
                        f"• EMA 9: `{market['ema_9']}` | SMA 20: `{market['sma_20']}`\n"
                        f"• SuperTrend: `{market['supertrend']}`\n\n"
                        f"🔔 _ऑटोमैटिक अलर्ट्स चालू हैं।_"
                    )
                    send_telegram_message(chat_id, msg)
                else:
                    msg = (
                        f"🤖 *BOT STATUS*\n\n"
                        f"• Status: 🟢 ACTIVE (Бot चालू है)\n"
                        f"• Market: Closed (बाजार बंद है)\n\n"
                        f"ℹ️ _बाजार बंद होने के कारण लाइव इंडिकेटर्स डेटा उपलब्ध नहीं है। बाजार खुलने पर यह स्वतः अपडेट हो जाएगा।_"
                    )
                    send_telegram_message(chat_id, msg)
            else:
                send_telegram_message(chat_id, '✅ बॉट एक्टिव है! लाइव रिपोर्ट देखने के लिए `/status` भेजें।')

    except Exception as e:
        logging.error(f'Webhook Error: {e}')
    return 'OK', 200

# ==========================================
# 9. Webhook Setup
# ==========================================
def setup_webhook():
    if WEBHOOK_URL and TELEGRAM_BOT_TOKEN:
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}/webhook'
        try:
            response = requests.get(url)
            if response.json().get('ok'):
                logging.info("✅ Webhook successfully set!")
            else:
                logging.error(f"❌ Webhook setup failed: {response.text}")
        except Exception as e:
            logging.error(f"Webhook setup error: {e}")
    else:
        logging.warning("⚠️ WEBHOOK_URL or TELEGRAM_BOT_TOKEN not set.")

if __name__ == '__main__':
    setup_webhook()
    port = int(os.environ.get('PORT', 10000))
    logging.info(f"🚀 Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
            
