import os
import time
import asyncio
import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from supabase import create_client

try:
    from telethon import TelegramClient, events
    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
except Exception:
    TelegramClient = None
    events = None


telegram_router = APIRouter()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").lower().replace("@", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")

TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_USER_SESSION = os.getenv("TELEGRAM_USER_SESSION", "milana_user_session")
ENABLE_TELEGRAM_USER_CLIENT = os.getenv("ENABLE_TELEGRAM_USER_CLIENT", "false").lower() == "true"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

MESSAGE_BUFFER = {}
USER_MESSAGE_BUFFER = {}
PROCESSED_BOT_MESSAGES = {}
PROCESSED_USER_MESSAGES = {}
TELEGRAM_USER_CLIENT = None


def log(title, data=None):
    print("\n" + "=" * 80)
    print(title)
    if data is not None:
        print(data)
    print("=" * 80 + "\n")


def normalize_text(value):
    return str(value or "").strip()


def already_processed(cache, event_id, ttl=3600):
    if not event_id:
        return False

    now = time.time()
    expired = [k for k, v in cache.items() if now - v > ttl]

    for key in expired:
        cache.pop(key, None)

    if event_id in cache:
        return True

    cache[event_id] = now
    return False


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

        result = query.limit(1).execute()
        rows = result.data or []

        if not rows:
            return True

        return bool(rows[0].get("ai_enabled", True))
    except Exception as e:
        log("Could not check chat AI setting", str(e))
        return True


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
{business.get("business_name", "Milana Premium")}

Business type:
{business.get("business_type", "Textile and Clothing")}

Language:
{business.get("language", "uz")}

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


def get_recent_chat_history(customer_id: str, platform="telegram", channel=None, limit=10):
    try:
        query = (
            supabase.table("inbox_messages")
            .select("role,content,media_type,media_url")
            .eq("customer_id", str(customer_id))
            .eq("platform", platform)
        )

        if channel:
            query = query.eq("channel", channel)

        result = (
            query.order("created_at", desc=False)
            .limit(limit)
            .execute()
        )

        return result.data or []

    except Exception as e:
        log("Could not load Telegram history", str(e))
        return []


def get_ai_reply(user_text, business, customer_id, channel="telegram_bot_private"):
    api_key = business.get("mistral_api_key") or MISTRAL_API_KEY

    if not api_key:
        return "Assalomu alaykum 😊 Qanday yordam kerak?"

    history = get_recent_chat_history(
        customer_id=customer_id,
        platform="telegram",
        channel=channel,
    )

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
- Avoid markdown.
- Avoid bullet lists.
- Talk like a real Uzbek sales manager.
- You are representing Milana Premium textile and clothing.
- Do not mention AI, bot, automation, prompt, database, or API.

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
Milana Premiumga xush kelibsiz! Qanday yordam kerak?

GOOD EXAMPLE:
Customer: Katalog bormi?
Assistant:
Ha albatta 😊
Mana katalogimiz:
{business.get("catalog_link", "")}
"""

    messages = [{"role": "system", "content": system_prompt}]

    for msg in history:
        role = msg.get("role") or "user"
        content = msg.get("content") or ""
        if content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": business.get("ai_model") or "mistral-small-latest",
        "messages": messages,
        "temperature": float(business.get("ai_temperature", 0.5) or 0.5),
        "max_tokens": int(business.get("ai_max_tokens", 130) or 130),
    }

    try:
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
            return "Xabaringiz qabul qilindi 😊 Menejerimiz tez orada javob beradi."

        reply = (
            res.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        return reply[:1500] if reply else "Assalomu alaykum 😊 Qanday yordam kerak?"

    except Exception as e:
        log("Telegram AI error", str(e))
        return "Xabaringiz qabul qilindi 😊 Menejerimiz tez orada javob beradi."


def save_telegram_message(
    business,
    customer_id,
    text,
    direction,
    message_id="",
    raw_payload=None,
    channel="telegram_bot_private",
    customer_name="",
    chat_id="",
    media_type=None,
    media_url=None,
    media_file_id=None,
):
    try:
        data = {
            "business_id": business.get("id"),
            "instagram_business_id": business.get("instagram_business_id"),
            "platform": "telegram",
            "customer_id": str(customer_id),
            "customer_name": customer_name or str(customer_id),
            "chat_id": str(chat_id or customer_id),
            "channel": channel,
            "direction": direction,
            "role": "user" if direction == "inbound" else "assistant",
            "content": text,
            "external_message_id": str(message_id),
            "raw_payload": raw_payload or {},
            "is_read": False if direction == "inbound" else True,
            "media_type": media_type,
            "media_url": media_url,
            "media_file_id": media_file_id,
        }

        try:
            supabase.table("inbox_messages").insert(data).execute()
        except Exception:
            fallback = dict(data)
            fallback.pop("customer_name", None)
            fallback.pop("chat_id", None)
            fallback.pop("is_read", None)
            supabase.table("inbox_messages").insert(fallback).execute()

        log("Telegram inbox message saved", data)

    except Exception as e:
        log("Could not save Telegram message", str(e))


def send_telegram_bot_message(chat_id, text, reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
        log("Missing TELEGRAM_BOT_TOKEN")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    res = requests.post(url, json=payload, timeout=30)

    log("Telegram bot send result", {"status": res.status_code, "body": res.text})

    return res


def send_telegram_photo(chat_id, photo_file_id, caption="", reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    payload = {
        "chat_id": chat_id,
        "photo": photo_file_id,
    }

    if caption:
        payload["caption"] = caption[:1024]

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    res = requests.post(url, json=payload, timeout=30)
    log("Telegram photo send result", {"status": res.status_code})
    return res


def send_telegram_video(chat_id, video_file_id, caption="", reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"

    payload = {
        "chat_id": chat_id,
        "video": video_file_id,
    }

    if caption:
        payload["caption"] = caption[:1024]

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    res = requests.post(url, json=payload, timeout=30)
    log("Telegram video send result", {"status": res.status_code})
    return res


def send_telegram_voice(chat_id, voice_file_id, reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVoice"

    payload = {
        "chat_id": chat_id,
        "voice": voice_file_id,
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    res = requests.post(url, json=payload, timeout=30)
    log("Telegram voice send result", {"status": res.status_code})
    return res


def get_file_url(file_id):
    if not TELEGRAM_BOT_TOKEN:
        return None

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
        res = requests.get(
            url,
            params={"file_id": file_id},
            timeout=30,
        )

        if res.ok:
            file_info = res.json().get("result", {})
            file_path = file_info.get("file_path")
            if file_path:
                return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

    except Exception as e:
        log("Could not get Telegram file URL", str(e))

    return None


def build_customer_name(user):
    first_name = normalize_text(user.get("first_name"))
    last_name = normalize_text(user.get("last_name"))
    username = normalize_text(user.get("username"))

    full_name = f"{first_name} {last_name}".strip()

    if username:
        return f"{full_name} (@{username})".strip()

    return full_name or str(user.get("id", ""))


def buffer_message(buffer_store, buffer_key, text):
    current_time = time.time()

    if buffer_key not in buffer_store:
        buffer_store[buffer_key] = {
            "texts": [],
            "last_time": current_time,
        }

    buffer_store[buffer_key]["texts"].append(text)
    buffer_store[buffer_key]["last_time"] = current_time


def pop_buffer_if_ready(buffer_store, buffer_key, wait_seconds=2):
    time.sleep(wait_seconds + 1)

    if buffer_key not in buffer_store:
        return None

    latest_time = buffer_store[buffer_key]["last_time"]

    if time.time() - latest_time < wait_seconds:
        return None

    combined_text = "\n".join(buffer_store[buffer_key]["texts"]).strip()

    del buffer_store[buffer_key]

    return combined_text


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

        log("TELEGRAM BOT WEBHOOK RECEIVED", update)

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

        chat = message.get("chat", {})
        user = message.get("from", {})

        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        customer_id = user.get("id")
        message_id = message.get("message_id")

        event_id = f"bot:{chat_id}:{customer_id}:{message_id}"

        if already_processed(PROCESSED_BOT_MESSAGES, event_id):
            return JSONResponse({"status": "duplicate"})

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

            if mention not in (message.get("text") or "").lower() and not replied_to_bot:
                return JSONResponse({"status": "ignored_group_message"})

        if chat_type in ["group", "supergroup"]:
            channel = "telegram_bot_group"
        else:
            channel = "telegram_bot_private"

        customer_name = build_customer_name(user)

        # Handle text messages
        text = normalize_text(message.get("text"))
        media_type = None
        media_url = None
        media_file_id = None
        
        if text:
            buffer_key = f"bot:{chat_id}:{customer_id}"
            buffer_message(MESSAGE_BUFFER, buffer_key, text)

            combined_text = pop_buffer_if_ready(MESSAGE_BUFFER, buffer_key, wait_seconds=2)

            if not combined_text:
                return JSONResponse({"status": "waiting_more_messages"})

            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=combined_text,
                direction="inbound",
                message_id=message_id,
                raw_payload=update,
                channel=channel,
                customer_name=customer_name,
                chat_id=chat_id,
            )

            if not is_chat_ai_enabled("telegram", channel, customer_id, business.get("id")):
                return JSONResponse({"status": "ai_disabled"})

            reply = get_ai_reply(
                user_text=combined_text,
                business=business,
                customer_id=customer_id,
                channel=channel,
            )

            send_telegram_bot_message(
                chat_id=chat_id,
                text=reply,
                reply_to_message_id=message_id if chat_type in ["group", "supergroup"] else None,
            )

            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=reply,
                direction="outbound",
                message_id="",
                raw_payload={},
                channel=channel,
                customer_name=customer_name,
                chat_id=chat_id,
            )

        # Handle photos
        elif message.get("photo"):
            photos = message.get("photo", [])
            largest_photo = photos[-1] if photos else {}
            file_id = largest_photo.get("file_id")
            caption = normalize_text(message.get("caption") or "📸 Photo")
            
            media_type = "photo"
            media_file_id = file_id
            media_url = get_file_url(file_id)

            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=caption,
                direction="inbound",
                message_id=message_id,
                raw_payload=update,
                channel=channel,
                customer_name=customer_name,
                chat_id=chat_id,
                media_type=media_type,
                media_url=media_url,
                media_file_id=media_file_id,
            )
            
            log("Telegram photo saved", {"file_id": file_id, "url": media_url})

        # Handle videos
        elif message.get("video"):
            video = message.get("video", {})
            file_id = video.get("file_id")
            caption = normalize_text(message.get("caption") or "🎥 Video")
            
            media_type = "video"
            media_file_id = file_id
            media_url = get_file_url(file_id)

            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=caption,
                direction="inbound",
                message_id=message_id,
                raw_payload=update,
                channel=channel,
                customer_name=customer_name,
                chat_id=chat_id,
                media_type=media_type,
                media_url=media_url,
                media_file_id=media_file_id,
            )
            
            log("Telegram video saved", {"file_id": file_id, "url": media_url})

        # Handle voice messages
        elif message.get("voice"):
            voice = message.get("voice", {})
            file_id = voice.get("file_id")
            duration = voice.get("duration", 0)
            
            media_type = "voice"
            media_file_id = file_id
            media_url = get_file_url(file_id)

            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=f"🎤 Voice message ({duration}s)",
                direction="inbound",
                message_id=message_id,
                raw_payload=update,
                channel=channel,
                customer_name=customer_name,
                chat_id=chat_id,
                media_type=media_type,
                media_url=media_url,
                media_file_id=media_file_id,
            )
            
            log("Telegram voice saved", {"file_id": file_id, "url": media_url})

        else:
            return JSONResponse({"status": "ignored_no_text_or_media"})

        return JSONResponse({"status": "ok"})

    except Exception as e:
        log("Telegram bot webhook error", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def process_telegram_user_event(event):
    try:
        if event.out:
            return

        if not event.is_private:
            return

        text = normalize_text(event.raw_text)
        sender = await event.get_sender()
        sender_id = str(sender.id)
        chat_id = str(event.chat_id)
        message_id = str(event.id)

        event_id = f"user:{chat_id}:{sender_id}:{message_id}"

        if already_processed(PROCESSED_USER_MESSAGES, event_id):
            return

        business = get_active_business()

        if not business:
            log("No active business for Telegram private user account")
            return

        customer_name_parts = []

        if getattr(sender, "first_name", None):
            customer_name_parts.append(sender.first_name)

        if getattr(sender, "last_name", None):
            customer_name_parts.append(sender.last_name)

        customer_name = " ".join(customer_name_parts).strip()

        if getattr(sender, "username", None):
            customer_name = f"{customer_name} (@{sender.username})".strip()

        customer_name = customer_name or sender_id

        # Handle text
        if text:
            buffer_key = f"user:{chat_id}:{sender_id}"
            buffer_message(USER_MESSAGE_BUFFER, buffer_key, text)

            await asyncio.sleep(3)

            if buffer_key not in USER_MESSAGE_BUFFER:
                return

            latest_time = USER_MESSAGE_BUFFER[buffer_key]["last_time"]

            if time.time() - latest_time < 2:
                return

            combined_text = "\n".join(USER_MESSAGE_BUFFER[buffer_key]["texts"]).strip()

            del USER_MESSAGE_BUFFER[buffer_key]

            save_telegram_message(
                business=business,
                customer_id=sender_id,
                text=combined_text,
                direction="inbound",
                message_id=message_id,
                raw_payload={
                    "chat_id": chat_id,
                    "sender_id": sender_id,
                    "message_id": message_id,
                    "source": "telethon_user_account",
                },
                channel="telegram_user_private",
                customer_name=customer_name,
                chat_id=chat_id,
            )

            if not is_chat_ai_enabled("telegram", "telegram_user_private", sender_id, business.get("id")):
                return

            reply = get_ai_reply(
                user_text=combined_text,
                business=business,
                customer_id=sender_id,
                channel="telegram_user_private",
            )

            sent = await event.respond(reply)

            save_telegram_message(
                business=business,
                customer_id=sender_id,
                text=reply,
                direction="outbound",
                message_id=getattr(sent, "id", ""),
                raw_payload={
                    "chat_id": chat_id,
                    "source": "telethon_user_account",
                },
                channel="telegram_user_private",
                customer_name=customer_name,
                chat_id=chat_id,
            )

        # Handle media
        elif event.media:
            media_type = None
            file_id = None
            caption = "📎 Media sent"

            if hasattr(event.media, "photo"):
                media_type = "photo"
                caption = "📸 Photo"
            elif hasattr(event.media, "document"):
                doc = event.media.document
                if hasattr(doc, "mime_type"):
                    if "video" in doc.mime_type:
                        media_type = "video"
                        caption = "🎥 Video"
                    elif "audio" in doc.mime_type:
                        media_type = "voice"
                        caption = "🎤 Voice"

            if media_type:
                save_telegram_message(
                    business=business,
                    customer_id=sender_id,
                    text=caption,
                    direction="inbound",
                    message_id=message_id,
                    raw_payload={
                        "chat_id": chat_id,
                        "source": "telethon_user_account",
                    },
                    channel="telegram_user_private",
                    customer_name=customer_name,
                    chat_id=chat_id,
                    media_type=media_type,
                )

    except Exception as e:
        log("Telegram user account event error", str(e))


async def send_telegram_user_message(customer_id, text):
    global TELEGRAM_USER_CLIENT

    if not TELEGRAM_USER_CLIENT:
        return False, {"error": "Telegram private user client is not running"}

    try:
        entity = await TELEGRAM_USER_CLIENT.get_entity(int(customer_id))
        sent = await TELEGRAM_USER_CLIENT.send_message(entity, text)

        sender_name = str(customer_id)

        try:
            if hasattr(entity, "first_name") or hasattr(entity, "last_name"):
                sender_name = f"{getattr(entity, 'first_name', '')} {getattr(entity, 'last_name', '')}".strip()
                if getattr(entity, "username", None):
                    sender_name = f"{sender_name} (@{entity.username})".strip()
        except Exception:
            pass

        return True, {
            "message_id": getattr(sent, "id", ""),
            "customer_id": str(customer_id),
            "chat_id": str(customer_id),
            "customer_name": sender_name or str(customer_id),
        }

    except Exception as e:
        return False, {"error": str(e)}


async def start_telegram_user_client():
    global TELEGRAM_USER_CLIENT

    if not ENABLE_TELEGRAM_USER_CLIENT:
        log("Telegram private user client disabled")
        return None

    if TelegramClient is None or events is None:
        log("Telethon is not installed. Run: pip install telethon")
        return None

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        log("Missing TELEGRAM_API_ID or TELEGRAM_API_HASH")
        return None

    if TELEGRAM_USER_CLIENT:
        return TELEGRAM_USER_CLIENT

    TELEGRAM_USER_CLIENT = TelegramClient(
        TELEGRAM_USER_SESSION,
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )

    @TELEGRAM_USER_CLIENT.on(events.NewMessage(incoming=True))
    async def private_user_message_handler(event):
        await process_telegram_user_event(event)

    try:
        await TELEGRAM_USER_CLIENT.connect()

        if not await TELEGRAM_USER_CLIENT.is_user_authorized():
            log(
                "Telegram private user session is not authorized. "
                "Create milana_user_session.session locally first, then deploy it."
            )
            await TELEGRAM_USER_CLIENT.disconnect()
            TELEGRAM_USER_CLIENT = None
            return None

        me = await TELEGRAM_USER_CLIENT.get_me()

        log("Telegram private user client started", {
            "id": getattr(me, "id", None),
            "username": getattr(me, "username", None),
            "phone": "***hidden***",
        })

        return TELEGRAM_USER_CLIENT

    except Exception as e:
        log("Telegram private user client startup error", str(e))
        try:
            await TELEGRAM_USER_CLIENT.disconnect()
        except Exception:
            pass
        TELEGRAM_USER_CLIENT = None
        return None


async def stop_telegram_user_client():
    global TELEGRAM_USER_CLIENT

    if TELEGRAM_USER_CLIENT:
        await TELEGRAM_USER_CLIENT.disconnect()
        TELEGRAM_USER_CLIENT = None
        log("Telegram private user client stopped")


def start_telegram_user_client_background():
    try:
        loop = asyncio.get_event_loop()

        if loop.is_running():
            loop.create_task(start_telegram_user_client())
        else:
            loop.run_until_complete(start_telegram_user_client())

    except RuntimeError:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(start_telegram_user_client())
