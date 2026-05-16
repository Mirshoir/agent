import os
import re
import time
import secrets
import base64
import tempfile
import shutil
import subprocess
import requests
from urllib.parse import urlencode
from typing import Optional
from datetime import datetime

from pydantic import BaseModel
from fastapi import FastAPI, Request, Header
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from supabase import create_client

from telegram_bot import (
    telegram_router,
    start_telegram_user_client,
    stop_telegram_user_client,
    send_telegram_user_message,
    send_telegram_user_file,
    send_telegram_user_voice_file,
    send_telegram_bot_message,
    save_telegram_message,
    get_active_business,
)

def env_list(name: str, default: str = ""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=env_list(
        "CORS_ORIGINS",
        "https://agent-kqwah9x4f-mirshoir-s-projects.vercel.app,https://agent-rust-delta.vercel.app,https://agent-psi-liard.vercel.app,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173,http://127.0.0.1:5173,https://instaagent.streamlit.app,https://agent-1-xi6h.onrender.com",
    ),
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app"),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telegram_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response

# ============================================================================
# SERVE REACT UI
# ============================================================================
try:
    app.mount("/static", StaticFiles(directory="static", html=True), name="static")
except Exception:
    pass


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve React dashboard"""
    for path in ("frontend/index.html", "static/index.html", "static/Instaagent Dashboard.html"):
        try:
            with open(path, "r") as f:
                return f.read()
        except FileNotFoundError:
            continue
    return RedirectResponse(DASHBOARD_URL)


@app.on_event("startup")
async def startup_telegram_user_client():
    await start_telegram_user_client()


@app.on_event("shutdown")
async def shutdown_telegram_user_client():
    await stop_telegram_user_client()


# ============================================================================
# ENV
# ============================================================================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
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

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://instaagent.streamlit.app")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://agent-1-xi6h.onrender.com")

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
WHATSAPP_MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
WHATSAPP_CATALOG_LINK = os.getenv("CATALOG_LINK", "Catalog link will be shared soon.")

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_message_ids = {}
processed_comment_ids = {}
processing_message_ids = set()
processing_comment_ids = set()
DEDUP_TTL_SECONDS = 60 * 60
WHATSAPP_CHAT_MEMORY = {}


# ============================================================================
# MODELS
# ============================================================================
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
    business_id: str = ""
    customer_id: str
    chat_id: str = ""
    text: str


class ManualTelegramFile(BaseModel):
    customer_id: str
    chat_id: str
    caption: str = ""
    media_type: str
    file_data: str
    filename: str


class ManualTelegramVoiceFile(BaseModel):
    customer_id: str
    chat_id: str
    file_data: str
    filename: str


class ManualInstagramFile(BaseModel):
    business_id: str
    customer_id: str
    caption: str = ""
    media_type: str
    file_data: str
    filename: str


class DashboardImageFile(BaseModel):
    business_id: str = ""
    conversation_id: str = ""
    platform: str
    channel: str = ""
    customer_id: str
    chat_id: str = ""
    caption: str = ""
    file_data: str
    filename: str = "image.jpg"
    mime_type: str = "image/jpeg"


class DashboardVoiceFile(BaseModel):
    business_id: str = ""
    conversation_id: str = ""
    platform: str
    channel: str = ""
    customer_id: str
    chat_id: str = ""
    file_data: str
    filename: str = "voice.ogg"
    mime_type: str = "audio/ogg"


class BusinessSettingsUpdate(BaseModel):
    business_id: str
    settings: dict


class AIPromptSettingsUpdate(BaseModel):
    business_id: str
    settings: dict


class AIPromptGenerateRequest(BaseModel):
    business_id: str
    field: str
    current_prompt: str = ""
    goal: str = "make it more natural and sales-focused"


class ManualWhatsAppReply(BaseModel):
    business_id: str = ""
    customer_id: str
    text: str


# ============================================================================
# HELPERS - GENERAL
# ============================================================================
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


def safe_json(res):
    if res is None:
        return {}
    try:
        return res.json()
    except Exception:
        return {"text": res.text}


def standard_channel(platform: str, channel: str = "") -> str:
    platform = normalize_id(platform).lower()
    channel = normalize_id(channel).lower()
    if platform == "instagram":
        return "dm" if channel in ("", "instagram", "instagram_dm") else channel
    if platform == "whatsapp":
        return "whatsapp"
    if platform == "telegram":
        if channel in ("private", "telegram_bot", "telegram_bot_dm"):
            return "telegram_bot_private"
        if channel in ("user", "telegram_user"):
            return "telegram_user_private"
        return channel or "telegram_bot_private"
    return channel or platform


def instagram_reply_window_closed(result: dict) -> bool:
    error = result.get("error") if isinstance(result, dict) else {}
    if not isinstance(error, dict):
        error = {}

    code = error.get("code") or result.get("code") or result.get("error_code")
    subcode = (
        error.get("error_subcode")
        or error.get("subcode")
        or result.get("error_subcode")
        or result.get("subcode")
    )

    return str(code) == "10" and str(subcode) == "2534022"


def send_failure_response(result: dict, default_message: str = "Failed to send message"):
    message = default_message
    if instagram_reply_window_closed(result or {}):
        message = "Instagram reply window is closed. Ask the customer to send a new DM first."

    return JSONResponse(
        {"status": "error", "message": message, "details": result or {}},
        status_code=400,
    )


def decode_upload_data(file_data: str, max_bytes: int = 10 * 1024 * 1024):
    raw = str(file_data or "")

    if "," in raw and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]

    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception:
        raise ValueError("Invalid base64 file data")

    if not decoded:
        raise ValueError("Empty file upload")

    if len(decoded) > max_bytes:
        raise ValueError("File is too large. Maximum upload size is 10 MB.")

    return decoded


def transcode_to_telegram_voice(file_bytes: bytes, filename: str = "", mime_type: str = ""):
    """
    Telegram native voice notes should be OGG/Opus. Browser recordings usually
    arrive as WebM, which Telegram clients display as a downloadable file.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to convert browser recordings into Telegram voice notes")

    suffix = ".webm"
    if "." in str(filename or ""):
        suffix = "." + str(filename).rsplit(".", 1)[-1].lower()

    input_path = ""
    output_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as source:
            source.write(file_bytes)
            input_path = source.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as target:
            output_path = target.name

        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                input_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "48000",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                "-application",
                "voip",
                "-f",
                "ogg",
                output_path,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
        )

        with open(output_path, "rb") as converted:
            return converted.read(), "voice.ogg", "audio/ogg"

    finally:
        for path in [input_path, output_path]:
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass


def cleanup_dedup_cache():
    now = time.time()
    for cache in (processed_message_ids, processed_comment_ids):
        expired = [k for k, v in cache.items() if now - v > DEDUP_TTL_SECONDS]
        for key in expired:
            cache.pop(key, None)


def is_processed(cache: dict, event_id: str) -> bool:
    if not event_id:
        return False
    cleanup_dedup_cache()
    return event_id in cache


def mark_processed(cache: dict, event_id: str):
    if event_id:
        cleanup_dedup_cache()
        cache[event_id] = time.time()


def already_processed(cache: dict, event_id: str) -> bool:
    if not event_id:
        return False
    cleanup_dedup_cache()
    if event_id in cache:
        return True
    cache[event_id] = time.time()
    return False


def require_dashboard_secret(x_dashboard_secret: str):
    return bool(DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET)


def require_dashboard_media_secret(token: str = "", x_dashboard_secret: str = ""):
    return bool(DASHBOARD_SECRET and token != DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET)


# ============================================================================
# HELPERS - REACT UI SPECIFIC
# ============================================================================
def generate_avatar(name: str) -> dict:
    """Generate avatar with initials and color for React UI"""
    clean_name = str(name or "").strip()
    parts = clean_name.split()
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[1][0]).upper()
    else:
        initials = (parts[0][:2] if parts[0] else "??").upper()

    hash_val = sum(ord(c) for c in clean_name or initials) % 8
    colors = [
        "linear-gradient(135deg,#e8a07a,#c75d3f)",
        "linear-gradient(135deg,#7fa8d1,#3a6aa3)",
        "linear-gradient(135deg,#d6b48a,#a07a4a)",
        "linear-gradient(135deg,#d97b8a,#9b3f5a)",
        "linear-gradient(135deg,#a8b899,#5d7548)",
        "linear-gradient(135deg,#cfa8d6,#7e4f9b)",
        "linear-gradient(135deg,#e3c87a,#a07e2a)",
        "linear-gradient(135deg,#7a8aa8,#3f4f6f)",
    ]

    return {
        "initials": initials,
        "color": colors[hash_val]
    }


def format_time(timestamp: str) -> str:
    """Format ISO timestamp to relative time"""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        now = datetime.now(dt.tzinfo)
        delta = now - dt
        seconds = delta.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            return f"{minutes} min" if minutes != 1 else "1 min"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f"{hours} hr" if hours != 1 else "1 hr"
        elif seconds < 604800:
            days = int(seconds // 86400)
            return "yesterday" if days == 1 else f"{days} days"
        else:
            weeks = int(seconds // 604800)
            return f"{weeks} weeks" if weeks != 1 else "1 week"
    except Exception:
        return "unknown"


def extract_date(timestamp: str) -> str:
    """Extract date like 'March 2025' from ISO timestamp"""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return dt.strftime('%B %Y')
    except Exception:
        return "unknown"


def transform_message_to_react(row: dict) -> dict:
    """Transform database message row to React UI format"""
    message = {
        'id': row.get('id', ''),
        'side': 'out' if row['direction'] == 'outbound' else 'in',
        'from': 'ai' if row['role'] == 'assistant' else 'user',
        'time': format_time(row.get('created_at', '')),
    }

    media_type = row.get('media_type')
    content = row.get('content', '')

    if media_type:
        message['type'] = 'media'
        message['label'] = media_type
        message['mediaCaption'] = content
        message['mediaUrl'] = row.get('media_url', '')
    else:
        message['type'] = 'text'
        message['text'] = content

    return message


def transform_conversation_to_react(key: str, rows: list, business: dict = None) -> dict:
    """Transform database rows to React conversation format"""
    if not rows:
        return None

    latest_row = rows[-1]
    parts = key.split("::")
    if len(parts) != 4:
        return None

    platform, business_id, channel, customer_id = parts

    customer_name = latest_row.get('customer_name') or f'Customer {customer_id[-4:]}'
    ai_enabled = is_chat_ai_enabled(platform, channel, customer_id, business_id)

    return {
        'id': key,
        'name': customer_name,
        'handle': f'@{customer_id}',
        'platform': platform,
        'avatar': generate_avatar(customer_name),
        'lang': business.get('language', 'uz') if business else 'uz',
        'online': False,
        'needsHuman': latest_row.get('needs_human', False),
        'aiOn': ai_enabled,
        'unread': sum(1 for r in rows if r.get('direction') == 'inbound' and not r.get('is_read', False)),
        'lastTime': format_time(latest_row.get('created_at', '')),
        'lastFromMe': latest_row.get('direction') == 'outbound',
        'preview': latest_row.get('content', '')[:60],
        'lastAt': extract_date(latest_row.get('created_at', '')),
        'tags': ['Customer'],
        'customerSince': extract_date(rows[0].get('created_at', '')),
        'location': 'Unknown',
        'summary': f"Total messages: {len(rows)}",
        'kpis': {
            'orders': 0,
            'ltv': '0',
            'last': '—',
            'conv': '—'
        },
        'orders': [],
        'suggestions': [
            'Salom! Qanday yordam kerak?',
            'Katalogni ko\'ring',
            'Qanday mahsulot xohlaysiz?',
        ],
    }


# ============================================================================
# DATABASE
# ============================================================================
def get_all_businesses():
    result = supabase.table("businesses").select("*").order("created_at", desc=True).execute()
    return result.data or []


def get_business_by_id(business_id: str):
    business_id = normalize_id(business_id)
    if not business_id:
        return None
    result = supabase.table("businesses").select("*").eq("id", business_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_business(instagram_business_id: str):
    instagram_business_id = normalize_id(instagram_business_id)
    if not instagram_business_id:
        return None
    result = supabase.table("businesses").select("*").eq("instagram_business_id", instagram_business_id).limit(
        1).execute()
    return result.data[0] if result.data else None


def get_business_by_page_id(page_id: str):
    page_id = normalize_id(page_id)
    if not page_id:
        return None
    result = supabase.table("businesses").select("*").eq("facebook_page_id", page_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_business_by_whatsapp_phone_number_id(phone_number_id: str):
    phone_number_id = normalize_id(phone_number_id)
    if not phone_number_id:
        return None
    try:
        result = (
            supabase.table("businesses")
            .select("*")
            .eq("whatsapp_phone_number_id", phone_number_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_active_instagram_direct_business():
    try:
        result = (
            supabase.table("businesses")
            .select("*")
            .eq("oauth_provider", "instagram_direct")
            .eq("bot_enabled", True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_active_whatsapp_business():
    try:
        if WHATSAPP_PHONE_NUMBER_ID:
            row = get_business_by_whatsapp_phone_number_id(WHATSAPP_PHONE_NUMBER_ID)
            if row:
                return row

        result = (
            supabase.table("businesses")
            .select("*")
            .eq("bot_enabled", True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def find_business_for_webhook(entry_id: str, recipient_id: str = ""):
    entry_id = normalize_id(entry_id)
    recipient_id = normalize_id(recipient_id)

    for lookup_id in [entry_id, recipient_id]:
        business = get_business(lookup_id)
        if business:
            return business

    for lookup_id in [entry_id, recipient_id]:
        business = get_business_by_page_id(lookup_id)
        if business:
            return business

    return get_active_instagram_direct_business()


def update_business(business_id, data):
    return supabase.table("businesses").update(data).eq("id", business_id).execute()


ALLOWED_BUSINESS_SETTINGS = {
    "business_name",
    "business_type",
    "language",
    "tone",
    "bot_enabled",
    "auto_reply_dms",
    "auto_reply_comments",
    "products",
    "prices",
    "delivery_info",
    "working_hours",
    "faq",
    "catalog_link",
    "sales_phone",
    "knowledge",
    "telegram_single",
    "telegram_package",
    "telegram_bag",
    "ai_model",
    "ai_temperature",
    "ai_max_tokens",
    "ai_reply_rules",
    "mistral_api_key",
    "openai_api_key",
    "gemini_api_key",
    "anthropic_api_key",
}


def clean_business_settings(settings: dict) -> dict:
    cleaned = {}
    for key, value in (settings or {}).items():
        if key not in ALLOWED_BUSINESS_SETTINGS:
            continue

        if key == "ai_temperature":
            try:
                cleaned[key] = max(0.0, min(1.0, float(value)))
            except Exception:
                continue
        elif key == "ai_max_tokens":
            try:
                cleaned[key] = max(50, min(1000, int(value)))
            except Exception:
                continue
        elif key in {"bot_enabled", "auto_reply_dms", "auto_reply_comments"}:
            cleaned[key] = bool(value)
        elif key.endswith("_api_key"):
            cleaned[key] = str(value or "").strip()
        else:
            cleaned[key] = str(value or "").strip()

    return cleaned


def sanitize_business_row(row: dict):
    if not row:
        return None
    clean = dict(row)
    for key in [
        "access_token",
        "page_access_token",
        "whatsapp_access_token",
        "mistral_api_key",
        "openai_api_key",
        "gemini_api_key",
        "anthropic_api_key",
    ]:
        if key in clean:
            clean[key] = safe_token(clean.get(key, ""))
    return clean


def is_chat_ai_enabled(platform, channel, customer_id, business_id=None):
    try:
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)
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
    platform = normalize_id(platform).lower()
    channel = standard_channel(platform, channel)
    data = {
        "business_id": business_id,
        "platform": platform,
        "channel": channel or "",
        "customer_id": str(customer_id),
        "ai_enabled": bool(enabled),
    }
    return supabase.table("chat_ai_settings").upsert(
        data,
        on_conflict="business_id,platform,channel,customer_id",
    ).execute()


def mark_conversation_read_in_db(conversation_id: str):
    parts = conversation_id.split("::")
    if len(parts) != 4:
        raise ValueError("Invalid conversation ID")

    platform, business_id, channel, customer_id = parts
    platform = normalize_id(platform).lower()
    channel = standard_channel(platform, channel)

    query = (
        supabase.table("inbox_messages")
        .update({"is_read": True})
        .eq("platform", platform)
        .eq("business_id", business_id)
        .eq("customer_id", str(customer_id))
        .eq("direction", "inbound")
    )

    if channel:
        query = query.eq("channel", channel)

    return query.execute()


def save_inbox_message(
        business: dict,
        platform: str,
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
        channel: str = "",
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        whatsapp_media_id: Optional[str] = None,
):
    try:
        customer_id = sender_id if direction == "inbound" else recipient_id

        data = {
            "business_id": business.get("id") if business else None,
            "instagram_business_id": business.get("instagram_business_id") if business else None,
            "platform": platform,
            "customer_id": normalize_id(customer_id),
            "customer_name": customer_name or normalize_id(customer_id),
            "channel": standard_channel(platform, channel),
            "direction": direction,
            "role": "user" if direction == "inbound" else "assistant",
            "content": message_text or "",
            "external_message_id": platform_message_id,
            "raw_payload": raw_payload or {},
            "is_read": is_read if direction == "inbound" else True,
            "media_type": media_type,
            "media_url": media_url,
            "file_name": file_name,
            "mime_type": mime_type,
            "whatsapp_media_id": whatsapp_media_id,
        }

        try:
            supabase.table("inbox_messages").insert(data).execute()
        except Exception:
            for optional_key in ["customer_name", "is_read", "media_type", "media_url", "file_name", "mime_type",
                                 "whatsapp_media_id"]:
                data.pop(optional_key, None)
            supabase.table("inbox_messages").insert(data).execute()

    except Exception as e:
        log("Could not save inbox message", str(e))


def get_message_count(platform=None):
    try:
        q = supabase.table("inbox_messages").select("id", count="exact")
        if platform:
            q = q.eq("platform", platform)
        result = q.execute()
        return result.count or 0
    except Exception:
        return 0


# ============================================================================
# AI
# ============================================================================
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


DEFAULT_AI_PROMPT_SETTINGS = {
    "global_prompt": """
You are a real human sales assistant for this business.
Sound like a real Uzbek seller on Instagram, Telegram, or WhatsApp, not customer support software.
Represent the company clearly, answer in the customer's language, and guide the customer toward the next useful buying step.
Keep replies short, warm, practical, and human. Ask one question at a time.
Do not sound corporate, do not over-explain, and do not repeat the product name in every message.
""".strip(),
    "instagram_prompt": """
Instagram rules:
- Keep DMs concise and natural.
- If customer asks for catalog, prices, models, photos, or collection, mention that catalog can be opened using the button.
- Do not paste raw catalog links in Instagram replies.
- For comments, invite the customer to DM when details are needed.
""".strip(),
    "telegram_prompt": """
Telegram rules:
- Sound like a natural Telegram sales manager.
- In groups, answer only when mentioned or replied to.
- Avoid long lists unless the customer asks for a list.
- Share Telegram catalog/group links only when relevant.
""".strip(),
    "whatsapp_prompt": """
WhatsApp rules:
- Be concise and direct.
- Reply naturally in 1-3 short sentences.
- Ask one follow-up question when it helps move the sale forward.
""".strip(),
    "opening_message": """
Assalomu alaykum 😊 Qanday yordam kerak?
""".strip(),
    "lead_collection_rules": """
Do not ask for name, phone, address, or full details at the beginning.
First answer naturally and understand what the customer wants.
Ask only one small follow-up question at a time.
Ask for phone/address only after the customer is clearly ready to order.
""".strip(),
    "sales_rules": """
- Answer the exact question first.
- Ask only one follow-up question at a time.
- Keep replies short and comfortable: usually 1-3 short sentences.
- Do not ask for phone number or address at the beginning.
- Do not repeat product names every message.
- Do not over-focus on only the product the customer first mentioned if they are still choosing.
- Avoid corporate phrases like "manager will contact you" unless the customer asks for a human or is ready to order.
- Do not overload the customer with all business information at once.
- Do not repeat the same request or paragraph.
- If the customer is annoyed, says the bot is bad, or asks to stop, reply very briefly and do not sell.
- Focus on helping the customer choose and buy.
""".strip(),
    "handoff_rules": """
If an important buying detail is missing, ask one simple follow-up question instead of saying a manager will clarify.
Only mention a manager when the customer asks for a human, is ready to order, or the exact detail really requires confirmation.
Do not invent information.
Escalate when the customer is frustrated, ready to buy, or asks for a human.
""".strip(),
}


AI_PROMPT_SETTING_FIELDS = set(DEFAULT_AI_PROMPT_SETTINGS.keys())


def clean_ai_prompt_settings(settings: dict) -> dict:
    return {
        key: str(value or "").strip()
        for key, value in (settings or {}).items()
        if key in AI_PROMPT_SETTING_FIELDS
    }


def get_ai_prompt_settings(business_id: str) -> dict:
    business_id = normalize_id(business_id)
    settings = dict(DEFAULT_AI_PROMPT_SETTINGS)

    if not business_id:
        return settings

    try:
        rows = (
            supabase.table("ai_prompt_settings")
            .select("*")
            .eq("business_id", business_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows:
            for key in AI_PROMPT_SETTING_FIELDS:
                if rows[0].get(key) not in (None, ""):
                    settings[key] = rows[0].get(key)
            settings["id"] = rows[0].get("id")
            settings["business_id"] = business_id
    except Exception as e:
        log("Could not load AI prompt settings", str(e))

    settings.setdefault("business_id", business_id)
    return settings


def upsert_ai_prompt_settings(business_id: str, settings: dict) -> dict:
    business_id = normalize_id(business_id)
    if not business_id:
        raise ValueError("Missing business_id")

    cleaned = clean_ai_prompt_settings(settings)
    if not cleaned:
        return get_ai_prompt_settings(business_id)

    payload = {
        "business_id": business_id,
        **cleaned,
        "updated_at": datetime.utcnow().isoformat(),
    }
    supabase.table("ai_prompt_settings").upsert(
        payload,
        on_conflict="business_id",
    ).execute()
    return get_ai_prompt_settings(business_id)


PROMPT_FIELD_LABELS = {
    "global_prompt": "global prompt",
    "instagram_prompt": "Instagram rules",
    "telegram_prompt": "Telegram rules",
    "whatsapp_prompt": "WhatsApp rules",
    "opening_message": "opening message",
    "lead_collection_rules": "lead collection rules",
    "sales_rules": "sales rules",
    "handoff_rules": "human handoff rules",
}


def fallback_prompt_suggestion(field: str, current_prompt: str = "", goal: str = "") -> dict:
    label = PROMPT_FIELD_LABELS.get(field, "prompt")
    current_words = re.findall(r"[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʼ']{4,}", current_prompt or "")
    product_hint = current_words[0] if current_words else "customer request"

    if field == "opening_message":
        return {
            "suggested_prompt": "Assalomu alaykum 😊 Qanday yordam kerak?",
            "explanation": "Made the opening short and natural, without asking for phone or address too early.",
        }

    suggested_prompt = "\n".join([
        f"{label.title()}:",
        "- Reply shortly, warmly, and naturally in the customer's language.",
        "- First answer the customer's question, then ask only one simple follow-up question.",
        "- Do not ask for phone number or address at the beginning.",
        "- Ask for phone/address only when the customer is clearly ready to order.",
        f"- Do not repeat {product_hint!r} or any product name in every message.",
        "- Never invent price, stock, delivery time, discounts, or availability.",
        "- Avoid corporate phrases like 'manager will contact you' unless the customer asks for a human or is ready to order.",
        "- If the customer is annoyed, reply calmly and briefly before continuing.",
        f"- Main improvement goal: {goal}." if goal else "",
    ]).strip()

    return {
        "suggested_prompt": suggested_prompt,
        "explanation": "Made it shorter, clearer, safer for sales replies, and aligned with Instaagent standards.",
    }


def generate_ai_prompt_suggestion(business: dict, field: str, current_prompt: str, goal: str) -> dict:
    field = normalize_id(field)
    if field not in AI_PROMPT_SETTING_FIELDS:
        raise ValueError("Invalid prompt field")

    fallback = fallback_prompt_suggestion(field, current_prompt, goal)
    business_for_generation = {
        **business,
        "ai_temperature": 0.35,
        "ai_max_tokens": max(450, int(business.get("ai_max_tokens", 130) or 130)),
    }

    messages = [
        {
            "role": "system",
            "content": """
You are Instaagent's prompt generator for non-technical business agents.
Rewrite weak sales-bot instructions into a professional prompt section.

Always follow Instaagent standards:
- short natural replies
- same language as customer
- one question at a time
- no repeated product names
- no phone/address at beginning
- no invented price, stock, delivery, discount, address, or availability
- no corporate language like "manager will contact you" unless truly needed
- handle angry customers calmly
- good for Instagram, Telegram, and WhatsApp

Return only the improved prompt text. Do not include markdown fences or explanations.
""".strip(),
        },
        {
            "role": "user",
            "content": f"""
Business name: {business.get("business_name", "")}
Prompt field: {PROMPT_FIELD_LABELS.get(field, field)}
Agent goal: {goal}

Current prompt:
{current_prompt or "(empty)"}

Write a better prompt section that a sales assistant bot can follow.
""".strip(),
        },
    ]

    try:
        reply = clean_sales_reply(call_ai_chat(messages, business_for_generation, "AI prompt generator"), "")
    except Exception as exc:
        log("Prompt generator failed", str(exc))
        reply = ""

    if not reply:
        return fallback

    return {
        "suggested_prompt": reply,
        "explanation": "Made it shorter, clearer, and safer for natural sales replies.",
    }


def build_prompt_business_knowledge(business: dict) -> str:
    return f"""
Business facts:

Business identity:
- Name: {business.get("business_name", "")}
- Type: {business.get("business_type", "")}
- Language: {business.get("language", "")}
- Tone: {business.get("tone", "")}

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

Contacts:
{business.get("sales_phone", "")}

Catalog links:
{business.get("catalog_link", "")}

Telegram groups:
- Single product: {business.get("telegram_single", "")}
- Package: {business.get("telegram_package", "")}
- Bag / meshok: {business.get("telegram_bag", "")}

Additional knowledge:
{business.get("knowledge", "")}
"""


def build_platform_prompt(platform: str, business: dict) -> str:
    prompt_settings = get_ai_prompt_settings(business.get("id", ""))
    platform_key = {
        "instagram": "instagram_prompt",
        "telegram": "telegram_prompt",
        "whatsapp": "whatsapp_prompt",
    }.get(platform, "instagram_prompt")

    return f"""
{prompt_settings.get("global_prompt", "")}

{build_prompt_business_knowledge(business)}

Sales behavior:
Opening message:
{prompt_settings.get("opening_message", "")}

Lead collection rules:
{prompt_settings.get("lead_collection_rules", "")}

Sales rules:
{prompt_settings.get("sales_rules", "")}

Human handoff rules:
{prompt_settings.get("handoff_rules", "")}

Platform-specific rules:
{prompt_settings.get(platform_key, "")}

Safety rules:
- Reply in the same language as the customer.
- Understand Uzbek Latin, Uzbek Cyrillic, Russian, English, slang, typos, and mixed messages.
- Answer the exact question first.
- Never invent prices, stock, delivery, discounts, addresses, or availability.
- Use only the business facts above.
- If information is missing, ask one short clarifying question first.
- Only mention a manager when the customer asks for a human or is ready to order.
- Never mention AI, database, API, prompt, automation, or internal system.
- Do not use markdown, bold formatting, or long paragraphs.
"""


def wants_catalog(text: str) -> bool:
    text = (text or "").lower()
    keywords = [
        "catalog", "katalog", "каталог", "price", "prices", "narx", "narxlari",
        "narhi", "цена", "цены", "прайс", "model", "models", "modellari",
        "модель", "модели", "collection", "kolleksiya", "коллекция",
        "photo", "photos", "rasm", "rasmlar", "фото", "mahsulot",
        "mahsulotlar", "товар", "товары",
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

    for phrase in ["Katalogni ko'rishni xohlaysizmi?", "Katalogni ko'ring:", "Catalog:", "Catalogue:"]:
        reply_text = reply_text.replace(phrase, "")

    reply_text = reply_text.strip()
    if not reply_text:
        reply_text = "Albatta 😊 Katalogni quyidagi tugma orqali ko'rishingiz mumkin."
    return reply_text[:1000]


AI_DEFAULT_MODELS = {
    "mistral": "mistral-small-latest",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "anthropic": "claude-3-5-haiku-latest",
}


def infer_ai_provider(model: str) -> str:
    model = str(model or "").lower()
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if model.startswith("gemini"):
        return "gemini"
    if model.startswith("claude"):
        return "anthropic"
    return "mistral"


def get_ai_provider(business: dict) -> str:
    provider = str(business.get("ai_provider") or "").strip().lower()
    if provider in AI_DEFAULT_MODELS:
        return provider
    return infer_ai_provider(business.get("ai_model"))


def get_ai_api_key(business: dict, provider: str) -> str:
    if provider == "openai":
        return business.get("openai_api_key") or OPENAI_API_KEY
    if provider == "gemini":
        return business.get("gemini_api_key") or GEMINI_API_KEY
    if provider == "anthropic":
        return business.get("anthropic_api_key") or ANTHROPIC_API_KEY
    return business.get("mistral_api_key") or MISTRAL_API_KEY or ""


def build_sales_system_prompt(business: dict, platform: str = "instagram") -> str:
    return build_platform_prompt(platform, business)


def call_ai_chat(messages: list, business: dict, log_label: str) -> str:
    provider = get_ai_provider(business)
    model = business.get("ai_model") or AI_DEFAULT_MODELS[provider]
    api_key = get_ai_api_key(business, provider)
    temperature = float(business.get("ai_temperature", 0.5) or 0.5)
    max_tokens = int(business.get("ai_max_tokens", 130) or 130)

    if not api_key:
        log("Missing AI API key", {"provider": provider, "model": model})
        return ""

    if provider in {"mistral", "openai"}:
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"

        res = requests.post(
            url,
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        log(log_label, {"provider": provider, "model": model, "status": res.status_code, "body": res.text[:1000]})
        if not res.ok:
            return ""
        return (
            res.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

    if provider == "gemini":
        system_text = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
        contents = [
            {
                "role": "model" if m.get("role") == "assistant" else "user",
                "parts": [{"text": m.get("content", "")}],
            }
            for m in messages
            if m.get("role") != "system" and m.get("content")
        ]
        res = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json={
                "systemInstruction": {"parts": [{"text": system_text}]},
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            },
            timeout=30,
        )
        log(log_label, {"provider": provider, "model": model, "status": res.status_code, "body": res.text[:1000]})
        if not res.ok:
            return ""
        parts = (
            res.json()
            .get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        return "\n".join(part.get("text", "") for part in parts).strip()

    if provider == "anthropic":
        system_text = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
        anthropic_messages = [
            {
                "role": "assistant" if m.get("role") == "assistant" else "user",
                "content": m.get("content", ""),
            }
            for m in messages
            if m.get("role") != "system" and m.get("content")
        ]
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "system": system_text,
                "messages": anthropic_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        log(log_label, {"provider": provider, "model": model, "status": res.status_code, "body": res.text[:1000]})
        if not res.ok:
            return ""
        return "\n".join(
            block.get("text", "")
            for block in res.json().get("content", [])
            if block.get("type") == "text"
        ).strip()

    return ""



def clean_sales_reply(reply_text: str, user_text: str = "") -> str:
    user = normalize_id(user_text).lower()

    if any(phrase in user for phrase in [
        "meni haqimda hamma ma'lumotni unut",
        "meni haqimda hamma malumotni unut",
        "men haqimda hamma ma'lumotni unut",
        "men haqimda hamma malumotni unut",
        "hamma ma'lumotni unut",
        "hamma malumotni unut",
        "forget everything about me",
        "delete my data",
    ]):
        return "Albatta 👍"

    if any(phrase in user for phrase in [
        "botinglar yoqmadi",
        "bot yoqmadi",
        "yoqmadi",
        "stop",
        "bas",
        "kerakmas",
        "kerak emas",
    ]):
        return "Tushundim 👍 Oddiyroq va qisqa javob beraman."

    text = normalize_id(reply_text)
    if not text:
        return "Xabaringiz qabul qilindi 😊"

    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"^[\-•]+\s*", "", text, flags=re.MULTILINE)

    parts = []
    seen = set()
    for part in re.split(r"\n\s*\n|\n", text):
        clean = re.sub(r"\s+", " ", part).strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(clean)

    text = "\n".join(parts).strip()

    noisy_phrases = [
        "menedjerimiz siz bilan bog'lanib",
        "menejerimiz siz bilan bog'lanib",
        "vakilimiz tez orada siz bilan bog‘lanadi",
        "vakilimiz tez orada siz bilan bog'lanadi",
    ]
    for phrase in noisy_phrases:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)

    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) > 500:
        text = text[:500].rsplit(" ", 1)[0].strip()

    return text or "Tushunarli 👍"


def get_recent_platform_chat_history(platform: str, business: dict, customer_id: str = "", channel: str = "", limit: int = 10) -> list:
    if not customer_id:
        return []

    try:
        query = (
            supabase.table("inbox_messages")
            .select("role,content")
            .eq("platform", platform)
            .eq("customer_id", normalize_id(customer_id))
        )

        if business and business.get("id"):
            query = query.eq("business_id", business.get("id"))

        if channel:
            query = query.eq("channel", channel)

        rows = query.order("created_at", desc=True).limit(limit).execute().data or []
        rows = list(reversed(rows))
        return [
            {"role": row.get("role") or "user", "content": row.get("content") or ""}
            for row in rows
            if row.get("content")
        ]
    except Exception as e:
        log("Could not load recent chat history", str(e))
        return []

def get_ai_reply(user_text: str, business: dict, platform: str = "instagram", customer_id: str = "", channel: str = ""):
    try:
        messages = [{"role": "system", "content": build_sales_system_prompt(business, platform)}]
        messages.extend(get_recent_platform_chat_history(platform, business, customer_id, channel, limit=10))
        messages.append({"role": "user", "content": user_text})

        reply = call_ai_chat(
            messages,
            business,
            "AI response",
        )
        return clean_sales_reply(reply.strip(), user_text) if reply else "Xabaringiz qabul qilindi 😊"

    except Exception as e:
        log("AI error", str(e))
        return "Xabaringiz qabul qilindi 😊"


# ============================================================================
# INSTAGRAM
# ============================================================================
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
    log("Instagram send result", {"url": url, "status": res.status_code, "body": res.text})
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
    res = send_dm(access_token, recipient_id, text, business)
    if res is None:
        return False, {"error": "Send failed"}
    return res.ok, safe_json(res)


def send_instagram_media(access_token: str, recipient_id: str, media_type: str, media_url: str, caption: str = "",
                         business: dict = None):
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
    log("Comment reply result", {"status": res.status_code, "body": res.text})
    return res


async def process_instagram_messaging_event(entry_id: str, messaging: dict):
    log("Processing Instagram messaging event", messaging)

    if "read" in messaging or "delivery" in messaging:
        return

    message = messaging.get("message") or {}
    if not message:
        return

    sender_id = normalize_id(messaging.get("sender", {}).get("id"))
    recipient_id = normalize_id(messaging.get("recipient", {}).get("id"))
    message_text = message.get("text") or ""
    message_id = normalize_id(message.get("mid") or str(messaging.get("timestamp") or ""))
    is_echo = bool(message.get("is_echo"))

    if is_echo:
        return

    media_type = None
    media_url = None

    attachments = message.get("attachments", [])
    if attachments:
        att = attachments[0]
        att_type = att.get("type", "")
        att_url = (att.get("payload") or {}).get("url", "")

        if att_type == "image":
            media_type = "photo"
            media_url = att_url
            message_text = message_text or "📸 Photo"
        elif att_type == "video":
            media_type = "video"
            media_url = att_url
            message_text = message_text or "🎥 Video"
        elif att_type == "audio":
            media_type = "audio"
            media_url = att_url
            message_text = message_text or "🎤 Audio"
        elif att_type == "file":
            media_type = "file"
            media_url = att_url
            message_text = message_text or "📎 File"

    if not sender_id or not recipient_id:
        return

    if not message_text and not media_type:
        return

    if is_processed(processed_message_ids, message_id):
        return

    if message_id in processing_message_ids:
        return

    processing_message_ids.add(message_id)

    try:
        business = find_business_for_webhook(entry_id, recipient_id)
        if not business:
            return

        save_inbox_message(
            business=business,
            platform="instagram",
            sender_id=sender_id,
            recipient_id=recipient_id,
            message_text=message_text,
            direction="inbound",
            platform_message_id=message_id,
            raw_payload=messaging,
            is_read=False,
            media_type=media_type,
            media_url=media_url,
            channel="dm",
        )

        if not business.get("bot_enabled", True):
            mark_processed(processed_message_ids, message_id)
            return

        if business.get("auto_reply_dms") is False:
            mark_processed(processed_message_ids, message_id)
            return

        if not is_chat_ai_enabled("instagram", "dm", sender_id, business.get("id")):
            mark_processed(processed_message_ids, message_id)
            return

        access_token = get_business_access_token(business)
        if not access_token:
            return

        reply_text = get_ai_reply(message_text or "Photo/Video received", business, "instagram", sender_id, "dm")

        should_send_catalog = wants_catalog(message_text) and bool(get_catalog_link(business))
        if should_send_catalog:
            send_result = send_catalog_button(access_token, sender_id, business, reply_text)
            saved_reply_text = clean_ai_reply_for_catalog(reply_text, business) + "\n[Catalog button sent]"
        else:
            reply_text = remove_urls(reply_text)
            send_result = send_dm(access_token, sender_id, reply_text, business)
            saved_reply_text = reply_text

        raw_result = safe_json(send_result) if send_result is not None else {}

        if send_result is not None and send_result.ok:
            save_inbox_message(
                business=business,
                platform="instagram",
                sender_id=recipient_id,
                recipient_id=sender_id,
                message_text=saved_reply_text,
                direction="outbound",
                platform_message_id=raw_result.get("message_id", ""),
                raw_payload=raw_result,
                is_read=True,
                channel="dm",
            )
            mark_processed(processed_message_ids, message_id)

    except Exception as e:
        log("Instagram DM processing error", str(e))
    finally:
        processing_message_ids.discard(message_id)


async def process_instagram_comment_event(entry_id: str, change: dict):
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

    reply_text = get_ai_reply(comment_text, business, "instagram", "", "comment")
    reply_text = remove_urls(reply_text)

    if wants_catalog(comment_text):
        reply_text = "Katalogni DM orqali yuboramiz 😊 Iltimos, bizga xabar yozing."

    reply_to_comment(access_token, comment_id, reply_text, business)


# ============================================================================
# WHATSAPP
# ============================================================================
def get_whatsapp_access_token(business: dict = None):
    if business:
        return business.get("whatsapp_access_token") or WHATSAPP_ACCESS_TOKEN
    return WHATSAPP_ACCESS_TOKEN


def get_whatsapp_phone_number_id(business: dict = None):
    if business:
        return business.get("whatsapp_phone_number_id") or WHATSAPP_PHONE_NUMBER_ID
    return WHATSAPP_PHONE_NUMBER_ID


def send_whatsapp_text(to: str, text: str, business: dict = None):
    token = get_whatsapp_access_token(business)
    phone_number_id = get_whatsapp_phone_number_id(business)

    if not token or not phone_number_id:
        return None

    url = f"{GRAPH_FACEBOOK}/{phone_number_id}/messages"

    res = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "to": normalize_id(to),
            "type": "text",
            "text": {"body": text[:4000]},
        },
        timeout=30,
    )

    log("WhatsApp send text", {"status": res.status_code, "body": res.text})
    return res


def send_whatsapp_image_upload(to: str, file_bytes: bytes, filename: str, mime_type: str, caption: str = "",
                               business: dict = None):
    token = get_whatsapp_access_token(business)
    phone_number_id = get_whatsapp_phone_number_id(business)

    if not token or not phone_number_id:
        return False, {"error": "Missing WhatsApp access token or phone number id"}, ""

    upload_res = requests.post(
        f"{GRAPH_FACEBOOK}/{phone_number_id}/media",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "messaging_product": "whatsapp",
            "type": mime_type or "image/jpeg",
        },
        files={"file": (filename or "image.jpg", file_bytes, mime_type or "image/jpeg")},
        timeout=60,
    )

    upload_result = safe_json(upload_res)
    log("WhatsApp media upload", {"status": upload_res.status_code, "body": upload_result})

    if not upload_res.ok:
        return False, upload_result, ""

    media_id = upload_result.get("id", "")
    if not media_id:
        return False, {"error": "WhatsApp media upload returned no media id", "meta": upload_result}, ""

    send_res = requests.post(
        f"{GRAPH_FACEBOOK}/{phone_number_id}/messages",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "to": normalize_id(to),
            "type": "image",
            "image": {
                "id": media_id,
                **({"caption": caption[:1024]} if caption else {}),
            },
        },
        timeout=30,
    )

    send_result = safe_json(send_res)
    log("WhatsApp image send", {"status": send_res.status_code, "body": send_result})
    return send_res.ok, send_result, media_id


def send_whatsapp_audio_upload(to: str, file_bytes: bytes, filename: str, mime_type: str, business: dict = None):
    token = get_whatsapp_access_token(business)
    phone_number_id = get_whatsapp_phone_number_id(business)

    if not token or not phone_number_id:
        return False, {"error": "Missing WhatsApp access token or phone number id"}, ""

    upload_res = requests.post(
        f"{GRAPH_FACEBOOK}/{phone_number_id}/media",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "messaging_product": "whatsapp",
            "type": mime_type or "audio/ogg",
        },
        files={"file": (filename or "voice.ogg", file_bytes, mime_type or "audio/ogg")},
        timeout=60,
    )

    upload_result = safe_json(upload_res)
    log("WhatsApp audio upload", {"status": upload_res.status_code, "body": upload_result})

    if not upload_res.ok:
        return False, upload_result, ""

    media_id = upload_result.get("id", "")
    if not media_id:
        return False, {"error": "WhatsApp audio upload returned no media id", "meta": upload_result}, ""

    send_res = requests.post(
        f"{GRAPH_FACEBOOK}/{phone_number_id}/messages",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "to": normalize_id(to),
            "type": "audio",
            "audio": {"id": media_id},
        },
        timeout=30,
    )

    send_result = safe_json(send_res)
    log("WhatsApp audio send", {"status": send_res.status_code, "body": send_result})
    return send_res.ok, send_result, media_id


def send_telegram_bot_photo_upload(chat_id: str, file_bytes: bytes, filename: str, mime_type: str, caption: str = ""):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    if not token:
        return None

    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1024]

    return requests.post(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=data,
        files={"photo": (filename or "image.jpg", file_bytes, mime_type or "image/jpeg")},
        timeout=60,
    )


def send_telegram_bot_voice_upload(chat_id: str, file_bytes: bytes, filename: str, mime_type: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    if not token:
        return None

    return requests.post(
        f"https://api.telegram.org/bot{token}/sendVoice",
        data={"chat_id": chat_id},
        files={"voice": (filename or "voice.ogg", file_bytes, mime_type or "audio/ogg")},
        timeout=60,
    )


def get_whatsapp_media_proxy_url(media_id: str):
    return f"{PUBLIC_BASE_URL}/api/whatsapp/media/{media_id}"


def cleanup_whatsapp_chat_memory(ttl_seconds: int = 24 * 60 * 60):
    now = time.time()
    expired = [
        phone
        for phone, data in WHATSAPP_CHAT_MEMORY.items()
        if now - float((data or {}).get("last_seen", 0)) > ttl_seconds
    ]
    for phone in expired:
        WHATSAPP_CHAT_MEMORY.pop(phone, None)


def get_whatsapp_chat(phone: str):
    phone = normalize_id(phone)
    cleanup_whatsapp_chat_memory()

    if phone not in WHATSAPP_CHAT_MEMORY:
        WHATSAPP_CHAT_MEMORY[phone] = {
            "intro_sent": False,
            "messages": [],
            "last_seen": time.time(),
        }

    WHATSAPP_CHAT_MEMORY[phone]["last_seen"] = time.time()
    return WHATSAPP_CHAT_MEMORY[phone]


def add_whatsapp_memory(phone: str, role: str, content: str, limit: int = 12):
    if not content:
        return
    chat = get_whatsapp_chat(phone)
    chat["messages"].append({"role": role, "content": content})
    chat["messages"] = chat["messages"][-limit:]


def first_whatsapp_intro_message(business: dict = None):
    settings = get_ai_prompt_settings((business or {}).get("id", ""))
    return settings.get("opening_message") or (
        "Assalomu alaykum. Men Milana Premium virtual assistentiman.\n\n"
        "Sizga tezroq yordam berishimiz uchun ism, telefon raqam, manzil, qaysi mahsulot kerakligi va miqdorini qoldiring.\n\n"
        "Vakilimiz tez orada siz bilan bog'lanadi."
    )


def build_whatsapp_system_prompt(business: dict, intro_sent: bool):
    prompt = build_platform_prompt("whatsapp", business)
    return f"""
{prompt}

WhatsApp opening state:
- intro_sent = {str(bool(intro_sent)).lower()}.
- If intro_sent is false, use the configured opening message and lead collection rules.
- If intro_sent is true, do not repeat the opening information request unless the customer asks.

Fallback catalog link:
{get_catalog_link(business) or WHATSAPP_CATALOG_LINK}
"""


def get_whatsapp_ai_reply(phone: str, user_text: str, business: dict) -> str:
    chat = get_whatsapp_chat(phone)

    if not chat.get("intro_sent"):
        chat["intro_sent"] = True
        intro = first_whatsapp_intro_message(business)
        add_whatsapp_memory(phone, "assistant", intro)
        return intro

    messages = [{"role": "system", "content": build_whatsapp_system_prompt(business, True)}]
    messages.extend(chat.get("messages", []))
    messages.append({"role": "user", "content": user_text})

    try:
        business_with_fallback_model = dict(business or {})
        business_with_fallback_model.setdefault("ai_model", WHATSAPP_MISTRAL_MODEL)
        reply = call_ai_chat(messages, business_with_fallback_model, "WhatsApp AI response")
        if reply:
            return clean_sales_reply(reply[:1500], user_text)
        return "Xabaringiz qabul qilindi 😊 Qanday yordam kerak?"
    except Exception as e:
        log("WhatsApp AI error", str(e))
        return "Xabaringiz qabul qilindi 😊 Qanday yordam kerak?"


async def process_whatsapp_message(change: dict):
    value = change.get("value", {})
    messages = value.get("messages", []) or []
    contacts = value.get("contacts", []) or []
    metadata = value.get("metadata", {}) or {}

    phone_number_id = normalize_id(metadata.get("phone_number_id") or WHATSAPP_PHONE_NUMBER_ID)

    business = get_business_by_whatsapp_phone_number_id(phone_number_id) or get_active_whatsapp_business()

    if not business:
        log("WhatsApp skipped: no business found", {"phone_number_id": phone_number_id})
        return

    customer_name = ""
    if contacts:
        customer_name = contacts[0].get("profile", {}).get("name", "") or ""

    for msg in messages:
        message_id = normalize_id(msg.get("id"))
        sender_id = normalize_id(msg.get("from"))
        msg_type = msg.get("type")

        if not message_id or not sender_id:
            continue

        if is_processed(processed_message_ids, message_id):
            continue

        if message_id in processing_message_ids:
            continue

        processing_message_ids.add(message_id)

        try:
            text = ""
            media_type = None
            media_url = None
            whatsapp_media_id = None
            mime_type = None
            file_name = None

            if msg_type == "text":
                text = msg.get("text", {}).get("body", "")

            elif msg_type in ["image", "video", "audio", "document", "sticker"]:
                media = msg.get(msg_type, {}) or {}
                whatsapp_media_id = media.get("id")
                mime_type = media.get("mime_type")
                file_name = media.get("filename")

                media_type = {
                    "image": "photo",
                    "video": "video",
                    "audio": "audio",
                    "document": "file",
                    "sticker": "photo",
                }.get(msg_type, "file")

                default_text = {
                    "image": "📸 Photo",
                    "video": "🎥 Video",
                    "audio": "🎤 Audio",
                    "document": "📎 Document",
                    "sticker": "🖼 Sticker",
                }.get(msg_type, "📎 File")

                text = media.get("caption") or default_text

                if whatsapp_media_id:
                    media_url = get_whatsapp_media_proxy_url(whatsapp_media_id)

            elif msg_type == "button":
                text = msg.get("button", {}).get("text", "")

            elif msg_type == "interactive":
                interactive = msg.get("interactive", {}) or {}
                if interactive.get("type") == "button_reply":
                    text = interactive.get("button_reply", {}).get("title", "")
                elif interactive.get("type") == "list_reply":
                    text = interactive.get("list_reply", {}).get("title", "")
                else:
                    text = "Interactive message"

            else:
                text = f"Unsupported WhatsApp message type: {msg_type}"

            save_inbox_message(
                business=business,
                platform="whatsapp",
                sender_id=sender_id,
                recipient_id=phone_number_id,
                message_text=text,
                direction="inbound",
                platform_message_id=message_id,
                raw_payload=msg,
                customer_name=customer_name,
                is_read=False,
                media_type=media_type,
                media_url=media_url,
                channel="whatsapp",
                file_name=file_name,
                mime_type=mime_type,
                whatsapp_media_id=whatsapp_media_id,
            )

            if not business.get("bot_enabled", True):
                mark_processed(processed_message_ids, message_id)
                continue

            if not is_chat_ai_enabled("whatsapp", "whatsapp", sender_id, business.get("id")):
                mark_processed(processed_message_ids, message_id)
                continue

            add_whatsapp_memory(sender_id, "user", text or f"Customer sent {msg_type}")

            if msg_type == "text":
                reply_text = get_whatsapp_ai_reply(sender_id, text, business)
            elif media_type:
                reply_text = get_whatsapp_ai_reply(
                    sender_id,
                    text or "Customer sent a media message.",
                    business,
                )
            else:
                reply_text = get_whatsapp_ai_reply(sender_id, text, business)

            send_result = send_whatsapp_text(sender_id, reply_text, business)
            raw_result = safe_json(send_result) if send_result is not None else {}

            if send_result is not None and send_result.ok:
                add_whatsapp_memory(sender_id, "assistant", reply_text)
                save_inbox_message(
                    business=business,
                    platform="whatsapp",
                    sender_id=phone_number_id,
                    recipient_id=sender_id,
                    message_text=reply_text,
                    direction="outbound",
                    platform_message_id=raw_result.get("messages", [{}])[0].get("id", ""),
                    raw_payload=raw_result,
                    is_read=True,
                    channel="whatsapp",
                )
                mark_processed(processed_message_ids, message_id)
            else:
                log("WhatsApp reply failed; not marking processed", raw_result)

        except Exception as e:
            log("WhatsApp processing error", str(e))
        finally:
            processing_message_ids.discard(message_id)


# ============================================================================
# OAUTH
# ============================================================================
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
    return res.json().get("access_token") or short_lived_token


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
        return supabase.table("businesses").update(update_data).eq("id", existing["id"]).execute().data

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

    return supabase.table("businesses").upsert(insert_data, on_conflict="instagram_business_id").execute().data


# ============================================================================
# API ROUTES - HOME & HEALTH
# ============================================================================
@app.head("/")
async def head_home():
    return PlainTextResponse("", status_code=200)


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>InsaAgent</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
    </head>
    <body style="font-family: Arial; padding:40px;">
        <h1>InsaAgent</h1>
        <p>AI-powered Instagram, Telegram and WhatsApp automation platform for businesses.</p>
        <p>Status: Online</p>
        <p><a href="/privacy">Privacy Policy</a> | <a href="/terms">Terms</a></p>
    </body>
    </html>
    """


@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "version": "5.1.0-telegram-voice",
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }


# ============================================================================
# API ROUTES - V2 (REACT UI)
# ============================================================================

@app.get("/api/v2/conversations")
async def get_conversations_v2(
        platform: str = "all",
        search: str = "",
        x_dashboard_secret: str = Header(default=""),
):
    """Get all conversations in React UI format"""
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        query = supabase.table("inbox_messages").select("*").order("created_at", desc=True).limit(900)

        if platform != "all":
            query = query.eq("platform", platform)

        result = query.execute()
        rows = result.data or []

        conversations_map = {}
        for row in rows:
            business_id = row.get("business_id")
            platform_name = normalize_id(row.get("platform", "instagram")).lower() or "instagram"
            channel = standard_channel(platform_name, row.get("channel", ""))
            customer_id = str(row.get("customer_id") or "").strip()

            if not business_id or not customer_id:
                continue

            key = f"{platform_name}::{business_id}::{channel}::{customer_id}"

            if key not in conversations_map:
                conversations_map[key] = []

            conversations_map[key].append(row)

        conversations = []
        for key, conv_rows in conversations_map.items():
            conv = transform_conversation_to_react(key, sorted(conv_rows, key=lambda x: x.get('created_at', '')))
            if conv:
                conversations.append(conv)

        if search.strip():
            q = search.lower().strip()
            conversations = [
                c for c in conversations
                if q in f"{c['name']} {c['handle']} {c['preview']}".lower()
            ]

        return {
            'status': 'ok',
            'count': len(conversations),
            'data': conversations
        }

    except Exception as e:
        log("Error fetching conversations", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.get("/api/v2/conversation/{conversation_id}/messages")
async def get_conversation_messages_v2(
        conversation_id: str,
        limit: int = 250,
        x_dashboard_secret: str = Header(default=""),
):
    """Get all messages for a conversation"""
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse(
                {"error": "Invalid conversation ID format"},
                status_code=400
            )

        platform, business_id, channel, customer_id = parts
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)

        query = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", platform)
            .eq("business_id", business_id)
            .eq("customer_id", str(customer_id))
        )

        if channel:
            query = query.eq("channel", channel)

        result = query.order("created_at", desc=False).limit(limit).execute()
        rows = result.data or []

        messages = [transform_message_to_react(row) for row in rows]

        try:
            mark_query = (
                supabase.table("inbox_messages")
                .update({"is_read": True})
                .eq("platform", platform)
                .eq("business_id", business_id)
                .eq("customer_id", str(customer_id))
                .eq("direction", "inbound")
            )
            if channel:
                mark_query = mark_query.eq("channel", channel)
            mark_query.execute()
        except Exception:
            pass

        return {
            'status': 'ok',
            'count': len(messages),
            'data': messages
        }

    except Exception as e:
        log("Error fetching conversation messages", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.post("/api/v2/send-message")
async def send_message_v2(
        request: Request,
        x_dashboard_secret: str = Header(default=""),
):
    """Send a message via the React UI"""
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
        conversation_id = payload.get("conversation_id")
        text = payload.get("text", "").strip()

        if not conversation_id or not text:
            return JSONResponse(
                {"error": "Missing conversation_id or text"},
                status_code=400
            )

        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse(
                {"error": "Invalid conversation ID format"},
                status_code=400
            )

        platform, business_id, channel, customer_id = parts
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)

        business = get_business_by_id(business_id)
        if not business:
            return JSONResponse(
                {"error": "Business not found"},
                status_code=404
            )

        ok = False
        result = {}

        if platform == "instagram":
            access_token = get_business_access_token(business)
            if not access_token:
                return JSONResponse(
                    {"error": "Instagram access token not configured"},
                    status_code=400
                )

            ok, result = send_instagram_dm(access_token, customer_id, text, business)

        elif platform == "telegram":
            if channel == "telegram_user_private":
                ok, result = await send_telegram_user_message(customer_id=customer_id, text=text)
            else:
                res = send_telegram_bot_message(customer_id, text)
                if res:
                    ok = res.ok
                    result = safe_json(res)
                else:
                    result = {"error": "Send failed"}

        elif platform == "whatsapp":
            res = send_whatsapp_text(customer_id, text, business)
            if res:
                ok = res.ok
                try:
                    result = res.json()
                except Exception:
                    result = {"text": res.text}
            else:
                result = {"error": "Send failed"}

        else:
            return JSONResponse(
                {"error": "Unknown platform"},
                status_code=400
            )

        if not ok:
            log("Message send failed", result)
            return send_failure_response(result)

        save_inbox_message(
            business=business,
            platform=platform,
            sender_id=business_id,
            recipient_id=customer_id,
            message_text=text,
            direction="outbound",
            platform_message_id=result.get("message_id") or result.get("messages", [{}])[0].get("id", ""),
            raw_payload=result,
            channel=channel,
        )

        return {'status': 'ok', 'data': result}

    except Exception as e:
        log("Error sending message", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.post("/api/v2/conversation/{conversation_id}/ai-toggle")
async def toggle_ai_v2(
        conversation_id: str,
        request: Request,
        x_dashboard_secret: str = Header(default=""),
):
    """Toggle AI for a specific conversation"""
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse(
                {"error": "Invalid conversation ID format"},
                status_code=400
            )

        platform, business_id, channel, customer_id = parts
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)

        payload = await request.json()
        enabled = payload.get("enabled", True)

        set_chat_ai_enabled(
            business_id=business_id,
            platform=platform,
            channel=channel or "",
            customer_id=customer_id,
            enabled=bool(enabled)
        )

        return {
            'status': 'ok',
            'conversation_id': conversation_id,
            'ai_enabled': enabled
        }

    except Exception as e:
        log("Error toggling AI", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.delete("/api/v2/conversation/{conversation_id}")
async def delete_conversation_v2(
        conversation_id: str,
        x_dashboard_secret: str = Header(default=""),
):
    """Delete a dashboard conversation from inbox_messages only."""
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse(
                {"error": "Invalid conversation ID format"},
                status_code=400
            )

        platform, business_id, channel, customer_id = parts
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)

        query = (
            supabase.table("inbox_messages")
            .delete()
            .eq("platform", platform)
            .eq("business_id", business_id)
            .eq("customer_id", str(customer_id))
        )

        if channel:
            query = query.eq("channel", channel)

        result = query.execute()
        deleted = len(result.data or [])

        return {
            "status": "ok",
            "conversation_id": conversation_id,
            "deleted_messages": deleted,
            "note": "Deleted from dashboard database only.",
        }

    except Exception as e:
        log("Error deleting conversation", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.get("/api/v2/conversation/{conversation_id}")
async def get_conversation_details_v2(
        conversation_id: str,
        x_dashboard_secret: str = Header(default=""),
):
    """Get full conversation details"""
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse(
                {"error": "Invalid conversation ID format"},
                status_code=400
            )

        platform, business_id, channel, customer_id = parts
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)

        business = get_business_by_id(business_id)

        query = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", platform)
            .eq("business_id", business_id)
            .eq("customer_id", str(customer_id))
        )

        if channel:
            query = query.eq("channel", channel)

        result = query.order("created_at", desc=False).execute()
        rows = result.data or []

        conv = transform_conversation_to_react(
            conversation_id,
            sorted(rows, key=lambda x: x.get('created_at', '')),
            business
        )

        if not conv:
            return JSONResponse(
                {"error": "Conversation not found"},
                status_code=404
            )

        conv['messages'] = [transform_message_to_react(row) for row in rows]

        return {
            'status': 'ok',
            'data': conv
        }

    except Exception as e:
        log("Error fetching conversation details", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.get("/api/v2/stats")
async def get_stats_v2(
        x_dashboard_secret: str = Header(default=""),
):
    """Get dashboard statistics"""
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        businesses = get_all_businesses()
        return {
            'status': 'ok',
            'data': {
                'total_messages': get_message_count(),
                'total_accounts': len(businesses),
                'active_accounts': sum(1 for b in businesses if b.get("bot_enabled")),
                'instagram_messages': get_message_count('instagram'),
                'telegram_messages': get_message_count('telegram'),
                'whatsapp_messages': get_message_count('whatsapp'),
                'active_conversations': 0,
                'needing_human': 0,
            }
        }

    except Exception as e:
        log("Error getting stats", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


# ============================================================================
# WEBHOOK ROUTES
# ============================================================================
@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    log("Webhook verification", {"mode": mode, "token": token, "challenge": challenge})

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(challenge, status_code=200)

    return PlainTextResponse("Verification failed", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()
        log("WEBHOOK RECEIVED", data)

        object_type = data.get("object")

        if object_type == "whatsapp_business_account":
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    if change.get("field") == "messages":
                        await process_whatsapp_message(change)
            return JSONResponse({"status": "ok"}, status_code=200)

        for entry in data.get("entry", []):
            entry_id = normalize_id(entry.get("id"))

            for messaging in entry.get("messaging", []):
                await process_instagram_messaging_event(entry_id, messaging)

            for change in entry.get("changes", []):
                field = change.get("field")

                if field in ["comments", "feed"]:
                    await process_instagram_comment_event(entry_id, change)
                elif field == "messages":
                    value = change.get("value", {})
                    fake_messaging = {
                        "sender": value.get("sender", {}),
                        "recipient": value.get("recipient", {}),
                        "timestamp": value.get("timestamp"),
                        "message": value.get("message", {}),
                    }
                    await process_instagram_messaging_event(entry_id, fake_messaging)

        return JSONResponse({"status": "ok"}, status_code=200)

    except Exception as e:
        log("Webhook error", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/whatsapp/media/{media_id}")
async def get_whatsapp_media(
        media_id: str,
        token: str = "",
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_media_secret(token, x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    token = WHATSAPP_ACCESS_TOKEN
    if not token:
        return JSONResponse({"error": "Missing WHATSAPP_ACCESS_TOKEN"}, status_code=400)

    meta_res = requests.get(
        f"{GRAPH_FACEBOOK}/{media_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )

    if not meta_res.ok:
        return JSONResponse({"error": meta_res.text}, status_code=meta_res.status_code)

    media_url = meta_res.json().get("url")
    if not media_url:
        return JSONResponse({"error": "No media URL returned"}, status_code=404)

    file_res = requests.get(
        media_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )

    if not file_res.ok:
        return JSONResponse({"error": file_res.text}, status_code=file_res.status_code)

    return Response(
        content=file_res.content,
        media_type=file_res.headers.get("Content-Type", "application/octet-stream"),
    )


# ============================================================================
# OAUTH ROUTES
# ============================================================================
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
    return PlainTextResponse("Facebook callback available.", status_code=200)


# ============================================================================
# DASHBOARD ROUTES (LEGACY + V2)
# ============================================================================
@app.post("/dashboard/send-whatsapp-message")
async def dashboard_send_whatsapp_message(
        payload: ManualWhatsAppReply,
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business = get_business_by_id(payload.business_id) if payload.business_id else get_active_whatsapp_business()
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    text = payload.text.strip()
    customer_id = normalize_id(payload.customer_id)

    if not text or not customer_id:
        return JSONResponse({"status": "error", "message": "Missing customer_id or text"}, status_code=400)

    res = send_whatsapp_text(customer_id, text, business)
    result = safe_json(res) if res is not None else {"error": "Send failed"}

    if res is None or not res.ok:
        return JSONResponse({"status": "error", "meta": result}, status_code=400)

    save_inbox_message(
        business=business,
        platform="whatsapp",
        sender_id=get_whatsapp_phone_number_id(business),
        recipient_id=customer_id,
        message_text=text,
        direction="outbound",
        platform_message_id=result.get("messages", [{}])[0].get("id", ""),
        raw_payload=result,
        is_read=True,
        channel="whatsapp",
    )

    return JSONResponse({"status": "ok", "meta": result}, status_code=200)


@app.post("/dashboard/send-telegram-user-message")
async def dashboard_send_telegram_user_message(
        payload: ManualTelegramMessage,
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business = get_business_by_id(payload.business_id) if payload.business_id else get_active_business()
    if not business:
        return JSONResponse({"status": "error", "message": "No active business"}, status_code=404)

    customer_id = normalize_id(payload.customer_id)
    text = (payload.text or "").strip()

    if not customer_id or not text:
        return JSONResponse({"status": "error", "message": "Missing customer_id or text"}, status_code=400)

    ok, result = await send_telegram_user_message(
        customer_id=customer_id,
        text=text,
    )

    if ok:
        save_telegram_message(
            business=business,
            customer_id=customer_id,
            text=text,
            direction="outbound",
            message_id=result.get("message_id", ""),
            raw_payload=result,
            channel="telegram_user_private",
            customer_name=result.get("customer_name", customer_id),
            chat_id=result.get("chat_id", payload.chat_id or customer_id),
        )

    return JSONResponse(
        {"status": "ok" if ok else "error", "meta": result},
        status_code=200 if ok else 400,
    )


@app.post("/dashboard/send-image-file")
async def dashboard_send_image_file(
        payload: DashboardImageFile,
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    if not str(payload.mime_type or "").startswith("image/"):
        return JSONResponse({"status": "error", "message": "Only image files are supported right now"}, status_code=400)

    try:
        file_bytes = decode_upload_data(payload.file_data)
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    business = get_business_by_id(payload.business_id) if payload.business_id else get_active_business()
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    customer_id = normalize_id(payload.customer_id)
    chat_id = normalize_id(payload.chat_id or payload.customer_id)
    caption = (payload.caption or "").strip()
    platform = normalize_id(payload.platform).lower()
    channel = normalize_id(payload.channel)

    if not customer_id:
        return JSONResponse({"status": "error", "message": "Missing customer_id"}, status_code=400)

    if platform == "telegram" and channel == "telegram_user_private":
        ok, result = await send_telegram_user_file(
            customer_id=customer_id,
            file_bytes=file_bytes,
            filename=payload.filename,
            caption=caption,
        )

        if ok:
            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=caption or "📸 Photo",
                direction="outbound",
                message_id=result.get("message_id", ""),
                raw_payload=result,
                channel="telegram_user_private",
                customer_name=result.get("customer_name", customer_id),
                chat_id=result.get("chat_id", chat_id),
                media_type="photo",
            )

        return JSONResponse({"status": "ok" if ok else "error", "meta": result}, status_code=200 if ok else 400)

    if platform == "telegram":
        res = send_telegram_bot_photo_upload(
            chat_id=chat_id,
            file_bytes=file_bytes,
            filename=payload.filename,
            mime_type=payload.mime_type,
            caption=caption,
        )
        result = safe_json(res) if res is not None else {"error": "Send failed — no bot token configured"}
        ok = res is not None and res.ok

        if ok:
            photos = result.get("result", {}).get("photo", []) if isinstance(result, dict) else []
            media_file_id = photos[-1].get("file_id", "") if photos else ""
            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=caption or "📸 Photo",
                direction="outbound",
                message_id=result.get("result", {}).get("message_id", ""),
                raw_payload=result,
                channel=channel or "telegram_bot_private",
                customer_name=customer_id,
                chat_id=chat_id,
                media_type="photo",
                media_file_id=media_file_id,
            )

        return JSONResponse({"status": "ok" if ok else "error", "meta": result}, status_code=200 if ok else 400)

    if platform == "whatsapp":
        ok, result, media_id = send_whatsapp_image_upload(
            to=customer_id,
            file_bytes=file_bytes,
            filename=payload.filename,
            mime_type=payload.mime_type,
            caption=caption,
            business=business,
        )

        if ok:
            save_inbox_message(
                business=business,
                platform="whatsapp",
                sender_id=get_whatsapp_phone_number_id(business),
                recipient_id=customer_id,
                message_text=caption or "📸 Photo",
                direction="outbound",
                platform_message_id=result.get("messages", [{}])[0].get("id", ""),
                raw_payload=result,
                is_read=True,
                media_type="photo",
                media_url=get_whatsapp_media_proxy_url(media_id) if media_id else None,
                channel=channel or "whatsapp",
                file_name=payload.filename,
                mime_type=payload.mime_type,
                whatsapp_media_id=media_id,
            )

        return JSONResponse({"status": "ok" if ok else "error", "meta": result}, status_code=200 if ok else 400)

    if platform == "instagram":
        return JSONResponse(
            {
                "status": "error",
                "message": "Instagram image uploads need public media hosting. Add Supabase Storage/S3, then send the public URL through Instagram DM.",
            },
            status_code=400,
        )

    return JSONResponse({"status": "error", "message": "Unknown platform"}, status_code=400)


@app.post("/dashboard/send-voice-file")
async def dashboard_send_voice_file(
        payload: DashboardVoiceFile,
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    if not str(payload.mime_type or "").startswith("audio/"):
        return JSONResponse({"status": "error", "message": "Only audio files are supported for voice notes"}, status_code=400)

    try:
        file_bytes = decode_upload_data(payload.file_data)
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    business = get_business_by_id(payload.business_id) if payload.business_id else get_active_business()
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    customer_id = normalize_id(payload.customer_id)
    chat_id = normalize_id(payload.chat_id or payload.customer_id)
    platform = normalize_id(payload.platform).lower()
    channel = normalize_id(payload.channel)

    if not customer_id:
        return JSONResponse({"status": "error", "message": "Missing customer_id"}, status_code=400)

    if platform == "telegram" and channel == "telegram_user_private":
        ok, result = await send_telegram_user_voice_file(
            customer_id=customer_id,
            file_bytes=file_bytes,
            filename=payload.filename,
        )

        if ok:
            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text="🎤 Voice message",
                direction="outbound",
                message_id=result.get("message_id", ""),
                raw_payload=result,
                channel="telegram_user_private",
                customer_name=result.get("customer_name", customer_id),
                chat_id=result.get("chat_id", chat_id),
                media_type="voice",
            )

        return JSONResponse({"status": "ok" if ok else "error", "meta": result}, status_code=200 if ok else 400)

    if platform == "telegram":
        res = send_telegram_bot_voice_upload(
            chat_id=chat_id,
            file_bytes=file_bytes,
            filename=payload.filename,
            mime_type=payload.mime_type,
        )
        result = safe_json(res) if res is not None else {"error": "Send failed — no bot token configured"}
        ok = res is not None and res.ok

        if ok:
            body = result.get("result", {}) if isinstance(result, dict) else {}
            media_file_id = (
                body.get("voice", {}).get("file_id")
                or body.get("audio", {}).get("file_id")
                or ""
            )
            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text="🎤 Voice message",
                direction="outbound",
                message_id=body.get("message_id", ""),
                raw_payload=result,
                channel=channel or "telegram_bot_private",
                customer_name=customer_id,
                chat_id=chat_id,
                media_type="voice",
                media_file_id=media_file_id,
            )

        return JSONResponse({"status": "ok" if ok else "error", "meta": result}, status_code=200 if ok else 400)

    if platform == "whatsapp":
        ok, result, media_id = send_whatsapp_audio_upload(
            to=customer_id,
            file_bytes=file_bytes,
            filename=payload.filename,
            mime_type=payload.mime_type,
            business=business,
        )

        if ok:
            save_inbox_message(
                business=business,
                platform="whatsapp",
                sender_id=get_whatsapp_phone_number_id(business),
                recipient_id=customer_id,
                message_text="🎤 Voice message",
                direction="outbound",
                platform_message_id=result.get("messages", [{}])[0].get("id", ""),
                raw_payload=result,
                is_read=True,
                media_type="voice",
                media_url=get_whatsapp_media_proxy_url(media_id) if media_id else None,
                channel=channel or "whatsapp",
                file_name=payload.filename,
                mime_type=payload.mime_type,
                whatsapp_media_id=media_id,
            )

        return JSONResponse({"status": "ok" if ok else "error", "meta": result}, status_code=200 if ok else 400)

    if platform == "instagram":
        return JSONResponse(
            {
                "status": "error",
                "message": "Instagram voice uploads need public media hosting and a supported attachment URL.",
            },
            status_code=400,
        )

    return JSONResponse({"status": "error", "message": "Unknown platform"}, status_code=400)


@app.get("/api/businesses")
async def api_get_businesses(x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    result = supabase.table("businesses").select("*").order("created_at", desc=True).execute()
    rows = [sanitize_business_row(row) for row in (result.data or [])]
    return {"status": "ok", "count": len(rows), "data": rows}


@app.get("/api/conversations")
async def api_get_conversations(platform: str = "all", search: str = "", x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    try:
        query = supabase.table("inbox_messages").select("*").order("created_at", desc=True).limit(900)

        if platform != "all":
            query = query.eq("platform", platform)

        rows = query.execute().data or []
        conversations = {}

        for row in rows:
            business_id = row.get("business_id")
            plat = normalize_id(row.get("platform", "instagram")).lower() or "instagram"
            channel = standard_channel(plat, row.get("channel", ""))
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
                    "media_type": row.get("media_type"),
                    "media_url": row.get("media_url"),
                }

            conversations[key]["total_messages"] += 1

            if row.get("direction") == "inbound" and not bool(row.get("is_read", False)):
                conversations[key]["unread_count"] += 1

        results = list(conversations.values())

        if search.strip():
            q = search.lower().strip()
            results = [
                c for c in results
                if q in f"{c.get('customer_id', '')} {c.get('customer_name', '')} {c.get('last_message', '')}".lower()
            ]

        return {"status": "ok", "count": len(results), "data": results}

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/conversation/{conversation_id}")
async def api_get_conversation_messages(conversation_id: str, limit: int = 250,
                                        x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse({"status": "error", "message": "Invalid conversation ID"}, status_code=400)

        platform, business_id, channel, customer_id = parts
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)

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

        try:
            mark_conversation_read_in_db(conversation_id)
        except Exception as exc:
            log("Could not mark conversation read", str(exc))

        return {"status": "ok", "count": len(messages), "data": messages}

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/api/conversation/{conversation_id}/read")
async def api_mark_conversation_read(
        conversation_id: str,
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    try:
        mark_conversation_read_in_db(conversation_id)
        return {"status": "ok"}
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/send-message")
async def api_send_message(
        conversation_id: str,
        text: str,
        business_id: str = "",
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    try:
        platform, biz_id, channel, customer_id = conversation_id.split("::")
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)
        business = get_business_by_id(biz_id)

        if not business:
            return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

        ok = False
        result = {}

        if platform == "instagram":
            ok, result = send_instagram_dm(
                access_token=get_business_access_token(business),
                recipient_id=customer_id,
                text=text,
                business=business,
            )
        elif platform == "telegram":
            if channel == "telegram_user_private":
                ok, result = await send_telegram_user_message(customer_id=customer_id, text=text)
            else:
                # send_telegram_bot_message returns a requests.Response object, not a tuple
                res = send_telegram_bot_message(chat_id=customer_id, text=text)
                if res is not None:
                    ok = res.ok
                    result = safe_json(res)
                else:
                    ok = False
                    result = {"error": "Send failed — no bot token configured"}
        elif platform == "whatsapp":
            res = send_whatsapp_text(customer_id, text, business)
            ok = res is not None and res.ok
            result = safe_json(res) if res is not None else {"error": "Send failed"}
        else:
            return JSONResponse({"status": "error", "message": "Unknown platform"}, status_code=400)

        if ok:
            save_inbox_message(
                business=business,
                platform=platform,
                sender_id=biz_id,
                recipient_id=customer_id,
                message_text=text,
                direction="outbound",
                platform_message_id=(
                            result.get("message_id") or result.get("messages", [{}])[0].get("id", "")) if isinstance(
                    result, dict) else "",
                raw_payload=result,
                is_read=True,
                channel=channel,
            )

        if not ok:
            return send_failure_response(result)

        return {"status": "ok", "meta": result}

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/api/chat-ai-toggle")
async def api_toggle_chat_ai(
        business_id: str,
        platform: str,
        channel: str,
        customer_id: str,
        enabled: bool,
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    set_chat_ai_enabled(business_id, platform, channel, customer_id, enabled)
    return {"status": "ok", "enabled": enabled}


@app.post("/api/business-settings")
async def api_update_business_settings(body: BusinessSettingsUpdate, x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business = get_business_by_id(body.business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    settings = clean_business_settings(body.settings)
    if not settings:
        return JSONResponse({"status": "error", "message": "No valid settings to update"}, status_code=400)

    update_business(body.business_id, settings)
    return {"status": "ok", "message": "Settings updated"}


@app.get("/api/ai-prompt-settings/{business_id}")
async def api_get_ai_prompt_settings(business_id: str, x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business = get_business_by_id(business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    return {"status": "ok", "data": get_ai_prompt_settings(business_id)}


@app.post("/api/v2/ai-prompt/generate")
async def api_generate_ai_prompt(body: AIPromptGenerateRequest, x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business = get_business_by_id(body.business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    try:
        result = generate_ai_prompt_suggestion(
            business=business,
            field=body.field,
            current_prompt=body.current_prompt,
            goal=body.goal,
        )
        return {
            "ok": True,
            "suggested_prompt": result["suggested_prompt"],
            "explanation": result["explanation"],
        }
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    except Exception as exc:
        log("Could not generate prompt suggestion", str(exc))
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/ai-prompt-settings")
async def api_update_ai_prompt_settings(body: AIPromptSettingsUpdate, x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business = get_business_by_id(body.business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    try:
        data = upsert_ai_prompt_settings(body.business_id, body.settings)
        return {"status": "ok", "data": data}
    except Exception as e:
        log("Could not update AI prompt settings", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/stats")
async def api_get_stats(x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    businesses = get_all_businesses()

    return {
        "status": "ok",
        "data": {
            "total_accounts": len(businesses),
            "active_accounts": sum(1 for b in businesses if b.get("bot_enabled")),
            "instagram_messages": get_message_count("instagram"),
            "telegram_messages": get_message_count("telegram"),
            "whatsapp_messages": get_message_count("whatsapp"),
        },
    }


@app.get("/debug/businesses")
async def debug_businesses(x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    result = supabase.table("businesses").select("*").order("created_at", desc=True).execute()
    rows = [sanitize_business_row(r) for r in (result.data or [])]
    return {"count": len(rows), "businesses": rows}


@app.get("/debug/whatsapp")
async def debug_whatsapp(x_dashboard_secret: str = Header(default="")):
    if require_dashboard_secret(x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    return {
        "has_whatsapp_access_token": bool(WHATSAPP_ACCESS_TOKEN),
        "whatsapp_access_token_preview": safe_token(WHATSAPP_ACCESS_TOKEN),
        "whatsapp_phone_number_id": WHATSAPP_PHONE_NUMBER_ID,
        "whatsapp_business_account_id": WHATSAPP_BUSINESS_ACCOUNT_ID,
        "public_base_url": PUBLIC_BASE_URL,
    }


# ============================================================================
# INFO ROUTES
# ============================================================================
@app.get("/privacy")
async def privacy():
    return PlainTextResponse(
        "Privacy Policy: This app collects Instagram, Telegram and WhatsApp messages to provide automated and manual sales replies."
    )


@app.get("/terms")
async def terms():
    return PlainTextResponse(
        "Terms of Service: This app provides automated and manual Instagram, Telegram and WhatsApp sales replies using AI-assisted tools."
    )
