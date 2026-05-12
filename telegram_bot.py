import os
import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from supabase import create_client

telegram_router = APIRouter()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def log(title, data=None):
    print("\n" + "=" * 80)
    print(title)
    if data is not None:
        print(data)
    print("=" * 80 + "\n")


def get_active_business():
    result = (
        supabase.table("businesses")
        .select("*")
        .eq("bot_enabled", True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def build_business_context(business):
    return f"""
Business name:
{business.get("business_name", "")}

Business type:
{business.get("business_type", "")}

Language:
{business.get("language", "")}

Products:
{business.get("products", "")}

Prices:
{business.get("prices", "")}

Delivery:
{business.get("delivery_info", "")}

FAQ:
{business.get("faq", "")}

Catalog:
{business.get("catalog_link", "")}

Phone:
{business.get("sales_phone", "")}

Knowledge:
{business.get("knowledge", "")}
"""


def get_ai_reply(user_text, business):
    api_key = business.get("mistral_api_key") or os.getenv("MISTRAL_API_KEY")

    if not api_key:
        return "Xabaringiz qabul qilindi 😊"

    system_prompt = f"""
You are a professional sales assistant.

Business info:
{build_business_context(business)}

Rules:
- Reply in the same language as the customer.
- Keep replies short and natural.
- Answer only from business information.
- Do not invent prices, stock, delivery, or addresses.
- If missing, say manager will clarify.
"""

    res = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": business.get("ai_model") or "mistral-small-latest",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.4,
            "max_tokens": 250,
        },
        timeout=30,
    )

    log("Telegram Mistral response", {"status": res.status_code, "body": res.text})

    if not res.ok:
        return "Xabaringiz qabul qilindi 😊"

    return res.json()["choices"][0]["message"]["content"].strip()


def send_telegram_message(chat_id, text, reply_to_message_id=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    res = requests.post(url, json=payload, timeout=30)
    log("Telegram send result", {"status": res.status_code, "body": res.text})
    return res


def save_telegram_message(business, chat_id, user_id, text, direction, message_id=None, chat_type="private"):
    try:
        data = {
            "business_id": business.get("id"),
            "instagram_business_id": business.get("instagram_business_id"),
            "platform": "telegram",
            "customer_id": str(user_id),
            "channel": chat_type,
            "direction": direction,
            "role": "user" if direction == "inbound" else "assistant",
            "content": text,
            "external_message_id": str(message_id or ""),
            "raw_payload": {},
        }

        supabase.table("inbox_messages").insert(data).execute()

    except Exception as e:
        log("Could not save Telegram message", str(e))


@telegram_router.get("/webhook/telegram")
async def telegram_webhook_check():
    return PlainTextResponse("Telegram webhook is running")


@telegram_router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
        log("TELEGRAM WEBHOOK RECEIVED", update)

        message = update.get("message") or update.get("edited_message") or {}

        if not message:
            return JSONResponse({"status": "ignored"})

        text = message.get("text") or ""
        if not text:
            return JSONResponse({"status": "ignored_no_text"})

        chat = message.get("chat", {})
        user = message.get("from", {})

        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        user_id = user.get("id")
        message_id = message.get("message_id")

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
        )

        reply = get_ai_reply(text, business)

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
        )

        return JSONResponse({"status": "ok"})

    except Exception as e:
        log("Telegram webhook error", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
