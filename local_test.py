import asyncio
import os
from google import genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN and GEMINI_API_KEY before running")

ai_client = genai.Client(api_key=GEMINI_API_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot đang test ở máy cục bộ (Polling)!")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = await asyncio.to_thread(
        ai_client.models.generate_content,
        model="gemini-2.5-flash",
        contents=update.message.text,
    )
    text = res.text or "Không nhận được phản hồi."
    for start_index in range(0, len(text), 4000):
        await update.message.reply_text(text[start_index : start_index + 4000])


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat))
    print("Bot đang chạy ở máy local...")
    app.run_polling()
