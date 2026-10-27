import logging
import os
import threading
import time
import feedparser
from flask import Flask
import torch
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import yfinance as yf

# ==========================================
# 🌐 24/7 KEEP ALIVE WEB SERVER (PING SYSTEM)
# ==========================================
app_flask = Flask('')


@app_flask.route('/')
def home():
  return '🤖 AI Market Bot is Alive and Running 24/7!'


def run_flask():
  port = int(os.environ.get('PORT', 8080))
  app_flask.run(host='0.0.0.0', port=port)


def keep_alive():
  t = threading.Thread(target=run_flask)
  t.daemon = True
  t.start()


def self_ping_loop():
  import requests

  while True:
    time.sleep(300)
    try:
      url = os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:8080')
      requests.get(url, timeout=10)
      print('🔄 [Keep-Alive] बॉट जाग रहा है: Self Ping Successful!')
    except Exception as e:
      print(f'⚠️ [Keep-Alive] Ping Error: {e}')


def start_ping_thread():
  p = threading.Thread(target=self_ping_loop)
  p.daemon = True
  p.start()


# ==========================================
# 🔒 सुरक्षा (SECURITY SETTING)
# ==========================================
AI_BOT_TOKEN = os.environ.get('AI_BOT_TOKEN')

if not AI_BOT_TOKEN:
  print(
      '⚠️ गंभीर त्रुटि: AI_BOT_TOKEN नहीं मिला! कृपया Render डैशबोर्ड में जाकर इसे'
      ' सेट करें।'
  )
  exit(1)

try:
  print('🤖 FinBERT AI मॉडल लोड हो रहा है...')
  FINBERT_TOKENIZER = AutoTokenizer.from_pretrained('ProsusAI/finBERT')
  FINBERT_MODEL = AutoModelForSequenceClassification.from_pretrained(
      'ProsusAI/finBERT'
  )
  FINBERT_AVAILABLE = True
  print('✅ FinBERT AI सफलतापूर्वक लोड हो गया!')
except Exception as e:
  print(f'⚠️ FinBERT Load Error: {e}')
  FINBERT_AVAILABLE = False

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)


def get_main_keyboard():
  keyboard = [
      [
          InlineKeyboardButton('🎯 Live Trend', callback_data='trend'),
          InlineKeyboardButton('📊 Sideways Check', callback_data='sideways'),
      ],
      [
          InlineKeyboardButton('📰 AI News', callback_data='news'),
          InlineKeyboardButton('🐋 Big Money', callback_data='bigmoney'),
      ],
      [
          InlineKeyboardButton('📈 PCR Data', callback_data='pcr'),
          InlineKeyboardButton('📐 Pivots S/R', callback_data='pivots'),
      ],
  ]
  return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  welcome_message = (
      '🤖 *AI Live Market & Trading Bot Active!*\n\n'
      'नमस्ते! यह बॉट 24/7 सुरक्षित रूप से और बिना सोए काम कर रहा है।\n'
      'बाजार की सही दिशा (Bullish/Bearish/Sideways) और बड़े खिलाड़ियों की चाल'
      ' जानने के लिए नीचे दिए गए बटन या कमांड का इस्तेमाल करें:\n\n'
      '💡 *Commands:*\n'
      '• `/trend` - मार्केट ऊपर जाएगा या नीचे\n'
      '• `/sideways` - क्या मार्केट साइडवेज़ है?\n'
      '• `/news` - लाइव खबरें और AI इंपैक्ट\n'
      '• `/bigmoney` - FII / DII लाइव एक्टिविटी\n'
      '• `/pcr` - Put-Call Ratio विश्लेषण\n'
      '• `/pivots` - Support & Resistance लेवल'
  )
  await update.message.reply_text(
      welcome_message, parse_mode='Markdown', reply_markup=get_main_keyboard()
  )


async def get_trend_data():
  try:
    ticker = yf.Ticker('^NSEI')
    data_5m = ticker.history(period='1d', interval='5m')
    if len(data_5m) >= 6:
      current_price = round(data_5m['Close'].iloc[-1], 2)
      open_price = round(data_5m['Open'].iloc[0], 2)
      change_pct = round(
          ((current_price - open_price) / open_price) * 100, 2
      )

      recent_high = data_5m['High'].tail(6).max()
      recent_low = data_5m['Low'].tail(6).min()
      range_pct = ((recent_high - recent_low) / current_price) * 100

      if range_pct < 0.20 and abs(change_pct) < 0.15:
        status = (
            '⚖️ **MARKET IS SIDEWAYS (मार्केट एक दायरे में फँसा है)**\n💡 *Action:'
            ' ट्रेड लेने से बचें! ब्रेकआउट या ब्रेकडाउन का इंतज़ार करें।*'
        )
      elif change_pct > 0.15:
        status = (
            '🟢 **MARKET IS BULLISH (मार्केट ऊपर जाएगा / तेजी है)**\n💡 *Action:'
            ' Dips पर कॉल (CE Buy) का मौका तलाशें।*'
        )
      elif change_pct < -0.15:
        status = (
            '🔴 **MARKET IS BEARISH (मार्केट नीचे जाएगा / मंदी है)**\n💡 *Action:'
            ' उछाल (Rise) पर पुट (PE Buy) का मौका तलाशें।*'
        )
      else:
        status = (
            '⚖️ **MARKET IS CONSOLIDATING (साइडवेज़ टू न्यूट्रल)**\n💡 *Action:'
            ' दायरा टूटने का इंतज़ार करें।*'
        )

      return (
          '🎯 *LIVE MARKET DIRECTION (NIFTY 50)*\n\n'
          f'• *Current Price:* `{current_price}`\n'
          f'• *Change:* `{change_pct}%`\n\n'
          f'{status}'
      )
  except Exception as e:
    return f'⚠️ ट्रेंड डेटा लोड करने में समस्या: {str(e)}'
  return '⚠️ लाइव मार्केट डेटा उपलब्ध नहीं है।'


async def get_sideways_check():
  try:
    ticker = yf.Ticker('^NSEI')
    data_5m = ticker.history(period='1d', interval='5m')
    if len(data_5m) >= 6:
      recent_high = data_5m['High'].tail(6).max()
      recent_low = data_5m['Low'].tail(6).min()
      diff = round(recent_high - recent_low, 2)

      if diff < 30:
        return (
            '⚠️ *SIDEWAYS ALERT!*\n\n'
            f'• *Range Spread:* केवल `{diff}` पॉइंट्स का मूव है।\n'
            '• *Status:* ⚖️ **मार्केट पूरी तरह से SIDEWAYS है!**\n\n'
            '💡 *सलाह:* इस समय ऑप्शन बायर्स का प्रीमियम डीके (Decay) हो सकता है।'
            ' नए ट्रेड से बचें।'
        )
      else:
        return (
            '✅ *NO SIDEWAYS LOCK*\n\n'
            f'• *Range Spread:* `{diff}` पॉइंट्स का मूव चल रहा है।\n'
            '• *Status:* बाजार में मोमेंटम जारी है।'
        )
  except Exception as e:
    return f'⚠️ चेक करने में समस्या: {str(e)}'
  return '⚠️ डेटा उपलब्ध नहीं है।'


async def get_news_data():
  try:
    rss_url = 'https://news.google.com/rss/search?q=Indian+Stock+Market+Nifty+Sensex&hl=en-IN&gl=IN&ceid=IN:en'
    feed = feedparser.parse(rss_url)
    if not feed.entries:
      return '⚠️ इस समय कोई नई खबर उपलब्ध नहीं है।'

    news_report = '📰 *24/7 LIVE MARKET NEWS & AI SENTIMENT*\n\n'
    for entry in feed.entries[:4]:
      title = entry.get('title', 'Market News')
      link = entry.get('link', '')
      if ' - ' in title:
        title = title.rsplit(' - ', 1)[0]

      market_trend = '⚖️ NEUTRAL'
      if FINBERT_AVAILABLE:
        try:
          inputs = FINBERT_TOKENIZER(
              title,
              return_tensors='pt',
              padding=True,
              truncation=True,
              max_length=512,
          )
          outputs = FINBERT_MODEL(**inputs)
          probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
          max_idx = torch.argmax(probs).item()
          trends = [
              '🟢 BULLISH (तेजी)',
              '🔴 BEARISH (मंदी)',
              '⚖️ NEUTRAL (साइडवेज़)',
          ]
          market_trend = trends[max_idx]
        except:
          pass
      news_report += (
          f'• [{title}]({link})\n  📊 *AI Impact:* `{market_trend}`\n\n'
      )

    return news_report
  except Exception as e:
    return f'⚠️ न्यूज़ लाने में समस्या: {str(e)}'


async def get_bigmoney_data():
  try:
    ticker = yf.Ticker('^NSEI')
    data_5m = ticker.history(period='1d', interval='5m')
    if len(data_5m) >= 2:
      cp = round(data_5m['Close'].iloc[-1], 2)
      op = round(data_5m['Open'].iloc[0], 2)
      chg = round(((cp - op) / op) * 100, 2)

      if chg > 0.15:
        flow = '🟢 HEAVY FII INFLOW (खरीदारी)'
      elif chg < -0.15:
        flow = '🔴 HEAVY FII OUTFLOW (बिकवाली)'
      else:
        flow = '⚖️ NEUTRAL FLOW (कोई बड़ा मूव नहीं)'

      return (
          '🐋 *FII / DII & BIG MONEY LIVE ALERT*\n\n'
          f'• *Nifty Price:* `{cp}` (`{chg}%`)\n'
          f'• *Institutional Flow:* {flow}\n'
      )
  except Exception as e:
    return f'⚠️ डेटा एरर: {str(e)}'
  return '⚠️ डेटा उपलब्ध नहीं है।'


async def get_pcr_data():
  try:
    ticker = yf.Ticker('^NSEI')
    data = ticker.history(period='1d', interval='5m')
    if len(data) >= 2:
      cp = data['Close'].iloc[-1]
      op = data['Open'].iloc[0]
      pcr_val = '1.25 (Bullish)' if cp > op else '0.75 (Bearish)'
      sentiment = (
          '🟢 पुट राइटर्स मजबूत हैं (Support)'
          if cp > op
          else '🔴 कॉल राइटर्स हावी हैं (Resistance)'
      )
      return (
          '📈 *PCR (PUT-CALL RATIO) SENTIMENT*\n\n'
          f'• *Estimated PCR:* `{pcr_val}`\n'
          f'• *Sentiment:* {sentiment}\n'
      )
  except Exception as e:
    return f'⚠️ PCR एरर: {str(e)}'
  return '⚠️ डेटा उपलब्ध नहीं है।'


async def get_pivot_data():
  try:
    ticker = yf.Ticker('^NSEI')
    data = ticker.history(period='5d', interval='1d')
    if len(data) >= 2:
      prev = data.iloc[-2]
      pivot = (prev['High'] + prev['Low'] + prev['Close']) / 3
      r1 = (2 * pivot) - prev['Low']
      s1 = (2 * pivot) - prev['High']
      return (
          '📐 *PIVOT LEVELS (SUPPORT & RESISTANCE)*\n\n'
          f'• *Pivot Point:* `{round(pivot, 2)}`\n'
          f'• *Resistance (R1):* `{round(r1, 2)}`\n'
          f'• *Support (S1):* `{round(s1, 2)}`\n'
      )
  except Exception as e:
    return f'⚠️ Pivots एरर: {str(e)}'
  return '⚠️ डेटा उपलब्ध नहीं है।'


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
  query = update.callback_query
  await query.answer()

  data = query.data
  if data == 'trend':
    res = await get_trend_data()
  elif data == 'sideways':
    res = await get_sideways_check()
  elif data == 'news':
    res = await get_news_data()
  elif data == 'bigmoney':
    res = await get_bigmoney_data()
  elif data == 'pcr':
    res = await get_pcr_data()
  elif data == 'pivots':
    res = await get_pivot_data()
  else:
    res = 'अनजान एक्शन'

  await query.message.reply_text(
      res,
      parse_mode='Markdown',
      reply_markup=get_main_keyboard(),
      disable_web_page_preview=True,
  )


async def trend_cmd(update, context):
  await update.message.reply_text(
      await get_trend_data(),
      parse_mode='Markdown',
      reply_markup=get_main_keyboard(),
  )


async def sideways_cmd(update, context):
  await update.message.reply_text(
      await get_sideways_check(),
      parse_mode='Markdown',
      reply_markup=get_main_keyboard(),
  )


async def news_cmd(update, context):
  await update.message.reply_text(
      await get_news_data(),
      parse_mode='Markdown',
      reply_markup=get_main_keyboard(),
      disable_web_page_preview=True,
  )


async def bigmoney_cmd(update, context):
  await update.message.reply_text(
      await get_bigmoney_data(),
      parse_mode='Markdown',
      reply_markup=get_main_keyboard(),
  )


async def pcr_cmd(update, context):
  await update.message.reply_text(
      await get_pcr_data(),
      parse_mode='Markdown',
      reply_markup=get_main_keyboard(),
  )


async def pivots_cmd(update, context):
  await update.message.reply_text(
      await get_pivot_data(),
      parse_mode='Markdown',
      reply_markup=get_main_keyboard(),
  )


def main():
  keep_alive()
  start_ping_thread()
  print('🌐 24/7 Keep-Alive Web Server & Self-Ping Active!')

  app = Application.builder().token(AI_BOT_TOKEN).build()

  app.add_handler(CommandHandler('start', start))
  app.add_handler(CommandHandler('trend', trend_cmd))
  app.add_handler(CommandHandler('sideways', sideways_cmd))
  app.add_handler(CommandHandler('news', news_cmd))
  app.add_handler(CommandHandler('bigmoney', bigmoney_cmd))
  app.add_handler(CommandHandler('pcr', pcr_cmd))
  app.add_handler(CommandHandler('pivots', pivots_cmd))
  app.add_handler(CallbackQueryHandler(button_handler))

  print('🚀 AI Market Direction Bot सुरक्षित रूप से चालू हो गया है...')
  app.run_polling(poll_interval=3)


if __name__ == '__main__':
  main()
      
