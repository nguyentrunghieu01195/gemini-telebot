import asyncio
import io
import json
import logging
import os
from http.server import BaseHTTPRequestHandler
from google import genai
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Thiết lập log cơ bản
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Đọc token từ Environment Variables cấu hình trên Vercel
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Khởi tạo Gemini Client
ai_client = (
    genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
)


async def translate_prompt_to_en(prompt: str) -> str:
    """Tối ưu prompt sang tiếng Anh giúp Imagen tạo ảnh chuẩn hơn."""
    try:
        res = await asyncio.to_thread(
            ai_client.models.generate_content,
            model="gemini-2.5-flash",
            contents=f"Translate and enhance this visual prompt to descriptive English for image generation. Return only the prompt, no intro: '{prompt}'",
        )
        return res.text.strip()
    except Exception:
        return prompt


# --- Handlers Telegram ---


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_text = (
        f"Xin chào {user_name}!\n\n"
        "🤖 **Bot AI Vercel Serverless:**\n"
        "• Nhắn tin bất kỳ: Trò chuyện thông minh cùng Gemini.\n"
        "• Lệnh `/img <mô tả>`: Sinh ảnh nghệ thuật bằng Imagen 3.\n\n"
        "_Lưu ý: Do chạy trên Vercel Serverless (Timeout 15s), tính năng tạo video Veo không thể thực hiện qua Webhook này._"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Kiểm tra xem người dùng có nhập mô tả hay không
    if not context.args:
        await update.message.reply_text(
            "⚠️ Vui lòng nhập mô tả sau lệnh `/img`.\nVí dụ: `/img a cute orange cat in space`",
            parse_mode="Markdown",
        )
        return

    prompt = " ".join(context.args)

    # 2. Phản hồi ngay lập tức để người dùng biết bot đã nhận lệnh
    status_msg = await update.message.reply_text(
        "🎨 Đang xử lý vẽ ảnh, vui lòng đợi..."
    )
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO
    )

    try:
        image_bytes = None

        # Cách 1: Sử dụng mô hình tạo ảnh trực tiếp của Gemini (Hỗ trợ tốt API Key thông thường)
        try:
            response = await asyncio.to_thread(
                ai_client.models.generate_content,
                model="gemini-2.5-flash-image",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
            # Trích xuất dữ liệu ảnh dạng byte
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    break
        except Exception as e_nano:
            logger.warning(
                f"gemini-2.5-flash-image failed: {e_nano}, thử fallback sang Imagen..."
            )

        # Cách 2: Fallback sang Imagen 3 nếu cách 1 không trả về ảnh
        if not image_bytes:
            result = await asyncio.to_thread(
                ai_client.models.generate_images,
                model="imagen-3.0-generate-002",
                prompt=prompt,
                config=dict(number_of_images=1, output_mime_type="image/jpeg"),
            )
            image_bytes = result.generated_images[0].image.image_bytes

        # 3. Gửi ảnh về Telegram
        photo_stream = io.BytesIO(image_bytes)
        photo_stream.name = "output.jpg"

        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=photo_stream,
            caption=f"✨ **Prompt:** {prompt}",
            parse_mode="Markdown",
        )
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Lỗi tạo ảnh: {e}")
        # Báo chi tiết lỗi ra khung chat để dễ debug
        err_text = str(e)
        if "403" in err_text or "PERMISSION_DENIED" in err_text:
            msg = "❌ API Key này chưa được cấp quyền sinh ảnh (Imagen yêu cầu bật billing trên Google Cloud/AI Studio)."
        elif "429" in err_text or "RESOURCE_EXHAUSTED" in err_text:
            msg = "❌ Quá giới hạn request (Rate Limit). Vui lòng thử lại sau 1 phút."
        else:
            msg = f"❌ Lỗi: {err_text[:200]}"

        await status_msg.edit_text(msg)


async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )

    try:
        response = await asyncio.to_thread(
            ai_client.models.generate_content,
            model="gemini-2.5-flash",
            contents=user_text,
        )
        reply_content = response.text or "Không nhận được phản hồi."
        await update.message.reply_text(reply_content)
    except Exception as e:
        logger.error(f"Lỗi chat: {e}")
        await update.message.reply_text("Có lỗi khi kết nối với Gemini.")


# Khởi tạo App Bot ở chế độ không dùng polling
bot_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).updater(None).build()
bot_app.add_handler(CommandHandler("start", cmd_start))
bot_app.add_handler(CommandHandler(["img", "image"], cmd_img))
bot_app.add_handler(
    MessageHandler(filters.TEXT & (~filters.COMMAND), handle_chat)
)


# --- HTTP Entrypoint cho Vercel ---
class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8"))

            update = Update.de_json(payload, bot_app.bot)

            # Chạy loop bất đồng bộ để xử lý tin nhắn
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.process(update))
            loop.close()

            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        except Exception as e:
            logger.error(f"Error handling POST: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    async def process(self, update: Update):
        async with bot_app:
            await bot_app.process_update(update)

    def do_GET(self):
        # Trả về trang test khi mở URL Vercel trên trình duyệt
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            "Telegram Gemini Bot Webhook đang chạy bình thường trên Vercel!".encode(
                "utf-8"
            )
        )