import asyncio
import hmac
import io
import json
import logging
import os
import re
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler

from google import genai
from google.genai import types
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from api.utils import split_telegram_text

# Thiết lập log cơ bản
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Đọc token từ Environment Variables cấu hình trên Vercel
def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


TELEGRAM_BOT_TOKEN = required_env("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = required_env("GEMINI_API_KEY")
WEBHOOK_SECRET_TOKEN = required_env("WEBHOOK_SECRET_TOKEN")
if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", WEBHOOK_SECRET_TOKEN):
    raise RuntimeError(
        "WEBHOOK_SECRET_TOKEN must be 1-256 characters using A-Z, a-z, 0-9, _ or -"
    )

# Khởi tạo Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Giảm việc xử lý lại khi Telegram retry trong cùng một serverless instance.
# Đây không thay thế một idempotency store dùng chung giữa nhiều instance.
_processed_update_ids: set[int] = set()
_processed_update_order: deque[int] = deque()
_processed_update_lock = threading.Lock()
_MAX_TRACKED_UPDATES = 2_000


def remember_update(update_id: int) -> bool:
    """Return False when an update has already been seen in this instance."""
    with _processed_update_lock:
        if update_id in _processed_update_ids:
            return False
        _processed_update_ids.add(update_id)
        _processed_update_order.append(update_id)
        if len(_processed_update_order) > _MAX_TRACKED_UPDATES:
            oldest = _processed_update_order.popleft()
            _processed_update_ids.discard(oldest)
        return True


def forget_update(update_id: int) -> None:
    """Allow Telegram to retry an update that failed during processing."""
    with _processed_update_lock:
        _processed_update_ids.discard(update_id)
        try:
            _processed_update_order.remove(update_id)
        except ValueError:
            pass


async def reply_long_text(message, text: str) -> None:
    for index, chunk in enumerate(split_telegram_text(text)):
        kwargs = {"reply_to_message_id": message.message_id} if index == 0 else {}
        await message.reply_text(chunk, **kwargs)


# --- Handlers Telegram ---


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name if update.effective_user else "bạn"
    welcome_text = (
        f"Xin chào {user_name}!\n\n"
        "🤖 Bot AI Vercel Serverless:\n"
        "• Nhắn tin bất kỳ: Trò chuyện thông minh cùng Gemini.\n"
        "• Lệnh /img <mô tả>: Sinh ảnh bằng Gemini.\n\n"
        "Lưu ý: Tạo ảnh có thể mất nhiều thời gian hơn trò chuyện."
    )
    await update.message.reply_text(welcome_text)


async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Kiểm tra tham số người dùng nhập
    if not context.args:
        await update.message.reply_text(
            "⚠️ Vui lòng nhập mô tả ảnh!\nVí dụ: /img một chú mèo cam phi hành gia trên sao hỏa",
        )
        return

    prompt = " ".join(context.args)

    status_msg = await update.message.reply_text(
        "🎨 Đang vẽ ảnh với Gemini, vui lòng đợi vài giây..."
    )
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO
    )

    try:
        # 2. Gọi mô hình Gemini tạo ảnh chính thức qua SDK
        # Chạy trong asyncio.to_thread để không nghẽn event loop của Vercel Webhook
        response = await asyncio.to_thread(
            ai_client.models.generate_content,
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        image_bytes = None

        # 3. Trích xuất bytes ảnh từ candidates trả về
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts or []:
                # Với SDK google-genai, dữ liệu ảnh nằm trong inline_data.data
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    image_bytes = part.inline_data.data
                    break

        if not image_bytes:
            # Trường hợp an toàn (Safety filter chặn hoặc prompt bị từ chối)
            refusal = (
                response.text
                if hasattr(response, "text") and response.text
                else "Prompt vi phạm chính sách an toàn hoặc không thể tạo ảnh."
            )
            await status_msg.edit_text(f"⚠️ Không nhận được ảnh: {refusal}")
            return

        # 4. Gửi ảnh trực tiếp về Telegram
        photo_stream = io.BytesIO(image_bytes)
        photo_stream.name = "gemini_generated.jpg"

        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=photo_stream,
            caption=f"✨ Prompt: {prompt}"[:1024],
        )
        await status_msg.delete()

    except Exception as e:
        logger.exception("Lỗi tạo ảnh Gemini")
        err_msg = str(e)
        if "403" in err_msg or "PERMISSION_DENIED" in err_msg:
            await status_msg.edit_text(
                "❌ Lỗi quyền hạn (403): API Key chưa được kích hoạt quyền tạo ảnh hoặc project cần liên kết phương thức thanh toán trên Google AI Studio."
            )
        elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
            await status_msg.edit_text(
                "❌ Đã chạm giới hạn lượt gọi (Rate Limit), vui lòng thử lại sau 1 phút."
            )
        else:
            await status_msg.edit_text(f"❌ Không thể tạo ảnh: {err_msg[:250]}")


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
        await reply_long_text(message, reply_content)

    except Exception:
        logger.exception("Lỗi xử lý chat")
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

    def send_text(self, status: int, body: str) -> None:
        self.send_response(status)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_POST(self):
        supplied_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied_secret, WEBHOOK_SECRET_TOKEN):
            self.send_text(403, "Forbidden")
            return

        update_id = None
        loop = None
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0 or content_length > 1_000_000:
                self.send_text(400, "Invalid request size")
                return
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8"))

            update_id = payload.get("update_id")
            if not isinstance(update_id, int):
                self.send_text(400, "Missing update_id")
                return
            if not remember_update(update_id):
                self.send_text(200, "Already processed")
                return

            update = Update.de_json(payload, bot_app.bot)

            # Chạy loop bất đồng bộ để xử lý tin nhắn
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.process(update))

            self.send_text(200, "OK")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            if update_id is not None:
                forget_update(update_id)
            logger.exception("Invalid webhook request")
            self.send_text(400, "Invalid request")
        except Exception:
            if update_id is not None:
                forget_update(update_id)
            logger.exception("Error handling webhook")
            self.send_text(500, "Internal server error")
        finally:
            if loop is not None:
                loop.close()

    async def process(self, update: Update):
        async with bot_app:
            await bot_app.process_update(update)

    def do_GET(self):
        # Trả về trang test khi mở URL Vercel trên trình duyệt
        self.send_text(200, "Telegram Gemini Bot webhook is available.")
