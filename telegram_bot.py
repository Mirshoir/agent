import os
import io
import time
import asyncio
import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from supabase import create_client

try:
    from telethon import TelegramClient, events
    from telethon.tl.types import (
        MessageMediaPhoto,
        MessageMediaDocument,
        DocumentAttributeAudio,
        DocumentAttributeVideo,
        DocumentAttributeFilename,
    )
except Exception:
    TelegramClient = None
    events = None
    MessageMediaPhoto = None
    MessageMediaDocument = None
    DocumentAttributeAudio = None
    DocumentAttributeVideo = None
    DocumentAttributeFilename = None


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


# ── Utils ──────────────────────────────────────────────────────────────────────

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
Business name: {business.get("business_name", "Milana Premium")}
Business type: {business.get("business_type", "Textile and Clothing")}
Language: {business.get("language", "uz")}
Products: {business.get("products", "")}
Prices: {business.get("prices", "")}
Delivery: {business.get("delivery_info", "")}
FAQ: {business.get("faq", "")}
Catalog: {business.get("catalog_link", "")}
Phone: {business.get("sales_phone", "")}
Knowledge: {business.get("knowledge", "")}
"""


def get_recent_chat_history(customer_id: str, platform="telegram", channel=None, limit=10):
    try:
        query = (
            supabase.table("inbox_messages")
            .select("role,content")
            .eq("customer_id", str(customer_id))
            .eq("platform", platform)
        )
        if channel:
            query = query.eq("channel", channel)
        result = query.order("created_at", desc=False).limit(limit).execute()
        return result.data or []
    except Exception as e:
        log("Could not load Telegram history", str(e))
        return []


def get_ai_reply(user_text, business, customer_id, channel="telegram_bot_private", media_type=""):
    api_key = business.get("mistral_api_key") or MISTRAL_API_KEY
    if not api_key:
        return "Assalomu alaykum 😊 Qanday yordam kerak?"

    history = get_recent_chat_history(customer_id=customer_id, platform="telegram", channel=channel)

    effective_text = user_text
    if media_type and not user_text:
        media_labels = {
            "photo": "mijoz rasm yubordi",
            "video": "mijoz video yubordi",
            "voice": "mijoz ovozli xabar yubordi",
            "audio": "mijoz audio fayl yubordi",
            "document": "mijoz hujjat yubordi",
            "sticker": "mijoz sticker yubordi",
            "animation": "mijoz gif/animation yubordi",
        }
        effective_text = media_labels.get(media_type, f"mijoz {media_type} yubordi")
    elif media_type and user_text:
        effective_text = f"[{media_type}] {user_text}"

    system_prompt = f"""
You are a real human sales manager for Milana Premium.

Business info:
{build_business_context(business)}

BEHAVIOR RULES:
- Speak naturally like a real Telegram sales manager.
- Keep answers short and comfortable (1-3 sentences usually).
- Never dump all business information at once.
- Never overwhelm the customer.
- Ask follow-up questions naturally.
- Sound warm, confident, and human.
- Use emojis lightly.
- Reply in the customer's language.
- Avoid AI-style formatting, markdown, and bullet lists.
- Do not mention AI, bot, automation, prompt, or database.
- If customer sends a photo/video/voice, acknowledge it naturally before asking what they need.

CATALOG RULE:
- Do NOT offer catalog automatically in greeting.
- Send catalog ONLY if customer explicitly asks for catalog, models, prices, collection, or photos.
- If customer only greets, greet back and ask what they need.
"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = msg.get("role") or "user"
        content = msg.get("content") or ""
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": effective_text})

    try:
        res = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": business.get("ai_model") or "mistral-small-latest",
                "messages": messages,
                "temperature": float(business.get("ai_temperature", 0.5) or 0.5),
                "max_tokens": int(business.get("ai_max_tokens", 130) or 130),
            },
            timeout=30,
        )
        log("Telegram Mistral response", {"status": res.status_code})
        if not res.ok:
            return "Xabaringiz qabul qilindi 😊 Menejerimiz tez orada javob beradi."
        reply = res.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return reply[:1500] if reply else "Assalomu alaykum 😊 Qanday yordam kerak?"
    except Exception as e:
        log("Telegram AI error", str(e))
        return "Xabaringiz qabul qilindi 😊 Menejerimiz tez orada javob beradi."


def save_telegram_message(
    business, customer_id, text, direction,
    message_id="", raw_payload=None, channel="telegram_bot_private",
    customer_name="", chat_id="", media_type="", media_url="",
):
    try:
        content = text
        if media_type and media_url:
            prefix = f"[{media_type.upper()}] {media_url}"
            content = f"{prefix}\n{text}" if text else prefix
        elif media_type and not media_url:
            content = f"[{media_type.upper()} received]\n{text}" if text else f"[{media_type.upper()} received]"

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
            "content": content,
            "media_type": media_type or "",
            "media_url": media_url or "",
            "external_message_id": str(message_id),
            "raw_payload": raw_payload or {},
            "is_read": False if direction == "inbound" else True,
        }

        try:
            supabase.table("inbox_messages").insert(data).execute()
        except Exception:
            fallback = dict(data)
            for k in ["customer_name", "chat_id", "is_read", "media_type", "media_url"]:
                fallback.pop(k, None)
            supabase.table("inbox_messages").insert(fallback).execute()

        log("Telegram message saved", {k: v for k, v in data.items() if k not in ["raw_payload", "content"]})

    except Exception as e:
        log("Could not save Telegram message", str(e))


# ── Telegram Bot API helpers ───────────────────────────────────────────────────

def send_telegram_bot_message(chat_id, text, reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
        log("Missing TELEGRAM_BOT_TOKEN")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": False}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    res = requests.post(url, json=payload, timeout=30)
    log("Telegram bot send result", {"status": res.status_code})
    return res


def get_telegram_file_url(file_id: str) -> str:
    """Resolve a Telegram file_id to a direct download URL."""
    if not TELEGRAM_BOT_TOKEN or not file_id:
        return ""
    try:
        res = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=15,
        )
        if res.ok:
            data = res.json()
            file_path = data.get("result", {}).get("file_path", "")
            if file_path:
                return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    except Exception as e:
        log("Could not get Telegram file URL", str(e))
    return ""


def upload_media_to_storage(file_bytes: bytes, path: str, content_type: str = "application/octet-stream") -> str:
    """Upload file bytes to Supabase Storage and return public URL."""
    try:
        supabase.storage.from_("media").upload(
            path=path,
            file=file_bytes,
            file_options={"content-type": content_type},
        )
        return supabase.storage.from_("media").get_public_url(path)
    except Exception as e:
        log("Storage upload failed", str(e))
    return ""


def download_telegram_file(file_url: str) -> bytes:
    """Download a Telegram file given its full URL."""
    try:
        res = requests.get(file_url, timeout=30)
        if res.ok:
            return res.content
    except Exception as e:
        log("Could not download Telegram file", str(e))
    return b""


def detect_bot_message_media(message: dict) -> tuple[str, str, str]:
    """
    Returns (media_type, file_id, file_name) from a Telegram bot message dict.
    media_type: 'photo', 'video', 'voice', 'audio', 'document', 'sticker', 'animation', or ''
    """
    if "photo" in message and message["photo"]:
        # Photo is array; take largest
        largest = max(message["photo"], key=lambda p: p.get("file_size", 0))
        return "photo", largest.get("file_id", ""), "photo.jpg"

    if "video" in message:
        v = message["video"]
        return "video", v.get("file_id", ""), v.get("file_name", "video.mp4")

    if "voice" in message:
        v = message["voice"]
        return "voice", v.get("file_id", ""), "voice.ogg"

    if "audio" in message:
        a = message["audio"]
        fname = a.get("file_name") or a.get("title") or "audio.mp3"
        return "audio", a.get("file_id", ""), fname

    if "document" in message:
        d = message["document"]
        mime = (d.get("mime_type") or "").lower()
        if "image" in mime:
            mt = "photo"
        elif "video" in mime:
            mt = "video"
        elif "audio" in mime or "ogg" in mime:
            mt = "voice"
        else:
            mt = "document"
        return mt, d.get("file_id", ""), d.get("file_name", "document")

    if "sticker" in message:
        s = message["sticker"]
        return "sticker", s.get("file_id", ""), "sticker.webp"

    if "animation" in message:
        a = message["animation"]
        return "animation", a.get("file_id", ""), a.get("file_name", "animation.gif")

    return "", "", ""


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
        buffer_store[buffer_key] = {"texts": [], "last_time": current_time}
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


# ── Bot Webhook ────────────────────────────────────────────────────────────────

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

        text = normalize_text(message.get("text") or message.get("caption") or "")
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
            replied_to_bot = message.get("reply_to_message", {}).get("from", {}).get("is_bot", False)
            if mention not in text.lower() and not replied_to_bot:
                return JSONResponse({"status": "ignored_group_message"})

        channel = "telegram_bot_group" if chat_type in ["group", "supergroup"] else "telegram_bot_private"
        customer_name = build_customer_name(user)

        # Detect media
        media_type, file_id, file_name = detect_bot_message_media(message)
        media_url = ""

        # Resolve file_id -> public URL via Supabase Storage
        if file_id:
            try:
                tg_file_url = get_telegram_file_url(file_id)
                if tg_file_url:
                    file_bytes = download_telegram_file(tg_file_url)
                    if file_bytes:
                        storage_path = f"telegram/{customer_id}/{message_id}_{file_name}"
                        content_type_map = {
                            "photo": "image/jpeg",
                            "video": "video/mp4",
                            "voice": "audio/ogg",
                            "audio": "audio/mpeg",
                            "document": "application/octet-stream",
                            "sticker": "image/webp",
                            "animation": "image/gif",
                        }
                        ct = content_type_map.get(media_type, "application/octet-stream")
                        media_url = upload_media_to_storage(file_bytes, storage_path, ct)
            except Exception as media_err:
                log("Media processing error", str(media_err))
                media_url = ""

        # Buffer text messages; media goes straight through
        if not file_id:
            buffer_key = f"bot:{chat_id}:{customer_id}"
            buffer_message(MESSAGE_BUFFER, buffer_key, text or "[message]")
            combined_text = pop_buffer_if_ready(MESSAGE_BUFFER, buffer_key, wait_seconds=2)
            if not combined_text:
                return JSONResponse({"status": "waiting_more_messages"})
            effective_text = combined_text
        else:
            effective_text = text  # caption or empty

        save_telegram_message(
            business=business, customer_id=customer_id,
            text=effective_text, direction="inbound",
            message_id=message_id, raw_payload=update, channel=channel,
            customer_name=customer_name, chat_id=chat_id,
            media_type=media_type, media_url=media_url,
        )

        if not is_chat_ai_enabled("telegram", channel, customer_id, business.get("id")):
            log("AI disabled for this Telegram chat", {"customer_id": customer_id})
            return JSONResponse({"status": "ai_disabled"})

        reply = get_ai_reply(
            user_text=effective_text,
            business=business,
            customer_id=customer_id,
            channel=channel,
            media_type=media_type,
        )

        send_telegram_bot_message(
            chat_id=chat_id,
            text=reply,
            reply_to_message_id=message_id if chat_type in ["group", "supergroup"] else None,
        )

        save_telegram_message(
            business=business, customer_id=customer_id,
            text=reply, direction="outbound",
            message_id="", raw_payload={}, channel=channel,
            customer_name=customer_name, chat_id=chat_id,
        )

        return JSONResponse({"status": "ok"})

    except Exception as e:
        log("Telegram bot webhook error", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ── Telethon Private User Client ───────────────────────────────────────────────

def telethon_detect_media_type(event) -> tuple[str, str]:
    """
    Returns (media_type, file_name) from a Telethon NewMessage event.
    """
    if not hasattr(event, "media") or not event.media:
        return "", ""

    media = event.media

    if MessageMediaPhoto and isinstance(media, MessageMediaPhoto):
        return "photo", "photo.jpg"

    if MessageMediaDocument and isinstance(media, MessageMediaDocument):
        doc = media.document
        attrs = doc.attributes if doc else []

        has_voice = any(
            isinstance(a, DocumentAttributeAudio) and getattr(a, "voice", False)
            for a in attrs
        )
        has_audio = any(isinstance(a, DocumentAttributeAudio) for a in attrs)
        has_video = any(isinstance(a, DocumentAttributeVideo) for a in attrs)

        fname_attr = next((a for a in attrs if isinstance(a, DocumentAttributeFilename)), None)
        file_name = fname_attr.file_name if fname_attr else "document"

        if has_voice:
            return "voice", file_name or "voice.ogg"
        if has_audio:
            return "audio", file_name or "audio.mp3"
        if has_video:
            return "video", file_name or "video.mp4"

        mime = getattr(doc, "mime_type", "") or ""
        if "image" in mime:
            return "photo", file_name
        if "video" in mime:
            return "video", file_name
        if "audio" in mime or "ogg" in mime:
            return "voice", file_name

        return "document", file_name

    return "", ""


async def process_telegram_user_event(event):
    try:
        if event.out:
            return
        if not event.is_private:
            return

        text = normalize_text(event.raw_text or event.message.message or "")
        sender = await event.get_sender()
        sender_id = str(sender.id)
        chat_id = str(event.chat_id)
        message_id = str(event.id)

        event_id = f"user:{chat_id}:{sender_id}:{message_id}"
        if already_processed(PROCESSED_USER_MESSAGES, event_id):
            return

        business = get_active_business()
        if not business:
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

        # Detect and download media
        media_type, file_name = telethon_detect_media_type(event)
        media_url = ""

        if media_type and event.media:
            try:
                buf = io.BytesIO()
                await TELEGRAM_USER_CLIENT.download_media(event.media, file=buf)
                file_bytes = buf.getvalue()
                if file_bytes:
                    storage_path = f"telegram_user/{sender_id}/{message_id}_{file_name or 'media'}"
                    content_type_map = {
                        "photo": "image/jpeg",
                        "video": "video/mp4",
                        "voice": "audio/ogg",
                        "audio": "audio/mpeg",
                        "document": "application/octet-stream",
                    }
                    ct = content_type_map.get(media_type, "application/octet-stream")
                    media_url = upload_media_to_storage(file_bytes, storage_path, ct)
            except Exception as media_err:
                log("Telethon media download error", str(media_err))

        # Buffer text-only messages
        if not media_type:
            buffer_key = f"user:{chat_id}:{sender_id}"
            buffer_message(USER_MESSAGE_BUFFER, buffer_key, text or "[message]")
            await asyncio.sleep(3)
            if buffer_key not in USER_MESSAGE_BUFFER:
                return
            latest_time = USER_MESSAGE_BUFFER[buffer_key]["last_time"]
            if time.time() - latest_time < 2:
                return
            combined_text = "\n".join(USER_MESSAGE_BUFFER[buffer_key]["texts"]).strip()
            del USER_MESSAGE_BUFFER[buffer_key]
            effective_text = combined_text
        else:
            effective_text = text

        save_telegram_message(
            business=business, customer_id=sender_id,
            text=effective_text, direction="inbound",
            message_id=message_id,
            raw_payload={"chat_id": chat_id, "sender_id": sender_id, "source": "telethon"},
            channel="telegram_user_private", customer_name=customer_name,
            chat_id=chat_id, media_type=media_type, media_url=media_url,
        )

        if not is_chat_ai_enabled("telegram", "telegram_user_private", sender_id, business.get("id")):
            log("AI disabled for private user chat", {"customer_id": sender_id})
            return

        reply = get_ai_reply(
            user_text=effective_text, business=business,
            customer_id=sender_id, channel="telegram_user_private",
            media_type=media_type,
        )

        sent = await event.respond(reply)

        save_telegram_message(
            business=business, customer_id=sender_id,
            text=reply, direction="outbound",
            message_id=getattr(sent, "id", ""),
            raw_payload={"chat_id": chat_id, "source": "telethon"},
            channel="telegram_user_private", customer_name=customer_name,
            chat_id=chat_id,
        )

    except Exception as e:
        log("Telegram user account event error", str(e))


# ── Telethon send helpers ──────────────────────────────────────────────────────

async def send_telegram_user_message(customer_id, text):
    global TELEGRAM_USER_CLIENT
    if not TELEGRAM_USER_CLIENT:
        return False, {"error": "Telegram private user client is not running"}
    try:
        entity = await TELEGRAM_USER_CLIENT.get_entity(int(customer_id))
        sent = await TELEGRAM_USER_CLIENT.send_message(entity, text)
        sender_name = str(customer_id)
        try:
            parts = [getattr(entity, "first_name", ""), getattr(entity, "last_name", "")]
            sender_name = " ".join(p for p in parts if p).strip()
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


async def send_telegram_user_media(customer_id, file_bytes: bytes, file_name: str = "media",
                                    caption: str = None, media_type: str = "document"):
    """
    Send a media file (photo, video, voice, audio, document) via Telethon to a user.
    """
    global TELEGRAM_USER_CLIENT
    if not TELEGRAM_USER_CLIENT:
        return False, {"error": "Telegram private user client is not running"}
    try:
        entity = await TELEGRAM_USER_CLIENT.get_entity(int(customer_id))
        buf = io.BytesIO(file_bytes)
        buf.name = file_name  # Telethon uses .name to detect file type

        # Force voice note attribute for voice messages
        attributes = []
        if media_type == "voice":
            try:
                from telethon.tl.types import DocumentAttributeAudio as DAAudio
                attributes = [DAAudio(duration=0, voice=True)]
            except Exception:
                pass

        sent = await TELEGRAM_USER_CLIENT.send_file(
            entity,
            file=buf,
            caption=caption,
            attributes=attributes if attributes else None,
        )
        return True, {
            "message_id": getattr(sent, "id", ""),
            "customer_id": str(customer_id),
            "chat_id": str(customer_id),
        }
    except Exception as e:
        return False, {"error": str(e)}


# ── Telethon lifecycle ─────────────────────────────────────────────────────────

async def start_telegram_user_client():
    global TELEGRAM_USER_CLIENT

    if not ENABLE_TELEGRAM_USER_CLIENT:
        log("Telegram private user client disabled")
        return None

    if TelegramClient is None:
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
            log("Telegram private user session not authorized. Create session file locally first.")
            await TELEGRAM_USER_CLIENT.disconnect()
            TELEGRAM_USER_CLIENT = None
            return None

        me = await TELEGRAM_USER_CLIENT.get_me()
        log("Telegram private user client started", {
            "id": getattr(me, "id", None),
            "username": getattr(me, "username", None),
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
