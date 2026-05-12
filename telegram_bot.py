import os
import time
import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from supabase import create_client

telegram_router = APIRouter()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").lower()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

MESSAGE_BUFFER = {}


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


def get_recent_chat_history(customer_id: str, limit: int = 10):
    try:
        result = (
            supabase.table("inbox_messages")
            .select("role,content")
            .eq("customer_id", str(customer_id))
            .eq("platform", "telegram")
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        log("Could not load Telegram history", str(e))
        return []


def get_ai_reply(user_text, business, customer_id):
    api_key = business.get("mistral_api_key") or os.getenv("MISTRAL_API_KEY")

    if not api_key:
        return "Assalomu alaykum 😊"

    history = get_recent_chat_history(customer_id)

    system_prompt = f"""
You are a real human sales manager for Milana Premium.

Business info:
{build_business_context(business)}

IMPORTANT BEHAVIOR RULES:

- Speak naturally like a real Telegram sales manager.
- Keep answers short and comfortable.
- Usually 1-3 short sentences.
- Never dump all business information at once.
- Never write huge lists unless customer explicitly asks.
- Never overwhelm the customer.
- Ask follow-up questions naturally.
- Focus on selling and continuing the conversation.
- Sound warm, confident, and human.
- Use emojis lightly.
- Reply in the customer's language.
- Avoid AI-style formatting.
- Avoid long markdown sections.
- Avoid giant bullet lists.
- Talk like a real Uzbek sales manager.

CATALOG RULE:

- Do NOT offer catalog automatically.
- Do NOT send catalog in greeting.
- Do NOT ask "Do you want to see catalog?" in greeting.
- Send catalog ONLY if the customer explicitly asks for:
  catalog, katalog, models, modellar, price list, narxlar, collection, kolleksiya, photos, rasmlar.
- If customer only says hello, greet and ask what they need.
- If customer asks what you sell, answer briefly and ask what product interests them.
- One main idea per message.

GOOD EXAMPLE:
Customer: Assalomu alaykum
Assistant:
Va alaykum assalom! 😊

Milana Premiumga xush kelibsiz! Qanday yordam kerak? Qiziqayotgan mahsulotingiz bormi?

GOOD EXAMPLE:
Customer: What do you sell?
Assistant:
Bizda premium kiyim va tekstil mahsulotlari bor 😊
Qaysi mahsulot sizni qiziqtiryapti?

GOOD EXAMPLE:
Customer: Katalog bormi?
Assistant:
Ha albatta 😊
Mana katalogimiz:
https://shmirzaev.github.io/Milana-Premium-Catalog/

BAD EXAMPLE:
Va alaykum assalom! 😊

Milana Premiumga xush kelibsiz! Qanday yordam kerak?

Katalogimizni ko'rishni xohlaysizmi?
https://shmirzaev.github.io/Milana-Premium-Catalog/

WHY BAD:
- Catalog was offered without customer asking.
- Too much information at once.
- Feels automated.
"""

    messages = [{"role": "system", "content": system_prompt}]

    for msg in history:
        messages.append(
            {
                "role": msg["role"],
                "content": msg["content"],
            }
        )

    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": business.get("ai_model") or "mistral-small-latest",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 130,
    }

    res = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    log("Telegram Mistral response", {"status": res.status_code, "body": res.text})

    if not res.ok:
        return "Assalomu alaykum 😊"

    try:
        reply = (
            res.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        if not reply:
            return "Assalomu alaykum 😊"

        return reply[:1500]

    except Exception as e:
        log("Telegram AI parse error", str(e))
        return "Assalomu alaykum 😊"


def send_telegram_message(chat_id, text, reply_to_message_id=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    res = requests.post(url, json=payload, timeout=30)

    log("Telegram send result", {"status": res.status_code, "body": res.text})

    return res


def save_telegram_message(
    business,
    customer_id,
    text,
    direction,
    message_id="",
    raw_payload=None,
    channel="private",
):
    try:
        data = {
            "business_id": business.get("id"),
            "instagram_business_id": business.get("instagram_business_id"),
            "platform": "telegram",
            "customer_id": str(customer_id),
            "channel": channel,
            "direction": direction,
            "role": "user" if direction == "inbound" else "assistant",
            "content": text,
            "external_message_id": str(message_id),
            "raw_payload": raw_payload or {},
        }

        supabase.table("inbox_messages").insert(data).execute()
        log("Telegram inbox message saved", data)

    except Exception as e:
        log("Could not save Telegram message", str(e))


@telegram_router.get("/webhook/telegram")
async def telegram_webhook_check():
    return PlainTextResponse("Telegram webhook working")


@telegram_router.get("/telegram/set-webhook")
async def set_telegram_webhook():
    webhook_url = f"{PUBLIC_BASE_URL}/webhook/telegram"

    res = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
        params={"url": webhook_url},
        timeout=30,
    )

    return JSONResponse(res.json())


@telegram_router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()

        log("TELEGRAM WEBHOOK RECEIVED", update)

        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
            or {}
        )

        if not message:
            return JSONResponse({"status": "ignored"})

        if message.get("from", {}).get("is_bot"):
            return JSONResponse({"status": "ignored_bot"})

        text = message.get("text", "").strip()

        if not text:
            return JSONResponse({"status": "ignored_no_text"})

        chat = message.get("chat", {})
        user = message.get("from", {})

        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        customer_id = user.get("id")
        message_id = message.get("message_id")

        business = get_active_business()

        if not business:
            return JSONResponse({"status": "no_business"})

        if chat_type in ["group", "supergroup"]:
            mention = f"@{TELEGRAM_BOT_USERNAME}"

            replied_to_bot = (
                message.get("reply_to_message", {})
                .get("from", {})
                .get("is_bot", False)
            )

            if mention not in text.lower() and not replied_to_bot:
                return JSONResponse({"status": "ignored_group_message"})

        buffer_key = f"{chat_id}_{customer_id}"
        current_time = time.time()

        if buffer_key not in MESSAGE_BUFFER:
            MESSAGE_BUFFER[buffer_key] = {
                "texts": [],
                "last_time": current_time,
            }

        MESSAGE_BUFFER[buffer_key]["texts"].append(text)
        MESSAGE_BUFFER[buffer_key]["last_time"] = current_time

        time.sleep(3)

        latest_time = MESSAGE_BUFFER[buffer_key]["last_time"]

        if time.time() - latest_time < 2:
            return JSONResponse({"status": "waiting_more_messages"})

        combined_text = "\n".join(MESSAGE_BUFFER[buffer_key]["texts"]).strip()

        del MESSAGE_BUFFER[buffer_key]

        save_telegram_message(
            business=business,
            customer_id=customer_id,
            text=combined_text,
            direction="inbound",
            message_id=message_id,
            raw_payload=update,
            channel=chat_type,
        )

        reply = get_ai_reply(
            user_text=combined_text,
            business=business,
            customer_id=customer_id,
        )

        send_telegram_message(
            chat_id=chat_id,
            text=reply,
            reply_to_message_id=message_id
            if chat_type in ["group", "supergroup"]
            else None,
        )

        save_telegram_message(
            business=business,
            customer_id=customer_id,
            text=reply,
            direction="outbound",
            message_id="",
            raw_payload={},
            channel=chat_type,
        )

        return JSONResponse({"status": "ok"})

    except Exception as e:
        log("Telegram webhook error", str(e))

        return JSONResponse(
            {
                "status": "error",
                "message": str(e),
            },
            status_code=500,
        )
