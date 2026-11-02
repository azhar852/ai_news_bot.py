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

# Logging Configuration Setup
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
RENDER_URL = 'https://trading-bot-pro-2bjl.onrender.com'

LAST_NOTIFIED_PRICE = None
LAST_ALERT_TIME = 0
PROCESSED_UPDATE_IDS = set()

# --- AUTO TRADING CONFIG (REALISTIC POINTS-BASED) ---
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
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)'''
    )
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                symbol TEXT,
                entry_price REAL,
                exit_price REAL,
                qty INTEGER,
                pnl REAL,
                date TEXT
            )
        ''')
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_wallets (
                chat_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 100000.0,
                created_at TEXT DEFAULT (datetime("now"))
            )
        ''')
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                symbol TEXT,
                qty INTEGER,
                entry_price REAL,
                opened_at TEXT
            )
        ''')
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                symbol TEXT,
                qty INTEGER,
                entry_price REAL,
                exit_price REAL,
                pnl REAL,
                opened_at TEXT,
                closed_at TEXT
            )
        ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auto_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            symbol TEXT,
            qty INTEGER,
            entry_price REAL,
            sl_price REAL,
            target_price REAL,
            type TEXT,
            highest_price REAL,
            lowest_price REAL,
            trailing_sl_steps INTEGER DEFAULT 0,
            opened_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auto_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            symbol TEXT,
            qty INTEGER,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            type TEXT,
            exit_reason TEXT,
            opened_at TEXT,
            closed_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auto_daily_stats (
            date TEXT PRIMARY KEY,
            trades_count INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            pnl REAL DEFAULT 0.0
        )
    ''')
    conn.commit()
    conn.close()
  except Exception as e:
    logging.error(f'DB Init Error: {e}')


init_db()


def add_user_to_db(chat_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR IGNORE INTO users (chat_id) VALUES (?)', (chat_id,)
    )
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
