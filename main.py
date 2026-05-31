import os
import re
import time
import asyncio
import secrets
import base64
import json
import hashlib
import hmac
import tempfile
import shutil
import subprocess
import requests
import telegram_bot as telegram_bot_module
from urllib.parse import urlencode, urlparse, parse_qs, unquote
from typing import Optional
from datetime import datetime, timedelta
import mimetypes
try:
    import bcrypt
except Exception:
    bcrypt = None

from pydantic import BaseModel
from fastapi import FastAPI, Request, Header, BackgroundTasks
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


async def run_blocking_io(func, *args, timeout: float = 20.0, label: str = "operation", **kwargs):
    """
    Run sync IO in a worker thread so one slow network call does not block the event loop.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=float(timeout),
        )
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{label} timed out after {int(timeout)}s") from exc


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
try:
    app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="frontend-assets")
except Exception:
    pass


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve React dashboard"""
    for path in (
        "frontend/dist/index.html",
        "static/index.html",
        "static/Instaagent Dashboard.html",
    ):
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
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.5-flash")
IG_VISUAL_ANALYZER_MAX_ITEMS = max(1, min(20, int(os.getenv("IG_VISUAL_ANALYZER_MAX_ITEMS", "8"))))
IG_VISUAL_ANALYZER_MAX_IMAGE_BYTES = max(200_000, min(8_000_000, int(os.getenv("IG_VISUAL_ANALYZER_MAX_IMAGE_BYTES", "4000000"))))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")

GRAPH_VERSION = os.getenv("GRAPH_API_VERSION") or os.getenv("GRAPH_VERSION", "v21.0")
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

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://agent-rust-delta.vercel.app")
if DASHBOARD_URL.rstrip("/") == "https://instaagent.streamlit.app":
    DASHBOARD_URL = "https://agent-rust-delta.vercel.app"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://agent-1-xi6h.onrender.com")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
SUPER_ADMIN_EMAILS = {
    str(item).strip().lower()
    for item in os.getenv("SUPER_ADMIN_EMAILS", "").split(",")
    if str(item).strip()
}

# Fallback store used only when `dashboard_workspace_state` table is missing.
# This keeps operator tasks usable until SQL migration is applied.
WORKSPACE_STATE_FALLBACK: dict[str, dict] = {}
STATS_CACHE_TTL_SECONDS = int(os.getenv("STATS_CACHE_TTL_SECONDS", "20"))
STATS_CACHE: dict[str, dict] = {}
INSTAGRAM_GROWTH_CACHE_TTL_SECONDS = int(os.getenv("INSTAGRAM_GROWTH_CACHE_TTL_SECONDS", "300"))
INSTAGRAM_GROWTH_CACHE: dict[str, tuple[float, dict]] = {}
INSTAGRAM_PUBLIC_PREVIEW_CACHE_TTL_SECONDS = int(os.getenv("INSTAGRAM_PUBLIC_PREVIEW_CACHE_TTL_SECONDS", str(60 * 60 * 6)))
INSTAGRAM_PUBLIC_PREVIEW_CACHE: dict[str, tuple[float, dict]] = {}
INSTAGRAM_CUSTOMER_PROFILE_CACHE_TTL_SECONDS = int(os.getenv("INSTAGRAM_CUSTOMER_PROFILE_CACHE_TTL_SECONDS", str(60 * 60 * 24)))
INSTAGRAM_CUSTOMER_PROFILE_CACHE: dict[str, tuple[float, dict]] = {}
WHATSAPP_EMBEDDED_REDIRECT_URI = os.getenv(
    "WHATSAPP_EMBEDDED_REDIRECT_URI",
    f"{PUBLIC_BASE_URL.rstrip('/')}/auth/whatsapp/embedded/callback",
)

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
WHATSAPP_FALLBACK_MODEL = os.getenv("OPENAI_MODEL", os.getenv("MISTRAL_MODEL", "gpt-4o-mini"))
WHATSAPP_CATALOG_LINK = os.getenv("CATALOG_LINK", "Catalog link will be shared soon.")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PRODUCT_MATCHER_ENABLED = str(os.getenv("PRODUCT_MATCHER_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_PRODUCT_MATCHER_API_URL = "https://new-project-2-kny4.onrender.com/api/process-media"
_product_matcher_urls = env_list("PRODUCT_MATCHER_API_URLS", "")
if not _product_matcher_urls:
    _legacy_matcher_url = os.getenv("PRODUCT_MATCHER_API_URL", "").strip()
    if _legacy_matcher_url:
        _product_matcher_urls = [_legacy_matcher_url]
    else:
        _product_matcher_urls = [DEFAULT_PRODUCT_MATCHER_API_URL]
PRODUCT_MATCHER_API_URLS = [str(url or "").strip() for url in _product_matcher_urls if str(url or "").strip()]
PRODUCT_MATCHER_TIMEOUT_SECONDS = max(3, min(60, int(os.getenv("PRODUCT_MATCHER_TIMEOUT_SECONDS", "20"))))
PRODUCT_MATCHER_TOP_K = max(1, min(10, int(os.getenv("PRODUCT_MATCHER_TOP_K", "3"))))
PRODUCT_MATCHER_MIN_SCORE = max(0.0, min(1.0, float(os.getenv("PRODUCT_MATCHER_MIN_SCORE", "0.45"))))
PRODUCT_MATCHER_CONTEXT_TTL_SECONDS = max(
    60,
    min(24 * 60 * 60, int(os.getenv("PRODUCT_MATCHER_CONTEXT_TTL_SECONDS", "1800"))),
)
PRODUCT_MATCHER_MAX_MEDIA_MB = max(
    2,
    min(40, int(os.getenv("PRODUCT_MATCHER_MAX_MEDIA_MB", "20"))),
)

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
WHATSAPP_EMBEDDED_SESSIONS = {}
LAST_WEBHOOK_EVENTS = []
INSTAGRAM_MEDIA_MATCH_MEMORY: dict[str, dict] = {}


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


class EmbeddedWhatsAppSendMessage(BaseModel):
    to: str
    text: str
    phone_number_id: str = ""
    access_token: str = ""


class BusinessChannelPayload(BaseModel):
    platform: str
    account_label: str
    account_external_id: str
    is_active: bool = True
    config: dict = {}


class DashboardLoginRequest(BaseModel):
    email: str
    password: str


class DashboardSignupRequest(BaseModel):
    email: str
    password: str
    role: str = "operator"
    business_id: str = ""
    full_name: str = ""


class OperatorCreateRequest(BaseModel):
    business_id: str
    login_id: str
    password: str


class BusinessCreateRequest(BaseModel):
    business_name: str
    owner_email: str
    business_type: str = ""
    language: str = "uz"
    tone: str = "friendly"


class BusinessAdminCreateRequest(BaseModel):
    email: str
    password: str
    role: str = "admin"
    full_name: str = ""


class OperatorTaskCreateRequest(BaseModel):
    business_id: str
    text: str
    recipients: list[str] = []
    assign_mode: str = "all"


class InstagramPostExtraUpdate(BaseModel):
    business_id: str
    post_id: str
    extra_info: str = ""


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


def unwrap_meta_redirect_url(value: str) -> str:
    value = normalize_id(value)
    if not value:
        return ""
    try:
        parsed = urlparse(value)
        host = normalize_id(parsed.netloc).lower()
        if host.endswith("instagram.com") or host.endswith("facebook.com"):
            target = parse_qs(parsed.query).get("u", [""])[0]
            target = unquote(normalize_id(target))
            if target.startswith(("http://", "https://")):
                return target
    except Exception:
        pass
    return value


def is_instagram_public_link(value: str) -> bool:
    value = normalize_id(value).lower()
    return (
        value.startswith(("http://", "https://"))
        and "instagram.com/" in value
        and any(seg in value for seg in ("/reel/", "/p/", "/tv/", "/share/"))
    )


def _extract_meta_content(html: str, *keys: str) -> str:
    if not html:
        return ""
    for key in keys:
        key_re = re.escape(key)
        patterns = [
            rf'<meta[^>]+property=["\']{key_re}["\'][^>]*content=["\']([^"\']+)["\']',
            rf'<meta[^>]+name=["\']{key_re}["\'][^>]*content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{key_re}["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{key_re}["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                value = normalize_id(match.group(1))
                if value:
                    return value
    return ""


def fetch_instagram_public_preview(permalink: str) -> dict:
    """
    Best-effort fallback for forwarded Instagram reels/posts that arrive without direct media URL.
    Scrapes OG meta from public link and caches it.
    """
    permalink = normalize_id(unwrap_meta_redirect_url(permalink))
    if not is_instagram_public_link(permalink):
        return {}

    now = time.time()
    cached = INSTAGRAM_PUBLIC_PREVIEW_CACHE.get(permalink)
    if cached and (now - cached[0]) < INSTAGRAM_PUBLIC_PREVIEW_CACHE_TTL_SECONDS:
        return cached[1] or {}

    user_agents = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Twitterbot/1.0",
    ]

    try:
        best_video = ""
        best_image = ""
        for user_agent in user_agents:
            headers = {
                "User-Agent": user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            }
            res = requests.get(permalink, headers=headers, timeout=12, allow_redirects=True)
            html = res.text if res.ok else ""
            if not html:
                continue
            og_video = _extract_meta_content(
                html,
                "og:video:secure_url",
                "og:video:url",
                "og:video",
                "twitter:player:stream",
            )
            og_image = _extract_meta_content(
                html,
                "og:image:secure_url",
                "og:image:url",
                "og:image",
                "twitter:image",
            )
            if og_video and not best_video:
                best_video = og_video
            if og_image and not best_image:
                best_image = og_image
            if best_video or best_image:
                break

        media_type = "video" if best_video else ("image" if best_image else "")
        payload = {
            "media_url": best_video or "",
            "post_image_url": best_image or "",
            "post_media_type": media_type,
            "post_permalink": permalink,
        }
        INSTAGRAM_PUBLIC_PREVIEW_CACHE[permalink] = (now, payload)
        return payload
    except Exception:
        INSTAGRAM_PUBLIC_PREVIEW_CACHE[permalink] = (now, {})
        return {}


def extract_instagram_permalink_from_payload(raw_payload: dict) -> str:
    raw_payload = raw_payload or {}
    candidates = []

    def collect_candidate(value):
        value = normalize_id(value)
        if not value:
            return
        value = unwrap_meta_redirect_url(value)
        if is_instagram_public_link(value) and value not in candidates:
            candidates.append(value)

    for key in ("post_permalink", "permalink", "link", "url"):
        collect_candidate(raw_payload.get(key))

    msg = raw_payload.get("message") if isinstance(raw_payload.get("message"), dict) else {}
    for key in ("permalink", "link", "url"):
        collect_candidate(msg.get(key))

    shares = msg.get("shares") if isinstance(msg.get("shares"), list) else []
    for share in shares:
        if not isinstance(share, dict):
            continue
        for key in ("permalink", "link", "url"):
            collect_candidate(share.get(key))

    attachments = msg.get("attachments") if isinstance(msg.get("attachments"), list) else []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        payload = att.get("payload") if isinstance(att.get("payload"), dict) else {}
        for key in ("permalink", "link", "url", "external_url"):
            collect_candidate(payload.get(key))

    return candidates[0] if candidates else ""


def normalize_email(value) -> str:
    return str(value or "").strip().lower()


def build_whatsapp_embedded_state(owner_email: str = "") -> str:
    payload = {
        "owner_email": normalize_email(owner_email),
        "nonce": secrets.token_urlsafe(10),
        "ts": int(time.time()),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_whatsapp_embedded_state(state: str) -> dict:
    try:
        if not state:
            return {}
        padded = state + ("=" * (-len(state) % 4))
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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


def remember_webhook_event(event: dict):
    LAST_WEBHOOK_EVENTS.append({
        **event,
        "received_at": datetime.utcnow().isoformat() + "Z",
    })
    del LAST_WEBHOOK_EVENTS[:-30]


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


def conversation_scope(platform: str, channel: str, customer_id: str, chat_id: str = "") -> str:
    """
    Stable conversation identity:
    - Telegram group/supergroup chats are scoped by chat_id (single window per group)
    - Other chats remain scoped by customer_id
    """
    platform = normalize_id(platform).lower()
    channel = standard_channel(platform, channel)
    customer_id = normalize_id(customer_id)
    chat_id = normalize_id(chat_id)

    if platform == "telegram":
        if channel in ("telegram_bot_group", "telegram_chat"):
            return chat_id or customer_id
        return customer_id or chat_id

    return customer_id


def extract_instagram_comment_post_id(row: dict) -> str:
    row = row or {}
    raw = row.get("raw_payload") or {}
    media = raw.get("media") if isinstance(raw, dict) else {}
    direct_media = row.get("media") if isinstance(row, dict) else {}
    return normalize_id(
        row.get("post_id")
        or row.get("media_id")
        or (raw.get("post_id") if isinstance(raw, dict) else "")
        or (raw.get("media_id") if isinstance(raw, dict) else "")
        or (media or {}).get("id")
        or (direct_media or {}).get("id")
    )


def fetch_instagram_media_info(access_token: str, post_id: str, business: dict = None) -> dict:
    post_id = normalize_id(post_id)
    if not access_token or not post_id:
        return {}
    fields = "id,media_type,media_url,thumbnail_url,permalink"
    oauth_provider = (business or {}).get("oauth_provider", "")
    urls = [f"{GRAPH_FACEBOOK}/{post_id}"] if oauth_provider == "facebook_page" else [f"{GRAPH_INSTAGRAM}/{post_id}", f"{GRAPH_FACEBOOK}/{post_id}"]
    for url in urls:
        try:
            res = requests.get(url, params={"access_token": access_token, "fields": fields}, timeout=20)
            body = safe_json(res)
            if not res.ok:
                continue
            return {
                "post_permalink": body.get("permalink") or f"https://www.instagram.com/p/{post_id}/",
                "post_image_url": body.get("media_url") or body.get("thumbnail_url") or "",
                "post_media_type": normalize_id(body.get("media_type")).lower(),
            }
        except Exception:
            continue
    return {"post_permalink": f"https://www.instagram.com/p/{post_id}/", "post_image_url": "", "post_media_type": ""}


def extract_instagram_shortcode_from_permalink(permalink: str) -> str:
    link = normalize_id(permalink)
    if not link:
        return ""
    try:
        parsed = urlparse(link)
        parts = [segment for segment in parsed.path.split("/") if segment]
        if len(parts) >= 2 and parts[0] in {"p", "reel", "tv"}:
            return normalize_id(parts[1])
        if len(parts) >= 1:
            return normalize_id(parts[-1])
    except Exception:
        pass
    return ""


def summarize_instagram_post_for_notes(post: dict) -> str:
    caption = normalize_id(post.get("caption"))
    media_type = normalize_id(post.get("media_type") or post.get("media_product_type")).lower()
    likes = _safe_int(post.get("like_count"), 0)
    comments = _safe_int(post.get("comments_count"), 0)
    ts = normalize_id(post.get("timestamp"))[:19].replace("T", " ")
    short_caption = caption[:220] + ("..." if len(caption) > 220 else "")
    return (
        f"Media: {media_type or 'post'}\n"
        f"Published: {ts or 'unknown'}\n"
        f"Likes: {likes}, Comments: {comments}\n"
        f"Caption: {short_caption or '—'}"
    )


def get_instagram_post_notes_state(business_id: str) -> dict:
    state = get_workspace_state(business_id)
    notes = state.get("instagram_post_notes") if isinstance(state, dict) else {}
    if isinstance(notes, dict):
        by_post = notes.get("by_post_id") if isinstance(notes.get("by_post_id"), dict) else {}
        by_shortcode = notes.get("by_shortcode") if isinstance(notes.get("by_shortcode"), dict) else {}
        by_permalink = notes.get("by_permalink") if isinstance(notes.get("by_permalink"), dict) else {}
        return {
            "by_post_id": by_post,
            "by_shortcode": by_shortcode,
            "by_permalink": by_permalink,
        }
    return {"by_post_id": {}, "by_shortcode": {}, "by_permalink": {}}


def save_instagram_post_extra_info(business_id: str, post: dict, extra_info: str, updated_by: str = "") -> dict:
    business_id = normalize_id(business_id)
    post_id = normalize_id(post.get("post_id") or post.get("id"))
    permalink = normalize_id(post.get("permalink"))
    shortcode = normalize_id(post.get("shortcode")) or extract_instagram_shortcode_from_permalink(permalink)
    clean_info = normalize_id(extra_info)
    if not business_id or not post_id:
        return {}

    notes = get_instagram_post_notes_state(business_id)
    entry = {
        "post_id": post_id,
        "permalink": permalink,
        "shortcode": shortcode,
        "extra_info": clean_info,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "updated_by": normalize_email(updated_by),
        "post_summary": summarize_instagram_post_for_notes(post),
    }
    notes["by_post_id"][post_id] = entry
    if shortcode:
        notes["by_shortcode"][shortcode] = post_id
    if permalink:
        notes["by_permalink"][permalink] = post_id

    upsert_workspace_state(
        business_id=business_id,
        state_key="instagram_post_notes",
        state_value=notes,
        updated_by=updated_by,
    )
    return entry


def resolve_instagram_post_note_for_context(business_id: str, post_id: str = "", permalink: str = "") -> dict:
    business_id = normalize_id(business_id)
    post_id = normalize_id(post_id)
    permalink = normalize_id(permalink)
    if not business_id:
        return {}
    notes = get_instagram_post_notes_state(business_id)
    by_post = notes.get("by_post_id") or {}
    if post_id and isinstance(by_post.get(post_id), dict):
        return by_post.get(post_id)
    if permalink:
        mapped_id = normalize_id((notes.get("by_permalink") or {}).get(permalink))
        if mapped_id and isinstance(by_post.get(mapped_id), dict):
            return by_post.get(mapped_id)
        shortcode = extract_instagram_shortcode_from_permalink(permalink)
        mapped_by_shortcode = normalize_id((notes.get("by_shortcode") or {}).get(shortcode))
        if mapped_by_shortcode and isinstance(by_post.get(mapped_by_shortcode), dict):
            return by_post.get(mapped_by_shortcode)
    return {}


def extract_latest_post_context_from_conversation(business_id: str, customer_id: str, channel: str = "dm") -> dict:
    business_id = normalize_id(business_id)
    customer_id = normalize_id(customer_id)
    if not business_id or not customer_id:
        return {}
    try:
        rows = (
            supabase.table("inbox_messages")
            .select("raw_payload,post_permalink,created_at")
            .eq("business_id", business_id)
            .eq("platform", "instagram")
            .eq("customer_id", customer_id)
            .eq("channel", standard_channel("instagram", channel))
            .order("created_at", desc=True)
            .limit(40)
            .execute()
            .data
            or []
        )
    except Exception:
        return {}

    for row in rows:
        raw = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
        post_id = normalize_id(raw.get("post_id") or raw.get("id") or raw.get("media_id"))
        permalink = normalize_id(row.get("post_permalink") or raw.get("post_permalink") or extract_instagram_permalink_from_payload(raw))
        if post_id or permalink:
            return {"post_id": post_id, "permalink": permalink}
    return {}


def build_instagram_post_reply_context(business: dict, customer_id: str, channel: str = "dm", post_id: str = "", post_permalink: str = "") -> str:
    business_id = normalize_id((business or {}).get("id"))
    if not business_id:
        return ""

    effective_post_id = normalize_id(post_id)
    effective_permalink = normalize_id(post_permalink)
    if not effective_post_id and not effective_permalink:
        latest = extract_latest_post_context_from_conversation(business_id, customer_id, channel)
        effective_post_id = normalize_id(latest.get("post_id"))
        effective_permalink = normalize_id(latest.get("permalink"))

    if not effective_post_id and not effective_permalink:
        return ""

    note = resolve_instagram_post_note_for_context(
        business_id=business_id,
        post_id=effective_post_id,
        permalink=effective_permalink,
    )
    if not note:
        return ""

    extra = normalize_id(note.get("extra_info"))
    if not extra:
        return ""

    return (
        "Post-specific context (very important):\n"
        f"- post_id: {normalize_id(note.get('post_id') or effective_post_id)}\n"
        f"- permalink: {normalize_id(note.get('permalink') or effective_permalink)}\n"
        f"- extra_info: {extra}\n"
        "Use this info when customer asks about this forwarded/shared post."
    )


def _parse_insights_values(rows: list[dict]) -> dict:
    values = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = normalize_id(row.get("name"))
        if not name:
            continue
        metric_values = row.get("values") if isinstance(row.get("values"), list) else []
        total = 0
        for item in metric_values:
            if isinstance(item, dict):
                total += _safe_int(item.get("value"), 0)
            else:
                total += _safe_int(item, 0)
        values[name] = total
    return values


def _fetch_media_insights_for_post(access_token: str, media_id: str) -> dict:
    media_id = normalize_id(media_id)
    if not access_token or not media_id:
        return {}
    metrics = [
        "reach",
        "impressions",
        "saved",
        "video_views",
        "total_interactions",
        "likes",
        "comments",
        "shares",
        "plays",
    ]
    ok, body = _graph_get_json(
        f"{GRAPH_FACEBOOK}/{media_id}/insights",
        access_token,
        {"metric": ",".join(metrics)},
        timeout=20,
    )
    if not ok:
        return {}
    rows = body.get("data") if isinstance(body.get("data"), list) else []
    return _parse_insights_values(rows)


def fetch_instagram_posts_for_import(business: dict, max_items: int = 300) -> list[dict]:
    token_candidates = get_instagram_token_candidates(business)
    if not token_candidates:
        raise ValueError("Instagram access token is missing. Reconnect Instagram account.")
    media_fields = (
        "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,"
        "like_count,comments_count,children{id,media_type,media_url,thumbnail_url,permalink}"
    )
    attempt_errors: list[str] = []

    for source, access_token in token_candidates:
        account_id, _ = _resolve_instagram_account_id_for_analysis(business, access_token)
        if not account_id:
            attempt_errors.append(f"{source}: Could not resolve Instagram account ID")
            continue

        raw_media, media_errors = _graph_paginated_get(
            f"{GRAPH_FACEBOOK}/{account_id}/media",
            access_token,
            {"fields": media_fields, "limit": 50},
            max_items=max_items,
            max_pages=12,
        )
        if not raw_media and media_errors:
            attempt_errors.append(f"{source}: {media_errors[0]}")
            continue

        posts = []
        for item in raw_media:
            if not isinstance(item, dict):
                continue
            post_id = normalize_id(item.get("id"))
            if not post_id:
                continue
            permalink = normalize_id(item.get("permalink"))
            shortcode = extract_instagram_shortcode_from_permalink(permalink)
            comments, _ = _graph_paginated_get(
                f"{GRAPH_FACEBOOK}/{post_id}/comments",
                access_token,
                {"fields": "id,text,timestamp,username,like_count,replies_count", "limit": 25},
                max_items=100,
                max_pages=5,
            )
            insights = _fetch_media_insights_for_post(access_token, post_id)
            posts.append(
                {
                    "post_id": post_id,
                    "shortcode": shortcode,
                    "permalink": permalink,
                    "caption": normalize_id(item.get("caption")),
                    "media_type": normalize_id(item.get("media_type")).lower(),
                    "media_product_type": normalize_id(item.get("media_product_type")).lower(),
                    "media_url": normalize_id(item.get("media_url")),
                    "thumbnail_url": normalize_id(item.get("thumbnail_url")),
                    "timestamp": normalize_id(item.get("timestamp")),
                    "like_count": _safe_int(item.get("like_count"), 0),
                    "comments_count": _safe_int(item.get("comments_count"), 0),
                    "children": item.get("children", {}).get("data", []) if isinstance(item.get("children"), dict) else [],
                    "comments_preview": comments[:30],
                    "comment_question_samples": [
                        normalize_id(comment.get("text"))
                        for comment in comments
                        if isinstance(comment, dict) and normalize_id(comment.get("text"))
                    ][:8],
                    "insights": insights,
                    "fetched_at": datetime.utcnow().isoformat() + "Z",
                    "token_source": source,
                }
            )
        return posts

    if attempt_errors:
        raise ValueError(f"Instagram media fetch failed: {attempt_errors[0]}")
    raise ValueError("Instagram media fetch failed: no valid token candidates")


def store_instagram_posts_cache(business_id: str, posts: list[dict], updated_by: str = "") -> dict:
    business_id = normalize_id(business_id)
    if not business_id:
        return {"stored": 0, "mode": "none"}

    clean_posts = []
    for item in posts or []:
        if not isinstance(item, dict):
            continue
        post_id = normalize_id(item.get("post_id") or item.get("id"))
        if not post_id:
            continue
        clean_posts.append({**item, "post_id": post_id, "business_id": business_id})

    stored = 0
    mode = "workspace_state"
    try:
        rows = []
        for post in clean_posts:
            rows.append(
                {
                    "business_id": business_id,
                    "post_id": normalize_id(post.get("post_id")),
                    "shortcode": normalize_id(post.get("shortcode")),
                    "permalink": normalize_id(post.get("permalink")),
                    "caption": normalize_id(post.get("caption")),
                    "media_type": normalize_id(post.get("media_type")),
                    "media_product_type": normalize_id(post.get("media_product_type")),
                    "media_url": normalize_id(post.get("media_url")),
                    "thumbnail_url": normalize_id(post.get("thumbnail_url")),
                    "timestamp": normalize_id(post.get("timestamp")),
                    "like_count": _safe_int(post.get("like_count"), 0),
                    "comments_count": _safe_int(post.get("comments_count"), 0),
                    "insights": post.get("insights") if isinstance(post.get("insights"), dict) else {},
                    "comments_preview": post.get("comments_preview") if isinstance(post.get("comments_preview"), list) else [],
                    "meta": post if isinstance(post, dict) else {},
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
        if rows:
            supabase.table("instagram_posts").upsert(rows, on_conflict="business_id,post_id").execute()
            stored = len(rows)
            mode = "instagram_posts_table"
    except Exception:
        mode = "workspace_state"

    upsert_workspace_state(
        business_id=business_id,
        state_key="instagram_posts_cache",
        state_value={"items": clean_posts[:500], "updated_at": datetime.utcnow().isoformat() + "Z"},
        updated_by=updated_by,
    )
    stored = max(stored, len(clean_posts))
    return {"stored": stored, "mode": mode}


def load_instagram_posts_from_cache(business_id: str, limit: int = 300) -> list[dict]:
    business_id = normalize_id(business_id)
    safe_limit = max(1, min(int(limit or 300), 1000))
    if not business_id:
        return []
    try:
        rows = (
            supabase.table("instagram_posts")
            .select("*")
            .eq("business_id", business_id)
            .order("timestamp", desc=True)
            .limit(safe_limit)
            .execute()
            .data
            or []
        )
        if rows:
            normalized = []
            for row in rows:
                meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
                normalized.append(
                    {
                        "post_id": normalize_id(row.get("post_id")),
                        "shortcode": normalize_id(row.get("shortcode")),
                        "permalink": normalize_id(row.get("permalink")),
                        "caption": normalize_id(row.get("caption")),
                        "media_type": normalize_id(row.get("media_type")).lower(),
                        "media_product_type": normalize_id(row.get("media_product_type")).lower(),
                        "media_url": normalize_id(row.get("media_url")),
                        "thumbnail_url": normalize_id(row.get("thumbnail_url")),
                        "timestamp": normalize_id(row.get("timestamp")),
                        "like_count": _safe_int(row.get("like_count"), 0),
                        "comments_count": _safe_int(row.get("comments_count"), 0),
                        "insights": row.get("insights") if isinstance(row.get("insights"), dict) else {},
                        "comments_preview": row.get("comments_preview") if isinstance(row.get("comments_preview"), list) else [],
                        "comment_question_samples": meta.get("comment_question_samples") if isinstance(meta.get("comment_question_samples"), list) else [],
                        "children": meta.get("children") if isinstance(meta.get("children"), list) else [],
                        "fetched_at": normalize_id(meta.get("fetched_at")) or normalize_id(row.get("updated_at")),
                    }
                )
            return normalized
    except Exception:
        pass

    state = get_workspace_state(business_id)
    cache = state.get("instagram_posts_cache") if isinstance(state, dict) else {}
    items = cache.get("items") if isinstance(cache, dict) and isinstance(cache.get("items"), list) else []
    return [item for item in items if isinstance(item, dict)][:safe_limit]


def encode_comment_scope(customer_id: str, post_id: str) -> str:
    """
    Canonical Instagram comment-thread scope.
    New format is post-based to keep one thread per post:
      post__<post_id>
    If post_id is unavailable, fall back to customer scope for safety.
    """
    customer_id = normalize_id(customer_id)
    post_id = normalize_id(post_id)
    if post_id:
        return f"post__{post_id}"
    return customer_id


def decode_comment_scope(scope: str) -> tuple[str, str]:
    """
    Return (customer_id, post_id).
    Supports:
    - New format: post__<post_id>
    - Legacy format: <customer_id>__post__<post_id>
    - Fallback: <customer_id>
    """
    scope = normalize_id(scope)
    if scope.startswith("post__"):
        return "", normalize_id(scope[6:])
    if "__post__" not in scope:
        return scope, ""
    customer_id, post_id = scope.split("__post__", 1)
    return normalize_id(customer_id), normalize_id(post_id)


def is_own_instagram_comment_actor(business: dict, entry_id: str, commenter_id: str, commenter_username: str = "") -> bool:
    """
    Ignore comment events authored by our own Instagram business account/page.
    These webhook echoes were creating duplicate comment threads.
    """
    entry_id = normalize_id(entry_id)
    commenter_id = normalize_id(commenter_id)
    commenter_username = normalize_id(commenter_username).lower()

    own_ids = {
        normalize_id((business or {}).get("instagram_business_id")),
        normalize_id((business or {}).get("facebook_page_id")),
        entry_id,
    }
    own_ids.discard("")
    if commenter_id and commenter_id in own_ids:
        return True

    own_usernames = {
        normalize_id((business or {}).get("instagram_username")).lower(),
        normalize_id((business or {}).get("business_name")).lower().replace(" ", ""),
    }
    own_usernames.discard("")
    if commenter_username and commenter_username in own_usernames:
        return True

    return False


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def hash_dashboard_password(password: str) -> str:
    password = str(password or "")
    if bcrypt:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    return "sha256$" + hashlib.sha256((password + str(DASHBOARD_SECRET)).encode()).hexdigest()


def verify_dashboard_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    raw_hash = str(password_hash or "")
    if raw_hash.startswith("$2") and bcrypt:
        try:
            return bool(bcrypt.checkpw(str(password).encode(), raw_hash.encode()))
        except Exception:
            return False
    if raw_hash.startswith("sha256$"):
        expected = "sha256$" + hashlib.sha256((str(password) + str(DASHBOARD_SECRET)).encode()).hexdigest()
        return hmac.compare_digest(expected, raw_hash)
    legacy = hashlib.sha256((str(password) + str(DASHBOARD_SECRET)).encode()).hexdigest()
    return hmac.compare_digest(legacy, raw_hash)


AUTH_TOKEN_TTL_SECONDS = int(os.getenv("DASHBOARD_AUTH_TTL_SECONDS", str(60 * 60 * 24 * 30)))
CONVERSATIONS_CACHE_TTL_SECONDS = float(os.getenv("CONVERSATIONS_CACHE_TTL_SECONDS", "10"))
_conversations_cache: dict[str, tuple[float, dict]] = {}
CONVERSATION_MESSAGES_CACHE_TTL_SECONDS = float(os.getenv("CONVERSATION_MESSAGES_CACHE_TTL_SECONDS", "12"))
_conversation_messages_cache: dict[str, tuple[float, dict]] = {}
BUSINESS_ADMIN_ROLES = {"owner", "admin", "super_admin"}


def clear_inbox_caches():
    _conversations_cache.clear()
    _conversation_messages_cache.clear()


def create_dashboard_auth_token(email: str, is_admin: bool = False, role: str = "") -> str:
    payload = {
        "email": normalize_email(email),
        "is_admin": bool(is_admin),
        "role": normalize_id(role).lower(),
        "exp": int(time.time()) + AUTH_TOKEN_TTL_SECONDS,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    signature = hmac.new(str(DASHBOARD_SECRET).encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def decode_dashboard_auth_token(token: str) -> Optional[dict]:
    token = normalize_id(token)
    if "." not in token:
        return None
    payload_b64, signature = token.rsplit(".", 1)
    expected = hmac.new(str(DASHBOARD_SECRET).encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None

    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        return None

    exp = int(payload.get("exp") or 0)
    if exp and exp < int(time.time()):
        return None
    payload["email"] = normalize_email(payload.get("email", ""))
    payload["is_admin"] = bool(payload.get("is_admin", False))
    payload["role"] = normalize_id(payload.get("role", "")).lower()
    return payload


def list_user_business_ids(email: str) -> list[str]:
    email = normalize_email(email)
    if not email:
        return []
    rows = (
        supabase.table("business_users")
        .select("business_id")
        .eq("user_email", email)
        .execute()
        .data
        or []
    )
    return [normalize_id(row.get("business_id")) for row in rows if normalize_id(row.get("business_id"))]


def list_user_business_memberships(email: str) -> list[dict]:
    email = normalize_email(email)
    if not email:
        return []
    try:
        rows = (
            supabase.table("business_users")
            .select("business_id,role")
            .eq("user_email", email)
            .execute()
            .data
            or []
        )
    except Exception:
        return []

    memberships = []
    for row in rows:
        business_id = normalize_id(row.get("business_id"))
        if not business_id:
            continue
        memberships.append(
            {
                "business_id": business_id,
                "role": normalize_id(row.get("role") or "operator").lower() or "operator",
            }
        )
    return memberships


def pick_user_business_role(email: str, business_id: str = "") -> str:
    business_id = normalize_id(business_id)
    memberships = list_user_business_memberships(email)
    if not memberships:
        return ""
    if business_id:
        for membership in memberships:
            if normalize_id(membership.get("business_id")) == business_id:
                return normalize_id(membership.get("role"))
    for preferred in ("owner", "admin", "operator"):
        for membership in memberships:
            if normalize_id(membership.get("role")) == preferred:
                return preferred
    return normalize_id(memberships[0].get("role"))


def get_user_business_role(email: str, business_id: str = "") -> str:
    email = normalize_email(email)
    business_id = normalize_id(business_id)
    if not email:
        return ""
    try:
        query = supabase.table("business_users").select("role").eq("user_email", email)
        if business_id:
            query = query.eq("business_id", business_id)
        rows = query.limit(1).execute().data or []
        return normalize_id(rows[0].get("role")) if rows else ""
    except Exception:
        return ""


def is_super_admin_email(email: str) -> bool:
    clean = normalize_email(email)
    if not clean:
        return False
    if clean in SUPER_ADMIN_EMAILS:
        return True
    return bool(ADMIN_EMAIL and clean == normalize_email(ADMIN_EMAIL))


def parse_auth_header(authorization: str) -> str:
    value = normalize_id(authorization)
    if value.lower().startswith("bearer "):
        return normalize_id(value[7:])
    return ""


def resolve_dashboard_access(authorization: str = "", x_dashboard_secret: str = "") -> Optional[dict]:
    # When a valid dashboard secret is provided, treat the request as admin/system access.
    # This keeps local/debug dashboard flows reliable even if the browser has a stale token.
    if not require_dashboard_secret(x_dashboard_secret):
        return {"email": "system", "is_admin": True, "business_ids": [], "role": "admin"}

    token = parse_auth_header(authorization)
    if token:
        payload = decode_dashboard_auth_token(token)
        if payload:
            email = normalize_email(payload.get("email"))
            is_admin = bool(payload.get("is_admin")) and is_super_admin_email(email)
            token_role = normalize_id(payload.get("role", "")).lower()
            if is_admin:
                role = "super_admin"
                business_ids = []
            else:
                memberships = list_user_business_memberships(email)
                business_ids = [normalize_id(item.get("business_id")) for item in memberships if normalize_id(item.get("business_id"))]
                # Always prefer current DB membership over stale token/global dashboard role.
                role = pick_user_business_role(email) or token_role or "operator"
            return {"email": email, "is_admin": is_admin, "business_ids": business_ids, "role": role or "operator"}
        return None

    # No bearer token and no valid dashboard secret.
    return None


def can_access_business(access: dict, business_id: str) -> bool:
    if not access:
        return False
    if access.get("is_admin"):
        return True
    return normalize_id(business_id) in set(access.get("business_ids") or [])


def get_latest_instagram_comment_anchor(business_id: str, commenter_id: str = "", post_id: str = "") -> dict:
    """
    Find the most recent inbound customer comment for (business, commenter[, post]).
    We reply to that comment_id so manual replies stay in the same comment thread.
    """
    business_id = normalize_id(business_id)
    commenter_id = normalize_id(commenter_id)
    post_id = normalize_id(post_id)
    if not business_id:
        return {}

    try:
        query = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", "instagram")
            .eq("business_id", business_id)
            .eq("channel", "instagram_comment")
            .eq("direction", "inbound")
        )
        if commenter_id:
            query = query.eq("customer_id", commenter_id)
        rows = query.order("created_at", desc=True).limit(120).execute().data or []
    except Exception:
        return {}

    if not rows:
        return {}

    if not post_id:
        return rows[0]

    for row in rows:
        if extract_instagram_comment_post_id(row) == post_id:
            return row
    return {}


def get_instagram_comment_anchor_by_comment_id(business_id: str, comment_id: str, post_id: str = "") -> dict:
    business_id = normalize_id(business_id)
    comment_id = normalize_id(comment_id)
    post_id = normalize_id(post_id)
    if not business_id or not comment_id:
        return {}

    rows = []
    try:
        rows = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", "instagram")
            .eq("business_id", business_id)
            .eq("channel", "instagram_comment")
            .eq("direction", "inbound")
            .eq("external_message_id", comment_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
            .data
            or []
        )
    except Exception:
        rows = []

    # Fallback path for legacy rows where external_message_id was not stored.
    if not rows:
        try:
            recent = (
                supabase.table("inbox_messages")
                .select("*")
                .eq("platform", "instagram")
                .eq("business_id", business_id)
                .eq("channel", "instagram_comment")
                .eq("direction", "inbound")
                .order("created_at", desc=True)
                .limit(300)
                .execute()
                .data
                or []
            )
            rows = [
                r for r in recent
                if normalize_id((r.get("raw_payload") or {}).get("id") or (r.get("raw_payload") or {}).get("comment_id")) == comment_id
            ]
        except Exception:
            rows = []

    if not rows:
        return {}
    if not post_id:
        return rows[0]
    for row in rows:
        if extract_instagram_comment_post_id(row) == post_id:
            return row
    return {}


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


def unsupported_message_mutation_response(platform: str, action: str):
    platform_label = (platform or "this platform").title()
    return JSONResponse(
        {
            "status": "error",
            "message": f"{platform_label} does not support dashboard {action} for already-delivered messages through the connected API.",
        },
        status_code=400,
    )


def telegram_bot_request(business: dict, method: str, payload: dict):
    token = get_telegram_bot_token(business)
    if not token:
        return None
    return requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload,
        timeout=30,
    )


def edit_telegram_bot_message(chat_id: str, message_id: str, text: str, business: dict):
    return telegram_bot_request(
        business,
        "editMessageText",
        {"chat_id": chat_id, "message_id": int(message_id), "text": text[:4096]},
    )


def delete_telegram_bot_message(chat_id: str, message_id: str, business: dict):
    return telegram_bot_request(
        business,
        "deleteMessage",
        {"chat_id": chat_id, "message_id": int(message_id)},
    )


async def edit_telegram_user_message_safe(customer_id: str, message_id: str, text: str):
    handler = getattr(telegram_bot_module, "edit_telegram_user_message", None)
    if not handler:
        return False, {"error": "Telegram user-account edit support is not deployed yet. Deploy the updated telegram_bot.py too."}
    return await handler(customer_id, message_id, text)


async def delete_telegram_user_message_safe(customer_id: str, message_id: str):
    handler = getattr(telegram_bot_module, "delete_telegram_user_message", None)
    if not handler:
        return False, {"error": "Telegram user-account delete support is not deployed yet. Deploy the updated telegram_bot.py too."}
    return await handler(customer_id, message_id)


def get_inbox_message_for_dashboard(message_id: str, access: dict):
    message_id = normalize_id(message_id)
    if not message_id:
        return None, JSONResponse({"error": "Missing message_id"}, status_code=400)

    rows = (
        supabase.table("inbox_messages")
        .select("*")
        .eq("id", message_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None, JSONResponse({"error": "Message not found"}, status_code=404)

    row = rows[0]
    if not can_access_business(access, normalize_id(row.get("business_id"))):
        return None, JSONResponse({"error": "Forbidden"}, status_code=403)

    if normalize_id(row.get("direction")).lower() != "outbound":
        return None, JSONResponse({"error": "Only outbound dashboard messages can be changed"}, status_code=400)

    return row, None


def message_target_chat_id(row: dict):
    payload = row.get("raw_payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    return normalize_id(
        row.get("chat_id")
        or payload.get("chat_id")
        or payload.get("customer_id")
        or row.get("customer_id")
    )


async def mutate_delivered_telegram_message(row: dict, business: dict, action: str, text: str = ""):
    channel = standard_channel("telegram", row.get("channel"))
    target_id = message_target_chat_id(row)
    message_id = normalize_id(row.get("external_message_id"))

    if not target_id or not message_id:
        return False, {"error": "Telegram message id is missing. This older row cannot be changed remotely."}

    try:
        if channel == "telegram_user_private":
            if action == "edit":
                return await edit_telegram_user_message_safe(target_id, message_id, text)
            return await delete_telegram_user_message_safe(target_id, message_id)

        if action == "edit":
            res = edit_telegram_bot_message(target_id, message_id, text, business)
        else:
            res = delete_telegram_bot_message(target_id, message_id, business)

        if not res:
            return False, {"error": "Telegram bot token is not configured"}

        data = safe_json(res)
        return bool(res.ok and data.get("ok", True)), data
    except Exception as exc:
        return False, {"error": str(exc)}


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


def telegram_user_media_proxy_url(customer_id: str, message_id: str) -> str:
    customer_id = normalize_id(customer_id)
    message_id = normalize_id(message_id)
    if not customer_id or not message_id:
        return ""

    base_root = (PUBLIC_BASE_URL or "").rstrip("/")
    base = f"{base_root}/api/telegram-user-media/{customer_id}/{message_id}" if base_root else f"/api/telegram-user-media/{customer_id}/{message_id}"
    if DASHBOARD_SECRET:
        return f"{base}?token={DASHBOARD_SECRET}"
    return base


def telegram_bot_media_proxy_url(file_id: str) -> str:
    file_id = normalize_id(file_id)
    if not file_id:
        return ""
    base_root = (PUBLIC_BASE_URL or "").rstrip("/")
    base = f"{base_root}/api/telegram-bot-media/{file_id}" if base_root else f"/api/telegram-bot-media/{file_id}"
    if DASHBOARD_SECRET:
        return f"{base}?token={DASHBOARD_SECRET}"
    return base


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
    platform = normalize_id(row.get("platform")).lower()
    channel = standard_channel(platform, row.get("channel", ""))
    customer_id = normalize_id(row.get("customer_id"))
    external_message_id = normalize_id(row.get("external_message_id"))
    media_file_id = normalize_id(row.get("media_file_id"))
    media_url = row.get("media_url") or ""

    # Telegram user client media is often stored without direct media_url.
    # Build proxy URL from customer_id + external_message_id so browser can stream it.
    if (
        not media_url
        and platform == "telegram"
        and channel == "telegram_user_private"
        and media_type in ("photo", "video", "voice", "audio", "file")
        and customer_id
        and external_message_id
    ):
        media_url = telegram_user_media_proxy_url(customer_id, external_message_id)

    # Fallback for legacy Telegram rows where external_message_id is missing,
    # but file_id was stored (common for bot API updates and some migrations).
    if not media_url and platform == "telegram" and media_file_id:
        media_url = telegram_bot_media_proxy_url(media_file_id)

    if media_type:
        message['type'] = 'media'
        message['label'] = media_type
        message['mediaCaption'] = content
        message['mediaUrl'] = media_url
        # Keep raw identity fields so frontend can reconstruct fallback media URLs when needed.
        message['media_type'] = media_type
        message['media_url'] = media_url
        message['platform'] = platform
        message['channel'] = channel
        message['customer_id'] = customer_id
        message['external_message_id'] = external_message_id
        message['media_file_id'] = media_file_id
    else:
        message['type'] = 'text'
        message['text'] = content

    raw_payload = row.get("raw_payload") or {}
    # Keep identifiers on every row (including plain text) so manual per-comment reply can target correctly.
    message['external_message_id'] = external_message_id
    message['comment_id'] = normalize_id(raw_payload.get("comment_id") or raw_payload.get("id") or external_message_id)
    message['raw_payload'] = raw_payload
    message["post_id"] = extract_instagram_comment_post_id(row)
    message["post_permalink"] = row.get("post_permalink") or raw_payload.get("post_permalink") or ""
    message["post_image_url"] = row.get("post_image_url") or raw_payload.get("post_image_url") or ""
    message["post_media_type"] = normalize_id(row.get("post_media_type") or raw_payload.get("post_media_type")).lower()

    return message


def _looks_like_numeric_id(value: str) -> bool:
    text = normalize_id(value)
    return bool(text and re.fullmatch(r"\d{6,}", text))


def _looks_like_generated_instagram_name(value: str) -> bool:
    text = normalize_id(value).lower()
    return bool(
        not text
        or _looks_like_numeric_id(text)
        or re.fullmatch(r"instagram (user|client|ig user)\s+\d{2,}", text)
        or re.fullmatch(r"ig user\s+\d{2,}", text)
    )


def _extract_username_candidates(raw_payload: dict) -> list[str]:
    raw = raw_payload or {}
    candidates = []
    for key in ("username", "user_name", "from_username", "customer_username"):
        value = normalize_id(raw.get(key))
        if value:
            candidates.append(value)

    for obj_key in ("from", "sender", "user", "contact", "profile"):
        obj = raw.get(obj_key)
        if isinstance(obj, dict):
            for key in ("username", "user_name", "name"):
                value = normalize_id(obj.get(key))
                if value:
                    candidates.append(value)
    return [item for item in candidates if item]


def resolve_customer_label(rows: list, platform: str, fallback_scope: str) -> tuple[str, str]:
    """
    Returns (display_name, handle_value_without_at).
    Prefers real usernames/names found in payloads and historical customer_name,
    falls back to scoped ids only when nothing human-readable is available.
    """
    best_name = ""
    best_username = ""

    for row in reversed(rows or []):
        customer_name = normalize_id(row.get("customer_name"))
        if customer_name and not _looks_like_numeric_id(customer_name):
            if not best_name:
                best_name = customer_name
            if platform == "instagram" and re.fullmatch(r"[A-Za-z0-9._]{2,64}", customer_name):
                best_username = best_username or customer_name

        raw = row.get("raw_payload") if isinstance(row, dict) else {}
        for candidate in _extract_username_candidates(raw if isinstance(raw, dict) else {}):
            if platform == "instagram":
                if re.fullmatch(r"[A-Za-z0-9._]{2,64}", candidate):
                    best_username = best_username or candidate
                    if not best_name:
                        best_name = candidate
            elif not best_name:
                best_name = candidate

        if best_name and (best_username or platform != "instagram"):
            break

    if not best_name:
        if platform == "instagram":
            best_name = f"Instagram user {fallback_scope[-4:]}"
        elif platform == "telegram":
            best_name = f"Telegram user {fallback_scope[-4:]}"
        elif platform == "whatsapp":
            best_name = f"WhatsApp user {fallback_scope[-4:]}"
        else:
            best_name = f"Customer {fallback_scope[-4:]}"

    handle_value = best_username or fallback_scope
    return best_name, handle_value


def fetch_instagram_customer_profile(access_token: str, customer_id: str) -> dict:
    access_token = normalize_id(access_token)
    customer_id = normalize_id(customer_id)
    if not access_token or not customer_id:
        return {}

    cache_key = f"{customer_id}:{hashlib.sha1(access_token.encode()).hexdigest()[:10]}"
    now = time.time()
    cached = INSTAGRAM_CUSTOMER_PROFILE_CACHE.get(cache_key)
    if cached and (now - cached[0]) < INSTAGRAM_CUSTOMER_PROFILE_CACHE_TTL_SECONDS:
        return cached[1] or {}

    profile = {}
    for base_url in (GRAPH_FACEBOOK, GRAPH_INSTAGRAM):
        try:
            res = requests.get(
                f"{base_url}/{customer_id}",
                params={"fields": "id,name,username,profile_pic", "access_token": access_token},
                timeout=8,
            )
            body = safe_json(res)
            if res.ok and isinstance(body, dict):
                profile = {
                    "id": normalize_id(body.get("id") or customer_id),
                    "name": normalize_id(body.get("name")),
                    "username": normalize_id(body.get("username")),
                    "profile_pic": normalize_id(body.get("profile_pic")),
                }
                if profile.get("name") or profile.get("username"):
                    break
        except Exception:
            continue

    INSTAGRAM_CUSTOMER_PROFILE_CACHE[cache_key] = (now, profile)
    if len(INSTAGRAM_CUSTOMER_PROFILE_CACHE) > 1000:
        for key in sorted(INSTAGRAM_CUSTOMER_PROFILE_CACHE, key=lambda item: INSTAGRAM_CUSTOMER_PROFILE_CACHE[item][0])[:250]:
            INSTAGRAM_CUSTOMER_PROFILE_CACHE.pop(key, None)
    return profile


def display_name_from_instagram_profile(profile: dict, fallback: str = "") -> str:
    if not isinstance(profile, dict):
        return fallback
    username = normalize_id(profile.get("username"))
    name = normalize_id(profile.get("name"))
    if username:
        return username
    if name and not _looks_like_numeric_id(name):
        return name
    return fallback


def backfill_instagram_customer_name(business_id: str, customer_id: str, profile_name: str):
    profile_name = normalize_id(profile_name)
    if not business_id or not customer_id or not profile_name:
        return
    try:
        supabase.table("inbox_messages").update({"customer_name": profile_name}).eq("business_id", business_id).eq("platform", "instagram").eq("customer_id", str(customer_id)).execute()
        clear_inbox_caches()
    except Exception:
        pass


def transform_conversation_to_react(key: str, rows: list, business: dict = None, ai_lookup_enabled: bool = True) -> dict:
    """Transform database rows to React conversation format"""
    if not rows:
        return None

    latest_row = rows[-1]
    parts = key.split("::")
    if len(parts) != 4:
        return None

    platform, business_id, channel, customer_id = parts
    comment_customer_id, comment_post_id = decode_comment_scope(customer_id) if (
        platform == "instagram" and "comment" in normalize_id(channel).lower()
    ) else (customer_id, "")
    latest_chat_id = normalize_id(latest_row.get("chat_id"))
    if platform == "telegram" and channel in ("telegram_bot_group", "telegram_chat"):
        effective_scope = latest_chat_id
    elif platform == "instagram" and "comment" in normalize_id(channel).lower():
        effective_scope = comment_post_id or comment_customer_id
    else:
        effective_scope = comment_customer_id

    customer_name, handle_value = resolve_customer_label(rows, platform, effective_scope)
    if (
        platform == "instagram"
        and "comment" not in normalize_id(channel).lower()
        and business
        and _looks_like_generated_instagram_name(customer_name)
    ):
        profile = fetch_instagram_customer_profile(get_business_access_token(business), effective_scope)
        profile_name = display_name_from_instagram_profile(profile)
        if profile_name:
            customer_name = profile_name
            handle_value = normalize_id(profile.get("username")) or handle_value
            backfill_instagram_customer_name(business_id, effective_scope, profile_name)
    ai_scope = encode_comment_scope("", comment_post_id) if (platform == "instagram" and "comment" in normalize_id(channel).lower() and comment_post_id) else effective_scope
    # Fast conversation list path should avoid per-conversation DB lookups.
    ai_enabled = is_chat_ai_enabled(platform, channel, ai_scope, business_id) if ai_lookup_enabled else True

    return {
        'id': key,
        'name': customer_name,
        'handle': f'@{handle_value}',
        'platform': platform,
        'isCommentThread': platform == "instagram" and "comment" in normalize_id(channel).lower(),
        'postId': comment_post_id or extract_instagram_comment_post_id(latest_row),
        'postPermalink': (latest_row.get("raw_payload") or {}).get("post_permalink", ""),
        'postImageUrl': (latest_row.get("raw_payload") or {}).get("post_image_url", ""),
        'postMediaType': normalize_id((latest_row.get("raw_payload") or {}).get("post_media_type", "")).lower(),
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


def get_business_channel(platform: str, external_account_id: str = "", only_active: bool = True):
    platform = normalize_id(platform).lower()
    external_account_id = normalize_id(external_account_id)
    if not platform or not external_account_id:
        return None
    try:
        query = (
            supabase.table("business_channels")
            .select("*")
            .eq("platform", platform)
            .eq("external_account_id", external_account_id)
        )
        if only_active:
            query = query.eq("is_active", True)
        result = query.limit(1).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_business(instagram_business_id: str):
    instagram_business_id = normalize_id(instagram_business_id)
    if not instagram_business_id:
        return None
    channel = get_business_channel("instagram", instagram_business_id)
    if channel:
        row = get_business_by_id(channel.get("business_id"))
        if row:
            return row
    result = supabase.table("businesses").select("*").eq("instagram_business_id", instagram_business_id).limit(
        1).execute()
    return result.data[0] if result.data else None


def get_business_by_page_id(page_id: str):
    page_id = normalize_id(page_id)
    if not page_id:
        return None
    channel = get_business_channel("instagram", page_id)
    if channel:
        row = get_business_by_id(channel.get("business_id"))
        if row:
            return row
    result = supabase.table("businesses").select("*").eq("facebook_page_id", page_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_business_by_whatsapp_phone_number_id(phone_number_id: str):
    phone_number_id = normalize_id(phone_number_id)
    if not phone_number_id:
        return None
    try:
        channel = get_business_channel("whatsapp", phone_number_id)
        if channel:
            row = get_business_by_id(channel.get("business_id"))
            if row:
                return row
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
        channel = get_business_channel("instagram", lookup_id)
        if channel:
            business = get_business_by_id(channel.get("business_id"))
            if business:
                return business

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
    "whatsapp_business_account_id",
    "whatsapp_phone_number_id",
    "whatsapp_access_token",
    "ai_model",
    "ai_temperature",
    "ai_max_tokens",
    "ai_reply_rules",
    "mistral_api_key",
    "openai_api_key",
    "gemini_api_key",
    "anthropic_api_key",
    "ai_provider",
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
        elif key == "ai_provider":
            provider = str(value or "").strip().lower()
            if provider in {"mistral", "openai", "gemini", "anthropic"}:
                cleaned[key] = provider
        elif key.endswith("_api_key"):
            cleaned[key] = str(value or "").strip()
        else:
            cleaned[key] = str(value or "").strip()

    if "ai_model" in cleaned and "ai_provider" not in cleaned:
        inferred_provider = infer_ai_provider_strict(cleaned.get("ai_model"))
        if inferred_provider:
            cleaned["ai_provider"] = inferred_provider

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


def sanitize_channel_row(row: dict):
    if not row:
        return None
    clean = dict(row)
    cfg = dict(clean.get("config") or {})
    for key in ("access_token", "page_access_token", "bot_token", "session_file_b64"):
        if key in cfg:
            cfg[key] = safe_token(cfg.get(key, ""))
    clean["config"] = cfg
    return clean


def get_business_channel_rows(business_id: str, platform_aliases: list[str]):
    business_id = normalize_id(business_id)
    if not business_id:
        return []
    aliases = [normalize_id(x).lower() for x in (platform_aliases or []) if normalize_id(x)]
    if not aliases:
        return []
    try:
        result = (
            supabase.table("business_channels")
            .select("*")
            .eq("business_id", business_id)
            .in_("platform", aliases)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def get_business_channel_token(business: dict, platform_aliases: list[str], token_keys: list[str]):
    business_id = normalize_id((business or {}).get("id"))
    rows = get_business_channel_rows(business_id, platform_aliases) if business_id else []
    for row in rows:
        cfg = dict(row.get("config") or {})
        for key in token_keys:
            value = normalize_id(cfg.get(key) or row.get(key))
            if value:
                return value
    return ""


def get_instagram_token_candidates(business: dict) -> list[tuple[str, str]]:
    """
    Return unique token candidates in priority order for Instagram Graph calls.
    """
    candidates: list[tuple[str, str]] = []
    business_id = normalize_id((business or {}).get("id"))
    if business_id:
        rows = get_business_channel_rows(business_id, ["instagram"])
        for row in rows:
            cfg = dict(row.get("config") or {})
            for key in ("page_access_token", "access_token"):
                value = normalize_id(cfg.get(key) or row.get(key))
                if value:
                    candidates.append((f"business_channels.{key}", value))

    for key in ("page_access_token", "access_token"):
        value = normalize_id((business or {}).get(key))
        if value:
            candidates.append((f"businesses.{key}", value))

    unique: list[tuple[str, str]] = []
    seen = set()
    for source, token in candidates:
        signature = hashlib.sha1(token.encode()).hexdigest()
        if signature in seen:
            continue
        seen.add(signature)
        unique.append((source, token))
    return unique


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
        .eq("is_read", False)
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
        post_permalink: Optional[str] = None,
        post_image_url: Optional[str] = None,
        post_media_type: Optional[str] = None,
):
    try:
        customer_id = sender_id if direction == "inbound" else recipient_id
        payload = dict(raw_payload or {})
        if post_permalink:
            payload["post_permalink"] = post_permalink
        if post_image_url:
            payload["post_image_url"] = post_image_url
        if post_media_type:
            payload["post_media_type"] = post_media_type

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
            "raw_payload": payload,
            "is_read": is_read if direction == "inbound" else True,
            "media_type": media_type,
            "media_url": media_url,
            "file_name": file_name,
            "mime_type": mime_type,
            "whatsapp_media_id": whatsapp_media_id,
            "post_permalink": post_permalink,
            "post_image_url": post_image_url,
            "post_media_type": post_media_type,
            "created_at": datetime.utcnow().isoformat(),
        }

        try:
            supabase.table("inbox_messages").insert(data).execute()
        except Exception:
            compatible_data = dict(data)
            for optional_key in ["post_permalink", "post_image_url", "post_media_type"]:
                compatible_data.pop(optional_key, None)
            try:
                supabase.table("inbox_messages").insert(compatible_data).execute()
            except Exception:
                for optional_key in ["customer_name", "is_read", "media_type", "media_url", "file_name", "mime_type",
                                     "whatsapp_media_id"]:
                    compatible_data.pop(optional_key, None)
                supabase.table("inbox_messages").insert(compatible_data).execute()

        # New data landed; keep dashboard reads fresh.
        clear_inbox_caches()

    except Exception as e:
        log("Could not save inbox message", str(e))


def get_message_count(platform=None, business_ids=None):
    try:
        q = supabase.table("inbox_messages").select("id", count="exact")
        if platform:
            q = q.eq("platform", platform)
        if business_ids:
            q = q.in_("business_id", business_ids)
        result = q.execute()
        return result.count or 0
    except Exception:
        return 0


def get_workspace_state(business_id: str):
    business_id = normalize_id(business_id)
    if not business_id:
        return {}
    try:
        rows = (
            supabase.table("dashboard_workspace_state")
            .select("state_key,state_value")
            .eq("business_id", business_id)
            .execute()
            .data
            or []
        )
        payload = {}
        for row in rows:
            key = normalize_id(row.get("state_key"))
            if key:
                payload[key] = row.get("state_value")
        # Merge runtime fallback (used only if DB table is unavailable).
        fallback = WORKSPACE_STATE_FALLBACK.get(business_id) or {}
        if isinstance(fallback, dict):
            payload = {**payload, **fallback}
        return payload
    except Exception as e:
        log("Could not load workspace state", str(e))
        fallback = WORKSPACE_STATE_FALLBACK.get(business_id) or {}
        return fallback if isinstance(fallback, dict) else {}


def upsert_workspace_state(business_id: str, state_key: str, state_value, updated_by: str = ""):
    business_id = normalize_id(business_id)
    state_key = normalize_id(state_key)
    if not business_id or not state_key:
        return
    data = {
        "business_id": business_id,
        "state_key": state_key,
        "state_value": state_value if isinstance(state_value, (dict, list, str, int, float, bool)) or state_value is None else {},
        "updated_by": normalize_email(updated_by),
    }
    try:
        supabase.table("dashboard_workspace_state").upsert(
            data,
            on_conflict="business_id,state_key",
        ).execute()
    except Exception as e:
        # Temporary safety-net if DB migration wasn't applied yet.
        log("Could not save workspace state", str(e))
        if business_id not in WORKSPACE_STATE_FALLBACK:
            WORKSPACE_STATE_FALLBACK[business_id] = {}
        WORKSPACE_STATE_FALLBACK[business_id][state_key] = data.get("state_value")


def list_business_operator_ids(business_id: str) -> list[str]:
    business_id = normalize_id(business_id)
    if not business_id:
        return []
    try:
        rows = (
            supabase.table("business_users")
            .select("user_email,role")
            .eq("business_id", business_id)
            .eq("role", "operator")
            .execute()
            .data
            or []
        )
        return sorted({normalize_email(row.get("user_email")) for row in rows if normalize_email(row.get("user_email"))})
    except Exception:
        return []


def append_operator_task(business_id: str, text: str, recipients: list[str], assign_mode: str, created_by: str) -> dict:
    business_id = normalize_id(business_id)
    clean_text = normalize_id(text)
    if not business_id or not clean_text:
        return {}

    safe_assign_mode = normalize_id(assign_mode).lower() or "all"
    allowed_modes = {"one", "group", "all"}
    if safe_assign_mode not in allowed_modes:
        safe_assign_mode = "all"

    all_operator_ids = list_business_operator_ids(business_id)
    normalized_recipients = [normalize_email(item) for item in (recipients or []) if normalize_email(item)]
    normalized_recipients = list(dict.fromkeys(normalized_recipients))

    if safe_assign_mode == "all" or "*" in normalized_recipients:
        final_recipients = ["*"]
    else:
        final_recipients = [item for item in normalized_recipients if item in set(all_operator_ids)]
        if not final_recipients and all_operator_ids:
            final_recipients = [all_operator_ids[0]]

    task = {
        "id": f"task_{int(time.time() * 1000)}_{secrets.token_hex(3)}",
        "text": clean_text,
        "recipients": final_recipients or ["*"],
        "assign_mode": safe_assign_mode,
        "created_by": normalize_email(created_by),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    state = get_workspace_state(business_id)
    existing = state.get("operator_tasks") or {}
    items = existing.get("items") if isinstance(existing, dict) else []
    if not isinstance(items, list):
        items = []

    next_items = [task] + items
    next_items = next_items[:200]
    payload = {"items": next_items}
    upsert_workspace_state(business_id, "operator_tasks", payload, updated_by=created_by)

    # Backward compatibility for dashboards still reading old key.
    legacy = state.get("operator_admin_notes") or {}
    legacy_items = legacy.get("items") if isinstance(legacy, dict) else []
    if not isinstance(legacy_items, list):
        legacy_items = []
    merged_legacy = [task] + legacy_items
    upsert_workspace_state(business_id, "operator_admin_notes", {"items": merged_legacy[:200]}, updated_by=created_by)

    return task


def merged_operator_task_items(state: dict) -> list[dict]:
    if not isinstance(state, dict):
        return []

    items = []
    for key in ("operator_tasks", "operator_admin_notes"):
        bucket = state.get(key) or {}
        bucket_items = bucket.get("items") if isinstance(bucket, dict) else []
        if isinstance(bucket_items, list):
            items.extend(bucket_items)

    merged = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = normalize_id(item.get("id")) or f"{normalize_id(item.get('created_at') or item.get('createdAt'))}:{normalize_id(item.get('text'))}"
        if item_id in seen:
            continue
        seen.add(item_id)
        recipients = item.get("recipients") if isinstance(item.get("recipients"), list) else ["*"]
        recipients = [normalize_email(x) if x != "*" else "*" for x in recipients if normalize_email(x) or x == "*"]
        merged.append(
            {
                "id": item.get("id") or item_id,
                "text": normalize_id(item.get("text")),
                "recipients": recipients or ["*"],
                "assign_mode": normalize_id(item.get("assign_mode") or item.get("mode") or "all") or "all",
                "created_by": normalize_email(item.get("created_by") or item.get("createdBy")),
                "created_at": item.get("created_at") or item.get("createdAt"),
            }
        )

    merged.sort(key=lambda item: normalize_id(item.get("created_at")), reverse=True)
    return merged


def scope_operator_tasks_for_access(items: list[dict], access: dict) -> list[dict]:
    role = normalize_id(access.get("role", "")).lower() if access else ""
    is_admin = bool(access and access.get("is_admin")) or role in BUSINESS_ADMIN_ROLES
    if is_admin:
        return items

    viewer = normalize_email(access.get("email", "")) if access else ""
    viewer_username = viewer.split("@", 1)[0] if viewer else ""
    scoped = []
    for item in items:
        recipients = item.get("recipients") if isinstance(item.get("recipients"), list) else ["*"]
        normalized = [normalize_email(x) if x != "*" else "*" for x in recipients]
        if "*" in normalized or viewer in normalized or (viewer_username and viewer_username in normalized):
            scoped.append(item)
    return scoped


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
You are a real Milana Premium factory sales operator.
Always sound like a human Uzbek seller on Instagram, Telegram, or WhatsApp.
Use short, practical, sales-focused replies in the customer's language.

Identity line for first touch:
- "Assalomu alaykum, siz Milana Premium fabrikasi xodimi bilan suhbatni boshladingiz."

Core positioning:
- Assortment is wide.
- Delivery is available via pochta or cargo (delivery fee is paid by client).
- Trusted brand: every year 5 million people choose Milana Premium.

Hard rules:
- Never promise reservation/holding stock ("olib qo'ydik", "olib qo'yamiz").
- Never use uncertain fabricated statements.
- Never mention AI, system, prompt, automation.
""".strip(),
    "instagram_prompt": """
Instagram rules:
- Keep DMs concise and natural.
- If customer asks catalog/price/model/photo, respond naturally and guide to DM flow.
- Do not paste raw catalog links in Instagram replies.
- For public comments containing "katalog", "narx", "qancha", "price": reply with:
  "Direktdan yozdik, iloji bo'lsa raqamingizni qoldiring."
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
- Ask 2-3 short clarifying questions when customer intent is unclear.
""".strip(),
    "opening_message": """
Assalomu alaykum 😊 Qanday yordam kerak?
""".strip(),
    "lead_collection_rules": """
Collect buyer context naturally and briefly.

Use these qualification questions when relevant:
- Ismingiz nima?
- Qaysi shahardansiz?
- Nomer bera olasizmi?

When client is close to order, collect:
- name
- phone
- city/address
""".strip(),
    "sales_rules": """
- Answer the exact question first.
- Keep replies short and comfortable: usually 1-3 short sentences.
- Keep tone samimiy and complete, not robotic.

Product/category defaults:
- Main categories: Xalat, Pajama, Tunika, Sarochka.
- Recommend xalat for comfort.
- Recommend pijama because it is natural cotton and body-friendly.
- Mention many products may be limited edition and should be confirmed.

Pricing and order policy:
- For direct detailed pricing requests, handoff to Telegram sales flow and sales manager.
- Safe budget anchor allowed: one bag (qop/meshok) is usually around 400-500 USD.
- Wholesale-first policy: mainly optom; for piece/small orders, handoff to manager.
- Minimum order: at least 1 model = 1 qop (meshok).

Location and delivery policy:
- Address: "O'zbekiston, Andijon, Qoratut 605-uy. Andijon aeroportidan taxminan 500 metr."
- Delivery: provide cargo number and ask client to coordinate directly with cargo service.

Payment and warranty policy:
- Payment details are explained by manager: +998501551010
- If product has factory defect, factory compensates or sends replacement.

Objection handling:
- If "qimmat": emphasize quality value briefly.
- If "keyin olaman": ask polite follow-up about purchase timing.
- If comparing other stores: stay respectful, no pressure.

Forbidden phrases:
- Never say: "Biz sizga tovar sotmaymiz."
""".strip(),
    "handoff_rules": """
Handoff immediately when:
- customer says they want wholesale/optom
- customer asks for final exact deal terms
- customer is angry/frustrated
- payment/contract specifics are requested

Handoff closing line:
- "Sizni menejerimiz bilan bog'layman: +998501551010"

Do not invent information before handoff.
""".strip(),
}


AI_PROMPT_SETTING_FIELDS = set(DEFAULT_AI_PROMPT_SETTINGS.keys())


MILANA_RESPONSE_GUARDRAILS = """
Milana Premium Q&A policy. Always enforce these rules even if saved prompt settings say otherwise.

Business-only scope:
- Only answer questions about Milana Premium, women's clothing products, catalog, price/order flow, wholesale, delivery/cargo, payment, address, warranty/defects, and manager handoff.
- If the customer asks about unrelated topics (politics, school homework, coding, general facts, jokes, medicine, law, weather, religion, personal advice, or anything outside Milana Premium sales), do not answer the topic.
- For unrelated topics, reply briefly in the customer's language: "Kechirasiz, men faqat Milana Premium mahsulotlari, katalog, narx va buyurtma bo'yicha yordam bera olaman. Katalog kerakmi yoki menejer bilan bog'laymi?"

PDF sales-agent rules:
- First-touch identity: "Assalomu alaykum, siz Milana Premium fabrikasi xodimi bilan suhbatni boshladingiz."
- Strong points: wide assortment, delivery by pochta/cargo, client pays delivery, trusted by 5 million customers yearly.
- Tone: samimiy, short, practical, complete enough to help the customer buy.
- Categories: Xalat, Pajama, Tunika, Sarochka.
- Recommend xalat for comfort and pajama because it is natural cotton and body-friendly.
- Ask qualification questions naturally: name, city, phone number.
- Products are limited edition; availability should be confirmed, never invented.
- Never say stock is reserved or will be reserved ("olib qo'ydik", "olib qo'yamiz").
- Never invent price, discount, stock, delivery time, payment terms, or availability.
- Exact price should not be invented. If asked price, guide toward Telegram/sales manager; safe anchor: one qop/meshok is around 400-500 USD.
- Do not claim prices changed or will change unless the manager confirms it.
- Wholesale-first: mostly optom. For small/piece orders, handoff to manager.
- Minimum order: one model from one qop/meshok.
- Address: "O'zbekiston, Andijon, Qoratut 605-uy. Andijon aeroportidan taxminan 500 metr."
- Delivery: give cargo number/process and ask client to coordinate with cargo service.
- Payment: manager explains payment via +998501551010.
- Warranty: if factory defect appears, factory pays/compensates or sends replacement.
- Comment keywords "katalog", "narx", "qancha", "price": public reply "Direktdan yozdik, iloji bo'lsa raqamingizni qoldiring."
- DM catalog follow-up: "Assalomu alaykum, bizga qiziqish bildirgan ekansiz. Biz bilan hamkorlik qilmoqchimisiz?"
- When customer asks for photo/video/catalog, answer warmly with one light smile/emoji-style touch; do not over-explain.
- Reply separately to each commenter; do not combine multiple customers into one response.
- Sticker-only/simple reactions: answer with a simple friendly emoji/sticker-style short reply, not a sales paragraph.
- If "qimmat": acknowledge and position quality, e.g. "Albatta, tovarimiz qimmat, lekin sizga sifatni taklif qilyapmiz."
- If "keyin olaman" or silent follow-up: ask when they plan to buy.
- If comparing with another shop: be respectful; no pressure.
- Buying signs: asks for card, cargo, exact order flow, or says wholesale/optom.
- Closing question should be safe: "Sizga bu modeldan nechta qop kerak bo'ladi?"
- Handoff immediately for optom intent, angry/norozi customer, payment details, or exact final order terms.
- Handoff line: "Sizni menejerimiz bilan bog'layman: +998501551010"
- If bot made spelling/meaning mistake, apologize briefly and correct it.
- Never say: "Biz sizga tovar sotmaymiz."
""".strip()


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
        "- First answer the customer's question, then ask 2-3 short clarifying questions when needed.",
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


def is_valid_prompt_suggestion(text: str) -> bool:
    candidate = (text or "").strip()
    if not candidate:
        return False
    if len(candidate) < 120:
        return False
    if candidate.count("\n") < 3:
        return False

    lower = candidate.lower()
    required_markers = ["- reply", "- do not", "- ask"]
    if not any(marker in lower for marker in required_markers):
        return False

    bad_starts = (
        "xabaringiz qabul qilindi",
        "assalomu alaykum",
        "salom",
        "hello",
        "hi ",
        "thanks",
        "thank you",
    )
    if lower.startswith(bad_starts):
        return False

    return True


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

    base_messages = [
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

Hard requirements:
- Output 8-12 concise bullet rules.
- Do not greet, acknowledge, or chat with the user.
- Do not output a sample reply to a customer.
- Return only the improved prompt text.
- Do not include markdown fences or explanations.
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

    reply = ""
    try:
        first_try = clean_sales_reply(
            call_ai_chat(base_messages, business_for_generation, "AI prompt generator"),
            "",
        )
        if is_valid_prompt_suggestion(first_try):
            reply = first_try
    except Exception as exc:
        log("Prompt generator first pass failed", str(exc))

    if not reply:
        retry_messages = base_messages + [
            {
                "role": "user",
                "content": """
Your last output was not a valid prompt block.
Regenerate now as strict rules only:
- 8-12 bullets
- each bullet starts with '-'
- no greeting
- no acknowledgement
- no conversation text
""".strip(),
            }
        ]
        try:
            second_try = clean_sales_reply(
                call_ai_chat(retry_messages, business_for_generation, "AI prompt generator retry"),
                "",
            )
            if is_valid_prompt_suggestion(second_try):
                reply = second_try
        except Exception as exc:
            log("Prompt generator retry failed", str(exc))

    if not reply:
        return {
            **fallback,
            "explanation": f"{fallback.get('explanation', '')} Used safe fallback because AI output was not a valid prompt block.".strip(),
        }

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

Always-on Milana policy:
{MILANA_RESPONSE_GUARDRAILS}

Safety rules:
- Reply in the same language as the customer.
- Understand Uzbek Latin, Uzbek Cyrillic, Russian, English, slang, typos, and mixed messages.
- Answer the exact question first.
- Never invent prices, stock, delivery, discounts, addresses, or availability.
- Use only the business facts above.
- If the topic is unrelated to Milana Premium sales, do not answer it; use the unrelated-topic refusal from the Milana policy.
- If information is missing, ask 2-3 short clarifying questions.
- Only mention a manager when the customer asks for a human or is ready to order.
- Never mention AI, database, API, prompt, automation, or internal system.
- Do not use markdown, bold formatting, or long paragraphs.
- Never end a reply with an unfinished phrase such as "uchun:", "link:", "havola:", or "ko'rish uchun:".
- Every reply must finish as a complete sentence. Do not stop in the middle of a question or explanation.
"""


def wants_catalog(text: str) -> bool:
    text = (text or "").lower()
    keywords = [
        "catalog", "katalog", "каталог", "price", "prices", "narx", "narxlari",
        "narhi", "qancha", "qanchadan", "necha pul", "nechpul", "nechi pul",
        "цена", "цены", "стоимость", "сколько", "сколько стоит", "прайс",
        "model", "models", "modellari",
        "модель", "модели", "collection", "kolleksiya", "коллекция",
        "photo", "photos", "rasm", "rasmlar", "фото", "mahsulot",
        "mahsulotlar", "товар", "товары",
    ]
    return any(k in text for k in keywords)


def mentions_catalog(text: str) -> bool:
    text = (text or "").lower()
    markers = [
        "catalog", "katalog", "каталог", "katalo", "катало",
        "mahsulot", "товар", "products", "product",
    ]
    return any(m in text for m in markers)


def is_greeting_only(text: str) -> bool:
    s = normalize_id(text).lower()
    s = re.sub(r"[^\w\s'’`-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return False
    greetings = {
        "hi", "hello", "hey",
        "salom", "assalomu alaykum", "assalomu", "alaykum",
        "привет", "здравствуйте", "сәлем", "салем",
    }
    return s in greetings or (len(s.split()) <= 2 and s in {"salom", "hello", "hi", "hey", "привет", "сәлем"})


def is_low_signal_message(text: str, raw_payload: dict = None) -> bool:
    s = normalize_id(text)
    if not s:
        return False

    compact = re.sub(r"\s+", "", s)
    emoji_only_re = re.compile(r"^[\u2600-\u27BF\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF\u200d\ufe0f]+$")
    if compact and emoji_only_re.fullmatch(compact):
        return True

    # Common lightweight reactions we should not auto-reply to.
    if compact in {"+", "++", "ok", "okk", "👍", "❤️", "🔥", "👏", "😂"}:
        return True

    payload = raw_payload or {}
    message = payload.get("message") if isinstance(payload, dict) else {}
    if isinstance(message, dict):
        # Story reaction/quick reaction style payloads often carry explicit markers.
        if message.get("is_story_reply") or message.get("story"):
            return True
        if message.get("reaction") and not (message.get("text") or "").strip():
            return True

    return False


def is_auto_media_placeholder_message(text: str) -> bool:
    s = normalize_id(text).strip().lower()
    return s in {
        "📸 photo",
        "🎥 video",
        "🎤 audio",
        "📎 file",
        "📎 attachment",
        "🔁 forwarded post",
        "🔁 forwarded reel",
    }


def wants_deal_handoff(text: str) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    markers = [
        "deal", "make a deal", "close deal", "contract", "partnership", "wholesale", "bulk order",
        "заказ", "оформить", "договор", "оптом", "сделка", "куплю",
        "zakaz", "buyurtma", "ulgurji", "kelishuv", "sotib olaman", "olaman",
        "мәміле", "тапсырыс", "көтерме", "келісім",
    ]
    return any(m in s for m in markers)


def detect_customer_language(text: str) -> str:
    text = normalize_id(text)
    lower = text.lower()
    if not lower:
        return ""

    english_words = {
        "hi", "hello", "hey", "can", "could", "would", "make", "purchase", "buy", "order",
        "price", "how", "much", "where", "shipping", "delivery", "catalog", "available",
        "need", "want", "please", "thanks", "thank", "size", "color", "model",
    }
    uzbek_latin_markers = {
        "salom", "assalomu", "alaykum", "narx", "qancha", "qayer", "kerak", "olmoq",
        "sotib", "mahsulot", "katalog", "manzil", "rahmat", "bormi", "necha",
    }
    kazakh_markers = {
        "сәлем", "салем", "қалай", "баға", "бағасы", "қанша", "қажет", "жеткізу",
        "тапсырыс", "каталог", "тауар", "бар", "мен", "сіз", "үшін",
    }
    russian_words = {
        "здравствуйте", "привет", "цена", "сколько", "купить", "заказ", "доставка",
        "каталог", "размер", "цвет", "модель", "есть", "можно",
    }

    words = set(re.findall(r"[a-zA-Z']+|[А-Яа-яЁё]+", lower))
    if any(m in lower for m in kazakh_markers):
        return "kk"
    if words & russian_words:
        return "ru"
    if words & english_words and not (words & uzbek_latin_markers):
        return "en"
    if re.search(r"[А-Яа-яЁё]", lower):
        return "ru"
    if words & uzbek_latin_markers:
        return "uz"
    return ""


def language_instruction_for(text: str) -> str:
    lang = detect_customer_language(text)
    if lang == "en":
        return "The latest customer message is in English. Reply only in English. Do not use Uzbek, Russian, or Kazakh words."
    if lang == "ru":
        return "Последнее сообщение клиента на русском. Отвечай только на русском языке."
    if lang == "kk":
        return "Клиенттің соңғы хабары қазақ тілінде. Тек қазақ тілінде жауап бер."
    if lang == "uz":
        return "Mijozning oxirgi xabari o'zbek tilida. Faqat o'zbek tilida javob ber."
    return ""


def media_matcher_language(text: str) -> str:
    lang = detect_customer_language(text)
    if lang in {"uz", "ru", "en"}:
        return lang
    return "uz"


def product_matcher_health_url(api_url: str) -> str:
    api_url = normalize_id(api_url)
    if not api_url:
        return ""
    if api_url.endswith("/api/process-media-url"):
        return api_url[:-len("/api/process-media-url")] + "/health"
    if api_url.endswith("/api/process-media"):
        return api_url[:-len("/api/process-media")] + "/health"
    return api_url.rstrip("/") + "/health"


def product_matcher_file_url(api_url: str) -> str:
    api_url = normalize_id(api_url)
    if not api_url:
        return ""
    if api_url.endswith("/api/process-media-url"):
        return api_url[:-len("/api/process-media-url")] + "/api/process-media"
    if api_url.endswith("/api/process-media"):
        return api_url
    return api_url.rstrip("/") + "/api/process-media"


def download_media_for_matcher(media_url: str) -> tuple[bytes, str, str]:
    media_url = normalize_id(media_url)
    if not media_url:
        raise ValueError("Empty media URL")
    limit_bytes = PRODUCT_MATCHER_MAX_MEDIA_MB * 1024 * 1024
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "*/*",
    }
    response = requests.get(media_url, timeout=min(PRODUCT_MATCHER_TIMEOUT_SECONDS, 20), stream=True, headers=headers)
    response.raise_for_status()
    content_type = normalize_id(response.headers.get("content-type")).split(";")[0].strip() or "application/octet-stream"
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit_bytes:
            raise ValueError(f"Media is too large (> {PRODUCT_MATCHER_MAX_MEDIA_MB} MB)")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise ValueError("Downloaded media is empty")

    ext = mimetypes.guess_extension(content_type) or ".bin"
    filename = f"media{ext}"
    return data, filename, content_type


def _safe_score(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def analyze_media_for_sales_reply(media_url: str, user_text: str, media_type: str = "") -> dict:
    media_url = normalize_id(media_url)
    if not PRODUCT_MATCHER_ENABLED or not PRODUCT_MATCHER_API_URLS or not media_url:
        return {}

    if media_type and media_type not in {"photo", "video", "file"}:
        return {}

    payload = {
        "media_url": media_url,
        "user_message": user_text or "",
        "language": media_matcher_language(user_text),
        "top_k": PRODUCT_MATCHER_TOP_K,
    }

    response = None
    body = {}
    last_upload_error = ""
    last_url_error = ""

    # Upload-first strategy: avoids frequent 403 on short-lived Instagram CDN links.
    try:
        media_bytes, filename, mime_type = download_media_for_matcher(media_url)
    except Exception as exc:
        media_bytes = b""
        filename = ""
        mime_type = ""
        last_upload_error = f"download: {exc}"

    if media_bytes:
        upload_data = {
            "user_message": user_text or "",
            "language": media_matcher_language(user_text),
            "top_k": str(PRODUCT_MATCHER_TOP_K),
        }
        upload_files = {
            "file": (filename, media_bytes, mime_type),
        }

        for matcher_url in PRODUCT_MATCHER_API_URLS:
            upload_url = product_matcher_file_url(matcher_url)
            try:
                response = requests.post(
                    upload_url,
                    data=upload_data,
                    files=upload_files,
                    timeout=max(PRODUCT_MATCHER_TIMEOUT_SECONDS, 30),
                )
            except Exception as exc:
                last_upload_error = f"{upload_url}: {exc}"
                continue
            if not response.ok:
                last_upload_error = f"{upload_url}: HTTP {response.status_code}"
                continue
            body = safe_json(response)
            if isinstance(body, dict) and body.get("status") == "ok":
                break
            last_upload_error = f"{upload_url}: invalid response shape"
        else:
            body = {}

    # Fallback to URL mode if upload mode fails.
    if not (isinstance(body, dict) and body.get("status") == "ok"):
        for matcher_url in PRODUCT_MATCHER_API_URLS:
            try:
                response = requests.post(
                    matcher_url,
                    json=payload,
                    timeout=PRODUCT_MATCHER_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                last_url_error = f"{matcher_url}: {exc}"
                continue
            if not response.ok:
                last_url_error = f"{matcher_url}: HTTP {response.status_code}"
                continue
            body = safe_json(response)
            if isinstance(body, dict) and body.get("status") == "ok":
                break
            last_url_error = f"{matcher_url}: invalid response shape"
        else:
            body = {}

    if not (isinstance(body, dict) and body.get("status") == "ok"):
        log(
            "Media matcher call failed",
            {"upload_mode": last_upload_error or "n/a", "url_mode": last_url_error or "n/a"},
        )
        return {}

    matches = body.get("matches") if isinstance(body.get("matches"), list) else []
    top = matches[0] if matches else {}
    top_score = _safe_score(top.get("score"))
    extracted_codes = body.get("extracted_codes") if isinstance(body.get("extracted_codes"), list) else []

    if top_score < PRODUCT_MATCHER_MIN_SCORE and not extracted_codes:
        return {}

    code = normalize_id(top.get("product_code"))
    model = normalize_id(top.get("model_code"))
    price = normalize_id(top.get("price"))
    currency = normalize_id(top.get("currency"))
    parts = []
    if code:
        parts.append(f"code={code}")
    if model:
        parts.append(f"model={model}")
    if price:
        parts.append(f"price={price} {currency}".strip())

    alternatives = []
    for item in matches[1:3]:
        alt_code = normalize_id(item.get("product_code"))
        alt_model = normalize_id(item.get("model_code"))
        alt_score = _safe_score(item.get("score"))
        if alt_code or alt_model:
            alternatives.append(f"{alt_code or alt_model} ({alt_score:.2f})")

    context_lines = [
        "Product media analysis (high-priority context for this customer message):",
        f"- Top match confidence: {top_score:.2f}",
    ]
    if parts:
        context_lines.append(f"- Top match details: {', '.join(parts)}")
    if extracted_codes:
        context_lines.append(f"- Extracted codes from media/text: {', '.join(str(x) for x in extracted_codes[:6])}")
    if alternatives:
        context_lines.append(f"- Alternatives: {', '.join(alternatives)}")
    context_lines.append("- Use this to answer product/price questions for the attached media.")

    return {
        "context": "\n".join(context_lines),
        "reply_hint": normalize_id(body.get("llm_reply")),
        "top_score": top_score,
        "top_match_code": code,
        "top_match_model": model,
    }


def _instagram_media_memory_key(business_id: str, customer_id: str) -> str:
    business_id = normalize_id(business_id)
    customer_id = normalize_id(customer_id)
    if not business_id or not customer_id:
        return ""
    return f"{business_id}:{customer_id}"


def remember_instagram_media_match(
    business_id: str,
    customer_id: str,
    context: str,
    reply_hint: str = "",
    top_match_code: str = "",
    top_match_model: str = "",
    top_score: float = 0.0,
):
    key = _instagram_media_memory_key(business_id, customer_id)
    if not key or not normalize_id(context):
        return
    INSTAGRAM_MEDIA_MATCH_MEMORY[key] = {
        "saved_at": time.time(),
        "context": normalize_id(context),
        "reply_hint": normalize_id(reply_hint),
        "top_match_code": normalize_id(top_match_code),
        "top_match_model": normalize_id(top_match_model),
        "top_score": _safe_score(top_score),
    }


def load_recent_instagram_media_match(business_id: str, customer_id: str) -> dict:
    key = _instagram_media_memory_key(business_id, customer_id)
    if not key:
        return {}
    payload = INSTAGRAM_MEDIA_MATCH_MEMORY.get(key)
    if not isinstance(payload, dict):
        return {}
    saved_at = float(payload.get("saved_at") or 0.0)
    if (time.time() - saved_at) > PRODUCT_MATCHER_CONTEXT_TTL_SECONDS:
        INSTAGRAM_MEDIA_MATCH_MEMORY.pop(key, None)
        return {}
    return payload


def should_reuse_recent_media_match(user_text: str, media_type: str = "") -> bool:
    if media_type in {"photo", "video", "file"}:
        return False
    text = normalize_id(user_text)
    if not text:
        return False
    lower = text.lower()
    # Typical follow-up buying messages that refer to the previously sent product image.
    if re.search(r"\b\d+\s*(qop|meshok|ta|dona|pack|quti)\b", lower):
        return True
    if has_strong_milana_sales_context(lower):
        return True
    short_followups = {"bor", "bormi", "narxi", "qancha", "razmer", "rang", "olaman", "zakaz", "беру", "есть"}
    return lower in short_followups


def has_strong_milana_sales_context(text: str) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    if mentions_catalog(s):
        return True
    markers = [
        "milana", "premium", "fabrika", "factory", "фабрика",
        "xalat", "halat", "robe", "халат", "pijama", "pajama", "пижама",
        "tunika", "туника", "sarochka", "сорочка", "kiyim", "clothes", "одежда",
        "ayollar", "women", "женск", "model", "модель", "rang", "color", "цвет",
        "razmer", "size", "размер", "sifat", "quality", "качество",
        "qop", "meshok", "мешок", "sumka", "pack", "bag",
        "optom", "optima", "ulgurji", "wholesale", "оптом", "опт",
        "dostavka", "delivery", "yetkaz", "yetqaz", "доставка", "pochta", "почта",
        "cargo", "kargo", "карго", "manzil", "address", "адрес", "qayerdasiz",
        "where are you", "where located", "location", "lokatsiya", "локация",
        "telefon", "phone number", "nomer", "raqam", "номер", "связаться",
        "menejer", "manager", "менеджер", "admin", "админ",
        "brak", "defect", "warranty", "garantiya", "гарантия", "qaytar",
        "qimmat", "arzon", "expensive", "cheap", "дорого", "дешево",
        "bor", "bormi", "mavjud", "available", "есть", "в наличии",
        "hamkorlik", "partnership", "сотрудничество", "ish vaqti", "working hours",
    ]
    return any(marker in s for marker in markers)


def has_milana_sales_context(text: str) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    if has_strong_milana_sales_context(s) or wants_catalog(s) or wants_deal_handoff(s):
        return True
    generic_sales_markers = [
        "kerak", "need", "want", "хочу", "interested", "qiziq", "интерес",
        "tanlash", "choose", "выбрать", "ko'rsat", "korsat", "show me", "покажите",
    ]
    return any(marker in s for marker in generic_sales_markers)


def is_obviously_unrelated_topic(text: str) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    if is_greeting_only(s) or is_low_signal_message(s):
        return False
    if has_strong_milana_sales_context(s):
        return False

    unrelated_markers = [
        "ob havo", "ob-havo", "weather", "погода", "ауа райы",
        "hazil", "anekdot", "joke", "tell me a joke", "шутка", "анекдот", "kuldir",
        "python", "javascript", "react", "frontend", "backend", "html", "css",
        "write code", "kod yoz", "code yoz", "dastur tuz", "программ", "написать код",
        "prezident", "president", "siyosat", "politics", "saylov", "election",
        "президент", "политика", "выборы", "правительство",
        "uy vazifa", "uyga vazifa", "homework", "essay", "referat", "matematika",
        "math", "tarix", "history", "solve", "реши", "сочинение", "реферат",
        "doctor", "medicine", "dori", "shifokor", "kasal", "врач", "лекарство", "болезн",
        "lawyer", "legal", "law", "advokat", "yurist", "qonun", "юрист", "адвокат", "закон",
        "namoz", "quron", "qur'on", "hadis", "religion", "дин", "намаз", "коран",
        "sevgi", "relationship", "boyfriend", "girlfriend", "oilaviy muammo",
        "news", "новости", "futbol", "football", "kurs valyuta", "dollar kursi", "курс доллара",
        "bitcoin", "crypto", "btc", "iphone", "samsung", "pizza", "restaurant",
        "translate", "tarjima qil", "переведи", "who is", "what is", "tell me about",
    ]
    if any(marker in s for marker in unrelated_markers):
        return True

    if re.search(r"\b\d+\s*[\+\-\*/]\s*\d+\b", s):
        return True

    if has_milana_sales_context(s):
        return False

    return False


def unrelated_topic_reply(text: str) -> str:
    if not is_obviously_unrelated_topic(text):
        return ""
    lang = detect_customer_language(text)
    if lang == "en":
        return "Sorry, I can only help with Milana Premium products, catalog, prices, and orders. Do you need the catalog or should I connect you with a manager?"
    if lang == "ru":
        return "Извините, я могу помочь только с товарами Milana Premium, каталогом, ценами и заказом. Нужен каталог или связать вас с менеджером?"
    if lang == "kk":
        return "Кешіріңіз, мен тек Milana Premium тауарлары, каталог, баға және тапсырыс бойынша көмектесе аламын. Каталог керек пе әлде менеджермен байланыстырайын ба?"
    return "Kechirasiz, men faqat Milana Premium mahsulotlari, katalog, narx va buyurtma bo'yicha yordam bera olaman. Katalog kerakmi yoki menejer bilan bog'laymi?"


def get_catalog_link(business: dict) -> str:
    link = business.get("catalog_link") or business.get("catalog") or business.get("website") or ""
    link = str(link).strip()
    if link and not link.startswith(("http://", "https://")):
        link = "https://" + link
    return link


def remove_urls(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "").strip()
    text = re.sub(r"\s+", " ", text).strip()
    return strip_incomplete_reply(text)


def strip_incomplete_reply(text: str) -> str:
    text = normalize_id(text)
    if not text:
        return ""

    trailing_patterns = [
        r"\s*(?:joylashuv xaritasini\s*)?(?:ko['‘’`]?rish|ochish)\s+uchun\s*[:：]?\s*$",
        r"\s*(?:xarita|lokatsiya|location|map|manzil linki|ссылка|карта)[^.!?]{0,100}\s*[:：]\s*$",
        r"\s*(?:link|havola|ссылка)\s*[:：]\s*$",
    ]
    for pattern in trailing_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

    # If URL removal leaves a final unfinished clause after a complete sentence, drop it.
    if re.search(r"[:：]\s*$", text):
        last_stop = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
        if last_stop >= 0:
            fragment = text[last_stop + 1:].strip().lower()
            if any(word in fragment for word in ["uchun", "link", "havola", "xarita", "map", "ссылка", "карта"]):
                text = text[:last_stop + 1].strip()

    return text.rstrip(" :：,;-").strip()


def complete_sentence_reply(text: str, limit: int = 950) -> str:
    text = strip_incomplete_reply(text)
    if not text:
        return ""

    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].strip()
        text = strip_incomplete_reply(text)

    sentence_end = ".!?。！？"
    soft_endings = ("😊", "👍", "🙌", "✅")
    if text.endswith(tuple(sentence_end)) or text.endswith(soft_endings):
        return text

    last_stop = max(text.rfind("."), text.rfind("!"), text.rfind("?"), text.rfind("。"), text.rfind("！"), text.rfind("？"))
    if last_stop >= 40:
        return strip_incomplete_reply(text[:last_stop + 1])

    return text.rstrip(" :：,;-").strip() + "."


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


def catalog_subtitle_text(raw_text: str, business: dict) -> str:
    text = clean_ai_reply_for_catalog(raw_text, business)
    text = complete_sentence_reply(text, limit=78)
    if text and len(text) <= 78:
        return text

    # Keep template subtitle short and always complete.
    lang = detect_customer_language(text)
    if lang == "ru":
        return "Нажмите кнопку ниже, чтобы открыть каталог."
    if lang == "en":
        return "Tap the button below to open the catalog."
    return "Quyidagi tugma orqali katalogni oching."


def catalog_template_payload(recipient: dict, business: dict, text: str = "") -> dict:
    catalog_link = get_catalog_link(business)
    business_name = normalize_id((business or {}).get("business_name")) or "Milana Premium"
    subtitle = catalog_subtitle_text(text, business)
    if not subtitle:
        subtitle = f"{business_name} katalogi shu yerda."

    return {
        "recipient": recipient,
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "generic",
                    "elements": [
                        {
                            "title": "Katalogni ko'rish",
                            "subtitle": subtitle,
                            "default_action": {
                                "type": "web_url",
                                "url": catalog_link,
                            },
                            "buttons": [
                                {
                                    "type": "web_url",
                                    "url": catalog_link,
                                    "title": "Katalogni ko'rish",
                                }
                            ],
                        }
                    ],
                },
            }
        },
    }


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
    if model.startswith("mistral"):
        return "mistral"
    return "openai"


def infer_ai_provider_strict(model: str) -> str:
    model = str(model or "").lower()
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if model.startswith("gemini"):
        return "gemini"
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("mistral"):
        return "mistral"
    return ""


def get_ai_provider(business: dict) -> str:
    provider = str(business.get("ai_provider") or "").strip().lower()
    inferred = infer_ai_provider_strict(business.get("ai_model"))
    if inferred and inferred != provider:
        return inferred
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
    max_tokens = max(220, int(business.get("ai_max_tokens", 220) or 220))

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
    lang = detect_customer_language(user_text)

    if wants_deal_handoff(user_text):
        if lang == "en":
            return "Great, for final order details please contact our manager: +998501551010."
        if lang == "ru":
            return "Отлично, по финальным деталям заказа свяжитесь с нашим менеджером: +998501551010."
        if lang == "kk":
            return "Керемет, тапсырыстың соңғы шарттары үшін менеджерімізге хабарласыңыз: +998501551010."
        return "Sizni menejerimiz bilan bog'layman: +998501551010"

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
        if lang == "en":
            return "Of course."
        if lang == "ru":
            return "Конечно."
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
        if lang == "en":
            return "Understood. I will keep replies simpler and shorter."
        if lang == "ru":
            return "Понял. Буду отвечать проще и короче."
        return "Tushundim 👍 Oddiyroq va qisqa javob beraman."

    if any(phrase in user for phrase in [
        "ololmayapman",
        "ololmayman",
        "qarzga",
        "hozircha olmayman",
        "hozircha yo'q",
        "keyinroq",
        "pul yo'q",
    ]):
        if lang == "en":
            return "No problem. Write whenever it is convenient for you."
        if lang == "ru":
            return "Понимаю. Напишите, когда вам будет удобно."
        return "Tushunarli 😊 Muammo emas, qachon qulay bo'lsa yozing."

    text = normalize_id(reply_text)
    if not text:
        if lang == "en":
            return "Your message has been received."
        if lang == "ru":
            return "Ваше сообщение получено."
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

    text = complete_sentence_reply(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # If customer asked price but reply has no numeric price hint, force concise pricing follow-up.
    price_ask = any(k in user for k in ["narx", "nechpul", "qancha", "цена", "сколько", "price"])
    has_number = bool(re.search(r"\d", text))
    if price_ask and not has_number:
        if lang == "en":
            text = (
                "Our manager explains exact prices. One qop/meshok is usually around 400-500 USD. "
                "Which model do you need?"
            )
        elif lang == "kk":
            text = (
                "Нақты бағаны менеджеріміз түсіндіреді. Бір қоп/қап әдетте 400-500 USD шамасында. "
                "Қай модель керек?"
            )
        elif lang == "ru":
            text = (
                "Точную цену объяснит наш менеджер. Один мешок обычно около 400-500 USD. "
                "Какая модель нужна?"
            )
        else:
            text = (
                "Aniq narxni menejerimiz tushuntiradi. 1 qop odatda 400-500 dollar atrofida bo'ladi. "
                "Sizga qaysi model kerak?"
            )

    # Strong language guard: if customer wrote in English but reply is not English, return safe English fallback.
    if lang == "en":
        has_cyr = bool(re.search(r"[А-Яа-яЁё]", text))
        uz_markers = ("salom", "assalomu", "alaykum", "qaysi", "mahsulot", "katalog")
        low = text.lower()
        if has_cyr or any(m in low for m in uz_markers):
            if price_ask:
                text = (
                    "Our manager explains exact prices. One qop/meshok is usually around 400-500 USD. "
                    "Which model do you need?"
                )
            else:
                text = "Hello! Of course. Which products are you interested in?"

    # Never push catalog on simple greetings.
    if is_greeting_only(user_text) and mentions_catalog(text):
        if lang == "en":
            text = "Hello! How can I help you today?"
        elif lang == "ru":
            text = "Здравствуйте! Чем могу помочь?"
        elif lang == "kk":
            text = "Сәлеметсіз бе! Қалай көмектесе аламын?"
        else:
            text = "Assalomu alaykum 😊 Qanday yordam kerak?"

    text = complete_sentence_reply(text, limit=900)

    if text:
        return text
    if lang == "en":
        return "Understood."
    if lang == "kk":
        return "Түсіндім."
    if lang == "ru":
        return "Понял."
    return "Tushunarli 👍"


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

def get_ai_reply(
    user_text: str,
    business: dict,
    platform: str = "instagram",
    customer_id: str = "",
    channel: str = "",
    post_id: str = "",
    post_permalink: str = "",
    media_context: str = "",
    media_reply_hint: str = "",
):
    try:
        off_topic_reply = unrelated_topic_reply(user_text)
        if off_topic_reply:
            return off_topic_reply

        messages = [{"role": "system", "content": build_sales_system_prompt(business, platform)}]
        if platform == "instagram":
            post_context = build_instagram_post_reply_context(
                business=business,
                customer_id=customer_id,
                channel=channel or "dm",
                post_id=post_id,
                post_permalink=post_permalink,
            )
            if post_context:
                messages.append({"role": "system", "content": post_context})
        if media_context:
            messages.append({"role": "system", "content": media_context})
        messages.extend(get_recent_platform_chat_history(platform, business, customer_id, channel, limit=8))
        language_instruction = language_instruction_for(user_text)
        if language_instruction:
            messages.append({"role": "system", "content": language_instruction})
        messages.append({"role": "user", "content": user_text})

        reply = call_ai_chat(
            messages,
            business,
            "AI response",
        )
        if reply:
            return clean_sales_reply(reply.strip(), user_text)
        if media_reply_hint:
            return clean_sales_reply(media_reply_hint, user_text)
        lang = detect_customer_language(user_text)
        if lang == "en":
            return "Your message has been received."
        if lang == "kk":
            return "Хабарыңыз қабылданды."
        if lang == "ru":
            return "Ваше сообщение получено."
        return "Xabaringiz qabul qilindi 😊"

    except Exception as e:
        log("AI error", str(e))
        lang = detect_customer_language(user_text)
        if lang == "en":
            return "Your message has been received."
        if lang == "kk":
            return "Хабарыңыз қабылданды."
        if lang == "ru":
            return "Ваше сообщение получено."
        return "Xabaringiz qabul qilindi 😊"


# ============================================================================
# INSTAGRAM
# ============================================================================
def get_business_access_token(business: dict):
    candidates = get_instagram_token_candidates(business)
    return candidates[0][1] if candidates else ""


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

    payload = catalog_template_payload({"id": recipient_id}, business, text)

    if business.get("oauth_provider") == "facebook_page":
        payload["messaging_type"] = "RESPONSE"

    return send_instagram_payload(access_token, business, payload)


def send_instagram_private_reply(access_token: str, comment_id: str, text: str, business: dict = None):
    comment_id = normalize_id(comment_id)
    if not access_token or not comment_id or not text:
        return None

    business = business or {}
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": text[:1000]},
    }

    if business.get("oauth_provider") == "facebook_page":
        payload["messaging_type"] = "RESPONSE"

    return send_instagram_payload(access_token, business, payload)


def send_catalog_private_reply(access_token: str, comment_id: str, business: dict):
    catalog_link = get_catalog_link(business)
    comment_id = normalize_id(comment_id)
    if not access_token or not comment_id or not catalog_link:
        return None

    business = business or {}
    business_name = normalize_id(business.get("business_name")) or "Milana Premium"
    text = f"Assalomu alaykum! {business_name} katalogi shu yerda. Qaysi mahsulotlar sizni qiziqtirmoqda?"
    payload = catalog_template_payload({"comment_id": comment_id}, business, text)

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
    post_permalink = ""
    post_image_url = ""
    post_media_type = ""
    share_asset_id = ""

    attachments = message.get("attachments", [])
    if attachments:
        attachment_had_media = False
        for att in attachments:
            if not isinstance(att, dict):
                continue

            att_type = normalize_id(att.get("type")).lower()
            payload = att.get("payload") if isinstance(att.get("payload"), dict) else {}

            url_candidates = []

            def collect_urls(value):
                if isinstance(value, dict):
                    for nested in value.values():
                        collect_urls(nested)
                    return
                if isinstance(value, list):
                    for nested in value:
                        collect_urls(nested)
                    return
                if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in url_candidates:
                    url_candidates.append(value)

            for key in ("url", "media_url", "image_url", "video_url", "external_url", "link", "permalink", "src"):
                direct = payload.get(key)
                if isinstance(direct, str) and direct.startswith(("http://", "https://")) and direct not in url_candidates:
                    url_candidates.append(direct)

            for key in ("reel_video_id", "media_id", "ig_media_id", "id"):
                candidate_asset_id = normalize_id(payload.get(key))
                if candidate_asset_id:
                    share_asset_id = share_asset_id or candidate_asset_id

            collect_urls(payload)
            collect_urls(att)

            att_url = url_candidates[0] if url_candidates else ""
            att_url_l = att_url.lower()
            unwrapped_att_url = unwrap_meta_redirect_url(att_url)
            if is_instagram_public_link(unwrapped_att_url):
                post_permalink = post_permalink or unwrapped_att_url
            elif is_instagram_public_link(att_url):
                post_permalink = post_permalink or att_url
            try:
                parsed_att = urlparse(att_url)
                candidate_asset_id = normalize_id(parse_qs(parsed_att.query).get("asset_id", [""])[0])
                if candidate_asset_id:
                    share_asset_id = share_asset_id or candidate_asset_id
            except Exception:
                pass

            inferred_type = None
            if att_type in ("image", "photo"):
                inferred_type = "photo"
            elif att_type in ("video", "ig_reel", "reel"):
                inferred_type = "video"
            elif att_type in ("audio", "voice"):
                inferred_type = "audio"
            elif att_type in ("file", "document"):
                inferred_type = "file"

            if not inferred_type and att_url_l:
                if re.search(r"\.(jpg|jpeg|png|gif|webp|bmp|heic|heif)(\?|$)", att_url_l):
                    inferred_type = "photo"
                elif re.search(r"\.(mp4|mov|m4v|webm|avi|mkv)(\?|$)", att_url_l):
                    inferred_type = "video"
                elif re.search(r"\.(mp3|m4a|wav|ogg|oga|aac|opus)(\?|$)", att_url_l):
                    inferred_type = "audio"
                elif any(token in att_url_l for token in ("/reel/", "ig_reel")):
                    inferred_type = "video"

            if not inferred_type and att_type in ("share", "ig_post", "ig_story", "story_mention", "embed", "fallback"):
                inferred_type = "file"

            if inferred_type:
                attachment_had_media = True
                media_type = inferred_type
                if att_url and not is_instagram_public_link(unwrapped_att_url):
                    media_url = att_url
                if not message_text:
                    if att_type in ("share", "ig_post", "ig_story", "story_mention", "ig_reel", "embed"):
                        message_text = "🔁 Forwarded reel" if att_type in ("ig_reel", "reel") else "🔁 Forwarded post"
                    elif media_type == "photo":
                        message_text = "📸 Photo"
                    elif media_type == "video":
                        message_text = "🎥 Video"
                    elif media_type == "audio":
                        message_text = "🎤 Audio"
                    else:
                        message_text = "📎 File"
                if media_url or post_permalink:
                    break

        if attachment_had_media and not message_text:
            message_text = "📎 Attachment"

    if not message_text and not media_type:
        share_url = ""
        shares = message.get("shares")
        if isinstance(shares, list):
            for share in shares:
                if not isinstance(share, dict):
                    continue
                for key in ("link", "url", "permalink"):
                    candidate = normalize_id(share.get(key))
                    if candidate.startswith(("http://", "https://")):
                        share_url = candidate
                        decoded = unwrap_meta_redirect_url(candidate)
                        if is_instagram_public_link(decoded):
                            post_permalink = post_permalink or decoded
                        elif is_instagram_public_link(candidate):
                            post_permalink = post_permalink or candidate
                        break
                if share_url:
                    break
        if share_url:
            lower_share = share_url.lower()
            media_type = "video" if ("/reel/" in lower_share or re.search(r"\.(mp4|mov|m4v|webm)(\?|$)", lower_share)) else "file"
            media_url = "" if is_instagram_public_link(unwrap_meta_redirect_url(share_url)) else share_url
            message_text = "🔁 Forwarded post"

    if attachments and not message_text and not media_type:
        # Do not drop unknown new attachment types from Meta; keep a visible placeholder.
        media_type = "file"
        message_text = "📎 Attachment"

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

        access_token = get_business_access_token(business)
        sender_profile = fetch_instagram_customer_profile(access_token, sender_id) if access_token else {}
        customer_display_name = display_name_from_instagram_profile(sender_profile, "")
        if sender_profile:
            messaging = {
                **messaging,
                "sender_profile": sender_profile,
            }
        if share_asset_id and access_token:
            try:
                share_media_info = fetch_instagram_media_info(access_token, share_asset_id, business) or {}
                resolved_permalink = normalize_id(share_media_info.get("post_permalink"))
                if resolved_permalink:
                    post_permalink = post_permalink or resolved_permalink
                resolved_preview = normalize_id(share_media_info.get("post_image_url"))
                if resolved_preview:
                    post_image_url = resolved_preview
                    if not media_url or "ig_messaging_cdn" in normalize_id(media_url):
                        media_url = resolved_preview
                resolved_media_type = normalize_id(share_media_info.get("post_media_type")).lower()
                if resolved_media_type:
                    post_media_type = resolved_media_type
                    if media_type in (None, "file"):
                        if "video" in resolved_media_type or "reel" in resolved_media_type:
                            media_type = "video"
                        elif "image" in resolved_media_type or "photo" in resolved_media_type:
                            media_type = "photo"
            except Exception as e:
                log("Could not enrich forwarded Instagram share", str(e))

        if not post_permalink and media_url:
            maybe_link = unwrap_meta_redirect_url(media_url)
            if is_instagram_public_link(maybe_link):
                post_permalink = maybe_link

        # Some forwarded reels arrive with only public permalink and no direct media URL.
        # Fetch OG preview as a stable fallback so dashboard can still render preview consistently.
        if post_permalink and (not media_url or "ig_messaging_cdn" in normalize_id(media_url)):
            try:
                public_preview = fetch_instagram_public_preview(post_permalink) or {}
                if public_preview.get("post_image_url") and not post_image_url:
                    post_image_url = normalize_id(public_preview.get("post_image_url"))
                if public_preview.get("post_media_type") and not post_media_type:
                    post_media_type = normalize_id(public_preview.get("post_media_type")).lower()
                candidate_media_url = normalize_id(public_preview.get("media_url"))
                if candidate_media_url:
                    media_url = candidate_media_url
                    if media_type in (None, "", "file"):
                        media_type = "video"
            except Exception as e:
                log("Could not fetch public Instagram preview", str(e))

        save_inbox_message(
            business=business,
            platform="instagram",
            sender_id=sender_id,
            recipient_id=recipient_id,
            message_text=message_text,
            direction="inbound",
            platform_message_id=message_id,
            raw_payload=messaging,
            customer_name=customer_display_name,
            is_read=False,
            media_type=media_type,
            media_url=media_url,
            channel="dm",
            post_permalink=post_permalink,
            post_image_url=post_image_url,
            post_media_type=post_media_type,
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

        if is_low_signal_message(message_text, messaging):
            mark_processed(processed_message_ids, message_id)
            return

        if not access_token:
            return

        media_match_context = ""
        media_reply_hint = ""
        matcher_source_url = media_url or post_image_url
        business_id = normalize_id(business.get("id"))
        if matcher_source_url and media_type in {"photo", "video", "file"}:
            log("Instagram DM media matcher request", {
                "customer_id": sender_id,
                "message_id": message_id,
                "media_type": media_type,
                "source_url_host": urlparse(matcher_source_url).netloc if matcher_source_url else "",
            })
            media_match = analyze_media_for_sales_reply(
                media_url=matcher_source_url,
                user_text=message_text or "",
                media_type=media_type or "",
            )
            if media_match:
                media_match_context = media_match.get("context", "")
                media_reply_hint = media_match.get("reply_hint", "")
                remember_instagram_media_match(
                    business_id=business_id,
                    customer_id=sender_id,
                    context=media_match_context,
                    reply_hint=media_reply_hint,
                    top_match_code=media_match.get("top_match_code", ""),
                    top_match_model=media_match.get("top_match_model", ""),
                    top_score=media_match.get("top_score", 0.0),
                )
                log("Instagram DM media matcher hit", {
                    "customer_id": sender_id,
                    "message_id": message_id,
                    "media_type": media_type,
                    "top_match_code": media_match.get("top_match_code"),
                    "top_match_model": media_match.get("top_match_model"),
                    "top_score": media_match.get("top_score"),
                })
            else:
                log("Instagram DM media matcher miss", {
                    "customer_id": sender_id,
                    "message_id": message_id,
                    "media_type": media_type,
                    "source_url_host": urlparse(matcher_source_url).netloc if matcher_source_url else "",
                })
        elif should_reuse_recent_media_match(message_text or "", media_type or ""):
            cached_match = load_recent_instagram_media_match(business_id=business_id, customer_id=sender_id)
            if cached_match:
                cached_context = normalize_id(cached_match.get("context"))
                if cached_context:
                    media_match_context = (
                        f"{cached_context}\n"
                        "- This customer follow-up likely refers to the same previously matched product unless they ask to change model."
                    )
                    media_reply_hint = normalize_id(cached_match.get("reply_hint")) or media_reply_hint
                    log("Instagram DM media matcher cache hit", {
                        "customer_id": sender_id,
                        "message_id": message_id,
                        "top_match_code": normalize_id(cached_match.get("top_match_code")),
                        "top_match_model": normalize_id(cached_match.get("top_match_model")),
                        "top_score": _safe_score(cached_match.get("top_score")),
                    })

        use_direct_matcher_reply = bool(media_reply_hint) and (
            is_auto_media_placeholder_message(message_text)
            or not normalize_id(message_text)
            or (media_type in {"photo", "video"} and not message.get("text"))
        )
        if use_direct_matcher_reply:
            reply_text = clean_sales_reply(media_reply_hint, message_text or "photo")
        else:
            reply_text = get_ai_reply(
                message_text or "Photo/Video received",
                business,
                "instagram",
                sender_id,
                "dm",
                post_id=share_asset_id,
                post_permalink=post_permalink,
                media_context=media_match_context,
                media_reply_hint=media_reply_hint,
            )

        should_send_catalog = (
            bool(get_catalog_link(business))
            and wants_catalog(message_text)
            and not is_greeting_only(message_text)
            and not is_auto_media_placeholder_message(message_text)
            and not (media_type in {"photo", "video", "file", "audio"})
            and not bool(media_match_context)
            and not bool(media_reply_hint)
        )
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
    from_user = value.get("from") or {}
    commenter_id = normalize_id(from_user.get("id"))
    commenter_username = normalize_id(from_user.get("username"))
    post_id = extract_instagram_comment_post_id(value)
    comment_text = value.get("message") or value.get("text") or ""

    if not comment_id or not comment_text:
        return

    if already_processed(processed_comment_ids, comment_id):
        return

    business = find_business_for_webhook(entry_id)
    if not business:
        return

    # Prevent self-echo loops and duplicate self threads.
    if is_own_instagram_comment_actor(business, entry_id, commenter_id, commenter_username):
        mark_processed(processed_comment_ids, comment_id)
        return

    access_token = get_business_access_token(business)
    media_info = fetch_instagram_media_info(access_token, post_id, business) if access_token and post_id else {}

    inbound_payload = dict(value)
    inbound_payload["post_id"] = post_id
    if not inbound_payload.get("post_permalink"):
        inbound_payload["post_permalink"] = media_info.get("post_permalink") or (f"https://www.instagram.com/p/{post_id}/" if post_id else "")
    if not inbound_payload.get("post_image_url"):
        inbound_payload["post_image_url"] = media_info.get("post_image_url") or ""
    if not inbound_payload.get("post_media_type"):
        inbound_payload["post_media_type"] = normalize_id(media_info.get("post_media_type")).lower()

    save_inbox_message(
        business=business,
        platform="instagram",
        sender_id=commenter_id or comment_id,
        recipient_id=entry_id,
        message_text=comment_text,
        direction="inbound",
        platform_message_id=comment_id,
        raw_payload=inbound_payload,
        customer_name=commenter_username or f"IG User {str(commenter_id or comment_id)[-4:]}",
        is_read=False,
        channel="instagram_comment",
    )

    if not business.get("bot_enabled", True):
        mark_processed(processed_comment_ids, comment_id)
        return

    if business.get("auto_reply_comments") is False:
        mark_processed(processed_comment_ids, comment_id)
        return

    comment_scope = encode_comment_scope("", post_id) if post_id else (commenter_id or comment_id)
    ai_enabled = is_chat_ai_enabled("instagram", "instagram_comment", comment_scope, business.get("id"))
    # Backward compatibility with old per-customer comment settings.
    if ai_enabled and comment_scope != (commenter_id or comment_id):
        ai_enabled = is_chat_ai_enabled("instagram", "instagram_comment", commenter_id or comment_id, business.get("id"))
    if not ai_enabled:
        mark_processed(processed_comment_ids, comment_id)
        return

    if not access_token:
        mark_processed(processed_comment_ids, comment_id)
        return

    if wants_catalog(comment_text):
        catalog_link = get_catalog_link(business)
        dm_result = send_catalog_private_reply(access_token, comment_id, business)
        dm_raw_result = safe_json(dm_result) if dm_result is not None else {}
        if dm_result is not None and dm_result.ok:
            save_inbox_message(
                business=business,
                platform="instagram",
                sender_id=entry_id,
                recipient_id=commenter_id or comment_id,
                message_text=f"Katalog: {catalog_link}",
                direction="outbound",
                platform_message_id=normalize_id(dm_raw_result.get("message_id") or dm_raw_result.get("id")) if isinstance(dm_raw_result, dict) else "",
                raw_payload=dm_raw_result if isinstance(dm_raw_result, dict) else {},
                customer_name=commenter_username or f"IG User {str(commenter_id or comment_id)[-4:]}",
                is_read=True,
                channel="dm",
            )
            reply_text = "Katalog DM orqali yuborildi"
        else:
            log("Instagram catalog private reply failed", {"comment_id": comment_id, "result": dm_raw_result})
            reply_text = "Katalogni DM orqali yuborish uchun bizga xabar yozing."
    else:
        reply_text = get_ai_reply(
            comment_text,
            business,
            "instagram",
            commenter_id or comment_id,
            "instagram_comment",
            post_id=post_id,
            post_permalink=inbound_payload.get("post_permalink", ""),
        )
        reply_text = remove_urls(reply_text)

    send_result = reply_to_comment(access_token, comment_id, reply_text, business)
    raw_result = safe_json(send_result) if send_result is not None else {}
    if send_result is not None and send_result.ok:
        outbound_payload = dict(raw_result) if isinstance(raw_result, dict) else {}
        outbound_payload["post_id"] = post_id
        if not outbound_payload.get("post_permalink"):
            outbound_payload["post_permalink"] = inbound_payload.get("post_permalink", "")
        if not outbound_payload.get("post_image_url"):
            outbound_payload["post_image_url"] = inbound_payload.get("post_image_url", "")
        if not outbound_payload.get("post_media_type"):
            outbound_payload["post_media_type"] = normalize_id(inbound_payload.get("post_media_type")).lower()
        save_inbox_message(
            business=business,
            platform="instagram",
            sender_id=entry_id,
            recipient_id=commenter_id or comment_id,
            message_text=reply_text,
            direction="outbound",
            platform_message_id=normalize_id(raw_result.get("id")) if isinstance(raw_result, dict) else "",
            raw_payload=outbound_payload,
            customer_name=commenter_username or f"IG User {str(commenter_id or comment_id)[-4:]}",
                is_read=True,
                channel="instagram_comment",
            )
        mark_processed(processed_comment_ids, comment_id)
    else:
        # Keep visibility when Meta rejects comment send; do not mark as processed
        # so duplicate webhook deliveries can retry.
        log("Instagram comment auto-reply failed", {
            "comment_id": comment_id,
            "customer_id": commenter_id,
            "post_id": post_id,
            "status_code": getattr(send_result, "status_code", None),
            "result": raw_result,
        })


# ============================================================================
# WHATSAPP
# ============================================================================
def get_whatsapp_access_token(business: dict = None):
    if business:
        channel_token = get_business_channel_token(
            business,
            ["whatsapp"],
            ["access_token", "whatsapp_access_token"],
        )
        if channel_token:
            return channel_token
        return business.get("whatsapp_access_token") or WHATSAPP_ACCESS_TOKEN
    return WHATSAPP_ACCESS_TOKEN


def get_whatsapp_phone_number_id(business: dict = None):
    if business:
        channel_phone = get_business_channel_token(
            business,
            ["whatsapp"],
            ["phone_number_id", "whatsapp_phone_number_id", "external_account_id"],
        )
        if channel_phone:
            return channel_phone
        return business.get("whatsapp_phone_number_id") or WHATSAPP_PHONE_NUMBER_ID
    return WHATSAPP_PHONE_NUMBER_ID


def get_telegram_bot_token(business: dict = None):
    if business:
        token = get_business_channel_token(
            business,
            ["telegram", "telegram_bot"],
            ["telegram_bot_token", "bot_token", "access_token"],
        )
        if token:
            return token
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


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


def send_telegram_bot_photo_upload(chat_id: str, file_bytes: bytes, filename: str, mime_type: str, caption: str = "", business: dict = None):
    token = get_telegram_bot_token(business)

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


def send_telegram_bot_voice_upload(chat_id: str, file_bytes: bytes, filename: str, mime_type: str, business: dict = None):
    token = get_telegram_bot_token(business)

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

    off_topic_reply = unrelated_topic_reply(user_text)
    if off_topic_reply:
        add_whatsapp_memory(phone, "user", user_text)
        add_whatsapp_memory(phone, "assistant", off_topic_reply)
        return off_topic_reply

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
        business_with_fallback_model.setdefault("ai_model", WHATSAPP_FALLBACK_MODEL)
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


def encode_oauth_state(owner_email: str = "") -> str:
    payload = {
        "owner_email": normalize_email(owner_email),
        "nonce": secrets.token_urlsafe(10),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_oauth_state(state: str) -> dict:
    try:
        if not state:
            return {}
        padded = state + ("=" * (-len(state) % 4))
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def exchange_facebook_code_for_user_token(code: str) -> str:
    res = requests.get(
        f"{GRAPH_FACEBOOK}/oauth/access_token",
        params={
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "redirect_uri": FACEBOOK_REDIRECT_URI,
            "code": code,
        },
        timeout=30,
    )
    log("Facebook short-lived token exchange", {"status": res.status_code, "body": res.text})
    res.raise_for_status()
    return normalize_id((res.json() or {}).get("access_token"))


def exchange_facebook_long_lived_token(short_lived_token: str) -> str:
    if not short_lived_token:
        return ""
    try:
        res = requests.get(
            f"{GRAPH_FACEBOOK}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "fb_exchange_token": short_lived_token,
            },
            timeout=30,
        )
        if not res.ok:
            return short_lived_token
        return normalize_id((res.json() or {}).get("access_token")) or short_lived_token
    except Exception:
        return short_lived_token


def get_facebook_user_profile(user_token: str) -> dict:
    if not user_token:
        return {}
    try:
        res = requests.get(
            f"{GRAPH_FACEBOOK}/me",
            params={"fields": "id,name,email", "access_token": user_token},
            timeout=30,
        )
        return res.json() if res.ok else {}
    except Exception:
        return {}


def get_facebook_pages_with_instagram(user_token: str):
    if not user_token:
        return []
    res = requests.get(
        f"{GRAPH_FACEBOOK}/me/accounts",
        params={
            "fields": "id,name,access_token,instagram_business_account{id,username}",
            "access_token": user_token,
        },
        timeout=30,
    )
    log("Facebook pages fetch", {"status": res.status_code, "body": res.text})
    if not res.ok:
        return []
    data = res.json() or {}
    return data.get("data", []) if isinstance(data, dict) else []


def subscribe_page_to_webhooks(page_id: str, page_access_token: str):
    page_id = normalize_id(page_id)
    if not page_id or not page_access_token:
        return False, {"error": "Missing page_id or page_access_token"}
    try:
        res = requests.post(
            f"{GRAPH_FACEBOOK}/{page_id}/subscribed_apps",
            params={"subscribed_fields": "messages,messaging_postbacks,comments", "access_token": page_access_token},
            timeout=30,
        )
        body = safe_json(res)
        log("Page webhook subscribe", {"page_id": page_id, "status": res.status_code, "body": body})
        return res.ok, body
    except Exception as exc:
        return False, {"error": str(exc)}


def subscribe_whatsapp_waba_to_webhooks(waba_id: str, access_token: str):
    waba_id = normalize_id(waba_id)
    access_token = normalize_id(access_token)
    if not waba_id or not access_token:
        return False, {"error": "Missing waba_id or access_token"}
    try:
        res = requests.post(
            f"{GRAPH_FACEBOOK}/{waba_id}/subscribed_apps",
            params={"access_token": access_token},
            timeout=30,
        )
        body = safe_json(res)
        log("WhatsApp WABA webhook subscribe", {"waba_id": waba_id, "status": res.status_code, "body": body})
        return res.ok, body
    except Exception as exc:
        return False, {"error": str(exc)}


def get_whatsapp_waba_phone_numbers(waba_id: str, access_token: str):
    waba_id = normalize_id(waba_id)
    access_token = normalize_id(access_token)
    if not waba_id or not access_token:
        return []
    try:
        res = requests.get(
            f"{GRAPH_FACEBOOK}/{waba_id}/phone_numbers",
            params={"fields": "id,display_phone_number,verified_name,quality_rating", "access_token": access_token},
            timeout=30,
        )
        body = safe_json(res)
        log("WhatsApp WABA phone numbers", {"waba_id": waba_id, "status": res.status_code, "body": body})
        if not res.ok:
            return []
        return body.get("data", []) if isinstance(body, dict) else []
    except Exception as exc:
        log("WhatsApp phone number fetch failed", str(exc))
        return []


def persist_whatsapp_embedded_business(owner_email: str, waba_id: str, phone_number_id: str, access_token: str):
    phone_number_id = normalize_id(phone_number_id)
    if not phone_number_id:
        return None

    existing = get_business_by_whatsapp_phone_number_id(phone_number_id)
    payload = {
        "instagram_business_id": f"whatsapp_{phone_number_id}",
        "business_name": "WhatsApp Business",
        "business_type": "WhatsApp Business",
        "oauth_provider": "whatsapp_embedded",
        "whatsapp_business_account_id": normalize_id(waba_id) or None,
        "whatsapp_phone_number_id": phone_number_id,
        "whatsapp_access_token": normalize_id(access_token),
        "token_preview": safe_token(access_token),
        "bot_enabled": True,
        "auto_reply_dms": True,
        "auto_reply_comments": True,
        "language": "uz",
    }

    optional = set(payload.keys())
    for _ in range(len(optional) + 1):
        try:
            if existing:
                result = supabase.table("businesses").update(payload).eq("id", existing["id"]).execute()
                business_id = existing["id"]
            else:
                result = supabase.table("businesses").upsert(
                    payload,
                    on_conflict="instagram_business_id",
                ).execute()
                rows = result.data or []
                business_id = rows[0].get("id") if rows else ""
            if owner_email and business_id:
                assign_business_owner(owner_email, business_id)
            return result.data
        except Exception as exc:
            message = str(exc)
            match = re.search(r"Could not find the '([^']+)' column", message)
            missing_column = match.group(1) if match else ""
            if missing_column and missing_column in payload:
                payload.pop(missing_column, None)
                continue
            raise
    return None


def assign_business_owner(user_email: str, business_id: str, role: str = "owner"):
    clean_email = normalize_email(user_email)
    business_id = normalize_id(business_id)
    if not clean_email or not business_id:
        return
    try:
        supabase.table("business_users").upsert(
            {"user_email": clean_email, "business_id": business_id, "role": role},
            on_conflict="user_email,business_id",
        ).execute()
    except Exception as e:
        log("business_users upsert failed", str(e))


def upsert_business(
        instagram_business_id: str,
        username: str,
        access_token: str,
        oauth_provider: str = "instagram_direct",
        facebook_page_id: str = "",
        facebook_page_name: str = "",
        page_access_token: str = "",
):
    instagram_business_id = normalize_id(instagram_business_id)
    facebook_page_id = normalize_id(facebook_page_id)
    existing = get_business(instagram_business_id)

    update_data = {
        "instagram_business_id": instagram_business_id,
        "business_name": username or f"instagram_{instagram_business_id}",
        "access_token": access_token or "",
        "page_access_token": page_access_token or None,
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
        "product_matcher_enabled": PRODUCT_MATCHER_ENABLED,
        "product_matcher_urls": PRODUCT_MATCHER_API_URLS,
        "product_matcher_context_ttl_seconds": PRODUCT_MATCHER_CONTEXT_TTL_SECONDS,
    }


@app.get("/api/health/deep")
async def api_health_deep(
        token: str = "",
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_media_secret(token, x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    checks = {}

    try:
        supabase.table("businesses").select("id").limit(1).execute()
        checks["supabase"] = "ok"
    except Exception as exc:
        checks["supabase"] = f"error: {exc}"

    checks["telegram_bot_token"] = "ok" if os.getenv("TELEGRAM_BOT_TOKEN", "") else "missing"
    checks["telegram_user_client"] = "configured" if (
        os.getenv("TELEGRAM_API_ID", "")
        and os.getenv("TELEGRAM_API_HASH", "")
        and os.getenv("TELEGRAM_USER_SESSION", "")
    ) else "missing_env"
    checks["whatsapp_access_token"] = "ok" if WHATSAPP_ACCESS_TOKEN else "missing"
    checks["product_matcher_enabled"] = "ok" if PRODUCT_MATCHER_ENABLED else "disabled"
    checks["product_matcher_url_count"] = len(PRODUCT_MATCHER_API_URLS)
    if PRODUCT_MATCHER_ENABLED and PRODUCT_MATCHER_API_URLS:
        matcher_url = product_matcher_health_url(PRODUCT_MATCHER_API_URLS[0])
        try:
            matcher_res = requests.get(matcher_url, timeout=min(PRODUCT_MATCHER_TIMEOUT_SECONDS, 10))
            checks["product_matcher_health"] = "ok" if matcher_res.ok else f"error_http_{matcher_res.status_code}"
        except Exception as exc:
            checks["product_matcher_health"] = f"error: {exc}"
    elif PRODUCT_MATCHER_ENABLED:
        checks["product_matcher_health"] = "missing_url"

    healthy = (
        checks["supabase"] == "ok"
        and checks["telegram_bot_token"] == "ok"
    )

    return {
        "status": "ok" if healthy else "degraded",
        "version": "5.1.1-telegram-media-fallback",
        "checks": checks,
    }


# ============================================================================
# API ROUTES - V2 (REACT UI)
# ============================================================================

@app.post("/api/v2/auth/login")
async def dashboard_login(payload: DashboardLoginRequest):
    email = normalize_email(payload.email)
    password = str(payload.password or "")
    if not email or not password:
        return JSONResponse({"status": "error", "error": "Email and password are required."}, status_code=400)

    try:
        user_result = (
            supabase.table("dashboard_users")
            .select("*")
            .eq("email", email)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        users = user_result.data or []
        if not users:
            return JSONResponse({"status": "error", "error": "Invalid email or password."}, status_code=401)

        user = users[0]
        if not verify_dashboard_password(password, user.get("password_hash", "")):
            return JSONResponse({"status": "error", "error": "Invalid email or password."}, status_code=401)

        businesses = []
        links = []
        if is_super_admin_email(email):
            businesses = (supabase.table("businesses").select("*").order("created_at", desc=True).execute().data or [])
        else:
            links = (
                supabase.table("business_users")
                .select("business_id,role")
                .eq("user_email", email)
                .execute()
                .data
                or []
            )
            business_ids = [row.get("business_id") for row in links if row.get("business_id")]
            if business_ids:
                businesses = (
                    supabase.table("businesses")
                    .select("*")
                    .in_("id", business_ids)
                    .order("created_at", desc=True)
                    .execute()
                    .data
                    or []
                )

        is_admin = is_super_admin_email(email)
        role_from_user = normalize_id(user.get("role") or "").lower()
        if is_admin:
            role = "super_admin"
        else:
            # Prefer per-business role to avoid stale global role in dashboard_users.
            role = pick_user_business_role(email) or role_from_user or "operator"
        token = create_dashboard_auth_token(email=email, is_admin=is_admin, role=role)
        return {
            "status": "ok",
            "data": {
                "user": {
                    "id": user.get("id"),
                    "email": email,
                    "is_admin": is_admin,
                    "role": role or "operator",
                },
                "token": token,
                "businesses": businesses,
            },
        }
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=500)


@app.post("/api/v2/auth/signup")
async def dashboard_signup(payload: DashboardSignupRequest):
    email = normalize_email(payload.email)
    password = str(payload.password or "")
    role = normalize_id(payload.role or "operator").lower()
    business_id = normalize_id(payload.business_id)

    if not email or not password:
        return JSONResponse({"status": "error", "error": "Email/ID and password are required."}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"status": "error", "error": "Password must be at least 6 characters."}, status_code=400)
    if role not in {"owner", "admin", "operator"}:
        return JSONResponse({"status": "error", "error": "Role must be owner, admin or operator."}, status_code=400)
    if role == "operator" and not business_id:
        return JSONResponse({"status": "error", "error": "Operator sign-up requires business_id."}, status_code=400)

    try:
        existing = (
            supabase.table("dashboard_users")
            .select("id,email")
            .eq("email", email)
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing:
            return JSONResponse({"status": "error", "error": "This ID already exists."}, status_code=409)

        supabase.table("dashboard_users").insert(
            {
                "email": email,
                "password_hash": hash_dashboard_password(password),
                "is_active": True,
            }
        ).execute()

        if business_id:
            supabase.table("business_users").upsert(
                {
                    "user_email": email,
                    "business_id": business_id,
                    "role": role,
                    "full_name": normalize_id(payload.full_name),
                },
                on_conflict="user_email,business_id",
            ).execute()

        is_admin = is_super_admin_email(email)
        effective_role = "super_admin" if is_admin else role
        token = create_dashboard_auth_token(email=email, is_admin=is_admin, role=effective_role)
        return {
            "status": "ok",
            "data": {
                "user": {
                    "email": email,
                    "is_admin": is_admin,
                    "role": effective_role,
                },
                "token": token,
            },
        }
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=500)


@app.get("/api/v2/operators")
async def list_operators_v2(
    business_id: str = "",
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business_id = normalize_id(business_id)
    if business_id and not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    try:
        query = supabase.table("business_users").select("user_email,role,business_id").eq("role", "operator")
        if business_id:
            query = query.eq("business_id", business_id)
        elif not access.get("is_admin"):
            allowed = access.get("business_ids") or []
            if not allowed:
                return {"status": "ok", "data": []}
            query = query.in_("business_id", allowed)
        query_result = await run_blocking_io(
            query.execute,
            timeout=18,
            label="conversations query",
        )
        rows = (query_result.data or []) if query_result else []
        return {
            "status": "ok",
            "data": [
                {
                    "login_id": normalize_email(row.get("user_email")),
                    "role": row.get("role") or "operator",
                    "business_id": row.get("business_id"),
                }
                for row in rows
            ],
        }
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/v2/operators")
async def create_operator_v2(
    body: OperatorCreateRequest,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    role = normalize_id(access.get("role", "")).lower()
    if not access.get("is_admin") and role not in BUSINESS_ADMIN_ROLES:
        return JSONResponse({"status": "error", "message": "Only admin can create operator accounts"}, status_code=403)

    business_id = normalize_id(body.business_id)
    login_id = normalize_email(body.login_id)
    password = str(body.password or "")
    if not business_id:
        return JSONResponse({"status": "error", "message": "Missing business_id"}, status_code=400)
    if not login_id:
        return JSONResponse({"status": "error", "message": "Operator ID is required"}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"status": "error", "message": "Password must be at least 6 characters"}, status_code=400)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    try:
        existing = (
            supabase.table("dashboard_users")
            .select("id,email")
            .eq("email", login_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        user_payload = {
            "email": login_id,
            "password_hash": hash_dashboard_password(password),
            "is_active": True,
        }
        if existing:
            supabase.table("dashboard_users").update(user_payload).eq("email", login_id).execute()
        else:
            supabase.table("dashboard_users").insert(user_payload).execute()

        supabase.table("business_users").upsert(
            {
                "user_email": login_id,
                "business_id": business_id,
                "role": "operator",
            },
            on_conflict="user_email,business_id",
        ).execute()
        return {"status": "ok", "data": {"login_id": login_id, "role": "operator", "business_id": business_id}}
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/v2/operator-tasks")
async def create_operator_task_v2(
    body: OperatorTaskCreateRequest,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business_id = normalize_id(body.business_id)
    text = normalize_id(body.text)
    assign_mode = normalize_id(body.assign_mode).lower() or "all"

    if not business_id:
        return JSONResponse({"status": "error", "message": "Missing business_id"}, status_code=400)
    if not text:
        return JSONResponse({"status": "error", "message": "Task text is required"}, status_code=400)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    # Only owners/admins/super_admin can assign tasks.
    role = normalize_id(access.get("role", "")).lower()
    if role not in BUSINESS_ADMIN_ROLES and not access.get("is_admin"):
        return JSONResponse({"status": "error", "message": "Only admin can assign tasks"}, status_code=403)

    try:
        task = append_operator_task(
            business_id=business_id,
            text=text,
            recipients=body.recipients or [],
            assign_mode=assign_mode,
            created_by=access.get("email", ""),
        )
        if not task:
            return JSONResponse({"status": "error", "message": "Could not create task"}, status_code=500)
        return {"status": "ok", "data": task}
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.get("/api/v2/operator-tasks")
async def list_operator_tasks_v2(
    business_id: str = "",
    for_me: bool = True,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business_id = normalize_id(business_id)
    if not business_id:
        return JSONResponse({"status": "error", "message": "Missing business_id"}, status_code=400)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    try:
        items = merged_operator_task_items(get_workspace_state(business_id))
        scoped = scope_operator_tasks_for_access(items, access) if for_me else items
        normalized = []
        for item in scoped:
            recipients = item.get("recipients") if isinstance(item.get("recipients"), list) else ["*"]
            normalized.append(
                {
                    "id": item.get("id"),
                    "text": normalize_id(item.get("text")),
                    "recipients": recipients,
                    "assign_mode": normalize_id(item.get("assign_mode", "all")) or "all",
                    "created_by": normalize_email(item.get("created_by")),
                    "created_at": item.get("created_at"),
                }
            )

        normalized.sort(key=lambda item: normalize_id(item.get("created_at")), reverse=True)
        return {"status": "ok", "count": len(normalized), "data": normalized}
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/v2/businesses")
async def create_business_v2(
    body: BusinessCreateRequest,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not access.get("is_admin"):
        return JSONResponse({"status": "error", "message": "Only super admin can create businesses"}, status_code=403)

    business_name = normalize_id(body.business_name)
    owner_email = normalize_email(body.owner_email)
    if not business_name or not owner_email:
        return JSONResponse({"status": "error", "message": "business_name and owner_email are required"}, status_code=400)

    try:
        created = (
            supabase.table("businesses")
            .insert(
                {
                    "business_name": business_name,
                    "owner_email": owner_email,
                    "business_type": normalize_id(body.business_type),
                    "language": normalize_id(body.language) or "uz",
                    "tone": normalize_id(body.tone) or "friendly",
                    "bot_enabled": True,
                }
            )
            .execute()
            .data
            or []
        )
        if not created:
            return JSONResponse({"status": "error", "message": "Failed to create business"}, status_code=500)

        business_id = normalize_id(created[0].get("id"))
        supabase.table("business_users").upsert(
            {
                "user_email": owner_email,
                "business_id": business_id,
                "role": "owner",
            },
            on_conflict="user_email,business_id",
        ).execute()
        return {"status": "ok", "data": created[0]}
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/v2/businesses/{business_id}/admins")
async def create_business_admin_v2(
    business_id: str,
    body: BusinessAdminCreateRequest,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)
    if not access.get("is_admin") and access.get("role") not in {"owner", "admin"}:
        return JSONResponse({"status": "error", "message": "Only owner/admin can create business admins"}, status_code=403)

    clean_business_id = normalize_id(business_id)
    email = normalize_email(body.email)
    password = str(body.password or "")
    role = normalize_id(body.role or "admin").lower()
    if role not in {"owner", "admin", "operator"}:
        return JSONResponse({"status": "error", "message": "Invalid role"}, status_code=400)
    if not clean_business_id or not email or len(password) < 6:
        return JSONResponse({"status": "error", "message": "business_id, email and password(>=6) are required"}, status_code=400)

    try:
        existing = (
            supabase.table("dashboard_users")
            .select("id,email")
            .eq("email", email)
            .limit(1)
            .execute()
            .data
            or []
        )
        user_payload = {"email": email, "password_hash": hash_dashboard_password(password), "is_active": True}
        if existing:
            supabase.table("dashboard_users").update(user_payload).eq("email", email).execute()
        else:
            supabase.table("dashboard_users").insert(user_payload).execute()

        supabase.table("business_users").upsert(
            {
                "user_email": email,
                "business_id": clean_business_id,
                "role": role,
                "full_name": normalize_id(body.full_name),
            },
            on_conflict="user_email,business_id",
        ).execute()
        return {"status": "ok", "data": {"email": email, "business_id": clean_business_id, "role": role}}
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.get("/api/v2/conversations")
async def get_conversations_v2(
        platform: str = "all",
        search: str = "",
        business_id: str = "",
        include_raw: bool = False,
        fast: bool = False,
        no_cache: bool = False,
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    """Get all conversations in React UI format"""
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        clean_business_id = normalize_id(business_id)
        allowed_ids = access.get("business_ids") or []
        cache_key = json.dumps(
            {
                "admin": bool(access.get("is_admin")),
                "email": normalize_email(access.get("email", "")),
                "allowed": sorted([normalize_id(x) for x in allowed_ids]),
                "platform": normalize_id(platform).lower(),
                "business_id": clean_business_id,
                "search": normalize_id(search).strip().lower(),
                "include_raw": bool(include_raw),
                "fast": bool(fast),
            },
            sort_keys=True,
        )
        now_ts = time.time()
        cached = _conversations_cache.get(cache_key)
        if (not no_cache) and cached and (now_ts - cached[0]) <= CONVERSATIONS_CACHE_TTL_SECONDS:
            return cached[1]

        # Keep payload slim on hot path; this endpoint is polled frequently.
        fields = (
            "business_id,platform,channel,customer_id,chat_id,customer_name,"
            "content,created_at,direction,is_read,external_message_id"
        )
        if include_raw:
            fields = f"{fields},raw_payload"
        if clean_business_id:
            if not can_access_business(access, clean_business_id):
                return {"status": "ok", "count": 0, "data": []}
        elif not access.get("is_admin"):
            allowed = access.get("business_ids") or []
            if not allowed:
                return {"status": "ok", "count": 0, "data": []}

        def build_base_query():
            q = supabase.table("inbox_messages").select(fields)
            if clean_business_id:
                q = q.eq("business_id", clean_business_id)
            elif not access.get("is_admin"):
                q = q.in_("business_id", access.get("business_ids") or [])
            if platform != "all":
                q = q.eq("platform", platform)
            return q

        if fast:
            # Fast mode is used by the inbox poller; keep it lightweight but large enough
            # to avoid hiding older active conversations.
            recent_cutoff = (datetime.utcnow() - timedelta(days=120)).strftime("%Y-%m-%dT00:00:00Z")
            rows = []
            page_size = 250
            max_scan_rows = 2500
            for offset in range(0, max_scan_rows, page_size):
                page = (
                    build_base_query()
                    .gte("created_at", recent_cutoff)
                    .order("created_at", desc=True)
                    .range(offset, offset + page_size - 1)
                    .execute()
                    .data
                    or []
                )
                if not page:
                    break
                rows.extend(page)
                if len(page) < page_size:
                    break
        else:
            rows = []
            page_size = 450
            max_scan_rows = 5400
            for offset in range(0, max_scan_rows, page_size):
                page = (
                    build_base_query()
                    .order("created_at", desc=True)
                    .range(offset, offset + page_size - 1)
                    .execute()
                    .data
                    or []
                )
                if not page:
                    break
                rows.extend(page)
                if len(page) < page_size:
                    break

        conversations_map = {}
        for row in rows:
            business_id = row.get("business_id")
            platform_name = normalize_id(row.get("platform", "instagram")).lower() or "instagram"
            channel = standard_channel(platform_name, row.get("channel", ""))
            customer_id = str(row.get("customer_id") or "").strip()
            chat_id = str(row.get("chat_id") or "").strip()
            scope = conversation_scope(platform_name, channel, customer_id, chat_id)
            if include_raw and platform_name == "instagram" and "comment" in channel:
                post_id = extract_instagram_comment_post_id(row)
                scope = encode_comment_scope(customer_id, post_id)

            if not business_id or not scope:
                continue

            # Merge Telegram rows of the same real chat even if legacy channel values differ.
            if platform_name == "telegram":
                if channel == "telegram_user_private":
                    key_channel = "telegram_user_private"
                else:
                    key_channel = "telegram_bot_group" if str(scope).startswith("-") else "telegram_bot_private"
                key = f"{platform_name}::{business_id}::{key_channel}::{scope}"
            else:
                key = f"{platform_name}::{business_id}::{channel}::{scope}"

            if key not in conversations_map:
                conversations_map[key] = []

            conversations_map[key].append(row)

        conversations = []
        business_lookup = {}
        for key, conv_rows in conversations_map.items():
            key_parts = key.split("::")
            row_business_id = key_parts[1] if len(key_parts) > 1 else ""
            if row_business_id and row_business_id not in business_lookup:
                business_lookup[row_business_id] = get_business_by_id(row_business_id)
            conv = transform_conversation_to_react(
                key,
                sorted(conv_rows, key=lambda x: x.get('created_at', '')),
                business=business_lookup.get(row_business_id) or {},
                ai_lookup_enabled=(not fast),
            )
            if conv:
                conversations.append(conv)

        if search.strip():
            q = search.lower().strip()
            conversations = [
                c for c in conversations
                if q in f"{c['name']} {c['handle']} {c['preview']}".lower()
            ]

        response = {
            'status': 'ok',
            'count': len(conversations),
            'data': conversations
        }
        if not no_cache:
            _conversations_cache[cache_key] = (time.time(), response)
            if len(_conversations_cache) > 120:
                for key in sorted(_conversations_cache, key=lambda item: _conversations_cache[item][0])[:40]:
                    _conversations_cache.pop(key, None)
        return response

    except TimeoutError as e:
        log("Conversations query timeout", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=504
        )
    except Exception as e:
        log("Error fetching conversations", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.get("/api/v2/conversation/{conversation_id}/messages")
async def get_conversation_messages_v2(
        conversation_id: str,
        background_tasks: BackgroundTasks,
        limit: int = 200,
        mark_read: bool = True,
        include_raw: bool = False,
        no_cache: bool = False,
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    """Get all messages for a conversation"""
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse(
                {"error": "Invalid conversation ID format"},
                status_code=400
            )

        platform, business_id, channel, customer_scope = parts
        if not can_access_business(access, business_id):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)
        customer_id = customer_scope
        post_id = ""
        if platform == "instagram" and "comment" in channel:
            customer_id, post_id = decode_comment_scope(customer_scope)

        limit = max(1, min(int(limit or 200), 300))
        cache_key = json.dumps(
            {
                "conversation_id": conversation_id,
                "limit": limit,
                "include_raw": bool(include_raw),
            },
            sort_keys=True,
        )
        now_ts = time.time()
        cached = _conversation_messages_cache.get(cache_key)
        if (not no_cache) and cached and (now_ts - cached[0]) <= CONVERSATION_MESSAGES_CACHE_TTL_SECONDS:
            if mark_read:
                def mark_read_cached_task():
                    try:
                        mark_query = (
                            supabase.table("inbox_messages")
                            .update({"is_read": True})
                            .eq("platform", platform)
                            .eq("business_id", business_id)
                            .eq("direction", "inbound")
                            .eq("is_read", False)
                        )
                        if platform == "telegram" and channel in ("telegram_bot_group", "telegram_bot_private"):
                            mark_query = mark_query.or_(f"chat_id.eq.{customer_id},customer_id.eq.{customer_id}")
                        elif platform == "instagram" and "comment" in channel:
                            if channel:
                                mark_query = mark_query.eq("channel", channel)
                            if post_id:
                                mark_query = mark_query.or_(f"raw_payload->media->>id.eq.{post_id},raw_payload->>post_id.eq.{post_id}")
                            elif customer_id:
                                mark_query = mark_query.eq("customer_id", str(customer_id))
                        else:
                            mark_query = mark_query.eq("customer_id", str(customer_id))
                            if channel:
                                mark_query = mark_query.eq("channel", channel)
                        mark_query.execute()
                    except Exception:
                        pass

                if background_tasks is not None:
                    background_tasks.add_task(mark_read_cached_task)
                else:
                    mark_read_cached_task()
            return cached[1]

        base_fields = (
            "id,direction,role,created_at,media_type,content,platform,channel,customer_id,"
            "external_message_id,media_url,post_permalink,post_image_url,post_media_type,raw_payload"
        )
        select_fields = base_fields

        query = (
            supabase.table("inbox_messages")
            .select(select_fields)
            .eq("platform", platform)
            .eq("business_id", business_id)
        )

        if platform == "telegram" and channel in ("telegram_bot_group", "telegram_bot_private"):
            query = query.or_(f"chat_id.eq.{customer_id},customer_id.eq.{customer_id}")
        elif platform == "instagram" and "comment" in channel:
            if channel:
                query = query.eq("channel", channel)
            if post_id:
                query = query.or_(f"raw_payload->media->>id.eq.{post_id},raw_payload->>post_id.eq.{post_id}")
            elif customer_id:
                query = query.eq("customer_id", str(customer_id))
        else:
            query = query.or_(f"customer_id.eq.{customer_id},chat_id.eq.{customer_id}")
            if platform == "instagram" and channel in ("dm", "instagram_dm", "instagram_private"):
                query = query.in_("channel", ["dm", "instagram_dm", "instagram_private", ""])
            elif channel:
                query = query.eq("channel", channel)

        result = query.order("created_at", desc=True).limit(limit).execute()
        rows = list(reversed(result.data or []))

        # Some legacy Instagram rows were saved with inconsistent channel values.
        # If strict channel filtering returns no history, fall back to customer-wide DM lookup.
        if not rows and platform == "instagram" and channel in ("dm", "instagram_dm", "instagram_private"):
            fallback_query = (
                supabase.table("inbox_messages")
                .select(select_fields)
                .eq("platform", platform)
                .eq("business_id", business_id)
                .or_(f"customer_id.eq.{customer_id},chat_id.eq.{customer_id}")
                .order("created_at", desc=True)
                .limit(limit)
            )
            rows = list(reversed(fallback_query.execute().data or []))

        # Backfill old forwarded Instagram messages that were saved without preview URLs.
        # This keeps forwarded reels stable in UI (no random "NO PREVIEW" regressions).
        if platform == "instagram" and rows:
            update_rows = []
            for row in rows:
                media_type = normalize_id(row.get("media_type")).lower()
                if media_type not in ("video", "file", "photo", "image"):
                    continue
                if normalize_id(row.get("media_url")):
                    continue

                post_permalink = normalize_id(
                    row.get("post_permalink")
                    or (row.get("raw_payload") or {}).get("post_permalink")
                    or extract_instagram_permalink_from_payload(row.get("raw_payload") or {})
                )
                if not post_permalink:
                    continue

                preview = fetch_instagram_public_preview(post_permalink) or {}
                preview_media_url = normalize_id(preview.get("media_url"))
                preview_image_url = normalize_id(preview.get("post_image_url"))
                preview_media_type = normalize_id(preview.get("post_media_type")).lower()

                changed = False
                if preview_media_url:
                    row["media_url"] = preview_media_url
                    changed = True
                if preview_image_url and not normalize_id(row.get("post_image_url")):
                    row["post_image_url"] = preview_image_url
                    changed = True
                if post_permalink and not normalize_id(row.get("post_permalink")):
                    row["post_permalink"] = post_permalink
                    changed = True
                if preview_media_type and media_type in ("", "file"):
                    row["media_type"] = "video" if "video" in preview_media_type else ("photo" if "image" in preview_media_type else media_type)
                    changed = True

                if changed and normalize_id(row.get("id")):
                    update_rows.append({
                        "id": normalize_id(row.get("id")),
                        "media_url": normalize_id(row.get("media_url")),
                        "post_image_url": normalize_id(row.get("post_image_url")),
                        "post_permalink": normalize_id(row.get("post_permalink")),
                        "post_media_type": normalize_id(preview_media_type or row.get("post_media_type")).lower(),
                    })

            if update_rows:
                def persist_preview_backfill(rows_to_update: list[dict]):
                    for item in rows_to_update:
                        try:
                            supabase.table("inbox_messages").update({
                                "media_url": item.get("media_url") or None,
                                "post_image_url": item.get("post_image_url") or None,
                                "post_permalink": item.get("post_permalink") or None,
                                "post_media_type": item.get("post_media_type") or None,
                            }).eq("id", item.get("id")).execute()
                        except Exception:
                            pass

                if background_tasks is not None:
                    background_tasks.add_task(persist_preview_backfill, update_rows)
                else:
                    persist_preview_backfill(update_rows)

        messages = [transform_message_to_react(row) for row in rows]

        if mark_read:
            def mark_read_task():
                try:
                    mark_query = (
                        supabase.table("inbox_messages")
                        .update({"is_read": True})
                        .eq("platform", platform)
                        .eq("business_id", business_id)
                        .eq("direction", "inbound")
                        .eq("is_read", False)
                    )
                    if platform == "telegram" and channel in ("telegram_bot_group", "telegram_bot_private"):
                        mark_query = mark_query.or_(f"chat_id.eq.{customer_id},customer_id.eq.{customer_id}")
                    elif platform == "instagram" and "comment" in channel:
                        if channel:
                            mark_query = mark_query.eq("channel", channel)
                        if post_id:
                            mark_query = mark_query.or_(f"raw_payload->media->>id.eq.{post_id},raw_payload->>post_id.eq.{post_id}")
                        elif customer_id:
                            mark_query = mark_query.eq("customer_id", str(customer_id))
                    else:
                        mark_query = mark_query.or_(f"customer_id.eq.{customer_id},chat_id.eq.{customer_id}")
                        if channel:
                            mark_query = mark_query.eq("channel", channel)
                    mark_query.execute()
                except Exception:
                    pass

            if background_tasks is not None:
                background_tasks.add_task(mark_read_task)
            else:
                mark_read_task()

        response_payload = {
            'status': 'ok',
            'count': len(messages),
            'data': messages
        }
        if not no_cache:
            _conversation_messages_cache[cache_key] = (time.time(), response_payload)
            if len(_conversation_messages_cache) > 500:
                for stale_key in sorted(_conversation_messages_cache, key=lambda item: _conversation_messages_cache[item][0])[:150]:
                    _conversation_messages_cache.pop(stale_key, None)
        return response_payload

    except Exception as e:
        log("Error fetching conversation messages", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.post("/api/v2/send-message")
async def send_message_v2(
        request: Request,
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    """Send a message via the React UI"""
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
        conversation_id = payload.get("conversation_id")
        text = payload.get("text", "").strip()
        reply_to_comment_id = normalize_id(payload.get("reply_to_comment_id") or payload.get("comment_id"))

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

        platform, business_id, channel, customer_scope = parts
        if not can_access_business(access, business_id):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)
        target_id = customer_scope
        post_id = ""
        if platform == "instagram" and "comment" in channel:
            target_id, post_id = decode_comment_scope(customer_scope)

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

            if "comment" in channel:
                if reply_to_comment_id:
                    anchor = get_instagram_comment_anchor_by_comment_id(
                        business_id=business_id,
                        comment_id=reply_to_comment_id,
                        post_id=post_id,
                    )
                else:
                    anchor = get_latest_instagram_comment_anchor(
                        business_id=business_id,
                        commenter_id=target_id,
                        post_id=post_id,
                    )
                if not target_id:
                    target_id = normalize_id(anchor.get("customer_id"))
                comment_id = reply_to_comment_id or normalize_id(
                    anchor.get("external_message_id")
                    or (anchor.get("raw_payload") or {}).get("id")
                )
                if reply_to_comment_id and not comment_id:
                    comment_id = reply_to_comment_id
                if not comment_id:
                    return JSONResponse(
                        {"error": "Comment anchor not found for this thread"},
                        status_code=400,
                    )

                send_result = reply_to_comment(access_token, comment_id, text, business)
                ok = bool(send_result and send_result.ok)
                result = safe_json(send_result) if send_result is not None else {"error": "Send failed"}
            else:
                ok, result = send_instagram_dm(access_token, target_id, text, business)

        elif platform == "telegram":
            if channel == "telegram_user_private":
                ok, result = await send_telegram_user_message(customer_id=target_id, text=text)
            else:
                res = send_telegram_bot_message(target_id, text)
                if res:
                    ok = res.ok
                    result = safe_json(res)
                else:
                    result = {"error": "Send failed"}

        elif platform == "whatsapp":
            res = send_whatsapp_text(target_id, text, business)
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
            recipient_id=target_id,
            message_text=text,
            direction="outbound",
            platform_message_id=normalize_id(result.get("message_id") or result.get("id") or result.get("messages", [{}])[0].get("id", "")),
            raw_payload={**(result or {}), **({"post_id": post_id} if post_id else {}), **({"reply_to_comment_id": reply_to_comment_id} if reply_to_comment_id else {})},
            channel=channel,
        )

        return {'status': 'ok', 'data': result}

    except Exception as e:
        log("Error sending message", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.post("/api/v2/message/edit")
async def edit_message_v2(
        request: Request,
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
        message_id = payload.get("message_id")
        text = str(payload.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "Message text is required"}, status_code=400)

        row, error = get_inbox_message_for_dashboard(message_id, access)
        if error:
            return error

        platform = normalize_id(row.get("platform")).lower()
        if platform != "telegram":
            return unsupported_message_mutation_response(platform, "editing")

        if row.get("media_type"):
            return JSONResponse({"error": "Only text messages can be edited"}, status_code=400)

        business = get_business_by_id(row.get("business_id"))
        ok, result = await mutate_delivered_telegram_message(row, business, "edit", text=text)
        if not ok:
            return send_failure_response(result, "Could not edit message on Telegram")

        existing_payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
        supabase.table("inbox_messages").update({
            "content": text,
            "raw_payload": {
                **existing_payload,
                "dashboard_edited": True,
                "dashboard_edited_at": datetime.utcnow().isoformat(),
            },
        }).eq("id", row.get("id")).execute()
        clear_inbox_caches()

        return {"status": "ok", "data": result}

    except Exception as e:
        log("Error editing dashboard message", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/api/v2/message/delete")
async def delete_message_v2(
        request: Request,
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
        row, error = get_inbox_message_for_dashboard(payload.get("message_id"), access)
        if error:
            return error

        platform = normalize_id(row.get("platform")).lower()
        if platform != "telegram":
            return unsupported_message_mutation_response(platform, "deletion")

        business = get_business_by_id(row.get("business_id"))
        ok, result = await mutate_delivered_telegram_message(row, business, "delete")
        if not ok:
            return send_failure_response(result, "Could not delete message on Telegram")

        supabase.table("inbox_messages").delete().eq("id", row.get("id")).execute()
        clear_inbox_caches()

        return {"status": "ok", "data": result}

    except Exception as e:
        log("Error deleting dashboard message", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/api/v2/conversation/{conversation_id}/ai-toggle")
async def toggle_ai_v2(
        conversation_id: str,
        request: Request,
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    """Toggle AI for a specific conversation"""
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse(
                {"error": "Invalid conversation ID format"},
                status_code=400
            )

        platform, business_id, channel, customer_scope = parts
        if not can_access_business(access, business_id):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)
        customer_id = customer_scope
        if platform == "instagram" and "comment" in channel:
            legacy_customer_id, post_id = decode_comment_scope(customer_scope)
            customer_id = encode_comment_scope("", post_id) if post_id else legacy_customer_id

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
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    """Delete a dashboard conversation from inbox_messages only."""
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse(
                {"error": "Invalid conversation ID format"},
                status_code=400
            )

        platform, business_id, channel, customer_scope = parts
        if not can_access_business(access, business_id):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)
        customer_id = customer_scope
        post_id = ""
        if platform == "instagram" and "comment" in channel:
            customer_id, post_id = decode_comment_scope(customer_scope)

        query = (
            supabase.table("inbox_messages")
            .delete()
            .eq("platform", platform)
            .eq("business_id", business_id)
        )

        if platform == "telegram" and channel in ("telegram_bot_group", "telegram_bot_private"):
            query = query.or_(f"chat_id.eq.{customer_id},customer_id.eq.{customer_id}")
        elif platform == "instagram" and "comment" in channel:
            if channel:
                query = query.eq("channel", channel)
            if post_id:
                query = query.or_(f"raw_payload->media->>id.eq.{post_id},raw_payload->>post_id.eq.{post_id}")
            elif customer_id:
                query = query.eq("customer_id", str(customer_id))
        else:
            query = query.eq("customer_id", str(customer_id))
            if channel:
                query = query.eq("channel", channel)

        result = query.execute()
        deleted = len(result.data or [])
        clear_inbox_caches()

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
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    """Get full conversation details"""
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        parts = conversation_id.split("::")
        if len(parts) != 4:
            return JSONResponse(
                {"error": "Invalid conversation ID format"},
                status_code=400
            )

        platform, business_id, channel, customer_scope = parts
        if not can_access_business(access, business_id):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        platform = normalize_id(platform).lower()
        channel = standard_channel(platform, channel)
        customer_id = customer_scope
        post_id = ""
        if platform == "instagram" and "comment" in channel:
            customer_id, post_id = decode_comment_scope(customer_scope)

        business = get_business_by_id(business_id)

        query = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", platform)
            .eq("business_id", business_id)
        )

        if platform == "instagram" and "comment" in channel:
            if channel:
                query = query.eq("channel", channel)
            if post_id:
                query = query.or_(f"raw_payload->media->>id.eq.{post_id},raw_payload->>post_id.eq.{post_id}")
            elif customer_id:
                query = query.eq("customer_id", str(customer_id))
        else:
            query = query.eq("customer_id", str(customer_id))
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


def _lang_copy(lang: str, en: str, uz: str, ru: str) -> str:
    value = normalize_id(lang).lower()
    if value.startswith("uz"):
        return uz
    if value.startswith("ru"):
        return ru
    return en


def _has_any_term(text: str, terms: list[str]) -> bool:
    lowered = normalize_id(text).lower()
    if not lowered:
        return False
    return any(term in lowered for term in terms)


def _is_instagram_story_reply_row(row: dict) -> bool:
    raw = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
    message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    if message.get("is_story_reply") or message.get("story"):
        return True
    if raw.get("is_story_reply") or raw.get("story"):
        return True
    attachments = raw.get("attachments") if isinstance(raw.get("attachments"), list) else []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        if normalize_id(item.get("type")).lower() in {"ig_story", "story_mention", "story"}:
            return True
    return False


def _instagram_question_theme(text: str) -> str:
    lowered = normalize_id(text).lower()
    if not lowered:
        return ""
    if _has_any_term(lowered, ["price", "narx", "qancha", "цена", "сколько"]):
        return "price"
    if _has_any_term(lowered, ["delivery", "dostavka", "yetkaz", "карго", "доставка"]):
        return "delivery"
    if _has_any_term(lowered, ["wholesale", "optom", "ulgurji", "оптом"]):
        return "wholesale"
    if _has_any_term(lowered, ["size", "razmer", "o'lcham", "размер"]):
        return "size"
    if _has_any_term(lowered, ["quality", "sifat", "качество", "материал"]):
        return "quality"
    if _has_any_term(lowered, ["catalog", "katalog", "каталог", "model", "модель"]):
        return "catalog"
    return "general"


def _instagram_product_interest(text: str) -> str:
    lowered = normalize_id(text).lower()
    if not lowered:
        return ""
    mapping = [
        ("xalat", ["xalat", "халат"]),
        ("pijama", ["pijama", "пижам", "pijam"]),
        ("sumka", ["sumka", "сумка", "bag"]),
        ("dress", ["dress", "ko'ylak", "плать", "kuylak"]),
        ("set", ["komplekt", "set", "набор"]),
    ]
    for label, terms in mapping:
        if _has_any_term(lowered, terms):
            return label
    return ""


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_instagram_timestamp(value: str) -> Optional[datetime]:
    text = normalize_id(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _graph_get_json(url: str, access_token: str, params: dict = None, timeout: int = 30) -> tuple[bool, dict]:
    query = dict(params or {})
    query["access_token"] = access_token
    try:
        res = requests.get(url, params=query, timeout=timeout)
        body = safe_json(res)
        if not isinstance(body, dict):
            body = {"raw": body}
        if not res.ok:
            body.setdefault("error", {"message": f"Graph API request failed with HTTP {res.status_code}"})
        return res.ok, body
    except Exception as exc:
        return False, {"error": {"message": str(exc)}}


def _graph_paginated_get(
    start_url: str,
    access_token: str,
    params: dict = None,
    max_items: int = 120,
    max_pages: int = 8,
) -> tuple[list[dict], list[str]]:
    url = start_url
    query = dict(params or {})
    items: list[dict] = []
    errors: list[str] = []

    for _ in range(max_pages):
        ok, body = _graph_get_json(url, access_token, query if url == start_url else None)
        if not ok:
            error_message = normalize_id((((body or {}).get("error") or {}).get("message")) or "Graph API request failed")
            if error_message:
                errors.append(error_message)
            break

        data = body.get("data") if isinstance(body, dict) else []
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    items.append(row)
                if len(items) >= max_items:
                    break
        if len(items) >= max_items:
            break

        paging = body.get("paging") if isinstance(body, dict) else {}
        next_url = normalize_id((paging or {}).get("next"))
        if not next_url:
            break
        url = next_url
        query = {}

    return items[:max_items], errors


def _resolve_instagram_account_id_for_analysis(business: dict, access_token: str) -> tuple[str, dict]:
    current = normalize_id((business or {}).get("instagram_business_id"))
    if current and not current.startswith("whatsapp_"):
        return current, {"source": "business.instagram_business_id", "id": current}

    page_id = normalize_id((business or {}).get("facebook_page_id"))
    if page_id and access_token:
        ok, body = _graph_get_json(
            f"{GRAPH_FACEBOOK}/{page_id}",
            access_token,
            {"fields": "instagram_business_account{id,username}"},
        )
        if ok:
            ig = (body.get("instagram_business_account") or {}) if isinstance(body, dict) else {}
            account_id = normalize_id(ig.get("id"))
            if account_id:
                return account_id, {
                    "source": "facebook_page_lookup",
                    "id": account_id,
                    "username": normalize_id(ig.get("username")),
                }
    return "", {"source": "not_resolved"}


def fetch_instagram_live_snapshot(business: dict, days: int = 30) -> dict:
    access_token = normalize_id(get_business_access_token(business))
    if not access_token:
        raise ValueError("Instagram access token is missing. Reconnect the Instagram account.")

    account_id, account_meta = _resolve_instagram_account_id_for_analysis(business, access_token)
    if not account_id:
        raise ValueError("Could not resolve Instagram professional account ID from connected business.")

    safe_days = max(7, min(int(days or 30), 120))
    now_utc = datetime.utcnow()
    since_dt = now_utc - timedelta(days=safe_days)
    since_unix = int(since_dt.timestamp())

    profile_fields = "id,username,name,biography,followers_count,follows_count,media_count,website,profile_picture_url"
    ok_profile, profile_body = _graph_get_json(
        f"{GRAPH_FACEBOOK}/{account_id}",
        access_token,
        {"fields": profile_fields},
    )
    if not ok_profile:
        error_message = normalize_id((((profile_body or {}).get("error") or {}).get("message")) or "Could not fetch Instagram profile")
        raise ValueError(error_message or "Could not fetch Instagram profile")

    media_fields = "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count"
    media, media_errors = _graph_paginated_get(
        f"{GRAPH_FACEBOOK}/{account_id}/media",
        access_token,
        {"fields": media_fields, "limit": 25, "since": since_unix},
        max_items=200,
        max_pages=10,
    )

    filtered_media: list[dict] = []
    for item in media:
        ts = _parse_instagram_timestamp(item.get("timestamp"))
        if ts and ts < since_dt:
            continue
        filtered_media.append(item)

    comment_errors: list[str] = []
    media_by_comments = sorted(
        filtered_media,
        key=lambda row: _safe_int(row.get("comments_count"), 0),
        reverse=True,
    )[:30]
    all_comments: list[dict] = []
    for media_item in media_by_comments:
        media_id = normalize_id(media_item.get("id"))
        if not media_id:
            continue
        comments, errors = _graph_paginated_get(
            f"{GRAPH_FACEBOOK}/{media_id}/comments",
            access_token,
            {"fields": "id,text,timestamp,username,like_count,replies_count", "limit": 20},
            max_items=80,
            max_pages=4,
        )
        comment_errors.extend(errors)
        for row in comments:
            if not isinstance(row, dict):
                continue
            row["media_id"] = media_id
            row["media_type"] = normalize_id(media_item.get("media_type"))
            row["media_product_type"] = normalize_id(media_item.get("media_product_type"))
            all_comments.append(row)

    stories, story_errors = _graph_paginated_get(
        f"{GRAPH_FACEBOOK}/{account_id}/stories",
        access_token,
        {"fields": "id,media_type,media_url,permalink,timestamp", "limit": 25},
        max_items=50,
        max_pages=3,
    )

    account_insights_ok, account_insights_body = _graph_get_json(
        f"{GRAPH_FACEBOOK}/{account_id}/insights",
        access_token,
        {"metric": "impressions,reach,profile_views", "period": "day"},
    )

    insights = []
    insight_errors: list[str] = []
    if account_insights_ok and isinstance(account_insights_body, dict):
        insights = account_insights_body.get("data") if isinstance(account_insights_body.get("data"), list) else []
    else:
        msg = normalize_id((((account_insights_body or {}).get("error") or {}).get("message")))
        if msg:
            insight_errors.append(msg)

    return {
        "source": "instagram_graph_api",
        "fetched_at": now_utc.isoformat() + "Z",
        "range_days": safe_days,
        "account_meta": account_meta,
        "profile": profile_body if isinstance(profile_body, dict) else {},
        "media": filtered_media,
        "stories": stories,
        "comments": all_comments,
        "account_insights": insights,
        "fetch_errors": {
            "media": media_errors,
            "comments": comment_errors[:8],
            "stories": story_errors,
            "insights": insight_errors,
        },
        "api_scope_notes": {
            "highlights_accessible": False,
            "highlights_note": "Instagram Graph API does not provide highlights directly. Use Stories and profile checks.",
        },
    }


def _extract_metric_total_from_insights(insights_rows: list[dict], metric_name: str) -> int:
    total = 0
    for row in insights_rows or []:
        if normalize_id(row.get("name")) != metric_name:
            continue
        values = row.get("values") if isinstance(row.get("values"), list) else []
        for value in values:
            if isinstance(value, dict):
                total += _safe_int(value.get("value"), 0)
    return total


def build_instagram_growth_analysis_from_live(snapshot: dict, business: dict, days: int = 30) -> dict:
    lang = normalize_id((business or {}).get("language")).lower() or "uz"
    business_name = normalize_id((business or {}).get("business_name")) or "Business"
    safe_days = max(7, min(int(days or 30), 120))

    profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), dict) else {}
    media = snapshot.get("media") if isinstance(snapshot.get("media"), list) else []
    stories = snapshot.get("stories") if isinstance(snapshot.get("stories"), list) else []
    comments = snapshot.get("comments") if isinstance(snapshot.get("comments"), list) else []
    account_insights = snapshot.get("account_insights") if isinstance(snapshot.get("account_insights"), list) else []
    fetch_errors = snapshot.get("fetch_errors") if isinstance(snapshot.get("fetch_errors"), dict) else {}

    captions = [normalize_id(item.get("caption")) for item in media if normalize_id(item.get("caption"))]
    cta_terms = ["direkt", "direct", "dm", "message", "yozing", "write", "contact", "katalog", "catalog"]
    cta_hits = sum(1 for caption in captions if _has_any_term(caption, cta_terms))
    cta_rate = cta_hits / max(1, len(captions))

    hook_hits = 0
    for caption in captions:
        first_chunk = caption[:90]
        if "?" in first_chunk or re.search(r"\d", first_chunk) or _has_any_term(first_chunk, ["how", "qanday", "nima", "necha", "сколько", "как"]):
            hook_hits += 1
    hook_rate = hook_hits / max(1, len(captions))

    reels = [
        row for row in media
        if "reel" in normalize_id(row.get("media_product_type")).lower()
        or "video" in normalize_id(row.get("media_type")).lower()
    ]
    reels_count = len(reels)
    post_count = len(media)
    reel_share = reels_count / max(1, post_count)

    followers = _safe_int(profile.get("followers_count"), 0)
    total_likes = sum(_safe_int(item.get("like_count"), 0) for item in media)
    total_comment_counts = sum(_safe_int(item.get("comments_count"), 0) for item in media)
    avg_engagement_rate = ((total_likes + total_comment_counts) / max(1, followers * max(1, post_count))) * 100

    question_counts = {"price": 0, "delivery": 0, "wholesale": 0, "size": 0, "quality": 0, "catalog": 0, "general": 0}
    product_counts = {}
    for item in comments:
        text = normalize_id(item.get("text"))
        if not text:
            continue
        if "?" in text or _has_any_term(text, ["narx", "price", "qancha", "delivery", "dostavka", "wholesale", "ulgurji", "optom", "katalog", "catalog"]):
            theme = _instagram_question_theme(text)
            question_counts[theme] = question_counts.get(theme, 0) + 1
        product_label = _instagram_product_interest(text)
        if product_label:
            product_counts[product_label] = product_counts.get(product_label, 0) + 1

    top_product = ""
    if product_counts:
        top_product = sorted(product_counts.items(), key=lambda item: item[1], reverse=True)[0][0]

    profile_score = 0
    if normalize_id(profile.get("username")):
        profile_score += 4
    if normalize_id(profile.get("biography")):
        profile_score += 4
    if normalize_id(profile.get("website")):
        profile_score += 3
    if followers > 0:
        profile_score += 4
    if normalize_id((business or {}).get("sales_phone")):
        profile_score += 2
    if normalize_id((business or {}).get("catalog_link")):
        profile_score += 3
    profile_score = max(0, min(20, profile_score))

    content_score = 0
    content_score += min(9, post_count)
    content_score += 6 if reel_share >= 0.4 else (4 if reel_share >= 0.2 else 2)
    content_score += min(5, len(stories))
    content_score += 5 if hook_rate >= 0.5 else (3 if hook_rate >= 0.25 else 1)
    content_score = max(0, min(25, content_score))

    caption_cta_score = max(0, min(20, int(round(cta_rate * 20))))

    engagement_score = 0
    if avg_engagement_rate >= 4:
        engagement_score += 10
    elif avg_engagement_rate >= 2:
        engagement_score += 8
    elif avg_engagement_rate >= 1:
        engagement_score += 6
    else:
        engagement_score += 3
    engagement_score += min(5, len(comments) // 10)
    engagement_score += min(5, _extract_metric_total_from_insights(account_insights, "profile_views") // 100)
    engagement_score = max(0, min(20, engagement_score))

    conversion_signals = question_counts.get("price", 0) + question_counts.get("catalog", 0) + question_counts.get("wholesale", 0)
    conversion_score = 0
    conversion_score += min(6, conversion_signals)
    conversion_score += min(5, int(round(cta_rate * 5)))
    conversion_score += 2 if top_product else 0
    conversion_score += 2 if normalize_id((business or {}).get("catalog_link")) else 0
    conversion_score = max(0, min(15, conversion_score))

    account_score = max(0, min(100, profile_score + content_score + caption_cta_score + engagement_score + conversion_score))

    problems = []
    if hook_rate < 0.35:
        problems.append(_lang_copy(lang, "Reels/posts need stronger first-3-second hooks.", "Reel/postlarda birinchi 3 soniya hooklari kuchliroq bo'lishi kerak.", "Reels/постам нужны более сильные hooks в первые 3 секунды."))
    if cta_rate < 0.4:
        problems.append(_lang_copy(lang, "Captions are not consistently pushing DM conversion.", "Captionlar doimiy ravishda DM konversiyasiga undamayapti.", "Caption недостаточно стабильно ведут к конверсии в DM."))
    if len(stories) < 3:
        problems.append(_lang_copy(lang, "Story activity is low this period.", "Bu davrda story faolligi past.", "Активность сторис в этом периоде низкая."))
    if question_counts.get("wholesale", 0) >= 3:
        problems.append(_lang_copy(lang, "Wholesale expectations need clearer content explanation.", "Ulgurji kutilmalarni kontentda aniqroq tushuntirish kerak.", "Нужно яснее объяснять условия опта в контенте."))
    if not problems:
        problems.append(_lang_copy(lang, "Performance is stable; focus on stronger conversion CTA and scaling winning content.", "Natija barqaror; konversiya CTA va ishlagan kontentni masshtablashga urg'u bering.", "Результат стабилен; усилите CTA на конверсию и масштабируйте лучший контент."))

    promote_product = top_product or _lang_copy(lang, "best seller", "eng talabgir model", "самая востребованная модель")
    faq_sorted = sorted(question_counts.items(), key=lambda item: item[1], reverse=True)
    common_questions = []
    theme_copy = {
        "price": _lang_copy(lang, "Price and discounts", "Narx va chegirmalar", "Цена и скидки"),
        "delivery": _lang_copy(lang, "Delivery and cargo timing", "Yetkazib berish va cargo muddatlari", "Сроки доставки и карго"),
        "wholesale": _lang_copy(lang, "Wholesale terms", "Ulgurji shartlar", "Условия опта"),
        "size": _lang_copy(lang, "Size and fit", "Razmer va moslik", "Размер и посадка"),
        "quality": _lang_copy(lang, "Quality and material proof", "Sifat va material isboti", "Качество и материал"),
        "catalog": _lang_copy(lang, "Catalog request", "Katalog so'rovi", "Запрос каталога"),
        "general": _lang_copy(lang, "General product details", "Umumiy mahsulot tafsilotlari", "Общие детали о товаре"),
    }
    for key, value in faq_sorted:
        if value <= 0:
            continue
        common_questions.append({"theme": theme_copy.get(key, key), "count": value})
        if len(common_questions) >= 5:
            break

    analysis_scope = _lang_copy(
        lang,
        "Live analysis from Instagram Graph API (profile, media, captions, comments, stories/insights when accessible). Highlights are limited by API.",
        "Tahlil Instagram Graph API orqali live olindi (profil, media, caption, komment, stories/insights imkon bo'lsa). Highlights APIda cheklangan.",
        "Анализ получен в live-режиме через Instagram Graph API (профиль, медиа, caption, комментарии, stories/insights при доступе). Highlights ограничены API.",
    )

    return {
        "dashboard_section_name": "Instagram Growth Analyzer",
        "business_name": business_name,
        "date_range_days": safe_days,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_source": "instagram_graph_api_live",
        "fetched_at": normalize_id(snapshot.get("fetched_at")),
        "account_score": int(account_score),
        "category_scores": {
            "profile_quality": int(profile_score),
            "content_quality": int(content_score),
            "caption_cta_strength": int(caption_cta_score),
            "engagement_health": int(engagement_score),
            "conversion_readiness": int(conversion_score),
        },
        "problems": problems,
        "recommended_next_content": [
            {"type": "reel", "idea": _lang_copy(lang, f"What is inside 1 package of {promote_product}?", f"1 qopda {promote_product}dan nimalar bor?", f"Что входит в 1 упаковку {promote_product}?")},
            {"type": "story_poll", "idea": _lang_copy(lang, "Poll: Which model do you like more?", "So'rovnoma: Qaysi model ko'proq yoqdi?", "Опрос: Какая модель нравится больше?")},
            {"type": "post", "idea": _lang_copy(lang, "Factory/product quality proof", "Factory/sifat isboti", "Подтверждение качества фабрики/товара")},
            {"type": "reel", "idea": _lang_copy(lang, "Cargo delivery explanation", "Cargo yetkazib berish tushuntiruvi", "Объяснение карго-доставки")},
            {"type": "story_cta", "idea": _lang_copy(lang, "Need catalog? Write in DM.", "Katalog kerakmi? Direktga yozing.", "Нужен каталог? Напишите в DM.")},
        ],
        "product_to_promote_this_week": promote_product,
        "first_3_seconds_hooks": [
            _lang_copy(lang, "Show product result in second 1, then package detail in second 2.", "1-soniyada natija, 2-soniyada qadoq detali ko'rsating.", "В 1-й секунде результат, во 2-й детали упаковки."),
            _lang_copy(lang, "Use a direct subtitle question in first frame.", "Birinchi freymda to'g'ridan-to'g'ri savol subtitle ishlating.", "Используйте прямой вопрос в субтитре с первого кадра."),
            _lang_copy(lang, "Finish with one clear DM CTA.", "Oxirini bitta aniq DM CTA bilan tugating.", "Завершайте одним четким CTA в DM."),
        ],
        "story_ideas": [
            _lang_copy(lang, "Poll: favorite model", "Poll: sevimli model", "Опрос: любимая модель"),
            _lang_copy(lang, "Q&A: delivery + wholesale", "Q&A: yetkazib berish + ulgurji", "Q&A: доставка + опт"),
            _lang_copy(lang, "Customer reaction screenshot + CTA", "Mijoz fikri screenshot + CTA", "Скрин отзыва клиента + CTA"),
        ],
        "common_customer_questions": common_questions,
        "content_gaps": [
            _lang_copy(lang, "Need more hook-driven reels.", "Hookga asoslangan reel soni ko'paytirilsin.", "Нужно больше reels с сильным hook."),
            _lang_copy(lang, "Need consistent CTA in captions.", "Captionlarda CTA izchil bo'lishi kerak.", "Нужен стабильный CTA в caption."),
            _lang_copy(lang, "Need more interactive stories.", "Interaktiv storylar ko'paytirilsin.", "Нужно больше интерактивных сторис."),
        ],
        "weekly_content_plan": [
            _lang_copy(lang, "Mon: Reel with strong opening hook + DM CTA.", "Du: kuchli opening hookli reel + DM CTA.", "Пн: Reel с сильным opening hook + CTA в DM."),
            _lang_copy(lang, "Tue: Story poll and quick response sticker.", "Se: Story poll va tezkor javob stikeri.", "Вт: Опрос в сторис и стикер быстрых ответов."),
            _lang_copy(lang, "Wed: Quality proof post.", "Cho: sifat isboti posti.", "Ср: Пост с доказательством качества."),
            _lang_copy(lang, "Thu: Delivery process reel.", "Pa: yetkazib berish jarayoni reeli.", "Чт: Reel про процесс доставки."),
            _lang_copy(lang, "Fri: FAQ carousel from comment questions.", "Ju: komment savollaridan FAQ karusel.", "Пт: FAQ-карусель из вопросов в комментариях."),
        ],
        "monthly_content_plan": [
            _lang_copy(lang, "Week 1: Product and visual trust.", "1-hafta: mahsulot va vizual ishonch.", "1 неделя: доверие к товару и визуалу."),
            _lang_copy(lang, "Week 2: Pricing and wholesale clarity.", "2-hafta: narx va ulgurji aniqlik.", "2 неделя: ясность цен и опта."),
            _lang_copy(lang, "Week 3: Delivery and social proof.", "3-hafta: yetkazib berish va social proof.", "3 неделя: доставка и социальное доказательство."),
            _lang_copy(lang, "Week 4: Conversion CTA campaign.", "4-hafta: konversiya CTA kampaniyasi.", "4 неделя: кампания CTA на конверсию."),
        ],
        "account_improvement_tasks": [
            _lang_copy(lang, "Prepare 10 caption CTA templates.", "10 ta caption CTA shabloni tayyorlang.", "Подготовьте 10 шаблонов CTA для caption."),
            _lang_copy(lang, "Prepare 5 first-3-second hook templates.", "5 ta birinchi-3-soniya hook shabloni tayyorlang.", "Подготовьте 5 шаблонов hooks на первые 3 секунды."),
            _lang_copy(lang, "Publish 3+ interactive stories per week.", "Haftasiga kamida 3 ta interaktiv story chiqaring.", "Публикуйте минимум 3 интерактивные сторис в неделю."),
        ],
        "analysis_scope": analysis_scope,
        "metrics": {
            "profile_followers": followers,
            "profile_media_count": _safe_int(profile.get("media_count"), 0),
            "fetched_media_count": post_count,
            "fetched_reels_count": reels_count,
            "fetched_story_count": len(stories),
            "fetched_comments_count": len(comments),
            "caption_cta_rate": round(cta_rate, 3),
            "hook_rate": round(hook_rate, 3),
            "avg_engagement_rate_percent": round(avg_engagement_rate, 3),
            "impressions_24h_total": _extract_metric_total_from_insights(account_insights, "impressions"),
            "reach_24h_total": _extract_metric_total_from_insights(account_insights, "reach"),
            "profile_views_24h_total": _extract_metric_total_from_insights(account_insights, "profile_views"),
        },
        "live_fetch_summary": {
            "account_id": normalize_id(profile.get("id")) or normalize_id((snapshot.get("account_meta") or {}).get("id")),
            "username": normalize_id(profile.get("username")) or normalize_id((snapshot.get("account_meta") or {}).get("username")),
            "fetch_errors": fetch_errors,
            "api_scope_notes": snapshot.get("api_scope_notes") or {},
        },
    }


def save_instagram_growth_report_history(business_id: str, report: dict, updated_by: str = ""):
    business_id = normalize_id(business_id)
    if not business_id or not isinstance(report, dict):
        return

    state = get_workspace_state(business_id)
    existing = state.get("instagram_growth_reports") if isinstance(state, dict) else {}
    items = []
    if isinstance(existing, dict):
        items = existing.get("items") if isinstance(existing.get("items"), list) else []
    elif isinstance(existing, list):
        items = existing

    entry = {
        "generated_at": report.get("generated_at"),
        "fetched_at": report.get("fetched_at"),
        "date_range_days": report.get("date_range_days"),
        "account_score": report.get("account_score"),
        "data_source": report.get("data_source", "instagram_graph_api_live"),
        "business_name": report.get("business_name", ""),
        "metrics": report.get("metrics", {}),
        "summary": {
            "problems": (report.get("problems") or [])[:4],
            "product_to_promote_this_week": report.get("product_to_promote_this_week", ""),
        },
        "report": report,
    }
    next_items = [entry] + [item for item in items if isinstance(item, dict)]
    next_items = next_items[:30]

    upsert_workspace_state(
        business_id=business_id,
        state_key="instagram_growth_latest",
        state_value=entry,
        updated_by=updated_by,
    )
    upsert_workspace_state(
        business_id=business_id,
        state_key="instagram_growth_reports",
        state_value={"items": next_items},
        updated_by=updated_by,
    )


def build_instagram_growth_analysis(rows: list[dict], business: dict, days: int = 30) -> dict:
    lang = normalize_id((business or {}).get("language")).lower() or "uz"
    business_name = normalize_id((business or {}).get("business_name")) or "Business"
    safe_days = max(7, min(int(days or 30), 120))

    if not rows:
        return {
            "dashboard_section_name": "Instagram Growth Analyzer",
            "business_name": business_name,
            "date_range_days": safe_days,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "account_score": 52,
            "category_scores": {
                "profile_quality": 12,
                "content_quality": 10,
                "caption_cta_strength": 8,
                "engagement_health": 12,
                "conversion_readiness": 10,
            },
            "problems": [
                _lang_copy(
                    lang,
                    "Not enough recent Instagram data to evaluate reels/hooks.",
                    "Reels/hooklarni baholash uchun oxirgi ma'lumotlar yetarli emas.",
                    "Недостаточно данных для оценки reels и первых секунд.",
                ),
                _lang_copy(
                    lang,
                    "CTA quality is unknown because outbound Instagram copy is limited.",
                    "CTA sifati noaniq, chunki Instagram outbound matnlar kam.",
                    "Сила CTA неясна: мало исходящих текстов Instagram.",
                ),
            ],
            "recommended_next_content": [
                {"type": "reel", "idea": "1 qopda qanday mahsulotlar bor?"},
                {"type": "story_poll", "idea": "Qaysi model yoqdi: xalat yoki pijama?"},
                {"type": "post", "idea": "Factory / product quality proof"},
                {"type": "story_cta", "idea": "Katalog kerakmi? Direktga yozing."},
            ],
            "product_to_promote_this_week": _lang_copy(lang, "Best seller set", "Eng ko'p so'raladigan set", "Самый часто спрашиваемый комплект"),
            "first_3_seconds_hooks": [
                _lang_copy(lang, "Show result first, then explain price and quality.", "Natijani birinchi ko'rsating, keyin narx va sifatni ayting.", "Сначала покажите результат, затем цену и качество."),
                _lang_copy(lang, "Use close-up in second 1 and subtitle in second 2.", "1-soniyada close-up, 2-soniyada subtitle qo'ying.", "Крупный план в 1-й секунде, субтитр во 2-й."),
            ],
            "story_ideas": [
                _lang_copy(lang, "Story poll about favorite model", "Model bo'yicha story so'rovnoma", "Опрос в сторис по любимой модели"),
                _lang_copy(lang, "Story Q&A: delivery and wholesale rules", "Yetkazib berish va ulgurji qoidalar bo'yicha Q&A", "Q&A в сторис по доставке и опту"),
            ],
            "common_customer_questions": [],
            "content_gaps": [
                _lang_copy(lang, "Need stronger reel hooks", "Reels uchun kuchliroq hook kerak", "Нужны более сильные hooks для reels"),
                _lang_copy(lang, "Need regular story reply collection", "Story reply yig'ishni muntazam qilish kerak", "Нужно регулярно собирать ответы в сторис"),
            ],
            "weekly_content_plan": [
                _lang_copy(lang, "Mon: Reel with product close-up and clear CTA", "Du: Mahsulot close-up reel + aniq CTA", "Пн: Reel с крупным планом и четким CTA"),
                _lang_copy(lang, "Wed: Story poll + follow-up story", "Chor: Story so'rovnoma + follow-up", "Ср: Опрос в сторис + follow-up"),
                _lang_copy(lang, "Fri: Quality proof post with caption CTA", "Juma: Sifat isboti posti + CTA", "Пт: Пост с доказательством качества + CTA"),
            ],
            "monthly_content_plan": [
                _lang_copy(lang, "Week 1: Product showcase reels", "1-hafta: mahsulot showcase reels", "1 неделя: reels-витрина товаров"),
                _lang_copy(lang, "Week 2: Delivery + trust content", "2-hafta: yetkazib berish + ishonch kontenti", "2 неделя: доставка + доверие"),
                _lang_copy(lang, "Week 3: FAQ-driven content", "3-hafta: FAQ asosida kontent", "3 неделя: контент по FAQ"),
                _lang_copy(lang, "Week 4: Offer + conversion push", "4-hafta: taklif + konversiya push", "4 неделя: оффер + конверсия"),
            ],
            "account_improvement_tasks": [
                _lang_copy(lang, "Create 5 reusable first-3-second reel hooks.", "5 ta birinchi-3-soniya reel hook tayyorlang.", "Подготовьте 5 готовых hooks для первых 3 секунд."),
                _lang_copy(lang, "Add CTA template at the end of every caption.", "Har caption oxiriga CTA shablon qo'shing.", "Добавляйте CTA-шаблон в конец каждого caption."),
            ],
            "analysis_scope": _lang_copy(
                lang,
                "Based on CRM message history. Direct profile elements (bio/logo/highlights) should be reviewed manually in Instagram app.",
                "Tahlil CRM xabarlariga asoslangan. Bio/logo/highlights kabi profil elementlarini Instagram ilovasida qo'lda tekshirish kerak.",
                "Анализ основан на истории CRM. Элементы профиля (bio/logo/highlights) нужно проверить вручную в Instagram.",
            ),
            "metrics": {"total_instagram_messages": 0},
        }

    inbound_rows = [row for row in rows if normalize_id(row.get("direction")).lower() == "inbound"]
    outbound_rows = [row for row in rows if normalize_id(row.get("direction")).lower() == "outbound"]
    comment_inbound = [
        row for row in inbound_rows
        if "comment" in standard_channel("instagram", row.get("channel")).lower()
    ]
    dm_inbound = [
        row for row in inbound_rows
        if standard_channel("instagram", row.get("channel")) in {"dm", "instagram_dm", "instagram_private", ""}
    ]

    outbound_texts = [normalize_id(row.get("content")) for row in outbound_rows if normalize_id(row.get("content"))]
    inbound_texts = [normalize_id(row.get("content")) for row in inbound_rows if normalize_id(row.get("content"))]
    story_reply_count = sum(1 for row in inbound_rows if _is_instagram_story_reply_row(row))

    cta_terms = ["direkt", "direct", "dm", "message", "yozing", "write", "contact", "katalog", "catalog"]
    cta_hits = sum(1 for text in outbound_texts if _has_any_term(text, cta_terms))
    cta_rate = cta_hits / max(1, len(outbound_texts))

    question_counts = {"price": 0, "delivery": 0, "wholesale": 0, "size": 0, "quality": 0, "catalog": 0, "general": 0}
    product_counts = {}
    wholesale_outbound_mentions = 0
    for text in inbound_texts:
        if "?" in text or _has_any_term(text, ["narx", "price", "qancha", "delivery", "dostavka", "wholesale", "optom", "ulgurji"]):
            theme = _instagram_question_theme(text)
            question_counts[theme] = question_counts.get(theme, 0) + 1
        product_label = _instagram_product_interest(text)
        if product_label:
            product_counts[product_label] = product_counts.get(product_label, 0) + 1
    for text in outbound_texts:
        if _has_any_term(text, ["wholesale", "optom", "ulgurji", "оптом"]):
            wholesale_outbound_mentions += 1

    post_engagement = {}
    for row in comment_inbound:
        post_id = extract_instagram_comment_post_id(row)
        if not post_id:
            continue
        info = post_engagement.setdefault(post_id, {"count": 0, "media_type": "", "sample": ""})
        info["count"] += 1
        media_type = normalize_id(
            row.get("post_media_type")
            or (row.get("raw_payload") or {}).get("post_media_type")
        ).lower()
        if media_type and not info["media_type"]:
            info["media_type"] = media_type
        if not info["sample"]:
            info["sample"] = normalize_id(row.get("content"))[:120]

    post_count = len(post_engagement)
    reel_post_count = sum(
        1 for item in post_engagement.values()
        if "reel" in normalize_id(item.get("media_type")).lower()
        or "video" in normalize_id(item.get("media_type")).lower()
    )
    reel_share = (reel_post_count / post_count) if post_count else 0.0

    active_days = {
        normalize_id(row.get("created_at"))[:10]
        for row in rows
        if normalize_id(row.get("created_at"))
    }
    active_day_count = len(active_days)

    top_product = ""
    if product_counts:
        top_product = sorted(product_counts.items(), key=lambda item: item[1], reverse=True)[0][0]

    profile_score = 0
    if normalize_id((business or {}).get("business_name")):
        profile_score += 4
    if normalize_id((business or {}).get("catalog_link")):
        profile_score += 4
    if normalize_id((business or {}).get("sales_phone")):
        profile_score += 3
    if normalize_id((business or {}).get("products")) or normalize_id((business or {}).get("knowledge")):
        profile_score += 4
    if normalize_id((business or {}).get("faq")) or normalize_id((business or {}).get("delivery_info")):
        profile_score += 3
    if (business or {}).get("auto_reply_dms") is True:
        profile_score += 1
    if (business or {}).get("auto_reply_comments") is True:
        profile_score += 1
    profile_score = max(0, min(20, profile_score))

    content_score = 0
    content_score += min(8, post_count * 2)
    if reel_share >= 0.45:
        content_score += 7
    elif reel_share >= 0.25:
        content_score += 5
    else:
        content_score += 2
    if story_reply_count >= 8:
        content_score += 4
    elif story_reply_count >= 3:
        content_score += 2
    if active_day_count >= 16:
        content_score += 6
    elif active_day_count >= 8:
        content_score += 4
    else:
        content_score += 2
    content_score = max(0, min(25, content_score))

    caption_cta_score = max(0, min(20, int(round(cta_rate * 20))))

    inbound_outbound_balance = len(outbound_rows) / max(1, len(inbound_rows))
    engagement_score = 0
    if 0.45 <= inbound_outbound_balance <= 1.6:
        engagement_score += 8
    elif 0.25 <= inbound_outbound_balance <= 2.2:
        engagement_score += 6
    else:
        engagement_score += 3
    engagement_score += min(6, story_reply_count)
    engagement_score += min(6, sum(question_counts.values()) // 2)
    engagement_score = max(0, min(20, engagement_score))

    conversion_signals = question_counts.get("price", 0) + question_counts.get("catalog", 0) + question_counts.get("wholesale", 0)
    conversion_score = 0
    conversion_score += min(7, conversion_signals)
    conversion_score += min(5, int(round(cta_rate * 5)))
    if top_product:
        conversion_score += 3
    conversion_score = max(0, min(15, conversion_score))

    account_score = profile_score + content_score + caption_cta_score + engagement_score + conversion_score
    account_score = max(0, min(100, account_score))

    problems = []
    if reel_share < 0.25:
        problems.append(_lang_copy(
            lang,
            "Reels do not have strong first 3 seconds.",
            "Reels birinchi 3 soniyada kuchli hook bermayapti.",
            "В reels нет сильного хука в первые 3 секунды.",
        ))
    if cta_rate < 0.35:
        problems.append(_lang_copy(
            lang,
            "Captions do not push customers to DM.",
            "Captionlar mijozni Direktga undamayapti.",
            "Caption не подталкивает клиента написать в DM.",
        ))
    if story_reply_count < 3:
        problems.append(_lang_copy(
            lang,
            "Stories are not collecting enough replies.",
            "Stories yetarli reply yig'mayapti.",
            "Stories собирают мало ответов.",
        ))
    if question_counts.get("wholesale", 0) >= 2 and wholesale_outbound_mentions == 0:
        problems.append(_lang_copy(
            lang,
            "Wholesale rules are not explained clearly.",
            "Ulgurji qoidalar kontentda aniq tushuntirilmagan.",
            "Правила опта объяснены недостаточно ясно.",
        ))
    if not problems:
        problems.append(_lang_copy(
            lang,
            "Keep improving CTA consistency and hook quality.",
            "CTA izchilligi va hook sifatini doimiy kuchaytiring.",
            "Продолжайте усиливать CTA и качество hooks.",
        ))

    promote_product = top_product or _lang_copy(lang, "best-seller set", "eng talab yuqori model", "самая востребованная модель")
    faq_sorted = sorted(question_counts.items(), key=lambda item: item[1], reverse=True)
    common_questions = []
    theme_copy = {
        "price": _lang_copy(lang, "Price and discounts", "Narx va chegirmalar", "Цена и скидки"),
        "delivery": _lang_copy(lang, "Delivery time and cargo", "Yetkazib berish va cargo", "Сроки доставки и карго"),
        "wholesale": _lang_copy(lang, "Wholesale minimum order", "Ulgurji minimal buyurtma", "Минимальный оптовый заказ"),
        "size": _lang_copy(lang, "Size and fit", "Razmer va o'lcham", "Размер и посадка"),
        "quality": _lang_copy(lang, "Quality proof", "Sifat isboti", "Подтверждение качества"),
        "catalog": _lang_copy(lang, "Catalog request", "Katalog so'rovi", "Запрос каталога"),
        "general": _lang_copy(lang, "General product details", "Umumiy mahsulot ma'lumoti", "Общие детали о товаре"),
    }
    for key, value in faq_sorted:
        if value <= 0:
            continue
        common_questions.append({"theme": theme_copy.get(key, key), "count": value})
        if len(common_questions) >= 5:
            break

    return {
        "dashboard_section_name": "Instagram Growth Analyzer",
        "business_name": business_name,
        "date_range_days": safe_days,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "account_score": int(account_score),
        "category_scores": {
            "profile_quality": int(profile_score),
            "content_quality": int(content_score),
            "caption_cta_strength": int(caption_cta_score),
            "engagement_health": int(engagement_score),
            "conversion_readiness": int(conversion_score),
        },
        "problems": problems,
        "recommended_next_content": [
            {"type": "reel", "idea": _lang_copy(lang, f"What is inside 1 package of {promote_product}?", f"1 qopda {promote_product}dan nimalar bor?", f"Что входит в 1 упаковку {promote_product}?")},
            {"type": "story_poll", "idea": _lang_copy(lang, "Poll: Which model do you like more?", "So'rovnoma: Qaysi model ko'proq yoqdi?", "Опрос: Какая модель нравится больше?")},
            {"type": "post", "idea": _lang_copy(lang, "Factory/product quality proof post", "Factory/sifat isboti posti", "Пост с подтверждением качества фабрики/товара")},
            {"type": "reel", "idea": _lang_copy(lang, "Cargo delivery explanation reel", "Cargo yetkazib berish tushuntirish reel", "Reel с объяснением карго-доставки")},
            {"type": "story_cta", "idea": _lang_copy(lang, "Need catalog? Write in DM.", "Katalog kerakmi? Direktga yozing.", "Нужен каталог? Напишите в DM.")},
        ],
        "product_to_promote_this_week": promote_product,
        "first_3_seconds_hooks": [
            _lang_copy(lang, "Start with a close-up result shot, then show packaging in second 2.", "1-soniyada mahsulot close-up natijasi, 2-soniyada qadoqni ko'rsating.", "В 1-й секунде покажите крупный результат, во 2-й упаковку."),
            _lang_copy(lang, "Use subtitle immediately: \"How much profit from 1 package?\"", "Darhol subtitle qo'ying: \"1 qopdan qancha foyda?\"", "Сразу дайте субтитр: «Сколько прибыли с 1 упаковки?»"),
            _lang_copy(lang, "End with a clear CTA to DM for catalog.", "Oxirida aniq CTA: katalog uchun Direktga yozing.", "Закончите четким CTA: напишите в DM за каталогом."),
        ],
        "story_ideas": [
            _lang_copy(lang, "Story poll on model preference", "Model tanlovi bo'yicha story poll", "Опрос в сторис по выбору модели"),
            _lang_copy(lang, "Story Q&A: price + delivery", "Story Q&A: narx + yetkazib berish", "Сторис Q&A: цена + доставка"),
            _lang_copy(lang, "Story: customer review screenshot + CTA", "Story: mijoz fikri screenshot + CTA", "Сторис: отзыв клиента + CTA"),
        ],
        "common_customer_questions": common_questions,
        "content_gaps": [
            _lang_copy(lang, "Need stronger reel hooks in first 3 seconds.", "Birinchi 3 soniyada kuchliroq reel hook kerak.", "Нужны более сильные hooks в первые 3 секунды."),
            _lang_copy(lang, "Need more story formats that force replies (polls/Q&A).", "Reply yig'adigan story formatlar (poll/Q&A) ko'paytirilsin.", "Нужно больше форматов сторис, которые собирают ответы (опросы/Q&A)."),
            _lang_copy(lang, "Need clearer wholesale explanation content.", "Ulgurji qoidalarni aniq tushuntiradigan kontent kerak.", "Нужен более понятный контент про правила опта."),
        ],
        "weekly_content_plan": [
            _lang_copy(lang, "Monday: Reel with close-up + profit hook + DM CTA.", "Dushanba: close-up reel + foyda hook + DM CTA.", "Понедельник: Reel с close-up + hook про прибыль + CTA в DM."),
            _lang_copy(lang, "Tuesday: Story poll and quick answer sticker.", "Seshanba: Story poll va tezkor javob stikeri.", "Вторник: Опрос в сторис и стикер быстрых ответов."),
            _lang_copy(lang, "Wednesday: Post with quality/material proof.", "Chorshanba: sifat/material isboti posti.", "Среда: Пост с доказательством качества/материала."),
            _lang_copy(lang, "Thursday: Reel on delivery/cargo process.", "Payshanba: yetkazib berish/cargo jarayoni reel.", "Четверг: Reel про процесс доставки/карго."),
            _lang_copy(lang, "Friday: FAQ carousel for top customer questions.", "Juma: eng ko'p savollar bo'yicha FAQ karusel.", "Пятница: FAQ-карусель по частым вопросам."),
        ],
        "monthly_content_plan": [
            _lang_copy(lang, "Week 1: Product trust and quality proof.", "1-hafta: mahsulot ishonchi va sifat isboti.", "1 неделя: доверие к товару и доказательство качества."),
            _lang_copy(lang, "Week 2: Pricing clarity + wholesale rules.", "2-hafta: narx aniqligi + ulgurji qoidalar.", "2 неделя: ясность по ценам + правила опта."),
            _lang_copy(lang, "Week 3: Delivery speed and geography proof.", "3-hafta: yetkazish tezligi va geografiya isboti.", "3 неделя: скорость и география доставки."),
            _lang_copy(lang, "Week 4: Conversion push with limited offer CTA.", "4-hafta: cheklangan taklif CTA bilan konversiya push.", "4 неделя: push на конверсию с CTA ограниченного оффера."),
        ],
        "account_improvement_tasks": [
            _lang_copy(lang, "Prepare 10 reusable CTA endings for captions.", "Captionlar uchun 10 ta tayyor CTA oxiri yozing.", "Подготовьте 10 готовых CTA-окончаний для caption."),
            _lang_copy(lang, "Create 5 hook templates for first 3 seconds of reels.", "Reelsning birinchi 3 soniyasi uchun 5 ta hook shablon yarating.", "Создайте 5 hook-шаблонов для первых 3 секунд reels."),
            _lang_copy(lang, "Publish at least 3 story polls every week.", "Har hafta kamida 3 ta story poll chiqaring.", "Публикуйте минимум 3 опроса в сторис каждую неделю."),
            _lang_copy(lang, "Make one dedicated post explaining wholesale rules.", "Ulgurji qoidalarni tushuntiradigan alohida post chiqaring.", "Сделайте отдельный пост с объяснением правил опта."),
        ],
        "analysis_scope": _lang_copy(
            lang,
            "Analysis is based on CRM Instagram messages and configured business fields. Bio/logo/highlights need direct in-app review.",
            "Tahlil CRM Instagram xabarlari va biznes sozlamalariga asoslangan. Bio/logo/highlights uchun Instagram ichida alohida audit kerak.",
            "Анализ основан на Instagram-сообщениях в CRM и настройках бизнеса. Bio/logo/highlights нужно проверять отдельно в Instagram.",
        ),
        "metrics": {
            "total_instagram_messages": len(rows),
            "inbound_messages": len(inbound_rows),
            "outbound_messages": len(outbound_rows),
            "dm_inbound_messages": len(dm_inbound),
            "comment_inbound_messages": len(comment_inbound),
            "story_replies": story_reply_count,
            "posts_with_comments": post_count,
            "reel_share_by_commented_posts": round(reel_share, 3),
            "cta_rate": round(cta_rate, 3),
            "active_days": active_day_count,
        },
    }


@app.get("/api/v2/instagram-growth-analyzer")
async def get_instagram_growth_analyzer_v2(
    business_id: str,
    days: int = 30,
    no_cache: bool = False,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    clean_business_id = normalize_id(business_id)
    if not clean_business_id:
        return JSONResponse({"error": "Missing business_id"}, status_code=400)
    if not can_access_business(access, clean_business_id):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    business = get_business_by_id(clean_business_id)
    if not business:
        return JSONResponse({"error": "Business not found"}, status_code=404)

    safe_days = max(7, min(int(days or 30), 120))
    cache_key = f"{clean_business_id}:{safe_days}:{normalize_email(access.get('email', ''))}:{int(bool(access.get('is_admin')))}"
    now_ts = time.time()
    cached = INSTAGRAM_GROWTH_CACHE.get(cache_key)
    if (not no_cache) and cached and (now_ts - cached[0]) < INSTAGRAM_GROWTH_CACHE_TTL_SECONDS:
        return {"status": "ok", "data": cached[1]}

    try:
        snapshot = fetch_instagram_live_snapshot(business=business, days=safe_days)
        payload = build_instagram_growth_analysis_from_live(
            snapshot=snapshot,
            business=business,
            days=safe_days,
        )
        save_instagram_growth_report_history(
            business_id=clean_business_id,
            report=payload,
            updated_by=access.get("email", ""),
        )
        if len(INSTAGRAM_GROWTH_CACHE) > 300:
            for stale_key in sorted(INSTAGRAM_GROWTH_CACHE, key=lambda item: INSTAGRAM_GROWTH_CACHE[item][0])[:120]:
                INSTAGRAM_GROWTH_CACHE.pop(stale_key, None)
        INSTAGRAM_GROWTH_CACHE[cache_key] = (time.time(), payload)
        return {"status": "ok", "data": payload}
    except Exception as exc:
        message = normalize_id(str(exc)) or "Could not fetch live Instagram data"
        history = get_workspace_state(clean_business_id).get("instagram_growth_latest") or {}
        if isinstance(history, dict) and isinstance(history.get("report"), dict):
            fallback_report = dict(history.get("report") or {})
            fallback_report["data_source"] = "cached_previous_live_report"
            fallback_note = _lang_copy(
                normalize_id((business or {}).get("language")).lower() or "uz",
                "Live fetch failed, showing latest cached live report.",
                "Live fetch muvaffaqiyatsiz, oxirgi saqlangan live hisobot ko'rsatildi.",
                "Live-запрос не удался, показан последний сохраненный live-отчет.",
            )
            fallback_report["analysis_scope"] = f"{fallback_report.get('analysis_scope', '')} {fallback_note}".strip()
            return {
                "status": "ok",
                "data": fallback_report,
                "warning": message,
            }
        log("Error generating Instagram growth analysis", message)
        return JSONResponse(
            {
                "status": "error",
                "message": message,
                "hint": "Reconnect Instagram account and ensure instagram_basic + instagram_manage_insights permissions.",
            },
            status_code=503,
        )


@app.post("/api/v2/instagram-posts/import")
async def import_instagram_posts_v2(
    request: Request,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    payload = await request.json()
    business_id = normalize_id(payload.get("business_id"))
    max_items = max(10, min(int(payload.get("max_items") or 300), 1000))

    if not business_id:
        return JSONResponse({"status": "error", "message": "Missing business_id"}, status_code=400)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    business = get_business_by_id(business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    try:
        posts = await run_blocking_io(
            fetch_instagram_posts_for_import,
            business,
            max_items=max_items,
            timeout=170,
            label="instagram posts import",
        )
        store_info = store_instagram_posts_cache(
            business_id=business_id,
            posts=posts,
            updated_by=access.get("email", ""),
        )
        notes_state = get_instagram_post_notes_state(business_id)
        by_post = notes_state.get("by_post_id") if isinstance(notes_state.get("by_post_id"), dict) else {}
        enriched = []
        for item in posts:
            post_id = normalize_id(item.get("post_id"))
            extra = normalize_id((by_post.get(post_id) or {}).get("extra_info"))
            enriched.append({**item, "extra_info": extra})
        return {
            "status": "ok",
            "count": len(enriched),
            "store": store_info,
            "data": enriched,
        }
    except TimeoutError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=504)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.get("/api/v2/instagram-posts")
async def list_instagram_posts_v2(
    business_id: str,
    refresh: int = 0,
    limit: int = 300,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business_id = normalize_id(business_id)
    if not business_id:
        return JSONResponse({"status": "error", "message": "Missing business_id"}, status_code=400)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    safe_limit = max(1, min(int(limit or 300), 1000))
    if int(refresh or 0) == 1:
        business = get_business_by_id(business_id)
        if not business:
            return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
        try:
            posts = await run_blocking_io(
                fetch_instagram_posts_for_import,
                business,
                max_items=safe_limit,
                timeout=170,
                label="instagram posts refresh",
            )
            store_instagram_posts_cache(
                business_id=business_id,
                posts=posts,
                updated_by=access.get("email", ""),
            )
        except TimeoutError as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=504)
        except Exception as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)

    posts = load_instagram_posts_from_cache(business_id, limit=safe_limit)
    notes_state = get_instagram_post_notes_state(business_id)
    by_post = notes_state.get("by_post_id") if isinstance(notes_state.get("by_post_id"), dict) else {}
    merged = []
    for item in posts:
        post_id = normalize_id(item.get("post_id"))
        note = by_post.get(post_id) if isinstance(by_post.get(post_id), dict) else {}
        merged.append({
            **item,
            "extra_info": normalize_id(note.get("extra_info")),
            "extra_updated_at": normalize_id(note.get("updated_at")),
        })
    return {"status": "ok", "count": len(merged), "data": merged}


@app.get("/api/v2/instagram-posts/{post_id}")
async def get_instagram_post_details_v2(
    post_id: str,
    business_id: str,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    business_id = normalize_id(business_id)
    post_id = normalize_id(post_id)
    if not business_id or not post_id:
        return JSONResponse({"status": "error", "message": "Missing business_id or post_id"}, status_code=400)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    posts = load_instagram_posts_from_cache(business_id, limit=1000)
    row = next((item for item in posts if normalize_id(item.get("post_id")) == post_id), None)
    if not row:
        return JSONResponse({"status": "error", "message": "Post not found in cache. Run import first."}, status_code=404)

    note = resolve_instagram_post_note_for_context(
        business_id=business_id,
        post_id=post_id,
        permalink=normalize_id(row.get("permalink")),
    )
    return {"status": "ok", "data": {**row, "extra_info": normalize_id(note.get("extra_info")), "note_meta": note}}


@app.post("/api/v2/instagram-posts/extra-info")
async def set_instagram_post_extra_info_v2(
    body: InstagramPostExtraUpdate,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    business_id = normalize_id(body.business_id)
    post_id = normalize_id(body.post_id)
    if not business_id or not post_id:
        return JSONResponse({"status": "error", "message": "business_id and post_id are required"}, status_code=400)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    posts = load_instagram_posts_from_cache(business_id, limit=1000)
    row = next((item for item in posts if normalize_id(item.get("post_id")) == post_id), None)
    if not row:
        row = {"post_id": post_id, "permalink": "", "caption": "", "media_type": ""}

    note = save_instagram_post_extra_info(
        business_id=business_id,
        post=row,
        extra_info=body.extra_info,
        updated_by=access.get("email", ""),
    )
    return {"status": "ok", "data": note}


@app.get("/api/v2/stats")
async def get_stats_v2(
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    """Get dashboard statistics"""
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        if access.get("is_admin"):
            scoped_ids = []
            cache_key = "admin"
        else:
            scoped_ids = access.get("business_ids") or []
            cache_key = f"user:{','.join(sorted(scoped_ids))}"

        now = time.time()
        cached = STATS_CACHE.get(cache_key)
        if cached and (now - float(cached.get("ts", 0))) < STATS_CACHE_TTL_SECONDS:
            return {'status': 'ok', 'data': cached.get("data", {})}

        if access.get("is_admin"):
            businesses = get_all_businesses()
        else:
            businesses = []
            if scoped_ids:
                businesses = (
                    supabase.table("businesses")
                    .select("id,bot_enabled")
                    .in_("id", scoped_ids)
                    .order("created_at", desc=True)
                    .execute()
                    .data
                    or []
                )

        payload = {
            'total_messages': get_message_count(business_ids=scoped_ids) if not access.get("is_admin") else get_message_count(),
            'total_accounts': len(businesses),
            'active_accounts': sum(1 for b in businesses if b.get("bot_enabled")),
            'instagram_messages': get_message_count('instagram', scoped_ids) if not access.get("is_admin") else get_message_count('instagram'),
            'telegram_messages': get_message_count('telegram', scoped_ids) if not access.get("is_admin") else get_message_count('telegram'),
            'whatsapp_messages': get_message_count('whatsapp', scoped_ids) if not access.get("is_admin") else get_message_count('whatsapp'),
            'active_conversations': 0,
            'needing_human': 0,
        }
        STATS_CACHE[cache_key] = {"ts": now, "data": payload}
        return {'status': 'ok', 'data': payload}

    except Exception as e:
        log("Error getting stats", str(e))
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.get("/api/v2/workspace-state")
async def get_workspace_state_v2(
    business_id: str = "",
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    business_id = normalize_id(business_id)
    if not business_id:
        return JSONResponse({"error": "Missing business_id"}, status_code=400)
    if not can_access_business(access, business_id):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    data = get_workspace_state(business_id)
    task_items = scope_operator_tasks_for_access(merged_operator_task_items(data), access)
    data["operator_admin_notes"] = {"items": task_items}
    data["operator_tasks"] = {"items": task_items}
    return {"status": "ok", "data": data}


@app.post("/api/v2/workspace-state")
async def update_workspace_state_v2(
    request: Request,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
        business_id = normalize_id(payload.get("business_id"))
        if not business_id:
            return JSONResponse({"error": "Missing business_id"}, status_code=400)
        if not can_access_business(access, business_id):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        allowed_keys = {
            "lead_stages",
            "lead_prices",
            "manual_clients",
            "client_owners",
            "operator_deals",
            "operator_admin_notes",
            "operator_tasks",
        }
        state = payload.get("state") or {}
        if not isinstance(state, dict):
            return JSONResponse({"error": "state must be an object"}, status_code=400)

        updated_keys = []
        for key, value in state.items():
            if key not in allowed_keys:
                continue
            upsert_workspace_state(
                business_id=business_id,
                state_key=key,
                state_value=value,
                updated_by=access.get("email", ""),
            )
            updated_keys.append(key)

        return {"status": "ok", "updated_keys": updated_keys}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/settings/{business_id}")
async def api_get_combined_settings(
    business_id: str,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    business = get_business_by_id(business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    workspace_state = get_workspace_state(business_id)
    task_items = scope_operator_tasks_for_access(merged_operator_task_items(workspace_state), access)
    workspace_state["operator_admin_notes"] = {"items": task_items}
    workspace_state["operator_tasks"] = {"items": task_items}
    return {
        "status": "ok",
        "data": {
            "business": sanitize_business_row(business),
            "ai_prompt_settings": get_ai_prompt_settings(business_id),
            "workspace_state": workspace_state,
        },
    }


@app.post("/api/settings/{business_id}")
async def api_update_combined_settings(
    business_id: str,
    request: Request,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    business = get_business_by_id(business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    payload = await request.json()
    updated = {}

    business_settings = clean_business_settings(payload.get("business_settings") or {})
    if business_settings:
        update_business(business_id, business_settings)
        updated["business_settings"] = list(business_settings.keys())

    ai_prompt_settings = payload.get("ai_prompt_settings") or {}
    if isinstance(ai_prompt_settings, dict) and ai_prompt_settings:
        upsert_ai_prompt_settings(business_id, ai_prompt_settings)
        updated["ai_prompt_settings"] = [
            key for key in ai_prompt_settings.keys() if key in AI_PROMPT_SETTING_FIELDS
        ]

    workspace_state = payload.get("workspace_state") or {}
    allowed_workspace_keys = {
        "lead_stages",
        "lead_prices",
        "manual_clients",
        "client_owners",
        "operator_deals",
        "operator_admin_notes",
        "operator_tasks",
    }
    if isinstance(workspace_state, dict) and workspace_state:
        updated_workspace = []
        for key, value in workspace_state.items():
            if key not in allowed_workspace_keys:
                continue
            upsert_workspace_state(
                business_id=business_id,
                state_key=key,
                state_value=value,
                updated_by=access.get("email", ""),
            )
            updated_workspace.append(key)
        updated["workspace_state"] = updated_workspace

    return {"status": "ok", "updated": updated}


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
        remember_webhook_event({
            "object": object_type,
            "entry_count": len(data.get("entry", []) or []),
            "summary": [
                {
                    "id": normalize_id(entry.get("id")),
                    "messaging": len(entry.get("messaging", []) or []),
                    "changes": [
                        {
                            "field": change.get("field"),
                            "message_count": len(((change.get("value") or {}).get("messages") or [])),
                            "status_count": len(((change.get("value") or {}).get("statuses") or [])),
                            "phone_number_id": normalize_id(((change.get("value") or {}).get("metadata") or {}).get("phone_number_id")),
                        }
                        for change in (entry.get("changes", []) or [])
                    ],
                }
                for entry in (data.get("entry", []) or [])
            ],
        })

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
        remember_webhook_event({"object": "error", "error": str(e)})
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/debug/webhook-last")
async def debug_webhook_last(x_dashboard_secret: str = Header(default="")):
    if DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return {
        "status": "ok",
        "count": len(LAST_WEBHOOK_EVENTS),
        "events": LAST_WEBHOOK_EVENTS,
        "webhook_url": f"{PUBLIC_BASE_URL.rstrip('/')}/webhook",
        "verify_token_configured": bool(VERIFY_TOKEN),
        "graph_version": GRAPH_VERSION,
    }


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


@app.get("/api/telegram-bot-media/{file_id}")
async def get_telegram_bot_media(
        file_id: str,
        token: str = "",
        x_dashboard_secret: str = Header(default=""),
):
    if require_dashboard_media_secret(token, x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    if not TELEGRAM_BOT_TOKEN:
        return JSONResponse({"status": "error", "message": "Missing TELEGRAM_BOT_TOKEN"}, status_code=400)

    try:
        meta_res = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=30,
        )
        if not meta_res.ok:
            return JSONResponse({"status": "error", "message": meta_res.text}, status_code=meta_res.status_code)

        file_path = (meta_res.json().get("result") or {}).get("file_path")
        if not file_path:
            return JSONResponse({"status": "error", "message": "file_path not found"}, status_code=404)

        file_res = requests.get(
            f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}",
            timeout=60,
        )
        if not file_res.ok:
            return JSONResponse({"status": "error", "message": file_res.text}, status_code=file_res.status_code)

        return Response(
            content=file_res.content,
            media_type=file_res.headers.get("Content-Type", "application/octet-stream"),
            headers={
                "Cache-Control": "private, max-age=3600",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(file_res.content)),
            },
        )
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


# ============================================================================
# OAUTH ROUTES
# ============================================================================
@app.get("/connect")
async def connect():
    return RedirectResponse("/connect-facebook")


@app.get("/connect-instagram")
async def connect_instagram():
    # Keep legacy route for older frontend buttons, but route through Facebook OAuth.
    # Meta app-review/business onboarding needs Facebook Page selection (pages_show_list).
    return RedirectResponse("/connect-facebook")


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
async def connect_facebook(owner_email: str = ""):
    state = encode_oauth_state(owner_email)
    params = {
        "client_id": META_APP_ID,
        "redirect_uri": FACEBOOK_REDIRECT_URI,
        "scope": "pages_show_list,pages_read_engagement,pages_manage_metadata,pages_messaging,instagram_basic,instagram_manage_messages,instagram_manage_comments,email",
        "response_type": "code",
        "state": state,
    }
    auth_url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urlencode(params)
    return RedirectResponse(auth_url)


@app.get("/auth/whatsapp/embedded/start")
async def whatsapp_embedded_start(owner_email: str = "", redirect_uri: str = ""):
    """
    Start WhatsApp Embedded Signup (Facebook Login for Business flow).
    """
    target_redirect = normalize_id(redirect_uri) or WHATSAPP_EMBEDDED_REDIRECT_URI
    state = build_whatsapp_embedded_state(owner_email)
    params = {
        "client_id": META_APP_ID,
        "redirect_uri": target_redirect,
        "response_type": "code",
        "scope": ",".join([
            "business_management",
            "whatsapp_business_management",
            "whatsapp_business_messaging",
        ]),
        "state": state,
    }
    auth_url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urlencode(params)
    return {"status": "ok", "auth_url": auth_url, "state": state, "redirect_uri": target_redirect}


@app.get("/auth/whatsapp/embedded/callback")
async def whatsapp_embedded_callback(
    request: Request,
    redirect_uri: str = "",
):
    """
    Callback endpoint for embedded signup code exchange.
    """
    code = normalize_id(request.query_params.get("code"))
    state = normalize_id(request.query_params.get("state"))
    error = normalize_id(request.query_params.get("error") or request.query_params.get("error_description"))
    if error:
        return JSONResponse({"status": "error", "message": error}, status_code=400)
    if not code:
        return JSONResponse({"status": "error", "message": "Missing code"}, status_code=400)

    target_redirect = normalize_id(redirect_uri) or WHATSAPP_EMBEDDED_REDIRECT_URI
    try:
        token_res = requests.get(
            f"{GRAPH_FACEBOOK}/oauth/access_token",
            params={
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "redirect_uri": target_redirect,
                "code": code,
            },
            timeout=30,
        )
        token_body = safe_json(token_res)
        if not token_res.ok:
            return JSONResponse(
                {"status": "error", "message": "Code exchange failed", "details": token_body},
                status_code=400,
            )

        access_token = normalize_id(token_body.get("access_token"))
        waba_id = normalize_id(request.query_params.get("waba_id") or os.getenv("WHATSAPP_WABA_ID", ""))
        phone_number_id = normalize_id(request.query_params.get("phone_number_id") or os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""))
        if waba_id and not phone_number_id:
            phone_numbers = get_whatsapp_waba_phone_numbers(waba_id, access_token)
            if phone_numbers:
                phone_number_id = normalize_id(phone_numbers[0].get("id"))

        subscribe_ok, subscribe_body = subscribe_whatsapp_waba_to_webhooks(waba_id, access_token) if waba_id else (False, {"error": "Missing waba_id"})
        data = {
            "access_token": access_token,
            "token_type": token_body.get("token_type", ""),
            "expires_in": token_body.get("expires_in", 0),
            "state": state,
            "owner_email": normalize_email(parse_whatsapp_embedded_state(state).get("owner_email")),
            "waba_id": waba_id,
            "phone_number_id": phone_number_id,
            "webhook_subscribe_ok": subscribe_ok,
            "webhook_subscribe_result": subscribe_body,
            "received_at": int(time.time()),
        }
        if state:
            WHATSAPP_EMBEDDED_SESSIONS[state] = data
        if phone_number_id and access_token:
            persist_whatsapp_embedded_business(data["owner_email"], waba_id, phone_number_id, access_token)

        return {
            "status": "ok",
            "state": state,
            "owner_email": data["owner_email"],
            "waba_id": data["waba_id"],
            "phone_number_id": data["phone_number_id"],
            "webhook_subscribe_ok": subscribe_ok,
            "webhook_subscribe_result": subscribe_body,
            "has_access_token": bool(access_token),
            "expires_in": data["expires_in"],
        }
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.get("/auth/whatsapp/embedded/status")
async def whatsapp_embedded_status(state: str = ""):
    session = WHATSAPP_EMBEDDED_SESSIONS.get(normalize_id(state), {}) if state else {}
    if not session:
        return {"status": "empty", "state": normalize_id(state)}
    return {
        "status": "ok",
        "state": normalize_id(state),
        "owner_email": session.get("owner_email", ""),
        "waba_id": session.get("waba_id", ""),
        "phone_number_id": session.get("phone_number_id", ""),
        "has_access_token": bool(session.get("access_token")),
        "received_at": session.get("received_at", 0),
    }


@app.post("/auth/whatsapp/embedded/subscribe")
async def whatsapp_embedded_subscribe(
    waba_id: str = "",
    access_token: str = "",
    state: str = "",
):
    session = WHATSAPP_EMBEDDED_SESSIONS.get(normalize_id(state), {}) if state else {}
    resolved_waba_id = normalize_id(waba_id) or normalize_id(session.get("waba_id")) or normalize_id(os.getenv("WHATSAPP_WABA_ID", ""))
    resolved_token = normalize_id(access_token) or normalize_id(session.get("access_token")) or normalize_id(os.getenv("WHATSAPP_ACCESS_TOKEN", ""))
    ok, body = subscribe_whatsapp_waba_to_webhooks(resolved_waba_id, resolved_token)
    return JSONResponse(
        {"status": "ok" if ok else "error", "waba_id": resolved_waba_id, "result": body},
        status_code=200 if ok else 400,
    )


@app.get("/auth/whatsapp/embedded/phone-numbers")
async def whatsapp_embedded_phone_numbers(
    waba_id: str = "",
    access_token: str = "",
    state: str = "",
):
    session = WHATSAPP_EMBEDDED_SESSIONS.get(normalize_id(state), {}) if state else {}
    resolved_waba_id = normalize_id(waba_id) or normalize_id(session.get("waba_id")) or normalize_id(os.getenv("WHATSAPP_WABA_ID", ""))
    resolved_token = normalize_id(access_token) or normalize_id(session.get("access_token")) or normalize_id(os.getenv("WHATSAPP_ACCESS_TOKEN", ""))
    rows = get_whatsapp_waba_phone_numbers(resolved_waba_id, resolved_token)
    return {"status": "ok", "waba_id": resolved_waba_id, "count": len(rows), "data": rows}


@app.post("/api/whatsapp/embedded/send-message")
async def whatsapp_embedded_send_message(payload: EmbeddedWhatsAppSendMessage):
    to = normalize_id(payload.to).replace("+", "").replace(" ", "")
    text = normalize_id(payload.text)
    phone_number_id = normalize_id(payload.phone_number_id) or normalize_id(os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""))
    access_token = normalize_id(payload.access_token) or normalize_id(os.getenv("WHATSAPP_ACCESS_TOKEN", ""))

    if not to or not text:
        return JSONResponse({"status": "error", "message": "Missing to or text"}, status_code=400)
    if not phone_number_id:
        return JSONResponse({"status": "error", "message": "Missing phone_number_id"}, status_code=400)
    if not access_token:
        return JSONResponse({"status": "error", "message": "Missing access_token"}, status_code=400)

    try:
        res = requests.post(
            f"{GRAPH_FACEBOOK}/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"preview_url": True, "body": text[:4096]},
            },
            timeout=30,
        )
        body = safe_json(res)
        return JSONResponse(
            {"status": "ok" if res.ok else "error", "http_status": res.status_code, "result": body},
            status_code=200 if res.ok else 400,
        )
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.get("/auth/facebook/callback")
async def facebook_callback(request: Request):
    code = request.query_params.get("code", "")
    if not code:
        error = request.query_params.get("error_description") or request.query_params.get("error") or "Missing code"
        return PlainTextResponse(f"Facebook OAuth error: {error}", status_code=400)

    state_data = decode_oauth_state(request.query_params.get("state", ""))
    state_owner_email = normalize_email(state_data.get("owner_email"))

    try:
        short_lived = exchange_facebook_code_for_user_token(code)
        if not short_lived:
            raise ValueError("Could not exchange Facebook code for token")

        user_token = exchange_facebook_long_lived_token(short_lived)
        profile = get_facebook_user_profile(user_token)
        profile_email = normalize_email(profile.get("email"))
        owner_email = state_owner_email or profile_email or normalize_email(ADMIN_EMAIL)

        pages = get_facebook_pages_with_instagram(user_token)
        created = []
        for page in pages:
            page_id = normalize_id(page.get("id"))
            page_name = page.get("name") or ""
            page_access_token = normalize_id(page.get("access_token"))
            ig = page.get("instagram_business_account") or {}
            ig_id = normalize_id(ig.get("id"))
            ig_username = ig.get("username") or f"instagram_{ig_id}" if ig_id else ""

            if not ig_id:
                continue

            saved = upsert_business(
                instagram_business_id=ig_id,
                username=ig_username,
                access_token=user_token,
                oauth_provider="facebook_page",
                facebook_page_id=page_id,
                facebook_page_name=page_name,
                page_access_token=page_access_token,
            )

            saved_row = (saved or [{}])[0] if isinstance(saved, list) else (saved or {})
            business_id = normalize_id(saved_row.get("id"))
            if owner_email and business_id:
                assign_business_owner(owner_email, business_id, role="owner")

            subscribe_page_to_webhooks(page_id, page_access_token)
            created.append({"business_id": business_id, "instagram_id": ig_id, "page_id": page_id})

        if not created:
            return RedirectResponse(f"{DASHBOARD_URL}?connected=facebook_no_instagram")

        return RedirectResponse(f"{DASHBOARD_URL}?connected=facebook_success&count={len(created)}")

    except Exception as e:
        log("Facebook OAuth error", str(e))
        return PlainTextResponse(f"Facebook OAuth error: {str(e)}", status_code=500)


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
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    clean_business_id = normalize_id(payload.business_id)
    if clean_business_id and not can_access_business(access, clean_business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    if not str(payload.mime_type or "").startswith("image/"):
        return JSONResponse({"status": "error", "message": "Only image files are supported right now"}, status_code=400)

    try:
        file_bytes = decode_upload_data(payload.file_data)
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    business = get_business_by_id(clean_business_id) if clean_business_id else get_active_business()
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
    if not can_access_business(access, normalize_id(business.get("id"))):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

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
            business=business,
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
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    clean_business_id = normalize_id(payload.business_id)
    if clean_business_id and not can_access_business(access, clean_business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    if not str(payload.mime_type or "").startswith("audio/"):
        return JSONResponse({"status": "error", "message": "Only audio files are supported for voice notes"}, status_code=400)

    try:
        file_bytes = decode_upload_data(payload.file_data)
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    business = get_business_by_id(clean_business_id) if clean_business_id else get_active_business()
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)
    if not can_access_business(access, normalize_id(business.get("id"))):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

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
            business=business,
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
async def api_get_businesses(
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    query = supabase.table("businesses").select("*").order("created_at", desc=True)
    if not access.get("is_admin"):
        allowed = access.get("business_ids") or []
        if not allowed:
            return {"status": "ok", "count": 0, "data": []}
        query = query.in_("id", allowed)
    try:
        result = await run_blocking_io(
            query.execute,
            timeout=12,
            label="businesses query",
        )
    except TimeoutError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=504)
    rows = [sanitize_business_row(row) for row in (result.data or [])]
    return {"status": "ok", "count": len(rows), "data": rows}


@app.get("/api/businesses/{business_id}/channels")
async def api_get_business_channels(
    business_id: str,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    rows = (
        supabase.table("business_channels")
        .select("*")
        .eq("business_id", normalize_id(business_id))
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    clean = [sanitize_channel_row(row) for row in rows]
    return {"status": "ok", "count": len(clean), "data": clean}


@app.post("/api/businesses/{business_id}/channels")
async def api_upsert_business_channel(
    business_id: str,
    payload: BusinessChannelPayload,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    row = {
        "business_id": normalize_id(business_id),
        "platform": normalize_id(payload.platform).lower(),
        "account_label": normalize_id(payload.account_label),
        "account_external_id": normalize_id(payload.account_external_id),
        "is_active": bool(payload.is_active),
        "config": payload.config or {},
    }
    result = (
        supabase.table("business_channels")
        .upsert(row, on_conflict="business_id,platform,account_external_id")
        .execute()
    )
    data = [sanitize_channel_row(x) for x in (result.data or [])]
    return {"status": "ok", "data": data}


@app.delete("/api/business-channels/{channel_id}")
async def api_delete_business_channel(
    channel_id: str,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not access.get("is_admin"):
        row = (
            supabase.table("business_channels")
            .select("business_id")
            .eq("id", normalize_id(channel_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        business_id = normalize_id(row[0].get("business_id")) if row else ""
        if not can_access_business(access, business_id):
            return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)
    supabase.table("business_channels").delete().eq("id", normalize_id(channel_id)).execute()
    return {"status": "ok"}


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
async def api_update_business_settings(
    body: BusinessSettingsUpdate,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, body.business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    business = get_business_by_id(body.business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    settings = clean_business_settings(body.settings)
    if not settings:
        return JSONResponse({"status": "error", "message": "No valid settings to update"}, status_code=400)

    update_business(body.business_id, settings)
    return {"status": "ok", "message": "Settings updated"}


@app.get("/api/ai-prompt-settings/{business_id}")
async def api_get_ai_prompt_settings(
    business_id: str,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

    business = get_business_by_id(business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    return {"status": "ok", "data": get_ai_prompt_settings(business_id)}


@app.post("/api/v2/ai-prompt/generate")
async def api_generate_ai_prompt(
    body: AIPromptGenerateRequest,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, body.business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

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
async def api_update_ai_prompt_settings(
    body: AIPromptSettingsUpdate,
    authorization: str = Header(default=""),
    x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, body.business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)

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
