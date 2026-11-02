from datetime import datetime, timedelta
import logging
import os
import sqlite3
import time
import feedparser
import requests

try:
  import yfinance as yf
except ImportError:
  os.system('pip install yfinance')
  import yfinance as yf

logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
RENDER_URL = 'https://new-trading-bot-2.onrender.com'
LAST_NOTIFIED_PRICE = None
LAST_ALERT_TIME = 0
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
    for row in rows: users.add(row[0])
    conn.close()
  except Exception as e:
    logging.error(f'DB Read Users Error: {e}')
  return users

def get_main_keyboard():
  return {
      'inline_keyboard': [
          [{'text': '📰 News', 'callback_data': 'news'}, {'text': '⚡ Real-Time Scalp', 'callback_data': 'scalping_alert'}],
          [{'text': '🎯 Trend Setup', 'callback_data': 'trend'}, {'text': '📊 Nifty 50', 'callback_data': 'nifty'}],
          [{'text': '🏦 BankNifty', 'callback_data': 'banknifty'}, {'text': '📈 Sensex', 'callback_data': 'sensex'}],
          [{'text': '📉 India VIX', 'callback_data': 'vix'}, {'text': '🌍 Global Markets', 'callback_data': 'global'}],
          [{'text': '💱 USD/INR', 'callback_data': 'usdinr'}, {'text': '🥇 Gold & Silver', 'callback_data': 'metals'}],
          [{'text': '📊 Sectors', 'callback_data': 'sectors'}, {'text': '📅 Expiry', 'callback_data': 'expiry'}],
          [{'text': '📐 Pivots', 'callback_data': 'pivots'}, {'text': '📈 PCR', 'callback_data': 'pcr'}],
          [{'text': '🐋 BigMoney', 'callback_data': 'bigmoney'}, {'text': '🛢️ Crude Oil', 'callback_data': 'crude_oil'}],
          [{'text': '🤖 AI Analysis', 'callback_data': 'ai_analysis'}, {'text': '📋 Summary', 'callback_data': 'summary'}],
          [{'text': '💰 Paper Trade', 'callback_data': 'paper_help'}, {'text': '🤖 Auto Trade', 'callback_data': 'auto_help'}],
          [{'text': '⚙️ Support & Reg', 'callback_data': 'support'}, {'text': '⚡ Signal', 'callback_data': 'signal'}],
      ]
  }

def send_telegram_message(chat_id, text, reply_markup=None):
  if not chat_id or not TELEGRAM_BOT_TOKEN: return
  url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
  payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
  if reply_markup: payload['reply_markup'] = reply_markup
  try: requests.post(url, json=payload, timeout=10)
  except Exception as e: logging.error(f'Telegram Send Error to {chat_id}: {e}')

def answer_callback_query(callback_query_id):
  if not TELEGRAM_BOT_TOKEN: return
  url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery'
  try: requests.post(url, json={'callback_query_id': callback_query_id}, timeout=5)
  except Exception as e: logging.error(f'Answer Callback Error: {e}')

def process_action(chat_id, data_action):
  if data_action == 'news': send_telegram_message(chat_id, get_market_news())
  elif data_action == 'scalping_alert':
    tr = get_live_market_trend('^NSEI')
    send_telegram_message(chat_id, f'⚡ *REAL-TIME SCALP DESK*\n\n• Current Price: `{tr["price"]}`\n• VWAP: `{tr["vwap"]}`\n• RSI (14): `{tr["rsi"]}`\n• Market Bias: {tr["status"]}\n\n💡 {tr["action"]}')
  elif data_action == 'trend':
    tr = get_live_market_trend('^NSEI')
    send_telegram_message(chat_id, f'🎯 *LIVE TREND SETUP*\n\n• *Price:* `{tr["price"]}` ({tr["change"]}%)\n• *VWAP:* `{tr["vwap"]}`\n• *RSI (14):* `{tr["rsi"]}`\n• *Bias:* {tr["status"]}\n💡 {tr["action"]}')
  elif data_action == 'nifty':
    tr = get_live_market_trend('^NSEI')
    send_telegram_message(chat_id, f'📊 *NIFTY 50 REAL-TIME*\n• Price: `{tr["price"]}` ({tr["change"]}%)\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n• Bias: {tr["status"]}')
  elif data_action == 'banknifty':
    tr = get_live_market_trend('^NSEBANK')
    send_telegram_message(chat_id, f'🏦 *BANK NIFTY REAL-TIME*\n• Price: `{tr["price"]}` ({tr["change"]}%)\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n• Bias: {tr["status"]}')
  elif data_action == 'sensex':
    tr = get_live_market_trend('^BSESN')
    send_telegram_message(chat_id, f'📈 *BSE SENSEX*\n• Price: `{tr["price"]}` ({tr["change"]}%)\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n• Bias: {tr["status"]}')
  elif data_action == 'vix': send_telegram_message(chat_id, get_real_vix())
  elif data_action == 'global': send_telegram_message(chat_id, get_global_markets())
  elif data_action == 'usdinr': send_telegram_message(chat_id, get_usd_inr())
  elif data_action == 'metals': send_telegram_message(chat_id, get_gold_silver())
  elif data_action == 'sectors': send_telegram_message(chat_id, get_sector_performance())
  elif data_action == 'expiry': send_telegram_message(chat_id, get_next_expiry())
  elif data_action == 'pivots': send_telegram_message(chat_id, get_pivot_levels('^NSEI'))
  elif data_action == 'pcr':
    tr = get_live_market_trend('^NSEI')
    p = analyze_pcr_data(tr)
    send_telegram_message(chat_id, f'📈 *PCR ANALYTICS*\n• Ratio: `{p["pcr"]}`\n• Sentiment: {p["sentiment"]}')
  elif data_action == 'bigmoney':
    tr = get_live_market_trend('^NSEI')
    bm = get_big_money_alert(tr)
    send_telegram_message(chat_id, f'🐋 *SMART MONEY FLOW*\n• {bm["action"]}\n• {bm["details"]}')
  elif data_action == 'crude_oil': send_telegram_message(chat_id, get_crude_oil_data())
  elif data_action == 'support': send_telegram_message(chat_id, '📋 *SUPPORT & ENTERPRISE REGISTRATION*\n\n• For formal business registrations (MSME), documentation, or technical support assistance in Bhopal, contact the administrator directly through registered channels.\n\n_Status: Verified & Active_ ✅')
  elif data_action == 'ai_analysis': send_telegram_message(chat_id, get_ai_trading_analysis('General Market Overview'))
  elif data_action == 'summary': send_telegram_message(chat_id, get_daily_summary())
  elif data_action == 'signal':
    tr = get_live_market_trend('^NSEI')
    send_telegram_message(chat_id, f'⚡ *REAL-TIME SIGNAL DESK*\n• Index Price: `{tr["price"]}`\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n• Mode: {tr["status"]}\n💡 {tr["action"]}')
  elif data_action == 'paper_help': send_telegram_message(chat_id, '💰 *PAPER TRADING COMMANDS*\n\n• `/paper` - Check wallet balance\n• `/buy SYMBOL QTY` - Buy position\n• `/sell SYMBOL QTY` - Sell position\n• `/positions` - View open positions\n• `/close ID` - Close position\n• `/paperhistory` - View completed trades')
  elif data_action == 'auto_help': send_telegram_message(chat_id, f'🤖 *AUTO TRADING COMMANDS*\n\n• `/autostart` - Start auto trading\n• `/autostop` - Stop auto trading\n• `/autostatus` - View current status\n• `/autostats` - View performance\n\n💡 *Current Config:*\n• SL: `{AUTO_TRADE_CONFIG["sl_points"]} pts`\n• Target: `{AUTO_TRADE_CONFIG["target_points"]} pts`\n• Trail: `{AUTO_TRADE_CONFIG["trail_step_points"]} pts`')

def get_real_vix():
  try:
    vix = yf.Ticker('^INDIAVIX')
    data = vix.history(period='2d', interval='1d')
    if not data.empty:
      current_vix = round(data['Close'].iloc[-1], 2)
      prev_vix = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else current_vix
      if prev_vix == 0: prev_vix = current_vix
      change = round(((current_vix - prev_vix) / prev_vix) * 100, 2)
      if current_vix < 12: status = '🟢 LOW FEAR (Bullish Market Support)'
      elif current_vix < 18: status = '🟡 MODERATE FEAR (Normal Volatility)'
      else: status = '🔴 HIGH FEAR (Market Panic / Correction)'
      return (f'📉 *INDIA VIX (FEAR GAUGE)*\n\n• *Current VIX:* `{current_vix}`\n• *Change:* `{change}%`\n• *Status:* {status}\n\n💡 *Tip:* Rising VIX means option premiums (CE/PE) will expand.')
  except Exception as e: logging.error(f'VIX Error: {e}')
  return '📉 *India VIX data currently updating.*'

def get_global_markets():
  markets = {'🇺🇸 Dow Jones': '^DJI', '🇺🇸 Nasdaq': '^IXIC', '🇺🇸 S&P 500': '^GSPC', '🇯🇵 Nikkei': '^N225', '🇭🇰 Hang Seng': '^HSI', '🇬🇧 FTSE': '^FTSE', '🇩🇪 DAX': '^GDAXI'}
  msg = '🌍 *GLOBAL MARKETS LIVE STATUS*\n\n'
  for name, symbol in markets.items():
    try:
      ticker = yf.Ticker(symbol)
      data = ticker.history(period='2d', interval='1d')
      if not data.empty:
        price = round(data['Close'].iloc[-1], 2)
        prev = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else price
        if prev == 0: prev = price
        change = round(((price - prev) / prev) * 100, 2)
        emoji = '🟢' if change >= 0 else '🔴'
        msg += f'{emoji} *{name}:* `{price}` ({change}%)\n'
    except Exception: msg += f'⚪ *{name}:* Data unavailable\n'
  return msg

def get_usd_inr():
  try:
    ticker = yf.Ticker('USDINR=X')
    data = ticker.history(period='2d', interval='1d')
    if not data.empty:
      current = round(data['Close'].iloc[-1], 4)
      prev = round(data['Close'].iloc[-2], 4) if len(data) >= 2 else current
      if prev == 0: prev = current
      change = round(((current - prev) / prev) * 100, 2)
      status = '🟢 RUPEE STRONGER' if change < 0 else '🔴 RUPEE WEAKER'
      return (f'💱 *USD/INR CURRENCY LIVE*\n\n• *Rate:* `₹{current}`\n• *Change:* `{change}%`\n• *Status:* {status}\n\n💡 *Impact:* Weak rupee is generally negative for domestic equity inflows.')
  except Exception as e: logging.error(f'USD/INR Error: {e}')
  return '💱 *USD/INR Data currently updating.*'

def get_gold_silver():
  try:
    gold = yf.Ticker('GC=F')
    silver = yf.Ticker('SI=F')
    gold_data = gold.history(period='2d', interval='1d')
    silver_data = silver.history(period='2d', interval='1d')
    gold_price = round(gold_data['Close'].iloc[-1], 2) if not gold_data.empty else 0
    silver_price = round(silver_data['Close'].iloc[-1], 2) if not silver_data.empty else 0
    return (f'🥇 *PRECIOUS METALS (GLOBAL SPOT)*\n\n• *Gold (USD/oz):* `${gold_price}`\n• *Silver (USD/oz):* `${silver_price}`\n\n💡 *Note:* Safe-haven asset tracking for global inflation cues.')
  except Exception as e: logging.error(f'Gold/Silver Error: {e}')
  return '🥇 *Precious Metals data updating.*'

def get_sector_performance():
  sectors = {'🏦 Nifty Bank': '^NSEBANK', '💻 Nifty IT': '^CNXIT', '🚗 Nifty Auto': '^CNXAUTO', '💊 Nifty Pharma': '^CNXPHARMA', '🏗️ Nifty Metal': '^CNXMETAL', '⚡ Nifty Energy': '^CNXENERGY'}
  msg = '📊 *SECTOR PERFORMANCE TODAY*\n\n'
  for name, symbol in sectors.items():
    try:
      ticker = yf.Ticker(symbol)
      data = ticker.history(period='2d', interval='1d')
      if not data.empty:
        price = round(data['Close'].iloc[-1], 2)
        prev = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else price
        if prev == 0: prev = price
        change = round(((price - prev) / prev) * 100, 2)
        emoji = '🟢' if change >= 0 else '🔴'
        msg += f'{emoji} *{name}:* `{change}%`\n'
    except Exception: pass
  return msg

def get_next_expiry():
  today = datetime.now()
  days_ahead = 3 - today.weekday()
  if days_ahead <= 0: days_ahead += 7
  next_thursday = today + timedelta(days=days_ahead)
  days_left = (next_thursday - today).days
  return (f'📅 *OPTIONS EXPIRY CALENDAR*\n\n• *Next Weekly Expiry:* `{next_thursday.strftime("%d %b %Y")}`\n• *Days Remaining:* `{days_left}` Days\n\n💡 *Tip:* Avoid holding naked options close to expiry due to rapid Theta Decay.')

def get_market_news():
  try:
    rss_url = 'https://news.google.com/rss/search?q=Indian+Stock+Market+Nifty+Sensex&hl=en-IN&gl=IN&ceid=IN:en'
    feed = feedparser.parse(rss_url)
    if feed.entries and len(feed.entries) > 0:
      msg = '📰 *24/7 LATEST MARKET & FINANCIAL NEWS*\n\n'
      for entry in feed.entries[:4]:
        title = entry.get('title', 'Market News')
        link = entry.get('link', '')
        source = entry.get('source', {}).get('title', 'Financial Express') if 'source' in entry else 'News Update'
        if ' - ' in title: title = title.rsplit(' - ', 1)[0]
        msg += f'• [{title}]({link})\n  _Source: {source}_\n\n'
      return msg
  except Exception as e: logging.error(f'RSS News Fetch Error: {e}')
  return '📰 *LATEST MARKET NEWS*\n\n• Headlines currently updating.'

def get_crude_oil_data():
  try:
    ticker = yf.Ticker('CL=F')
    data = ticker.history(period='2d', interval='1d')
    if not data.empty:
      current_price = round(data['Close'].iloc[-1], 2)
      prev_price = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else current_price
      if prev_price == 0: prev_price = current_price
      change = round(((current_price - prev_price) / prev_price) * 100, 2)
      status = '🟢 BULLISH / RISING' if change >= 0 else '🔴 BEARISH / FALLING'
      return (f'🛢️ *CRUDE OIL LIVE MARKET*\n\n• *Price:* `${current_price}`\n• *Change:* `{change}%`\n• *Trend:* {status}\n\n💡 *Market Impact:* High crude prices increase inflation and put pressure on indices.')
  except Exception as e: logging.error(f'Crude Fetch Error: {e}')
  return '🛢️ *CRUDE OIL*\n\n• Live data currently updating.'

def calculate_rsi(data, window=14):
  try:
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)
  except Exception as e: logging.error(f'RSI Calculation Error: {e}')
  return 50.0

def calculate_vwap(data):
  try:
    q = data['Volume']
    tp = (data['High'] + data['Low'] + data['Close']) / 3
    vwap = (tp * q).cumsum() / q.cumsum()
    return round(vwap.iloc[-1], 2)
  except Exception as e: logging.error(f'VWAP Calculation Error: {e}')
  return 0.0
  
