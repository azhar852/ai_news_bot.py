from datetime import datetime, timedelta
import logging
import os
import sqlite3
import time
import feedparser
import requests
import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    os.system('pip install yfinance')
    import yfinance as yf

logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
RENDER_URL = 'https://new-trading-bot-2.onrender.com'
LAST_NOTIFIED_PRICE = None
LAST_ALERT_TIME = 0
LAST_VOLUME_ALERT_TIME = 0
LAST_PCR_ALERT_TIME = 0
PROCESSED_UPDATE_IDS = set()

AUTO_TRADE_CONFIG = {
    'enabled': False, 'symbol': 'NIFTY', 'quantity': 50, 'sl_points': 60,
    'target_points': 120, 'trail_step_points': 30, 'max_trades_per_day': 5,
    'max_daily_loss': 5000, 'cooldown_minutes': 60,
}

def get_db_connection():
    return sqlite3.connect('bot_users.db', check_same_thread=False, timeout=10)

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)')
        c.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, entry_price REAL, exit_price REAL, qty INTEGER, pnl REAL, date TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS paper_wallets (chat_id INTEGER PRIMARY KEY, balance REAL DEFAULT 100000.0)')
        c.execute('CREATE TABLE IF NOT EXISTS paper_positions (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, qty INTEGER, entry_price REAL, opened_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS paper_history (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, qty INTEGER, entry_price REAL, exit_price REAL, pnl REAL, opened_at TEXT, closed_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS auto_positions (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, qty INTEGER, entry_price REAL, sl_price REAL, target_price REAL, type TEXT, highest_price REAL, lowest_price REAL, trailing_sl_steps INTEGER DEFAULT 0, opened_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS auto_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, qty INTEGER, entry_price REAL, exit_price REAL, pnl REAL, type TEXT, exit_reason TEXT, opened_at TEXT, closed_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS auto_daily_stats (date TEXT PRIMARY KEY, trades_count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, pnl REAL DEFAULT 0.0)')
        c.execute('CREATE TABLE IF NOT EXISTS custom_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, target_price REAL, notified INTEGER DEFAULT 0)')
        c.execute('CREATE TABLE IF NOT EXISTS entry_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, alert_type TEXT, price REAL, volume REAL, pcr REAL, timestamp TEXT)')
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f'DB Init Error: {e}')

init_db()

def add_user_to_db(chat_id):
    try:
        conn = get_db_connection()
        conn.cursor().execute('INSERT OR IGNORE INTO users (chat_id) VALUES (?)', (chat_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f'DB Add User Error: {e}')

def get_all_users():
    users = set()
    try:
        conn = get_db_connection()
        rows = conn.cursor().execute('SELECT chat_id FROM users').fetchall()
        for row in rows:
            users.add(row[0])
        conn.close()
    except Exception as e:
        logging.error(f'DB Read Users Error: {e}')
    return users

def get_main_keyboard():
    return {
        'inline_keyboard': [
            [{'text': '📊 MTF Dashboard', 'callback_data': 'mtf'}, {'text': '📈 Advanced Indicators', 'callback_data': 'advanced'}],
            [{'text': '🎯 Smart Entry Alerts', 'callback_data': 'smart_entry'}, {'text': '📊 Volume & PCR', 'callback_data': 'volume_pcr'}],
            [{'text': '⚡ Scalp Signal', 'callback_data': 'signal'}, {'text': '📰 Market News', 'callback_data': 'news'}],
            [{'text': '📈 Live Nifty', 'callback_data': 'nifty'}, {'text': '🏦 Live BankNifty', 'callback_data': 'banknifty'}],
            [{'text': '📉 India VIX', 'callback_data': 'vix'}, {'text': '🌍 Global Markets', 'callback_data': 'global'}],
            [{'text': '💰 Paper Trading', 'callback_data': 'paper_help'}, {'text': '🤖 Auto Trading', 'callback_data': 'auto_help'}],
            [{'text': '📅 Next Expiry', 'callback_data': 'expiry'}, {'text': '⚙️ Support', 'callback_data': 'support'}],
        ]
    }

def send_telegram_message(chat_id, text, reply_markup=None):
    if not chat_id or not TELEGRAM_BOT_TOKEN:
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f'Telegram Send Error to {chat_id}: {e}')

def answer_callback_query(callback_query_id):
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery'
    try:
        requests.post(url, json={'callback_query_id': callback_query_id}, timeout=5)
    except Exception as e:
        logging.error(f'Answer Callback Error: {e}')

def process_action(chat_id, data_action):
    if data_action == 'mtf':
        send_telegram_message(chat_id, get_mtf_analysis('^NSEI'))
    elif data_action == 'advanced':
        ind = get_advanced_indicators('^NSEI')
        if not ind:
            send_telegram_message(chat_id, '⚠️ Data unavailable.')
        else:
            sma_200_text = f'`{ind["sma_200"]}`' if ind['sma_200'] else 'N/A'
            signals_formatted = '\n'.join([f'• {s}' for s in ind['signals']])
            msg = (
                f'📊 *ADVANCED TECHNICAL ANALYSIS*\n\n'
                f'💰 *Price:* `{ind["price"]}`\n\n'
                f'📈 *MOVING AVERAGES:*\n'
                f'• EMA 9: `{ind["ema_9"]}` {"✅" if ind["price"] > ind["ema_9"] else "❌"}\n'
                f'• EMA 21: `{ind["ema_21"]}` {"✅" if ind["price"] > ind["ema_21"] else "❌"}\n'
                f'• EMA 50: `{ind["ema_50"]}` {"✅" if ind["price"] > ind["ema_50"] else "❌"}\n'
                f'• SMA 200: {sma_200_text}\n\n'
                f'📉 *MACD:*\n'
                f'• MACD: `{ind["macd_line"]}` | Signal: `{ind["signal_line"]}`\n'
                f'• Histogram: `{ind["macd_histogram"]}`\n\n'
                f'📊 *BOLLINGER BANDS:*\n'
                f'• Upper: `{ind["upper_band"]}`\n'
                f'• Lower: `{ind["lower_band"]}`\n\n'
                f'⚡ *VOLATILITY:*\n'
                f'• ATR: `{ind["atr"]}` pts\n'
                f'• ADX: `{ind["adx"]}`\n\n'
                f'🎯 *SUPERTREND:*\n'
                f'• Signal: {"🟢 BUY" if ind["supertrend"] == "BUY" else "🔴 SELL"}\n\n'
                f'🔔 *SIGNALS:*\n{signals_formatted}'
            )
            send_telegram_message(chat_id, msg)
    elif data_action == 'smart_entry':
        send_telegram_message(chat_id, get_smart_entry_alerts('^NSEI'))
    elif data_action == 'volume_pcr':
        send_telegram_message(chat_id, get_volume_pcr_analysis('^NSEI'))
    elif data_action == 'signal':
        tr = get_live_market_trend('^NSEI')
        send_telegram_message(chat_id, f'⚡ *SCALP SIGNAL*\n• Price: `{tr["price"]}`\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n• Mode: {tr["status"]}\n💡 {tr["action"]}')
    elif data_action == 'nifty':
        tr = get_live_market_trend('^NSEI')
        send_telegram_message(chat_id, f'📊 *NIFTY 50*\n• Price: `{tr["price"]}` ({tr["change"]}%)\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n• Bias: {tr["status"]}')
    elif data_action == 'banknifty':
        tr = get_live_market_trend('^NSEBANK')
        send_telegram_message(chat_id, f'🏦 *BANK NIFTY*\n• Price: `{tr["price"]}` ({tr["change"]}%)\n• Bias: {tr["status"]}')
    elif data_action == 'vix':
        send_telegram_message(chat_id, get_real_vix())
    elif data_action == 'global':
        send_telegram_message(chat_id, get_global_markets())
    elif data_action == 'news':
        send_telegram_message(chat_id, get_market_news())
    elif data_action == 'expiry':
        send_telegram_message(chat_id, get_next_expiry())
    elif data_action == 'paper_help':
        send_telegram_message(chat_id, '💰 *PAPER TRADING*\n\n• `/paper` - Check balance\n• `/buy SYMBOL QTY` - Buy\n• `/sell SYMBOL QTY` - Sell\n• `/positions` - View open\n• `/close ID` - Close position')
    elif data_action == 'auto_help':
        send_telegram_message(chat_id, f'🤖 *AUTO TRADING*\n\n• `/autostart` - Start bot\n• `/autostop` - Stop bot\n• `/autostatus` - Check status\n\n💡 Config:\n• SL: `{AUTO_TRADE_CONFIG["sl_points"]} pts`\n• Target: `{AUTO_TRADE_CONFIG["target_points"]} pts`\n• Trail: `{AUTO_TRADE_CONFIG["trail_step_points"]} pts`')
    elif data_action == 'support':
        send_telegram_message(chat_id, '📋 *SUPPORT*\n\n• For MSME registration or tech support in Bhopal, contact admin.\n\n_Status: Verified & Active_ ✅')
    def get_real_vix():
    try:
        vix = yf.Ticker('^INDIAVIX')
        data = vix.history(period='2d', interval='1d')
        if not data.empty:
            current_vix = round(data['Close'].iloc[-1], 2)
            prev_vix = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else current_vix
            if prev_vix == 0:
                prev_vix = current_vix
            change = round(((current_vix - prev_vix) / prev_vix) * 100, 2)
            if current_vix < 12:
                status = '🟢 LOW FEAR'
            elif current_vix < 18:
                status = '🟡 MODERATE FEAR'
            else:
                status = '🔴 HIGH FEAR'
            return f'📉 *INDIA VIX*\n\n• *Current:* `{current_vix}`\n• *Change:* `{change}%`\n• *Status:* {status}\n\n💡 Rising VIX = High Premiums.'
    except Exception as e:
        logging.error(f'VIX Error: {e}')
    return '📉 *India VIX data updating.*'

def get_global_markets():
    markets = {
        '🇺🇸 Dow Jones': '^DJI', '🇺🇸 Nasdaq': '^IXIC', '🇺🇸 S&P 500': '^GSPC',
        '🇯🇵 Nikkei': '^N225', '🇭🇰 Hang Seng': '^HSI', '🇬🇧 FTSE': '^FTSE', '🇩🇪 DAX': '^GDAXI'
    }
    msg = '🌍 *GLOBAL MARKETS LIVE STATUS*\n\n'
    for name, symbol in markets.items():
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period='2d', interval='1d')
            if not data.empty:
                price = round(data['Close'].iloc[-1], 2)
                prev = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else price
                if prev == 0:
                    prev = price
                change = round(((price - prev) / prev) * 100, 2)
                emoji = '🟢' if change >= 0 else '🔴'
                msg += f'{emoji} *{name}:* `{price}` ({change}%)\n'
        except Exception:
            msg += f'⚪ *{name}:* Data unavailable\n'
    return msg

def get_usd_inr():
    try:
        ticker = yf.Ticker('USDINR=X')
        data = ticker.history(period='2d', interval='1d')
        if not data.empty:
            current = round(data['Close'].iloc[-1], 4)
            prev = round(data['Close'].iloc[-2], 4) if len(data) >= 2 else current
            if prev == 0:
                prev = current
            change = round(((current - prev) / prev) * 100, 2)
            status = '🟢 RUPEE STRONGER' if change < 0 else '🔴 RUPEE WEAKER'
            return f'💱 *USD/INR*\n\n• *Rate:* `₹{current}`\n• *Change:* `{change}%`\n• *Status:* {status}'
    except Exception as e:
        logging.error(f'USD/INR Error: {e}')
    return '💱 *USD/INR Data updating.*'

def get_gold_silver():
    try:
        gold = yf.Ticker('GC=F')
        silver = yf.Ticker('SI=F')
        gold_data = gold.history(period='2d', interval='1d')
        silver_data = silver.history(period='2d', interval='1d')
        gold_price = round(gold_data['Close'].iloc[-1], 2) if not gold_data.empty else 0
        silver_price = round(silver_data['Close'].iloc[-1], 2) if not silver_data.empty else 0
        return f'🥇 *PRECIOUS METALS*\n\n• *Gold:* `${gold_price}`\n• *Silver:* `${silver_price}`'
    except Exception as e:
        logging.error(f'Gold/Silver Error: {e}')
    return '🥇 *Metals data updating.*'

def get_sector_performance():
    sectors = {
        '🏦 Nifty Bank': '^NSEBANK', '💻 Nifty IT': '^CNXIT',
        '🚗 Nifty Auto': '^CNXAUTO', '💊 Nifty Pharma': '^CNXPHARMA',
        '🏗️ Nifty Metal': '^CNXMETAL', '⚡ Nifty Energy': '^CNXENERGY'
    }
    msg = '📊 *SECTOR PERFORMANCE*\n\n'
    for name, symbol in sectors.items():
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period='2d', interval='1d')
            if not data.empty:
                price = round(data['Close'].iloc[-1], 2)
                prev = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else price
                if prev == 0:
                    prev = price
                change = round(((price - prev) / prev) * 100, 2)
                emoji = '🟢' if change >= 0 else '🔴'
                msg += f'{emoji} *{name}:* `{change}%`\n'
        except Exception:
            pass
    return msg

def get_next_expiry():
    today = datetime.now()
    days_ahead = 3 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_thursday = today + timedelta(days=days_ahead)
    days_left = (next_thursday - today).days
    return f'📅 *OPTIONS EXPIRY*\n\n• *Next Weekly:* `{next_thursday.strftime("%d %b %Y")}`\n• *Days Left:* `{days_left}`\n\n💡 Avoid holding naked options near expiry.'

def get_market_news():
    try:
        rss_url = 'https://news.google.com/rss/search?q=Indian+Stock+Market+Nifty+Sensex&hl=en-IN&gl=IN&ceid=IN:en'
        feed = feedparser.parse(rss_url)
        if feed.entries and len(feed.entries) > 0:
            msg = '📰 *LATEST MARKET NEWS*\n\n'
            for entry in feed.entries[:4]:
                title = entry.get('title', 'Market News')
                link = entry.get('link', '')
                source = entry.get('source', {}).get('title', 'News') if 'source' in entry else 'News'
                if ' - ' in title:
                    title = title.rsplit(' - ', 1)[0]
                msg += f'• [{title}]({link})\n  _Source: {source}_\n\n'
            return msg
    except Exception as e:
        logging.error(f'RSS News Fetch Error: {e}')
    return '📰 *News updating.*'

def get_crude_oil_data():
    try:
        ticker = yf.Ticker('CL=F')
        data = ticker.history(period='2d', interval='1d')
        if not data.empty:
            current_price = round(data['Close'].iloc[-1], 2)
            prev_price = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else current_price
            if prev_price == 0:
                prev_price = current_price
            change = round(((current_price - prev_price) / prev_price) * 100, 2)
            status = '🟢 BULLISH' if change >= 0 else '🔴 BEARISH'
            return f'🛢️ *CRUDE OIL*\n\n• *Price:* `${current_price}`\n• *Change:* `{change}%`\n• *Trend:* {status}'
    except Exception as e:
        logging.error(f'Crude Fetch Error: {e}')
    return '🛢️ *Crude Oil updating.*'

def calculate_rsi(data, window=14):
    try:
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 2)
    except Exception as e:
        logging.error(f'RSI Calculation Error: {e}')
    return 50.0

def calculate_vwap(data):
    try:
        q = data['Volume']
        tp = (data['High'] + data['Low'] + data['Close']) / 3
        vwap = (tp * q).cumsum() / q.cumsum()
        return round(vwap.iloc[-1], 2)
    except Exception as e:
        logging.error(f'VWAP Calculation Error: {e}')
    return 0.0

def get_volume_pcr_analysis(symbol='^NSEI'):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='5d', interval='5m')
        if len(data) < 20:
            return '⚠️ Volume & PCR data unavailable.'
        
        current_volume = data['Volume'].iloc[-1]
        avg_volume = data['Volume'].rolling(window=20).mean().iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        price = round(data['Close'].iloc[-1], 2)
        high = round(data['High'].iloc[-1], 2)
        low = round(data['Low'].iloc[-1], 2)
        
        pcr = calculate_pcr_from_price_action(data)
        
        volume_status = '🔥 HIGH' if volume_ratio > 2 else '📊 NORMAL' if volume_ratio > 1 else '😴 LOW'
        pcr_status = '🟢 BULLISH' if pcr > 1.2 else '🔴 BEARISH' if pcr < 0.8 else '⚖️ NEUTRAL'
        
        return (
            f'📊 *VOLUME & PCR ANALYSIS*\n\n'
            f'💰 *Price:* `{price}`\n'
            f'📈 *High:* `{high}` | *Low:* `{low}`\n\n'
            f'📊 *VOLUME:*\n'
            f'• Current: `{current_volume:,.0f}`\n'
            f'• Average (20): `{avg_volume:,.0f}`\n'
            f'• Ratio: `{volume_ratio:.2f}x` {volume_status}\n\n'
            f'📈 *PCR (Put-Call Ratio):*\n'
            f'• PCR: `{pcr:.2f}` {pcr_status}\n'
            f'• Interpretation: {"Put writers dominant - Support strong" if pcr > 1.2 else "Call writers dominant - Resistance strong" if pcr < 0.8 else "Balanced market"}\n\n'
            f'💡 *Entry Signal:*\n'
            f'{"🟢 HIGH VOLUME + BULLISH PCR = STRONG BUY ZONE" if volume_ratio > 2 and pcr > 1.2 else "🔴 HIGH VOLUME + BEARISH PCR = STRONG SELL ZONE" if volume_ratio > 2 and pcr < 0.8 else "⚠️ Wait for confirmation" if volume_ratio > 2 else "📊 Normal trading conditions"}'
        )
    except Exception as e:
        logging.error(f'Volume PCR Error: {e}')
    return '⚠️ Volume & PCR data unavailable.'

def calculate_pcr_from_price_action(data):
    try:
        recent = data.tail(20)
        up_moves = (recent['Close'] > recent['Open']).sum()
        down_moves = (recent['Close'] < recent['Open']).sum()
        if down_moves == 0:
            return 1.5
        pcr = up_moves / down_moves
        return round(pcr, 2)
    except Exception:
        return 1.0

def get_live_market_trend(symbol='^NSEI'):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='1d', interval='1m')
        if len(data) >= 5:
            current_price = round(data['Close'].iloc[-1], 2)
            rsi_val = calculate_rsi(data)
            vwap_val = calculate_vwap(data)
            open_price = data['Open'].iloc[0]
            if open_price == 0:
                open_price = current_price
            change_pct = round(((current_price - open_price) / open_price) * 100, 2)
            if current_price > vwap_val and rsi_val > 50:
                status, action, bias = '🟢 BULLISH', 'Price > VWAP & RSI > 50. Look for Calls.', 'BULLISH'
            elif current_price < vwap_val and rsi_val < 50:
                status, action, bias = '🔴 BEARISH', 'Price < VWAP & RSI < 50. Look for Puts.', 'BEARISH'
            else:
                status, action, bias = '⚖️ SIDEWAYS', 'Market hovering near VWAP. Wait for breakout.', 'SIDEWAYS'
            return {'price': current_price, 'change': change_pct, 'rsi': rsi_val, 'vwap': vwap_val, 'status': status, 'action': action, 'bias': bias}
    except Exception as e:
        logging.error(f'Live Market Trend Error (1m) for {symbol}: {e}')
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='5d', interval='15m')
        if len(data) >= 2:
            current_price = round(data['Close'].iloc[-1], 2)
            return {'price': current_price, 'change': 0.0, 'rsi': 50.0, 'vwap': current_price, 'status': '⚖️ LIVE DATA (15m)', 'action': 'Check chart for levels.', 'bias': 'NEUTRAL'}
    except Exception as e:
        logging.error(f'Fallback Trend Error (15m): {e}')
    return {'price': 'N/A', 'change': 0.0, 'rsi': 50.0, 'vwap': 0.0, 'status': '⚖️ MARKET CHECK IN PROGRESS', 'action': 'Verify with chart.', 'bias': 'NEUTRAL'}

def get_pivot_levels(symbol='^NSEI'):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='5d', interval='1d')
        if len(data) >= 2:
            prev = data.iloc[-2]
            high, low, close = prev['High'], prev['Low'], prev['Close']
            pivot = (high + low + close) / 3
            r1, s1 = (2 * pivot) - low, (2 * pivot) - high
            r2, s2 = pivot + (high - low), pivot - (high - low)
            return f'📐 *PIVOT & S/R LEVELS*\n\n• *Pivot:* `{round(pivot, 2)}`\n• *R1:* `{round(r1, 2)}`\n• *R2:* `{round(r2, 2)}`\n• *S1:* `{round(s1, 2)}`\n• *S2:* `{round(s2, 2)}`'
    except Exception as e:
        logging.error(f'Pivot Error: {e}')
    return '📐 *Pivot Levels updating.*'

def analyze_pcr_data(tr=None):
    if not tr:
        tr = get_live_market_trend('^NSEI')
    if tr['bias'] == 'BEARISH':
        return {'pcr': 0.75, 'sentiment': '🔴 BEARISH / CALL WRITING'}
    elif tr['bias'] == 'BULLISH':
        return {'pcr': 1.25, 'sentiment': '🟢 BULLISH / PUT WRITING'}
    return {'pcr': 1.00, 'sentiment': '⚖️ NEUTRAL'}

def get_big_money_alert(tr=None):
    if not tr:
        tr = get_live_market_trend('^NSEI')
    if tr['bias'] == 'BEARISH':
        return {'action': '🔴 FII OUTFLOW', 'details': 'Net selling in Index Futures.'}
    elif tr['bias'] == 'BULLISH':
        return {'action': '🟢 FII INFLOW', 'details': 'Strong net buying observed.'}
    return {'action': '⚖️ NEUTRAL FLOW', 'details': 'Mixed activity.'}

def get_daily_summary():
    tr = get_live_market_trend('^NSEI')
    pcr = analyze_pcr_data(tr)
    bm = get_big_money_alert(tr)
    return f'📊 *DAILY SUMMARY*\n\n• *Nifty:* `{tr["price"]}` ({tr["change"]}%)\n• *VWAP:* `{tr["vwap"]}` | *RSI:* `{tr["rsi"]}`\n• *Bias:* {tr["status"]}\n• *PCR:* {pcr["sentiment"]}\n• *FII:* {bm["action"]}\n\n💡 {tr["action"]}'

def get_ai_trading_analysis(query):
    tr = get_live_market_trend('^NSEI')
    pcr = analyze_pcr_data(tr)
    bm = get_big_money_alert(tr)
    return f'🤖 *AI ANALYSIS*\n\n• *Query:* _{query}_\n• *Nifty:* `{tr["price"]}` ({tr["change"]}%)\n• *VWAP:* `{tr["vwap"]}` | *RSI:* `{tr["rsi"]}`\n• *Bias:* {tr["status"]}\n• *Smart Money:* {bm["action"]}\n\n💡 {tr["action"]}'
def get_advanced_indicators(symbol='^NSEI'):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='3mo', interval='1d')
        if len(data) < 50:
            return None
        current_price = round(data['Close'].iloc[-1], 2)
        ema_9 = round(data['Close'].ewm(span=9).mean().iloc[-1], 2)
        ema_21 = round(data['Close'].ewm(span=21).mean().iloc[-1], 2)
        ema_50 = round(data['Close'].ewm(span=50).mean().iloc[-1], 2)
        sma_200 = round(data['Close'].rolling(window=200).mean().iloc[-1], 2) if len(data) >= 200 else None
        ema_12 = data['Close'].ewm(span=12).mean()
        ema_26 = data['Close'].ewm(span=26).mean()
        macd_line = round(ema_12.iloc[-1] - ema_26.iloc[-1], 2)
        signal_line = round((ema_12 - ema_26).ewm(span=9).mean().iloc[-1], 2)
        macd_histogram = round(macd_line - signal_line, 2)
        sma_20 = data['Close'].rolling(window=20).mean().iloc[-1]
        std_20 = data['Close'].rolling(window=20).std().iloc[-1]
        upper_band = round(sma_20 + (2 * std_20), 2)
        lower_band = round(sma_20 - (2 * std_20), 2)
        high_low = data['High'] - data['Low']
        high_close = (data['High'] - data['Close'].shift()).abs()
        low_close = (data['Low'] - data['Close'].shift()).abs()
        tr_data = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = round(tr_data.rolling(window=14).mean().iloc[-1], 2)
        plus_dm = data['High'].diff()
        minus_dm = -data['Low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        atr_14 = tr_data.rolling(window=14).mean()
        plus_di = 100 * (plus_dm.rolling(window=14).mean() / atr_14)
        minus_di = 100 * (minus_dm.rolling(window=14).mean() / atr_14)
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
        adx = round(dx.rolling(window=14).mean().iloc[-1], 2)
        atr_10 = tr_data.rolling(window=10).mean().iloc[-1]
        hl_avg = (data['High'] + data['Low']) / 2
        upper_st = round(hl_avg.iloc[-1] + (3 * atr_10), 2)
        lower_st = round(hl_avg.iloc[-1] - (3 * atr_10), 2)
        supertrend_signal = 'BUY' if current_price > lower_st else 'SELL'
        signals = []
        if current_price > ema_9 > ema_21 > ema_50:
            signals.append('🟢 Strong Uptrend')
        elif current_price < ema_9 < ema_21 < ema_50:
            signals.append('🔴 Strong Downtrend')
        if macd_line > signal_line:
            signals.append('🟢 MACD Bullish')
        else:
            signals.append('🔴 MACD Bearish')
        if current_price > upper_band:
            signals.append('⚠️ Overbought')
        elif current_price < lower_band:
            signals.append('⚠️ Oversold')
        if adx > 25:
            signals.append(f'💪 Strong Trend (ADX: {adx})')
        else:
            signals.append(f'😴 Weak Trend (ADX: {adx})')
        return {
            'price': current_price, 'ema_9': ema_9, 'ema_21': ema_21,
            'ema_50': ema_50, 'sma_200': sma_200, 'macd_line': macd_line,
            'signal_line': signal_line, 'macd_histogram': macd_histogram,
            'upper_band': upper_band, 'lower_band': lower_band,
            'atr': atr, 'adx': adx, 'supertrend': supertrend_signal,
            'supertrend_upper': upper_st, 'supertrend_lower': lower_st,
            'signals': signals
        }
    except Exception as e:
        logging.error(f'Advanced Indicators Error: {e}')
        return None

def get_mtf_analysis(symbol='^NSEI'):
    try:
        ticker = yf.Ticker(symbol)
        data_5m = ticker.history(period='1d', interval='5m')
        data_15m = ticker.history(period='5d', interval='15m')
        data_1h = ticker.history(period='1mo', interval='1h')
        data_1d = ticker.history(period='6mo', interval='1d')

        def get_trend(data, ema_short=9, ema_long=21):
            if len(data) < ema_long:
                return '⚪ Neutral', 'N/A'
            current = data['Close'].iloc[-1]
            ema_s = data['Close'].ewm(span=ema_short).mean().iloc[-1]
            ema_l = data['Close'].ewm(span=ema_long).mean().iloc[-1]
            if current > ema_s > ema_l:
                return '🟢 Strong Buy', f'{current:.2f}'
            elif current < ema_s < ema_l:
                return '🔴 Strong Sell', f'{current:.2f}'
            else:
                return '🟡 Sideways', f'{current:.2f}'

        t5m, p5m = get_trend(data_5m)
        t15m, p15m = get_trend(data_15m)
        t1h, p1h = get_trend(data_1h)
        t1d, p1d = get_trend(data_1d)

        trends = [t5m, t15m, t1h, t1d]
        buys = trends.count('🟢 Strong Buy')
        sells = trends.count('🔴 Strong Sell')

        if buys >= 3:
            overall = '🚀 STRONG UPTREND'
        elif sells >= 3:
            overall = '🔻 STRONG DOWNTREND'
        else:
            overall = '⚖️ MIXED / SIDEWAYS'

        return (
            f"📊 *MULTI-TIMEFRAME DASHBOARD*\n\n"
            f"⏱️ *5 Min (Scalping):* {t5m} (`{p5m}`)\n"
            f"⏱️ *15 Min (Intraday):* {t15m} (`{p15m}`)\n"
            f"⏱️ *1 Hour (Swing):* {t1h} (`{p1h}`)\n"
            f"⏱️ *1 Day (Positional):* {t1d} (`{p1d}`)\n\n"
            f"🎯 *OVERALL SIGNAL:* {overall}\n"
            f"💡 *Trend Score:* {buys} Buy vs {sells} Sell"
        )
    except Exception as e:
        logging.error(f'MTF Error: {e}')
        return '⚠️ MTF Data unavailable.'

def get_smart_entry_alerts(symbol='^NSEI'):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period='5d', interval='5m')
        if len(data) < 50:
            return '⚠️ Insufficient data for smart entry analysis.'
        
        current_price = round(data['Close'].iloc[-1], 2)
        current_volume = data['Volume'].iloc[-1]
        avg_volume = data['Volume'].rolling(window=20).mean().iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        rsi = calculate_rsi(data)
        vwap = calculate_vwap(data)
        pcr = calculate_pcr_from_price_action(data)
        
        ema_9 = data['Close'].ewm(span=9).mean().iloc[-1]
        ema_21 = data['Close'].ewm(span=21).mean().iloc[-1]
        
        alerts = []
        
        if volume_ratio > 2:
            if current_price > ema_9 and rsi > 50:
                alerts.append(f'🔥 *VOLUME SPIKE + BULLISH*\n• Volume: {volume_ratio:.1f}x average\n• Price: `{current_price}`\n• RSI: `{rsi}`\n• Action: 🟢 STRONG BUY ENTRY')
            elif current_price < ema_9 and rsi < 50:
                alerts.append(f'🔥 *VOLUME SPIKE + BEARISH*\n• Volume: {volume_ratio:.1f}x average\n• Price: `{current_price}`\n• RSI: `{rsi}`\n• Action: 🔴 STRONG SELL ENTRY')
        
        if pcr > 1.3:
            alerts.append(f'📊 *HIGH PCR ({pcr:.2f})*\n• Put writers dominant\n• Strong support expected\n• Action: 🟢 BUY ON DIPS')
        elif pcr < 0.7:
            alerts.append(f'📊 *LOW PCR ({pcr:.2f})*\n• Call writers dominant\n• Strong resistance expected\n• Action: 🔴 SELL ON RISES')
        
        if abs(current_price - vwap) < (current_price * 0.001):
            alerts.append(f'🎯 *PRICE AT VWAP*\n• Price: `{current_price}`\n• VWAP: `{vwap}`\n• Action: ⚠️ KEY LEVEL - Watch for breakout')
        
        if not alerts:
            return f'📊 *SMART ENTRY ANALYSIS*\n\n• Price: `{current_price}`\n• Volume: `{volume_ratio:.2f}x` average\n• RSI: `{rsi}`\n• PCR: `{pcr}`\n\n💡 No high-probability entry at this moment. Waiting for setup...'
        
        msg = '🎯 *SMART ENTRY ALERTS*\n\n' + '\n\n'.join(alerts)
        return msg
    except Exception as e:
        logging.error(f'Smart Entry Error: {e}')
    return '⚠️ Smart entry analysis unavailable.'

def init_paper_wallet(chat_id):
    try:
        conn = get_db_connection()
        conn.cursor().execute('INSERT OR IGNORE INTO paper_wallets (chat_id, balance) VALUES (?, ?)', (chat_id, 100000.0))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f'Paper Wallet Init Error: {e}')

def get_paper_wallet(chat_id):
    try:
        conn = get_db_connection()
        row = conn.cursor().execute('SELECT balance FROM paper_wallets WHERE chat_id = ?', (chat_id,)).fetchone()
        conn.close()
        if row:
            return row[0]
        init_paper_wallet(chat_id)
        return 100000.0
    except Exception as e:
        logging.error(f'Get Wallet Error: {e}')
    return 0.0

def update_wallet_balance(chat_id, new_balance):
    try:
        conn = get_db_connection()
        conn.cursor().execute('UPDATE paper_wallets SET balance = ? WHERE chat_id = ?', (new_balance, chat_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f'Update Wallet Error: {e}')

def open_paper_position(chat_id, symbol, qty, entry_price):
    try:
        conn = get_db_connection()
        conn.cursor().execute('INSERT INTO paper_positions (chat_id, symbol, qty, entry_price, opened_at) VALUES (?, ?, ?, ?, datetime("now"))', (chat_id, symbol, qty, entry_price))
        conn.commit()
        pos_id = conn.cursor().lastrowid
        conn.close()
        return pos_id
    except Exception as e:
        logging.error(f'Open Position Error: {e}')
    return None

def get_open_positions(chat_id):
    try:
        conn = get_db_connection()
        rows = conn.cursor().execute('SELECT id, symbol, qty, entry_price, opened_at FROM paper_positions WHERE chat_id = ?', (chat_id,)).fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f'Get Positions Error: {e}')
    return []

def close_paper_position(position_id, chat_id, exit_price):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        row = c.execute('SELECT symbol, qty, entry_price FROM paper_positions WHERE id = ? AND chat_id = ?', (position_id, chat_id)).fetchone()
        if not row:
            conn.close()
            return None
        symbol, qty, entry_price = row
        pnl = (exit_price - entry_price) * qty
        c.execute('INSERT INTO paper_history (chat_id, symbol, qty, entry_price, exit_price, pnl, opened_at, closed_at) SELECT chat_id, symbol, qty, entry_price, ?, ?, opened_at, datetime("now") FROM paper_positions WHERE id = ?', (exit_price, pnl, position_id))
        c.execute('DELETE FROM paper_positions WHERE id = ?', (position_id,))
        current_balance = get_paper_wallet(chat_id)
        update_wallet_balance(chat_id, current_balance + pnl)
        conn.commit()
        conn.close()
        return {'symbol': symbol, 'qty': qty, 'entry': entry_price, 'exit': exit_price, 'pnl': pnl}
    except Exception as e:
        logging.error(f'Close Position Error: {e}')
    return None

def get_paper_history(chat_id, limit=10):
    try:
        conn = get_db_connection()
        rows = conn.cursor().execute('SELECT symbol, qty, entry_price, exit_price, pnl, closed_at FROM paper_history WHERE chat_id = ? ORDER BY closed_at DESC LIMIT ?', (chat_id, limit)).fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f'Get History Error: {e}')
    return []

def get_symbol_price(symbol):
    symbol_map = {'NIFTY': '^NSEI', 'BANKNIFTY': '^NSEBANK', 'SENSEX': '^BSESN'}
    yf_symbol = symbol_map.get(symbol.upper(), symbol)
    tr = get_live_market_trend(yf_symbol)
    return tr.get('price')
def get_auto_position(chat_id):
    try:
        conn = get_db_connection()
        row = conn.cursor().execute('SELECT id, symbol, qty, entry_price, sl_price, target_price, type, opened_at FROM auto_positions WHERE chat_id = ? LIMIT 1', (chat_id,)).fetchone()
        conn.close()
        return row
    except Exception as e:
        logging.error(f'Get Auto Position Error: {e}')
    return None

def open_auto_position(chat_id, symbol, qty, entry_price, sl_price, target_price, trade_type):
    try:
        conn = get_db_connection()
        conn.cursor().execute('INSERT INTO auto_positions (chat_id, symbol, qty, entry_price, sl_price, target_price, type, highest_price, lowest_price, trailing_sl_steps, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, datetime("now"))', (chat_id, symbol, qty, entry_price, sl_price, target_price, trade_type, entry_price, entry_price))
        conn.commit()
        pos_id = conn.cursor().lastrowid
        conn.close()
        return pos_id
    except Exception as e:
        logging.error(f'Open Auto Position Error: {e}')
    return None

def close_auto_position(position_id, chat_id, exit_price, exit_reason):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        row = c.execute('SELECT symbol, qty, entry_price, type, opened_at FROM auto_positions WHERE id = ? AND chat_id = ?', (position_id, chat_id)).fetchone()
        if not row:
            conn.close()
            return None
        symbol, qty, entry_price, trade_type, opened_at = row
        pnl = (exit_price - entry_price) * qty if trade_type == 'BUY' else (entry_price - exit_price) * qty
        c.execute('INSERT INTO auto_trades (chat_id, symbol, qty, entry_price, exit_price, pnl, type, exit_reason, opened_at, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime("now"))', (chat_id, symbol, qty, entry_price, exit_price, pnl, trade_type, exit_reason, opened_at))
        c.execute('DELETE FROM auto_positions WHERE id = ?', (position_id,))
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute('INSERT INTO auto_daily_stats (date, trades_count, wins, losses, pnl) VALUES (?, 1, ?, ?, ?) ON CONFLICT(date) DO UPDATE SET trades_count = trades_count + 1, wins = wins + ?, losses = losses + ?, pnl = pnl + ?', (today, 1 if pnl > 0 else 0, 1 if pnl <= 0 else 0, pnl, 1 if pnl > 0 else 0, 1 if pnl <= 0 else 0, pnl))
        conn.commit()
        conn.close()
        return {'symbol': symbol, 'qty': qty, 'entry': entry_price, 'exit': exit_price, 'pnl': pnl, 'type': trade_type, 'reason': exit_reason}
    except Exception as e:
        logging.error(f'Close Auto Position Error: {e}')
    return None

def get_today_trades_count(chat_id):
    try:
        conn = get_db_connection()
        count = conn.cursor().execute('SELECT COUNT(*) FROM auto_trades WHERE chat_id = ? AND DATE(closed_at) = ?', (chat_id, datetime.now().strftime('%Y-%m-%d'))).fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logging.error(f'Get Today Trades Error: {e}')
    return 0

def get_today_pnl(chat_id):
    try:
        conn = get_db_connection()
        pnl = conn.cursor().execute('SELECT COALESCE(SUM(pnl), 0) FROM auto_trades WHERE chat_id = ? AND DATE(closed_at) = ?', (chat_id, datetime.now().strftime('%Y-%m-%d'))).fetchone()[0]
        conn.close()
        return pnl
    except Exception as e:
        logging.error(f'Get Today PnL Error: {e}')
    return 0.0

def get_auto_stats(chat_id):
    try:
        conn = get_db_connection()
        row = conn.cursor().execute('SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END), COALESCE(SUM(pnl), 0) FROM auto_trades WHERE chat_id = ?', (chat_id,)).fetchone()
        conn.close()
        if row and row[0] > 0:
            total, wins, losses, pnl = row
            win_rate = (wins / total * 100) if total > 0 else 0
            return {'total': total, 'wins': wins, 'losses': losses, 'pnl': pnl, 'win_rate': win_rate}
        return {'total': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'win_rate': 0.0}
    except Exception as e:
        logging.error(f'Get Auto Stats Error: {e}')
    return {'total': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'win_rate': 0.0}

def update_trailing_stop_loss(position_id, chat_id, current_price):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        row = c.execute('SELECT entry_price, sl_price, target_price, type, trailing_sl_steps FROM auto_positions WHERE id = ? AND chat_id = ?', (position_id, chat_id)).fetchone()
        if not row:
            conn.close()
            return None, False
        entry_price, sl_price, target_price, trade_type, trailing_steps = row
        trail_step = AUTO_TRADE_CONFIG['trail_step_points']
        sl_updated = False
        new_sl = sl_price
        new_steps = trailing_steps
        if trade_type == 'BUY':
            profit_points = current_price - entry_price
            profit_steps = int(profit_points / trail_step)
            if profit_steps > trailing_steps:
                new_sl = entry_price + (profit_steps * trail_step)
                new_steps = profit_steps
                sl_updated = True
        else:
            profit_points = entry_price - current_price
            profit_steps = int(profit_points / trail_step)
            if profit_steps > trailing_steps:
                new_sl = entry_price - (profit_steps * trail_step)
                new_steps = profit_steps
                sl_updated = True
        if sl_updated:
            c.execute('UPDATE auto_positions SET sl_price = ?, trailing_sl_steps = ? WHERE id = ?', (new_sl, new_steps, position_id))
            conn.commit()
        conn.close()
        return new_sl, sl_updated
    except Exception as e:
        logging.error(f'Update Trailing SL Error: {e}')
    return sl_price, False
def is_market_hours():
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    time_mins = now.hour * 60 + now.minute
    return 555 <= time_mins <= 930

def auto_trading_scanner():
    while True:
        try:
            if not AUTO_TRADE_CONFIG['enabled'] or not is_market_hours():
                time.sleep(60)
                continue
            users = get_all_users()
            for chat_id in users:
                try:
                    position = get_auto_position(chat_id)
                    if position:
                        pos_id, symbol, qty, entry_price, sl_price, target_price, trade_type, opened_at = position[:8]
                        current_price = get_symbol_price(symbol)
                        if not isinstance(current_price, (int, float)):
                            continue
                        new_sl, sl_updated = update_trailing_stop_loss(pos_id, chat_id, current_price)
                        if sl_updated:
                            profit_pct = ((new_sl - entry_price) / entry_price * 100) if trade_type == 'BUY' else ((entry_price - new_sl) / entry_price * 100)
                            msg = f'📈 *TRAILING SL UPDATED*\n\n• *Symbol:* `{symbol}` | *Type:* `{trade_type}`\n• *Entry:* `₹{entry_price:,.2f}`\n• *Current:* `₹{current_price:,.2f}`\n• *New SL:* `₹{new_sl:,.2f}` ({profit_pct:.2f}% profit locked)\n\n💡 Profit protect ho raha hai!'
                            send_telegram_message(chat_id, msg)
                        exit_reason = None
                        if trade_type == 'BUY':
                            if current_price <= new_sl:
                                exit_reason = 'TRAILING SL HIT'
                            elif current_price >= target_price:
                                exit_reason = 'TARGET HIT'
                            else:
                                opened_time = datetime.strptime(opened_at, '%Y-%m-%d %H:%M:%S')
                                if (datetime.now() - opened_time).total_seconds() > AUTO_TRADE_CONFIG['cooldown_minutes'] * 60:
                                    exit_reason = 'TIME EXIT'
                        else:
                            if current_price >= new_sl:
                                exit_reason = 'TRAILING SL HIT'
                            elif current_price <= target_price:
                                exit_reason = 'TARGET HIT'
                            else:
                                opened_time = datetime.strptime(opened_at, '%Y-%m-%d %H:%M:%S')
                                if (datetime.now() - opened_time).total_seconds() > AUTO_TRADE_CONFIG['cooldown_minutes'] * 60:
                                    exit_reason = 'TIME EXIT'
                        if exit_reason:
                            result = close_auto_position(pos_id, chat_id, current_price, exit_reason)
                            if result:
                                pnl_emoji = '🟢' if result['pnl'] >= 0 else '🔴'
                                msg = f'🤖 *AUTO TRADE CLOSED*\n\n• *Symbol:* `{result["symbol"]}`\n• *Type:* `{result["type"]}`\n• *Entry:* `₹{result["entry"]:,.2f}`\n• *Exit:* `₹{result["exit"]:,.2f}`\n• *P&L:* {pnl_emoji} `₹{result["pnl"]:,.2f}`\n• *Reason:* `{exit_reason}`'
                                send_telegram_message(chat_id, msg)
                    else:
                        today_trades = get_today_trades_count(chat_id)
                        if today_trades >= AUTO_TRADE_CONFIG['max_trades_per_day']:
                            continue
                        today_pnl = get_today_pnl(chat_id)
                        if today_pnl <= -AUTO_TRADE_CONFIG['max_daily_loss']:
                            continue
                        tr = get_live_market_trend('^NSEI')
                        current_price = tr.get('price')
                        rsi_val = tr.get('rsi', 50)
                        vwap_val = tr.get('vwap', 0)
                        if not isinstance(current_price, (int, float)):
                            continue
                        symbol = AUTO_TRADE_CONFIG['symbol']
                        qty = AUTO_TRADE_CONFIG['quantity']
                        sl_points = AUTO_TRADE_CONFIG['sl_points']
                        target_points = AUTO_TRADE_CONFIG['target_points']
                        trade_type = None
                        sl_price = 0.0
                        target_price = 0.0
                        if current_price > vwap_val and rsi_val > 55:
                            trade_type = 'BUY'
                            sl_price = current_price - sl_points
                            target_price = current_price + target_points
                        elif current_price < vwap_val and rsi_val < 45:
                            trade_type = 'SELL'
                            sl_price = current_price + sl_points
                            target_price = current_price - target_points
                        if trade_type:
                            pos_id = open_auto_position(chat_id, symbol, qty, current_price, sl_price, target_price, trade_type)
                            if pos_id:
                                emoji = '🟢' if trade_type == 'BUY' else '🔴'
                                msg = f'{emoji} *AUTO TRADE OPENED*\n\n• *Symbol:* `{symbol}`\n• *Type:* `{trade_type}`\n• *Quantity:* `{qty}`\n• *Entry:* `₹{current_price:,.2f}`\n• *SL:* `₹{sl_price:,.2f}` ({sl_points} pts)\n• *Target:* `₹{target_price:,.2f}` ({target_points} pts)\n• *Trailing SL:* Active (Har {AUTO_TRADE_CONFIG["trail_step_points"]} pts par)\n• *RSI:* `{rsi_val:.2f}` | *VWAP:* `{vwap_val:.2f}`'
                                send_telegram_message(chat_id, msg)
                except Exception as e:
                    logging.error(f'Auto Scanner User Error ({chat_id}): {e}')
                    continue
        except Exception as e:
            logging.error(f'Auto Scanner Error: {e}')
        time.sleep(60)

def keep_alive():
    while True:
        try:
            requests.get(RENDER_URL, timeout=10)
        except Exception as e:
            logging.error(f'Keep-alive ping error: {e}')
        time.sleep(300)

def background_automation_scheduler():
    morning_sent = False
    closing_sent = False
    while True:
        now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        current_time_str = now.strftime('%H:%M')
        users = get_all_users()
        if current_time_str == '09:00' and not morning_sent:
            if users:
                tr = get_live_market_trend('^NSEI')
                msg = f'🌅 *GOOD MORNING!*\n\n• *Pre-Market Nifty:* `{tr["price"]}`\n• *Bias:* {tr["status"]}\n• *Action:* Prepare setups!'
                for c_id in users:
                    send_telegram_message(c_id, msg)
                    time.sleep(0.1)
            morning_sent = True
        elif current_time_str == '15:30' and not closing_sent:
            if users:
                summary_msg = get_daily_summary()
                for c_id in users:
                    send_telegram_message(c_id, summary_msg)
                    time.sleep(0.1)
            closing_sent = True
        if current_time_str == '00:00':
            morning_sent = False
            closing_sent = False
        time.sleep(30)

def real_time_entry_scanner():
    global LAST_NOTIFIED_PRICE, LAST_ALERT_TIME
    while True:
        try:
            current_time = time.time()
            COOLDOWN_PERIOD = 300
            tr = get_live_market_trend('^NSEI')
            current_price = tr.get('price')
            rsi_val = tr.get('rsi', 50)
            vwap_val = tr.get('vwap', 0)
            if isinstance(current_price, (int, float)):
                if LAST_NOTIFIED_PRICE is None:
                    LAST_NOTIFIED_PRICE = current_price
                else:
                    diff = current_price - LAST_NOTIFIED_PRICE
                    if abs(diff) >= 50 and (current_time - LAST_ALERT_TIME) > COOLDOWN_PERIOD:
                        if (diff > 0 and current_price > vwap_val and rsi_val > 50) or (diff < 0 and current_price < vwap_val and rsi_val < 50):
                            move_type = '🚀 *FAST MOVE: UP (+50+ Pts)*' if diff > 0 else '🔻 *FAST MOVE: DOWN (-50+ Pts)*'
                            users = get_all_users()
                            if users:
                                msg = f'{move_type}\n\n• *Ref:* `{LAST_NOTIFIED_PRICE}`\n• *Current:* `{current_price}`\n• *Move:* `{round(diff, 2)} Pts`\n• *VWAP:* `{vwap_val}` | *RSI:* `{rsi_val}`\n• *Bias:* {tr["status"]}\n\n💡 {tr["action"]}'
                                for c_id in users:
                                    send_telegram_message(c_id, msg)
                                    time.sleep(0.1)
                            LAST_NOTIFIED_PRICE = current_price
                            LAST_ALERT_TIME = current_time
        except Exception as e:
            logging.error(f'Real-Time Scanner Error: {e}')
        time.sleep(30)
        LAST_ADVANCED_STATE = {'supertrend': None, 'adx_strong': False}

def advanced_indicator_scanner():
    while True:
        try:
            if not is_market_hours():
                time.sleep(300)
                continue
            ind = get_advanced_indicators('^NSEI')
            if not ind:
                time.sleep(300)
                continue
            users = get_all_users()
            if not users:
                time.sleep(300)
                continue
            current_st = ind['supertrend']
            if LAST_ADVANCED_STATE['supertrend'] != current_st:
                if LAST_ADVANCED_STATE['supertrend'] is not None:
                    emoji = '🟢' if current_st == 'BUY' else '🔴'
                    action = 'BUY' if current_st == 'BUY' else 'SELL'
                    msg = f'🚨 *SUPERTREND FLIP*\n\n• Symbol: NIFTY\n• New Signal: {emoji} {action}\n• Price: `{ind["price"]}`\n• Upper: `{ind["supertrend_upper"]}`\n• Lower: `{ind["supertrend_lower"]}`\n\n💡 {"Long positions consider karein" if current_st == "BUY" else "Short/Exit consider karein"}'
                    for uid in users:
                        send_telegram_message(uid, msg)
                        time.sleep(0.5)
                LAST_ADVANCED_STATE['supertrend'] = current_st
            if ind['adx'] > 25 and not LAST_ADVANCED_STATE['adx_strong']:
                msg = f'💪 *STRONG TREND DETECTED*\n\n• ADX: `{ind["adx"]}` (>25)\n• Price: `{ind["price"]}`\n• Supertrend: {ind["supertrend"]}\n\n💡 Strong momentum detected!'
                for uid in users:
                    send_telegram_message(uid, msg)
                    time.sleep(0.5)
                LAST_ADVANCED_STATE['adx_strong'] = True
            elif ind['adx'] <= 25:
                LAST_ADVANCED_STATE['adx_strong'] = False
            time.sleep(300)
        except Exception as e:
            logging.error(f'Advanced Scanner Error: {e}')
            time.sleep(300)

def smart_entry_alert_scanner():
    global LAST_VOLUME_ALERT_TIME, LAST_PCR_ALERT_TIME
    while True:
        try:
            if not is_market_hours():
                time.sleep(120)
                continue
            ticker = yf.Ticker('^NSEI')
            data = ticker.history(period='5d', interval='5m')
            if len(data) < 20:
                time.sleep(120)
                continue
            current_price = round(data['Close'].iloc[-1], 2)
            current_volume = data['Volume'].iloc[-1]
            avg_volume = data['Volume'].rolling(window=20).mean().iloc[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
            rsi = calculate_rsi(data)
            vwap = calculate_vwap(data)
            pcr = calculate_pcr_from_price_action(data)
            ema_9 = data['Close'].ewm(span=9).mean().iloc[-1]
            ema_21 = data['Close'].ewm(span=21).mean().iloc[-1]
            current_time = time.time()
            users = get_all_users()
            if not users:
                time.sleep(120)
                continue
            volume_alert_cooldown = 600
            pcr_alert_cooldown = 900
            if volume_ratio > 2 and (current_time - LAST_VOLUME_ALERT_TIME) > volume_alert_cooldown:
                if current_price > ema_9 and rsi > 50:
                    msg = f'🔥 *VOLUME SPIKE ALERT - BUY ENTRY*\n\n• *Price:* `{current_price}`\n• *Volume:* `{volume_ratio:.1f}x` average\n• *RSI:* `{rsi}`\n• *PCR:* `{pcr}`\n• *VWAP:* `{vwap}`\n\n🟢 *STRONG BUY SIGNAL*\n• High volume + Bullish momentum\n• Entry: `{current_price}`\n• SL: `{current_price - 30}`\n• Target: `{current_price + 60}`\n\n💡 Act fast! Volume spike indicates institutional buying.'
                    for uid in users:
                        send_telegram_message(uid, msg)
                        time.sleep(0.3)
                    LAST_VOLUME_ALERT_TIME = current_time
                elif current_price < ema_9 and rsi < 50:
                    msg = f'🔥 *VOLUME SPIKE ALERT - SELL ENTRY*\n\n• *Price:* `{current_price}`\n• *Volume:* `{volume_ratio:.1f}x` average\n• *RSI:* `{rsi}`\n• *PCR:* `{pcr}`\n• *VWAP:* `{vwap}`\n\n🔴 *STRONG SELL SIGNAL*\n• High volume + Bearish momentum\n• Entry: `{current_price}`\n• SL: `{current_price + 30}`\n• Target: `{current_price - 60}`\n\n💡 Act fast! Volume spike indicates institutional selling.'
                    for uid in users:
                        send_telegram_message(uid, msg)
                        time.sleep(0.3)
                    LAST_VOLUME_ALERT_TIME = current_time
            if pcr > 1.3 and (current_time - LAST_PCR_ALERT_TIME) > pcr_alert_cooldown:
                msg = f'📊 *HIGH PCR ALERT - BUY ON DIPS*\n\n• *PCR:* `{pcr}` (>1.3)\n• *Price:* `{current_price}`\n• *RSI:* `{rsi}`\n\n🟢 *BULLISH SIGNAL*\n• Put writers dominant\n• Strong support at current levels\n• Entry on dips: `{current_price - 20}`\n• SL: `{current_price - 50}`\n• Target: `{current_price + 80}`\n\n💡 High PCR means market expects upside.'
                for uid in users:
                    send_telegram_message(uid, msg)
                    time.sleep(0.3)
                LAST_PCR_ALERT_TIME = current_time
            elif pcr < 0.7 and (current_time - LAST_PCR_ALERT_TIME) > pcr_alert_cooldown:
                msg = f'📊 *LOW PCR ALERT - SELL ON RISES*\n\n• *PCR:* `{pcr}` (<0.7)\n• *Price:* `{current_price}`\n• *RSI:* `{rsi}`\n\n🔴 *BEARISH SIGNAL*\n• Call writers dominant\n• Strong resistance at current levels\n• Entry on rises: `{current_price + 20}`\n• SL: `{current_price + 50}`\n• Target: `{current_price - 80}`\n\n💡 Low PCR means market expects downside.'
                for uid in users:
                    send_telegram_message(uid, msg)
                    time.sleep(0.3)
                LAST_PCR_ALERT_TIME = current_time
            time.sleep(120)
        except Exception as e:
            logging.error(f'Smart Entry Scanner Error: {e}')
            time.sleep(120)

def set_custom_alert(chat_id, symbol, target_price):
    try:
        conn = get_db_connection()
        conn.cursor().execute('INSERT INTO custom_alerts (chat_id, symbol, target_price) VALUES (?, ?, ?)', (chat_id, symbol, target_price))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f'Set Alert Error: {e}')

def delete_custom_alert(chat_id, symbol):
    try:
        conn = get_db_connection()
        conn.cursor().execute('DELETE FROM custom_alerts WHERE chat_id = ? AND symbol = ?', (chat_id, symbol))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f'Delete Alert Error: {e}')

def get_custom_alerts(chat_id):
    try:
        conn = get_db_connection()
        rows = conn.cursor().execute('SELECT id, symbol, target_price FROM custom_alerts WHERE chat_id = ?', (chat_id,)).fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f'Get Alerts Error: {e}')
    return []

def custom_alert_scanner():
    while True:
        try:
            conn = get_db_connection()
            alerts = conn.cursor().execute('SELECT id, chat_id, symbol, target_price, notified FROM custom_alerts').fetchall()
            conn.close()
            if not alerts:
                time.sleep(60)
                continue
            for alert_id, chat_id, symbol, target_price, notified in alerts:
                try:
                    symbol_map = {'NIFTY': '^NSEI', 'BANKNIFTY': '^NSEBANK', 'SENSEX': '^BSESN'}
                    yf_symbol = symbol_map.get(symbol.upper(), symbol)
                    tr = get_live_market_trend(yf_symbol)
                    current_price = tr.get('price')
                    if isinstance(current_price, (int, float)):
                        if notified == 0 and current_price >= target_price:
                            msg = f'🔔 *ALERT TRIGGERED!*\n\n• `{symbol}` crossed `{target_price}`\n• Current Price: `{current_price}`'
                            send_telegram_message(chat_id, msg)
                            conn = get_db_connection()
                            conn.cursor().execute('UPDATE custom_alerts SET notified = 1 WHERE id = ?', (alert_id,))
                            conn.commit()
                            conn.close()
                except Exception as e:
                    logging.error(f'Alert Check Error for {symbol}: {e}')
            time.sleep(60)
        except Exception as e:
            logging.error(f'Custom Alert Scanner Error: {e}')
            time.sleep(60)
