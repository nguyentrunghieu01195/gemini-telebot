# Telegram Gemini Bot

Telegram bot chạy dưới dạng Vercel Python Function. Bot hỗ trợ trò chuyện với
Gemini trong tin nhắn riêng/nhóm và tạo ảnh bằng lệnh `/img`.

## Cấu hình

Thiết lập ba biến môi trường trên Vercel:

- `TELEGRAM_BOT_TOKEN`: token lấy từ BotFather.
- `GEMINI_API_KEY`: API key của Google AI Studio.
- `WEBHOOK_SECRET_TOKEN`: chuỗi bí mật ngẫu nhiên chỉ gồm `A-Z`, `a-z`, `0-9`,
  `_` và `-` (1–256 ký tự).

Đăng ký webhook và truyền đúng cùng secret:

```bash
curl --request POST \
  "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  --data-urlencode "url=https://<YOUR_DEPLOYMENT>/" \
  --data-urlencode "secret_token=<WEBHOOK_SECRET_TOKEN>"
```

Không commit các giá trị bí mật vào repository.

## Chạy local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="..."
export GEMINI_API_KEY="..."
python local_test.py
```

`local_test.py` sử dụng polling nên không cần `WEBHOOK_SECRET_TOKEN`.

## Kiểm tra

```bash
python -m unittest discover -s tests
python -m py_compile api/index.py local_test.py
```

## Giới hạn kiến trúc

Việc ghi nhớ `update_id` hiện nằm trong bộ nhớ của từng serverless instance. Nó
ngăn retry trùng trên cùng instance nhưng không bảo đảm idempotency giữa nhiều
instance. Tạo ảnh cũng diễn ra ngay trong request webhook và có thể vượt timeout
của gói hosting. Nếu bot có lưu lượng thực tế, nên đưa tác vụ Gemini vào queue,
lưu `update_id` trong Redis/database và để worker gửi kết quả về Telegram.
