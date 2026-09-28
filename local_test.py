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

from api.conversation import ConversationMemory
from api.utils import split_telegram_text

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN and GEMINI_API_KEY before running")

ai_client = genai.Client(api_key=GEMINI_API_KEY)
conversation_memory = ConversationMemory(max_messages=16, max_characters=24_000)


def conversation_key(update: Update) -> tuple[int, int]:
    message = update.effective_message
    thread_id = message.message_thread_id if message else None
    return update.effective_chat.id, thread_id or 0


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot đang test ở máy cục bộ (Polling)! Dùng /reset để xóa ngữ cảnh."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversation_memory.clear(conversation_key(update))
    await update.message.reply_text("Đã xóa ngữ cảnh hội thoại hiện tại.")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = conversation_key(update)
    contents = conversation_memory.get(key)
    contents.append({"role": "user", "parts": [{"text": update.message.text}]})
    res = await asyncio.to_thread(
        ai_client.models.generate_content,
        model="gemini-2.5-flash",
        contents=contents,
    )
    text = res.text or "Không nhận được phản hồi."
    conversation_memory.add_exchange(key, update.message.text, text)
    for chunk in split_telegram_text(text):
        await update.message.reply_text(chunk)


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(["reset", "new"], reset))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat))
    print("Bot đang chạy ở máy local...")
    app.run_polling()
