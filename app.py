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
        elif text_lower == '/autostart':
        AUTO_TRADE_CONFIG['enabled'] = True
        send_telegram_message(chat_id, f'🤖 *AUTO TRADING STARTED*\n\n• Strategy: VWAP + RSI\n• SL: `{AUTO_TRADE_CONFIG["sl_points"]} pts` | Target: `{AUTO_TRADE_CONFIG["target_points"]} pts`\n• Trailing: Har `{AUTO_TRADE_CONFIG["trail_step_points"]} pts` par\n• Max: `{AUTO_TRADE_CONFIG["max_trades_per_day"]}/day`\n\n💡 Bot ab market hours mein auto trade karega.')

      elif text_lower == '/autostop':
        AUTO_TRADE_CONFIG['enabled'] = False
        send_telegram_message(chat_id, '⏸️ *AUTO TRADING STOPPED*')

      elif text_lower == '/autostatus':
        status = '🟢 ACTIVE' if AUTO_TRADE_CONFIG['enabled'] else '🔴 INACTIVE'
        pos = get_auto_position(chat_id)
        t_trades = get_today_trades_count(chat_id)
        t_pnl = get_today_pnl(chat_id)
        msg = f'🤖 *AUTO STATUS*\n\n• Status: {status}\n• Symbol: `{AUTO_TRADE_CONFIG["symbol"]}`\n• Today: `{t_trades}/{AUTO_TRADE_CONFIG["max_trades_per_day"]}`\n• Today P&L: `₹{t_pnl:,.2f}`\n'
        if pos:
          pid, sym, q, ent, sl, tgt, typ, _ = pos[:8]
          cur = get_symbol_price(sym)
          if isinstance(cur, (int, float)):
            pnl = (cur - ent) * q if typ == 'BUY' else (ent - cur) * q
            msg += f'\n📊 *Open:*\n• ID: `{pid}` | {typ} `{sym}`\n• Entry: `₹{ent:,.2f}` | Cur: `₹{cur:,.2f}`\n• SL: `₹{sl:,.2f}` | Target: `₹{tgt:,.2f}`\n• P&L: `₹{pnl:,.2f}`'
        send_telegram_message(chat_id, msg)

      elif text_lower == '/autostats':
        stats = get_auto_stats(chat_id)
        if stats['total'] == 0: send_telegram_message(chat_id, '📭 *No Auto Trades Yet*')
        else:
          em = '🟢' if stats['pnl'] >= 0 else '🔴'
          send_telegram_message(chat_id, f'📊 *AUTO PERFORMANCE*\n\n• Total: `{stats["total"]}`\n• Wins: `{stats["wins"]}` | Losses: `{stats["losses"]}`\n• Win Rate: `{stats["win_rate"]:.1f}%`\n• Total P&L: {em} `₹{stats["pnl"]:,.2f}`')

      elif text_lower in ['/vix', '/india_vix']: send_telegram_message(chat_id, get_real_vix())
      elif text_lower in ['/global', '/world']: send_telegram_message(chat_id, get_global_markets())
      elif text_lower in ['/usdinr', '/dollar']: send_telegram_message(chat_id, get_usd_inr())
      elif text_lower in ['/metals', '/gold']: send_telegram_message(chat_id, get_gold_silver())
      elif text_lower in ['/sectors', '/sector']: send_telegram_message(chat_id, get_sector_performance())
      elif text_lower in ['/expiry', '/expiration']: send_telegram_message(chat_id, get_next_expiry())
      elif text_lower == '/news': send_telegram_message(chat_id, get_market_news())
      elif text_lower == '/reversal':
        tr = get_live_market_trend('^NSEI')
        send_telegram_message(chat_id, f'🔄 *REVERSAL STATUS*\n• Status: {tr["status"]}\n• Price: `{tr["price"]}`\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n💡 {tr["action"]}')
      elif text_lower == '/ai_analysis': send_telegram_message(chat_id, get_ai_trading_analysis('General Market Overview'))
      elif text_lower == '/ai' or text_lower.startswith('/ai '):
        query = text[3:].strip() or 'Overall market condition'
        send_telegram_message(chat_id, get_ai_trading_analysis(query))
      elif text_lower in ['/trend', '/market']:
        tr = get_live_market_trend('^NSEI')
        send_telegram_message(chat_id, f'🎯 *LIVE TREND*\n• Price: `{tr["price"]}` ({tr["change"]}%)\n• Status: {tr["status"]}\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n💡 {tr["action"]}')
      elif text_lower in ['/nifty', '/nifty50']:
        tr = get_live_market_trend('^NSEI')
        send_telegram_message(chat_id, f'📊 *NIFTY 50*\n• Price: `{tr["price"]}` ({tr["change"]}%)\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n• Bias: {tr["status"]}')
      elif text_lower in ['/banknifty']:
        tr = get_live_market_trend('^NSEBANK')
        send_telegram_message(chat_id, f'🏦 *BANK NIFTY*\n• Price: `{tr["price"]}` ({tr["change"]}%)\n• Bias: {tr["status"]}')
      elif text_lower in ['/sensex']:
        tr = get_live_market_trend('^BSESN')
        send_telegram_message(chat_id, f'📈 *SENSEX*\n• Price: `{tr["price"]}` ({tr["change"]}%)\n• Bias: {tr["status"]}')
      elif text_lower == '/pivots': send_telegram_message(chat_id, get_pivot_levels('^NSEI'))
      elif text_lower == '/pcr':
        p = analyze_pcr_data()
        send_telegram_message(chat_id, f'📈 *PCR*\n• Value: `{p["pcr"]}`\n• Sentiment: {p["sentiment"]}')
      elif text_lower == '/bigmoney':
        bm = get_big_money_alert()
        send_telegram_message(chat_id, f'🐋 *SMART MONEY*\n• {bm["action"]}\n• {bm["details"]}')
      elif text_lower == '/commodity': send_telegram_message(chat_id, '🛢️ *MCX COMMODITY*\n• Check Crude Oil, Gold & Silver near key support levels.')
      elif text_lower == '/support': send_telegram_message(chat_id, '📋 *SUPPORT*\n\n• For MSME registration or tech support in Bhopal, contact admin.\n\n_Status: Verified & Active_ ✅')
      elif text_lower == '/summary': send_telegram_message(chat_id, get_daily_summary())
      elif text_lower == '/signal':
        tr = get_live_market_trend('^NSEI')
        send_telegram_message(chat_id, f'⚡ *SCALP SIGNAL*\n• Price: `{tr["price"]}`\n• VWAP: `{tr["vwap"]}` | RSI: `{tr["rsi"]}`\n• Mode: {tr["status"]}\n💡 {tr["action"]}')
      else:
        send_telegram_message(chat_id, '✅ Command received. Use buttons below:', reply_markup=get_main_keyboard())

  except Exception as e:
    logging.error(f'Webhook error: {e}')
  return 'OK', 200

# Start Background Threads
threading.Thread(target=keep_alive, daemon=True).start()
threading.Thread(target=background_automation_scheduler, daemon=True).start()
threading.Thread(target=real_time_entry_scanner, daemon=True).start()
threading.Thread(target=auto_trading_scanner, daemon=True).start()

if __name__ == '__main__':
  port = int(os.environ.get('PORT', 10000))
  app.run(host='0.0.0.0', port=port)
