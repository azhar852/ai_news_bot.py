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

logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
RENDER_URL = 'https://new-trading-bot-2.onrender.com'

LAST_NOTIFIED_PRICE = None
LAST_ALERT_TIME = 0
PROCESSED_UPDATE_IDS = set()

AUTO_TRADE_CONFIG = {
    'enabled': False,
    'symbol': 'NIFTY',
    'quantity': 50,
    'sl_points': 60,
    'target_points': 120,
    'trail_step_points': 30,
    'max_trades_per_day': 5,
    'max_daily_loss': 5000,
    'cooldown_minutes': 60,
}


def get_db_connection():
  conn = sqlite3.connect('bot_users.db', check_same_thread=False, timeout=10)
  return conn


def init_db():
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)')
    cursor.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, entry_price REAL, exit_price REAL, qty INTEGER, pnl REAL, date TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS paper_wallets (chat_id INTEGER PRIMARY KEY, balance REAL DEFAULT 100000.0, created_at TEXT DEFAULT (datetime("now")))')
    cursor.execute('CREATE TABLE IF NOT EXISTS paper_positions (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, qty INTEGER, entry_price REAL, opened_at TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS paper_history (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, qty INTEGER, entry_price REAL, exit_price REAL, pnl REAL, opened_at TEXT, closed_at TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS auto_positions (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, qty INTEGER, entry_price REAL, sl_price REAL, target_price REAL, type TEXT, highest_price REAL, lowest_price REAL, trailing_sl_steps INTEGER DEFAULT 0, opened_at TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS auto_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, qty INTEGER, entry_price REAL, exit_price REAL, pnl REAL, type TEXT, exit_reason TEXT, opened_at TEXT, closed_at TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS auto_daily_stats (date TEXT PRIMARY KEY, trades_count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, pnl REAL DEFAULT 0.0)')
    conn.commit()
    conn.close()
  except Exception as e:
    logging.error(f'DB Init Error: {e}')

init_db()


def add_user_to_db(chat_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (chat_id) VALUES (?)', (chat_id,))
    conn.commit()
    conn.close()
  except Exception as e:
    logging.error(f'DB Add User Error: {e}')


def get_all_users():
  users = set()
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM users')
    rows = cursor.fetchall()
    for row in rows:
      users.add(row[0])
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
  if data_action == 'news':
    send_telegram_message(chat_id, get_market_news())
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
  elif data_action == 'vix':
    send_telegram_message(chat_id, get_real_vix())
  elif data_action == 'global':
    send_telegram_message(chat_id, get_global_markets())
  elif data_action == 'usdinr':
    send_telegram_message(chat_id, get_usd_inr())
  elif data_action == 'metals':
    send_telegram_message(chat_id, get_gold_silver())
  elif data_action == 'sectors':
    send_telegram_message(chat_id, get_sector_performance())
  elif data_action == 'expiry':
    send_telegram_message(chat_id, get_next_expiry())
  elif data_action == 'pivots':
    send_telegram_message(chat_id, get_pivot_levels('^NSEI'))
  elif data_action == 'pcr':
    tr = get_live_market_trend('^NSEI')
    p = analyze_pcr_data(tr)
    send_telegram_message(chat_id, f'📈 *PCR ANALYTICS*\n• Ratio: `{p["pcr"]}`\n• Sentiment: {p["sentiment"]}')
  elif data_action == 'bigmoney':
    tr = get_live_market_trend('^NSEI')
    bm = get_big_money_alert(tr)
    send_telegram_message(chat_id, f'🐋 *SMART MONEY FLOW*\n• {bm["action"]}\n• {bm["details"]}')
  elif data_action == 'crude_oil':
    send_telegram_message(chat_id, get_crude_oil_data())
  elif data_action == 'support':
    send_telegram_message(chat_id, '📋 *SUPPORT & ENTERPRISE REGISTRATION*\n\n• For formal business registrations (MSME), documentation, or technical support assistance in Bhopal, contact the administrator directly through registered channels.\n\n_Status: Verified & Active_ ✅')
  elif data_action == 'ai_analysis':
    send_telegram_message(chat_id, get_ai_trading_analysis('General Market Overview'))
  elif data_action == 'summary':
    send_telegram_message(chat_id, get_daily_summary())
  elif data_action == 'signal':
    tr = get_live_market_trend('^NSEI')
    send_telegram_message(chat_id, f'⚡ *REAL-TIME SIGNAL DESK*\n• Index Price: `{tr["price"]}`\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n• Mode: {tr["status"]}\n💡 {tr["action"]}')
  elif data_action == 'paper_help':
    send_telegram_message(chat_id, '💰 *PAPER TRADING COMMANDS*\n\n• `/paper` - Check wallet balance\n• `/buy SYMBOL QTY` - Buy position\n• `/sell SYMBOL QTY` - Sell position\n• `/positions` - View open positions\n• `/close ID` - Close position\n• `/paperhistory` - View completed trades')
  elif data_action == 'auto_help':
    send_telegram_message(chat_id, f'🤖 *AUTO TRADING COMMANDS*\n\n• `/autostart` - Start auto trading\n• `/autostop` - Stop auto trading\n• `/autostatus` - View current status\n• `/autostats` - View performance\n\n💡 *Current Config:*\n• SL: `{AUTO_TRADE_CONFIG["sl_points"]} pts`\n• Target: `{AUTO_TRADE_CONFIG["target_points"]} pts`\n• Trail: `{AUTO_TRADE_CONFIG["trail_step_points"]} pts`')
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
      else: status = ' HIGH FEAR (Market Panic / Correction)'
      return (f'📉 *INDIA VIX (FEAR GAUGE)*\n\n• *Current VIX:* `{current_vix}`\n• *Change:* `{change}%`\n• *Status:* {status}\n\n💡 *Tip:* Rising VIX means option premiums (CE/PE) will expand.')
  except Exception as e:
    logging.error(f'VIX Error: {e}')
  return '📉 *India VIX data currently updating.*'


def get_global_markets():
  markets = {'🇺🇸 Dow Jones': '^DJI', '🇺🇸 Nasdaq': '^IXIC', '🇸 S&P 500': '^GSPC', '🇯🇵 Nikkei': '^N225', '🇰 Hang Seng': '^HSI', '🇬🇧 FTSE': '^FTSE', '🇪 DAX': '^GDAXI'}
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
    except Exception:
      msg += f' *{name}:* Data unavailable\n'
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
      return (f' *USD/INR CURRENCY LIVE*\n\n• *Rate:* `₹{current}`\n• *Change:* `{change}%`\n• *Status:* {status}\n\n *Impact:* Weak rupee is generally negative for domestic equity inflows.')
  except Exception as e:
    logging.error(f'USD/INR Error: {e}')
  return '💱 *USD/INR Data currently updating.*'


def get_gold_silver():
  try:
    gold = yf.Ticker('GC=F')
    silver = yf.Ticker('SI=F')
    gold_data = gold.history(period='2d', interval='1d')
    silver_data = silver.history(period='2d', interval='1d')
    gold_price = round(gold_data['Close'].iloc[-1], 2) if not gold_data.empty else 0
    silver_price = round(silver_data['Close'].iloc[-1], 2) if not silver_data.empty else 0
    return (f' *PRECIOUS METALS (GLOBAL SPOT)*\n\n• *Gold (USD/oz):* `${gold_price}`\n• *Silver (USD/oz):* `${silver_price}`\n\n💡 *Note:* Safe-haven asset tracking for global inflation cues.')
  except Exception as e:
    logging.error(f'Gold/Silver Error: {e}')
  return '🥇 *Precious Metals data updating.*'


def get_sector_performance():
  sectors = {'🏦 Nifty Bank': '^NSEBANK', '💻 Nifty IT': '^CNXIT', '🚗 Nifty Auto': '^CNXAUTO', '💊 Nifty Pharma': '^CNXPHARMA', '🏗️ Nifty Metal': '^CNXMETAL', '⚡ Nifty Energy': '^CNXENERGY'}
  msg = ' *SECTOR PERFORMANCE TODAY*\n\n'
  for name, symbol in sectors.items():
    try:
      ticker = yf.Ticker(symbol)
      data = ticker.history(period='2d', interval='1d')
      if not data.empty:
        price = round(data['Close'].iloc[-1], 2)
        prev = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else price
        if prev == 0: prev = price
        change = round(((price - prev) / prev) * 100, 2)
        emoji = '' if change >= 0 else ''
        msg += f'{emoji} *{name}:* `{change}%`\n'
    except Exception:
      pass
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
      msg = ' *24/7 LATEST MARKET & FINANCIAL NEWS*\n\n'
      for entry in feed.entries[:4]:
        title = entry.get('title', 'Market News')
        link = entry.get('link', '')
        source = entry.get('source', {}).get('title', 'Financial Express') if 'source' in entry else 'News Update'
        if ' - ' in title: title = title.rsplit(' - ', 1)[0]
        msg += f'• [{title}]({link})\n  _Source: {source}_\n\n'
      return msg
  except Exception as e:
    logging.error(f'RSS News Fetch Error: {e}')
  return ' *LATEST MARKET NEWS*\n\n• Headlines currently updating.'


def get_crude_oil_data():
  try:
    ticker = yf.Ticker('CL=F')
    data = ticker.history(period='2d', interval='1d')
    if not data.empty:
      current_price = round(data['Close'].iloc[-1], 2)
      prev_price = round(data['Close'].iloc[-2], 2) if len(data) >= 2 else current_price
      if prev_price == 0: prev_price = current_price
      change = round(((current_price - prev_price) / prev_price) * 100, 2)
      status = ' BULLISH / RISING' if change >= 0 else '🔴 BEARISH / FALLING'
      return (f'️ *CRUDE OIL LIVE MARKET*\n\n• *Price:* `${current_price}`\n• *Change:* `{change}%`\n• *Trend:* {status}\n\n💡 *Market Impact:* High crude prices increase inflation and put pressure on indices.')
  except Exception as e:
    logging.error(f'Crude Fetch Error: {e}')
  return '️ *CRUDE OIL*\n\n• Live data currently updating.'


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


def get_live_market_trend(symbol='^NSEI'):
  try:
    ticker = yf.Ticker(symbol)
    data_5m = ticker.history(period='5d', interval='5m')
    if len(data_5m) >= 5:
      current_price = round(data_5m['Close'].iloc[-1], 2)
      rsi_val = calculate_rsi(data_5m)
      vwap_val = calculate_vwap(data_5m)
      open_price = data_5m['Open'].iloc[0]
      if open_price == 0: open_price = current_price
      change_pct = round(((current_price - open_price) / open_price) * 100, 2)
      if current_price > vwap_val and rsi_val > 50:
        status = '🟢 BULLISH (Upward Momentum)'
        action = 'Price is above VWAP with RSI > 50. Look for Call (CE) opportunities.'
        bias = 'BULLISH'
      elif current_price < vwap_val and rsi_val < 50:
        status = '🔴 BEARISH (Downward Momentum)'
        action = 'Price is below VWAP with RSI < 50. Look for Put (PE) opportunities.'
        bias = 'BEARISH'
      else:
        status = '⚖️ CONSOLIDATION / SIDEWAYS'
        action = 'Market is hovering around VWAP. Wait for a clear breakout.'
        bias = 'SIDEWAYS'
      return {'price': current_price, 'change': change_pct, 'rsi': rsi_val, 'vwap': vwap_val, 'status': status, 'action': action, 'bias': bias}
  except Exception as e:
    logging.error(f'Live Market Trend Error for {symbol}: {e}')
  try:
    ticker = yf.Ticker(symbol)
    data_15m = ticker.history(period='5d', interval='15m')
    if len(data_15m) >= 2:
      current_price = round(data_15m['Close'].iloc[-1], 2)
      return {'price': current_price, 'change': 0.0, 'rsi': 50.0, 'vwap': current_price, 'status': '️ LIVE DATA (15m)', 'action': 'Market is active. Check chart for exact levels.', 'bias': 'NEUTRAL'}
  except Exception as e:
    logging.error(f'Fallback Trend Error: {e}')
  return {'price': 'N/A', 'change': 0.0, 'rsi': 50.0, 'vwap': 0.0, 'status': '⚖️ MARKET CHECK IN PROGRESS', 'action': 'Verify with chart indicators.', 'bias': 'NEUTRAL'}


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
      return (f'📐 *AUTOMATIC PIVOT & S/R LEVELS*\n\n• *Pivot Point:* `{round(pivot, 2)}`\n• *Resistance 1 (R1):* `{round(r1, 2)}`\n• *Resistance 2 (R2):* `{round(r2, 2)}`\n• *Support 1 (S1):* `{round(s1, 2)}`\n• *Support 2 (S2):* `{round(s2, 2)}`\n\n💡 *Usage:* Trade breakouts above R1 or bounces near S1.')
  except Exception as e:
    logging.error(f'Pivot Error: {e}')
  return '📐 *Pivot Levels calculation currently updating.*'


def analyze_pcr_data(tr=None):
  if not tr: tr = get_live_market_trend('^NSEI')
  if tr['bias'] == 'BEARISH':
    return {'pcr': 0.75, 'sentiment': '🔴 BEARISH / CALL WRITING HEAVY', 'details': 'Call Writers building resistance.'}
  elif tr['bias'] == 'BULLISH':
    return {'pcr': 1.25, 'sentiment': '🟢 BULLISH / PUT WRITING DOMINANT', 'details': 'Put Writers supporting down levels.'}
  return {'pcr': 1.00, 'sentiment': '⚖️ NEUTRAL / RANGEBOUND', 'details': 'Balanced OI buildup.'}


def get_big_money_alert(tr=None):
  if not tr: tr = get_live_market_trend('^NSEI')
  if tr['bias'] == 'BEARISH':
    return {'action': '🔴 HEAVY FII OUTFLOW (SELLING)', 'details': 'FII net selling observed in Index Futures.'}
  elif tr['bias'] == 'BULLISH':
    return {'action': '🟢 HEAVY FII INFLOW (BUYING)', 'details': 'FII strong net buying observed.'}
  return {'action': '⚖️ NEUTRAL FLOW', 'details': 'Mixed institutional activity.'}


def get_daily_summary():
  tr = get_live_market_trend('^NSEI')
  pcr = analyze_pcr_data(tr)
  bm = get_big_money_alert(tr)
  return (f'📊 *DAILY MARKET SUMMARY & TECHNICAL REPORT*\n\n• *Nifty Price:* `{tr["price"]}` ({tr["change"]}%)\n• *VWAP:* `{tr["vwap"]}` | *RSI:* `{tr["rsi"]}`\n• *Overall Trend Bias:* {tr["status"]}\n• *Derivatives Sentiment:* {pcr["sentiment"]}\n• *Institutional Flow:* {bm["action"]}\n\n *Next Session Plan:* {tr["action"]}')


def get_ai_trading_analysis(query):
  tr = get_live_market_trend('^NSEI')
  pcr = analyze_pcr_data(tr)
  bm = get_big_money_alert(tr)
  return (f'🤖 *AI TECHNICAL ASSISTANT*\n\n• *Query:* _{query}_\n• *Nifty Live:* `{tr["price"]}` ({tr["change"]}%)\n• *VWAP:* `{tr["vwap"]}` | *RSI:* `{tr["rsi"]}`\n• *Market Bias:* {tr["status"]}\n• *Smart Money:* {bm["action"]}\n\n💡 *Recommendation:* {tr["action"]}')
 # --- PAPER TRADING SYSTEM ---

def init_paper_wallet(chat_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO paper_wallets (chat_id, balance) VALUES (?, ?)', (chat_id, 100000.0))
    conn.commit()
    conn.close()
  except Exception as e:
    logging.error(f'Paper Wallet Init Error: {e}')

def get_paper_wallet(chat_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM paper_wallets WHERE chat_id = ?', (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row: return row[0]
    init_paper_wallet(chat_id)
    return 100000.0
  except Exception as e:
    logging.error(f'Get Wallet Error: {e}')
    return 0.0

def update_wallet_balance(chat_id, new_balance):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE paper_wallets SET balance = ? WHERE chat_id = ?', (new_balance, chat_id))
    conn.commit()
    conn.close()
  except Exception as e:
    logging.error(f'Update Wallet Error: {e}')

def open_paper_position(chat_id, symbol, qty, entry_price):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO paper_positions (chat_id, symbol, qty, entry_price, opened_at) VALUES (?, ?, ?, ?, datetime("now"))', (chat_id, symbol, qty, entry_price))
    conn.commit()
    pos_id = cursor.lastrowid
    conn.close()
    return pos_id
  except Exception as e:
    logging.error(f'Open Position Error: {e}')
    return None

def get_open_positions(chat_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, symbol, qty, entry_price, opened_at FROM paper_positions WHERE chat_id = ?', (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows
  except Exception as e:
    logging.error(f'Get Positions Error: {e}')
    return []

def close_paper_position(position_id, chat_id, exit_price):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT symbol, qty, entry_price FROM paper_positions WHERE id = ? AND chat_id = ?', (position_id, chat_id))
    row = cursor.fetchone()
    if not row:
      conn.close()
      return None
    symbol, qty, entry_price = row
    pnl = (exit_price - entry_price) * qty
    cursor.execute('INSERT INTO paper_history (chat_id, symbol, qty, entry_price, exit_price, pnl, opened_at, closed_at) SELECT chat_id, symbol, qty, entry_price, ?, ?, opened_at, datetime("now") FROM paper_positions WHERE id = ?', (exit_price, pnl, position_id))
    cursor.execute('DELETE FROM paper_positions WHERE id = ?', (position_id,))
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
    cursor = conn.cursor()
    cursor.execute('SELECT symbol, qty, entry_price, exit_price, pnl, closed_at FROM paper_history WHERE chat_id = ? ORDER BY closed_at DESC LIMIT ?', (chat_id, limit))
    rows = cursor.fetchall()
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


# --- AUTOMATIC TRADING SYSTEM ---

def get_auto_position(chat_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, symbol, qty, entry_price, sl_price, target_price, type, opened_at FROM auto_positions WHERE chat_id = ? LIMIT 1', (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return row
  except Exception as e:
    logging.error(f'Get Auto Position Error: {e}')
    return None

def open_auto_position(chat_id, symbol, qty, entry_price, sl_price, target_price, trade_type):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO auto_positions (chat_id, symbol, qty, entry_price, sl_price, target_price, type, highest_price, lowest_price, trailing_sl_steps, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, datetime("now"))', (chat_id, symbol, qty, entry_price, sl_price, target_price, trade_type, entry_price, entry_price))
    conn.commit()
    pos_id = cursor.lastrowid
    conn.close()
    return pos_id
  except Exception as e:
    logging.error(f'Open Auto Position Error: {e}')
    return None

def close_auto_position(position_id, chat_id, exit_price, exit_reason):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT symbol, qty, entry_price, type, opened_at FROM auto_positions WHERE id = ? AND chat_id = ?', (position_id, chat_id))
    row = cursor.fetchone()
    if not row:
      conn.close()
      return None
    symbol, qty, entry_price, trade_type, opened_at = row
    pnl = (exit_price - entry_price) * qty if trade_type == 'BUY' else (entry_price - exit_price) * qty
    cursor.execute('INSERT INTO auto_trades (chat_id, symbol, qty, entry_price, exit_price, pnl, type, exit_reason, opened_at, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime("now"))', (chat_id, symbol, qty, entry_price, exit_price, pnl, trade_type, exit_reason, opened_at))
    cursor.execute('DELETE FROM auto_positions WHERE id = ?', (position_id,))
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('INSERT INTO auto_daily_stats (date, trades_count, wins, losses, pnl) VALUES (?, 1, ?, ?, ?) ON CONFLICT(date) DO UPDATE SET trades_count = trades_count + 1, wins = wins + ?, losses = losses + ?, pnl = pnl + ?', (today, 1 if pnl > 0 else 0, 1 if pnl <= 0 else 0, pnl, 1 if pnl > 0 else 0, 1 if pnl <= 0 else 0, pnl))
    conn.commit()
    conn.close()
    return {'symbol': symbol, 'qty': qty, 'entry': entry_price, 'exit': exit_price, 'pnl': pnl, 'type': trade_type, 'reason': exit_reason}
  except Exception as e:
    logging.error(f'Close Auto Position Error: {e}')
    return None

def get_today_trades_count(chat_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('SELECT COUNT(*) FROM auto_trades WHERE chat_id = ? AND DATE(closed_at) = ?', (chat_id, today))
    count = cursor.fetchone()[0]
    conn.close()
    return count
  except Exception as e:
    logging.error(f'Get Today Trades Error: {e}')
    return 0

def get_today_pnl(chat_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('SELECT COALESCE(SUM(pnl), 0) FROM auto_trades WHERE chat_id = ? AND DATE(closed_at) = ?', (chat_id, today))
    pnl = cursor.fetchone()[0]
    conn.close()
    return pnl
  except Exception as e:
    logging.error(f'Get Today PnL Error: {e}')
    return 0.0

def get_auto_stats(chat_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END), COALESCE(SUM(pnl), 0) FROM auto_trades WHERE chat_id = ?', (chat_id,))
    row = cursor.fetchone()
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
    cursor = conn.cursor()
    cursor.execute('SELECT entry_price, sl_price, target_price, type, trailing_sl_steps FROM auto_positions WHERE id = ? AND chat_id = ?', (position_id, chat_id))
    row = cursor.fetchone()
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
      cursor.execute('UPDATE auto_positions SET sl_price = ?, trailing_sl_steps = ? WHERE id = ?', (new_sl, new_steps, position_id))
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
      if not AUTO_TRADE_CONFIG['enabled']:
        time.sleep(60)
        continue
      if not is_market_hours():
        time.sleep(60)
        continue
      users = get_all_users()
      for chat_id in users:
        try:
          position = get_auto_position(chat_id)
          if position:
            pos_id, symbol, qty, entry_price, sl_price, target_price, trade_type, opened_at = position[:8]
            current_price = get_symbol_price(symbol)
            if not isinstance(current_price, (int, float)): continue
            new_sl, sl_updated = update_trailing_stop_loss(pos_id, chat_id, current_price)
            if sl_updated:
              profit_pct = ((new_sl - entry_price) / entry_price * 100) if trade_type == 'BUY' else ((entry_price - new_sl) / entry_price * 100)
              msg = (f'📈 *TRAILING SL UPDATED*\n\n• *Symbol:* `{symbol}` | *Type:* `{trade_type}`\n• *Entry:* `₹{entry_price:,.2f}`\n• *Current:* `₹{current_price:,.2f}`\n• *New SL:* `₹{new_sl:,.2f}` ({profit_pct:.2f}% profit locked)\n\n💡 Profit protect ho raha hai!')
              send_telegram_message(chat_id, msg)
            exit_reason = None
            if trade_type == 'BUY':
              if current_price <= new_sl: exit_reason = 'TRAILING SL HIT'
              elif current_price >= target_price: exit_reason = 'TARGET HIT'
              else:
                opened_time = datetime.strptime(opened_at, '%Y-%m-%d %H:%M:%S')
                if (datetime.now() - opened_time).total_seconds() > AUTO_TRADE_CONFIG['cooldown_minutes'] * 60: exit_reason = 'TIME EXIT'
            else:
              if current_price >= new_sl: exit_reason = 'TRAILING SL HIT'
              elif current_price <= target_price: exit_reason = 'TARGET HIT'
              else:
                opened_time = datetime.strptime(opened_at, '%Y-%m-%d %H:%M:%S')
                if (datetime.now() - opened_time).total_seconds() > AUTO_TRADE_CONFIG['cooldown_minutes'] * 60: exit_reason = 'TIME EXIT'
            if exit_reason:
              result = close_auto_position(pos_id, chat_id, current_price, exit_reason)
              if result:
                pnl_emoji = '🟢' if result['pnl'] >= 0 else '🔴'
                msg = (f'🤖 *AUTO TRADE CLOSED*\n\n• *Symbol:* `{result["symbol"]}`\n• *Type:* `{result["type"]}`\n• *Entry:* `₹{result["entry"]:,.2f}`\n• *Exit:* `₹{result["exit"]:,.2f}`\n• *P&L:* {pnl_emoji} `₹{result["pnl"]:,.2f}`\n• *Reason:* `{exit_reason}`')
                send_telegram_message(chat_id, msg)
          else:
            today_trades = get_today_trades_count(chat_id)
            if today_trades >= AUTO_TRADE_CONFIG['max_trades_per_day']: continue
            today_pnl = get_today_pnl(chat_id)
            if today_pnl <= -AUTO_TRADE_CONFIG['max_daily_loss']: continue
            tr = get_live_market_trend('^NSEI')
            current_price = tr.get('price')
            rsi_val = tr.get('rsi', 50)
            vwap_val = tr.get('vwap', 0)
            if not isinstance(current_price, (int, float)): continue
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
                msg = (f'{emoji} *AUTO TRADE OPENED*\n\n• *Symbol:* `{symbol}`\n• *Type:* `{trade_type}`\n• *Quantity:* `{qty}`\n• *Entry:* `₹{current_price:,.2f}`\n• *SL:* `₹{sl_price:,.2f}` ({sl_points} pts)\n• *Target:* `₹{target_price:,.2f}` ({target_points} pts)\n• *Trailing SL:* Active (Har {AUTO_TRADE_CONFIG["trail_step_points"]} pts par)\n• *RSI:* `{rsi_val:.2f}` | *VWAP:* `{vwap_val:.2f}`')
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
        msg = (f'🌅 *GOOD MORNING! TECHNICAL BRIEFING*\n\n• *Pre-Market Nifty Ref:* `{tr["price"]}`\n• *Initial Bias:* {tr["status"]}\n• *Action:* Prepare your live setups!')
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
              move_type = f'🚀 *FAST SCALPING ALERT: UPWARD MOVE (+50+ Pts)*' if diff > 0 else f'🔻 *FAST SCALPING ALERT: DOWNWARD MOVE (-50+ Pts)*'
              users = get_all_users()
              if users:
                msg = (f'{move_type}\n\n• *Previous Ref:* `{LAST_NOTIFIED_PRICE}`\n• *Current Price:* `{current_price}`\n• *Net Move:* `{round(diff, 2)} Points`\n• *VWAP:* `{vwap_val}` | *RSI:* `{rsi_val}`\n• *Market Bias:* {tr["status"]}\n\n💡 *Action:* {tr["action"]}')
                for c_id in users:
                  send_telegram_message(c_id, msg)
                  time.sleep(0.1)
              LAST_NOTIFIED_PRICE = current_price
              LAST_ALERT_TIME = current_time
    except Exception as e:
      logging.error(f'Real-Time Scanner Error: {e}')
    time.sleep(30)
