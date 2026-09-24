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
    if not context.args:
        await update.message.reply_text(
            "⚠️ Vui lòng nhập mô tả ảnh!\nVí dụ: `/img cute cat in space, 4k digital art`",
            parse_mode="Markdown",
        )
        return

    prompt = " ".join(context.args)

    status_msg = await update.message.reply_text(
        "🎨 Đang vẽ ảnh với Imagen 3, vui lòng đợi..."
    )
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO
    )

    try:
        # Gọi chính xác API của Imagen 3 dành cho Google AI Studio
        result = await asyncio.to_thread(
            ai_client.models.generate_images,
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=dict(
                number_of_images=1,
                aspect_ratio="1:1",
                output_mime_type="image/jpeg",
            ),
        )

        # Lấy dữ liệu bytes của ảnh
        image_bytes = result.generated_images[0].image.image_bytes
        photo_stream = io.BytesIO(image_bytes)
        photo_stream.name = "generated.jpg"

        # Gửi ảnh về Telegram
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=photo_stream,
            caption=f"✨ **Prompt:** {prompt}",
            parse_mode="Markdown",
        )
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Lỗi tạo ảnh: {e}")
        err_msg = str(e)

        # Bắt các trường hợp lỗi thường gặp của AI Studio
        if (
            "403" in err_msg
            or "PERMISSION_DENIED" in err_msg
            or "billed" in err_msg.lower()
        ):
            await status_msg.edit_text(
                "❌ **Lỗi phân quyền:** Mô hình Imagen 3 trên Google AI Studio yêu cầu dự án phải liên kết thẻ thanh toán (Billing/Pay-as-you-go). Tài khoản Free Tier hiện chưa hỗ trợ gọi trực tiếp Imagen 3 qua API."
            )
        elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
            await status_msg.edit_text(
                "❌ Hết hạn ngạch tạm thời (Rate Limit). Vui lòng thử lại sau 1 phút."
            )
        else:
            await status_msg.edit_text(f"❌ Chi tiết lỗi:\n`{err_msg[:250]}`")


async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Bỏ qua nếu không có tin nhắn văn bản
    if not update.message or not update.message.text:
        return

    message = update.message
    chat_type = message.chat.type  # 'private', 'group', hoặc 'supergroup'
    user_text = message.text
    bot_username = context.bot.username

    # Xử lý logic theo môi trường:
    is_private = chat_type == "private"
    is_mentioned = bot_username and f"@{bot_username}" in user_text
    is_reply_to_bot = (
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == context.bot.id
    )

    # Nếu ở trong Group: Chỉ trả lời khi được tag HOẶC khi được reply
    # (Nếu muốn bot trả lời TẤT CẢ mọi tin nhắn trong group, bạn chỉ cần bỏ điều kiện if này đi)
    if not is_private and not (is_mentioned or is_reply_to_bot):
        return

    # Lọc bỏ chữ @tên_bot ra khỏi câu hỏi để Gemini không bị bối rối
    if is_mentioned and bot_username:
        user_text = user_text.replace(f"@{bot_username}", "").strip()

    if not user_text:
        await message.reply_text("Dạ, bạn cần mình hỗ trợ gì ạ?")
        return

    # Hiển thị trạng thái đang soạn tin nhắn
    await context.bot.send_chat_action(
        chat_id=message.chat_id, action=ChatAction.TYPING
    )

    try:
        # Gọi Gemini
        response = await asyncio.to_thread(
            ai_client.models.generate_content,
            model="gemini-2.5-flash",
            contents=user_text,
        )
        reply_content = response.text or "Không nhận được phản hồi."

        # Trả lời dạng Reply vào chính tin nhắn của người hỏi trong nhóm
        await message.reply_text(reply_content, reply_to_message_id=message.message_id)

    except Exception as e:
        logger.error(f"Lỗi chat nhóm: {e}")
        await message.reply_text("Có lỗi khi kết nối với AI, vui lòng thử lại sau!")


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