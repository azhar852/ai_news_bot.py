import os
import logging
import threading
from flask import Flask, request
from utils import (
    PROCESSED_UPDATE_IDS, AUTO_TRADE_CONFIG, add_user_to_db,
    analyze_pcr_data, answer_callback_query, auto_trading_scanner,
    background_automation_scheduler, close_auto_position,
    close_paper_position, get_ai_trading_analysis, get_auto_position,
    get_auto_stats, get_big_money_alert, get_daily_summary,
    get_db_connection, get_global_markets, get_gold_silver,
    get_live_market_trend, get_main_keyboard, get_market_news,
    get_next_expiry, get_open_positions, get_paper_history,
    get_paper_wallet, get_pivot_levels, get_real_vix,
    get_sector_performance, get_symbol_price, get_today_pnl,
    get_today_trades_count, get_usd_inr, keep_alive,
    open_paper_position, process_action, real_time_entry_scanner,
    send_telegram_message,
)

app = Flask(__name__)

logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

@app.route('/')
def home():
  return 'MyMarketAlertBot Ultimate Pro Webhook Active!'

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
  try:
    update = request.get_json(force=True, silent=True)
    if not update: return 'OK', 200

    logging.info(f'Received Update ID: {update.get("update_id")}')
    update_id = update.get('update_id')
    if update_id:
      if update_id in PROCESSED_UPDATE_IDS: return 'OK', 200
      PROCESSED_UPDATE_IDS.add(update_id)
      if len(PROCESSED_UPDATE_IDS) > 300: PROCESSED_UPDATE_IDS.clear()

    chat_id = None
    if 'callback_query' in update: chat_id = update['callback_query']['message']['chat']['id']
    elif 'message' in update: chat_id = update['message'].get('chat', {}).get('id')

    if chat_id: add_user_to_db(chat_id)

    if 'callback_query' in update:
      cq = update['callback_query']
      answer_callback_query(cq['id'])
      process_action(chat_id, cq['data'])
      return 'OK', 200

    message = update.get('message', {})
    text = message.get('text', '').strip()
    text_lower = text.lower()

    if chat_id:
      if text_lower in ['/start', 'start']:
        send_telegram_message(chat_id, '✅ *MyMarketAlertBot Ultimate Pro Active!*\n\nAll Indices, Pivots, AI Analysis, Paper Trading & Auto Trading Ready.\n\n💡 *Quick Commands:*\n• `/paper` - Paper trading wallet\n• `/autostart` - Start auto trading\n• `/calc <entry>` - Target & Stoploss\n\nSelect a command using the buttons below:', reply_markup=get_main_keyboard())

      elif text_lower.startswith('/calc'):
        try:
          parts = text.split()
          if len(parts) < 2: raise IndexError
          entry = float(parts[1])
          sl = entry * 0.99
          t1 = entry + (entry - sl) * 2
          t2 = entry + (entry - sl) * 3
          send_telegram_message(chat_id, f'🎯 *Trade Calculator*\n• Entry: `{entry}`\n• 🔴 SL: `{sl:.2f}`\n• 🟢 T1 (1:2): `{t1:.2f}`\n• 🟢 T2 (1:3): `{t2:.2f}`')
        except IndexError: send_telegram_message(chat_id, '⚠️ Format: `/calc 22600`')
        except ValueError: send_telegram_message(chat_id, '⚠️ Sirf numbers use karein.')
        except Exception: send_telegram_message(chat_id, '⚠️ Error aaya.')

      elif text_lower.startswith('/trade'):
        try:
          parts = text.split()
          if len(parts) < 5: raise IndexError
          sym, ent, ext, q = parts[1], float(parts[2]), float(parts[3]), int(parts[4])
          pnl = (ext - ent) * q
          conn = get_db_connection()
          conn.cursor().execute('INSERT INTO trades (chat_id, symbol, entry_price, exit_price, qty, pnl, date) VALUES (?, ?, ?, ?, ?, ?, datetime("now"))', (chat_id, sym, ent, ext, q, pnl))
          conn.commit(); conn.close()
          send_telegram_message(chat_id, f'✅ *Trade Saved*\n• Symbol: `{sym}`\n• P&L: `₹{pnl:.2f}`')
        except IndexError: send_telegram_message(chat_id, '⚠️ Format: `/trade Nifty 22600 22750 50`')
        except Exception: send_telegram_message(chat_id, '⚠️ Error aaya.')

      elif text_lower == '/paper':
        bal = get_paper_wallet(chat_id)
        send_telegram_message(chat_id, f'💰 *Paper Wallet*\n• Balance: `₹{bal:,.2f}`\n• Start: `₹1,00,000`\n\n💡 `/buy SYMBOL QTY` | `/sell SYMBOL QTY`\n💡 `/positions` | `/close ID` | `/paperhistory`')

      elif text_lower.startswith('/buy '):
        try:
          parts = text.split()
          if len(parts) < 3: raise IndexError
          sym, qty = parts[1].upper(), int(parts[2])
          if qty <= 0: raise ValueError
          price = get_symbol_price(sym)
          if not isinstance(price, (int, float)) or price <= 0:
            send_telegram_message(chat_id, '⚠️ Invalid symbol/price.'); return
          req = price * qty; bal = get_paper_wallet(chat_id)
          if bal < req:
            send_telegram_message(chat_id, f'⚠️ *Insufficient Balance*\n• Req: `₹{req:,.2f}`\n• Avail: `₹{bal:,.2f}`'); return
          pid = open_paper_position(chat_id, sym, qty, price)
          if pid: send_telegram_message(chat_id, f'✅ *Buy Executed*\n• `{sym}` | Qty: `{qty}`\n• Entry: `₹{price:,.2f}`\n• ID: `{pid}`')
          else: send_telegram_message(chat_id, '⚠️ Order failed.')
        except Exception: send_telegram_message(chat_id, '⚠️ Format: `/buy NIFTY 50`')

      elif text_lower.startswith('/sell '):
        try:
          parts = text.split()
          if len(parts) < 3: raise IndexError
          sym, qty = parts[1].upper(), int(parts[2])
          if qty <= 0: raise ValueError
          price = get_symbol_price(sym)
          if not isinstance(price, (int, float)) or price <= 0:
            send_telegram_message(chat_id, '⚠️ Invalid symbol/price.'); return
          pid = open_paper_position(chat_id, sym, -qty, price)
          if pid: send_telegram_message(chat_id, f'✅ *Sell Executed (Short)*\n• `{sym}` | Qty: `{qty}`\n• Entry: `₹{price:,.2f}`\n• ID: `{pid}`')
          else: send_telegram_message(chat_id, '⚠️ Order failed.')
        except Exception: send_telegram_message(chat_id, '⚠️ Format: `/sell NIFTY 50`')

      elif text_lower == '/positions':
        pos = get_open_positions(chat_id)
        if not pos: send_telegram_message(chat_id, '📭 *No Open Positions*'); return
        msg = '📊 *Open Positions*\n\n'
        for p in pos:
          pid, sym, q, ent, _ = p
          cur = get_symbol_price(sym)
          if isinstance(cur, (int, float)):
            pnl = (cur - ent) * q
            msg += f"{'🟢' if pnl>=0 else '🔴'} *ID {pid}:* `{sym}`\n  Qty: `{q}` | Entry: `₹{ent:,.2f}`\n  Cur: `₹{cur:,.2f}` | P&L: `₹{pnl:,.2f}`\n\n"
          else: msg += f'⚪ *ID {pid}:* `{sym}` (No price)\n\n'
        msg += '💡 Use `/close ID`'
        send_telegram_message(chat_id, msg)

      elif text_lower.startswith('/close '):
        try:
          pid = int(text.split()[1])
          pos = get_open_positions(chat_id)
          found = next((p for p in pos if p[0] == pid), None)
          if not found: send_telegram_message(chat_id, '⚠️ ID not found.'); return
          sym = found[1]; exit_p = get_symbol_price(sym)
          if not isinstance(exit_p, (int, float)): send_telegram_message(chat_id, '⚠️ Price unavailable.'); return
          res = close_paper_position(pid, chat_id, exit_p)
          if res:
            em = '🟢' if res['pnl'] >= 0 else '🔴'
            send_telegram_message(chat_id, f'✅ *Position Closed*\n• `{res["symbol"]}`\n• Entry: `₹{res["entry"]:,.2f}` → Exit: `₹{res["exit"]:,.2f}`\n• P&L: {em} `₹{res["pnl"]:,.2f}`\n\n💰 New Bal: `₹{get_paper_wallet(chat_id):,.2f}`')
          else: send_telegram_message(chat_id, '⚠️ Failed.')
        except Exception: send_telegram_message(chat_id, '⚠️ Format: `/close 1`')

      elif text_lower == '/paperhistory':
        hist = get_paper_history(chat_id)
        if not hist: send_telegram_message(chat_id, '📭 *No History*'); return
        msg = '📜 *Completed Trades*\n\n'
        for t in hist:
          sym, q, ent, ext, pnl, dt = t
          em = '🟢' if pnl >= 0 else '🔴'
          msg += f'{em} `{sym}` | Qty: `{q}`\n  Entry: `₹{ent:,.2f}` → Exit: `₹{ext:,.2f}`\n  P&L: `₹{pnl:,.2f}` | {dt}\n\n'
        send_telegram_message(chat_id, msg)
