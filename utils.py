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
    
