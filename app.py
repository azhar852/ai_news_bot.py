import os
import logging
import threading
from flask import Flask, request
from utils import (
    PROCESSED_UPDATE_IDS, AUTO_TRADE_CONFIG, add_user_to_db,
    analyze_pcr_data, answer_callback_query, auto_trading_scanner,
    background_automation_scheduler, close_auto_position,
    close_paper_position, get_advanced_indicators,
    get_ai_trading_analysis, get_auto_position, get_auto_stats,
    get_big_money_alert, get_daily_summary, get_db_connection,
    get_global_markets, get_gold_silver, get_live_market_trend,
    get_main_keyboard, get_market_news, get_next_expiry,
    get_open_positions, get_paper_history, get_paper_wallet,
    get_pivot_levels, get_real_vix, get_sector_performance,
    get_symbol_price, get_today_pnl, get_today_trades_count,
    get_usd_inr, keep_alive, open_paper_position, process_action,
    real_time_entry_scanner, send_telegram_message,
    get_crude_oil_data, advanced_indicator_scanner,
    get_mtf_analysis, custom_alert_scanner, set_custom_alert,
    get_custom_alerts, delete_custom_alert,
    get_volume_pcr_analysis, get_smart_entry_alerts,
    smart_entry_alert_scanner
)

app = Flask(__name__)
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

@app.route('/')
def home():
    return 'Ultimate Pro Trading Bot Active!'

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    try:
        update = request.get_json(force=True, silent=True)
        if not update:
            return 'OK', 200

        update_id = update.get('update_id')
        if update_id:
            if update_id in PROCESSED_UPDATE_IDS:
                return 'OK', 200
            PROCESSED_UPDATE_IDS.add(update_id)
            if len(PROCESSED_UPDATE_IDS) > 300:
                PROCESSED_UPDATE_IDS.clear()

        chat_id = None
        if 'callback_query' in update:
            chat_id = update['callback_query']['message']['chat']['id']
        elif 'message' in update:
            chat_id = update['message'].get('chat', {}).get('id')

        if chat_id:
            add_user_to_db(chat_id)

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
                msg = '🚀 *ULTIMATE PRO TRADING BOT*\n\n'
                msg += 'Welcome! Institutional-grade data.\n\n'
                msg += '💡 *Commands:*\n'
                msg += '• `/mtf` - Multi-Timeframe\n'
                msg += '• `/advanced` - 7 Indicators\n'
                msg += '• `/volume` - Volume & PCR\n'
                msg += '• `/smart` - Smart Entry\n'
                msg += '• `/alert SYMBOL PRICE` - Set Alert\n'
                msg += '• `/paper` - Virtual Wallet\n\n'
                msg += 'Niche buttons use karein:'
                send_telegram_message(chat_id, msg, reply_markup=get_main_keyboard())

            elif text_lower.startswith('/calc'):
                try:
                    parts = text.split()
                    entry = float(parts[1])
                    sl = entry * 0.99
                    t1 = entry + (entry - sl) * 2
                    t2 = entry + (entry - sl) * 3
                    msg = '🎯 *Trade Calculator*\n'
                    msg += '• Entry: `' + str(entry) + '`\n'
                    msg += '• SL: `' + str(round(sl, 2)) + '`\n'
                    msg += '• T1: `' + str(round(t1, 2)) + '`\n'
                    msg += '• T2: `' + str(round(t2, 2)) + '`'
                    send_telegram_message(chat_id, msg)
                except Exception:
                    send_telegram_message(chat_id, '⚠️ Format: `/calc 22600`')

            elif text_lower == '/paper':
                bal = get_paper_wallet(chat_id)
                msg = '💰 *Paper Wallet*\n'
                msg += '• Balance: `₹' + f'{bal:,.2f}' + '`\n'
                msg += '• Start: `₹1,00,000`\n\n'
                msg += '💡 `/buy SYMBOL QTY` | `/sell SYMBOL QTY`\n'
                msg += '💡 `/positions` | `/close ID`'
                send_telegram_message(chat_id, msg)

            elif text_lower.startswith('/buy '):
                try:
                    parts = text.split()
                    sym = parts[1].upper()
                    qty = int(parts[2])
                    price = get_symbol_price(sym)
                    if not isinstance(price, (int, float)) or price <= 0:
                        raise ValueError
                    req = price * qty
                    bal = get_paper_wallet(chat_id)
                    if bal < req:
                        msg = '⚠️ *Insufficient Balance*\n'
                        msg += '• Req: `₹' + f'{req:,.2f}' + '`\n'
                        msg += '• Avail: `₹' + f'{bal:,.2f}' + '`'
                        send_telegram_message(chat_id, msg)
                        return
                    pid = open_paper_position(chat_id, sym, qty, price)
                    msg = '✅ *Buy Executed*\n'
                    msg += '• `' + sym + '` | Qty: `' + str(qty) + '`\n'
                    msg += '• Entry: `₹' + f'{price:,.2f}' + '`\n'
                    msg += '• ID: `' + str(pid) + '`'
                    send_telegram_message(chat_id, msg)
                except Exception:
                    send_telegram_message(chat_id, '⚠️ Format: `/buy NIFTY 50`')

            elif text_lower.startswith('/sell '):
                try:
                    parts = text.split()
                    sym = parts[1].upper()
                    qty = int(parts[2])
                    price = get_symbol_price(sym)
                    if not isinstance(price, (int, float)) or price <= 0:
                        raise ValueError
                    pid = open_paper_position(chat_id, sym, -qty, price)
                    msg = '✅ *Sell Executed (Short)*\n'
                    msg += '• `' + sym + '` | Qty: `' + str(qty) + '`\n'
                    msg += '• Entry: `₹' + f'{price:,.2f}' + '`\n'
                    msg += '• ID: `' + str(pid) + '`'
                    send_telegram_message(chat_id, msg)
                except Exception:
                    send_telegram_message(chat_id, '⚠️ Format: `/sell NIFTY 50`')

            elif text_lower == '/positions':
                pos = get_open_positions(chat_id)
                if not pos:
                    send_telegram_message(chat_id, '📭 *No Open Positions*')
                    return
                msg = '📊 *Open Positions*\n\n'
                for p in pos:
                    pid, sym, q, ent, _ = p
                    cur = get_symbol_price(sym)
                    if isinstance(cur, (int, float)):
                        pnl = (cur - ent) * q
                        emoji = '🟢' if pnl >= 0 else '🔴'
                        msg += emoji + ' *ID ' + str(pid) + ':* `' + sym + '`\n'
                        msg += '  Qty: `' + str(q) + '` | Entry: `₹' + f'{ent:,.2f}' + '`\n'
                        msg += '  Cur: `₹' + f'{cur:,.2f}' + '` | P&L: `₹' + f'{pnl:,.2f}' + '`\n\n'
                msg += '💡 Use `/close ID`'
                send_telegram_message(chat_id, msg)

            elif text_lower.startswith('/close '):
                try:
                    pid = int(text.split()[1])
                    pos = get_open_positions(chat_id)
                    found = next((p for p in pos if p[0] == pid), None)
                    if not found:
                        send_telegram_message(chat_id, '⚠️ ID not found.')
                        return
                    sym = found[1]
                    exit_p = get_symbol_price(sym)
                    if not isinstance(exit_p, (int, float)):
                        raise ValueError
                    res = close_paper_position(pid, chat_id, exit_p)
                    if res:
                        em = '🟢' if res['pnl'] >= 0 else '🔴'
                        new_bal = get_paper_wallet(chat_id)
                        msg = '✅ *Position Closed*\n'
                        msg += '• `' + res['symbol'] + '`\n'
                        msg += '• Entry: `₹' + f'{res["entry"]:,.2f}' + '` → Exit: `₹' + f'{res["exit"]:,.2f}' + '`\n'
                        msg += '• P&L: ' + em + ' `₹' + f'{res["pnl"]:,.2f}' + '`\n\n'
                        msg += '💰 New Bal: `₹' + f'{new_bal:,.2f}' + '`'
                        send_telegram_message(chat_id, msg)
                except Exception:
                    send_telegram_message(chat_id, '⚠️ Format: `/close 1`')

            elif text_lower == '/autostart':
                AUTO_TRADE_CONFIG['enabled'] = True
                msg = '🤖 *AUTO TRADING STARTED*\n\n'
                msg += '• Strategy: VWAP + RSI\n'
                msg += '• SL: `' + str(AUTO_TRADE_CONFIG['sl_points']) + ' pts`\n'
                msg += '• Target: `' + str(AUTO_TRADE_CONFIG['target_points']) + ' pts`\n'
                msg += '• Trailing: Har `' + str(AUTO_TRADE_CONFIG['trail_step_points']) + ' pts` par'
                send_telegram_message(chat_id, msg)

            elif text_lower == '/autostop':
                AUTO_TRADE_CONFIG['enabled'] = False
                send_telegram_message(chat_id, '⏸️ *AUTO TRADING STOPPED*')

            elif text_lower == '/autostatus':
                status = '🟢 ACTIVE' if AUTO_TRADE_CONFIG['enabled'] else '🔴 INACTIVE'
                pos = get_auto_position(chat_id)
                t_trades = get_today_trades_count(chat_id)
                t_pnl = get_today_pnl(chat_id)
                msg = '🤖 *AUTO STATUS*\n\n'
                msg += '• Status: ' + status + '\n'
                msg += '• Today Trades: `' + str(t_trades) + '/' + str(AUTO_TRADE_CONFIG['max_trades_per_day']) + '`\n'
                msg += '• Today P&L: `₹' + f'{t_pnl:,.2f}' + '`\n'
                if pos:
                    pid, sym, q, ent, sl, tgt, typ, _ = pos[:8]
                    cur = get_symbol_price(sym)
                    if isinstance(cur, (int, float)):
                        pnl = (cur - ent) * q if typ == 'BUY' else (ent - cur) * q
                        msg += '\n📊 *Open:*\n'
                        msg += '• ID: `' + str(pid) + '` | ' + typ + ' `' + sym + '`\n'
                        msg += '• Entry: `₹' + f'{ent:,.2f}' + '` | Cur: `₹' + f'{cur:,.2f}' + '`\n'
                        msg += '• SL: `₹' + f'{sl:,.2f}' + '` | Target: `₹' + f'{tgt:,.2f}' + '`\n'
                        msg += '• P&L: `₹' + f'{pnl:,.2f}' + '`'
                send_telegram_message(chat_id, msg)

            elif text_lower in ['/vix', '/india_vix']:
                send_telegram_message(chat_id, get_real_vix())
            elif text_lower in ['/global', '/world']:
                send_telegram_message(chat_id, get_global_markets())
            elif text_lower in ['/usdinr', '/dollar']:
                send_telegram_message(chat_id, get_usd_inr())
            elif text_lower in ['/metals', '/gold']:
                send_telegram_message(chat_id, get_gold_silver())
            elif text_lower in ['/sectors', '/sector']:
                send_telegram_message(chat_id, get_sector_performance())
            elif text_lower in ['/expiry', '/expiration']:
                send_telegram_message(chat_id, get_next_expiry())
            elif text_lower == '/news':
                send_telegram_message(chat_id, get_market_news())
            elif text_lower == '/ai_analysis':
                send_telegram_message(chat_id, get_ai_trading_analysis('General Market Overview'))
            
            elif text_lower in ['/trend', '/market']:
                tr = get_live_market_trend('^NSEI')
                msg = '🎯 *LIVE TREND*\n'
                msg += '• Price: `' + str(tr['price']) + '` (' + str(tr['change']) + '%)\n'
                msg += '• Status: ' + tr['status'] + '\n'
                msg += '• VWAP: `' + str(tr['vwap']) + '` | RSI: `' + str(tr['rsi']) + '`\n'
                msg += '💡 ' + tr['action']
                send_telegram_message(chat_id, msg)

            elif text_lower in ['/nifty', '/nifty50']:
                tr = get_live_market_trend('^NSEI')
                msg = '📊 *NIFTY 50*\n'
                msg += '• Price: `' + str(tr['price']) + '` (' + str(tr['change']) + '%)\n'
                msg += '• VWAP: `' + str(tr['vwap']) + '` | RSI: `' + str(tr['rsi']) + '`\n'
                msg += '• Bias: ' + tr['status']
                send_telegram_message(chat_id, msg)

            elif text_lower in ['/banknifty']:
                tr = get_live_market_trend('^NSEBANK')
                msg = '🏦 *BANK NIFTY*\n'
                msg += '• Price: `' + str(tr['price']) + '` (' + str(tr['change']) + '%)\n'
                msg += '• Bias: ' + tr['status']
                send_telegram_message(chat_id, msg)

            elif text_lower in ['/sensex']:
                tr = get_live_market_trend('^BSESN')
                msg = '📈 *SENSEX*\n'
                msg += '• Price: `' + str(tr['price']) + '` (' + str(tr['change']) + '%)\n'
                msg += '• Bias: ' + tr['status']
                send_telegram_message(chat_id, msg)

            elif text_lower == '/pivots':
                send_telegram_message(chat_id, get_pivot_levels('^NSEI'))
            elif text_lower == '/pcr':
                p = analyze_pcr_data()
                msg = '📈 *PCR*\n'
                msg += '• Value: `' + str(p['pcr']) + '`\n'
                msg += '• Sentiment: ' + p['sentiment']
                send_telegram_message(chat_id, msg)
            elif text_lower == '/bigmoney':
                bm = get_big_money_alert()
                msg = '🐋 *SMART MONEY*\n'
                msg += '• ' + bm['action'] + '\n'
                msg += '• ' + bm['details']
                send_telegram_message(chat_id, msg)
            elif text_lower == '/commodity':
                send_telegram_message(chat_id, get_crude_oil_data())
            elif text_lower == '/support':
                msg = '📋 *SUPPORT*\n\n'
                msg += '• For MSME registration or tech support in Bhopal, contact admin.\n\n'
                msg += '_Status: Verified & Active_ ✅'
                send_telegram_message(chat_id, msg)
            elif text_lower == '/summary':
                send_telegram_message(chat_id, get_daily_summary())
            
            elif text_lower == '/signal':
                tr = get_live_market_trend('^NSEI')
                msg = '⚡ *SCALP SIGNAL*\n'
                msg += '• Price: `' + str(tr['price']) + '`\n'
                msg += '• VWAP: `' + str(tr['vwap']) + '` | RSI: `' + str(tr['rsi']) + '`\n'
                msg += '• Mode: ' + tr['status'] + '\n'
                msg += '💡 ' + tr['action']
                send_telegram_message(chat_id, msg)

            elif text_lower in ['/advanced', '/indicators']:
                ind = get_advanced_indicators('^NSEI')
                if not ind:
                    send_telegram_message(chat_id, '⚠️ Data unavailable.')
                else:
                    sma_text = '`' + str(ind['sma_200']) + '`' if ind['sma_200'] else 'N/A'
                    ema9_ok = '✅' if ind['price'] > ind['ema_9'] else '❌'
                    ema21_ok = '✅' if ind['price'] > ind['ema_21'] else '❌'
                    ema50_ok = '✅' if ind['price'] > ind['ema_50'] else '❌'
                    st_signal = '🟢 BUY' if ind['supertrend'] == 'BUY' else '🔴 SELL'
                    signals_text = '\n'.join(['• ' + s for s in ind['signals']])
                    msg = '📊 *ADVANCED TECHNICAL ANALYSIS*\n\n'
                    msg += '💰 *Price:* `' + str(ind['price']) + '`\n\n'
                    msg += '📈 *MOVING AVERAGES:*\n'
                    msg += '• EMA 9: `' + str(ind['ema_9']) + '` ' + ema9_ok + '\n'
                    msg += '• EMA 21: `' + str(ind['ema_21']) + '` ' + ema21_ok + '\n'
                    msg += '• EMA 50: `' + str(ind['ema_50']) + '` ' + ema50_ok + '\n'
                    msg += '• SMA 200: ' + sma_text + '\n\n'
                    msg += '📉 *MACD:*\n'
                    msg += '• MACD: `' + str(ind['macd_line']) + '` | Signal: `' + str(ind['signal_line']) + '`\n'
                    msg += '• Histogram: `' + str(ind['macd_histogram']) + '`\n\n'
                    msg += '📊 *BOLLINGER BANDS:*\n'
                    msg += '• Upper: `' + str(ind['upper_band']) + '`\n'
                    msg += '• Lower: `' + str(ind['lower_band']) + '`\n\n'
                    msg += '⚡ *VOLATILITY:*\n'
                    msg += '• ATR: `' + str(ind['atr']) + '` pts\n'
                    msg += '• ADX: `' + str(ind['adx']) + '`\n\n'
                    msg += '🎯 *SUPERTREND:*\n'
                    msg += '• Signal: ' + st_signal + '\n\n'
                    msg += '🔔 *SIGNALS:*\n' + signals_text
                    send_telegram_message(chat_id, msg)

            elif text_lower in ['/mtf', '/dashboard']:
                send_telegram_message(chat_id, get_mtf_analysis('^NSEI'))
            elif text_lower in ['/volume', '/pcr_data']:
                send_telegram_message(chat_id, get_volume_pcr_analysis('^NSEI'))
            elif text_lower in ['/smart', '/entry']:
                send_telegram_message(chat_id, get_smart_entry_alerts('^NSEI'))

            elif text_lower.startswith('/alert '):
                try:
                    parts = text.split()
                    if len(parts) < 3:
                        raise IndexError
                    sym = parts[1].upper()
                    target = float(parts[2])
                    set_custom_alert(chat_id, sym, target)
                    msg = '🔔 *Alert Set!*\n\n'
                    msg += '• Symbol: `' + sym + '`\n'
                    msg += '• Target: `' + str(target) + '`\n\n'
                    msg += 'Bot alert dega jab price cross karega.\n\n'
                    msg += '💡 Delete: `/delalert ' + sym + '`'
                    send_telegram_message(chat_id, msg)
                except Exception:
                    send_telegram_message(chat_id, '⚠️ Format: `/alert NIFTY 23500`')

            elif text_lower.startswith('/delalert '):
                try:
                    sym = text.split()[1].upper()
                    delete_custom_alert(chat_id, sym)
                    send_telegram_message(chat_id, '🗑️ Alert deleted for `' + sym + '`.')
                except Exception:
                    send_telegram_message(chat_id, '⚠️ Format: `/delalert NIFTY`')

            elif text_lower == '/myalerts':
                alerts = get_custom_alerts(chat_id)
                if not alerts:
                    send_telegram_message(chat_id, '📭 *No Active Alerts*')
                else:
                    msg = '🔔 *Your Active Alerts*\n\n'
                    for a in alerts:
                        msg += '• `' + str(a[1]) + '` @ `' + str(a[2]) + '`\n'
                    send_telegram_message(chat_id, msg)

            else:
                send_telegram_message(chat_id, '✅ Command received. Use buttons below:', reply_markup=get_main_keyboard())

    except Exception as e:
        logging.error(f'Webhook error: {e}')
    return 'OK', 200

threading.Thread(target=keep_alive, daemon=True).start()
threading.Thread(target=background_automation_scheduler, daemon=True).start()
threading.Thread(target=real_time_entry_scanner, daemon=True).start()
threading.Thread(target=auto_trading_scanner, daemon=True).start()
threading.Thread(target=advanced_indicator_scanner, daemon=True).start()
threading.Thread(target=custom_alert_scanner, daemon=True).start()
threading.Thread(target=smart_entry_alert_scanner, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
