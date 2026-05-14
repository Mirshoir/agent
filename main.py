import os
import re
import time
import secrets
import base64
import tempfile
import asyncio
import requests
from urllib.parse import urlencode
from typing import Optional

from pydantic import BaseModel
from fastapi import FastAPI, Request, Header, File, UploadFile
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

from telegram_bot import (
    telegram_router,
    start_telegram_user_client,
    stop_telegram_user_client,
    send_telegram_user_message,
    send_telegram_photo,
    send_telegram_video,
    send_telegram_voice,
    send_telegram_bot_message,
    save_telegram_message,
    get_active_business,
)

app = FastAPI()

# ----------------------------------------------------------------------
# CORS – allow the frontend (GitHub Pages / Vercel / Netlify) to call us
# ----------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # or your exact frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telegram_router)


@app.on_event("startup")
async def startup_telegram_user_client():
    await start_telegram_user_client()


@app.on_event("shutdown")
async def shutdown_telegram_user_client():
    await stop_telegram_user_client()


# ----------------------------------------------------------------------
# Environment & Constants
# ----------------------------------------------------------------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")
GRAPH_FACEBOOK = f"https://graph.facebook.com/{GRAPH_VERSION}"
GRAPH_INSTAGRAM = f"https://graph.instagram.com/{GRAPH_VERSION}"

INSTAGRAM_REDIRECT_URI = os.getenv(
    "INSTAGRAM_REDIRECT_URI",
    "https://agent-1-xi6h.onrender.com/auth/instagram/callback",
)

FACEBOOK_REDIRECT_URI = os.getenv(
    "FACEBOOK_REDIRECT_URI",
    "https://agent-1-xi6h.onrender.com/auth/facebook/callback",
)

DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL",
    "https://instaagent.streamlit.app",
)

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "https://agent-1-xi6h.onrender.com",
)

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_message_ids = {}
processed_comment_ids = {}
DEDUP_TTL_SECONDS = 60 * 60


# ----------------------------------------------------------------------
# Pydantic models for JSON body endpoints
# ----------------------------------------------------------------------
class ManualInstagramReply(BaseModel):
    business_id: str
    customer_id: str
    text: str


class ManualInstagramMedia(BaseModel):
    business_id: str
    customer_id: str
    caption: str = ""
    media_type: str
    media_url: str


class ManualTelegramMessage(BaseModel):
    customer_id: str
    text: str


class ManualTelegramFile(BaseModel):
    customer_id: str
    chat_id: str
    caption: str = ""
    media_type: str
    file_data: str      # base64
    filename: str


class ManualTelegramVoiceFile(BaseModel):
    customer_id: str
    chat_id: str
    file_data: str      # base64
    filename: str


class ManualInstagramFile(BaseModel):
    business_id: str
    customer_id: str
    caption: str = ""
    media_type: str
    file_data: str      # base64
    filename: str


class BusinessSettingsUpdate(BaseModel):
    business_id: str
    settings: dict


# ----------------------------------------------------------------------
# Helpers (log, normalize, dedup, etc.)
# ----------------------------------------------------------------------
def log(title, data=None):
    print("\n" + "=" * 80)
    print(title)
    if data is not None:
        print(data)
    print("=" * 80 + "\n")


def normalize_id(value) -> str:
    return str(value or "").strip()


def safe_token(token: str) -> str:
    if not token:
        return ""
    token = str(token)
    if len(token) <= 18:
        return token[:4] + "..."
    return token[:10] + "..." + token[-6:]


def cleanup_dedup_cache():
    now = time.time()
    for cache in (processed_message_ids, processed_comment_ids):
        expired = [k for k, v in cache.items() if now - v > DEDUP_TTL_SECONDS]
        for key in expired:
            cache.pop(key, None)


def already_processed(cache: dict, event_id: str) -> bool:
    if not event_id:
        return False
    cleanup_dedup_cache()
    if event_id in cache:
        return True
    cache[event_id] = time.time()
    return False


# ----------------------------------------------------------------------
# Database helpers
# ----------------------------------------------------------------------
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


def set_chat_ai_enabled(business_id, platform, channel, customer_id, enabled):
    data = {
        "business_id": business_id,
        "platform": platform,
        "channel": channel or "",
        "customer_id": str(customer_id),
        "ai_enabled": bool(enabled),
        "updated_at": "now()",
    }
    try:
        return supabase.table("chat_ai_settings").upsert(data, on_conflict="business_id,platform,channel,customer_id").execute()
    except Exception:
        data.pop("updated_at", None)
        return supabase.table("chat_ai_settings").upsert(data, on_conflict="business_id,platform,channel,customer_id").execute()


def get_all_businesses():
    result = supabase.table("businesses").select("*").order("created_at", desc=True).execute()
    return result.data or []


def get_message_count(platform=None):
    try:
        q = supabase.table("inbox_messages").select("id", count="exact")
        if platform:
            q = q.eq("platform", platform)
        result = q.execute()
        return result.count or 0
    except Exception:
        return 0


def update_business(business_id, data):
    return supabase.table("businesses").update(data).eq("id", business_id).execute()


def sanitize_business_row(row: dict):
    if not row:
        return None
    clean = dict(row)
    clean["access_token"] = safe_token(clean.get("access_token", ""))
    clean["page_access_token"] = safe_token(clean.get("page_access_token", ""))
    clean["mistral_api_key"] = safe_token(clean.get("mistral_api_key", ""))
    clean["openai_api_key"] = safe_token(clean.get("openai_api_key", ""))
    clean["gemini_api_key"] = safe_token(clean.get("gemini_api_key", ""))
    clean["anthropic_api_key"] = safe_token(clean.get("anthropic_api_key", ""))
    return clean


def get_business(instagram_business_id: str):
    instagram_business_id = normalize_id(instagram_business_id)
    if not instagram_business_id:
        return None
    result = supabase.table("businesses").select("*").eq("instagram_business_id", instagram_business_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_business_by_id(business_id: str):
    business_id = normalize_id(business_id)
    if not business_id:
        return None
    result = supabase.table("businesses").select("*").eq("id", business_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_business_by_page_id(page_id: str):
    page_id = normalize_id(page_id)
    if not page_id:
        return None
    result = supabase.table("businesses").select("*").eq("facebook_page_id", page_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_active_instagram_direct_business():
    result = supabase.table("businesses").select("*").eq("oauth_provider", "instagram_direct").eq("bot_enabled", True).limit(1).execute()
    return result.data[0] if result.data else None


def find_business_for_webhook(entry_id: str, recipient_id: str = ""):
    entry_id = normalize_id(entry_id)
    recipient_id = normalize_id(recipient_id)
    checks = [
        lambda: get_business(entry_id),
        lambda: get_business(recipient_id),
        lambda: get_business_by_page_id(entry_id),
        lambda: get_business_by_page_id(recipient_id),
    ]
    for fn in checks:
        business = fn()
        if business:
            return business
    return get_active_instagram_direct_business()


# ----------------------------------------------------------------------
# Instagram OAuth helpers
# ----------------------------------------------------------------------
def exchange_instagram_code_for_token(code: str):
    res = requests.post(
        "https://api.instagram.com/oauth/access_token",
        data={
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": INSTAGRAM_REDIRECT_URI,
            "code": code,
        },
        timeout=30,
    )
    log("Instagram short-lived token exchange", {"status": res.status_code, "body": res.text})
    res.raise_for_status()
    return res.json()


def exchange_for_long_lived_token(short_lived_token: str) -> str:
    res = requests.get(
        "https://graph.instagram.com/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": META_APP_SECRET,
            "access_token": short_lived_token,
        },
        timeout=30,
    )
    if not res.ok:
        return short_lived_token
    data = res.json()
    return data.get("access_token") or short_lived_token


def refresh_long_lived_token(existing_long_lived_token: str) -> str:
    res = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={
            "grant_type": "ig_refresh_token",
            "access_token": existing_long_lived_token,
        },
        timeout=30,
    )
    if not res.ok:
        return existing_long_lived_token
    data = res.json()
    return data.get("access_token") or existing_long_lived_token


def get_instagram_user(access_token: str):
    res = requests.get(
        f"{GRAPH_INSTAGRAM}/me",
        params={"fields": "id,username,account_type", "access_token": access_token},
        timeout=30,
    )
    return res.json() if res.ok else {}


def upsert_business(
    instagram_business_id: str,
    username: str,
    access_token: str,
    oauth_provider: str = "instagram_direct",
    facebook_page_id: str = "",
    facebook_page_name: str = "",
):
    instagram_business_id = normalize_id(instagram_business_id)
    facebook_page_id = normalize_id(facebook_page_id)
    existing = get_business(instagram_business_id)
    update_data = {
        "instagram_business_id": instagram_business_id,
        "business_name": username or f"instagram_{instagram_business_id}",
        "access_token": access_token or "",
        "page_access_token": None,
        "token_preview": safe_token(access_token),
        "oauth_provider": oauth_provider,
        "facebook_page_id": facebook_page_id or None,
        "facebook_page_name": facebook_page_name or None,
        "bot_enabled": True,
        "auto_reply_dms": True,
        "auto_reply_comments": True,
    }
    if existing:
        result = supabase.table("businesses").update(update_data).eq("id", existing["id"]).execute()
        return result.data
    insert_data = {
        **update_data,
        "business_type": "Instagram Business",
        "language": "uz",
        "tone": "friendly, polite, sales-focused",
        "knowledge": "",
        "products": "",
        "prices": "",
        "delivery_info": "",
        "working_hours": "",
        "faq": "",
        "catalog_link": "",
        "sales_phone": "",
        "telegram_single": "",
        "telegram_package": "",
        "telegram_bag": "",
    }
    result = supabase.table("businesses").upsert(insert_data, on_conflict="instagram_business_id").execute()
    return result.data


# ----------------------------------------------------------------------
# AI reply helpers
# ----------------------------------------------------------------------
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


def wants_catalog(text: str) -> bool:
    text = (text or "").lower()
    keywords = [
        "catalog","katalog","каталог","price","prices","narx","narxlari","narhi",
        "цена","цены","прайс","model","models","modellari","модель","модели",
        "collection","kolleksiya","коллекция","photo","photos","rasm","rasmlar",
        "фото","mahsulot","mahsulotlar","товар","товары",
    ]
    return any(k in text for k in keywords)


def get_catalog_link(business: dict) -> str:
    link = business.get("catalog_link") or business.get("catalog") or business.get("website") or ""
    link = str(link).strip()
    if link and not link.startswith(("http://", "https://")):
        link = "https://" + link
    return link


def remove_urls(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "").strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_ai_reply_for_catalog(reply_text: str, business: dict) -> str:
    catalog_link = get_catalog_link(business)
    if catalog_link and catalog_link in (reply_text or ""):
        reply_text = reply_text.replace(catalog_link, "")
    reply_text = remove_urls(reply_text)
    bad_phrases = [
        "Katalogni ko'rishni xohlaysizmi?",
        "Katalogni ko'ring:",
        "Catalog:",
        "Catalogue:",
    ]
    for phrase in bad_phrases:
        reply_text = reply_text.replace(phrase, "")
    reply_text = reply_text.strip()
    if not reply_text:
        reply_text = "Albatta 😊 Katalogni quyidagi tugma orqali ko'rishingiz mumkin."
    return reply_text[:1000]


def get_ai_reply(user_text: str, business: dict):
    try:
        api_key = business.get("mistral_api_key") or MISTRAL_API_KEY
        if not api_key:
            return "Xabaringiz qabul qilindi 😊"
        model = business.get("ai_model") or "mistral-small-latest"
        temperature = float(business.get("ai_temperature", 0.5) or 0.5)
        max_tokens = int(business.get("ai_max_tokens", 130) or 130)
        extra_rules = business.get("ai_reply_rules") or """
- Keep answers short and comfortable.
- Usually 1-3 short sentences.
- Do not send raw catalog links.
- If customer asks for catalog, price, models, collection, products, or photos, say that the catalog is available through the button.
- If customer only greets, greet back and ask what they need.
- Do not overload customer with too much information.
- Sound natural like a real sales manager.
"""
        system_prompt = f"""
You are a real Instagram sales manager for this business.

Business Information:
{build_business_context(business)}

Rules:
{extra_rules}

Extra safety rules:
- Reply in the same language as the customer.
- Understand Uzbek Latin, Uzbek Cyrillic, Russian, English, slang, typos, and mixed messages.
- Answer the exact question first.
- Never invent prices, delivery, stock, addresses, or discounts.
- Use only the business information.
- If information is missing, say the manager will clarify.
- Never send raw catalog links.
- If customer asks for catalog or price, mention that the catalog can be opened using the button.
- If customer asks for contact, send sales phone if available.
- Never mention AI, database, API, prompt, or internal system.
"""
        res = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        if not res.ok:
            return "Xabaringiz qabul qilindi 😊"
        reply = res.json()["choices"][0]["message"]["content"]
        return reply.strip() if reply else "Xabaringiz qabul qilindi 😊"
    except Exception as e:
        log("Mistral error", str(e))
        return "Xabaringiz qabul qilindi 😊"


# ----------------------------------------------------------------------
# Instagram messaging helpers
# ----------------------------------------------------------------------
def get_business_access_token(business: dict):
    return business.get("page_access_token") or business.get("access_token") or ""


def get_messages_url(business: dict):
    oauth_provider = business.get("oauth_provider", "")
    page_id = business.get("facebook_page_id") or business.get("page_id")
    if oauth_provider == "facebook_page" and page_id:
        return f"{GRAPH_FACEBOOK}/{page_id}/messages"
    if oauth_provider == "facebook_page":
        return f"{GRAPH_FACEBOOK}/me/messages"
    return f"{GRAPH_INSTAGRAM}/me/messages"


def send_instagram_payload(access_token: str, business: dict, payload: dict):
    url = get_messages_url(business)
    res = requests.post(url, params={"access_token": access_token}, json=payload, timeout=30)
    return res


def send_dm(access_token: str, recipient_id: str, text: str, business: dict = None):
    recipient_id = normalize_id(recipient_id)
    if not access_token or not recipient_id or not text:
        return None
    business = business or {}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text[:1000]},
    }
    if business.get("oauth_provider") == "facebook_page":
        payload["messaging_type"] = "RESPONSE"
    return send_instagram_payload(access_token, business, payload)


def send_instagram_dm(access_token: str, recipient_id: str, text: str, business: dict):
    """Wrapper compatible with /api/send-message"""
    res = send_dm(access_token, recipient_id, text, business)
    if res is None:
        return False, {"error": "Send failed"}
    try:
        result = res.json()
    except Exception:
        result = {"text": res.text}
    return res.ok, result


def send_instagram_media(access_token: str, recipient_id: str, media_type: str, media_url: str, caption: str = "", business: dict = None):
    recipient_id = normalize_id(recipient_id)
    if not access_token or not recipient_id or not media_url:
        return None
    business = business or {}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "image" if media_type == "photo" else "video",
                "payload": {"url": media_url},
            }
        },
    }
    if caption:
        payload["message"]["text"] = caption[:1000]
    if business.get("oauth_provider") == "facebook_page":
        payload["messaging_type"] = "RESPONSE"
    return send_instagram_payload(access_token, business, payload)


def send_catalog_button(access_token: str, recipient_id: str, business: dict, text: str = ""):
    recipient_id = normalize_id(recipient_id)
    catalog_link = get_catalog_link(business)
    if not access_token or not recipient_id or not catalog_link:
        return None
    text = clean_ai_reply_for_catalog(text, business)
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": text[:640],
                    "buttons": [{"type": "web_url", "url": catalog_link, "title": "Katalogni ko'rish"}],
                },
            }
        },
    }
    if business.get("oauth_provider") == "facebook_page":
        payload["messaging_type"] = "RESPONSE"
    return send_instagram_payload(access_token, business, payload)


def reply_to_comment(access_token: str, comment_id: str, text: str, business: dict = None):
    comment_id = normalize_id(comment_id)
    if not access_token or not comment_id or not text:
        return None
    oauth_provider = (business or {}).get("oauth_provider", "")
    if oauth_provider == "facebook_page":
        url = f"{GRAPH_FACEBOOK}/{comment_id}/comments"
    else:
        url = f"{GRAPH_INSTAGRAM}/{comment_id}/replies"
    text = remove_urls(text)[:1000]
    if not text:
        text = "Xabaringiz uchun rahmat 😊 Batafsil ma'lumot uchun DM yozing."
    res = requests.post(url, params={"access_token": access_token, "message": text}, timeout=30)
    return res


# ----------------------------------------------------------------------
# Save inbox message
# ----------------------------------------------------------------------
def save_inbox_message(
    business: dict,
    sender_id: str,
    recipient_id: str,
    message_text: str,
    direction: str,
    platform_message_id: str = "",
    raw_payload: dict = None,
    customer_name: str = "",
    is_read: bool = False,
    media_type: Optional[str] = None,
    media_url: Optional[str] = None,
):
    try:
        customer_id = sender_id if direction == "inbound" else recipient_id
        data = {
            "business_id": business.get("id"),
            "instagram_business_id": business.get("instagram_business_id"),
            "platform": "instagram",
            "customer_id": normalize_id(customer_id),
            "customer_name": customer_name or normalize_id(customer_id),
            "channel": "dm",
            "direction": direction,
            "role": "user" if direction == "inbound" else "assistant",
            "content": message_text,
            "external_message_id": platform_message_id,
            "raw_payload": raw_payload or {},
            "is_read": is_read if direction == "inbound" else True,
            "media_type": media_type,
            "media_url": media_url,
        }
        try:
            supabase.table("inbox_messages").insert(data).execute()
        except Exception:
            data.pop("customer_name", None)
            data.pop("is_read", None)
            supabase.table("inbox_messages").insert(data).execute()
    except Exception as e:
        log("Could not save inbox message", str(e))


# ----------------------------------------------------------------------
# Webhook processing (Instagram)
# ----------------------------------------------------------------------
async def process_messaging_event(entry_id: str, messaging: dict):
    log("Processing messaging event", messaging)
    if "read" in messaging or "delivery" in messaging:
        return
    message = messaging.get("message") or {}
    if not message:
        return
    sender_id = normalize_id(messaging.get("sender", {}).get("id"))
    recipient_id = normalize_id(messaging.get("recipient", {}).get("id"))
    message_text = message.get("text") or ""
    message_id = message.get("mid") or str(messaging.get("timestamp") or "")
    is_echo = bool(message.get("is_echo"))
    media_type = None
    media_url = None
    attachment = message.get("attachments", [])
    if attachment:
        att = attachment[0]
        att_type = att.get("type", "")
        att_payload = att.get("payload", {})
        att_url = att_payload.get("url", "")
        if att_type == "image":
            media_type = "photo"
            media_url = att_url
            if not message_text:
                message_text = "📸 Photo"
        elif att_type == "video":
            media_type = "video"
            media_url = att_url
            if not message_text:
                message_text = "🎥 Video"
        elif att_type == "file":
            media_type = "file"
            media_url = att_url
            if not message_text:
                message_text = "📎 File"
    if is_echo:
        return
    if not sender_id or not recipient_id:
        return
    if not message_text and not media_type:
        return
    if already_processed(processed_message_ids, message_id):
        return
    business = find_business_for_webhook(entry_id, recipient_id)
    if not business:
        return
    save_inbox_message(
        business=business,
        sender_id=sender_id,
        recipient_id=recipient_id,
        message_text=message_text,
        direction="inbound",
        platform_message_id=message_id,
        raw_payload=messaging,
        is_read=False,
        media_type=media_type,
        media_url=media_url,
    )
    if not business.get("bot_enabled", True):
        return
    if business.get("auto_reply_dms") is False:
        return
    access_token = get_business_access_token(business)
    if not access_token:
        return
    if not is_chat_ai_enabled("instagram", "dm", sender_id, business.get("id")):
        return
    reply_text = get_ai_reply(message_text or "Photo/Video received", business)
    should_send_catalog = wants_catalog(message_text) and bool(get_catalog_link(business))
    if should_send_catalog:
        send_result = send_catalog_button(access_token, sender_id, business, reply_text)
        saved_reply_text = clean_ai_reply_for_catalog(reply_text, business) + "\n[Catalog button sent]"
    else:
        reply_text = remove_urls(reply_text)
        send_result = send_dm(access_token, sender_id, reply_text, business)
        saved_reply_text = reply_text
    raw_result = {}
    if send_result is not None:
        try:
            raw_result = send_result.json()
        except Exception:
            raw_result = {"text": send_result.text}
    save_inbox_message(
        business=business,
        sender_id=recipient_id,
        recipient_id=sender_id,
        message_text=saved_reply_text,
        direction="outbound",
        platform_message_id=raw_result.get("message_id", ""),
        raw_payload=raw_result,
        is_read=True,
    )


async def process_comment_event(entry_id: str, change: dict):
    value = change.get("value", {})
    comment_id = normalize_id(value.get("comment_id") or value.get("id"))
    comment_text = value.get("message") or value.get("text") or ""
    if not comment_id or not comment_text:
        return
    if already_processed(processed_comment_ids, comment_id):
        return
    business = find_business_for_webhook(entry_id)
    if not business:
        return
    if not business.get("bot_enabled", True):
        return
    if business.get("auto_reply_comments") is False:
        return
    access_token = get_business_access_token(business)
    if not access_token:
        return
    reply_text = get_ai_reply(comment_text, business)
    reply_text = remove_urls(reply_text)
    if wants_catalog(comment_text):
        reply_text = "Katalogni DM orqali yuboramiz 😊 Iltimos, bizga xabar yozing."
    reply_to_comment(access_token, comment_id, reply_text, business)


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# API routes for the new HTML/CSS/JS dashboard
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------

@app.get("/api/health")
async def api_health():
    """Health check – public"""
    return {"status": "ok", "version": "3.0.0"}


@app.post("/api/auth/login")
async def api_login(email: str = "", password: str = ""):
    """Simple login (can be extended later). No secret required."""
    if not email or not password:
        return JSONResponse({"status": "error", "message": "Email and password required"}, status_code=400)
    # Placeholder – you can implement real auth here
    return JSONResponse({
        "status": "ok",
        "user": {"email": email, "id": "user_123", "is_admin": email == "admin@example.com"},
        "token": "placeholder_token"
    })


# ---------- Businesses ----------
@app.get("/api/businesses")
async def api_get_businesses(x_dashboard_secret: str = Header(default="")):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        result = supabase.table("businesses").select("*").order("created_at", desc=True).execute()
        return {"status": "ok", "count": len(result.data or []), "data": result.data or []}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/business/{business_id}")
async def api_get_business(business_id: str, x_dashboard_secret: str = Header(default="")):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        result = supabase.table("businesses").select("*").eq("id", business_id).limit(1).execute()
        if not result.data:
            return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
        return {"status": "ok", "data": result.data[0]}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ---------- Conversations ----------
@app.get("/api/conversations")
async def api_get_conversations(
    platform: str = "all",
    search: str = "",
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        query = supabase.table("inbox_messages").select("*").order("created_at", desc=True).limit(900)
        if platform != "all":
            query = query.eq("platform", platform)
        rows = query.execute().data or []
        conversations = {}
        for row in rows:
            business_id = row.get("business_id")
            plat = row.get("platform", "instagram")
            channel = row.get("channel", "")
            customer_id = str(row.get("customer_id") or "").strip()
            if not business_id or not customer_id:
                continue
            key = f"{plat}::{business_id}::{channel}::{customer_id}"
            if key not in conversations:
                conversations[key] = {
                    "id": key,
                    "business_id": business_id,
                    "platform": plat,
                    "channel": channel,
                    "customer_id": customer_id,
                    "chat_id": str(row.get("chat_id") or customer_id),
                    "customer_name": row.get("customer_name") or f"Client {str(customer_id)[-4:]}",
                    "last_message": row.get("content", ""),
                    "last_message_at": row.get("created_at", ""),
                    "unread_count": 0,
                    "total_messages": 0,
                }
            conversations[key]["total_messages"] += 1
            if row.get("direction") == "inbound" and not bool(row.get("is_read", False)):
                conversations[key]["unread_count"] += 1
        results = list(conversations.values())
        if search.strip():
            q = search.lower().strip()
            results = [c for c in results if q in f"{c.get('customer_id','')} {c.get('customer_name','')} {c.get('last_message','')}".lower()]
        return {"status": "ok", "count": len(results), "data": results}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/conversation/{conversation_id}")
async def api_get_conversation_messages(
    conversation_id: str,
    limit: int = 250,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse({"status": "error", "message": "Invalid conversation ID"}, status_code=400)
        platform, business_id, channel, customer_id = parts
        query = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", platform)
            .eq("business_id", business_id)
            .eq("customer_id", str(customer_id))
        )
        if channel:
            query = query.eq("channel", channel)
        messages = query.order("created_at", desc=False).limit(limit).execute().data or []
        return {"status": "ok", "count": len(messages), "data": messages}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ---------- Send message (text) ----------
@app.post("/api/send-message")
async def api_send_message(
    conversation_id: str,
    text: str,
    business_id: str,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        parts = conversation_id.split("::")
        platform, biz_id, channel, customer_id = parts
        business = get_business_by_id(biz_id)
        if not business:
            return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
        if platform == "instagram":
            ok, result = send_instagram_dm(
                access_token=get_business_access_token(business),
                recipient_id=customer_id,
                text=text,
                business=business,
            )
        elif platform == "telegram":
            ok, result = send_telegram_bot_message(chat_id=customer_id, text=text)
        else:
            return JSONResponse({"status": "error", "message": "Unknown platform"}, status_code=400)
        return {"status": "ok" if ok else "error", "meta": result}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ---------- Send file (photo/video) ----------
@app.post("/api/send-file")
async def api_send_file(
    conversation_id: str,
    caption: str = "",
    media_type: str = "photo",
    file_data: str = "",
    filename: str = "",
    business_id: str = "",
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        parts = conversation_id.split("::")
        platform, biz_id, channel, customer_id = parts
        business = get_business_by_id(biz_id)
        if not business:
            return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
        file_bytes = base64.b64decode(file_data)
        # Write to temporary file
        suffix = f"_{filename}" if filename else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            if platform == "instagram":
                # Instagram requires a public URL, not raw bytes.
                # In production, upload the file to cloud storage first and use the URL.
                # For a quick demo we can reuse the Telegram bot API as a file host.
                # Placeholder: just respond with an error for now.
                return JSONResponse({"status": "error", "message": "Instagram file sending via raw bytes not implemented yet. Use /dashboard/send-instagram-file for now."}, status_code=501)
            elif platform == "telegram":
                # Use the Telegram bot to send the file
                url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/send{'Photo' if media_type == 'photo' else 'Video'}"
                with open(tmp_path, 'rb') as f:
                    files = {media_type: f, 'chat_id': (None, str(customer_id))}
                    if caption:
                        files['caption'] = (None, caption[:1024])
                    res = requests.post(url, files=files, timeout=60)
                try:
                    result = res.json()
                except:
                    result = {"text": res.text}
                ok = res.ok
                if ok:
                    # Save outbound message
                    business = get_business_by_id(biz_id)
                    if business:
                        save_telegram_message(
                            business=business,
                            customer_id=customer_id,
                            text=caption or f"📎 {media_type.upper()} sent",
                            direction="outbound",
                            message_id="",
                            raw_payload=result,
                            channel="telegram_user_private" if channel == "telegram_user_private" else "telegram_bot_private",
                            chat_id=customer_id,
                            media_type=media_type,
                        )
            else:
                ok, result = False, {"error": "Unknown platform"}
        finally:
            os.remove(tmp_path)
        return {"status": "ok" if ok else "error", "meta": result}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ---------- Send voice (Telegram only) ----------
@app.post("/api/send-voice")
async def api_send_voice(
    customer_id: str,
    file_data: str = "",
    filename: str = "",
    chat_id: str = "",
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        file_bytes = base64.b64decode(file_data)
        suffix = f"_{filename}" if filename else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendVoice"
            with open(tmp_path, 'rb') as f:
                files = {'voice': f, 'chat_id': (None, str(chat_id or customer_id))}
                res = requests.post(url, files=files, timeout=60)
            try:
                result = res.json()
            except:
                result = {"text": res.text}
            ok = res.ok
            if ok:
                business = get_active_business()
                if business:
                    save_telegram_message(
                        business=business,
                        customer_id=customer_id,
                        text="🎤 Voice message sent",
                        direction="outbound",
                        message_id="",
                        raw_payload=result,
                        channel="telegram_user_private",
                        chat_id=chat_id or customer_id,
                        media_type="voice",
                    )
        finally:
            os.remove(tmp_path)
        return {"status": "ok" if ok else "error", "meta": result}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ---------- AI toggle per chat ----------
@app.post("/api/chat-ai-toggle")
async def api_toggle_chat_ai(
    business_id: str,
    platform: str,
    channel: str,
    customer_id: str,
    enabled: bool,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        set_chat_ai_enabled(business_id, platform, channel, customer_id, enabled)
        return {"status": "ok", "enabled": enabled}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ---------- Business settings (JSON body) ----------
@app.post("/api/business-settings")
async def api_update_business_settings(
    body: BusinessSettingsUpdate,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        business = get_business_by_id(body.business_id)
        if not business:
            return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
        update_business(body.business_id, body.settings)
        return {"status": "ok", "message": "Settings updated"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ---------- Stats ----------
@app.get("/api/stats")
async def api_get_stats(x_dashboard_secret: str = Header(default="")):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    try:
        businesses = get_all_businesses()
        instagram_count = get_message_count("instagram")
        telegram_count = get_message_count("telegram")
        return {
            "status": "ok",
            "data": {
                "total_accounts": len(businesses),
                "active_accounts": sum(1 for b in businesses if b.get("bot_enabled")),
                "instagram_messages": instagram_count,
                "telegram_messages": telegram_count,
            }
        }
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ----------------------------------------------------------------------
# Old /dashboard/ endpoints (still used by Streamlit)
# ----------------------------------------------------------------------
@app.post("/dashboard/send-instagram-dm")
async def dashboard_send_instagram_dm(
    payload: ManualInstagramReply,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    business = get_business_by_id(payload.business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
    text = payload.text.strip()
    customer_id = normalize_id(payload.customer_id)
    if not text or not customer_id:
        return JSONResponse({"status": "error", "message": "Missing customer_id or text"}, status_code=400)
    access_token = get_business_access_token(business)
    if not access_token:
        return JSONResponse({"status": "error", "message": "Business has no access token"}, status_code=400)
    if wants_catalog(text) and get_catalog_link(business):
        res = send_catalog_button(access_token, customer_id, business, text)
        saved_text = clean_ai_reply_for_catalog(text, business) + "\n[Catalog button sent]"
    else:
        text = remove_urls(text)
        res = send_dm(access_token, customer_id, text, business)
        saved_text = text
    if res is None:
        return JSONResponse({"status": "error", "message": "Send failed"}, status_code=500)
    try:
        result = res.json()
    except Exception:
        result = {"text": res.text}
    if not res.ok:
        return JSONResponse({"status": "error", "meta": result}, status_code=res.status_code)
    save_inbox_message(
        business=business,
        sender_id=business.get("instagram_business_id") or "",
        recipient_id=customer_id,
        message_text=saved_text,
        direction="outbound",
        platform_message_id=result.get("message_id", ""),
        raw_payload=result,
        is_read=True,
    )
    return JSONResponse({"status": "ok", "meta": result}, status_code=200)


@app.post("/dashboard/send-instagram-media")
async def dashboard_send_instagram_media(
    payload: ManualInstagramMedia,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    business = get_business_by_id(payload.business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
    customer_id = normalize_id(payload.customer_id)
    if not customer_id or not payload.media_url:
        return JSONResponse({"status": "error", "message": "Missing customer_id or media_url"}, status_code=400)
    access_token = get_business_access_token(business)
    if not access_token:
        return JSONResponse({"status": "error", "message": "Business has no access token"}, status_code=400)
    res = send_instagram_media(access_token, customer_id, payload.media_type, payload.media_url, payload.caption, business)
    if res is None:
        return JSONResponse({"status": "error", "message": "Send failed"}, status_code=500)
    try:
        result = res.json()
    except Exception:
        result = {"text": res.text}
    if not res.ok:
        return JSONResponse({"status": "error", "meta": result}, status_code=res.status_code)
    save_inbox_message(
        business=business,
        sender_id=business.get("instagram_business_id") or "",
        recipient_id=customer_id,
        message_text=payload.caption or f"📎 {payload.media_type.upper()} sent",
        direction="outbound",
        platform_message_id=result.get("message_id", ""),
        raw_payload=result,
        is_read=True,
        media_type=payload.media_type,
        media_url=payload.media_url,
    )
    return JSONResponse({"status": "ok", "meta": result}, status_code=200)


@app.post("/dashboard/send-telegram-user-message")
async def dashboard_send_telegram_user_message(
    payload: ManualTelegramMessage,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    text = payload.text.strip()
    customer_id = normalize_id(payload.customer_id)
    if not text or not customer_id:
        return JSONResponse({"status": "error", "message": "Missing customer_id or text"}, status_code=400)
    ok, result = await send_telegram_user_message(customer_id=customer_id, text=text)
    if not ok:
        return JSONResponse({"status": "error", "meta": result}, status_code=400)
    business = get_active_business()
    if business:
        save_telegram_message(
            business=business,
            customer_id=customer_id,
            text=text,
            direction="outbound",
            message_id=result.get("message_id", ""),
            raw_payload=result,
            channel="telegram_user_private",
            customer_name=result.get("customer_name", ""),
            chat_id=result.get("chat_id", customer_id),
        )
    return JSONResponse({"status": "ok", "meta": result}, status_code=200)


@app.post("/dashboard/send-telegram-file")
async def dashboard_send_telegram_file(
    payload: ManualTelegramFile,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    customer_id = normalize_id(payload.customer_id)
    chat_id = normalize_id(payload.chat_id)
    if not customer_id or not payload.file_data:
        return JSONResponse({"status": "error", "message": "Missing customer_id or file_data"}, status_code=400)
    try:
        file_bytes = base64.b64decode(payload.file_data)
        suffix = f"_{payload.filename}" if payload.filename else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/send{'Photo' if payload.media_type == 'photo' else 'Video'}"
            with open(tmp_path, 'rb') as f:
                files = {payload.media_type: f, 'chat_id': (None, str(chat_id))}
                if payload.caption:
                    files['caption'] = (None, payload.caption[:1024])
                res = requests.post(url, files=files, timeout=60)
            try:
                result = res.json()
            except:
                result = {"text": res.text}
            if not res.ok:
                return JSONResponse({"status": "error", "meta": result}, status_code=res.status_code)
            business = get_active_business()
            if business:
                save_telegram_message(
                    business=business,
                    customer_id=customer_id,
                    text=payload.caption or f"📎 {payload.media_type.upper()} sent",
                    direction="outbound",
                    message_id="",
                    raw_payload=result,
                    channel="telegram_user_private",
                    chat_id=chat_id,
                    media_type=payload.media_type,
                )
            return JSONResponse({"status": "ok", "meta": result}, status_code=200)
        finally:
            os.remove(tmp_path)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/dashboard/send-telegram-voice-file")
async def dashboard_send_telegram_voice_file(
    payload: ManualTelegramVoiceFile,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    customer_id = normalize_id(payload.customer_id)
    chat_id = normalize_id(payload.chat_id)
    if not customer_id or not payload.file_data:
        return JSONResponse({"status": "error", "message": "Missing customer_id or file_data"}, status_code=400)
    try:
        file_bytes = base64.b64decode(payload.file_data)
        suffix = f"_{payload.filename}" if payload.filename else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendVoice"
            with open(tmp_path, 'rb') as f:
                files = {'voice': f, 'chat_id': (None, str(chat_id))}
                res = requests.post(url, files=files, timeout=60)
            try:
                result = res.json()
            except:
                result = {"text": res.text}
            if not res.ok:
                return JSONResponse({"status": "error", "meta": result}, status_code=res.status_code)
            business = get_active_business()
            if business:
                save_telegram_message(
                    business=business,
                    customer_id=customer_id,
                    text="🎤 Voice message sent",
                    direction="outbound",
                    message_id="",
                    raw_payload=result,
                    channel="telegram_user_private",
                    chat_id=chat_id,
                    media_type="voice",
                )
            return JSONResponse({"status": "ok", "meta": result}, status_code=200)
        finally:
            os.remove(tmp_path)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/dashboard/send-instagram-file")
async def dashboard_send_instagram_file(
    payload: ManualInstagramFile,
    x_dashboard_secret: str = Header(default=""),
):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    business = get_business_by_id(payload.business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
    customer_id = normalize_id(payload.customer_id)
    if not customer_id or not payload.file_data:
        return JSONResponse({"status": "error", "message": "Missing customer_id or file_data"}, status_code=400)
    try:
        file_bytes = base64.b64decode(payload.file_data)
        suffix = f"_{payload.filename}" if payload.filename else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            access_token = get_business_access_token(business)
            if not access_token:
                return JSONResponse({"status": "error", "message": "No access token"}, status_code=400)
            # Instagram file sending via raw bytes requires public URL; this is a placeholder.
            # You can use the same Telegram bot as a temporary hosting hack.
            return JSONResponse({"status": "error", "message": "Instagram file upload via raw bytes not yet implemented."}, status_code=501)
        finally:
            os.remove(tmp_path)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ----------------------------------------------------------------------
# Health, OAuth, webhook, privacy, etc. (unchanged)
# ----------------------------------------------------------------------
@app.head("/")
async def head_home():
    return PlainTextResponse("", status_code=200)


@app.get("/connect")
async def connect():
    return RedirectResponse("/connect-instagram")


@app.get("/connect-instagram")
async def connect_instagram():
    params = {
        "client_id": META_APP_ID,
        "redirect_uri": INSTAGRAM_REDIRECT_URI,
        "scope": "instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments",
        "response_type": "code",
        "state": secrets.token_urlsafe(16),
    }
    auth_url = "https://www.instagram.com/oauth/authorize?" + urlencode(params)
    return RedirectResponse(auth_url)


@app.get("/auth/instagram/callback")
async def instagram_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return PlainTextResponse("Missing Instagram code", status_code=400)
    try:
        token_data = exchange_instagram_code_for_token(code)
        short_lived_token = token_data.get("access_token")
        user_id = normalize_id(token_data.get("user_id"))
        if not short_lived_token or not user_id:
            raise ValueError("Missing access_token or user_id")
        access_token = exchange_for_long_lived_token(short_lived_token)
        user_info = get_instagram_user(access_token)
        username = user_info.get("username") or f"instagram_{user_id}"
        upsert_business(user_id, username, access_token, oauth_provider="instagram_direct")
        return RedirectResponse(f"{DASHBOARD_URL}?connected=success")
    except Exception as e:
        log("Instagram OAuth error", str(e))
        return PlainTextResponse(f"Instagram OAuth error: {str(e)}", status_code=500)


@app.get("/connect-facebook")
async def connect_facebook():
    params = {
        "client_id": META_APP_ID,
        "redirect_uri": FACEBOOK_REDIRECT_URI,
        "scope": "pages_show_list,pages_read_engagement,pages_manage_metadata,pages_messaging,instagram_basic,instagram_manage_messages,instagram_manage_comments",
        "response_type": "code",
        "state": secrets.token_urlsafe(16),
    }
    auth_url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urlencode(params)
    return RedirectResponse(auth_url)


@app.get("/auth/facebook/callback")
async def facebook_callback(request: Request):
    return PlainTextResponse("Facebook callback available, but currently using Instagram Direct primary mode.", status_code=200)


@app.get("/debug/businesses")
async def debug_businesses():
    result = supabase.table("businesses").select("*").order("created_at", desc=True).execute()
    rows = [sanitize_business_row(r) for r in (result.data or [])]
    return {"count": len(rows), "businesses": rows}


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN and params.get("hub.challenge"):
        return PlainTextResponse(params.get("hub.challenge"), status_code=200)
    return PlainTextResponse("Verification failed", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()
        log("WEBHOOK RECEIVED", data)
        for entry in data.get("entry", []):
            entry_id = normalize_id(entry.get("id"))
            for messaging in entry.get("messaging", []):
                await process_messaging_event(entry_id, messaging)
            for change in entry.get("changes", []):
                field = change.get("field")
                if field in ["comments", "feed"]:
                    await process_comment_event(entry_id, change)
                elif field == "messages":
                    value = change.get("value", {})
                    fake_messaging = {
                        "sender": value.get("sender", {}),
                        "recipient": value.get("recipient", {}),
                        "timestamp": value.get("timestamp"),
                        "message": value.get("message", {}),
                    }
                    await process_messaging_event(entry_id, fake_messaging)
        return JSONResponse({"status": "ok"}, status_code=200)
    except Exception as e:
        log("Webhook error", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/privacy")
async def privacy():
    return PlainTextResponse("Privacy Policy: This app collects Instagram and Telegram messages to provide automated and manual sales replies.")

@app.get("/terms")
async def terms():
    return PlainTextResponse("Terms of Service: This app provides automated and manual Instagram and Telegram sales replies using AI-assisted tools.")
