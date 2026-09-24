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

# Có thể thay trực tiếp token vào đây để test nhanh ở local
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "DIEN_TOKEN_TELE_VAO_DAY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "DIEN_KEY_GEMINI_VAO_DAY")

ai_client = genai.Client(api_key=GEMINI_API_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot đang test ở máy cục bộ (Polling)!")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = ai_client.models.generate_content(
        model="gemini-2.5-flash", contents=update.message.text
    )
    await update.message.reply_text(res.text)


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat))
    print("Bot đang chạy ở máy local...")
    app.run_polling()