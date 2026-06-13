import os
import re
import time
import secrets
import base64
import io
import json
import hashlib
import hmac
import sys
import tempfile
import shutil
import subprocess
import requests
import mimetypes
from urllib.parse import urlencode, urlparse, parse_qs, unquote
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path
try:
    import bcrypt
except Exception:
    bcrypt = None

from dotenv import load_dotenv
from pydantic import BaseModel
from fastapi import APIRouter, FastAPI, Request, Header, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from supabase import create_client

from agent_orchestrator import run_agent_cycle
from ai_audit_log import build_ai_action, save_ai_action
from coaching_report import build_daily_coaching_report, coaching_report_text

try:
    import telegram_bot as telegram_bot_module
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
except Exception as exc:
    telegram_bot_module = None
    telegram_router = APIRouter()
    TELEGRAM_IMPORT_ERROR = exc
    print(f"Telegram module disabled during startup: {exc}")

    async def start_telegram_user_client():
        return None

    async def stop_telegram_user_client():
        return None

    async def send_telegram_user_message(*args, **kwargs):
        return False, {"error": f"Telegram module unavailable: {TELEGRAM_IMPORT_ERROR}"}

    async def send_telegram_user_file(*args, **kwargs):
        return False, {"error": f"Telegram module unavailable: {TELEGRAM_IMPORT_ERROR}"}

    async def send_telegram_user_voice_file(*args, **kwargs):
        return False, {"error": f"Telegram module unavailable: {TELEGRAM_IMPORT_ERROR}"}

    def send_telegram_bot_message(*args, **kwargs):
        return None

    def save_telegram_message(*args, **kwargs):
        return None

    def get_active_business():
        return None

try:
    import catalog_matcher as catalog_matcher_module
except Exception as exc:
    catalog_matcher_module = None
    CATALOG_MATCHER_IMPORT_ERROR = exc
    print(f"catalog_matcher import disabled: {exc}")

try:
    from video_analyzer import VideoAnalyzerError, analyze_video_content
except Exception as exc:
    VideoAnalyzerError = None
    VIDEO_ANALYZER_IMPORT_ERROR = exc
    print(f"video_analyzer import disabled: {exc}")

    def analyze_video_content(*args, **kwargs):
        raise RuntimeError(f"Video analyzer unavailable: {VIDEO_ANALYZER_IMPORT_ERROR}")


def load_local_env():
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        env_file = parent / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
            return env_file
    return None


LOADED_ENV_FILE = load_local_env()


def env_list(name: str, default: str = ""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=env_list(
        "CORS_ORIGINS",
        "https://agent-kqwah9x4f-mirshoir-s-projects.vercel.app,https://agent-rust-delta.vercel.app,https://agent-psi-liard.vercel.app,http://localhost:5173,http://localhost:5174,http://127.0.0.1:4173,http://localhost:4173,http://127.0.0.1:5173,http://127.0.0.1:5174,https://instaagent.streamlit.app,https://agent-1-xi6h.onrender.com",
    ),
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app|https?://(localhost|127\.0\.0\.1)(:\d+)?"),
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

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
CATALOG_SUPABASE_URL = (
    os.getenv("CATALOG_SUPABASE_URL")
    or os.getenv("PRODUCT_CATALOG_SUPABASE_URL")
    or os.getenv("PRODUCT_MATCHER_SUPABASE_URL")
    or os.getenv("MILANA_CATALOG_SUPABASE_URL")
    or SUPABASE_URL
)
CATALOG_SUPABASE_SERVICE_KEY = (
    os.getenv("CATALOG_SUPABASE_SERVICE_KEY")
    or os.getenv("PRODUCT_CATALOG_SUPABASE_SERVICE_KEY")
    or os.getenv("PRODUCT_MATCHER_SUPABASE_SERVICE_KEY")
    or os.getenv("MILANA_CATALOG_SUPABASE_SERVICE_KEY")
    or SUPABASE_SERVICE_KEY
)

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
LEAD_CONTACT_REQUEST_UZ = "Buyurtmani yakunlashda menejerimiz yordam beradi."
LEAD_CONTACT_REQUEST_EN = "Our manager will help finalize the order."
LEAD_CONTACT_REQUEST_RU = "Менеджер поможет завершить заказ."
LEAD_CONTACT_REQUEST_KK = "Тапсырысты аяқтауға менеджеріміз көмектеседі."
STATS_CACHE_TTL_SECONDS = int(os.getenv("STATS_CACHE_TTL_SECONDS", "20"))
STATS_CACHE: dict[str, dict] = {}
INSTAGRAM_PUBLIC_PREVIEW_CACHE_TTL_SECONDS = int(os.getenv("INSTAGRAM_PUBLIC_PREVIEW_CACHE_TTL_SECONDS", str(60 * 60 * 6)))
INSTAGRAM_PUBLIC_PREVIEW_CACHE: dict[str, tuple[float, dict]] = {}
INSTAGRAM_REEL_DOWNLOAD_ENABLED = str(os.getenv("INSTAGRAM_REEL_DOWNLOAD_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
INSTAGRAM_REEL_CACHE_DIR = Path(os.getenv("INSTAGRAM_REEL_CACHE_DIR", "/tmp/instaagent_reels"))
INSTAGRAM_REEL_MAX_MB = max(5, min(200, int(os.getenv("INSTAGRAM_REEL_MAX_MB", "80"))))
INSTAGRAM_REEL_DOWNLOAD_TIMEOUT_SECONDS = max(10, min(90, int(os.getenv("INSTAGRAM_REEL_DOWNLOAD_TIMEOUT_SECONDS", "35"))))
INSTAGRAM_REEL_DOWNLOAD_FAILURE_TTL_SECONDS = max(60, min(24 * 60 * 60, int(os.getenv("INSTAGRAM_REEL_DOWNLOAD_FAILURE_TTL_SECONDS", "1800"))))
INSTAGRAM_REEL_DOWNLOAD_ATTEMPT_CACHE: dict[str, tuple[float, dict]] = {}
INSTAGRAM_CUSTOMER_PROFILE_CACHE_TTL_SECONDS = int(os.getenv("INSTAGRAM_CUSTOMER_PROFILE_CACHE_TTL_SECONDS", str(60 * 60 * 24)))
INSTAGRAM_CUSTOMER_PROFILE_CACHE: dict[str, tuple[float, dict]] = {}
INSTAGRAM_HUMAN_AGENT_RETRY_ENABLED = str(
    os.getenv("INSTAGRAM_HUMAN_AGENT_RETRY_ENABLED", "0")
).strip().lower() in {"1", "true", "yes", "on"}
PRODUCT_MATCHER_ENABLED = str(os.getenv("PRODUCT_MATCHER_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
_product_matcher_urls = env_list("PRODUCT_MATCHER_API_URLS", "")
if not _product_matcher_urls:
    _legacy_matcher_url = os.getenv("PRODUCT_MATCHER_API_URL", "").strip()
    _product_matcher_urls = [_legacy_matcher_url] if _legacy_matcher_url else []
PRODUCT_MATCHER_API_URLS = [str(url or "").strip() for url in _product_matcher_urls if str(url or "").strip()]
PRODUCT_MATCHER_TIMEOUT_SECONDS = max(10, min(180, int(os.getenv("PRODUCT_MATCHER_TIMEOUT_SECONDS", "90"))))
PRODUCT_MATCHER_TOP_K = max(1, min(10, int(os.getenv("PRODUCT_MATCHER_TOP_K", "3"))))
PRODUCT_MATCHER_MIN_SCORE = max(0.0, min(1.0, float(os.getenv("PRODUCT_MATCHER_MIN_SCORE", "0.20"))))
PRODUCT_MATCHER_WEAK_MIN_SCORE = max(0.0, min(1.0, float(os.getenv("PRODUCT_MATCHER_WEAK_MIN_SCORE", "0.10"))))
PRODUCT_MATCHER_CONTEXT_TTL_SECONDS = max(60, min(24 * 60 * 60, int(os.getenv("PRODUCT_MATCHER_CONTEXT_TTL_SECONDS", "1800"))))
PRODUCT_MATCHER_MAX_MEDIA_MB = max(2, min(40, int(os.getenv("PRODUCT_MATCHER_MAX_MEDIA_MB", "20"))))
PRODUCT_MATCHER_RECENT_MEDIA_LOOKBACK_SECONDS = max(
    60,
    min(24 * 60 * 60, int(os.getenv("PRODUCT_MATCHER_RECENT_MEDIA_LOOKBACK_SECONDS", "1800"))),
)
OUTBOUND_DUPLICATE_WINDOW_SECONDS = max(
    5,
    min(300, int(os.getenv("OUTBOUND_DUPLICATE_WINDOW_SECONDS", "25"))),
)
PRODUCT_MATCHER_LOCAL_ENABLED = str(os.getenv("PRODUCT_MATCHER_LOCAL_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
PRODUCT_MATCHER_LOCAL_ONLY = str(os.getenv("PRODUCT_MATCHER_LOCAL_ONLY", "1")).strip().lower() in {"1", "true", "yes", "on"}
PRODUCT_MATCHER_LOCAL_CATALOG_TABLE = str(os.getenv("PRODUCT_MATCHER_LOCAL_CATALOG_TABLE", "milana_products") or "").strip() or "milana_products"
PRODUCT_MATCHER_LOCAL_CATALOG_CACHE_TTL_SECONDS = max(
    30,
    min(60 * 60, int(os.getenv("PRODUCT_MATCHER_LOCAL_CATALOG_CACHE_TTL_SECONDS", "300"))),
)
PRODUCT_MATCHER_LOCAL_FETCH_LIMIT = max(
    50,
    min(3000, int(os.getenv("PRODUCT_MATCHER_LOCAL_FETCH_LIMIT", "1200"))),
)
PRODUCT_MATCHER_LOCAL_MAX_KEYWORDS = max(
    3,
    min(40, int(os.getenv("PRODUCT_MATCHER_LOCAL_MAX_KEYWORDS", "24"))),
)
PRODUCT_MATCHER_OPENAI_VISION_MODEL = str(
    os.getenv("PRODUCT_MATCHER_OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")) or ""
).strip() or "gpt-4.1-mini"
PRODUCT_MATCHER_OPENAI_VISION_TIMEOUT_SECONDS = max(
    8,
    min(120, int(os.getenv("PRODUCT_MATCHER_OPENAI_VISION_TIMEOUT_SECONDS", "20"))),
)
PRODUCT_MATCHER_OPENAI_VISION_DETAIL = str(os.getenv("PRODUCT_MATCHER_OPENAI_VISION_DETAIL", "low") or "").strip().lower() or "low"
OPENAI_TRANSCRIBE_MODEL = str(os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe") or "").strip() or "gpt-4o-transcribe"
OPENAI_TRANSCRIBE_TIMEOUT_SECONDS = max(
    10,
    min(180, int(os.getenv("OPENAI_TRANSCRIBE_TIMEOUT_SECONDS", "90"))),
)
INSTAGRAM_MEDIA_MATCH_MEMORY: dict[str, dict] = {}
INSTAGRAM_RECENT_OUTBOUND_MEMORY: dict[str, dict] = {}
PRODUCT_MATCHER_LOCAL_CATALOG_CACHE = {"loaded_at": 0.0, "rows": []}
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

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
catalog_supabase = create_client(CATALOG_SUPABASE_URL, CATALOG_SUPABASE_SERVICE_KEY)

processed_message_ids = {}
processed_comment_ids = {}
processing_message_ids = set()
processing_comment_ids = set()
DEDUP_TTL_SECONDS = 60 * 60
WHATSAPP_CHAT_MEMORY = {}
WHATSAPP_EMBEDDED_SESSIONS = {}
LAST_WEBHOOK_EVENTS = []


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


def normalize_bool(value, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = normalize_id(value).lower()
    if text in {"1", "true", "yes", "y", "on", "enabled", "enable", "full_auto"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled", "disable", "manual", "human_only", "human"}:
        return False
    return default


def get_business_automation_mode(business: dict = None) -> str:
    return normalize_id((business or {}).get("automation_mode")).upper()


def business_memory_limit(business: dict = None, default: int = 8) -> int:
    business = business or {}
    if not normalize_bool(business.get("memory_enabled"), True):
        return 0
    raw_limit = business.get("memory_limit")
    try:
        limit = int(raw_limit if raw_limit not in (None, "") else default)
    except Exception:
        limit = default
    return max(0, min(20, limit))


def lead_state_workspace_key(platform: str, customer_id: str, channel: str = "") -> str:
    platform = normalize_id(platform).lower()
    customer_id = normalize_id(customer_id)
    channel = normalize_id(channel).lower()
    if not platform or not customer_id:
        return ""
    if channel:
        return f"lead_state:{platform}:{channel}:{customer_id}"
    return f"lead_state:{platform}:{customer_id}"


def normalize_phone_number(value: str) -> str:
    digits = re.sub(r"\D+", "", normalize_id(value))
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("8") and len(digits) == 10:
        return f"998{digits[1:]}"
    if digits.startswith("998") and len(digits) >= 12:
        return digits[:12]
    return digits


def extract_phone_candidates(text: str) -> list[str]:
    source = normalize_id(text)
    if not source:
        return []

    candidates = []
    patterns = [
        r"(?<!\d)(?:\+?\d[\d\s().-]{6,}\d)(?!\d)",
        r"(?<!\d)\d{7,15}(?!\d)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            digits = normalize_phone_number(match.group(0))
            if 7 <= len(digits) <= 15 and digits not in candidates:
                candidates.append(digits)
    return candidates


def _looks_like_customer_name(value: str) -> bool:
    text = normalize_id(value)
    if not text or len(text) > 60:
        return False
    if re.search(r"\d", text):
        return False
    if is_greeting_only(text.lower()) or is_low_signal_message(text.lower()):
        return False
    if has_business_sales_context(text):
        return False
    tokens = [token for token in re.split(r"\s+", text.strip()) if token]
    if not 1 <= len(tokens) <= 4:
        return False
    return all(re.fullmatch(r"[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʼ'`-]{2,}", token) for token in tokens)


def extract_customer_name_candidate(text: str) -> str:
    source = normalize_id(text).strip()
    if not source:
        return ""

    explicit_patterns = [
        r"(?:ismim|mening ismim|mening adim|mening ism|my name is|name is|меня зовут|менің атым|mening ismim[:\-]?)\s+([A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʼ'`-]{2,}(?:\s+[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʼ'`-]{2,}){0,3})",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            candidate = normalize_id(match.group(1)).strip(" ,.!?:;")
            if _looks_like_customer_name(candidate):
                return candidate

    if _looks_like_customer_name(source):
        return source
    return ""


def normalize_lead_state(state: dict = None) -> dict:
    state = dict(state or {})
    phone = normalize_phone_number(state.get("phone"))
    customer_name = normalize_id(state.get("customer_name"))
    phone_collected = bool(state.get("phone_collected")) or bool(phone)
    name_collected = bool(state.get("name_collected")) or bool(customer_name and not _looks_like_generated_instagram_name(customer_name))
    last_lead_update = normalize_id(state.get("last_lead_update"))
    last_message_id = normalize_id(state.get("last_message_id"))
    stage = normalize_id(state.get("stage") or "new").lower()
    if stage == "negotiation":
        stage = "hot"
    if stage == "handoff":
        stage = "handoff_required"
    if stage not in {"new", "engaged", "interested", "qualified", "hot", "handoff_required", "won", "lost"}:
        stage = "new"
    try:
        score = max(0, min(100, int(float(state.get("score") or state.get("lead_score") or 0))))
    except Exception:
        score = 0

    normalized = {
        "phone": phone,
        "customer_name": customer_name,
        "phone_collected": phone_collected,
        "name_collected": name_collected,
        "last_lead_update": last_lead_update,
        "last_message_id": last_message_id,
        "score": score,
        "lead_score": score,
        "stage": stage,
        "handoff_required": bool(state.get("handoff_required") or stage == "handoff_required"),
    }
    for key in (
        "business_id",
        "platform",
        "channel",
        "customer_id",
        "last_message_text",
        "last_message_at",
        "primary_intent",
        "language",
        "stage_label",
        "product_interest",
        "qualification_summary",
        "handoff_reason",
        "handoff_priority",
        "manager_note",
        "updated_at",
    ):
        value = normalize_id(state.get(key))
        if value:
            normalized[key] = value
    for key in ("intents", "score_reasons", "handoff_reasons"):
        value = state.get(key)
        if isinstance(value, list):
            normalized[key] = value[:20]
    for key in ("signals",):
        value = state.get(key)
        if isinstance(value, dict):
            normalized[key] = value
    if state.get("intent_confidence") not in (None, ""):
        try:
            normalized["intent_confidence"] = float(state.get("intent_confidence"))
        except Exception:
            pass
    return normalized


def lead_state_missing_fields(state: dict = None) -> list[str]:
    normalized = normalize_lead_state(state)
    missing = []
    if not normalized.get("name_collected"):
        missing.append("name")
    if not normalized.get("phone_collected"):
        missing.append("phone")
    return missing


def build_known_customer_information_block(lead_state: dict = None) -> str:
    state = normalize_lead_state(lead_state)
    missing = lead_state_missing_fields(state)
    return f"""
Known customer information:
- Name: {state.get("customer_name") or "unknown"}
- Phone: {state.get("phone") or "unknown"}
- Lead stage: {state.get("stage") or "new"}
- Lead score: {state.get("score") or 0}
- Phone collected: {"yes" if state.get("phone_collected") else "no"}
- Name collected: {"yes" if state.get("name_collected") else "no"}
- Last lead update: {state.get("last_lead_update") or "unknown"}
- Missing fields: {", ".join(missing) if missing else "none"}

Lead handling rules:
- Before asking for the customer's name or phone number, always check the known customer information and conversation history.
- If the customer has already sent a phone number in any valid format, never ask for the phone number again.
- If the customer has already sent their name, never ask for the name again.
- If only the phone number is missing, ask only for the phone number.
- If only the name is missing, ask only for the name.
- If both name and phone number are already collected, confirm briefly and move to the next sales step.
- Do not repeat the same lead-collection question more than once in the same conversation.
""".strip()


def extract_lead_state_from_text(
    text: str,
    current_state: dict = None,
    customer_name_hint: str = "",
    message_id: str = "",
) -> dict:
    state = normalize_lead_state(current_state)
    text = normalize_id(text)

    phone_candidates = extract_phone_candidates(text)
    if phone_candidates:
        state["phone"] = phone_candidates[0]
        state["phone_collected"] = True

    name_candidate = extract_customer_name_candidate(text)
    if not name_candidate:
        hinted_name = normalize_id(customer_name_hint)
        if hinted_name and not _looks_like_generated_instagram_name(hinted_name):
            if _looks_like_customer_name(hinted_name):
                name_candidate = hinted_name

    if name_candidate:
        state["customer_name"] = name_candidate
        state["name_collected"] = True

    if message_id:
        state["last_message_id"] = normalize_id(message_id)
    if text:
        state["last_lead_update"] = datetime.utcnow().isoformat()

    return normalize_lead_state(state)


def get_customer_lead_state(platform: str, business_id: str, customer_id: str, channel: str = "") -> dict:
    platform = normalize_id(platform).lower()
    business_id = normalize_id(business_id)
    customer_id = normalize_id(customer_id)
    channel = normalize_id(channel).lower()
    if not platform or not business_id or not customer_id:
        return normalize_lead_state({})

    state_key = lead_state_workspace_key(platform, customer_id, channel)
    if not state_key:
        return normalize_lead_state({})

    try:
        rows = (
            supabase.table("dashboard_workspace_state")
            .select("state_value")
            .eq("business_id", business_id)
            .eq("state_key", state_key)
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows:
            value = rows[0].get("state_value")
            if isinstance(value, dict):
                return normalize_lead_state(value)
    except Exception as exc:
        log("Could not load customer lead state", {"business_id": business_id, "customer_id": customer_id, "error": str(exc)})

    return normalize_lead_state({})


def upsert_customer_lead_state(
    business_id: str,
    platform: str,
    customer_id: str,
    lead_state: dict,
    channel: str = "",
    updated_by: str = "instagram_bot",
) -> dict:
    business_id = normalize_id(business_id)
    platform = normalize_id(platform).lower()
    customer_id = normalize_id(customer_id)
    channel = normalize_id(channel).lower()
    state_key = lead_state_workspace_key(platform, customer_id, channel)
    state_value = normalize_lead_state(lead_state)

    if not business_id or not state_key:
        return state_value

    try:
        supabase.table("dashboard_workspace_state").upsert(
            {
                "business_id": business_id,
                "state_key": state_key,
                "state_value": state_value,
                "updated_by": normalize_id(updated_by),
            },
            on_conflict="business_id,state_key",
        ).execute()
    except Exception as exc:
        log("Could not upsert customer lead state", {"business_id": business_id, "customer_id": customer_id, "error": str(exc)})

    return state_value


def derive_customer_lead_state(
    platform: str,
    business: dict,
    customer_id: str,
    channel: str = "",
    recent_rows: list = None,
    current_text: str = "",
    customer_name_hint: str = "",
    message_id: str = "",
) -> dict:
    state = get_customer_lead_state(platform, business.get("id", ""), customer_id, channel)
    rows = list(recent_rows or [])

    for row in rows:
        if not isinstance(row, dict):
            continue
        if normalize_id(row.get("direction")).lower() != "inbound":
            continue
        row_text = normalize_id(row.get("content"))
        row_name = normalize_id(row.get("customer_name"))
        row_state = {
            "phone": state.get("phone", ""),
            "customer_name": state.get("customer_name", ""),
            "phone_collected": state.get("phone_collected", False),
            "name_collected": state.get("name_collected", False),
            "last_lead_update": state.get("last_lead_update", ""),
            "last_message_id": normalize_id(row.get("external_message_id")),
        }
        if row_text:
            row_state = extract_lead_state_from_text(row_text, row_state, row_name, row.get("external_message_id"))
            if row_name and not _looks_like_generated_instagram_name(row_name) and _looks_like_customer_name(row_name):
                row_state["customer_name"] = row_name
                row_state["name_collected"] = True
        state = normalize_lead_state({
            **state,
            **row_state,
        })

    if current_text or customer_name_hint:
        state = extract_lead_state_from_text(current_text, state, customer_name_hint, message_id)

    if state.get("customer_name") and _looks_like_generated_instagram_name(state.get("customer_name")):
        state["name_collected"] = False

    return normalize_lead_state(state)


def business_allows_auto_reply(business: dict, platform: str, channel: str = "") -> bool:
    business = business or {}
    if not normalize_bool(business.get("bot_enabled"), True):
        return False

    mode = get_business_automation_mode(business)
    if mode in {"OFF", "DISABLED", "MANUAL", "HUMAN_ONLY"}:
        return False

    platform = normalize_id(platform).lower()
    channel = normalize_id(channel).lower()

    if platform == "instagram":
        if channel == "dm":
            return normalize_bool(business.get("auto_reply_dms"), True)
        if "comment" in channel:
            return normalize_bool(business.get("auto_reply_comments"), True)
        return True

    if platform == "telegram":
        if channel in {"bot", "telegram_bot"}:
            return normalize_bool(business.get("telegram_bot_enabled"), True)
        return True

    if platform == "whatsapp":
        return normalize_bool(business.get("whatsapp_enabled"), True)

    return True


def business_allows_human_handoff(business: dict = None) -> bool:
    return normalize_bool((business or {}).get("human_takeover_enabled"), True)


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


def instagram_reel_cache_id(permalink: str) -> str:
    permalink = normalize_id(unwrap_meta_redirect_url(permalink))
    if not permalink:
        return ""
    return hashlib.sha256(permalink.encode("utf-8")).hexdigest()[:32]


def is_instagram_reel_cache_url(url: str) -> bool:
    value = normalize_id(url)
    return "/api/instagram-reel-cache/" in value


def instagram_reel_cache_url(cache_name: str) -> str:
    cache_name = normalize_id(cache_name)
    if not re.fullmatch(r"[a-f0-9]{32}\.(mp4|m4v|mov|webm)", cache_name):
        return ""
    base_root = (PUBLIC_BASE_URL or "").rstrip("/")
    base = f"{base_root}/api/instagram-reel-cache/{cache_name}" if base_root else f"/api/instagram-reel-cache/{cache_name}"
    if DASHBOARD_SECRET:
        return f"{base}?token={DASHBOARD_SECRET}"
    return base


def find_instagram_reel_cache_path(cache_id: str) -> Path | None:
    cache_id = normalize_id(cache_id).lower()
    if not re.fullmatch(r"[a-f0-9]{32}", cache_id):
        return None
    try:
        for ext in ("mp4", "m4v", "mov", "webm"):
            path = INSTAGRAM_REEL_CACHE_DIR / f"{cache_id}.{ext}"
            if path.exists() and path.is_file() and path.stat().st_size > 0:
                return path
    except Exception:
        return None
    return None


def download_instagram_reel_to_cache(permalink: str) -> dict:
    permalink = normalize_id(unwrap_meta_redirect_url(permalink))
    if not INSTAGRAM_REEL_DOWNLOAD_ENABLED or not is_instagram_public_link(permalink):
        return {}

    cache_id = instagram_reel_cache_id(permalink)
    if not cache_id:
        return {}

    cached_path = find_instagram_reel_cache_path(cache_id)
    if cached_path:
        return {
            "media_url": instagram_reel_cache_url(cached_path.name),
            "media_type": "video",
            "cache_name": cached_path.name,
        }

    now = time.time()
    attempted = INSTAGRAM_REEL_DOWNLOAD_ATTEMPT_CACHE.get(cache_id)
    if attempted and (now - attempted[0]) < INSTAGRAM_REEL_DOWNLOAD_FAILURE_TTL_SECONDS:
        return attempted[1] or {}

    INSTAGRAM_REEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="ig-reel-", dir=str(INSTAGRAM_REEL_CACHE_DIR)))
    try:
        output_template = str(tmp_dir / f"{cache_id}.%(ext)s")
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--no-warnings",
            "--quiet",
            "--no-cache-dir",
            "--socket-timeout",
            str(min(INSTAGRAM_REEL_DOWNLOAD_TIMEOUT_SECONDS, 30)),
            "--max-filesize",
            f"{INSTAGRAM_REEL_MAX_MB}M",
            "--format",
            "best[ext=mp4]/mp4/best[ext=m4v]/best[ext=webm]/best",
            "--output",
            output_template,
            "--print",
            "after_move:filepath",
            permalink,
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=INSTAGRAM_REEL_DOWNLOAD_TIMEOUT_SECONDS + 10,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:500]
            log("Instagram reel download failed", {"permalink": permalink, "error": detail or result.returncode})
            INSTAGRAM_REEL_DOWNLOAD_ATTEMPT_CACHE[cache_id] = (now, {})
            return {}

        candidates = []
        for line in (result.stdout or "").splitlines():
            candidate = Path(line.strip())
            if candidate.exists() and candidate.is_file():
                candidates.append(candidate)
        if not candidates:
            candidates = [p for p in tmp_dir.glob(f"{cache_id}.*") if p.is_file()]

        max_bytes = INSTAGRAM_REEL_MAX_MB * 1024 * 1024
        for candidate in candidates:
            ext = candidate.suffix.lower().lstrip(".")
            if ext not in {"mp4", "m4v", "mov", "webm"}:
                continue
            size = candidate.stat().st_size
            if size <= 0 or size > max_bytes:
                continue
            final_path = INSTAGRAM_REEL_CACHE_DIR / f"{cache_id}.{ext}"
            if final_path.exists():
                final_path.unlink()
            shutil.move(str(candidate), str(final_path))
            payload = {
                "media_url": instagram_reel_cache_url(final_path.name),
                "media_type": "video",
                "cache_name": final_path.name,
                "size": size,
            }
            INSTAGRAM_REEL_DOWNLOAD_ATTEMPT_CACHE[cache_id] = (now, payload)
            return payload

        log("Instagram reel download produced no playable file", {"permalink": permalink})
        INSTAGRAM_REEL_DOWNLOAD_ATTEMPT_CACHE[cache_id] = (now, {})
        return {}
    except Exception as exc:
        log("Instagram reel download error", {"permalink": permalink, "error": str(exc)})
        INSTAGRAM_REEL_DOWNLOAD_ATTEMPT_CACHE[cache_id] = (now, {})
        return {}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def cache_instagram_reel_for_message(message_id: str, post_permalink: str):
    message_id = normalize_id(message_id)
    post_permalink = normalize_id(post_permalink)
    if not message_id or not post_permalink:
        return
    try:
        cached_reel = download_instagram_reel_to_cache(post_permalink) or {}
        cached_media_url = normalize_id(cached_reel.get("media_url"))
        if not cached_media_url:
            return
        supabase.table("inbox_messages").update({
            "media_url": cached_media_url,
            "media_type": "video",
            "post_permalink": post_permalink,
            "post_media_type": "video",
        }).eq("id", message_id).execute()
        clear_inbox_caches()
    except Exception as exc:
        log("Could not persist Instagram reel cache", {"message_id": message_id, "error": str(exc)})


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
CONVERSATIONS_FAST_LOOKBACK_DAYS = max(7, min(365, int(os.getenv("CONVERSATIONS_FAST_LOOKBACK_DAYS", "120"))))
CONVERSATIONS_FAST_FETCH_LIMIT = max(80, min(5000, int(os.getenv("CONVERSATIONS_FAST_FETCH_LIMIT", "800"))))
CONVERSATIONS_MAX_FETCH_ROWS = max(200, min(20000, int(os.getenv("CONVERSATIONS_MAX_FETCH_ROWS", "5000"))))
CONVERSATIONS_FETCH_BATCH_SIZE = max(100, min(1000, int(os.getenv("CONVERSATIONS_FETCH_BATCH_SIZE", "1000"))))
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


def is_local_dashboard_demo_mode() -> bool:
    secret = str(DASHBOARD_SECRET or "").strip().lower()
    supabase_url = str(SUPABASE_URL or "").strip().lower()
    return secret == "localdev" or "example.supabase.co" in supabase_url


def build_local_dashboard_demo_business(email: str = "") -> dict:
    clean_email = normalize_email(email)
    return {
        "id": "localdev-demo-business",
        "business_name": "Milana Premium",
        "owner_email": clean_email or "localdev@example.com",
        "business_type": "fashion",
        "bot_enabled": True,
        "auto_reply_dms": True,
        "auto_reply_comments": True,
        "language": "ru",
        "tone": "friendly",
        "ai_model": "gemini-3-flash-preview",
    }


def build_local_dashboard_demo_stats() -> dict:
    return {
        "total_accounts": 1,
        "active_accounts": 1,
        "instagram_messages": 0,
        "telegram_messages": 0,
        "whatsapp_messages": 0,
        "conversations": 0,
        "messages": 0,
        "needs_reply": 0,
        "unread": 0,
    }


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
        # Fallback path for stale/invalid browser token when dashboard secret is valid.
        if not require_dashboard_secret(x_dashboard_secret):
            return {"email": "system", "is_admin": True, "business_ids": [], "role": "admin"}
        return None

    # Backward-compatible admin/system path
    if not require_dashboard_secret(x_dashboard_secret):
        return {"email": "system", "is_admin": True, "business_ids": [], "role": "admin"}
    return None


def can_access_business(access: dict, business_id: str) -> bool:
    if not access:
        return False
    if access.get("is_admin"):
        return True
    return normalize_id(business_id) in set(access.get("business_ids") or [])


def can_manage_business(access: dict, business_id: str = "") -> bool:
    if not access:
        return False
    if access.get("is_admin"):
        return True
    business_id = normalize_id(business_id)
    if business_id and not can_access_business(access, business_id):
        return False
    role = normalize_id(get_user_business_role(access.get("email"), business_id) or access.get("role")).lower()
    return role in {"owner", "admin", "super_admin"}


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


def instagram_human_agent_review_required(result: dict) -> bool:
    error = result.get("error") if isinstance(result, dict) else {}
    if not isinstance(error, dict):
        error = {}
    message = normalize_id(error.get("message") or result.get("message"))
    return "human agent" in message.lower() and "review" in message.lower()


def send_failure_response(result: dict, default_message: str = "Failed to send message"):
    message = default_message
    if instagram_reply_window_closed(result or {}):
        message = "Instagram reply window is closed. Ask the customer to send a new DM first."
    elif instagram_human_agent_review_required(result or {}):
        message = "Instagram Human Agent is not approved for this Meta app. Ask the customer to send a new DM first."

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


def transcribe_audio_bytes(file_bytes: bytes, filename: str = "", mime_type: str = "") -> str:
    if not OPENAI_API_KEY or not file_bytes:
        return ""

    safe_name = normalize_id(filename) or "audio.ogg"
    guessed_mime = normalize_id(mime_type) or mimetypes.guess_type(safe_name)[0] or "audio/ogg"

    try:
        response = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            data={"model": OPENAI_TRANSCRIBE_MODEL},
            files={"file": (safe_name, file_bytes, guessed_mime)},
            timeout=OPENAI_TRANSCRIBE_TIMEOUT_SECONDS,
        )
        log("OpenAI audio transcription", {"status": response.status_code, "body": response.text[:500]})
        if not response.ok:
            return ""
        payload = response.json() if response.content else {}
        return normalize_id(payload.get("text"))
    except Exception as exc:
        log("OpenAI audio transcription failed", str(exc))
        return ""


def transcribe_media_url_for_voice(media_url: str, access_token: str = "") -> str:
    media_url = normalize_id(media_url)
    if not media_url:
        return ""
    try:
        media_bytes, filename, mime_type = download_media_for_matcher(media_url, access_token=access_token)
        return transcribe_audio_bytes(media_bytes, filename=filename, mime_type=mime_type)
    except Exception as exc:
        log("Voice media transcription failed", {"media_url": media_url[:200], "error": str(exc)})
        return ""


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


def parse_http_range(range_header: str, total_size: int):
    range_header = normalize_id(range_header)
    if not range_header or not range_header.startswith("bytes=") or total_size <= 0:
        return None
    try:
        raw_start, raw_end = range_header.replace("bytes=", "", 1).split("-", 1)
        if raw_start == "":
            suffix = int(raw_end)
            if suffix <= 0:
                return None
            start = max(total_size - suffix, 0)
            end = total_size - 1
        else:
            start = int(raw_start)
            end = int(raw_end) if raw_end else total_size - 1
        if start < 0 or end < start or start >= total_size:
            return None
        return start, min(end, total_size - 1)
    except Exception:
        return None


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


def parse_instagram_test_allowlist(value) -> set[str]:
    raw_items = []
    if isinstance(value, dict):
        value = value.get("items") if isinstance(value.get("items"), list) else value.get("value", "")
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[\s,;]+", normalize_id(value))

    allowed = set()
    for item in raw_items:
        clean = normalize_id(item).lower().lstrip("@")
        if clean:
            allowed.add(clean)
    return allowed


def instagram_dm_allowed_for_test_customer(business_id: str, sender_id: str, sender_profile: dict = None, customer_name: str = "") -> bool:
    state = get_workspace_state(business_id)
    allowed = parse_instagram_test_allowlist(state.get("instagram_dm_test_allowlist"))
    if not allowed:
        return True

    profile = sender_profile if isinstance(sender_profile, dict) else {}
    candidates = {
        normalize_id(sender_id).lower().lstrip("@"),
        normalize_id(customer_name).lower().lstrip("@"),
        normalize_id(profile.get("username")).lower().lstrip("@"),
        normalize_id(profile.get("name")).lower().lstrip("@"),
    }
    return bool(allowed.intersection({item for item in candidates if item}))


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
    "memory_enabled",
    "memory_limit",
    "dashboard_language",
    "bot_language_mode",
    "automation_mode",
    "human_takeover_enabled",
    "whatsapp_enabled",
    "telegram_bot_enabled",
    "telegram_chat_id",
    "telegram_notes",
    "analytics_enabled",
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


def set_business_channel_chat_ai_enabled(business_id: str, platform: str, channel: str, enabled: bool) -> int:
    business_id = normalize_id(business_id)
    platform = normalize_id(platform).lower()
    channel = standard_channel(platform, channel)
    if not business_id or not platform:
        return 0
    try:
        result = (
            supabase.table("chat_ai_settings")
            .update({"ai_enabled": bool(enabled)})
            .eq("business_id", business_id)
            .eq("platform", platform)
            .eq("channel", channel or "")
            .execute()
        )
        rows = result.data if isinstance(result.data, list) else []
        return len(rows)
    except Exception as exc:
        log("Could not sync channel chat AI settings", {
            "business_id": business_id,
            "platform": platform,
            "channel": channel,
            "enabled": bool(enabled),
            "error": str(exc),
        })
        return 0


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


def load_inbox_message_by_external_id(
    business_id: str,
    platform: str,
    customer_id: str,
    external_message_id: str,
    direction: str = "",
) -> dict:
    business_id = normalize_id(business_id)
    platform = normalize_id(platform)
    customer_id = normalize_id(customer_id)
    external_message_id = normalize_id(external_message_id)
    direction = normalize_id(direction)
    if not business_id or not platform or not customer_id or not external_message_id:
        return {}

    try:
        query = (
            supabase.table("inbox_messages")
            .select("id,created_at,external_message_id,direction,platform,customer_id")
            .eq("business_id", business_id)
            .eq("platform", platform)
            .eq("customer_id", customer_id)
            .eq("external_message_id", external_message_id)
            .order("created_at", desc=True)
            .limit(5)
        )
        if direction:
            query = query.eq("direction", direction)
        rows = query.execute().data or []
        return rows[0] if rows and isinstance(rows[0], dict) else {}
    except Exception as exc:
        log("Could not load inbox message by external id", {"business_id": business_id, "platform": platform, "external_message_id": external_message_id, "error": str(exc)})
        return {}


def mark_customer_inbound_read(business_id: str, platform: str, customer_id: str, channel: str = ""):
    business_id = normalize_id(business_id)
    platform = normalize_id(platform).lower()
    customer_id = normalize_id(customer_id)
    channel = standard_channel(platform, channel)
    if not business_id or not platform or not customer_id:
        return
    try:
        query = (
            supabase.table("inbox_messages")
            .update({"is_read": True})
            .eq("business_id", business_id)
            .eq("platform", platform)
            .eq("customer_id", customer_id)
            .eq("direction", "inbound")
            .eq("is_read", False)
        )
        if channel:
            query = query.eq("channel", channel)
        query.execute()
        clear_inbox_caches()
    except Exception as exc:
        log("Could not mark customer inbound read", {"business_id": business_id, "platform": platform, "customer_id": customer_id, "error": str(exc)})


def has_outbound_reply_after(
    business_id: str,
    platform: str,
    customer_id: str,
    inbound_created_at: str,
    channel: str = "",
) -> bool:
    business_id = normalize_id(business_id)
    platform = normalize_id(platform)
    customer_id = normalize_id(customer_id)
    inbound_created_at = normalize_id(inbound_created_at)
    channel = normalize_id(channel)
    if not business_id or not platform or not customer_id or not inbound_created_at:
        return False

    try:
        query = (
            supabase.table("inbox_messages")
            .select("id,created_at,external_message_id")
            .eq("business_id", business_id)
            .eq("platform", platform)
            .eq("customer_id", customer_id)
            .eq("direction", "outbound")
            .gt("created_at", inbound_created_at)
            .order("created_at", desc=True)
            .limit(1)
        )
        if channel:
            query = query.eq("channel", channel)
        rows = query.execute().data or []
        return bool(rows and isinstance(rows[0], dict))
    except Exception as exc:
        log("Could not check outbound reply dedupe", {"business_id": business_id, "platform": platform, "customer_id": customer_id, "error": str(exc)})
        return False


def has_recent_outbound_text(
    business_id: str,
    platform: str,
    customer_id: str,
    message_text: str,
    channel: str = "",
    window_seconds: int = OUTBOUND_DUPLICATE_WINDOW_SECONDS,
) -> bool:
    business_id = normalize_id(business_id)
    platform = normalize_id(platform)
    customer_id = normalize_id(customer_id)
    channel = normalize_id(channel)
    message_text = normalize_id(message_text)
    if not business_id or not platform or not customer_id or not message_text:
        return False

    try:
        rows = (
            supabase.table("inbox_messages")
            .select("content,created_at")
            .eq("business_id", business_id)
            .eq("platform", platform)
            .eq("customer_id", customer_id)
            .eq("direction", "outbound")
            .eq("channel", standard_channel(platform, channel))
            .order("created_at", desc=True)
            .limit(5)
            .execute()
            .data
            or []
        )
        now = datetime.utcnow()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if normalize_id(row.get("content")) != message_text:
                continue
            created_at = normalize_id(row.get("created_at"))
            if not created_at:
                continue
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                continue
            if (now - dt).total_seconds() <= window_seconds:
                return True
    except Exception as exc:
        log("Could not check recent outbound text dedupe", {
            "business_id": business_id,
            "platform": platform,
            "customer_id": customer_id,
            "error": str(exc),
        })
    return False


def get_message_count(platform=None, business_ids=None):
    try:
        if business_ids is not None and not business_ids:
            return 0
        q = supabase.table("inbox_messages").select("id", count="exact")
        if platform:
            q = q.eq("platform", platform)
        if business_ids is not None:
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


def _safe_state_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _safe_state_items(value) -> list:
    return value if isinstance(value, list) else []


def _safe_rows(value) -> list:
    return value if isinstance(value, list) else []


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_manual_lead(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    lead_id = normalize_id(item.get("id")) or f"manual_lead_{secrets.token_hex(5)}"
    return {
        "id": lead_id,
        "name": normalize_id(item.get("name")) or "Manual lead",
        "platform": normalize_id(item.get("platform")).lower() or "manual",
        "operator": normalize_id(item.get("operator") or item.get("owner")),
        "note": normalize_id(item.get("note") or item.get("last_message")),
        "price": normalize_id(item.get("price")),
        "stage": normalize_id(item.get("stage")).lower(),
        "created_at": normalize_id(item.get("created_at") or item.get("createdAt")),
    }


def collect_sales_agent_lead_states(business_id: str) -> list[dict]:
    state = get_workspace_state(business_id)
    if not isinstance(state, dict):
        return []
    leads = []
    for key, value in state.items():
        if isinstance(key, str) and key.startswith("lead_state:") and isinstance(value, dict):
            leads.append(normalize_lead_state(value))
    return leads


def collect_workspace_ai_actions(business_id: str) -> list[dict]:
    state = get_workspace_state(business_id)
    bucket = state.get("ai_actions_recent") or {}
    items = bucket.get("items") if isinstance(bucket, dict) else []
    return [item for item in items if isinstance(item, dict)]


def load_ai_actions_for_metrics(business_ids: list[str], limit: int = 1000) -> list[dict]:
    actions = []
    clean_ids = [normalize_id(item) for item in (business_ids or []) if normalize_id(item)]
    try:
        query = (
            supabase.table("ai_actions")
            .select("business_id,customer_id,platform,action_type,confidence,handoff_required,manager_corrected,created_at")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if clean_ids:
            query = query.in_("business_id", clean_ids)
        actions = _safe_rows(query.execute().data)
    except Exception:
        actions = []

    if clean_ids:
        for business_id in clean_ids:
            actions.extend(collect_workspace_ai_actions(business_id))
    return [item for item in actions if isinstance(item, dict)]


def estimate_average_response_minutes(business_ids: list[str], limit: int = 1200) -> float:
    clean_ids = [normalize_id(item) for item in (business_ids or []) if normalize_id(item)]
    try:
        query = (
            supabase.table("inbox_messages")
            .select("business_id,platform,channel,customer_id,chat_id,direction,created_at")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if clean_ids:
            query = query.in_("business_id", clean_ids)
        rows = list(reversed(_safe_rows(query.execute().data)))
    except Exception:
        return 0.0

    pending = {}
    intervals = []
    for row in rows:
        created_at = normalize_id(row.get("created_at"))
        try:
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
        platform = normalize_id(row.get("platform")).lower()
        channel = standard_channel(platform, row.get("channel", ""))
        key = (
            normalize_id(row.get("business_id")),
            platform,
            channel,
            conversation_scope(platform, channel, row.get("customer_id"), row.get("chat_id")),
        )
        if normalize_id(row.get("direction")).lower() == "inbound":
            pending[key] = ts
        elif key in pending:
            delta = (ts - pending.pop(key)).total_seconds() / 60
            if 0 <= delta <= 24 * 60:
                intervals.append(delta)
    if not intervals:
        return 0.0
    return round(sum(intervals) / len(intervals), 1)


def build_sales_agent_metrics(business_ids: list[str]) -> dict:
    clean_ids = [normalize_id(item) for item in (business_ids or []) if normalize_id(item)]
    leads = []
    for business_id in clean_ids:
        leads.extend(_safe_rows(collect_sales_agent_lead_states(business_id)))

    today = datetime.utcnow().date()
    stage_counts = {}
    for lead in leads:
        stage = normalize_id(lead.get("stage") or "new").lower()
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    phones = {
        normalize_phone_number(lead.get("phone"))
        for lead in leads
        if normalize_phone_number(lead.get("phone"))
    }
    actions = _safe_rows(load_ai_actions_for_metrics(clean_ids))
    action_count = len(actions)
    handoff_actions = [action for action in actions if action.get("handoff_required")]
    low_confidence = [action for action in actions if 0 < _safe_float(action.get("confidence")) < 0.45]
    manager_corrections = [action for action in actions if action.get("manager_corrected")]

    new_today = 0
    for lead in leads:
        ts = normalize_id(lead.get("updated_at") or lead.get("last_message_at") or lead.get("last_lead_update"))
        try:
            if datetime.fromisoformat(ts.replace("Z", "+00:00")).date() == today:
                new_today += 1
        except Exception:
            pass

    qualified = sum(stage_counts.get(stage, 0) for stage in ("qualified", "hot", "handoff_required", "won"))
    handoff_rate = round((len(handoff_actions) / action_count) * 100, 1) if action_count else 0.0
    return {
        "new_leads_today": new_today,
        "qualified_leads": qualified,
        "hot_leads": stage_counts.get("hot", 0),
        "handoff_required_leads": stage_counts.get("handoff_required", 0),
        "won_orders": stage_counts.get("won", 0),
        "lost_leads": stage_counts.get("lost", 0),
        "phone_numbers_collected": len(phones),
        "average_response_time_minutes": estimate_average_response_minutes(clean_ids),
        "ai_to_human_handoff_rate": handoff_rate,
        "ai_actions_logged": action_count,
        "low_confidence_replies": len(low_confidence),
        "manager_corrections": len(manager_corrections),
        "wrong_replies": len([a for a in actions if normalize_id(a.get("action_type")).lower() == "wrong_reply"]),
        "hallucination_reports": len([a for a in actions if normalize_id(a.get("action_type")).lower() == "hallucination_report"]),
        "customer_asked_for_human": len([a for a in actions if "human" in json.dumps(a, ensure_ascii=False).lower()]),
    }


def load_business_conversation_lookup(business_id: str, limit: int = 2500) -> dict:
    business_id = normalize_id(business_id)
    if not business_id:
        return {}

    try:
        rows = (
            supabase.table("inbox_messages")
            .select(
                "business_id,platform,channel,customer_id,chat_id,customer_name,"
                "content,created_at,direction,is_read,external_message_id,raw_payload"
            )
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        log("Could not load conversation rows for report", {"business_id": business_id, "error": str(exc)})
        rows = []

    grouped = {}
    for row in rows:
        platform = normalize_id(row.get("platform", "instagram")).lower() or "instagram"
        channel = standard_channel(platform, row.get("channel", ""))
        customer_id = normalize_id(row.get("customer_id"))
        chat_id = normalize_id(row.get("chat_id"))
        scope = conversation_scope(platform, channel, customer_id, chat_id)
        if platform == "instagram" and "comment" in channel:
            post_id = extract_instagram_comment_post_id(row)
            scope = encode_comment_scope(customer_id, post_id) if post_id else scope
        if not scope:
            continue
        key = f"{platform}::{business_id}::{channel}::{scope}"
        grouped.setdefault(key, []).append(row)

    business = get_business_by_id(business_id) or {}
    lookup = {}
    for key, conv_rows in grouped.items():
        conv = transform_conversation_to_react(
            key,
            sorted(conv_rows, key=lambda item: item.get("created_at", "")),
            business=business,
            ai_lookup_enabled=False,
        )
        if conv:
            lookup[key] = conv
    return lookup


def build_operator_deal_report_data(business_id: str) -> dict:
    business_id = normalize_id(business_id)
    business = get_business_by_id(business_id) or {}
    state = get_workspace_state(business_id)
    lead_stages = _safe_state_dict(state.get("lead_stages"))
    lead_prices = _safe_state_dict(state.get("lead_prices"))
    client_owners = _safe_state_dict(state.get("client_owners"))
    manual_clients_bucket = state.get("manual_clients") or {}
    manual_clients = _safe_state_items(manual_clients_bucket.get("items") if isinstance(manual_clients_bucket, dict) else [])
    manual_leads_bucket = state.get("manual_leads") or {}
    manual_leads = [
        lead for lead in (
            normalize_manual_lead(item)
            for item in _safe_state_items(manual_leads_bucket.get("items") if isinstance(manual_leads_bucket, dict) else [])
        )
        if lead.get("id")
    ]
    manual_lead_lookup = {lead["id"]: lead for lead in manual_leads}
    legacy_operator_deals = _safe_state_dict(state.get("operator_deals"))
    conversations = load_business_conversation_lookup(business_id)

    conversation_ids = set(str(item) for item in manual_clients if item)
    conversation_ids.update(manual_lead_lookup.keys())
    conversation_ids.update(str(key) for key in client_owners.keys() if key)
    conversation_ids.update(str(key) for key, stage in lead_stages.items() if normalize_id(stage).lower() == "won")
    conversation_ids.update(str(key) for key in conversations.keys() if client_owners.get(key) or lead_stages.get(key) == "won")

    rows = []
    ranking = {}
    for conversation_id in sorted(conversation_ids):
        conv = conversations.get(conversation_id) or {}
        manual_lead = manual_lead_lookup.get(conversation_id) or {}
        owner = normalize_id(client_owners.get(conversation_id) or manual_lead.get("operator"))
        stage = normalize_id(lead_stages.get(conversation_id) or manual_lead.get("stage")) or "new"
        successful = stage.lower() == "won" and bool(owner)
        if successful:
            ranking.setdefault(owner, {"operator": owner, "picked_clients": 0, "successful_deals": 0, "clients": []})
            ranking[owner]["successful_deals"] += 1
            ranking[owner]["clients"].append(conv.get("name") or conversation_id)
        if owner:
            ranking.setdefault(owner, {"operator": owner, "picked_clients": 0, "successful_deals": 0, "clients": []})
            ranking[owner]["picked_clients"] += 1

        parts = conversation_id.split("::")
        platform = conv.get("platform") or (parts[0] if len(parts) == 4 else "")
        channel = parts[2] if len(parts) == 4 else ""
        rows.append({
            "conversation_id": conversation_id,
            "client": manual_lead.get("name") or conv.get("name") or conv.get("handle") or (parts[3] if len(parts) == 4 else conversation_id),
            "handle": conv.get("handle") or "",
            "platform": manual_lead.get("platform") or platform,
            "channel": channel or ("manual" if manual_lead else ""),
            "operator": owner or "Unassigned",
            "stage": stage,
            "successful_deal": successful,
            "price": normalize_id(lead_prices.get(conversation_id) or manual_lead.get("price")) or "-",
            "last_message": normalize_id(manual_lead.get("note") or conv.get("preview")) or "-",
            "last_at": normalize_id(conv.get("lastAt") or conv.get("lastTime") or manual_lead.get("created_at")) or "-",
            "source": "Manual lead" if manual_lead else "Conversation",
        })

    for operator_id, count in legacy_operator_deals.items():
        operator = normalize_id(operator_id)
        if not operator:
            continue
        ranking.setdefault(operator, {"operator": operator, "picked_clients": 0, "successful_deals": 0, "clients": []})
        if not ranking[operator]["successful_deals"]:
            try:
                ranking[operator]["successful_deals"] = int(count or 0)
            except Exception:
                pass

    ranking_rows = sorted(
        ranking.values(),
        key=lambda item: (int(item.get("successful_deals") or 0), int(item.get("picked_clients") or 0), item.get("operator", "")),
        reverse=True,
    )
    return {
        "business": sanitize_business_row(business) or {"id": business_id},
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "ranking": ranking_rows,
        "clients": rows,
        "summary": {
            "total_clients": len(rows),
            "manual_leads": len(manual_leads),
            "picked_clients": sum(1 for row in rows if row.get("operator") and row.get("operator") != "Unassigned"),
            "successful_deals": sum(1 for row in rows if row.get("successful_deal")),
        },
    }


def _pdf_text(value) -> str:
    text = re.sub(r"\s+", " ", normalize_id(value)).strip()
    return text.encode("latin-1", "replace").decode("latin-1")


def _pdf_escape(value) -> str:
    return _pdf_text(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_pdf_line(text: str, width: int = 132) -> list[str]:
    text = _pdf_text(text)
    if len(text) <= width:
        return [text]
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word[:width]
    if current:
        lines.append(current)
    return lines or [""]


def build_operator_deal_report_pdf(report: dict) -> bytes:
    try:
        return build_operator_deal_report_pdf_reportlab(report)
    except Exception as exc:
        log("ReportLab operator report failed, using fallback PDF", str(exc))

    business = report.get("business") or {}
    business_name = normalize_id(business.get("business_name")) or normalize_id(business.get("id")) or "Business"
    lines = [
        f"Operator deals report - {business_name}",
        f"Generated: {report.get('generated_at')}",
        "",
        "Operator ranking",
    ]
    ranking = report.get("ranking") or []
    if ranking:
        for index, row in enumerate(ranking, start=1):
            lines.append(
                f"{index}. {row.get('operator')}: {row.get('successful_deals', 0)} successful deals, "
                f"{row.get('picked_clients', 0)} picked clients"
            )
    else:
        lines.append("No picked clients or successful deals yet.")

    lines.extend(["", "Client details"])
    clients = report.get("clients") or []
    if clients:
        for row in clients:
            deal_status = "SUCCESS" if row.get("successful_deal") else "pending/not won"
            lines.append(
                f"- {row.get('client')} {row.get('handle')}: operator={row.get('operator')}; "
                f"stage={row.get('stage')}; deal={deal_status}; price={row.get('price')}; "
                f"channel={row.get('platform')}/{row.get('channel')}; last={row.get('last_message')}"
            )
    else:
        lines.append("No client rows to report.")

    wrapped_lines = []
    for line in lines:
        if not line:
            wrapped_lines.append("")
        else:
            wrapped_lines.extend(_wrap_pdf_line(line))

    page_width = 842
    page_height = 595
    margin_x = 36
    start_y = 555
    line_height = 12
    lines_per_page = 42
    pages = [wrapped_lines[i:i + lines_per_page] for i in range(0, len(wrapped_lines), lines_per_page)] or [[]]

    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    page_refs = []
    for page_lines in pages:
        content_parts = []
        y = start_y
        for line in page_lines:
            font_size = 14 if y == start_y and page_lines is pages[0] else 9
            content_parts.append(f"BT /F1 {font_size} Tf {margin_x} {y} Td ({_pdf_escape(line)}) Tj ET")
            y -= line_height
        stream = "\n".join(content_parts)
        content_obj_num = len(objects) + 1
        objects.append(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")
        page_obj_num = len(objects) + 1
        page_refs.append(f"{page_obj_num} 0 R")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj_num} 0 R >>"
        )
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(page_refs)}] /Count {len(page_refs)} >>"

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n{obj}\nendobj\n".encode("latin-1"))
    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("latin-1")
    )
    return bytes(pdf)


def build_operator_deal_report_pdf_reportlab(report: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    def register_font() -> tuple[str, str]:
        regular_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
        bold_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
        ]
        regular = next((path for path in regular_candidates if Path(path).exists()), "")
        bold = next((path for path in bold_candidates if Path(path).exists()), "")
        if regular:
            pdfmetrics.registerFont(TTFont("InstaReport", regular))
            if bold:
                pdfmetrics.registerFont(TTFont("InstaReport-Bold", bold))
                return "InstaReport", "InstaReport-Bold"
            return "InstaReport", "InstaReport"
        return "Helvetica", "Helvetica-Bold"

    font_name, bold_font = register_font()
    buffer = io.BytesIO()
    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=13 * mm,
        title="Operator Deals Report",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#111827"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#6B7280"),
        spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "ReportSection",
        parent=styles["Heading2"],
        fontName=bold_font,
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#111827"),
        spaceBefore=8,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#111827"),
    )
    muted_style = ParagraphStyle(
        "ReportMuted",
        parent=body_style,
        textColor=colors.HexColor("#6B7280"),
    )
    header_style = ParagraphStyle(
        "ReportHeader",
        parent=body_style,
        fontName=bold_font,
        textColor=colors.white,
    )
    right_style = ParagraphStyle("Right", parent=body_style, alignment=TA_RIGHT)

    business = report.get("business") or {}
    business_name = normalize_id(business.get("business_name")) or normalize_id(business.get("id")) or "Business"
    generated_at = normalize_id(report.get("generated_at"))
    summary = report.get("summary") or {}
    ranking = report.get("ranking") or []
    clients = report.get("clients") or []

    story = [
        Paragraph("Operator Performance Report", title_style),
        Paragraph(f"{business_name} · Generated {generated_at}", subtitle_style),
    ]

    metrics = [
        ["Successful deals", str(summary.get("successful_deals", 0))],
        ["Picked clients", str(summary.get("picked_clients", 0))],
        ["Manual leads", str(summary.get("manual_leads", 0))],
        ["Total tracked clients", str(summary.get("total_clients", 0))],
    ]
    metrics_table = Table(
        [[Paragraph(label, muted_style), Paragraph(value, ParagraphStyle(f"Metric{idx}", parent=right_style, fontName=bold_font, fontSize=16, leading=18))]
         for idx, (label, value) in enumerate(metrics)],
        colWidths=[45 * mm, 26 * mm],
        hAlign="LEFT",
    )
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D1D5DB")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([metrics_table, Spacer(1, 8)])

    story.append(Paragraph("Operator Ranking", section_style))
    ranking_data = [[
        Paragraph("#", header_style),
        Paragraph("Operator", header_style),
        Paragraph("Picked", header_style),
        Paragraph("Successful deals", header_style),
        Paragraph("Conversion", header_style),
    ]]
    for idx, row in enumerate(ranking, start=1):
        picked = int(row.get("picked_clients") or 0)
        deals = int(row.get("successful_deals") or 0)
        conversion = f"{round((deals / picked) * 100)}%" if picked else "0%"
        ranking_data.append([
            Paragraph(str(idx), body_style),
            Paragraph(normalize_id(row.get("operator")) or "Unassigned", body_style),
            Paragraph(str(picked), right_style),
            Paragraph(str(deals), right_style),
            Paragraph(conversion, right_style),
        ])
    if len(ranking_data) == 1:
        ranking_data.append(["-", Paragraph("No operator activity yet.", body_style), "0", "0", "0%"])

    ranking_table = Table(ranking_data, colWidths=[12 * mm, 78 * mm, 28 * mm, 38 * mm, 30 * mm], repeatRows=1)
    ranking_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), bold_font),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([ranking_table, Spacer(1, 8)])

    story.append(Paragraph("Client And Deal Details", section_style))
    client_data = [[
        Paragraph("Client", header_style),
        Paragraph("Platform", header_style),
        Paragraph("Operator", header_style),
        Paragraph("Stage", header_style),
        Paragraph("Deal", header_style),
        Paragraph("Value", header_style),
        Paragraph("Last note / message", header_style),
    ]]
    stage_label = {"new": "New", "qualified": "Qualified", "negotiation": "Negotiation", "won": "Won", "lost": "Lost"}
    for row in clients:
        deal = "Won" if row.get("successful_deal") else "-"
        client_data.append([
            Paragraph(normalize_id(row.get("client")) or "-", body_style),
            Paragraph(normalize_id(row.get("platform")) or "-", body_style),
            Paragraph(normalize_id(row.get("operator")) or "Unassigned", body_style),
            Paragraph(stage_label.get(normalize_id(row.get("stage")).lower(), normalize_id(row.get("stage")) or "-"), body_style),
            Paragraph(deal, body_style),
            Paragraph(normalize_id(row.get("price")) or "-", body_style),
            Paragraph(normalize_id(row.get("last_message"))[:220] or "-", body_style),
        ])
    if len(client_data) == 1:
        client_data.append(["-", "-", "-", "-", "-", "-", Paragraph("No clients to report.", body_style)])

    client_table = Table(
        client_data,
        colWidths=[36 * mm, 24 * mm, 42 * mm, 27 * mm, 18 * mm, 24 * mm, 92 * mm],
        repeatRows=1,
    )
    client_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), bold_font),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(client_table)

    def decorate(canvas, doc_obj):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#E5E7EB"))
        canvas.line(14 * mm, 12 * mm, page_size[0] - 14 * mm, 12 * mm)
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawString(14 * mm, 7 * mm, "Instaagent operator performance report")
        canvas.drawRightString(page_size[0] - 14 * mm, 7 * mm, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def instagram_processed_message_state_key(message_id: str) -> str:
    message_id = normalize_id(message_id)
    return f"instagram_processed_message:{message_id}" if message_id else ""


def claim_instagram_message_processing(business_id: str, message_id: str, customer_id: str = "", channel: str = "dm") -> bool:
    business_id = normalize_id(business_id)
    state_key = instagram_processed_message_state_key(message_id)
    if not business_id or not state_key:
        return False
    state_value = {
        "message_id": normalize_id(message_id),
        "customer_id": normalize_id(customer_id),
        "channel": normalize_id(channel),
        "status": "processing",
        "claimed_at": datetime.utcnow().isoformat(),
    }
    try:
        supabase.table("dashboard_workspace_state").insert({
            "business_id": business_id,
            "state_key": state_key,
            "state_value": state_value,
            "updated_by": "instagram_bot",
        }).execute()
        return True
    except Exception as exc:
        log("Could not claim Instagram message processing", {"business_id": business_id, "message_id": message_id, "error": str(exc)})

    fallback = WORKSPACE_STATE_FALLBACK.get(business_id) or {}
    if state_key in fallback:
        return False
    return False


def mark_instagram_processed_message(business_id: str, message_id: str, customer_id: str = "", channel: str = "dm", status: str = "processed"):
    business_id = normalize_id(business_id)
    state_key = instagram_processed_message_state_key(message_id)
    if not business_id or not state_key:
        return
    state_value = {
        "message_id": normalize_id(message_id),
        "customer_id": normalize_id(customer_id),
        "channel": normalize_id(channel),
        "status": normalize_id(status) or "processed",
        "processed_at": datetime.utcnow().isoformat(),
    }
    try:
        upsert_workspace_state(business_id, state_key, state_value)
    except Exception as exc:
        log("Could not mark Instagram processed message", {"business_id": business_id, "message_id": message_id, "error": str(exc)})


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


def sales_agent_conversation_id(
    platform: str,
    business_id: str,
    channel: str,
    customer_id: str,
    chat_id: str = "",
) -> str:
    platform = normalize_id(platform).lower()
    business_id = normalize_id(business_id)
    channel = standard_channel(platform, channel)
    scope = conversation_scope(platform, channel, normalize_id(customer_id), normalize_id(chat_id))
    if not platform or not business_id or not scope:
        return ""
    return f"{platform}::{business_id}::{channel}::{scope}"


def sales_agent_recent_messages(rows: list[dict]) -> list[dict]:
    messages = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        messages.append(
            {
                "direction": normalize_id(row.get("direction")).lower(),
                "content": normalize_id(row.get("content")),
                "media_type": normalize_id(row.get("media_type")).lower(),
                "created_at": normalize_id(row.get("created_at")),
            }
        )
    return messages


def write_ai_action_fallback(action: dict):
    business_id = normalize_id(action.get("business_id"))
    if not business_id:
        return
    state = get_workspace_state(business_id)
    bucket = state.get("ai_actions_recent") or {}
    items = bucket.get("items") if isinstance(bucket, dict) else []
    if not isinstance(items, list):
        items = []
    items = [action] + items
    upsert_workspace_state(
        business_id,
        "ai_actions_recent",
        {"items": items[:200]},
        updated_by="sales_agent",
    )


def record_sales_agent_action(
    *,
    business: dict,
    platform: str,
    channel: str,
    customer_id: str,
    action_type: str,
    input_message: str,
    decision: dict = None,
    reply_sent: str = "",
    tool_used: str = "",
):
    try:
        payload = build_ai_action(
            business_id=(business or {}).get("id", ""),
            customer_id=customer_id,
            platform=platform,
            channel=channel,
            action_type=action_type,
            input_message=input_message,
            ai_decision=decision or {},
            confidence=(decision or {}).get("confidence"),
            tool_used=tool_used,
            reply_sent=reply_sent,
            handoff_required=bool(((decision or {}).get("handoff") or {}).get("handoff_required")),
        )
        save_ai_action(supabase, payload, fallback_writer=write_ai_action_fallback)
    except Exception as exc:
        log("Could not record sales agent action", str(exc))


def sync_sales_agent_workspace_indexes(
    *,
    business_id: str,
    conversation_id: str,
    lead_state: dict,
):
    business_id = normalize_id(business_id)
    conversation_id = normalize_id(conversation_id)
    if not business_id or not conversation_id:
        return

    state = get_workspace_state(business_id)
    lead_stages = dict(_safe_state_dict(state.get("lead_stages")))
    lead_scores = dict(_safe_state_dict(state.get("lead_scores")))
    lead_reasons = dict(_safe_state_dict(state.get("lead_reasons")))
    needs_human = dict(_safe_state_dict(state.get("needs_human")))

    lead_stages[conversation_id] = normalize_id(lead_state.get("stage") or "new").lower()
    lead_scores[conversation_id] = int(lead_state.get("score") or lead_state.get("lead_score") or 0)
    lead_reasons[conversation_id] = {
        "summary": normalize_id(lead_state.get("qualification_summary")),
        "reasons": lead_state.get("score_reasons") if isinstance(lead_state.get("score_reasons"), list) else [],
        "intent": normalize_id(lead_state.get("primary_intent")),
        "updated_at": normalize_id(lead_state.get("updated_at") or lead_state.get("last_message_at")),
    }
    needs_human[conversation_id] = {
        "required": bool(lead_state.get("handoff_required")),
        "reason": normalize_id(lead_state.get("handoff_reason")),
        "priority": normalize_id(lead_state.get("handoff_priority")),
        "manager_note": normalize_id(lead_state.get("manager_note")),
        "updated_at": normalize_id(lead_state.get("updated_at") or lead_state.get("last_message_at")),
    }

    upsert_workspace_state(business_id, "lead_stages", lead_stages, updated_by="sales_agent")
    upsert_workspace_state(business_id, "lead_scores", lead_scores, updated_by="sales_agent")
    upsert_workspace_state(business_id, "lead_reasons", lead_reasons, updated_by="sales_agent")
    upsert_workspace_state(business_id, "needs_human", needs_human, updated_by="sales_agent")


def upsert_customer_lead_record(
    *,
    business_id: str,
    platform: str,
    channel: str,
    customer_id: str,
    lead_state: dict,
):
    try:
        payload = {
            "business_id": normalize_id(business_id),
            "platform": normalize_id(platform).lower(),
            "channel": standard_channel(platform, channel),
            "customer_id": normalize_id(customer_id),
            "customer_name": normalize_id(lead_state.get("customer_name")),
            "phone": normalize_phone_number(lead_state.get("phone")),
            "product_interest": normalize_id(lead_state.get("product_interest")),
            "stage": normalize_id(lead_state.get("stage") or "new").lower(),
            "score": int(lead_state.get("score") or lead_state.get("lead_score") or 0),
            "handoff_required": bool(lead_state.get("handoff_required")),
            "handoff_reason": normalize_id(lead_state.get("handoff_reason")),
            "qualification_summary": normalize_id(lead_state.get("qualification_summary")),
            "state": lead_state,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        supabase.table("customer_leads").upsert(
            payload,
            on_conflict="business_id,platform,channel,customer_id",
        ).execute()
    except Exception:
        pass


def create_handoff_operator_task_once(business_id: str, conversation_id: str, lead_state: dict):
    business_id = normalize_id(business_id)
    conversation_id = normalize_id(conversation_id)
    if not business_id or not conversation_id or not lead_state.get("handoff_required"):
        return
    state = get_workspace_state(business_id)
    task_index = dict(_safe_state_dict(state.get("handoff_tasks")))
    if task_index.get(conversation_id):
        return

    customer = normalize_id(lead_state.get("customer_name")) or normalize_id(lead_state.get("customer_id")) or "Customer"
    stage = normalize_id(lead_state.get("stage_label") or lead_state.get("stage") or "Lead")
    score = int(lead_state.get("score") or 0)
    reason = normalize_id(lead_state.get("handoff_reason")) or "review required"
    text = f"{stage}: {customer} needs human attention. Score {score}. Reason: {reason}."
    try:
        append_operator_task(
            business_id=business_id,
            text=text,
            recipients=["*"],
            assign_mode="all",
            created_by="sales_agent",
        )
        task_index[conversation_id] = {
            "created_at": datetime.utcnow().isoformat() + "Z",
            "reason": reason,
        }
        upsert_workspace_state(business_id, "handoff_tasks", task_index, updated_by="sales_agent")
    except Exception as exc:
        log("Could not create handoff operator task", str(exc))


def run_sales_agent_for_inbound(
    *,
    business: dict,
    platform: str,
    customer_id: str,
    channel: str,
    message_text: str,
    message_id: str = "",
    customer_name: str = "",
    chat_id: str = "",
    media_type: str = "",
    media_match: dict = None,
    recent_rows: list = None,
    existing_lead_state: dict = None,
) -> dict:
    business = business or {}
    business_id = normalize_id(business.get("id"))
    platform = normalize_id(platform).lower()
    channel = standard_channel(platform, channel)
    customer_id = normalize_id(customer_id)
    if not business_id or not platform or not customer_id:
        return {}

    existing_state = normalize_lead_state(existing_lead_state or get_customer_lead_state(platform, business_id, customer_id, channel))
    rows = recent_rows if recent_rows is not None else get_recent_platform_message_rows(platform, business, customer_id, channel, limit=20)
    decision = run_agent_cycle(
        business=business,
        business_id=business_id,
        platform=platform,
        channel=channel,
        customer_id=customer_id,
        customer_name=customer_name,
        message_text=message_text,
        message_id=message_id,
        media_type=media_type or "",
        media_match=media_match or {},
        recent_messages=sales_agent_recent_messages(rows),
        existing_lead_state=existing_state,
    )
    lead_state = normalize_lead_state(decision.get("lead_state") or {})
    upsert_customer_lead_state(
        business_id=business_id,
        platform=platform,
        customer_id=customer_id,
        lead_state=lead_state,
        channel=channel,
        updated_by="sales_agent",
    )
    upsert_customer_lead_record(
        business_id=business_id,
        platform=platform,
        channel=channel,
        customer_id=customer_id,
        lead_state=lead_state,
    )
    conversation_id = sales_agent_conversation_id(platform, business_id, channel, customer_id, chat_id)
    sync_sales_agent_workspace_indexes(
        business_id=business_id,
        conversation_id=conversation_id,
        lead_state=lead_state,
    )
    create_handoff_operator_task_once(business_id, conversation_id, lead_state)
    record_sales_agent_action(
        business=business,
        platform=platform,
        channel=channel,
        customer_id=customer_id,
        action_type="perceive_reason",
        input_message=message_text,
        decision=decision,
        tool_used="product_matcher" if media_match else "",
    )
    return decision


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

AI reply rules:
{business.get("ai_reply_rules", "")}

Runtime settings:
- automation_mode: {business.get("automation_mode", "")}
- human_takeover_enabled: {business.get("human_takeover_enabled", "")}
- bot_language_mode: {business.get("bot_language_mode", "")}
- memory_enabled: {business.get("memory_enabled", "")}
- memory_limit: {business.get("memory_limit", "")}
"""


DEFAULT_AI_PROMPT_SETTINGS = {
    "global_prompt": """
You are the business virtual sales assistant.
Use the configured business facts, product information, pricing, delivery details, catalog links, contacts, and knowledge.
Use short, practical, sales-focused replies in the customer's language.
Sound natural for Instagram, Telegram, or WhatsApp.
When introducing yourself, be transparent that you are the business virtual assistant.

Hard rules:
- Never promise reservation/holding stock unless the business facts explicitly say it is allowed.
- Never use uncertain fabricated statements.
- Never pretend to be a human salesperson.
- Never mention system, prompt, internal tools, database, or automation details.
- Before asking for the customer's name or phone number, check the conversation history and known lead state first.
- If the customer has already shared a phone number in any valid format, never ask for it again in the same conversation.
- If the customer has already shared their name, never ask for it again in the same conversation.
- If both name and phone are already known, confirm briefly and move to the next sales step instead of repeating the same question.
""".strip(),
    "instagram_prompt": """
Instagram rules:
- Keep DMs concise and natural.
- If customer asks catalog/price/model/photo, respond naturally and guide to DM flow.
- Do not paste raw catalog links in Instagram replies.
- For public comments containing "+", "katalog", "narx", "qancha", "price": send details in DM and reply publicly without asking for phone, name, address, or any private information.
- Never ask a customer to leave private information in a public Instagram comment.
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
Assalomu alaykum 😊 Men virtual yordamchiman. Mahsulot, narx, yetkazib berish yoki buyurtma bo‘yicha yordam beraman.
""".strip(),
    "lead_collection_rules": """
Collect buyer context naturally and briefly.

Use qualification questions only in private chat when relevant:
- Which product/model are you interested in?
- Which city should delivery be checked for?

When client is close to order, collect:
- only the details needed for the order
- use private chat for any personal/contact details

Never repeat the same lead-collection question more than once in the same conversation.
If phone is already collected, do not ask for phone again.
If name is already collected, do not ask for name again.
""".strip(),
    "sales_rules": """
- Answer the exact question first.
- Keep replies short and comfortable: usually 1-3 short sentences.
- Keep tone samimiy and complete, not robotic.

Product/category defaults:
- Use only the categories and product facts configured for this business.
- Recommend products only when the business facts support the recommendation.
- Mention limited availability only when configured or when availability must be confirmed.

Pricing and order policy:
- For price questions, use configured prices when available.
- If exact price is missing, say it should be confirmed and ask one useful follow-up question.
- Use minimum order and wholesale/retail rules only when configured.

Location and delivery policy:
- Use configured address, location, delivery, and working-hours facts only.

Payment and warranty policy:
- Use configured payment and warranty facts only.
- If payment or warranty details are missing, ask for contact details or hand off to a manager.

Objection handling:
- If "qimmat": emphasize quality value briefly.
- If "keyin olaman": ask polite follow-up about purchase timing.
- If comparing other stores: stay respectful, no pressure.

Forbidden phrases:
- Do not reject a sales lead unless the business facts require it.
""".strip(),
    "handoff_rules": """
Handoff immediately when:
- customer says they want wholesale/optom
- customer asks for final exact deal terms
- customer is angry/frustrated
- payment/contract specifics are requested

Handoff closing line:
- "Direktda yozing, menejerimiz yordam beradi."

If the customer already sent a phone number, do not use the full name+phone request again.
Ask only for the missing field.

Do not invent information before handoff.
""".strip(),
}


AI_PROMPT_SETTING_FIELDS = set(DEFAULT_AI_PROMPT_SETTINGS.keys())


GENERIC_RESPONSE_GUARDRAILS = """
Business Q&A policy. Always enforce these rules even if saved prompt settings say otherwise.

Business-only scope:
- Only answer questions about this business, its products/services, catalog, prices, orders, delivery, payment, address, warranty, and manager handoff.
- If the customer asks about unrelated topics, do not answer that topic.
- For unrelated topics, reply briefly in the customer's language and offer catalog or manager help.

Sales-agent rules:
- Introduce the configured business naturally when needed.
- If introducing yourself, say you are the business virtual assistant.
- Use only configured business strengths and facts.
- Tone: samimiy, short, practical, complete enough to help the customer buy.
- Ask qualification questions naturally: name, city, phone number.
- In public comments, never ask for name, phone, address, Telegram, WhatsApp, passport, card, or other private details.
- Never ask for a phone number again if the customer already sent one in the current conversation.
- Never ask for a name again if the customer already sent one in the current conversation.
- If both name and phone are already collected, confirm briefly and continue the sale.
- Product availability should be confirmed, never invented.
- Never pretend to be a human salesperson.
- Never say stock is reserved or will be reserved unless configured.
- Never invent price, discount, stock, delivery time, payment terms, or availability.
- Exact price should not be invented. If asked price and it is missing, say it should be confirmed.
- Do not claim prices changed or will change unless configured.
- Use wholesale/retail/minimum-order rules only when configured.
- For qop/size questions, use the configured qop/size rule from Business facts. Do not invent size composition.
- Use configured address and delivery process only.
- Payment: move the customer to private chat or a manager; do not request private details in public comments.
- When customer asks for photo/video/catalog, answer warmly with one light smile/emoji-style touch; do not over-explain.
- Reply separately to each commenter; do not combine multiple customers into one response.
- Sticker-only/simple reactions: answer with a simple friendly emoji/sticker-style short reply, not a sales paragraph.
- If "qimmat": acknowledge and position value based on configured quality facts.
- If "keyin olaman" or silent follow-up: ask when they plan to buy.
- If comparing with another shop: be respectful; no pressure.
- Buying signs: asks for card, cargo, exact order flow, or says wholesale/optom.
- Handoff immediately for optom intent, angry/norozi customer, payment details, or exact final order terms.
- Handoff line: "Direktda yozing, menejerimiz yordam beradi."
- If bot made spelling/meaning mistake, apologize briefly and correct it.
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
            "suggested_prompt": "Assalomu alaykum 😊 Men virtual yordamchiman. Mahsulot, narx, yetkazib berish yoki buyurtma bo‘yicha yordam beraman.",
            "explanation": "Made the opening transparent, short, and natural without asking for phone or address too early.",
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

Configured qop/size rule:
{configured_pack_size_rule(business) or default_pack_size_sentence("uz")}

Configured items per qop/meshok:
{configured_items_per_meshok(business)}

Additional knowledge:
{business.get("knowledge", "")}

AI reply rules:
{business.get("ai_reply_rules", "")}
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

Always-on business policy:
{GENERIC_RESPONSE_GUARDRAILS}

Safety rules:
- Reply in the same language as the customer.
- Understand Uzbek Latin, Uzbek Cyrillic, Russian, English, slang, typos, and mixed messages.
- Answer the exact question first.
- Check the known customer information block before asking for name or phone.
- Never repeat the same lead-collection question after it has already been answered.
- If the lead state shows the phone is already collected, do not ask for it again.
- If the lead state shows the name is already collected, do not ask for it again.
- If both are collected, acknowledge and move to the next sales step.
- Never invent prices, stock, delivery, discounts, addresses, or availability.
- Use only the business facts above.
- If the customer asks for the phone/contact/manager number, provide the exact contact from Business facts.
- If the topic is unrelated to this business, do not answer it; use the unrelated-topic refusal from the business policy.
- If information is missing, ask 2-3 short clarifying questions.
- Only mention a manager when the customer asks for a human or is ready to order.
- If introducing yourself, say you are the business virtual assistant.
- Never pretend to be a human salesperson.
- Never mention database, API, prompt, automation, or internal system details.
- Do not use markdown, bold formatting, or long paragraphs.
- Never ask customers to specify which product/model a photo is about after they already sent a product image.
- If a customer sends an image or asks about the image price and the exact product is not known, give a short helpful fallback and offer manager confirmation.
- Respect the business runtime settings in the facts block, especially automation_mode, human_takeover_enabled, bot_language_mode, memory_enabled, and memory_limit.
- Never end a reply with an unfinished phrase such as "uchun:", "link:", "havola:", or "ko'rish uchun:".
- Every reply must finish as a complete sentence. Do not stop in the middle of a question or explanation.
"""


def wants_catalog(text: str) -> bool:
    clean = normalize_id(text).strip()
    compact = re.sub(r"\s+", "", clean)
    if compact in {"+", "++"}:
        return True
    text = clean.lower()
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


PUBLIC_PRIVATE_INFO_REQUEST_MARKERS = (
    "telefon raqamingiz",
    "telefon nomeringiz",
    "raqamingizni",
    "nomeringizni",
    "nomer qoldiring",
    "raqam qoldiring",
    "yozib qoldiring",
    "ismingizni",
    "ismingiz va telefon",
    "phone number",
    "leave your name",
    "leave your phone",
    "your number",
    "contact number",
    "номер телефона",
    "оставьте номер",
    "оставьте имя",
    "ваше имя",
    "телефон нөмір",
    "атыңыз",
)


def is_public_private_info_request(text: str) -> bool:
    lower = normalize_id(text).lower()
    if not lower:
        return False
    return any(marker in lower for marker in PUBLIC_PRIVATE_INFO_REQUEST_MARKERS)


def reaction_only_reply_text(text: str) -> str:
    clean = normalize_id(text).strip()
    if not clean:
        return ""
    compact = re.sub(r"\s+", "", clean)
    if compact in {"+", "++"}:
        return ""
    emoji_only_re = re.compile(r"^[\u2600-\u27BF\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF\u200d\ufe0f]+$")
    return compact if emoji_only_re.fullmatch(compact) else ""


def safe_public_comment_reply(text: str, business: dict = None) -> str:
    reaction_reply = reaction_only_reply_text(text)
    if reaction_reply:
        return reaction_reply

    reply = complete_sentence_reply(remove_urls(text), limit=1000)
    if reply and not is_public_private_info_request(reply):
        return reply

    business_name = normalize_id((business or {}).get("business_name"))
    if business_name:
        return "Ma'lumotni direktga yubordik. Xabaringiz uchun rahmat."
    return "Ma'lumotni direktga yubordik. Xabaringiz uchun rahmat."


def is_conversation_finished_message(text: str) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    compact = re.sub(r"[\s.!?。！？,;:()\\-]+", "", s)
    exact_markers = {
        "ok", "okay", "okey", "kk",
        "hop", "хоп", "xo'p", "xop", "хорошо",
        "rahmat", "raxmat", "спасибо", "thanks", "thankyou",
        "tushunarli", "понятно", "ясно",
        "boldi", "bo'ldi", "bo‘ldi", "всё", "все",
        "kerakmas", "kerakemas", "не надо", "nenado",
        "stop", "bas", "хватит",
    }
    if compact in {re.sub(r"[\s.!?。！？,;:()\\-]+", "", item) for item in exact_markers}:
        return True
    finish_phrases = [
        "boshqa savol yo'q",
        "boshqa savolim yo'q",
        "kerak emas rahmat",
        "hozircha kerak emas",
        "that's all",
        "no more questions",
        "don't message me",
        "do not message me",
        "не пишите",
        "больше не нужно",
        "вопросов нет",
    ]
    return any(phrase in s for phrase in finish_phrases)


def is_price_question(text: str) -> bool:
    text = normalize_id(text).lower()
    if not text:
        return False
    return any(k in text for k in [
        "narx", "narxi", "nechpul", "necha pul", "qancha", "kancha",
        "цена", "сколько", "сколько стоит", "price", "how much", "cost",
        "баға", "бағасы", "қанша",
    ])


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


def is_forwarded_instagram_share_placeholder(text: str) -> bool:
    return normalize_id(text).strip().lower() in {
        "🔁 forwarded post",
        "🔁 forwarded reel",
    }


def contains_forbidden_product_photo_question(text: str) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    s = (
        s.replace("‘", "'")
        .replace("’", "'")
        .replace("`", "'")
        .replace("o'", "o'")
    )
    compact = re.sub(r"\s+", " ", s).strip()
    blocked_phrases = [
        "siz qaysi mahsulot yoki model haqida foto so'rayapsiz",
        "siz qaysi mahsulot yoki model haqida rasm so'rayapsiz",
        "qaysi mahsulot yoki model haqida foto so'rayapsiz",
        "qaysi mahsulot yoki model haqida rasm so'rayapsiz",
        "qaysi mahsulot yoki model haqida",
    ]
    if any(phrase in compact for phrase in blocked_phrases):
        return True
    return bool(re.search(r"qaysi\s+mahsulot\s+yoki\s+model.*(foto|rasm|so'?ray)", compact))


def generic_price_fallback_reply(user_text: str, business: dict = None) -> str:
    lang = detect_customer_language(user_text)
    if lang == "en":
        return "Which model do you need? I will tell you the price."
    if lang == "ru":
        return "Какая модель вам нужна? Я скажу цену."
    if lang == "kk":
        return "Қай модель керек? Бағасын айтып беремін."
    return "Qaysi model kerak? Narxini aytaman."


def is_wholesale_inquiry(text: str) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    markers = [
        "optom", "оптом", "опт", "wholesale", "ulgurji", "ulguji",
        "цены оптом", "оптов", "оптовый", "оптовая",
        "ulgurji narx", "optom narx", "wholesale price",
    ]
    return any(marker in s for marker in markers)


def is_generic_media_wholesale_inquiry(
    user_text: str,
    media_type: str = "",
    post_permalink: str = "",
    post_media_type: str = "",
) -> bool:
    if not is_wholesale_inquiry(user_text):
        return False
    media_type = normalize_id(media_type).lower()
    post_media_type = normalize_id(post_media_type).lower()
    permalink = normalize_id(post_permalink).lower()
    return (
        media_type in {"video", "file"}
        or "video" in post_media_type
        or "reel" in post_media_type
        or "/reel/" in permalink
    )


def build_generic_wholesale_intro_reply(user_text: str, business: dict = None) -> str:
    has_catalog = bool(get_catalog_link(business or {}))
    lang = detect_customer_language(user_text)
    if lang == "en":
        base = (
            "Hello! We sell wholesale in USD. Minimum order is from 1 qop/meshok per model. "
            "Send a photo, screenshot, or model code, and I will tell you the exact price."
        )
        return base + (" If you want, I can also send the catalog." if has_catalog else "")
    if lang == "ru":
        base = (
            "Здравствуйте! Мы продаём оптом в USD. Минимальный заказ — от 1 qop/мешка на модель. "
            "Отправьте фото, стоп-кадр или код модели, и я сразу скажу точную цену."
        )
        return base + (" Если хотите, могу сразу отправить каталог." if has_catalog else "")
    if lang == "kk":
        base = (
            "Сәлеметсіз бе! Біз USD бойынша көтерме сатамыз. Ең аз тапсырыс — бір модельден 1 qop/мешок. "
            "Фото, стоп-кадр немесе модель кодын жіберіңіз, нақты бағасын бірден айтамын."
        )
        return base + (" Қаласаңыз, каталогты да жіберемін." if has_catalog else "")
    base = (
        "Assalomu alaykum! Biz USDda ulgurji sotamiz. Minimal buyurtma — 1 modeldan 1 qop/meshok. "
        "Foto, stop-kadr yoki model kodini yuboring, aniq narxini darrov aytaman."
    )
    return base + (" Xohlasangiz, katalogni ham yuboraman." if has_catalog else "")


def product_media_price_fallback_reply(user_text: str, business: dict = None) -> str:
    lang = detect_customer_language(user_text)
    if lang == "en":
        return "Thanks. Send a clearer photo or the model code, and I will tell you the price."
    if lang == "ru":
        return "Спасибо. Отправьте фото чётче или код модели, и я скажу цену."
    if lang == "kk":
        return "Рахмет. Анығырақ фото не модель кодын жіберіңіз, бағасын айтамын."
    return "Rahmat. Aniqroq rasm yoki model kodini yuboring, narxini aytaman."


def business_products_summary(business: dict = None, limit: int = 4) -> str:
    business = business or {}
    raw = normalize_id(business.get("products"))
    if not raw:
        return ""

    parts = []
    for chunk in re.split(r"[,;\n/]+", raw):
        clean = re.sub(r"\s+", " ", normalize_id(chunk)).strip(" .:-")
        if clean and clean.lower() not in {item.lower() for item in parts}:
            parts.append(clean)
        if len(parts) >= limit:
            break
    return ", ".join(parts)


def replacement_for_forbidden_product_photo_question(user_text: str = "", business: dict = None) -> str:
    lang = detect_customer_language(user_text)
    if lang == "en":
        if is_price_question(user_text):
            return "Thanks. Send a clearer photo or the model code, and I will tell you the price."
        return "Thanks. Which model are you interested in?"
    if lang == "ru":
        if is_price_question(user_text):
            return "Спасибо. Отправьте фото чётче или код модели, и я скажу цену."
        return "Спасибо. Какая модель вас интересует?"
    if lang == "kk":
        if is_price_question(user_text):
            return "Рахмет. Анығырақ фото не модель кодын жіберіңіз, бағасын айтамын."
        return "Рахмет. Қай модель қызықтырады?"
    if is_price_question(user_text):
        return "Rahmat. Aniqroq rasm yoki model kodini yuboring, narxini aytaman."
    return "Rahmat. Qaysi model kerak?"


def get_sales_phone(business: dict) -> str:
    return normalize_id(
        (business or {}).get("sales_phone")
        or os.getenv("SALES_PHONE", "")
        or os.getenv("CONTACT_PHONE", "")
        or os.getenv("BUSINESS_PHONE", "")
        or os.getenv("MILANA_SALES_PHONE", "")
    )


def wants_business_phone_number(text: str) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False

    # If the customer is leaving their own phone number, do not answer with ours.
    if re.search(r"\b(?:\+?998)?\s*\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b", s):
        return False

    phone_markers = [
        "telefon", "tel", "phone", "phone number", "contact", "kontakt",
        "nomer", "номер", "телефон", "контакт", "raqam", "рақам",
    ]
    owner_markers = [
        "sizni", "sizning", "raqamingiz", "nomeringiz", "telefoningiz",
        "menejer", "menedjer", "manager", "admin", "админ", "менеджер",
        "operator", "sales", "sotuvchi",
    ]
    request_markers = [
        "bering", "yuboring", "jo'nating", "jonating", "bormi", "bor mi",
        "kerak", "ayting", "yozing", "бер", "дайте", "номер есть",
        "send", "give", "share", "can i call", "call you",
    ]

    has_phone_word = any(marker in s for marker in phone_markers)
    has_owner_word = any(marker in s for marker in owner_markers)
    has_request_word = any(marker in s for marker in request_markers)

    direct_patterns = [
        r"\b(menejer|menedjer|manager|admin|operator)\s+(raqam|nomer|telefon)",
        r"\b(raqam|nomer|telefon)\w*\s+(ber|yubor|jo'?nat|bor|bormi)",
        r"\b(phone|contact)\s+(number|details)?\s*(please|send|give|share)?",
        r"(номер|телефон|контакт).*(дайте|есть|можно|менеджер)",
    ]
    return (has_phone_word and (has_owner_word or has_request_word)) or any(
        re.search(pattern, s) for pattern in direct_patterns
    )


def sales_phone_reply(user_text: str, business: dict) -> str:
    phone = get_sales_phone(business)
    if not phone:
        return ""

    lang = detect_customer_language(user_text)
    if lang == "en":
        return f"You can contact our manager at this number: {phone}."
    if lang == "ru":
        return f"С менеджером можно связаться по этому номеру: {phone}."
    if lang == "kk":
        return f"Менеджермен осы нөмір арқылы байланыса аласыз: {phone}."
    return f"Menejerimiz bilan shu raqam orqali bog'lanishingiz mumkin: {phone}."


def wants_deal_handoff(text: str) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    markers = [
        "payment", "pay", "prepayment", "invoice", "contract", "agreement", "manager",
        "оплата", "оплатить", "счет", "инвойс", "договор", "менеджер",
        "to'lov", "tolov", "oplata", "shartnoma", "hisob-faktura", "invoice", "menejer",
        "төлем", "шарт", "келісімшарт", "менеджер",
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
        "nechpul", "nechi", "pul", "shu", "bo'lad", "bolad", "qop",
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


def business_scope_terms(business: dict = None) -> set[str]:
    business = business or {}
    terms = set()
    for field in (
        "business_name",
        "business_type",
        "products",
        "prices",
        "delivery_info",
        "faq",
        "catalog_link",
        "sales_phone",
        "knowledge",
    ):
        value = normalize_id(business.get(field))
        for word in re.findall(r"[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ0-9']{3,}", value.lower()):
            terms.add(word)
    return terms


def has_strong_business_sales_context(text: str, business: dict = None) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    if mentions_catalog(s):
        return True
    business_terms = business_scope_terms(business)
    if business_terms and any(term in s for term in business_terms):
        return True
    markers = [
        "product", "products", "service", "services", "mahsulot", "mahsulotlar", "товар", "товары",
        "model", "модель", "rang", "color", "цвет", "size", "razmer", "размер",
        "sifat", "quality", "качество", "pack", "bag", "qop", "meshok", "quti",
        "optom", "optima", "ulgurji", "wholesale", "оптом", "опт",
        "dostavka", "delivery", "yetkaz", "yetqaz", "доставка", "pochta", "почта",
        "cargo", "kargo", "карго", "manzil", "address", "адрес", "qayerdasiz",
        "where are you", "where located", "location", "lokatsiya", "локация",
        "telefon", "phone number", "nomer", "raqam", "номер", "связаться",
        "menejer", "manager", "менеджер", "admin", "админ",
        "brak", "defect", "warranty", "garantiya", "гарантия", "qaytar",
        "narx", "narxi", "nechpul", "necha pul", "qancha", "kancha", "price",
        "qimmat", "arzon", "expensive", "cheap", "дорого", "дешево",
        "bor", "bormi", "mavjud", "available", "есть", "в наличии",
        "hamkorlik", "partnership", "сотрудничество", "ish vaqti", "working hours",
    ]
    return any(marker in s for marker in markers)


def has_business_sales_context(text: str, business: dict = None) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    if has_strong_business_sales_context(s, business) or wants_catalog(s) or wants_deal_handoff(s):
        return True
    generic_sales_markers = [
        "kerak", "need", "want", "хочу", "interested", "qiziq", "интерес",
        "tanlash", "choose", "выбрать", "ko'rsat", "korsat", "show me", "покажите",
    ]
    return any(marker in s for marker in generic_sales_markers)


def is_obviously_unrelated_topic(text: str, business: dict = None) -> bool:
    s = normalize_id(text).lower()
    if not s:
        return False
    if is_greeting_only(s) or is_low_signal_message(s):
        return False
    if has_strong_business_sales_context(s, business):
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

    if has_business_sales_context(s, business):
        return False

    return False


def unrelated_topic_reply(text: str, business: dict = None) -> str:
    if not is_obviously_unrelated_topic(text, business):
        return ""
    lang = detect_customer_language(text)
    business_name = normalize_id((business or {}).get("business_name")) or "this business"
    if lang == "en":
        return f"Sorry, I can only help with {business_name} products/services, catalog, prices, and orders. Do you need the catalog or should I connect you with a manager?"
    if lang == "ru":
        return f"Извините, я могу помочь только с товарами/услугами {business_name}, каталогом, ценами и заказом. Нужен каталог или связать вас с менеджером?"
    if lang == "kk":
        return f"Кешіріңіз, мен тек {business_name} тауарлары/қызметтері, каталог, баға және тапсырыс бойынша көмектесе аламын. Каталог керек пе әлде менеджермен байланыстырайын ба?"
    return f"Kechirasiz, men faqat {business_name} mahsulotlari/xizmatlari, katalog, narx va buyurtma bo'yicha yordam bera olaman. Katalog kerakmi yoki menejer bilan bog'laymi?"


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


def complete_sentence_reply(text: str, limit: int = 1000) -> str:
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


LEAD_PHONE_ASK_MARKERS = (
    "telefon raqamingizni",
    "telefon raqamingiz",
    "telefon nomeringizni",
    "raqamingizni yozib qoldiring",
    "nomer qoldiring",
    "phone number",
    "leave your name and phone number",
    "please leave your name and phone number",
    "номер телефона",
    "оставьте, пожалуйста, ваше имя и номер телефона",
)


LEAD_NAME_ASK_MARKERS = (
    "ismingizni",
    "ismingiz nima",
    "ismingiz va telefon raqamingizni",
    "your name",
    "what is your name",
    "ваше имя",
    "как вас зовут",
    "атыңызды",
)


def _reply_mentions_phone_request(text: str) -> bool:
    lower = normalize_id(text).lower()
    return any(marker in lower for marker in LEAD_PHONE_ASK_MARKERS)


def _reply_mentions_name_request(text: str) -> bool:
    lower = normalize_id(text).lower()
    return any(marker in lower for marker in LEAD_NAME_ASK_MARKERS)


def lead_followup_reply(user_text: str, business: dict = None, lead_state: dict = None) -> str:
    lang = detect_customer_language(user_text)
    state = normalize_lead_state(lead_state)
    has_phone = bool(state.get("phone_collected"))
    has_name = bool(state.get("name_collected"))

    if has_phone and has_name:
        if lang == "en":
            return "Thanks, we have your details. Our manager will contact you."
        if lang == "ru":
            return "Спасибо, мы получили ваши данные. Наш менеджер свяжется с вами."
        if lang == "kk":
            return "Рақмет, мәліметтеріңізді алдық. Менеджеріміз сізбен байланысады."
        return "Rahmat, ma'lumotlaringizni oldik. Menejerimiz siz bilan bog'lanadi."

    if has_phone and not has_name:
        if lang == "en":
            return "Thanks, we got your phone number. Please leave your name too, and our manager will contact you."
        if lang == "ru":
            return "Спасибо, ваш номер мы получили. Пожалуйста, оставьте еще имя, и наш менеджер свяжется с вами."
        if lang == "kk":
            return "Рақмет, телефон нөміріңізді алдық. Атыңызды да жазып жіберсеңіз, менеджеріміз хабарласады."
        return "Rahmat, telefon raqamingizni oldik. Ismingizni ham yozib qoldirsangiz, menejerimiz siz bilan bog'lanadi."

    if has_name and not has_phone:
        if lang == "en":
            return "Thanks, we got your name. Please leave your phone number too, and our manager will contact you."
        if lang == "ru":
            return "Спасибо, ваше имя мы получили. Пожалуйста, оставьте еще номер телефона, и наш менеджер свяжется с вами."
        if lang == "kk":
            return "Рақмет, атыңызды алдық. Телефон нөміріңізді де жіберсеңіз, менеджеріміз хабарласады."
        return "Rahmat, ismingizni oldik. Telefon raqamingizni ham yozib qoldirsangiz, menejerimiz siz bilan bog'lanadi."

    return ""


def enforce_lead_reply_guardrails(reply_text: str, user_text: str, business: dict = None, lead_state: dict = None) -> str:
    reply = normalize_id(reply_text)
    if not reply:
        return ""

    state = normalize_lead_state(lead_state)
    user_has_phone = bool(extract_phone_candidates(user_text))
    user_has_name = bool(extract_customer_name_candidate(user_text))
    phone_collected = bool(state.get("phone_collected") or user_has_phone)
    name_collected = bool(state.get("name_collected") or user_has_name)

    phone_request = _reply_mentions_phone_request(reply)
    name_request = _reply_mentions_name_request(reply)

    if phone_collected and phone_request:
        fallback = lead_followup_reply(user_text, business, {**state, "phone_collected": True, "name_collected": name_collected})
        if fallback:
            return fallback

    if name_collected and name_request and phone_collected:
        fallback = lead_followup_reply(user_text, business, {**state, "phone_collected": True, "name_collected": True})
        if fallback:
            return fallback

    if phone_collected and name_collected and (phone_request or name_request):
        fallback = lead_followup_reply(user_text, business, {**state, "phone_collected": True, "name_collected": True})
        if fallback:
            return fallback

    if phone_collected and not name_collected and phone_request and not name_request:
        fallback = lead_followup_reply(user_text, business, {**state, "phone_collected": True, "name_collected": False})
        if fallback:
            return fallback

    if name_collected and not phone_collected and name_request and not phone_request:
        fallback = lead_followup_reply(user_text, business, {**state, "phone_collected": False, "name_collected": True})
        if fallback:
            return fallback

    return reply


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
    return complete_sentence_reply(reply_text, limit=1000)


def catalog_card_subtitle(business: dict) -> str:
    business_name = normalize_id((business or {}).get("business_name"))
    if len(business_name) <= 22:
        return f"{business_name} katalogi tayyor." if business_name else "Katalog tayyor."
    return "Katalog tayyor. Tugmani bosing."


def catalog_template_payload(recipient: dict, business: dict, text: str = "") -> dict:
    catalog_link = get_catalog_link(business)
    business_name = normalize_id((business or {}).get("business_name")) or "Bizning katalog"
    text = clean_ai_reply_for_catalog(text, business)
    if not text:
        text = f"{business_name} katalogi shu yerda. Qaysi mahsulotlar sizni qiziqtirmoqda?"

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
                            "subtitle": catalog_card_subtitle(business),
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
    max_tokens = max(500, int(business.get("ai_max_tokens", 500) or 500))

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



def clean_sales_reply(reply_text: str, user_text: str = "", business: dict = None, lead_state: dict = None) -> str:
    user = normalize_id(user_text).lower()
    lang = detect_customer_language(user_text)
    allow_handoff = business_allows_human_handoff(business)

    if wants_deal_handoff(user_text) and allow_handoff:
        if lang == "en":
            return LEAD_CONTACT_REQUEST_EN
        if lang == "ru":
            return LEAD_CONTACT_REQUEST_RU
        if lang == "kk":
            return LEAD_CONTACT_REQUEST_KK
        return LEAD_CONTACT_REQUEST_UZ

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

    if looks_like_internal_prompt_leak(text):
        log("Prompt leak blocked", {"reply_preview": text[:300], "user_text": user_text[:120]})
        return safe_prompt_leak_fallback(user_text, business, lead_state)

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

    forced_contact_request = False

    if contains_forbidden_product_photo_question(text):
        text = replacement_for_forbidden_product_photo_question(user_text, business)

    if re.search(r"menejerimiz bilan bog'?lay|manager.*connect|connect you with our manager", text, re.IGNORECASE) and not is_price_question(user_text):
        text = LEAD_CONTACT_REQUEST_UZ if lang not in {"en", "ru", "kk"} else {
            "en": LEAD_CONTACT_REQUEST_EN,
            "ru": LEAD_CONTACT_REQUEST_RU,
            "kk": LEAD_CONTACT_REQUEST_KK,
        }.get(lang, LEAD_CONTACT_REQUEST_UZ)
        forced_contact_request = True

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
    price_ask = is_price_question(user_text)
    has_number = bool(re.search(r"\d", text))
    if price_ask and (_reply_mentions_phone_request(text) or _reply_mentions_name_request(text)):
        text = generic_price_fallback_reply(user_text, business)
        forced_contact_request = False
        has_number = bool(re.search(r"\d", text))
    if price_ask and not has_number and not forced_contact_request:
        text = generic_price_fallback_reply(user_text, business)

    if contains_forbidden_product_photo_question(text):
        text = replacement_for_forbidden_product_photo_question(user_text, business)

    # Strong language guard: if customer wrote in English but reply is not English, return safe English fallback.
    if lang == "en":
        has_cyr = bool(re.search(r"[А-Яа-яЁё]", text))
        uz_markers = ("salom", "assalomu", "alaykum", "qaysi", "mahsulot", "katalog")
        low = text.lower()
        if has_cyr or any(m in low for m in uz_markers):
            if price_ask:
                text = generic_price_fallback_reply(user_text, business)
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

    if looks_like_internal_prompt_leak(text):
        log("Prompt leak blocked after cleanup", {"reply_preview": text[:300], "user_text": user_text[:120]})
        return safe_prompt_leak_fallback(user_text, business, lead_state)

    text = complete_sentence_reply(text, limit=900)
    text = enforce_lead_reply_guardrails(text, user_text, business, lead_state)

    if text:
        return text
    lead_fallback = lead_followup_reply(user_text, business, lead_state)
    if lead_fallback:
        return lead_fallback
    if lang == "en":
        return "Understood."
    if lang == "kk":
        return "Түсіндім."
    if lang == "ru":
        return "Понял."
    return "Tushunarli 👍"


PROMPT_LEAK_MARKERS = (
    "narx bo'yicha ma'lumot",
    "if customer",
    "agar mijoz",
    "bot aniq narx aytmasin",
    "do not ask",
    "do not mention",
    "always enforce these rules",
    "internal system",
    "system prompt",
    "reply separately",
    "never mention ai",
    "suggested product answer",
)


def looks_like_internal_prompt_leak(text: str) -> bool:
    low = normalize_id(text).lower()
    if not low:
        return False

    marker_hits = sum(1 for marker in PROMPT_LEAK_MARKERS if marker in low)
    rule_line_hits = len(re.findall(r"(?:^|\n)\s*[-•]\s*(?:if|do not|never|always|agar|bot|reply|narx)", low))
    imperative_hits = len(re.findall(r"\b(?:if customer|agar mijoz|do not|never|always enforce|reply separately)\b", low))

    if marker_hits >= 1 and (rule_line_hits >= 1 or imperative_hits >= 1):
        return True
    if marker_hits >= 2:
        return True
    return False


def safe_prompt_leak_fallback(user_text: str, business: dict = None, lead_state: dict = None) -> str:
    lang = detect_customer_language(user_text)
    if is_price_question(user_text):
        return generic_price_fallback_reply(user_text, business)
    if is_greeting_only(user_text):
        if lang == "en":
            return "Hello! How can I help you today?"
        if lang == "ru":
            return "Здравствуйте! Чем могу помочь?"
        if lang == "kk":
            return "Сәлеметсіз бе! Қалай көмектесе аламын?"
        return "Assalomu alaykum 😊 Qanday yordam kerak?"

    lead_fallback = lead_followup_reply(user_text, business, lead_state)
    if lead_fallback:
        return lead_fallback

    if lang == "en":
        return "Of course. Which product are you interested in?"
    if lang == "ru":
        return "Конечно. Какой товар вас интересует?"
    if lang == "kk":
        return "Әрине. Сізді қай тауар қызықтырады?"
    return "Albatta. Sizga qaysi mahsulot kerak?"


def safe_outbound_leak_fallback(business: dict = None) -> str:
    lang = normalize_id((business or {}).get("language")).lower()
    if lang.startswith("en"):
        return "Which model do you need?"
    if lang.startswith("ru"):
        return "Какая модель вам нужна?"
    if lang.startswith("kk"):
        return "Қай модель керек?"
    return "Qaysi model kerak?"


def _safe_score(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def product_matcher_file_url(api_url: str) -> str:
    api_url = normalize_id(api_url)
    if not api_url:
        return ""
    if api_url.endswith("/api/process-media-url"):
        return api_url[:-len("/api/process-media-url")] + "/api/process-media"
    if api_url.endswith("/api/process-media"):
        return api_url
    return api_url.rstrip("/") + "/api/process-media"


def product_matcher_url_url(api_url: str) -> str:
    api_url = normalize_id(api_url)
    if not api_url:
        return ""
    if api_url.endswith("/api/process-media"):
        return api_url[:-len("/api/process-media")] + "/api/process-media-url"
    if api_url.endswith("/api/process-media-url"):
        return api_url
    return api_url.rstrip("/") + "/api/process-media-url"


def product_matcher_health_url(api_url: str) -> str:
    api_url = normalize_id(api_url)
    if not api_url:
        return ""
    if "/api/" in api_url:
        return api_url.split("/api/", 1)[0].rstrip("/") + "/health"
    return api_url.rstrip("/") + "/health"


def append_url_query(url: str, params: dict) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in (params or {}).items():
        clean_key = normalize_id(key)
        clean_value = normalize_id(value)
        if clean_key and clean_value:
            query[clean_key] = [clean_value]
    return parsed._replace(query=urlencode(query, doseq=True)).geturl()


def download_media_for_matcher(media_url: str, access_token: str = "") -> tuple[bytes, str, str]:
    media_url = normalize_id(media_url)
    if not media_url:
        raise ValueError("Empty media URL")

    limit_bytes = PRODUCT_MATCHER_MAX_MEDIA_MB * 1024 * 1024
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "*/*",
    }
    clean_token = normalize_id(access_token)
    if clean_token:
        headers["Authorization"] = f"Bearer {clean_token}"

    try:
        response = requests.get(media_url, timeout=min(PRODUCT_MATCHER_TIMEOUT_SECONDS, 30), stream=True, headers=headers)
        response.raise_for_status()
    except requests.HTTPError as exc:
        response = getattr(exc, "response", None)
        if not clean_token or response is None or response.status_code != 403:
            raise
        token_url = append_url_query(media_url, {"access_token": clean_token})
        token_headers = {key: value for key, value in headers.items() if key.lower() != "authorization"}
        response = requests.get(token_url, timeout=min(PRODUCT_MATCHER_TIMEOUT_SECONDS, 30), stream=True, headers=token_headers)
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

    filename = f"media{mimetypes.guess_extension(content_type) or '.bin'}"
    return data, filename, content_type


def build_product_match_reply(code: str, model: str, price: str, currency: str, top_score: float, business: dict = None) -> str:
    code = normalize_id(code)
    model = normalize_id(model)
    price = normalize_id(price)
    currency = normalize_id(currency)
    label = model or code or "shu model"
    pack_info = default_pack_size_sentence("uz", business=business)
    if price:
        return f"Model {label} narxi {price} {currency or '$'}. {pack_info} Nechta qop kerak?"
    return f"Model {label} bo'yicha aniqroq rasm yoki kod yuboring. {pack_info} Nechta qop kerak?"


def normalize_product_code(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9-]", "", normalize_id(value).upper())
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value


def extract_codes_from_text_local(text: str) -> list[str]:
    text = normalize_id(text)
    if not text:
        return []
    found = []
    for raw in re.findall(r"\b[A-Za-z]{1,4}-?\d{2,6}\b", text):
        code = normalize_product_code(raw)
        if code and code not in found:
            found.append(code)
    return found


def _extract_json_object_loose(text: str) -> dict:
    raw = normalize_id(text)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _get_local_catalog_rows(force_refresh: bool = False) -> list[dict]:
    now = time.time()
    cached_rows = PRODUCT_MATCHER_LOCAL_CATALOG_CACHE.get("rows") if isinstance(PRODUCT_MATCHER_LOCAL_CATALOG_CACHE, dict) else []
    loaded_at = PRODUCT_MATCHER_LOCAL_CATALOG_CACHE.get("loaded_at", 0.0) if isinstance(PRODUCT_MATCHER_LOCAL_CATALOG_CACHE, dict) else 0.0
    if not force_refresh and cached_rows and (now - float(loaded_at or 0.0)) < PRODUCT_MATCHER_LOCAL_CATALOG_CACHE_TTL_SECONDS:
        return cached_rows

    fields = "product_code,model_code,price,currency,combined_text,image_url,image_sha256,image_fingerprint,embedding_model,embedding_preview,source_pdf,page,card_index"
    try:
        res = (
            catalog_supabase
            .table(PRODUCT_MATCHER_LOCAL_CATALOG_TABLE)
            .select(fields)
            .limit(PRODUCT_MATCHER_LOCAL_FETCH_LIMIT)
            .execute()
        )
        rows = res.data if isinstance(res.data, list) else []
    except Exception as exc:
        same_database = normalize_id(CATALOG_SUPABASE_URL).rstrip("/") == normalize_id(SUPABASE_URL).rstrip("/")
        log("Local catalog fetch failed", {
            "table": PRODUCT_MATCHER_LOCAL_CATALOG_TABLE,
            "catalog_supabase_url": normalize_id(CATALOG_SUPABASE_URL).split("//")[-1].split(".")[0] if CATALOG_SUPABASE_URL else "",
            "same_as_business_database": same_database,
            "fix": "Set CATALOG_SUPABASE_URL and CATALOG_SUPABASE_SERVICE_KEY in Render." if same_database else "",
            "error": str(exc),
        })
        return cached_rows or []

    normalized_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_code = normalize_product_code(row.get("product_code"))
        model_code = normalize_product_code(row.get("model_code"))
        combined_text = normalize_id(row.get("combined_text"))
        if not (product_code or model_code or combined_text):
            continue
        normalized_rows.append({
            "product_code": product_code,
            "model_code": model_code,
            "price": normalize_id(row.get("price")),
            "currency": normalize_id(row.get("currency")),
            "combined_text": combined_text,
            "image_url": normalize_id(row.get("image_url")),
            "image_sha256": normalize_id(row.get("image_sha256")).lower(),
            "image_fingerprint": normalize_id(row.get("image_fingerprint")),
            "embedding_model": normalize_id(row.get("embedding_model")).lower(),
            "embedding_preview": normalize_id(row.get("embedding_preview")),
            "source_pdf": normalize_id(row.get("source_pdf")),
            "page": row.get("page"),
            "card_index": row.get("card_index"),
        })

    PRODUCT_MATCHER_LOCAL_CATALOG_CACHE["rows"] = normalized_rows
    PRODUCT_MATCHER_LOCAL_CATALOG_CACHE["loaded_at"] = now
    return normalized_rows


def _extract_output_text_from_responses(body: dict) -> str:
    text = normalize_id(body.get("output_text"))
    if text:
        return text
    output = body.get("output") if isinstance(body.get("output"), list) else []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), list) else []
        for chunk in content:
            if not isinstance(chunk, dict):
                continue
            value = normalize_id(chunk.get("text"))
            if value:
                return value
    return ""


def _extract_media_vision_hints_local(media_bytes: bytes, mime_type: str, user_text: str) -> dict:
    if not OPENAI_API_KEY:
        return {}
    clean_mime = normalize_id(mime_type).split(";")[0].lower()
    if not clean_mime.startswith("image/"):
        return {}

    b64 = base64.b64encode(media_bytes).decode("ascii")
    prompt = {
        "task": "Identify product codes/models, garment details, colors, patterns, and useful keywords from this product image.",
        "customer_message": normalize_id(user_text),
        "output_format": {
            "product_codes": ["code strings"],
            "model_codes": ["model strings"],
            "keywords": ["short style/product keywords"],
            "colors": ["dominant colors"],
            "garment_type": "short product type label",
            "detected_text": "short OCR-like text seen on image",
            "confidence": "0..1",
        },
    }

    payload = {
        "model": PRODUCT_MATCHER_OPENAI_VISION_MODEL,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Return ONLY JSON. Do not add markdown. "
                            "Focus on codes, model identifiers, and concise retrieval keywords."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": json.dumps(prompt, ensure_ascii=False)},
                    {
                        "type": "input_image",
                        "image_url": f"data:{clean_mime};base64,{b64}",
                        "detail": PRODUCT_MATCHER_OPENAI_VISION_DETAIL,
                    },
                ],
            },
        ],
        "temperature": 0.0,
    }

    try:
        res = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=PRODUCT_MATCHER_OPENAI_VISION_TIMEOUT_SECONDS,
        )
        body = safe_json(res)
        if not res.ok:
            log("Local vision request failed", {"status": res.status_code, "body": body})
            return {}
    except Exception as exc:
        log("Local vision request error", str(exc))
        return {}

    raw_text = _extract_output_text_from_responses(body)
    parsed = _extract_json_object_loose(raw_text)
    parsed_codes = []
    for key in ("product_codes", "model_codes"):
        values = parsed.get(key)
        if isinstance(values, list):
            parsed_codes.extend(values)
    if isinstance(parsed.get("detected_text"), str):
        parsed_codes.extend(extract_codes_from_text_local(parsed.get("detected_text")))

    codes = []
    for code in parsed_codes:
        normalized = normalize_product_code(code)
        if normalized and normalized not in codes:
            codes.append(normalized)

    keywords = []
    raw_keywords = parsed.get("keywords")
    if isinstance(raw_keywords, list):
        for item in raw_keywords:
            token = normalize_id(item).lower()
            if token and token not in keywords:
                keywords.append(token)

    detected_text = normalize_id(parsed.get("detected_text"))
    if detected_text:
        for token in re.findall(r"[A-Za-z0-9'-]{3,}", detected_text.lower()):
            if token not in keywords:
                keywords.append(token)

    return {
        "codes": codes[:24],
        "keywords": keywords[:PRODUCT_MATCHER_LOCAL_MAX_KEYWORDS],
        "colors": [normalize_id(x).lower() for x in (parsed.get("colors") if isinstance(parsed.get("colors"), list) else [])][:8],
        "garment_type": normalize_id(parsed.get("garment_type")).lower(),
        "detected_text": detected_text,
        "confidence": _safe_score(parsed.get("confidence")),
        "raw_text": raw_text[:400],
    }


def _parse_float_list(value, limit: int = 12) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, tuple):
        items = list(value)
    else:
        text = normalize_id(value)
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = parsed
            else:
                items = re.findall(r"-?\d+(?:\.\d+)?", text)
        except Exception:
            items = re.findall(r"-?\d+(?:\.\d+)?", text)
    result = []
    for item in items[:limit]:
        try:
            result.append(float(item))
        except Exception:
            continue
    return result


def _image_sha256_from_bytes(media_bytes: bytes) -> str:
    if not media_bytes:
        return ""
    return hashlib.sha256(media_bytes).hexdigest()


def _build_image_signatures_from_bytes(media_bytes: bytes) -> list[list[float]]:
    if not media_bytes:
        return []

    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return []

    try:
        image = Image.open(io.BytesIO(media_bytes)).convert("RGB").resize((128, 128))
        arr = np.asarray(image, dtype=np.float32)
    except Exception:
        return []

    signatures = []

    try:
        rgb_hist = []
        total_pixels = float(arr.shape[0] * arr.shape[1] * 3) or 1.0
        for channel in range(3):
            hist, _ = np.histogram(arr[:, :, channel], bins=4, range=(0, 255))
            rgb_hist.extend((hist.astype(np.float32) / total_pixels).tolist())
        signatures.append([float(x) for x in rgb_hist])
    except Exception:
        pass

    try:
        lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        lum_hist, _ = np.histogram(lum, bins=12, range=(0, 255))
        lum_total = float(lum_hist.sum()) or 1.0
        signatures.append((lum_hist.astype(np.float32) / lum_total).tolist())
    except Exception:
        pass

    try:
        flat = arr.reshape(-1, 3)
        means = (flat.mean(axis=0) / 255.0).tolist()
        stds = (flat.std(axis=0) / 255.0).tolist()
        percentiles = np.percentile(flat, [10, 25, 50], axis=0) / 255.0
        signatures.append([float(x) for x in (means + stds + percentiles.reshape(-1).tolist())[:12]])
    except Exception:
        pass

    return [sig for sig in signatures if len(sig) >= 6]


def _vector_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    if size < 4:
        return 0.0
    l = [float(x) for x in left[:size]]
    r = [float(x) for x in right[:size]]
    dot = sum(a * b for a, b in zip(l, r))
    left_norm = sum(a * a for a in l) ** 0.5
    right_norm = sum(b * b for b in r) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _row_image_similarity_score(row: dict, media_sha256: str, media_signatures: list[list[float]]) -> float:
    row_sha256 = normalize_id(row.get("image_sha256")).lower()
    if row_sha256 and media_sha256 and row_sha256 == media_sha256:
        return 1.0

    row_signature = _parse_float_list(row.get("embedding_preview"), limit=12)
    if not row_signature:
        return 0.0

    best = 0.0
    for media_signature in media_signatures or []:
        score = _vector_similarity(row_signature, media_signature)
        if score > best:
            best = score
    return best


def _score_local_catalog_row(row: dict, code_set: set, keyword_set: set, media_sha256: str = "", media_signatures: list[list[float]] = None, vision: dict = None) -> tuple[float, dict]:
    code = normalize_product_code(row.get("product_code"))
    model = normalize_product_code(row.get("model_code"))
    text_blob = " ".join(
        [
            normalize_id(row.get("combined_text")).upper(),
            code,
            model,
            normalize_id(row.get("image_fingerprint")).upper(),
        ]
    )

    code_score = 0.0
    if code and code in code_set:
        code_score = 1.0
    elif model and model in code_set:
        code_score = 0.92

    keyword_hits = 0
    if keyword_set:
        lower_blob = text_blob.lower()
        for kw in keyword_set:
            if kw and kw in lower_blob:
                keyword_hits += 1
    keyword_score = 0.0
    if keyword_set:
        keyword_score = min(1.0, keyword_hits / max(1, min(6, len(keyword_set))))

    text_score = 0.0
    if code and code in text_blob:
        text_score = 1.0
    elif model and model in text_blob:
        text_score = 0.9

    image_score = _row_image_similarity_score(row, media_sha256, media_signatures or [])
    if vision and isinstance(vision, dict):
        row_text = normalize_id(row.get("combined_text")).lower()
        row_type_blob = f"{code} {model} {row_text}".lower()
        for color in vision.get("colors", []) or []:
            token = normalize_id(color).lower()
            if token and token in row_type_blob:
                image_score = max(image_score, 0.55)
        garment_type = normalize_id(vision.get("garment_type")).lower()
        if garment_type and garment_type in row_type_blob:
            image_score = max(image_score, 0.60)

    final_score = (0.54 * code_score) + (0.18 * keyword_score) + (0.08 * text_score) + (0.20 * image_score)
    parts = {
        "final": round(final_score, 6),
        "code": round(code_score, 6),
        "keyword": round(keyword_score, 6),
        "text": round(text_score, 6),
        "image": round(image_score, 6),
    }
    return final_score, parts


def analyze_media_for_sales_reply_local(media_url: str, user_text: str, media_type: str = "", access_token: str = "") -> dict:
    if catalog_matcher_module is not None:
        try:
            return catalog_matcher_module.analyze_media_for_sales_reply_local(
                media_url=media_url,
                user_text=user_text,
                media_type=media_type,
                access_token=access_token,
            )
        except Exception as exc:
            log("catalog_matcher local delegation failed", {"error": str(exc)})
    if not PRODUCT_MATCHER_LOCAL_ENABLED:
        return {}
    media_type = normalize_id(media_type).lower()
    if media_type and media_type not in {"photo", "file", "image"}:
        return {}
    if not media_url:
        return {}

    try:
        media_bytes, _, mime_type = download_media_for_matcher(media_url, access_token=access_token)
    except Exception as exc:
        log("Local matcher download failed", {"error": str(exc)})
        return {}

    vision = _extract_media_vision_hints_local(media_bytes, mime_type, user_text)
    media_sha256 = _image_sha256_from_bytes(media_bytes)
    media_signatures = _build_image_signatures_from_bytes(media_bytes)
    extracted_codes = extract_codes_from_text_local(user_text)
    for code in vision.get("codes", []):
        if code not in extracted_codes:
            extracted_codes.append(code)
    code_set = {normalize_product_code(code) for code in extracted_codes if code}

    keyword_set = {normalize_id(x).lower() for x in re.findall(r"[A-Za-z0-9'-]{3,}", normalize_id(user_text))}
    for token in vision.get("keywords", []):
        clean = normalize_id(token).lower()
        if clean:
            keyword_set.add(clean)

    rows = _get_local_catalog_rows()
    if not rows:
        return {}
    exact_image_match = any(
        normalize_id(row.get("image_sha256")).lower()
        and normalize_id(row.get("image_sha256")).lower() == media_sha256
        for row in rows
    )

    scored = []
    for row in rows:
        score, parts = _score_local_catalog_row(
            row,
            code_set,
            keyword_set,
            media_sha256=media_sha256,
            media_signatures=media_signatures,
            vision=vision,
        )
        if score <= 0:
            continue
        scored.append({
            **row,
            "score": score,
            "components": parts,
        })

    scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    matches = scored[:PRODUCT_MATCHER_TOP_K]
    if not matches:
        return {}

    top = matches[0]
    top_score = _safe_score(top.get("score"))
    code = normalize_id(top.get("product_code"))
    model = normalize_id(top.get("model_code"))
    price = normalize_id(top.get("price"))
    currency = normalize_id(top.get("currency"))
    image_score = _safe_score(top.get("components", {}).get("image"))

    visual_evidence = exact_image_match or bool(code_set) or bool(vision.get("codes")) or bool(vision.get("keywords")) or bool(vision.get("garment_type"))
    accepted_by_score = top_score >= PRODUCT_MATCHER_MIN_SCORE and visual_evidence
    accepted_by_code = bool(code_set)
    accepted_by_image = image_score >= max(PRODUCT_MATCHER_WEAK_MIN_SCORE, 0.45) and visual_evidence
    accepted_weak_match = bool(code or model or price) and top_score >= PRODUCT_MATCHER_WEAK_MIN_SCORE and visual_evidence

    log("Local media matcher response summary", {
        "match_count": len(matches),
        "top_score": round(top_score, 4),
        "top_product_code": code,
        "top_model_code": model,
        "has_price": bool(price),
        "extracted_codes": list(code_set)[:8],
        "vision_confidence": _safe_score(vision.get("confidence")),
        "accepted_by_score": accepted_by_score,
        "accepted_by_code": accepted_by_code,
        "accepted_by_image": accepted_by_image,
        "accepted_weak_match": accepted_weak_match,
    })

    if not (accepted_by_score or accepted_by_code or accepted_by_image or accepted_weak_match):
        return {}

    alternatives = []
    for item in matches[1:3]:
        alt_code = normalize_id(item.get("product_code"))
        alt_model = normalize_id(item.get("model_code"))
        alt_score = _safe_score(item.get("score"))
        if alt_code or alt_model:
            alternatives.append(f"{alt_code or alt_model} ({alt_score:.2f})")

    parts = []
    if code:
        parts.append(f"code={code}")
    if model:
        parts.append(f"model={model}")
    if price:
        parts.append(f"price={price} {currency}".strip())

    context_lines = [
        "Product media analysis (high-priority context for this customer message):",
        f"- Top match confidence: {top_score:.2f}",
    ]
    if parts:
        context_lines.append(f"- Top match details: {', '.join(parts)}")
    if code_set:
        context_lines.append(f"- Extracted codes from media/text: {', '.join(sorted(code_set)[:8])}")
    if alternatives:
        context_lines.append(f"- Alternatives: {', '.join(alternatives)}")
    context_lines.append("- Use this to answer product/price questions for the attached media.")

    return {
        "context": "\n".join(context_lines),
        "reply_hint": build_product_match_reply(code, model, price, currency, top_score),
        "top_score": top_score,
        "top_match_code": code,
        "top_match_model": model,
        "matches": matches,
    }


def analyze_media_for_sales_reply(media_url: str, user_text: str, media_type: str = "", access_token: str = "") -> dict:
    if catalog_matcher_module is not None:
        try:
            return catalog_matcher_module.analyze_media_for_sales_reply(
                media_url=media_url,
                user_text=user_text,
                media_type=media_type,
                access_token=access_token,
            )
        except Exception as exc:
            log("catalog_matcher delegation failed", {"error": str(exc)})
    media_url = normalize_id(media_url)
    if not PRODUCT_MATCHER_ENABLED or not PRODUCT_MATCHER_API_URLS or not media_url:
        if PRODUCT_MATCHER_LOCAL_ENABLED and PRODUCT_MATCHER_ENABLED and media_url:
            return analyze_media_for_sales_reply_local(
                media_url=media_url,
                user_text=user_text,
                media_type=media_type,
                access_token=access_token,
            )
        return {}
    local_result = analyze_media_for_sales_reply_local(
        media_url=media_url,
        user_text=user_text,
        media_type=media_type,
        access_token=access_token,
    )
    if local_result:
        return local_result
    if PRODUCT_MATCHER_LOCAL_ONLY:
        return {}
    if media_type and media_type not in {"photo", "video", "file"}:
        return {}

    payload = {
        "media_url": media_url,
        "user_message": user_text or "",
        "language": media_matcher_language(user_text),
        "top_k": PRODUCT_MATCHER_TOP_K,
    }
    body = {}
    last_upload_error = ""
    last_url_error = ""

    try:
        media_bytes, filename, mime_type = download_media_for_matcher(media_url, access_token=access_token)
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
        upload_files = {"file": (filename, media_bytes, mime_type)}
        for matcher_url in PRODUCT_MATCHER_API_URLS:
            upload_url = product_matcher_file_url(matcher_url)
            try:
                response = requests.post(
                    upload_url,
                    data=upload_data,
                    files=upload_files,
                    timeout=max(PRODUCT_MATCHER_TIMEOUT_SECONDS, 90),
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

    if not (isinstance(body, dict) and body.get("status") == "ok"):
        for matcher_url in PRODUCT_MATCHER_API_URLS:
            url_endpoint = product_matcher_url_url(matcher_url)
            try:
                response = requests.post(
                    url_endpoint,
                    json=payload,
                    timeout=max(PRODUCT_MATCHER_TIMEOUT_SECONDS, 90),
                )
            except Exception as exc:
                last_url_error = f"{url_endpoint}: {exc}"
                continue
            if not response.ok:
                last_url_error = f"{url_endpoint}: HTTP {response.status_code}"
                continue
            body = safe_json(response)
            if isinstance(body, dict) and body.get("status") == "ok":
                break
            last_url_error = f"{url_endpoint}: invalid response shape"
        else:
            body = {}

    if not (isinstance(body, dict) and body.get("status") == "ok"):
        log("Media matcher call failed", {"upload_mode": last_upload_error or "n/a", "url_mode": last_url_error or "n/a"})
        return {}

    matches = body.get("matches") if isinstance(body.get("matches"), list) else []
    top = matches[0] if matches else {}
    top_score = _safe_score(top.get("score"))
    extracted_codes = body.get("extracted_codes") if isinstance(body.get("extracted_codes"), list) else []
    code = normalize_id(top.get("product_code"))
    model = normalize_id(top.get("model_code"))
    price = normalize_id(top.get("price"))
    currency = normalize_id(top.get("currency"))
    matcher_debug = body.get("debug") if isinstance(body.get("debug"), dict) else {}
    has_match_identity = bool(code or model or price)
    accepted_by_score = top_score >= PRODUCT_MATCHER_MIN_SCORE
    accepted_by_code = bool(extracted_codes)
    accepted_weak_match = has_match_identity and top_score >= PRODUCT_MATCHER_WEAK_MIN_SCORE

    log("Media matcher response summary", {
        "match_count": len(matches),
        "top_score": round(top_score, 4),
        "top_product_code": code,
        "top_model_code": model,
        "has_price": bool(price),
        "extracted_codes": [normalize_id(x) for x in extracted_codes[:6]],
        "min_required_score": PRODUCT_MATCHER_MIN_SCORE,
        "weak_min_score": PRODUCT_MATCHER_WEAK_MIN_SCORE,
        "accepted_by_score": accepted_by_score,
        "accepted_by_code": accepted_by_code,
        "accepted_weak_match": accepted_weak_match,
        "clip_available": matcher_debug.get("clip_available"),
        "clip_loaded": matcher_debug.get("clip_loaded"),
        "matcher_min_fusion_score": matcher_debug.get("min_fusion_score"),
    })

    if not (accepted_by_score or accepted_by_code or accepted_weak_match):
        log("Media matcher rejected by score", {
            "top_score": round(top_score, 4),
            "top_product_code": code,
            "top_model_code": model,
            "match_count": len(matches),
            "min_required_score": PRODUCT_MATCHER_MIN_SCORE,
            "weak_min_score": PRODUCT_MATCHER_WEAK_MIN_SCORE,
        })
        return {}

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
        "reply_hint": normalize_id(body.get("llm_reply")) or build_product_match_reply(code, model, price, currency, top_score),
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
    top_match_price: str = "",
    top_match_currency: str = "",
    match_strategy: str = "",
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
        "top_match_price": normalize_id(top_match_price),
        "top_match_currency": normalize_id(top_match_currency),
        "match_strategy": normalize_id(match_strategy),
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


DEFAULT_SIZES_PER_MESHOK = 6
DEFAULT_ITEMS_PER_SIZE_IN_MESHOK = 10
DEFAULT_ITEMS_PER_MESHOK = DEFAULT_SIZES_PER_MESHOK * DEFAULT_ITEMS_PER_SIZE_IN_MESHOK


def configured_pack_size_rule(business: dict = None) -> str:
    business = business or {}
    direct_keys = [
        "default_pack_size_rule",
        "default_qop_size_rule",
        "qop_size_rule",
        "pack_size_rule",
        "meshok_size_rule",
        "telegram_bag",
    ]
    for key in direct_keys:
        value = normalize_id(business.get(key))
        if value:
            if key == "telegram_bag":
                lower_value = value.lower()
                has_pack_word = any(marker in lower_value for marker in ["qop", "meshok", "мешок", "bag"])
                has_size_word = any(marker in lower_value for marker in ["razmer", "size", "размер", "o'lcham", "olcham", "өлшем"])
                if not (has_pack_word and has_size_word):
                    continue
            return value

    combined = "\n".join([
        normalize_id(business.get("knowledge")),
        normalize_id(business.get("ai_reply_rules")),
        normalize_id(business.get("faq")),
    ])
    for line in combined.splitlines():
        clean = re.sub(r"\s+", " ", line).strip(" -")
        lower = clean.lower()
        if any(marker in lower for marker in ["qop", "meshok", "мешок", "bag"]) and any(marker in lower for marker in ["razmer", "size", "размер", "o'lcham", "olcham", "өлшем"]):
            return clean
    return ""


def configured_items_per_meshok(business: dict = None) -> int:
    business = business or {}
    for key in ["items_per_meshok", "pack_total_items", "default_pack_total_items", "qop_total_items", "meshok_total_items"]:
        raw = normalize_id(business.get(key))
        if not raw:
            continue
        match = re.search(r"\d+", raw)
        if match:
            return max(1, int(match.group(0)))

    rule = configured_pack_size_rule(business)
    if rule:
        total_match = re.search(r"(?:jami|total|всего|барлығы|жалпы)\D{0,24}(\d+)", rule, re.IGNORECASE)
        if total_match:
            return max(1, int(total_match.group(1)))
        nums = [int(item) for item in re.findall(r"\d+", rule)]
        if len(nums) >= 3:
            return max(1, nums[-1])
        if len(nums) >= 2:
            return max(1, nums[0] * nums[1])

    return DEFAULT_ITEMS_PER_MESHOK


def default_pack_size_sentence(lang: str = "", include_model_hint: bool = False, business: dict = None) -> str:
    configured_rule = configured_pack_size_rule(business)
    if configured_rule:
        if include_model_hint:
            hint = {
                "en": "Send the model and I will confirm the exact size run.",
                "ru": "Отправьте модель, и я уточню размерный ряд.",
                "kk": "Модельді жіберсеңіз, нақты өлшемдерін анықтап беремін.",
            }.get(normalize_id(lang).lower(), "Modelni yuborsangiz, aniq razmerlarini aniqlab beraman.")
            return f"{configured_rule.rstrip('.!?')}. {hint}"
        return configured_rule

    lang = normalize_id(lang).lower()
    if lang == "en":
        text = "One bag contains 6 different sizes: 10 pieces per size, 60 garments total."
        if include_model_hint:
            text += " Send the model and I will confirm the exact size run."
        return text
    if lang == "ru":
        text = "В одном мешке 6 разных размеров: по 10 штук каждого размера, всего 60 единиц одежды."
        if include_model_hint:
            text += " Отправьте модель, и я уточню размерный ряд."
        return text
    if lang == "kk":
        text = "1 қаптың ішінде 6 түрлі өлшем бар: әр өлшемнен 10 данадан, барлығы 60 киім болады."
        if include_model_hint:
            text += " Модельді жіберсеңіз, нақты өлшемдерін анықтап беремін."
        return text
    text = "1 qop ichida 6 xil razmer bor: har bir razmerdan 10 tadan, jami 60 ta kiyim bo'ladi."
    if include_model_hint:
        text += " Modelni yuborsangiz, aniq razmerlarini aniqlab beraman."
    return text


def default_pack_count_question(lang: str = "") -> str:
    lang = normalize_id(lang).lower()
    if lang == "en":
        return "How many bags do you need?"
    if lang == "ru":
        return "Сколько мешков нужно?"
    if lang == "kk":
        return "Қанша қап керек?"
    return "Nechta qop kerak?"


def wants_default_pack_size_info(text: str) -> bool:
    low = normalize_id(text).lower()
    if not low:
        return False
    size_markers = [
        "razmer", "razmeri", "razmerlar", "size", "sizes", "размер", "размеры",
        "o'lcham", "o‘lcham", "olcham", "өлшем",
    ]
    pack_markers = ["qop", "meshok", "мешок", "bag", "sack", "upakovka", "упаковка", "пакет"]
    question_markers = [
        "ichida", "nechta", "qancha", "qanaqa", "qanday", "qaysi", "bor", "bormi",
        "сколько", "какие", "какой", "есть", "внутри", "қанша", "қандай", "бар",
    ]
    if any(marker in low for marker in size_markers):
        return True
    return any(marker in low for marker in pack_markers) and any(marker in low for marker in question_markers)


def default_pack_size_reply(text: str, business: dict = None) -> str:
    if not wants_default_pack_size_info(text):
        return ""
    return default_pack_size_sentence(detect_customer_language(text), include_model_hint=True, business=business)


def _parse_numeric_price(value: str) -> float | None:
    nums = re.findall(r"\d+(?:[.,]\d+)?", normalize_id(value))
    if not nums:
        return None
    try:
        return float(nums[0].replace(",", "."))
    except Exception:
        return None


def _extract_meshok_count(text: str) -> int | None:
    low = normalize_id(text).lower()
    match = re.search(r"(\d+)\s*(?:qop|meshok|мешок|sack|bag)\b", low)
    if match:
        try:
            return max(1, int(match.group(1)))
        except Exception:
            return 1
    if any(token in low for token in ["qop", "meshok", "мешок", "sack", "bag"]):
        return 1
    return None


def is_local_currency_question(text: str) -> bool:
    low = normalize_id(text).lower()
    if not low:
        return False
    markers = [
        "so'm", "som", "sum", "uzs", "o'zbek so'm", "uzbek sum", "узбек", "сум",
    ]
    return any(marker in low for marker in markers)


def build_usd_only_reply(user_text: str, media_match: dict, business: dict = None) -> str:
    currency = normalize_id(media_match.get("top_match_currency")) or "USD"
    code = normalize_id(media_match.get("top_match_code"))
    model = normalize_id(media_match.get("top_match_model"))
    label = model or code or "shu model"
    price = _parse_numeric_price(media_match.get("top_match_price", ""))
    lang = detect_customer_language(user_text)
    unit_str = f"{price:.1f}".rstrip("0").rstrip(".") if price is not None else ""
    pack_info = default_pack_size_sentence(lang, business=business)
    pack_question = default_pack_count_question(lang)
    if lang == "en":
        if unit_str:
            return f"We sell in {currency} only. Model {label} price is {unit_str} {currency}. {pack_info} {pack_question}"
        return f"We sell in {currency} only. {pack_info} {pack_question}"
    if lang == "ru":
        if unit_str:
            return f"Мы продаём только в {currency}. Цена модели {label}: {unit_str} {currency}. {pack_info} {pack_question}"
        return f"Мы продаём только в {currency}. {pack_info} {pack_question}"
    if lang == "kk":
        if unit_str:
            return f"Біз тек {currency}-мен сатамыз. Model {label} бағасы {unit_str} {currency}. {pack_info} {pack_question}"
        return f"Біз тек {currency}-мен сатамыз. {pack_info} {pack_question}"
    if unit_str:
        return f"Biz faqat {currency}da sotamiz. Model {label} narxi {unit_str} {currency}. {pack_info} {pack_question}"
    return f"Biz faqat {currency}da sotamiz. {pack_info} {pack_question}"


def build_verified_meshok_price_reply(user_text: str, media_match: dict, business: dict = None) -> str:
    unit_price = _parse_numeric_price(media_match.get("top_match_price", ""))
    if unit_price is None:
        return ""
    meshok_count = _extract_meshok_count(user_text)
    currency = normalize_id(media_match.get("top_match_currency")) or "USD"
    lang = detect_customer_language(user_text)
    code = normalize_id(media_match.get("top_match_code"))
    model = normalize_id(media_match.get("top_match_model"))
    label = model or code or "shu model"
    unit_str = f"{unit_price:.1f}".rstrip("0").rstrip(".")
    pack_info = default_pack_size_sentence(lang, business=business)
    pack_question = default_pack_count_question(lang)
    if meshok_count is None:
        if lang == "en":
            return f"Model {label} price is {unit_str} {currency}. {pack_info} {pack_question}"
        if lang == "ru":
            return f"Цена модели {label}: {unit_str} {currency}. {pack_info} {pack_question}"
        if lang == "kk":
            return f"Модель {label} бағасы {unit_str} {currency}. {pack_info} {pack_question}"
        return f"Model {label} narxi {unit_str} {currency}. {pack_info} {pack_question}"

    items_per_meshok = configured_items_per_meshok(business)
    total_items = items_per_meshok * meshok_count
    total_price = unit_price * total_items
    total_str = f"{total_price:.1f}".rstrip("0").rstrip(".")
    if lang == "en":
        if meshok_count == 1:
            return f"Model {label} price per piece is {unit_str} {currency}. {pack_info} Total is {total_str} {currency}. {pack_question}"
        return f"Model {label} price per piece is {unit_str} {currency}. {meshok_count} bags contain {total_items} garments total, total price {total_str} {currency}. {pack_question}"
    if lang == "ru":
        if meshok_count == 1:
            return f"Для модели {label} цена за 1 штуку {unit_str} {currency}. {pack_info} Итого {total_str} {currency}. {pack_question}"
        return f"Для модели {label} цена за 1 штуку {unit_str} {currency}. В {meshok_count} мешках всего {total_items} единиц одежды, общая сумма {total_str} {currency}. {pack_question}"
    if lang == "kk":
        if meshok_count == 1:
            return f"Model {label} үшін 1 данасының бағасы {unit_str} {currency}. {pack_info} Жалпы {total_str} {currency}. {pack_question}"
        return f"Model {label} үшін 1 данасының бағасы {unit_str} {currency}. {meshok_count} қапта барлығы {total_items} киім болады, жалпы баға {total_str} {currency}. {pack_question}"
    if meshok_count == 1:
        return f"Model {label} uchun 1 dona narxi {unit_str} {currency}. {pack_info} Jami {total_str} {currency}. {pack_question}"
    return f"Model {label} uchun 1 dona narxi {unit_str} {currency}. {meshok_count} qopda jami {total_items} ta kiyim bo'ladi, umumiy narx {total_str} {currency}. {pack_question}"


def is_verified_media_match(media_match: dict = None) -> bool:
    strategy = normalize_id((media_match or {}).get("match_strategy"))
    return strategy in {"exact_code_match", "exact_model_match"}


def recent_outbound_memory_key(business_id: str, customer_id: str, channel: str = "dm") -> str:
    business_id = normalize_id(business_id)
    customer_id = normalize_id(customer_id)
    channel = normalize_id(channel) or "dm"
    if not business_id or not customer_id:
        return ""
    return f"{business_id}:{customer_id}:{channel}"


def remember_recent_outbound_text(business_id: str, customer_id: str, text: str, channel: str = "dm") -> None:
    key = recent_outbound_memory_key(business_id, customer_id, channel)
    text = normalize_id(text)
    if not key or not text:
        return
    INSTAGRAM_RECENT_OUTBOUND_MEMORY[key] = {"text": text, "saved_at": time.time()}


def has_recent_outbound_memory_text(business_id: str, customer_id: str, text: str, channel: str = "dm") -> bool:
    key = recent_outbound_memory_key(business_id, customer_id, channel)
    text = normalize_id(text)
    if not key or not text:
        return False
    payload = INSTAGRAM_RECENT_OUTBOUND_MEMORY.get(key)
    if not isinstance(payload, dict):
        return False
    if (time.time() - float(payload.get("saved_at") or 0.0)) > OUTBOUND_DUPLICATE_WINDOW_SECONDS:
        INSTAGRAM_RECENT_OUTBOUND_MEMORY.pop(key, None)
        return False
    return normalize_id(payload.get("text")) == text


def _collect_instagram_payload_urls(value, url_candidates: list[str]):
    if isinstance(value, dict):
        for nested in value.values():
            _collect_instagram_payload_urls(nested, url_candidates)
        return
    if isinstance(value, list):
        for nested in value:
            _collect_instagram_payload_urls(nested, url_candidates)
        return
    if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in url_candidates:
        url_candidates.append(value)


def extract_instagram_media_url_from_payload(raw_payload: dict) -> tuple[str, str]:
    raw_payload = raw_payload or {}
    message = raw_payload.get("message") if isinstance(raw_payload.get("message"), dict) else {}
    attachments = message.get("attachments") if isinstance(message.get("attachments"), list) else []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        payload = att.get("payload") if isinstance(att.get("payload"), dict) else {}
        url_candidates = []
        for key in ("url", "media_url", "image_url", "video_url", "external_url", "link", "permalink", "src"):
            direct = payload.get(key)
            if isinstance(direct, str) and direct.startswith(("http://", "https://")) and direct not in url_candidates:
                url_candidates.append(direct)
        _collect_instagram_payload_urls(payload, url_candidates)
        _collect_instagram_payload_urls(att, url_candidates)
        media_url = normalize_id(url_candidates[0] if url_candidates else "")
        if not media_url:
            continue
        att_type = normalize_id(att.get("type")).lower()
        if att_type in {"image", "photo"}:
            return media_url, "photo"
        if att_type in {"video", "ig_reel", "reel"}:
            return media_url, "video"
        if re.search(r"\.(jpg|jpeg|png|gif|webp|bmp|heic|heif)(\?|$)", media_url.lower()):
            return media_url, "photo"
        if re.search(r"\.(mp4|mov|m4v|webm|avi|mkv)(\?|$)", media_url.lower()):
            return media_url, "video"
        return media_url, "file"
    return "", ""


def load_instagram_message_media_reference(business_id: str, customer_id: str, message_id: str) -> dict:
    business_id = normalize_id(business_id)
    customer_id = normalize_id(customer_id)
    message_id = normalize_id(message_id)
    if not business_id or not customer_id or not message_id:
        return {}
    try:
        result = (
            supabase.table("inbox_messages")
            .select("media_url,media_type,raw_payload")
            .eq("business_id", business_id)
            .eq("platform", "instagram")
            .eq("customer_id", customer_id)
            .eq("external_message_id", message_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        row = (result.data or [None])[0]
        if not isinstance(row, dict):
            return {}
        media_url = normalize_id(row.get("media_url"))
        media_type = normalize_id(row.get("media_type")).lower()
        if not media_url:
            media_url, payload_media_type = extract_instagram_media_url_from_payload(row.get("raw_payload") or {})
            media_type = media_type or payload_media_type
        if not media_url:
            return {}
        return {"media_url": media_url, "media_type": media_type or "photo"}
    except Exception as exc:
        log("Could not load Instagram reply-to media reference", str(exc))
        return {}


def load_recent_instagram_media_reference(
    business_id: str,
    customer_id: str,
    exclude_message_id: str = "",
) -> dict:
    business_id = normalize_id(business_id)
    customer_id = normalize_id(customer_id)
    exclude_message_id = normalize_id(exclude_message_id)
    if not business_id or not customer_id:
        return {}
    try:
        result = (
            supabase.table("inbox_messages")
            .select("external_message_id,created_at,media_url,media_type,raw_payload")
            .eq("business_id", business_id)
            .eq("platform", "instagram")
            .eq("channel", "dm")
            .eq("customer_id", customer_id)
            .eq("direction", "inbound")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        rows = result.data or []
        now_utc = datetime.utcnow()
        for row in rows:
            if not isinstance(row, dict):
                continue
            external_message_id = normalize_id(row.get("external_message_id"))
            if exclude_message_id and external_message_id == exclude_message_id:
                continue
            created_at = normalize_id(row.get("created_at"))
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    age_seconds = (now_utc - dt.replace(tzinfo=None)).total_seconds()
                    if age_seconds > PRODUCT_MATCHER_RECENT_MEDIA_LOOKBACK_SECONDS:
                        continue
                except Exception:
                    pass
            media_url = normalize_id(row.get("media_url"))
            media_type = normalize_id(row.get("media_type")).lower()
            if not media_url:
                media_url, payload_media_type = extract_instagram_media_url_from_payload(row.get("raw_payload") or {})
                media_type = media_type or payload_media_type
            if not media_url:
                continue
            if media_type not in {"photo", "video", "file"}:
                media_type = "photo"
            return {
                "media_url": media_url,
                "media_type": media_type,
                "external_message_id": external_message_id,
            }
    except Exception as exc:
        log("Could not load recent Instagram media reference", str(exc))
    return {}


def should_reuse_recent_media_match(user_text: str, media_type: str = "", business: dict = None) -> bool:
    if media_type in {"photo", "video", "file"}:
        return False
    text = normalize_id(user_text)
    if not text:
        return False
    lower = text.lower()
    compact = re.sub(r"[^\w\s'А-Яа-яЁёЎўҚқҒғҲҳ-]+", " ", lower).strip()
    if is_price_question(lower):
        return True
    if is_greeting_only(lower):
        return True
    if re.search(r"\b\d+\s*(qop|meshok|ta|dona|pack|quti)\b", lower):
        return True
    if has_strong_business_sales_context(lower, business):
        return True
    short_followups = {
        "bor", "bormi", "narxi", "qancha", "nechpul", "razmer", "rang", "olaman",
        "zakaz", "беру", "есть", "how much", "cost", "price",
    }
    return compact in short_followups or lower in short_followups


def get_recent_platform_chat_history(platform: str, business: dict, customer_id: str = "", channel: str = "", limit: int = 10) -> list:
    if not customer_id:
        return []
    limit = min(limit, business_memory_limit(business, default=limit))
    if limit <= 0:
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


def get_recent_platform_message_rows(
    platform: str,
    business: dict,
    customer_id: str = "",
    channel: str = "",
    limit: int = 20,
) -> list:
    platform = normalize_id(platform).lower()
    customer_id = normalize_id(customer_id)
    channel = normalize_id(channel)
    if not platform or not customer_id:
        return []

    limit = min(max(1, limit), 50)

    try:
        query = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", platform)
            .eq("customer_id", customer_id)
        )
        if business and business.get("id"):
            query = query.eq("business_id", business.get("id"))
        if channel:
            query = query.eq("channel", channel)

        rows = query.order("created_at", desc=True).limit(limit).execute().data or []
        return list(reversed(rows))
    except Exception as e:
        log("Could not load recent platform message rows", str(e))
        return []

def get_ai_reply(
    user_text: str,
    business: dict,
    platform: str = "instagram",
    customer_id: str = "",
    channel: str = "",
    media_context: str = "",
    media_reply_hint: str = "",
    lead_state: dict = None,
):
    try:
        if wants_business_phone_number(user_text):
            direct_phone_reply = sales_phone_reply(user_text, business)
            if direct_phone_reply:
                return direct_phone_reply

        size_pack_reply = default_pack_size_reply(user_text, business)
        if size_pack_reply:
            return size_pack_reply

        off_topic_reply = unrelated_topic_reply(user_text, business)
        if off_topic_reply:
            return off_topic_reply

        messages = [{"role": "system", "content": build_sales_system_prompt(business, platform)}]
        if platform == "instagram" and "comment" in normalize_id(channel).lower():
            messages.append({
                "role": "system",
                "content": (
                    "This is a public Instagram comment. Never ask for private information "
                    "such as name, phone number, address, WhatsApp/Telegram, passport, card, "
                    "or order contact details in the public reply. Move private details to DM."
                ),
            })
        normalized_lead_state = normalize_lead_state(lead_state)
        lead_context = build_known_customer_information_block(normalized_lead_state)
        if lead_context:
            messages.append({"role": "system", "content": lead_context})
        if media_context:
            messages.append({"role": "system", "content": media_context})
        if media_reply_hint:
            messages.append({
                "role": "system",
                "content": f"Suggested product answer from media matcher: {media_reply_hint}. Keep the answer in the customer's language and do not ask which model if the matcher already found one.",
            })
        messages.extend(get_recent_platform_chat_history(platform, business, customer_id, channel, limit=20))
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
            return clean_sales_reply(reply.strip(), user_text, business, normalized_lead_state)
        if media_reply_hint:
            return clean_sales_reply(media_reply_hint, user_text, business, normalized_lead_state)
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
    channel_token = get_business_channel_token(
        business,
        ["instagram"],
        ["page_access_token", "access_token"],
    )
    if channel_token:
        return channel_token
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


def send_dm(access_token: str, recipient_id: str, text: str, business: dict = None, message_tag: str = "", preserve_text: bool = False):
    recipient_id = normalize_id(recipient_id)
    if not access_token or not recipient_id or not text:
        return None

    business = business or {}
    text = normalize_id(text)[:1000] if preserve_text else complete_sentence_reply(remove_urls(text), limit=1000)
    if looks_like_internal_prompt_leak(text):
        log("Prompt leak blocked at send_dm", {"reply_preview": text[:300], "recipient_id": recipient_id})
        text = safe_outbound_leak_fallback(business)
    if not text:
        return None

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text[:1000]},
    }

    message_tag = normalize_id(message_tag).upper()
    if message_tag:
        payload["tag"] = message_tag

    if business.get("oauth_provider") == "facebook_page":
        payload["messaging_type"] = "MESSAGE_TAG" if message_tag else "RESPONSE"

    return send_instagram_payload(access_token, business, payload)


def send_instagram_dm(access_token: str, recipient_id: str, text: str, business: dict, message_tag: str = "", preserve_text: bool = False):
    res = send_dm(access_token, recipient_id, text, business, message_tag=message_tag, preserve_text=preserve_text)
    if res is None:
        return False, {"error": "Send failed"}
    return res.ok, safe_json(res)


def send_manual_instagram_dm(access_token: str, recipient_id: str, text: str, business: dict):
    ok, result = send_instagram_dm(access_token, recipient_id, text, business, preserve_text=True)
    if ok or not instagram_reply_window_closed(result or {}):
        return ok, result
    if not INSTAGRAM_HUMAN_AGENT_RETRY_ENABLED:
        return ok, result

    ok, retry_result = send_instagram_dm(
        access_token,
        recipient_id,
        text,
        business,
        message_tag="HUMAN_AGENT",
        preserve_text=True,
    )
    if not ok:
        retry_error = retry_result.get("error") if isinstance(retry_result, dict) else {}
        retry_message = normalize_id((retry_error or {}).get("message") if isinstance(retry_error, dict) else "")
        if "human agent" in retry_message.lower() and "review" in retry_message.lower():
            return False, result
    if isinstance(retry_result, dict):
        retry_result = {
            **retry_result,
            "human_agent_retry": True,
            **({"message_tag": "HUMAN_AGENT"} if ok else {}),
        }
    return ok, retry_result


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
    business_name = normalize_id(business.get("business_name")) or "Bizning katalog"
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

    text = safe_public_comment_reply(text, business)[:1000]
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
    reply_to = message.get("reply_to") if isinstance(message.get("reply_to"), dict) else {}
    reply_to_message_id = normalize_id(reply_to.get("mid"))
    is_echo = bool(message.get("is_echo"))

    if is_echo:
        business = find_business_for_webhook(entry_id, sender_id)
        if business and recipient_id:
            business_id = normalize_id(business.get("id"))
            if not load_inbox_message_by_external_id(
                business_id,
                "instagram",
                recipient_id,
                message_id,
                direction="outbound",
            ):
                save_inbox_message(
                    business=business,
                    platform="instagram",
                    sender_id=sender_id or normalize_id(business.get("instagram_business_id")) or entry_id,
                    recipient_id=recipient_id,
                    message_text=message_text,
                    direction="outbound",
                    platform_message_id=message_id,
                    raw_payload=messaging,
                    is_read=True,
                    channel="dm",
                )
            mark_customer_inbound_read(business_id, "instagram", recipient_id, "dm")
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
        if media_type == "audio" and media_url:
            transcript = transcribe_media_url_for_voice(media_url, access_token=access_token)
            if transcript:
                message_text = transcript
                message["text"] = transcript
        sender_profile = fetch_instagram_customer_profile(access_token, sender_id) if access_token else {}
        customer_display_name = display_name_from_instagram_profile(sender_profile, "")
        if sender_profile:
            messaging = {
                **messaging,
                "sender_profile": sender_profile,
            }
        recent_lead_rows = get_recent_platform_message_rows("instagram", business, sender_id, "dm", limit=20)
        lead_state = derive_customer_lead_state(
            "instagram",
            business,
            sender_id,
            "dm",
            recent_rows=recent_lead_rows,
            current_text=message_text,
            customer_name_hint=customer_display_name,
            message_id=message_id,
        )
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

        if post_permalink and media_type in (None, "", "file", "video"):
            try:
                cached_reel = download_instagram_reel_to_cache(post_permalink) or {}
                cached_media_url = normalize_id(cached_reel.get("media_url"))
                if cached_media_url:
                    media_url = cached_media_url
                    media_type = "video"
                    post_media_type = post_media_type or "video"
            except Exception as e:
                log("Could not cache Instagram reel", str(e))

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
        upsert_customer_lead_state(
            business_id=business.get("id"),
            platform="instagram",
            customer_id=sender_id,
            lead_state=lead_state,
            channel="dm",
            updated_by="instagram_bot",
        )

        if not instagram_dm_allowed_for_test_customer(
            business_id=business.get("id"),
            sender_id=sender_id,
            sender_profile=sender_profile,
            customer_name=customer_display_name,
        ):
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="skipped_test_allowlist")
            mark_processed(processed_message_ids, message_id)
            return

        if is_conversation_finished_message(message_text):
            set_chat_ai_enabled(business.get("id"), "instagram", "dm", sender_id, False)
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="finished_by_customer")
            mark_processed(processed_message_ids, message_id)
            return

        if not claim_instagram_message_processing(business.get("id"), message_id, sender_id, "dm"):
            log("Instagram DM reply skipped: already claimed in database", {
                "customer_id": sender_id,
                "message_id": message_id,
                "media_type": media_type,
            })
            mark_processed(processed_message_ids, message_id)
            return

        if not business_allows_auto_reply(business, "instagram", "dm"):
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="skipped_auto_reply_disabled")
            mark_processed(processed_message_ids, message_id)
            return

        if not is_chat_ai_enabled("instagram", "dm", sender_id, business.get("id")):
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="skipped_ai_disabled")
            mark_processed(processed_message_ids, message_id)
            return

        existing_inbound = load_inbox_message_by_external_id(
            business.get("id"),
            "instagram",
            sender_id,
            message_id,
            direction="inbound",
        )
        if existing_inbound and has_outbound_reply_after(
            business.get("id"),
            "instagram",
            sender_id,
            normalize_id(existing_inbound.get("created_at")),
            "dm",
        ):
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="duplicate_skipped")
            mark_processed(processed_message_ids, message_id)
            return

        if is_forwarded_instagram_share_placeholder(message_text):
            log("Instagram DM forwarded share saved without auto-reply", {
                "customer_id": sender_id,
                "message_id": message_id,
                "media_type": media_type,
                "post_permalink": post_permalink,
            })
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="skipped_forwarded_share")
            mark_processed(processed_message_ids, message_id)
            return

        if is_low_signal_message(message_text, messaging):
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="skipped_low_signal")
            mark_processed(processed_message_ids, message_id)
            return

        if not access_token:
            log("Instagram DM reply skipped: missing access token", {
                "customer_id": sender_id,
                "message_id": message_id,
                "media_type": media_type,
                "post_permalink": post_permalink,
                "has_media_url": bool(media_url),
                "has_post_image_url": bool(post_image_url),
            })
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="skipped_missing_access_token")
            return

        generic_wholesale_reply = ""
        if is_generic_media_wholesale_inquiry(
            message_text,
            media_type=media_type or "",
            post_permalink=post_permalink,
            post_media_type=post_media_type,
        ):
            generic_wholesale_reply = build_generic_wholesale_intro_reply(message_text, business)

        media_match_context = ""
        media_reply_hint = ""
        matcher_source_url = media_url or post_image_url
        business_id = normalize_id(business.get("id"))
        recent_media_context_found = False
        force_direct_media_reply = False
        resolved_media_match = {}
        verified_exact_media_match = False
        sales_agent_decision = {}

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
                access_token=access_token,
            )
            if media_match:
                resolved_media_match = media_match
                verified_exact_media_match = is_verified_media_match(media_match)
                media_match_context = media_match.get("context", "")
                media_reply_hint = media_match.get("reply_hint", "")
                remember_instagram_media_match(
                    business_id=business_id,
                    customer_id=sender_id,
                    context=media_match_context,
                    reply_hint=media_reply_hint,
                    top_match_code=media_match.get("top_match_code", ""),
                    top_match_model=media_match.get("top_match_model", ""),
                    top_match_price=media_match.get("top_match_price", ""),
                    top_match_currency=media_match.get("top_match_currency", ""),
                    match_strategy=media_match.get("match_strategy", ""),
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
        elif should_reuse_recent_media_match(message_text or "", media_type or "", business):
            cached_match = load_recent_instagram_media_match(business_id=business_id, customer_id=sender_id)
            if cached_match:
                recent_media_context_found = True
                resolved_media_match = cached_match
                verified_exact_media_match = is_verified_media_match(cached_match)
                cached_context = normalize_id(cached_match.get("context"))
                if cached_context:
                    media_match_context = (
                        f"{cached_context}\n"
                        "- This customer follow-up likely refers to the same previously matched product unless they ask to change model."
                    )
                    media_reply_hint = ""
                    log("Instagram DM media matcher cache hit", {
                        "customer_id": sender_id,
                        "message_id": message_id,
                        "top_match_code": normalize_id(cached_match.get("top_match_code")),
                        "top_match_model": normalize_id(cached_match.get("top_match_model")),
                        "top_score": _safe_score(cached_match.get("top_score")),
                    })
            elif reply_to_message_id:
                media_ref = load_instagram_message_media_reference(
                    business_id=business_id,
                    customer_id=sender_id,
                    message_id=reply_to_message_id,
                )
                replied_media_url = normalize_id(media_ref.get("media_url"))
                replied_media_type = normalize_id(media_ref.get("media_type")).lower() or "photo"
                if replied_media_url and replied_media_type in {"photo", "video", "file"}:
                    recent_media_context_found = True
                    log("Instagram DM reply-to media matcher request", {
                        "customer_id": sender_id,
                        "message_id": message_id,
                        "reply_to_message_id": reply_to_message_id,
                        "media_type": replied_media_type,
                        "source_url_host": urlparse(replied_media_url).netloc,
                    })
                    media_match = analyze_media_for_sales_reply(
                        media_url=replied_media_url,
                        user_text=message_text or "",
                        media_type=replied_media_type,
                        access_token=access_token,
                    )
                    if media_match:
                        resolved_media_match = media_match
                        verified_exact_media_match = is_verified_media_match(media_match)
                        media_match_context = (
                            f"{media_match.get('context', '')}\n"
                            "- This customer follow-up is replying directly to the matched product image."
                        )
                        media_reply_hint = ""
                        remember_instagram_media_match(
                            business_id=business_id,
                            customer_id=sender_id,
                            context=media_match_context,
                            reply_hint=media_match.get("reply_hint", ""),
                            top_match_code=media_match.get("top_match_code", ""),
                            top_match_model=media_match.get("top_match_model", ""),
                            top_match_price=media_match.get("top_match_price", ""),
                            top_match_currency=media_match.get("top_match_currency", ""),
                            match_strategy=media_match.get("match_strategy", ""),
                            top_score=media_match.get("top_score", 0.0),
                        )
                        log("Instagram DM reply-to media matcher hit", {
                            "customer_id": sender_id,
                            "message_id": message_id,
                            "reply_to_message_id": reply_to_message_id,
                            "top_match_code": media_match.get("top_match_code"),
                            "top_match_model": media_match.get("top_match_model"),
                            "top_score": media_match.get("top_score"),
                        })
                    else:
                        log("Instagram DM reply-to media matcher miss", {
                            "customer_id": sender_id,
                            "message_id": message_id,
                            "reply_to_message_id": reply_to_message_id,
                            "media_type": replied_media_type,
                        })

            if not media_match_context:
                recent_media_ref = load_recent_instagram_media_reference(
                    business_id=business_id,
                    customer_id=sender_id,
                    exclude_message_id=message_id,
                )
                recent_media_url = normalize_id(recent_media_ref.get("media_url"))
                recent_media_type = normalize_id(recent_media_ref.get("media_type")).lower() or "photo"
                if recent_media_url and recent_media_type in {"photo", "video", "file"}:
                    recent_media_context_found = True
                    log("Instagram DM recent-media matcher request", {
                        "customer_id": sender_id,
                        "message_id": message_id,
                        "recent_media_message_id": normalize_id(recent_media_ref.get("external_message_id")),
                        "media_type": recent_media_type,
                        "source_url_host": urlparse(recent_media_url).netloc,
                    })
                    media_match = analyze_media_for_sales_reply(
                        media_url=recent_media_url,
                        user_text=message_text or "",
                        media_type=recent_media_type,
                        access_token=access_token,
                    )
                    if media_match:
                        resolved_media_match = media_match
                        verified_exact_media_match = is_verified_media_match(media_match)
                        media_match_context = (
                            f"{media_match.get('context', '')}\n"
                            "- This customer follow-up likely refers to their most recent product image."
                        )
                        media_reply_hint = ""
                        remember_instagram_media_match(
                            business_id=business_id,
                            customer_id=sender_id,
                            context=media_match_context,
                            reply_hint=media_match.get("reply_hint", ""),
                            top_match_code=media_match.get("top_match_code", ""),
                            top_match_model=media_match.get("top_match_model", ""),
                            top_match_price=media_match.get("top_match_price", ""),
                            top_match_currency=media_match.get("top_match_currency", ""),
                            match_strategy=media_match.get("match_strategy", ""),
                            top_score=media_match.get("top_score", 0.0),
                        )
                        log("Instagram DM recent-media matcher hit", {
                            "customer_id": sender_id,
                            "message_id": message_id,
                            "top_match_code": media_match.get("top_match_code"),
                            "top_match_model": media_match.get("top_match_model"),
                            "top_score": media_match.get("top_score"),
                        })
                    else:
                        log("Instagram DM recent-media matcher miss", {
                            "customer_id": sender_id,
                            "message_id": message_id,
                            "media_type": recent_media_type,
                        })

        sales_agent_decision = run_sales_agent_for_inbound(
            business=business,
            platform="instagram",
            customer_id=sender_id,
            channel="dm",
            message_text=message_text or ("Customer sent product media." if media_type in {"photo", "video", "file"} else ""),
            message_id=message_id,
            customer_name=customer_display_name,
            media_type=media_type or "",
            media_match=resolved_media_match or {},
            recent_rows=recent_lead_rows,
            existing_lead_state=lead_state,
        )
        if sales_agent_decision:
            lead_state = sales_agent_decision.get("lead_state") or lead_state
            agent_context = normalize_id(sales_agent_decision.get("reply_context"))
            if agent_context:
                media_match_context = f"{media_match_context}\n{agent_context}".strip()
            handoff_result = sales_agent_decision.get("handoff") or {}
            if handoff_result.get("handoff_required") and normalize_id(handoff_result.get("customer_reply")):
                media_reply_hint = normalize_id(handoff_result.get("customer_reply"))
                force_direct_media_reply = True

        if media_type in {"photo", "video", "file"} and not normalize_id(message_text):
            log("Instagram DM cached media without immediate reply", {
                "customer_id": sender_id,
                "message_id": message_id,
                "media_type": media_type,
                "has_verified_match": bool(normalize_id((resolved_media_match or {}).get("top_match_code"))),
            })
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="cached_media_waiting_for_text")
            mark_processed(processed_message_ids, message_id)
            return

        needs_photo_fallback = (
            (media_type in {"photo", "video", "file"} or recent_media_context_found)
            and not media_match_context
            and not media_reply_hint
        )

        quantity_followup = _extract_meshok_count(message_text) is not None

        media_match_strategy = normalize_id((resolved_media_match or {}).get("match_strategy"))

        if verified_exact_media_match and is_local_currency_question(message_text):
            usd_only_reply = build_usd_only_reply(message_text, resolved_media_match, business)
            if usd_only_reply:
                media_reply_hint = usd_only_reply
                force_direct_media_reply = True

        if media_match_strategy == "exact_model_ambiguous_price" and (is_price_question(message_text) or quantity_followup):
            media_reply_hint = normalize_id((resolved_media_match or {}).get("reply_hint"))
            if media_reply_hint:
                force_direct_media_reply = True

        if verified_exact_media_match and (is_price_question(message_text) or quantity_followup):
            verified_meshok_reply = build_verified_meshok_price_reply(message_text, resolved_media_match, business)
            if verified_meshok_reply:
                media_reply_hint = verified_meshok_reply
                force_direct_media_reply = True

        if needs_photo_fallback:
            if recent_media_context_found and (is_price_question(message_text) or quantity_followup):
                verified_meshok_reply = build_verified_meshok_price_reply(message_text, resolved_media_match, business)
                if verified_meshok_reply:
                    media_reply_hint = verified_meshok_reply
                    media_match_context = (
                        "The customer is asking about bag/meshok pricing for a verified matched product. "
                        f"Use the verified unit price and the configured {configured_items_per_meshok(business)} pieces per meshok to answer directly."
                    )
                else:
                    media_reply_hint = product_media_price_fallback_reply(message_text, business)
                    media_match_context = (
                        "The customer is asking the price for their recent product photo, "
                        "but the product matcher did not return a verified catalog match. "
                        "Answer with a short price-confirmation fallback and do not ask for name or phone."
                    )
                force_direct_media_reply = True
            elif media_type in {"photo", "video", "file"}:
                media_reply_hint = replacement_for_forbidden_product_photo_question(message_text or "photo", business)
                media_match_context = (
                    "The customer sent product media, but the product matcher did not return a verified catalog match. "
                    "Acknowledge the media briefly and do not ask for name or phone."
                )
                force_direct_media_reply = True
            else:
                log("Instagram DM skipped auto-reply: no verified media match", {
                    "customer_id": sender_id,
                    "message_id": message_id,
                    "media_type": media_type,
                    "source_url_host": urlparse(matcher_source_url).netloc if matcher_source_url else "",
                })
                mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="skipped_no_verified_match")
                mark_processed(processed_message_ids, message_id)
                return

        if force_direct_media_reply:
            log("Instagram DM media fallback reply", {
                "customer_id": sender_id,
                "message_id": message_id,
                "reason": "media_match_missing",
            })

        use_direct_matcher_reply = bool(generic_wholesale_reply) or force_direct_media_reply or verified_exact_media_match or (bool(media_reply_hint) and (
            is_auto_media_placeholder_message(message_text)
            or not normalize_id(message_text)
            or (media_type in {"photo", "video"} and not message.get("text"))
        ))
        if generic_wholesale_reply:
            reply_text = clean_sales_reply(generic_wholesale_reply, message_text or "photo", business, lead_state)
        elif force_direct_media_reply:
            reply_text = clean_sales_reply(media_reply_hint, message_text or "photo", business, lead_state)
        elif use_direct_matcher_reply:
            reply_text = clean_sales_reply(media_reply_hint, message_text or "photo", business, lead_state)
        else:
            reply_text = get_ai_reply(
                message_text or "Photo/Video received",
                business,
                "instagram",
                sender_id,
                "dm",
                media_context=media_match_context,
                media_reply_hint=media_reply_hint,
                lead_state=lead_state,
            )

        reply_text = complete_sentence_reply(remove_urls(reply_text), limit=1000)
        if has_recent_outbound_memory_text(business.get("id"), sender_id, reply_text, "dm"):
            log("Instagram DM duplicate outbound suppressed from memory", {
                "customer_id": sender_id,
                "message_id": message_id,
                "reply_preview": reply_text[:180],
            })
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="duplicate_outbound_memory_suppressed")
            mark_processed(processed_message_ids, message_id)
            return
        if has_recent_outbound_text(
            business.get("id"),
            "instagram",
            sender_id,
            reply_text,
            "dm",
        ):
            log("Instagram DM duplicate outbound suppressed", {
                "customer_id": sender_id,
                "message_id": message_id,
                "reply_preview": reply_text[:180],
            })
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="duplicate_outbound_suppressed")
            mark_processed(processed_message_ids, message_id)
            return

        should_send_catalog = (
            bool(get_catalog_link(business))
            and wants_catalog(message_text)
            and not is_price_question(message_text)
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
            send_result = send_dm(access_token, sender_id, reply_text, business)
            saved_reply_text = reply_text

        raw_result = safe_json(send_result) if send_result is not None else {}

        if send_result is not None and send_result.ok:
            remember_recent_outbound_text(business.get("id"), sender_id, reply_text, "dm")
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
            record_sales_agent_action(
                business=business,
                platform="instagram",
                channel="dm",
                customer_id=sender_id,
                action_type="reply_sent",
                input_message=message_text,
                decision=sales_agent_decision,
                reply_sent=saved_reply_text,
                tool_used="product_matcher" if resolved_media_match else "",
            )
            handoff_required = bool(((sales_agent_decision or {}).get("handoff") or {}).get("handoff_required"))
            if handoff_required:
                set_chat_ai_enabled(business.get("id"), "instagram", "dm", sender_id, False)
            mark_instagram_processed_message(
                business.get("id"),
                message_id,
                sender_id,
                "dm",
                status="processed_handoff_required" if handoff_required else "processed",
            )
            mark_processed(processed_message_ids, message_id)
        elif send_result is not None:
            record_sales_agent_action(
                business=business,
                platform="instagram",
                channel="dm",
                customer_id=sender_id,
                action_type="reply_failed",
                input_message=message_text,
                decision=sales_agent_decision,
                reply_sent=reply_text,
                tool_used="product_matcher" if resolved_media_match else "",
            )
            mark_instagram_processed_message(business.get("id"), message_id, sender_id, "dm", status="failed_send")
            log("Instagram DM send failed", {
                "customer_id": sender_id,
                "message_id": message_id,
                "media_type": media_type,
                "reply_preview": reply_text[:180],
                "result": raw_result,
            })

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
    comment_customer_id = commenter_id or comment_id
    sales_agent_decision = run_sales_agent_for_inbound(
        business=business,
        platform="instagram",
        customer_id=comment_customer_id,
        channel="instagram_comment",
        message_text=comment_text,
        message_id=comment_id,
        customer_name=commenter_username or f"IG User {str(comment_customer_id)[-4:]}",
        media_type="",
        media_match={},
        recent_rows=get_recent_platform_message_rows("instagram", business, comment_customer_id, "instagram_comment", limit=20),
    )

    if is_conversation_finished_message(comment_text):
        comment_scope = encode_comment_scope("", post_id) if post_id else (commenter_id or comment_id)
        set_chat_ai_enabled(business.get("id"), "instagram", "instagram_comment", comment_scope, False)
        mark_processed(processed_comment_ids, comment_id)
        return

    if not business_allows_auto_reply(business, "instagram", "instagram_comment"):
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

    reaction_reply = reaction_only_reply_text(comment_text)
    if reaction_reply:
        reply_text = reaction_reply
    elif wants_catalog(comment_text):
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
            reply_text = "Katalog DM orqali yuborildi."
        else:
            log("Instagram catalog private reply failed", {"comment_id": comment_id, "result": dm_raw_result})
            reply_text = "Katalogni DM orqali yuborish uchun bizga xabar yozing."
    elif ((sales_agent_decision or {}).get("handoff") or {}).get("handoff_required"):
        reply_text = normalize_id(((sales_agent_decision or {}).get("handoff") or {}).get("customer_reply")) or "Menejerimiz DM orqali yordam beradi."
    else:
        agent_context = normalize_id((sales_agent_decision or {}).get("reply_context"))
        reply_text = get_ai_reply(
            comment_text,
            business,
            "instagram",
            commenter_id or comment_id,
            "instagram_comment",
            media_context=agent_context,
            lead_state=(sales_agent_decision or {}).get("lead_state") or {},
        )
        reply_text = safe_public_comment_reply(reply_text, business)

    reply_text = safe_public_comment_reply(reply_text, business)
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
        record_sales_agent_action(
            business=business,
            platform="instagram",
            channel="instagram_comment",
            customer_id=comment_customer_id,
            action_type="reply_sent",
            input_message=comment_text,
            decision=sales_agent_decision,
            reply_sent=reply_text,
        )

    mark_processed(processed_comment_ids, comment_id)


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
    business_name = normalize_id((business or {}).get("business_name")) or "bizning kompaniya"
    return settings.get("opening_message") or f"Assalomu alaykum. Men {business_name} virtual yordamchisiman. Qanday yordam bera olaman?"


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


def get_whatsapp_ai_reply(phone: str, user_text: str, business: dict, media_context: str = "", media_reply_hint: str = "") -> str:
    chat = get_whatsapp_chat(phone)

    off_topic_reply = unrelated_topic_reply(user_text, business)
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
    if media_context:
        messages.append({"role": "system", "content": media_context})
    if media_reply_hint:
        messages.append({
            "role": "system",
            "content": f"Suggested product answer from media matcher: {media_reply_hint}. Keep the answer in the customer's language and do not ask which model if the matcher already found one.",
        })
    messages.extend(chat.get("messages", []))
    messages.append({"role": "user", "content": user_text})

    try:
        business_with_fallback_model = dict(business or {})
        business_with_fallback_model.setdefault("ai_model", WHATSAPP_FALLBACK_MODEL)
        reply = call_ai_chat(messages, business_with_fallback_model, "WhatsApp AI response")
        if reply:
            return clean_sales_reply(reply[:1500], user_text, business)
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

            if not business_allows_auto_reply(business, "whatsapp", "whatsapp"):
                mark_processed(processed_message_ids, message_id)
                continue

            if not is_chat_ai_enabled("whatsapp", "whatsapp", sender_id, business.get("id")):
                mark_processed(processed_message_ids, message_id)
                continue

            add_whatsapp_memory(sender_id, "user", text or f"Customer sent {msg_type}")

            media_match_context = ""
            media_reply_hint = ""
            media_match = {}
            if media_type and media_url and media_type in {"photo", "file"}:
                media_match = analyze_media_for_sales_reply(
                    media_url=media_url,
                    user_text=text or "",
                    media_type=media_type,
                    access_token=get_whatsapp_access_token(business),
                )
                if media_match:
                    media_match_context = media_match.get("context", "")
                    media_reply_hint = media_match.get("reply_hint", "")

            sales_agent_decision = run_sales_agent_for_inbound(
                business=business,
                platform="whatsapp",
                customer_id=sender_id,
                channel="whatsapp",
                message_text=text or f"Customer sent {msg_type}",
                message_id=message_id,
                customer_name=customer_name,
                media_type=media_type or "",
                media_match=media_match or {},
                recent_rows=get_recent_platform_message_rows("whatsapp", business, sender_id, "whatsapp", limit=20),
            )
            agent_context = normalize_id((sales_agent_decision or {}).get("reply_context"))
            if agent_context:
                media_match_context = f"{media_match_context}\n{agent_context}".strip()

            handoff_result = (sales_agent_decision or {}).get("handoff") or {}
            if handoff_result.get("handoff_required") and normalize_id(handoff_result.get("customer_reply")):
                reply_text = normalize_id(handoff_result.get("customer_reply"))
            elif msg_type == "text":
                reply_text = get_whatsapp_ai_reply(
                    sender_id,
                    text,
                    business,
                    media_context=media_match_context,
                    media_reply_hint=media_reply_hint,
                )
            elif media_type:
                reply_text = get_whatsapp_ai_reply(
                    sender_id,
                    text or "Customer sent a media message.",
                    business,
                    media_context=media_match_context,
                    media_reply_hint=media_reply_hint,
                )
            else:
                reply_text = get_whatsapp_ai_reply(
                    sender_id,
                    text,
                    business,
                    media_context=media_match_context,
                    media_reply_hint=media_reply_hint,
                )

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
                record_sales_agent_action(
                    business=business,
                    platform="whatsapp",
                    channel="whatsapp",
                    customer_id=sender_id,
                    action_type="reply_sent",
                    input_message=text,
                    decision=sales_agent_decision,
                    reply_sent=reply_text,
                    tool_used="product_matcher" if media_match else "",
                )
                if handoff_result.get("handoff_required"):
                    set_chat_ai_enabled(business.get("id"), "whatsapp", "whatsapp", sender_id, False)
                mark_processed(processed_message_ids, message_id)
            else:
                record_sales_agent_action(
                    business=business,
                    platform="whatsapp",
                    channel="whatsapp",
                    customer_id=sender_id,
                    action_type="reply_failed",
                    input_message=text,
                    decision=sales_agent_decision,
                    reply_sent=reply_text,
                    tool_used="product_matcher" if media_match else "",
                )
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
        "human_takeover_enabled": True,
        "telegram_bot_enabled": True,
        "whatsapp_enabled": True,
        "analytics_enabled": True,
        "automation_mode": "FULL_AUTO",
        "bot_language_mode": "auto",
        "memory_enabled": True,
        "memory_limit": 8,
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
        "human_takeover_enabled": True,
        "telegram_bot_enabled": True,
        "whatsapp_enabled": False,
        "analytics_enabled": True,
        "automation_mode": "FULL_AUTO",
        "bot_language_mode": "auto",
        "memory_enabled": True,
        "memory_limit": 8,
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
        "ai_reply_rules": "",
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
        "product_matcher_local_enabled": PRODUCT_MATCHER_LOCAL_ENABLED,
        "product_matcher_local_only": PRODUCT_MATCHER_LOCAL_ONLY,
        "product_matcher_local_catalog_table": PRODUCT_MATCHER_LOCAL_CATALOG_TABLE,
        "product_matcher_catalog_database": normalize_id(CATALOG_SUPABASE_URL).split("//")[-1].split(".")[0] if CATALOG_SUPABASE_URL else "",
        "product_matcher_urls": PRODUCT_MATCHER_API_URLS,
        "product_matcher_context_ttl_seconds": PRODUCT_MATCHER_CONTEXT_TTL_SECONDS,
    }


@app.post("/api/v2/video-analyzer/analyze")
async def api_video_analyzer_analyze(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"status": "error", "message": "Invalid JSON body"}, status_code=400)
        report, model = analyze_video_content(body)
        return {"status": "ok", "ok": True, "data": {"provider": "gemini", "model": model, "report": report}}
    except Exception as exc:
        if VideoAnalyzerError is not None and isinstance(exc, VideoAnalyzerError):
            return JSONResponse({"status": "error", "message": exc.message}, status_code=exc.status_code)
        return JSONResponse({"status": "error", "message": f"Video analyzer error: {exc}"}, status_code=500)


@app.get("/api/catalog/embeddings/status")
async def api_catalog_embeddings_status():
    if catalog_matcher_module is None:
        return {
            "status": "unavailable",
            "error": str(globals().get("CATALOG_MATCHER_IMPORT_ERROR", "catalog_matcher not loaded")),
        }
    try:
        return {"status": "ok", "embedding_status": catalog_matcher_module.get_embedding_status()}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.post("/api/catalog/embeddings/sync")
async def api_catalog_embeddings_sync(force: bool = True):
    if catalog_matcher_module is None:
        return {
            "status": "unavailable",
            "error": str(globals().get("CATALOG_MATCHER_IMPORT_ERROR", "catalog_matcher not loaded")),
        }
    try:
        return {"status": "ok", "result": catalog_matcher_module.sync_catalog_embeddings(force=bool(force))}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


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
    checks["product_matcher_local_enabled"] = "ok" if PRODUCT_MATCHER_LOCAL_ENABLED else "disabled"
    checks["product_matcher_local_catalog_rows_cached"] = len(
        PRODUCT_MATCHER_LOCAL_CATALOG_CACHE.get("rows", []) if isinstance(PRODUCT_MATCHER_LOCAL_CATALOG_CACHE, dict) else []
    )
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

    if is_local_dashboard_demo_mode():
        token = create_dashboard_auth_token(email=email, is_admin=True, role="super_admin")
        return {
            "status": "ok",
            "data": {
                "user": {
                    "id": "localdev-user",
                    "email": email,
                    "is_admin": True,
                    "role": "super_admin",
                },
                "token": token,
                "businesses": [build_local_dashboard_demo_business(email)],
            },
        }

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

    if is_local_dashboard_demo_mode():
        effective_role = "admin" if role == "admin" else "operator"
        token = create_dashboard_auth_token(email=email, is_admin=(effective_role == "admin"), role=effective_role)
        return {
            "status": "ok",
            "data": {
                "user": {
                    "id": "localdev-signup-user",
                    "email": email,
                    "is_admin": effective_role == "admin",
                    "role": effective_role,
                },
                "token": token,
                "businesses": [build_local_dashboard_demo_business(email)],
            },
        }

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
        rows = query.execute().data or []
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

    if is_local_dashboard_demo_mode():
        return {
            "status": "ok",
            "count": 0,
            "data": [],
        }

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
        query = supabase.table("inbox_messages").select(fields)
        if clean_business_id:
            if not can_access_business(access, clean_business_id):
                return {"status": "ok", "count": 0, "data": []}
            query = query.eq("business_id", clean_business_id)
        elif not access.get("is_admin"):
            allowed = access.get("business_ids") or []
            if not allowed:
                return {"status": "ok", "count": 0, "data": []}
            query = query.in_("business_id", allowed)

        if platform != "all":
            query = query.eq("platform", platform)

        if fast:
            recent_cutoff = (datetime.utcnow() - timedelta(days=CONVERSATIONS_FAST_LOOKBACK_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
            query = query.gte("created_at", recent_cutoff)
            target_rows = CONVERSATIONS_FAST_FETCH_LIMIT
        else:
            target_rows = CONVERSATIONS_MAX_FETCH_ROWS

        query = query.order("created_at", desc=True)

        rows = []
        offset = 0
        while len(rows) < target_rows:
            remaining = target_rows - len(rows)
            page_size = min(CONVERSATIONS_FETCH_BATCH_SIZE, remaining)
            page = query.range(offset, offset + page_size - 1).execute().data or []
            if not page:
                break
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)

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
            cache_tasks = []
            for row in rows:
                media_type = normalize_id(row.get("media_type")).lower()
                if media_type not in ("", "video", "file", "photo", "image"):
                    continue

                post_permalink = normalize_id(
                    row.get("post_permalink")
                    or (row.get("raw_payload") or {}).get("post_permalink")
                    or extract_instagram_permalink_from_payload(row.get("raw_payload") or {})
                )
                if not post_permalink:
                    continue

                media_url = normalize_id(row.get("media_url"))
                preview = {}
                if not is_instagram_reel_cache_url(media_url):
                    cache_id = instagram_reel_cache_id(post_permalink)
                    cached_path = find_instagram_reel_cache_path(cache_id)
                    if cached_path:
                        row["media_url"] = instagram_reel_cache_url(cached_path.name)
                        row["media_type"] = "video"
                        row["post_media_type"] = "video"
                    elif normalize_id(row.get("id")):
                        cache_tasks.append({
                            "id": normalize_id(row.get("id")),
                            "post_permalink": post_permalink,
                        })
                if not normalize_id(row.get("media_url")):
                    cached_preview = INSTAGRAM_PUBLIC_PREVIEW_CACHE.get(post_permalink)
                    if cached_preview and (time.time() - cached_preview[0]) < INSTAGRAM_PUBLIC_PREVIEW_CACHE_TTL_SECONDS:
                        preview = cached_preview[1] or {}

                preview_media_url = normalize_id(preview.get("media_url"))
                preview_image_url = normalize_id(preview.get("post_image_url"))
                preview_media_type = normalize_id(preview.get("post_media_type")).lower()

                changed = False
                if is_instagram_reel_cache_url(row.get("media_url")) and media_url != normalize_id(row.get("media_url")):
                    changed = True
                elif preview_media_url:
                    row["media_url"] = preview_media_url
                    changed = True
                if preview_image_url and not normalize_id(row.get("post_image_url")):
                    row["post_image_url"] = preview_image_url
                    changed = True
                if post_permalink and not normalize_id(row.get("post_permalink")):
                    row["post_permalink"] = post_permalink
                    changed = True
                if is_instagram_reel_cache_url(row.get("media_url")) and normalize_id(row.get("post_media_type")).lower() != "video":
                    row["post_media_type"] = "video"
                    changed = True
                elif preview_media_type and media_type in ("", "file"):
                    row["media_type"] = "video" if "video" in preview_media_type else ("photo" if "image" in preview_media_type else media_type)
                    changed = True

                if changed and normalize_id(row.get("id")):
                    update_rows.append({
                        "id": normalize_id(row.get("id")),
                        "media_url": normalize_id(row.get("media_url")),
                        "media_type": normalize_id(row.get("media_type")),
                        "post_image_url": normalize_id(row.get("post_image_url")),
                        "post_permalink": normalize_id(row.get("post_permalink")),
                        "post_media_type": normalize_id(row.get("post_media_type") or preview_media_type).lower(),
                    })

            if update_rows:
                def persist_preview_backfill(rows_to_update: list[dict]):
                    for item in rows_to_update:
                        try:
                            supabase.table("inbox_messages").update({
                                "media_url": item.get("media_url") or None,
                                "media_type": item.get("media_type") or None,
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

            if cache_tasks:
                seen_cache_tasks = set()
                for item in cache_tasks[:3]:
                    task_key = f"{item.get('id')}:{item.get('post_permalink')}"
                    if task_key in seen_cache_tasks:
                        continue
                    seen_cache_tasks.add(task_key)
                    if background_tasks is not None:
                        background_tasks.add_task(
                            cache_instagram_reel_for_message,
                            item.get("id"),
                            item.get("post_permalink"),
                        )

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
                ok, result = send_manual_instagram_dm(access_token, target_id, text, business)

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
        if not can_manage_business(access, business_id):
            return JSONResponse({"error": "Only owner/admin can turn bots on or off"}, status_code=403)
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


@app.get("/api/v2/stats")
async def get_stats_v2(
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    """Get dashboard statistics"""
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if is_local_dashboard_demo_mode():
        return {
            "status": "ok",
            "data": build_local_dashboard_demo_stats(),
        }

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
            businesses = _safe_rows(get_all_businesses())
        else:
            businesses = []
            if scoped_ids:
                businesses = _safe_rows(
                    supabase.table("businesses")
                    .select("id,bot_enabled")
                    .in_("id", scoped_ids)
                    .order("created_at", desc=True)
                    .execute()
                    .data
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
        stats_business_ids = [normalize_id(b.get("id")) for b in businesses if normalize_id(b.get("id"))]
        sales_metrics = build_sales_agent_metrics(stats_business_ids)
        payload.update(sales_metrics)
        payload["needing_human"] = sales_metrics.get("handoff_required_leads", 0)
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


@app.get("/api/v2/operator-deals/report.pdf")
async def get_operator_deals_report_pdf(
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

    role = normalize_id(access.get("role", "")).lower()
    if role not in BUSINESS_ADMIN_ROLES and not access.get("is_admin"):
        return JSONResponse({"error": "Only owner/admin can download operator reports"}, status_code=403)

    report = build_operator_deal_report_data(business_id)
    pdf_bytes = build_operator_deal_report_pdf(report)
    filename = f"operator-deals-{business_id}-{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v2/coaching-report")
async def get_coaching_report_v2(
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

    business = get_business_by_id(business_id) or {}
    lead_states = collect_sales_agent_lead_states(business_id)
    ai_actions = load_ai_actions_for_metrics([business_id], limit=500)
    try:
        messages = (
            supabase.table("inbox_messages")
            .select("business_id,platform,channel,customer_id,direction,content,created_at")
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .limit(500)
            .execute()
            .data
            or []
        )
    except Exception:
        messages = []

    report = build_daily_coaching_report(
        business=business,
        lead_states=lead_states,
        ai_actions=ai_actions,
        messages=messages,
    )
    return {"status": "ok", "data": report, "text": coaching_report_text(report)}


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
            "lead_scores",
            "lead_reasons",
            "lead_prices",
            "needs_human",
            "handoff_tasks",
            "instagram_dm_test_allowlist",
            "manual_clients",
            "manual_leads",
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
        if not can_manage_business(access, business_id):
            return JSONResponse({"status": "error", "message": "Only owner/admin can update bot settings"}, status_code=403)
        update_business(business_id, business_settings)
        updated["business_settings"] = list(business_settings.keys())

    ai_prompt_settings = payload.get("ai_prompt_settings") or {}
    if isinstance(ai_prompt_settings, dict) and ai_prompt_settings:
        if not can_manage_business(access, business_id):
            return JSONResponse({"status": "error", "message": "Only owner/admin can update AI prompt settings"}, status_code=403)
        upsert_ai_prompt_settings(business_id, ai_prompt_settings)
        updated["ai_prompt_settings"] = [
            key for key in ai_prompt_settings.keys() if key in AI_PROMPT_SETTING_FIELDS
        ]

    workspace_state = payload.get("workspace_state") or {}
    allowed_workspace_keys = {
        "lead_stages",
        "lead_prices",
        "manual_clients",
        "manual_leads",
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


@app.get("/api/instagram-reel-cache/{cache_name}")
async def get_instagram_reel_cache(
        cache_name: str,
        token: str = "",
        x_dashboard_secret: str = Header(default=""),
        range_header: str = Header(default="", alias="Range"),
):
    if require_dashboard_media_secret(token, x_dashboard_secret):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    cache_name = normalize_id(cache_name).lower()
    if not re.fullmatch(r"[a-f0-9]{32}\.(mp4|m4v|mov|webm)", cache_name):
        return JSONResponse({"status": "error", "message": "Invalid media id"}, status_code=400)

    path = INSTAGRAM_REEL_CACHE_DIR / cache_name
    try:
        resolved = path.resolve()
        cache_root = INSTAGRAM_REEL_CACHE_DIR.resolve()
        if cache_root not in resolved.parents or not resolved.exists() or not resolved.is_file():
            return JSONResponse({"status": "error", "message": "Cached video not found"}, status_code=404)

        total = resolved.stat().st_size
        mime = mimetypes.guess_type(str(resolved))[0] or "video/mp4"
        byte_range = parse_http_range(range_header, total)
        common_headers = {
            "Cache-Control": "private, max-age=86400",
            "Accept-Ranges": "bytes",
            "Content-Type": mime,
        }

        with open(resolved, "rb") as fh:
            if byte_range is not None:
                start, end = byte_range
                fh.seek(start)
                chunk = fh.read(end - start + 1)
                return Response(
                    content=chunk,
                    media_type=mime,
                    status_code=206,
                    headers={
                        **common_headers,
                        "Content-Range": f"bytes {start}-{end}/{total}",
                        "Content-Length": str(len(chunk)),
                    },
                )
            body = fh.read()
        return Response(
            content=body,
            media_type=mime,
            headers={**common_headers, "Content-Length": str(total)},
        )
    except Exception as exc:
        log("Instagram reel cache proxy error", str(exc))
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


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

    if is_local_dashboard_demo_mode():
        demo = build_local_dashboard_demo_business(access.get("email", ""))
        return {"status": "ok", "count": 1, "data": [demo]}

    query = supabase.table("businesses").select("*").order("created_at", desc=True)
    if not access.get("is_admin"):
        allowed = access.get("business_ids") or []
        if not allowed:
            return {"status": "ok", "count": 0, "data": []}
        query = query.in_("id", allowed)
    result = query.execute()
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

    if is_local_dashboard_demo_mode():
        return {"status": "ok", "count": 0, "data": []}

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
            ok, result = send_manual_instagram_dm(
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
        authorization: str = Header(default=""),
        x_dashboard_secret: str = Header(default=""),
):
    access = resolve_dashboard_access(authorization=authorization, x_dashboard_secret=x_dashboard_secret)
    if not access:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)
    if not can_access_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Forbidden"}, status_code=403)
    if not can_manage_business(access, business_id):
        return JSONResponse({"status": "error", "message": "Only owner/admin can turn bots on or off"}, status_code=403)

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
    if not can_manage_business(access, body.business_id):
        return JSONResponse({"status": "error", "message": "Only owner/admin can update bot settings"}, status_code=403)

    business = get_business_by_id(body.business_id)
    if not business:
        return JSONResponse({"status": "error", "message": "Business not found"}, status_code=404)

    settings = clean_business_settings(body.settings)
    if not settings:
        return JSONResponse({"status": "error", "message": "No valid settings to update"}, status_code=400)

    update_business(body.business_id, settings)
    next_bot_enabled = settings.get("bot_enabled", business.get("bot_enabled"))
    next_auto_reply_dms = settings.get("auto_reply_dms", business.get("auto_reply_dms"))
    next_auto_reply_comments = settings.get("auto_reply_comments", business.get("auto_reply_comments"))
    synced_chat_ai = {}

    # Settings is the owner/admin master control. When a channel is enabled here,
    # unpause existing per-chat rows for that channel so old manual pauses do not
    # invisibly override the business-level switch.
    if normalize_bool(next_bot_enabled, True):
        if settings.get("bot_enabled") is True and normalize_bool(next_auto_reply_dms, True):
            synced_chat_ai["instagram_dm"] = set_business_channel_chat_ai_enabled(body.business_id, "instagram", "dm", True)
        if settings.get("auto_reply_dms") is True:
            synced_chat_ai["instagram_dm"] = set_business_channel_chat_ai_enabled(body.business_id, "instagram", "dm", True)
        if settings.get("auto_reply_comments") is True or (settings.get("bot_enabled") is True and normalize_bool(next_auto_reply_comments, True)):
            synced_chat_ai["instagram_comment"] = set_business_channel_chat_ai_enabled(body.business_id, "instagram", "instagram_comment", True)

    message = "Settings updated"
    if synced_chat_ai:
        message = "Settings updated and matching chats were re-enabled"
    return {"status": "ok", "message": message, "synced_chat_ai": synced_chat_ai}


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
    if not can_manage_business(access, body.business_id):
        return JSONResponse({"status": "error", "message": "Only owner/admin can generate AI prompts"}, status_code=403)

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
    if not can_manage_business(access, body.business_id):
        return JSONResponse({"status": "error", "message": "Only owner/admin can update AI prompt settings"}, status_code=403)

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
