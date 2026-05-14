import os
import time
import requests
from fastapi.responses import JSONResponse
from supabase import create_client

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

PROCESSED_WHATSAPP_MESSAGES = {}


def log(title, data=None):
    print("\n" + "=" * 80)
    print(title)
    if data is not None:
        print(data)
    print("=" * 80 + "\n")


def already_processed(event_id, ttl=3600):
    if not event_id:
        return False

    now = time.time()
    expired = [k for k, v in PROCESSED_WHATSAPP_MESSAGES.items() if now - v > ttl]
    for k in expired:
        PROCESSED_WHATSAPP_MESSAGES.pop(k, None)

    if event_id in PROCESSED_WHATSAPP_MESSAGES:
        return True

    PROCESSED_WHATSAPP_MESSAGES[event_id] = now
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


def is_chat_ai_enabled(platform, channel, customer_id, business_id=None):
    try:
        query = (
            supabase.table("chat_ai_settings")
            .select("ai_enabled")
            .eq("platform", platform)
            .eq("channel", channel or "")
            .eq("customer_id", str(customer_id))
        )

        if business_id:
            query = query.eq("business_id", business_id)

        rows = query.limit(1).execute().data or []
        if not rows:
            return True

        return bool(rows[0].get("ai_enabled", True))
    except Exception as e:
        log("Could not check WhatsApp AI setting", str(e))
        return True


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

Working hours:
{business.get("working_hours", "")}

FAQ:
{business.get("faq", "")}

Catalog:
{business.get("catalog_link", "")}

Phone:
{business.get("sales_phone", "")}

Knowledge:
{business.get("knowledge", "")}
"""


def get_recent_chat_history(customer_id, limit=10):
    try:
        return (
            supabase.table("inbox_messages")
            .select("role,content")
            .eq("platform", "whatsapp")
            .eq("customer_id", str(customer_id))
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception:
        return []


def get_ai_reply(user_text, business, customer_id):
    api_key = business.get("mistral_api_key") or MISTRAL_API_KEY

    if not api_key:
        return "Xabaringiz qabul qilindi 😊"

    system_prompt = f"""
You are a real human WhatsApp sales manager.

Business info:
{build_business_context(business)}

Rules:
- Reply naturally and shortly.
- Usually 1-3 short sentences.
- Reply in the customer's language.
- Never invent prices, stock, delivery, discounts, or addresses.
- If information is missing, say the manager will clarify.
- Do not mention AI, bot, automation, database, or API.
- Focus on selling and continuing the conversation.
"""

    messages = [{"role": "system", "content": system_prompt}]

    for msg in get_recent_chat_history(customer_id):
        if msg.get("content"):
            messages.append({
                "role": msg.get("role") or "user",
                "content": msg.get("content"),
            })

    messages.append({"role": "user", "content": user_text})

    try:
        res = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": business.get("ai_model") or "mistral-small-latest",
                "messages": messages,
                "temperature": float(business.get("ai_temperature", 0.5) or 0.5),
                "max_tokens": int(business.get("ai_max_tokens", 130) or 130),
            },
            timeout=30,
        )

        log("WhatsApp Mistral response", {"status": res.status_code, "body": res.text})

        if not res.ok:
            return "Xabaringiz qabul qilindi 😊"

        reply = res.json()["choices"][0]["message"]["content"].strip()
        return reply[:1500] if reply else "Xabaringiz qabul qilindi 😊"

    except Exception as e:
        log("WhatsApp AI error", str(e))
        return "Xabaringiz qabul qilindi 😊"


def save_whatsapp_message(
    business,
    customer_id,
    text,
    direction,
    message_id="",
    raw_payload=None,
    customer_name="",
    media_type=None,
    media_url=None,
):
    data = {
        "business_id": business.get("id"),
        "instagram_business_id": business.get("instagram_business_id"),
        "platform": "whatsapp",
        "customer_id": str(customer_id),
        "customer_name": customer_name or str(customer_id),
        "chat_id": str(customer_id),
        "channel": "whatsapp_cloud",
        "direction": direction,
        "role": "user" if direction == "inbound" else "assistant",
        "content": text,
        "external_message_id": str(message_id),
        "raw_payload": raw_payload or {},
        "is_read": False if direction == "inbound" else True,
        "media_type": media_type,
        "media_url": media_url,
    }

    try:
        supabase.table("inbox_messages").insert(data).execute()
    except Exception:
        fallback = dict(data)
        fallback.pop("customer_name", None)
        fallback.pop("chat_id", None)
        fallback.pop("is_read", None)
        supabase.table("inbox_messages").insert(fallback).execute()

    log("WhatsApp message saved", data)


def send_whatsapp_text(to_phone, text):
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return False, {
            "error": "Missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID"
        }

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": str(to_phone),
        "type": "text",
        "text": {
            "preview_url": False,
            "body": text[:4096],
        },
    }

    res = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    try:
        result = res.json()
    except Exception:
        result = {"text": res.text}

    log("WhatsApp send result", {"status": res.status_code, "body": result})
    return res.ok, result


async def process_whatsapp_webhook(data: dict):
    try:
        log("WHATSAPP WEBHOOK RECEIVED", data)

        business = get_active_business()

        if not business:
            return JSONResponse({"status": "no_business"}, status_code=200)

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                contacts = value.get("contacts", [])
                messages = value.get("messages", [])

                for message in messages:
                    message_id = message.get("id", "")

                    if already_processed(message_id):
                        continue

                    from_phone = message.get("from", "")
                    customer_name = from_phone

                    if contacts:
                        customer_name = (
                            contacts[0]
                            .get("profile", {})
                            .get("name")
                            or from_phone
                        )

                    msg_type = message.get("type", "text")

                    text = ""
                    media_type = None
                    media_url = None

                    if msg_type == "text":
                        text = message.get("text", {}).get("body", "")

                    elif msg_type == "image":
                        text = message.get("image", {}).get("caption") or "📸 Photo"
                        media_type = "photo"

                    elif msg_type == "video":
                        text = message.get("video", {}).get("caption") or "🎥 Video"
                        media_type = "video"

                    elif msg_type == "audio":
                        text = "🎤 Voice message"
                        media_type = "voice"

                    elif msg_type == "document":
                        text = message.get("document", {}).get("caption") or "📎 Document"
                        media_type = "file"

                    elif msg_type == "button":
                        text = message.get("button", {}).get("text", "")

                    elif msg_type == "interactive":
                        interactive = message.get("interactive", {})
                        text = (
                            interactive.get("button_reply", {}).get("title")
                            or interactive.get("list_reply", {}).get("title")
                            or "Interactive reply"
                        )

                    else:
                        text = f"Unsupported WhatsApp message type: {msg_type}"

                    save_whatsapp_message(
                        business=business,
                        customer_id=from_phone,
                        text=text,
                        direction="inbound",
                        message_id=message_id,
                        raw_payload=message,
                        customer_name=customer_name,
                        media_type=media_type,
                        media_url=media_url,
                    )

                    if not business.get("bot_enabled", True):
                        continue

                    if not is_chat_ai_enabled(
                        "whatsapp",
                        "whatsapp_cloud",
                        from_phone,
                        business.get("id"),
                    ):
                        continue

                    reply = get_ai_reply(text, business, from_phone)

                    ok, result = send_whatsapp_text(from_phone, reply)

                    save_whatsapp_message(
                        business=business,
                        customer_id=from_phone,
                        text=reply,
                        direction="outbound",
                        message_id=(
                            result.get("messages", [{}])[0].get("id", "")
                            if isinstance(result, dict)
                            else ""
                        ),
                        raw_payload=result,
                        customer_name=customer_name,
                    )

        return JSONResponse({"status": "ok"}, status_code=200)

    except Exception as e:
        log("WhatsApp webhook error", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
