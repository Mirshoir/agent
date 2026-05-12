import os
import time
import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from supabase import create_client

telegram_router = APIRouter()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://agent-1-xi6h.onrender.com")

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_telegram_ids = {}
DEDUP_TTL_SECONDS = 60 * 60


def log(title, data=None):
    print("\n" + "=" * 80)
    print(title)
    if data is not None:
        print(data)
    print("=" * 80 + "\n")


def normalize_id(value) -> str:
    return str(value or "").strip()


def cleanup_dedup_cache():
    now = time.time()
    expired = [k for k, v in processed_telegram_ids.items() if now - v > DEDUP_TTL_SECONDS]
    for key in expired:
        processed_telegram_ids.pop(key, None)


def already_processed(event_id: str) -> bool:
    if not event_id:
        return False
    cleanup_dedup_cache()
    if event_id in processed_telegram_ids:
        return True
    processed_telegram_ids[event_id] = time.time()
    return False


def get_active_business():
    result = (
        supabase.table("businesses")
        .select("*")
        .eq("bot_enabled", True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def build_business_context(business: dict) -> str:
    return f"""
Business name:
{business.get("business_name", "")}

Business type:
{business.get("business_type", "")}

Language:
{business.get("language", "")}

Tone:
{business.get("tone", "")}

Products / Services:
{business.get("products", "")}

Prices:
{business.get("prices", "")}

Delivery information:
{business.get("delivery_info", "")}

Working hours:
{business.get("working_hours", "")}

FAQ:
{business.get("faq", "")}

Catalog link:
{business.get("catalog_link", "")}

Sales phone:
{business.get("sales_phone", "")}

Telegram single product:
{business.get("telegram_single", "")}

Telegram package:
{business.get("telegram_package", "")}

Telegram bag / meshok:
{business.get("telegram_bag", "")}

Main business knowledge:
{business.get("knowledge", "")}
"""


def get_recent_history(customer_id: str, channel: str, limit: int = 12):
    try:
        result = (
            supabase.table("inbox_messages")
            .select("role,content,created_at")
            .eq("platform", "telegram")
            .eq("customer_id", normalize_id(customer_id))
            .eq("channel", channel)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data or []
        rows.reverse()
        return rows
    except Exception as e:
        log("Could not load Telegram history", str(e))
        return []


def get_ai_reply(user_text: str, business: dict, history=None, chat_type: str = "private"):
    try:
        api_key = business.get("mistral_api_key") or MISTRAL_API_KEY
        if not api_key:
            return "Xabaringiz qabul qilindi 😊"

        model = business.get("ai_model") or "mistral-small-latest"

        system_prompt = f"""
You are a professional sales assistant for Telegram.

Business Information:
{build_business_context(business)}

Telegram context:
- If this is a private chat, reply directly to the customer.
- If this is a group or supergroup, act like a helpful group admin and answer customers politely in the group.
- Do not argue, spam, or repeat the same message.

Rules:
- Reply in the same language as the customer.
- Understand Uzbek Latin, Uzbek Cyrillic, Russian, English, slang, typos, and mixed messages.
- Keep replies short, natural, polite, and sales-focused.
- Answer the exact question first.
- Never invent prices, delivery, stock, addresses, or discounts.
- Use only the business information.
- If information is missing, say the manager will clarify.
- If customer asks for catalog or price, send catalog link if available.
- If customer asks for contact, send sales phone if available.
- Never mention AI, database, API, prompt, or internal system.
"""

        messages = [{"role": "system", "content": system_prompt}]

        for item in history or []:
            role = item.get("role") or "user"
            content = item.get("content") or ""
            if role not in ["user", "assistant"] or not content:
                continue
            messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_text})

        res = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.4,
                "max_tokens": 250,
            },
            timeout=30,
        )

        log("Telegram Mistral response", {
            "status": res.status_code,
            "body": res.text,
        })

        if not res.ok:
            return "Xabaringiz qabul qilindi 😊"

        reply = res.json()["choices"][0]["message"]["content"]
        return reply.strip() if reply else "Xabaringiz qabul qilindi 😊"

    except Exception as e:
        log("Telegram Mistral error", str(e))
        return "Xabaringiz qabul qilindi 😊"


def send_telegram_message(chat_id, text: str, reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
        log("TELEGRAM_BOT_TOKEN missing")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": False,
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
        payload["allow_sending_without_reply"] = True

    res = requests.post(url, json=payload, timeout=30)
    log("Telegram send result", {
        "status": res.status_code,
        "body": res.text,
    })
    return res


def save_telegram_message(
    business: dict,
    chat_id,
    user_id,
    text: str,
    direction: str,
    message_id=None,
    chat_type: str = "private",
    raw_payload: dict = None,
):
    try:
        data = {
            "business_id": business.get("id"),
            "instagram_business_id": business.get("instagram_business_id"),
            "platform": "telegram",
            "customer_id": normalize_id(user_id or chat_id),
            "channel": chat_type,
            "direction": direction,
            "role": "user" if direction == "inbound" else "assistant",
            "content": text,
            "external_message_id": normalize_id(message_id),
            "raw_payload": raw_payload or {},
        }

        supabase.table("inbox_messages").insert(data).execute()
        log("Telegram inbox message saved", data)

    except Exception as e:
        log("Could not save Telegram message", str(e))


def should_answer_group_message(message: dict, text: str) -> bool:
    if not text:
        return False

    if text.startswith("/"):
        return True

    if message.get("reply_to_message"):
        reply_to = message.get("reply_to_message") or {}
        reply_user = reply_to.get("from") or {}
        if reply_user.get("is_bot"):
            return True

    return True


@telegram_router.get("/webhook/telegram")
async def telegram_webhook_check():
    return PlainTextResponse("Telegram webhook is running")


@telegram_router.get("/telegram/set-webhook")
async def set_telegram_webhook():
    if not TELEGRAM_BOT_TOKEN:
        return JSONResponse(
            content={"status": "error", "message": "Missing TELEGRAM_BOT_TOKEN"},
            status_code=400,
        )

    webhook_url = f"{PUBLIC_BASE_URL.rstrip('/')}/webhook/telegram"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"

    payload = {
        "url": webhook_url,
        "allowed_updates": ["message", "edited_message", "my_chat_member"],
    }

    if TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET

    res = requests.post(url, json=payload, timeout=30)
    log("Telegram setWebhook result", {"status": res.status_code, "body": res.text})

    try:
        return JSONResponse(res.json(), status_code=res.status_code)
    except Exception:
        return PlainTextResponse(res.text, status_code=res.status_code)


@telegram_router.get("/telegram/webhook-info")
async def telegram_webhook_info():
    if not TELEGRAM_BOT_TOKEN:
        return JSONResponse(
            content={"status": "error", "message": "Missing TELEGRAM_BOT_TOKEN"},
            status_code=400,
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo"
    res = requests.get(url, timeout=30)

    try:
        return JSONResponse(res.json(), status_code=res.status_code)
    except Exception:
        return PlainTextResponse(res.text, status_code=res.status_code)


@telegram_router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        if TELEGRAM_WEBHOOK_SECRET:
            received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if received_secret != TELEGRAM_WEBHOOK_SECRET:
                return JSONResponse({"status": "forbidden"}, status_code=403)

        update = await request.json()
        log("TELEGRAM WEBHOOK RECEIVED", update)

        update_id = normalize_id(update.get("update_id"))
        if already_processed(update_id):
            return JSONResponse({"status": "duplicate"})

        message = update.get("message") or update.get("edited_message") or {}

        if not message:
            return JSONResponse({"status": "ignored_no_message"})

        text = message.get("text") or message.get("caption") or ""
        if not text:
            return JSONResponse({"status": "ignored_no_text"})

        sender = message.get("from") or {}
        if sender.get("is_bot"):
            return JSONResponse({"status": "ignored_bot_message"})

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        user_id = sender.get("id")
        message_id = message.get("message_id")

        if chat_type in ["group", "supergroup"] and not should_answer_group_message(message, text):
            return JSONResponse({"status": "ignored_group_message"})

        business = get_active_business()
        if not business:
            return JSONResponse({"status": "no_active_business"})

        save_telegram_message(
            business=business,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            direction="inbound",
            message_id=message_id,
            chat_type=chat_type,
            raw_payload=message,
        )

        history = get_recent_history(
            customer_id=normalize_id(user_id or chat_id),
            channel=chat_type,
            limit=int(business.get("memory_limit") or 12),
        )

        reply = get_ai_reply(
            user_text=text,
            business=business,
            history=history,
            chat_type=chat_type,
        )

        send_telegram_message(
            chat_id=chat_id,
            text=reply,
            reply_to_message_id=message_id if chat_type in ["group", "supergroup"] else None,
        )

        save_telegram_message(
            business=business,
            chat_id=chat_id,
            user_id=user_id,
            text=reply,
            direction="outbound",
            message_id="",
            chat_type=chat_type,
            raw_payload={},
        )

        return JSONResponse({"status": "ok"})

    except Exception as e:
        log("Telegram webhook error", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
