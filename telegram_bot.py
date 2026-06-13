import os
import re
import time
import asyncio
import io
import requests
from datetime import datetime
from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from supabase import create_client
from catalog_matcher import analyze_media_for_sales_reply_local as analyze_catalog_media

from agent_orchestrator import run_agent_cycle
from ai_audit_log import build_ai_action, save_ai_action

try:
    from telethon import TelegramClient, events
except Exception:
    TelegramClient = None
    events = None


telegram_router = APIRouter()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").lower().replace("@", "")
TELEGRAM_GROUP_REPLY_MODE = os.getenv("TELEGRAM_GROUP_REPLY_MODE", "mention_or_reply").strip().lower()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_USER_SESSION = os.getenv("TELEGRAM_USER_SESSION", "telegram_user_session")
ENABLE_TELEGRAM_USER_CLIENT = os.getenv("ENABLE_TELEGRAM_USER_CLIENT", "false").lower() == "true"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

MESSAGE_BUFFER = {}
USER_MESSAGE_BUFFER = {}
PROCESSED_BOT_MESSAGES = {}
PROCESSED_USER_MESSAGES = {}
TELEGRAM_USER_CLIENT = None
TELEGRAM_BOT_ID = None
TELEGRAM_CHAT_ADMINS_CACHE = {}
OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe").strip() or "gpt-4o-mini-transcribe"
MAX_AUDIO_TRANSCRIBE_BYTES = 25 * 1024 * 1024

OPTIONAL_INBOX_COLUMNS = [
    "customer_name",
    "chat_id",
    "is_read",
    "media_type",
    "media_url",
    "media_file_id",
]


def log(title, data=None):
    print("\n" + "=" * 80)
    print(title)
    if data is not None:
        print(data)
    print("=" * 80 + "\n")


def transcribe_audio_bytes(
    file_bytes: bytes,
    *,
    filename: str,
    mime_type: str,
    api_key: str,
    prompt: str = "",
    language: str = "",
    timeout: int = 120,
    logger=None,
) -> str:
    if not api_key or not file_bytes:
        return ""
    if len(file_bytes) > MAX_AUDIO_TRANSCRIBE_BYTES:
        if logger:
            logger("Audio transcription skipped", {"reason": "file_too_large", "bytes": len(file_bytes)})
        return ""

    data = {"model": OPENAI_TRANSCRIBE_MODEL}
    if prompt:
        data["prompt"] = prompt[:400]
    if language:
        data["language"] = language[:16]

    try:
        response = requests.post(
            OPENAI_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files={"file": (filename or "audio.webm", file_bytes, mime_type or "audio/webm")},
            timeout=timeout,
        )
        if not response.ok:
            if logger:
                logger("Audio transcription failed", {"status": response.status_code, "body": response.text[:800]})
            return ""
        body = response.json() if response.content else {}
        text = str(body.get("text") or "").strip()
        if not text and logger:
            logger("Audio transcription empty", {"status": response.status_code, "body": body})
        return text
    except Exception as exc:
        if logger:
            logger("Audio transcription error", str(exc))
        return ""


def normalize_bool(value, default=True):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enabled", "enable", "full_auto"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled", "disable", "manual", "human_only", "human"}:
        return False
    return default


def business_memory_limit(business: dict = None, default: int = 8) -> int:
    business = business or {}
    if not normalize_bool(business.get("memory_enabled"), True):
        return 0
    try:
        return max(0, min(20, int(business.get("memory_limit") or default)))
    except Exception:
        return default


def business_allows_human_handoff(business: dict = None) -> bool:
    return normalize_bool((business or {}).get("human_takeover_enabled"), True)


def business_allows_auto_reply(business: dict = None, channel: str = "") -> bool:
    business = business or {}
    if not normalize_bool(business.get("bot_enabled"), True):
        return False
    mode = str(business.get("automation_mode") or "").strip().upper()
    if mode in {"OFF", "DISABLED", "MANUAL", "HUMAN_ONLY"}:
        return False
    if normalize_text(channel).lower() in {"telegram_bot", "bot"}:
        return normalize_bool(business.get("telegram_bot_enabled"), True)
    return True


def normalize_text(value):
    return str(value or "").strip()


def standard_telegram_channel(channel: str = "") -> str:
    clean = normalize_text(channel).lower()
    if clean in {"telegram_bot_group", "telegram_group", "group", "supergroup"}:
        return "telegram_bot_group"
    if clean in {"telegram_user_private", "user_private"}:
        return "telegram_user_private"
    return "telegram_bot_private"


def telegram_conversation_id(business_id: str, channel: str, customer_id: str, chat_id: str = "") -> str:
    business_id = normalize_text(business_id)
    channel = standard_telegram_channel(channel)
    scope = normalize_text(chat_id or customer_id)
    if not business_id or not scope:
        return ""
    return f"telegram::{business_id}::{channel}::{scope}"


def lead_state_workspace_key(platform: str, customer_id: str, channel: str = "") -> str:
    platform = normalize_text(platform).lower()
    customer_id = normalize_text(customer_id)
    channel = normalize_text(channel).lower()
    if not platform or not customer_id:
        return ""
    if channel:
        return f"lead_state:{platform}:{channel}:{customer_id}"
    return f"lead_state:{platform}:{customer_id}"


def get_workspace_state(business_id: str) -> dict:
    business_id = normalize_text(business_id)
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
        return {
            normalize_text(row.get("state_key")): row.get("state_value")
            for row in rows
            if normalize_text(row.get("state_key"))
        }
    except Exception as exc:
        log("Could not load Telegram workspace state", str(exc))
        return {}


def upsert_workspace_state(business_id: str, state_key: str, state_value, updated_by: str = "telegram_bot"):
    business_id = normalize_text(business_id)
    state_key = normalize_text(state_key)
    if not business_id or not state_key:
        return
    try:
        supabase.table("dashboard_workspace_state").upsert(
            {
                "business_id": business_id,
                "state_key": state_key,
                "state_value": state_value,
                "updated_by": updated_by,
            },
            on_conflict="business_id,state_key",
        ).execute()
    except Exception as exc:
        log("Could not save Telegram workspace state", str(exc))


def normalize_agent_lead_state(state: dict = None) -> dict:
    state = dict(state or {})
    stage = normalize_text(state.get("stage") or "new").lower()
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
    state["stage"] = stage
    state["score"] = score
    state["lead_score"] = score
    state["handoff_required"] = bool(state.get("handoff_required") or stage == "handoff_required")
    return state


def get_customer_lead_state(platform: str, business_id: str, customer_id: str, channel: str = "") -> dict:
    key = lead_state_workspace_key(platform, customer_id, channel)
    if not key:
        return {}
    state = get_workspace_state(business_id)
    value = state.get(key)
    return normalize_agent_lead_state(value if isinstance(value, dict) else {})


def upsert_customer_lead_state(business_id: str, platform: str, customer_id: str, channel: str, lead_state: dict):
    key = lead_state_workspace_key(platform, customer_id, channel)
    if key:
        upsert_workspace_state(business_id, key, normalize_agent_lead_state(lead_state), updated_by="telegram_bot")


def telegram_recent_rows_for_agent(customer_id: str, channel: str, business: dict, limit: int = 20) -> list[dict]:
    history = get_recent_chat_history(customer_id, platform="telegram", channel=channel, limit=limit, business=business)
    rows = []
    for item in history:
        rows.append(
            {
                "direction": "outbound" if item.get("role") == "assistant" else "inbound",
                "content": item.get("content") or "",
                "media_type": "",
            }
        )
    return rows


def sales_agent_recent_messages(rows: list[dict]) -> list[dict]:
    return [
        {
            "direction": normalize_text(row.get("direction")).lower(),
            "content": normalize_text(row.get("content")),
            "media_type": normalize_text(row.get("media_type")).lower(),
        }
        for row in (rows or [])
        if isinstance(row, dict)
    ]


def sync_sales_agent_workspace_indexes(business_id: str, conversation_id: str, lead_state: dict):
    business_id = normalize_text(business_id)
    conversation_id = normalize_text(conversation_id)
    if not business_id or not conversation_id:
        return
    state = get_workspace_state(business_id)
    lead_stages = dict(state.get("lead_stages") or {})
    lead_scores = dict(state.get("lead_scores") or {})
    lead_reasons = dict(state.get("lead_reasons") or {})
    needs_human = dict(state.get("needs_human") or {})

    lead_stages[conversation_id] = normalize_text(lead_state.get("stage") or "new").lower()
    lead_scores[conversation_id] = int(lead_state.get("score") or lead_state.get("lead_score") or 0)
    lead_reasons[conversation_id] = {
        "summary": normalize_text(lead_state.get("qualification_summary")),
        "reasons": lead_state.get("score_reasons") if isinstance(lead_state.get("score_reasons"), list) else [],
        "intent": normalize_text(lead_state.get("primary_intent")),
        "updated_at": normalize_text(lead_state.get("updated_at") or lead_state.get("last_message_at")),
    }
    needs_human[conversation_id] = {
        "required": bool(lead_state.get("handoff_required")),
        "reason": normalize_text(lead_state.get("handoff_reason")),
        "priority": normalize_text(lead_state.get("handoff_priority")),
        "manager_note": normalize_text(lead_state.get("manager_note")),
        "updated_at": normalize_text(lead_state.get("updated_at") or lead_state.get("last_message_at")),
    }

    upsert_workspace_state(business_id, "lead_stages", lead_stages, updated_by="telegram_bot")
    upsert_workspace_state(business_id, "lead_scores", lead_scores, updated_by="telegram_bot")
    upsert_workspace_state(business_id, "lead_reasons", lead_reasons, updated_by="telegram_bot")
    upsert_workspace_state(business_id, "needs_human", needs_human, updated_by="telegram_bot")


def upsert_customer_lead_record(
    *,
    business_id: str,
    channel: str,
    customer_id: str,
    lead_state: dict,
):
    try:
        supabase.table("customer_leads").upsert(
            {
                "business_id": normalize_text(business_id),
                "platform": "telegram",
                "channel": standard_telegram_channel(channel),
                "customer_id": normalize_text(customer_id),
                "customer_name": normalize_text(lead_state.get("customer_name")),
                "phone": normalize_text(lead_state.get("phone")),
                "product_interest": normalize_text(lead_state.get("product_interest")),
                "stage": normalize_text(lead_state.get("stage") or "new").lower(),
                "score": int(lead_state.get("score") or lead_state.get("lead_score") or 0),
                "handoff_required": bool(lead_state.get("handoff_required")),
                "handoff_reason": normalize_text(lead_state.get("handoff_reason")),
                "qualification_summary": normalize_text(lead_state.get("qualification_summary")),
                "state": lead_state,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
            on_conflict="business_id,platform,channel,customer_id",
        ).execute()
    except Exception:
        pass


def create_handoff_operator_task_once(business_id: str, conversation_id: str, lead_state: dict):
    if not lead_state.get("handoff_required"):
        return
    state = get_workspace_state(business_id)
    task_index = dict(state.get("handoff_tasks") or {})
    if task_index.get(conversation_id):
        return
    bucket = state.get("operator_tasks") or {}
    items = bucket.get("items") if isinstance(bucket, dict) else []
    if not isinstance(items, list):
        items = []
    customer = normalize_text(lead_state.get("customer_name") or lead_state.get("customer_id") or "Customer")
    reason = normalize_text(lead_state.get("handoff_reason") or "review required")
    score = int(lead_state.get("score") or 0)
    task = {
        "id": f"task_{int(time.time() * 1000)}_tg",
        "text": f"Needs Human Attention: {customer}. Score {score}. Reason: {reason}.",
        "recipients": ["*"],
        "assign_mode": "all",
        "created_by": "telegram_bot",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    upsert_workspace_state(business_id, "operator_tasks", {"items": [task] + items[:199]}, updated_by="telegram_bot")
    task_index[conversation_id] = {"created_at": task["created_at"], "reason": reason}
    upsert_workspace_state(business_id, "handoff_tasks", task_index, updated_by="telegram_bot")


def write_ai_action_fallback(action: dict):
    business_id = normalize_text(action.get("business_id"))
    if not business_id:
        return
    state = get_workspace_state(business_id)
    bucket = state.get("ai_actions_recent") or {}
    items = bucket.get("items") if isinstance(bucket, dict) else []
    if not isinstance(items, list):
        items = []
    upsert_workspace_state(business_id, "ai_actions_recent", {"items": [action] + items[:199]}, updated_by="telegram_bot")


def record_sales_agent_action(
    *,
    business: dict,
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
            platform="telegram",
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
        log("Could not record Telegram sales agent action", str(exc))


def run_sales_agent_for_telegram(
    *,
    business: dict,
    customer_id: str,
    chat_id: str,
    channel: str,
    message_text: str,
    message_id: str = "",
    customer_name: str = "",
    media_type: str = "",
    media_match: dict = None,
) -> dict:
    business_id = normalize_text((business or {}).get("id"))
    customer_id = normalize_text(customer_id)
    channel = standard_telegram_channel(channel)
    if not business_id or not customer_id:
        return {}
    existing = get_customer_lead_state("telegram", business_id, customer_id, channel)
    recent_rows = telegram_recent_rows_for_agent(customer_id, channel, business, limit=20)
    decision = run_agent_cycle(
        business=business,
        business_id=business_id,
        platform="telegram",
        channel=channel,
        customer_id=customer_id,
        customer_name=customer_name,
        message_text=message_text,
        message_id=message_id,
        media_type=media_type or "",
        media_match=media_match or {},
        recent_messages=sales_agent_recent_messages(recent_rows),
        existing_lead_state=existing,
    )
    lead_state = normalize_agent_lead_state(decision.get("lead_state") or {})
    upsert_customer_lead_state(business_id, "telegram", customer_id, channel, lead_state)
    upsert_customer_lead_record(
        business_id=business_id,
        channel=channel,
        customer_id=customer_id,
        lead_state=lead_state,
    )
    conversation_id = telegram_conversation_id(business_id, channel, customer_id, chat_id)
    sync_sales_agent_workspace_indexes(business_id, conversation_id, lead_state)
    create_handoff_operator_task_once(business_id, conversation_id, lead_state)
    record_sales_agent_action(
        business=business,
        channel=channel,
        customer_id=customer_id,
        action_type="perceive_reason",
        input_message=message_text,
        decision=decision,
        tool_used="product_matcher" if media_match else "",
    )
    return decision


def get_business_channels(business_id: str, aliases: list[str]):
    business_id = normalize_text(business_id)
    aliases = [normalize_text(a).lower() for a in (aliases or []) if normalize_text(a)]
    if not business_id or not aliases:
        return []
    try:
        rows = (
            supabase.table("business_channels")
            .select("*")
            .eq("business_id", business_id)
            .in_("platform", aliases)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
        return rows
    except Exception:
        return []


def get_telegram_bot_token_for_business(business: dict = None):
    business_id = normalize_text((business or {}).get("id"))
    if business_id:
        rows = get_business_channels(business_id, ["telegram", "telegram_bot"])
        for row in rows:
            cfg = dict(row.get("config") or {})
            token = normalize_text(cfg.get("bot_token") or cfg.get("telegram_bot_token") or cfg.get("access_token"))
            if token:
                return token
    return TELEGRAM_BOT_TOKEN


def wants_catalog(text: str) -> bool:
    text = normalize_text(text).lower()
    keywords = [
        "catalog", "katalog", "каталог", "price", "prices", "narx", "narxlari",
        "narhi", "qancha", "qanchadan", "necha pul", "nechpul", "nechi pul",
        "цена", "цены", "стоимость", "сколько", "сколько стоит", "прайс",
        "model", "models", "modellari", "модель", "модели",
        "collection", "kolleksiya", "коллекция", "photo", "photos", "rasm", "rasmlar",
        "фото", "mahsulot", "mahsulotlar", "товар", "товары",
    ]
    return any(k in text for k in keywords)


def mentions_catalog(text: str) -> bool:
    text = normalize_text(text).lower()
    markers = ["catalog", "katalog", "каталог", "katalo", "катало", "products", "товар", "mahsulot"]
    return any(m in text for m in markers)


def is_greeting_only(text: str) -> bool:
    s = normalize_text(text).lower()
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


def is_low_signal_message(text: str) -> bool:
    s = normalize_text(text)
    if not s:
        return False

    compact = re.sub(r"\s+", "", s)
    emoji_only_re = re.compile(r"^[\u2600-\u27BF\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF\u200d\ufe0f]+$")
    if compact and emoji_only_re.fullmatch(compact):
        return True

    if compact.lower() in {"+", "++", "ok", "okk"}:
        return True

    return False


def looks_like_sales_question(text: str) -> bool:
    s = normalize_text(text).lower()
    if not s:
        return False
    keywords = [
        "price", "prices", "catalog", "delivery", "shipping", "order", "buy", "purchase",
        "narx", "narxlari", "qancha", "katalog", "yetkazib", "buyurtma", "zakaz", "buyurtma bermoqchiman",
        "zakaz qilmoqchiman", "olmoqchiman", "olaman", "mahsulot", "model", "rang",
        "цена", "цены", "каталог", "доставка", "заказ", "купить", "товар", "оформить",
        "баға", "каталог", "жеткізу", "тапсырыс", "тауар", "сатып алу",
    ]
    if any(k in s for k in keywords):
        return True

    # Quantity/wholesale intent patterns like "2 kilo", "5 dona", "10 kg".
    if re.search(r"\b\d+\s*(kg|kilo|кг|dona|donaa|ta|pcs|piece|qop|мешок)\b", s):
        return True

    return False


def wants_deal_handoff(text: str) -> bool:
    s = normalize_text(text).lower()
    if not s:
        return False
    keywords = [
        "deal", "make a deal", "let's deal", "order", "buy", "purchase", "ready to buy",
        "заказ", "оформить", "оформим", "куплю", "покупка", "сделка",
        "zakaz", "zakaz qilmoqchiman", "buyurtma", "buyurtma bermoqchiman", "olaman", "olmoqchiman", "kelishuv",
        "тапсырыс", "сатып аламын", "келісім",
    ]
    return any(k in s for k in keywords)


def business_contact_text(business: dict = None) -> str:
    business = business or {}
    return normalize_text(
        business.get("telegram_admin")
        or business.get("telegram_single")
        or business.get("sales_phone")
        or business.get("catalog_link")
        or ""
    )


def deal_handoff_text(lang: str, business: dict = None) -> str:
    contact = business_contact_text(business)
    if not contact:
        if lang == "en":
            return "Great. Please leave your name and phone number, and our manager will contact you."
        if lang == "ru":
            return "Отлично. Оставьте, пожалуйста, имя и номер телефона, менеджер свяжется с вами."
        if lang == "kk":
            return "Керемет. Атыңыз бен телефон нөміріңізді қалдырыңыз, менеджер сізбен байланысады."
        return "Zo'r. Ismingiz va telefon raqamingizni qoldiring, menejerimiz siz bilan bog'lanadi."

    if lang == "en":
        return f"Great. To finalize the deal, please contact us here: {contact}."
    if lang == "ru":
        return f"Отлично. Чтобы оформить сделку, свяжитесь с нами здесь: {contact}."
    if lang == "kk":
        return f"Керемет. Мәмілені рәсімдеу үшін бізге осы жерге жазыңыз: {contact}."
    return f"Zo'r. Kelishuvni yakunlash uchun shu yerga yozing: {contact}."


def detect_customer_language(text: str) -> str:
    lower = normalize_text(text).lower()
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
    uzbek_cyrillic_markers = {
        "салом", "ассалому", "алайкум", "нарх", "канча", "қанча", "нечпул", "нечпуд",
        "неча", "пул", "керак", "олмок", "олмоқ", "сотиб", "махсулот", "маҳсулот",
        "каталог", "манзил", "рахмат", "раҳмат", "борми", "шу", "халат", "тошкент",
        "тошкентдам", "бормм", "донага", "бераслами", "юборасизми",
        "етказиб", "йетказиб", "доставка", "оптом", "оптима", "улгуржи",
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
    if words & uzbek_cyrillic_markers or any(m in lower for m in uzbek_cyrillic_markers):
        return "uz"
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
        return "Mijozning oxirgi xabari o'zbek tilida, hattoki kirill yozuvida bo'lsa ham. Faqat o'zbek tilida javob ber. Rus tilida javob berma."
    return ""


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
        value = normalize_text(business.get(key))
        if not value:
            continue
        if key == "telegram_bag":
            lower_value = value.lower()
            has_pack_word = any(marker in lower_value for marker in ["qop", "meshok", "мешок", "bag"])
            has_size_word = any(marker in lower_value for marker in ["razmer", "size", "размер", "o'lcham", "olcham", "өлшем"])
            if not (has_pack_word and has_size_word):
                continue
        return value

    combined = "\n".join([
        normalize_text(business.get("knowledge")),
        normalize_text(business.get("ai_reply_rules")),
        normalize_text(business.get("faq")),
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
        raw = normalize_text(business.get(key))
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
            }.get(normalize_text(lang).lower(), "Modelni yuborsangiz, aniq razmerlarini aniqlab beraman.")
            return f"{configured_rule.rstrip('.!?')}. {hint}"
        return configured_rule

    lang = normalize_text(lang).lower()
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


def wants_default_pack_size_info(text: str) -> bool:
    low = normalize_text(text).lower()
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


def get_catalog_link(business: dict) -> str:
    link = (business or {}).get("catalog_link") or (business or {}).get("catalog") or (business or {}).get("website") or ""
    link = normalize_text(link)
    if link and not link.startswith(("http://", "https://")):
        link = f"https://{link}"
    return link


def wants_business_location(text: str) -> bool:
    s = normalize_text(text).lower()
    if not s:
        return False
    markers = [
        "qayerda", "manzil", "address", "location", "where are you", "where located",
        "joylashgan", "uzbekistan", "o'zbekiston", "uzbekiston", "andijan", "andijon",
        "адрес", "где вы", "локация", "узбекистан", "андижан",
    ]
    return any(marker in s for marker in markers)


def extract_business_location_summary(business: dict = None) -> str:
    business = business or {}
    combined = "\n".join([
        normalize_text(business.get("faq")),
        normalize_text(business.get("knowledge")),
        normalize_text(business.get("delivery_info")),
    ]).strip()
    if not combined:
        return ""
    lines = [re.sub(r"\s+", " ", line).strip(" -") for line in combined.splitlines() if normalize_text(line)]
    location_lines = []
    for line in lines:
        lower = line.lower()
        if lower.endswith("?") or "qayerda" in lower or "address?" in lower or "адрес" == lower.strip():
            continue
        if any(token in lower for token in [
            "manzil", "address", "o'zbekiston", "uzbekiston", "uzbekistan",
            "andijon", "andijan", "qoratut", "aeroport", "airport",
            "адрес", "узбекистан", "андижан",
        ]):
            location_lines.append(line)
        if len(location_lines) >= 2:
            break
    summary = " ".join(location_lines).strip()
    summary = re.sub(r"^\d+\.\s*", "", summary)
    summary = re.sub(r"\s+", " ", summary).strip()
    return summary[:320]


def business_location_reply(user_text: str, business: dict = None) -> str:
    lang = detect_customer_language(user_text)
    summary = extract_business_location_summary(business)
    if summary:
        return summary
    if lang == "en":
        return "Yes, we are located in Uzbekistan, Andijan. Please contact our manager for the exact address details."
    if lang == "ru":
        return "Да, мы находимся в Узбекистане, Андижане. За точными деталями адреса можно обратиться к менеджеру."
    if lang == "kk":
        return "Иә, біз Өзбекстан, Әндіжан қаласында орналасқанбыз. Нақты мекенжайды менеджер нақтылап береді."
    return "Ha, biz O'zbekiston, Andijonda joylashganmiz. Aniq manzilni menejerimiz tasdiqlab beradi."


def wants_business_scope_intro(text: str) -> bool:
    s = normalize_text(text).lower()
    if not s:
        return False
    markers = [
        "which factory", "what factory", "what do you produce", "do you produce", "factory?",
        "qanaqa fabrika", "qaysi fabrika", "nima ishlab chiqarasiz", "nima tikasiz",
        "какая фабрика", "что производите", "что шьете",
    ]
    return any(marker in s for marker in markers)


def business_scope_reply(user_text: str, business: dict = None) -> str:
    lang = detect_customer_language(user_text)
    business_name = normalize_text((business or {}).get("business_name")) or "Milana Premium"
    if lang == "en":
        return f"{business_name} is a clothing manufacturer in Uzbekistan. We mostly produce women's wear, and we also make kids' and men's clothing."
    if lang == "ru":
        return f"{business_name} — швейная фабрика в Узбекистане. В основном мы производим женскую одежду, а также шьем детскую и мужскую одежду."
    if lang == "kk":
        return f"{business_name} — Өзбекстандағы тігін фабрикасы. Негізінен әйелдер киімін тігеміз, сонымен қатар балалар мен ерлер киімін де шығарамыз."
    return f"{business_name} O'zbekistondagi kiyim ishlab chiqaruvchi fabrika. Asosan ayollar kiyimlarini ishlab chiqaramiz, shu bilan birga bolalar va erkaklar kiyimlari ham tikamiz."


def clean_ai_reply_for_catalog(reply_text: str, business: dict) -> str:
    catalog_link = get_catalog_link(business)
    if catalog_link and catalog_link in (reply_text or ""):
        reply_text = (reply_text or "").replace(catalog_link, "")
    return re.sub(r"\s+", " ", normalize_text(reply_text)).strip()


def complete_sentence_reply(text: str, limit: int = 700) -> str:
    text = normalize_text(text)
    text = re.sub(r"(?:joylashuv xaritasini\s*)?(?:ko['‘’`]?rish|ochish)\s+uchun\s*[:：]?\s*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"(?:link|havola|ссылка)\s*[:：]\s*$", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return ""
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].strip()
    if not re.search(r"[.!?…]$", text):
        text += "."
    return text


def should_reply_in_group(message):
    """
    Group reply modes:
    - all: reply to all user messages in groups/supergroups
    - mention_or_reply: reply only when mentioned/replied to
    """
    mode = TELEGRAM_GROUP_REPLY_MODE or "mention_or_reply"

    text = normalize_text(message.get("text")).lower()
    mention = f"@{TELEGRAM_BOT_USERNAME}" if TELEGRAM_BOT_USERNAME else ""
    has_mention = bool(mention and mention in text)

    reply_from = (message.get("reply_to_message") or {}).get("from") or {}
    replied_to_bot = is_own_or_any_bot_user(reply_from)
    is_reply_chain = bool(message.get("reply_to_message"))

    # Never join user-to-user reply chains unless they explicitly address the bot.
    if is_reply_chain and not replied_to_bot and not has_mention:
        return False

    if mode == "all":
        return True

    # Mention/reply mode: answer if directly addressed,
    # OR if message is standalone and clearly a sales question.
    if has_mention or replied_to_bot:
        return True

    if not is_reply_chain and looks_like_sales_question(text):
        return True

    return False


def already_processed(cache, event_id, ttl=3600):
    if not event_id:
        return False

    now = time.time()
    expired = [key for key, value in cache.items() if now - value > ttl]

    for key in expired:
        cache.pop(key, None)

    if event_id in cache:
        return True

    cache[event_id] = now
    return False


def safe_json(response):
    if response is None:
        return {}
    try:
        return response.json()
    except Exception:
        return {"text": getattr(response, "text", "")}


def get_telegram_bot_id(business: dict = None):
    global TELEGRAM_BOT_ID

    if TELEGRAM_BOT_ID:
        return TELEGRAM_BOT_ID

    token = get_telegram_bot_token_for_business(business)
    if not token:
        return None

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=15,
        )
        data = safe_json(response)
        if response.ok and data.get("ok"):
            TELEGRAM_BOT_ID = str(data.get("result", {}).get("id") or "")
            return TELEGRAM_BOT_ID or None
    except Exception as exc:
        log("Could not resolve Telegram bot id", str(exc))

    return None


def get_group_admin_ids(chat_id, ttl_seconds=300, business: dict = None):
    chat_id = str(chat_id or "")
    token = get_telegram_bot_token_for_business(business)
    if not chat_id or not token:
        return set()

    now = time.time()
    cached = TELEGRAM_CHAT_ADMINS_CACHE.get(chat_id)
    if cached and now - float(cached.get("ts", 0)) < ttl_seconds:
        return set(cached.get("ids", []))

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getChatAdministrators",
            params={"chat_id": chat_id},
            timeout=20,
        )
        data = safe_json(response)
        ids = set()
        if response.ok and data.get("ok"):
            for item in data.get("result", []) or []:
                user = item.get("user") or {}
                uid = str(user.get("id") or "")
                if uid:
                    ids.add(uid)
        TELEGRAM_CHAT_ADMINS_CACHE[chat_id] = {"ts": now, "ids": list(ids)}
        return ids
    except Exception as exc:
        log("Could not fetch Telegram group admins", {"chat_id": chat_id, "error": str(exc)})
        return set()


def is_group_admin(chat_id, user_id, business: dict = None):
    uid = str(user_id or "")
    if not uid:
        return False
    return uid in get_group_admin_ids(chat_id, business=business)


def is_own_or_any_bot_user(user, business: dict = None):
    if not user:
        return False

    user_id = str(user.get("id") or "")
    username = normalize_text(user.get("username")).lower().replace("@", "")
    bot_id = get_telegram_bot_id(business)

    return (
        bool(user.get("is_bot"))
        or bool(bot_id and user_id == bot_id)
        or bool(TELEGRAM_BOT_USERNAME and username == TELEGRAM_BOT_USERNAME)
    )


def is_telegram_bot_authored_message(message, business: dict = None):
    if not message:
        return True

    if is_own_or_any_bot_user(message.get("from") or {}, business):
        return True

    if is_own_or_any_bot_user(message.get("via_bot") or {}, business):
        return True

    # Posts from channels/anonymous admins do not represent a customer DM.
    # Treat them as non-customer events so the sales bot never talks to itself.
    if message.get("sender_chat"):
        return True

    return False


def insert_inbox_message(data):
    payload = dict(data)
    removed = []

    for _ in range(len(OPTIONAL_INBOX_COLUMNS) + 2):
        try:
            return supabase.table("inbox_messages").insert(payload).execute()
        except Exception as exc:
            message = str(exc)
            match = re.search(r"Could not find the '([^']+)' column", message)
            missing_column = match.group(1) if match else ""

            if missing_column and missing_column in payload:
                payload.pop(missing_column, None)
                removed.append(missing_column)
                continue

            removable = next((key for key in OPTIONAL_INBOX_COLUMNS if key in payload), None)
            if removable:
                payload.pop(removable, None)
                removed.append(removable)
                continue

            raise

    log("Inserted Telegram message with fallback columns removed", removed)
    return None


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
    except Exception as exc:
        log("Could not check chat AI setting", str(exc))
        return True


def set_chat_ai_enabled(business_id, platform, channel, customer_id, enabled):
    try:
        payload = {
            "business_id": business_id,
            "platform": platform,
            "channel": channel or "",
            "customer_id": str(customer_id),
            "ai_enabled": bool(enabled),
        }
        supabase.table("chat_ai_settings").upsert(
            payload,
            on_conflict="business_id,platform,channel,customer_id",
        ).execute()
    except Exception as exc:
        log("Could not update Telegram chat AI setting", str(exc))


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
    "global_prompt": (
        "You are the business virtual sales assistant. "
        "Sound natural for Uzbek Telegram sales conversations, not like customer support software. "
        "When introducing yourself, be transparent that you are the business virtual assistant. "
        "Represent the company clearly, answer in the customer's language, and guide the customer toward the next useful buying step. "
        "Keep every reply short and natural. Ask one question at a time. "
        "Never pretend to be a human salesperson. "
        "Do not repeat product names in every message or sound corporate."
    ),
    "telegram_prompt": (
        "Telegram rules:\n"
        "- Sound like a natural Telegram sales manager.\n"
        "- In groups, answer only when mentioned or replied to.\n"
        "- Avoid long lists unless the customer asks for a list.\n"
        "- Share Telegram catalog/group links only when relevant.\n"
        "- If customer is ready to make a deal/order, use the configured business contact or ask for their name and phone."
    ),
    "opening_message": "Assalomu alaykum 😊 Men virtual yordamchiman. Mahsulot, narx, yetkazib berish yoki buyurtma bo‘yicha yordam beraman.",
    "lead_collection_rules": (
        "Do not ask for name, phone, address, or full details at the beginning. "
        "First answer naturally and understand what the customer wants. "
        "Ask only one small follow-up question at a time. "
        "Ask for phone/address only after the customer is clearly ready to order."
    ),
    "sales_rules": (
        "Answer the exact question first. Ask only one follow-up question at a time. "
        "For price questions ('narx', 'nechpul', 'qancha', 'цена', 'сколько'), answer price directly first if known. "
        "For qop/size questions, use the configured qop/size rule from Business facts. Do not invent size composition. "
        "Keep replies short and comfortable: usually 1-3 short sentences. "
        "Do not ask for phone number or address at the beginning. "
        "Do not repeat product names every message. "
        "Do not over-focus on only the product the customer first mentioned if they are still choosing. "
        "Avoid corporate phrases like 'manager will contact you' unless the customer asks for a human or is ready to order. "
        "Do not repeat the same request or paragraph. "
        "Do not repeat the same question the customer already answered. "
        "If customer says they cannot buy now, stop selling and close politely in one short line. "
        "If the customer is annoyed, apologizes, says the bot is bad, or asks to stop, reply very briefly and do not sell."
    ),
    "handoff_rules": (
        "If an important buying detail is missing, ask one simple follow-up question instead of saying a manager will clarify. "
        "Only mention a manager when the customer asks for a human, is ready to order, or the exact detail really requires confirmation. "
        "Do not invent information."
    ),
}


def get_ai_prompt_settings(business_id):
    settings = dict(DEFAULT_AI_PROMPT_SETTINGS)
    if not business_id:
        return settings

    try:
        rows = (
            supabase.table("ai_prompt_settings")
            .select("*")
            .eq("business_id", str(business_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows:
            row = rows[0]
            for key in [
                "global_prompt",
                "telegram_prompt",
                "opening_message",
                "lead_collection_rules",
                "sales_rules",
                "handoff_rules",
            ]:
                if row.get(key):
                    settings[key] = row.get(key)
    except Exception as exc:
        log("Could not load Telegram AI prompt settings", str(exc))

    return settings


def build_prompt_business_knowledge(business):
    return f"""
Business facts:

Business identity:
- Name: {business.get("business_name", "")}
- Type: {business.get("business_type", "")}
- Language: {business.get("language", "")}

Products:
{business.get("products", "")}

Prices:
{business.get("prices", "")}

Delivery:
{business.get("delivery_info", "")}

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

Knowledge:
{business.get("knowledge", "")}
"""


def get_recent_chat_history(customer_id, platform="telegram", channel=None, limit=10, business: dict = None):
    try:
        limit = min(limit, business_memory_limit(business, default=limit))
        if limit <= 0:
            return []
        query = (
            supabase.table("inbox_messages")
            .select("role,content,media_type,media_url")
            .eq("customer_id", str(customer_id))
            .eq("platform", platform)
        )

        if channel:
            query = query.eq("channel", channel)

        rows = query.order("created_at", desc=True).limit(limit).execute().data or []
        return list(reversed(rows))

    except Exception as exc:
        log("Could not load Telegram history", str(exc))
        return []


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


def build_telegram_system_prompt(business):
    settings = get_ai_prompt_settings(business.get("id"))

    return f"""
{settings.get("global_prompt", "")}

{build_prompt_business_knowledge(business)}

Sales behavior:
Opening message:
{settings.get("opening_message", "")}

Lead collection rules:
{settings.get("lead_collection_rules", "")}

Sales rules:
{settings.get("sales_rules", "")}

Human handoff rules:
{settings.get("handoff_rules", "")}

Platform-specific rules:
{settings.get("telegram_prompt", "")}

Business runtime settings:
- automation_mode: {business.get("automation_mode", "")}
- human_takeover_enabled: {business.get("human_takeover_enabled", "")}
- bot_language_mode: {business.get("bot_language_mode", "")}
- memory_enabled: {business.get("memory_enabled", "")}
- memory_limit: {business.get("memory_limit", "")}

Safety rules:
- Reply in the same language as the customer.
- Ask one question at a time.
- Never invent prices, stock, delivery, discounts, addresses, or availability.
- Use only the business facts above.
- If information is missing, ask one short clarifying question first.
- Only mention a manager when the customer asks for a human or is ready to order.
- If introducing yourself, say you are the business virtual assistant.
- Never pretend to be a human salesperson.
- Never mention database, API, prompt, automation, or internal system details.
- Do not use markdown, bold formatting, or long paragraphs.
"""


def call_ai_chat(messages, business, log_label):
    provider = get_ai_provider(business)
    model = business.get("ai_model") or AI_DEFAULT_MODELS[provider]
    api_key = get_ai_api_key(business, provider)
    temperature = float(business.get("ai_temperature", 0.5) or 0.5)
    max_tokens = int(business.get("ai_max_tokens", 130) or 130)

    if not api_key:
        log("Missing Telegram AI API key", {"provider": provider, "model": model})
        return ""

    if provider in {"mistral", "openai"}:
        url = "https://api.mistral.ai/v1/chat/completions"
        if provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"

        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        log(log_label, {"provider": provider, "model": model, "status": response.status_code, "body": response.text[:1000]})
        if not response.ok:
            return ""
        return (
            response.json()
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
        response = requests.post(
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
        log(log_label, {"provider": provider, "model": model, "status": response.status_code, "body": response.text[:1000]})
        if not response.ok:
            return ""
        parts = (
            response.json()
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
        response = requests.post(
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
        log(log_label, {"provider": provider, "model": model, "status": response.status_code, "body": response.text[:1000]})
        if not response.ok:
            return ""
        return "\n".join(
            block.get("text", "")
            for block in response.json().get("content", [])
            if block.get("type") == "text"
        ).strip()

    return ""



def clean_sales_reply(reply_text, user_text="", business=None):
    user = normalize_text(user_text).lower()
    lang = detect_customer_language(user_text)

    if wants_deal_handoff(user_text) and business_allows_human_handoff(business):
        return deal_handoff_text(lang, business)

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

    if any(phrase in user for phrase in [
        "ololmayapman",
        "ololmayman",
        "qarzga",
        "hozircha olmayman",
        "hozircha yo'q",
        "keyinroq",
        "pul yo'q",
    ]):
        return "Tushunarli 😊 Muammo emas, qachon qulay bo'lsa yozing."

    text = normalize_text(reply_text)
    if looks_like_internal_prompt_leak(text):
        summary = customer_safe_price_summary(business)
        if any(k in user for k in ["narx", "nechpul", "qancha", "цена", "сколько", "price"]):
            if summary:
                return f"{summary} Sizga qaysi mahsulot yoki model kerak?"
            return "Aniq narxni menejerimiz tasdiqlaydi. Sizga qaysi mahsulot yoki model kerak?"
    if not text:
        if lang == "en":
            return "Hello! How can I help you?"
        if lang == "ru":
            return "Здравствуйте! Чем могу помочь?"
        if lang == "kk":
            return "Сәлеметсіз бе! Қалай көмектесе аламын?"
        return "Assalomu alaykum 😊 Qanday yordam kerak?"

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

    question_count = text.count("?")
    if question_count > 1:
        first_q = text.find("?")
        tail = text[first_q + 1:]
        tail = tail.replace("?", ".")
        text = text[:first_q + 1] + tail

    price_ask = any(k in user for k in ["narx", "nechpul", "qancha", "цена", "сколько", "price"])
    has_number = bool(re.search(r"\d", text))
    if price_ask and not has_number:
        if lang == "en":
            text = "You can view our catalog through the link. Which products are you interested in?"
        elif lang == "ru":
            text = "Вы можете посмотреть наш каталог по ссылке. Какие товары вас интересуют?"
        elif lang == "kk":
            text = "Біздің каталогты төмендегі сілтеме арқылы көре аласыз. Қай тауарлар сізді қызықтырады?"
        else:
            text = "Katalogimizga quyidagi havoladan kirishingiz mumkin. Qaysi mahsulotlar sizni qiziqtirmoqda?"

    if lang == "en":
        has_cyr = bool(re.search(r"[А-Яа-яЁё]", text))
        uz_markers = ("salom", "assalomu", "alaykum", "qaysi", "mahsulot", "katalog")
        low = text.lower()
        if has_cyr or any(m in low for m in uz_markers):
            if price_ask:
                text = "You can view our catalog through the link. Which products are you interested in?"
            else:
                text = "Hello! Of course. Which products are you interested in?"

    if is_greeting_only(user_text) and mentions_catalog(text):
        if lang == "en":
            text = "Hello! How can I help you today?"
        elif lang == "ru":
            text = "Здравствуйте! Чем могу помочь?"
        elif lang == "kk":
            text = "Сәлеметсіз бе! Қалай көмектесе аламын?"
        else:
            text = "Assalomu alaykum 😊 Qanday yordam kerak?"

    if mentions_media_analysis_or_attachment_ack(text):
        text = neutral_media_redirect_reply(user_text, business)

    text = complete_sentence_reply(text, limit=900)
    if text:
        return text
    if lang == "en":
        return "Understood."
    if lang == "ru":
        return "Понял."
    if lang == "kk":
        return "Түсіндім."
    return "Tushunarli 👍"


def _extract_first_price_range(raw_text: str) -> str:
    text = normalize_text(raw_text)
    if not text:
        return ""
    match = re.search(r"(\d[\d\s]{0,6}(?:[–-]\d[\d\s]{0,6}))\s*(\$|usd|dollar|dollor|доллар|so['’]?m|sum)?", text, re.IGNORECASE)
    if not match:
        match = re.search(r"(?<!\+)(\d{2,6})\s*(\$|usd|dollar|dollor|доллар|so['’]?m|sum)", text, re.IGNORECASE)
    if not match:
        return ""
    amount = re.sub(r"\s+", "", match.group(1) or "")
    currency = normalize_text(match.group(2))
    return f"{amount} {currency}".strip()


def customer_safe_price_summary(business: dict = None) -> str:
    business = business or {}
    raw_prices = normalize_text(business.get("prices"))
    if not raw_prices:
        return ""

    lower = raw_prices.lower()
    phone = normalize_text(business.get("sales_phone"))
    approx_price = _extract_first_price_range(raw_prices)
    has_internal_rules = any(marker in lower for marker in [
        "bot ",
        "bot-",
        "mijozni",
        "yo'naltir",
        "aytmasin",
        "so'rasa",
        "menejerimiz",
        "sotuvch",
        "minimal buyurtma",
    ])

    if has_internal_rules:
        if approx_price and phone:
            return f"Taxminiy narx {approx_price} atrofida. Aniq narx bo'yicha menejer yordam beradi: {phone}."
        if approx_price:
            return f"Taxminiy narx {approx_price} atrofida. Aniq narx modelga qarab tasdiqlanadi."
        if phone:
            return f"Aniq narxni menejer tasdiqlaydi: {phone}."
        return "Aniq narx modelga va buyurtmaga qarab tasdiqlanadi."

    first_sentence = re.split(r"(?<=[.!?])\s+|\n+", raw_prices)[0].strip(" -")
    first_sentence = re.sub(r"\s+", " ", first_sentence).strip()
    return first_sentence[:220] if first_sentence else ""


def looks_like_internal_prompt_leak(text: str) -> bool:
    clean = normalize_text(text).lower()
    if not clean:
        return False
    leak_markers = [
        "bot aniq narx aytmasin",
        "narx so'ragan mijozni",
        "mijozni telegram",
        "mijozni sotuv agentiga",
        "bot:",
        "do not",
        "ai reply rules",
        "business facts",
        "opening message",
    ]
    return any(marker in clean for marker in leak_markers)


def mentions_media_analysis_or_attachment_ack(text: str) -> bool:
    clean = normalize_text(text).lower()
    if not clean:
        return False
    patterns = [
        "thanks for the photo",
        "thank you for the photo",
        "thanks for the video",
        "rasm uchun rahmat",
        "foto uchun rahmat",
        "video uchun rahmat",
        "спасибо за фото",
        "спасибо за видео",
        "фото үшін рахмет",
        "видео үшін рахмет",
        "clear photo",
        "aniqroq rasm",
        "четкое фото",
        "анық фото",
        "i checked the photo",
        "i checked the video",
        "analys",
        "recogniz",
    ]
    return any(pattern in clean for pattern in patterns)


def neutral_media_redirect_reply(user_text: str, business: dict = None) -> str:
    lang = detect_customer_language(user_text)
    summary = customer_safe_price_summary(business) if any(k in normalize_text(user_text).lower() for k in ["narx", "nechpul", "qancha", "цена", "сколько", "price"]) else ""
    if summary:
        if lang == "en":
            return f"{summary} Please send the exact model name/code."
        if lang == "ru":
            return f"{summary} Отправьте точное название или код модели."
        if lang == "kk":
            return f"{summary} Нақты модель атауын не кодын жіберіңіз."
        return f"{summary} Aniq model nomi yoki kodini yuboring."
    if lang == "en":
        return "Please send the exact model name/code, and I will help further."
    if lang == "ru":
        return "Отправьте точное название или код модели, и я помогу дальше."
    if lang == "kk":
        return "Нақты модель атауын не кодын жіберіңіз, мен ары қарай көмектесемін."
    return "Aniq model nomi yoki kodini yuboring, men keyin davom ettiraman."

def get_ai_reply(
    user_text,
    business,
    customer_id,
    channel="telegram_bot_private",
    media_context: str = "",
    media_reply_hint: str = "",
    lead_state: dict = None,
):
    if wants_business_location(user_text):
        return business_location_reply(user_text, business)

    if wants_business_scope_intro(user_text):
        return business_scope_reply(user_text, business)

    size_pack_reply = default_pack_size_reply(user_text, business)
    if size_pack_reply:
        return size_pack_reply

    history = get_recent_chat_history(
        customer_id=customer_id,
        platform="telegram",
        channel=channel,
        limit=20,
        business=business,
    )

    messages = [{"role": "system", "content": build_telegram_system_prompt(business)}]
    if lead_state:
        messages.append({
            "role": "system",
            "content": (
                "Known customer sales state:\n"
                f"- stage: {lead_state.get('stage', 'new')}\n"
                f"- score: {lead_state.get('score', 0)}\n"
                f"- phone_collected: {'yes' if lead_state.get('phone_collected') else 'no'}\n"
                f"- name_collected: {'yes' if lead_state.get('name_collected') else 'no'}\n"
                "- Do not ask again for fields already collected."
            ),
        })
    if media_context:
        messages.append({"role": "system", "content": media_context})
    if media_reply_hint:
        messages.append({
            "role": "system",
            "content": f"Suggested product answer from media matcher: {media_reply_hint}. Keep the answer in the customer's language.",
        })

    for msg in history:
        role = msg.get("role") or "user"
        content = msg.get("content") or ""
        if content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_text})
    language_instruction = language_instruction_for(user_text)
    if language_instruction:
        messages.insert(1, {"role": "system", "content": language_instruction})

    try:
        reply = call_ai_chat(messages, business, "Telegram AI response")
        if reply:
            return clean_sales_reply(reply[:1500], user_text, business)
        lang = detect_customer_language(user_text)
        if lang == "en":
            return "Your message has been received."
        if lang == "ru":
            return "Ваше сообщение получено."
        if lang == "kk":
            return "Хабарыңыз қабылданды."
        return "Xabaringiz qabul qilindi 😊"

    except Exception as exc:
        log("Telegram AI error", str(exc))
        lang = detect_customer_language(user_text)
        if lang == "en":
            return "Your message has been received."
        if lang == "ru":
            return "Ваше сообщение получено."
        if lang == "kk":
            return "Хабарыңыз қабылданды."
        return "Xabaringiz qabul qilindi 😊"


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
            "content": text or "",
            "external_message_id": str(message_id or ""),
            "raw_payload": raw_payload or {},
            "is_read": False if direction == "inbound" else True,
            "media_type": media_type,
            "media_url": media_url,
            "media_file_id": media_file_id,
        }

        insert_inbox_message(data)
        log("Telegram inbox message saved", data)

    except Exception as exc:
        log("Could not save Telegram message", str(exc))


def send_telegram_bot_message(chat_id, text, reply_to_message_id=None, business: dict = None):
    token = get_telegram_bot_token_for_business(business)
    if not token:
        log("Missing Telegram bot token")
        return None

    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": False,
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
        timeout=30,
    )

    log("Telegram bot send result", {"status": response.status_code, "body": response.text})
    return response


def send_telegram_catalog_button(chat_id, business, text="", reply_to_message_id=None):
    token = get_telegram_bot_token_for_business(business)
    if not token:
        return None

    catalog_link = get_catalog_link(business)
    if not catalog_link:
        return None

    body_text = clean_ai_reply_for_catalog(text, business) or "Katalogimizga quyidagi havoladan kirishingiz mumkin. Qaysi mahsulotlar sizni qiziqtirmoqda?"
    payload = {
        "chat_id": chat_id,
        "text": body_text[:4096],
        "disable_web_page_preview": False,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Katalogni ko'rish", "url": catalog_link}
                ]
            ]
        },
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
        timeout=30,
    )
    log("Telegram catalog button send result", {"status": response.status_code, "body": response.text})
    return response


def send_telegram_photo(chat_id, photo_file_id, caption="", reply_to_message_id=None, business: dict = None):
    token = get_telegram_bot_token_for_business(business)
    if not token:
        return None

    payload = {
        "chat_id": chat_id,
        "photo": photo_file_id,
    }

    if caption:
        payload["caption"] = caption[:1024]

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        json=payload,
        timeout=30,
    )
    log("Telegram photo send result", {"status": response.status_code, "body": response.text})
    return response


def send_telegram_video(chat_id, video_file_id, caption="", reply_to_message_id=None, business: dict = None):
    token = get_telegram_bot_token_for_business(business)
    if not token:
        return None

    payload = {
        "chat_id": chat_id,
        "video": video_file_id,
    }

    if caption:
        payload["caption"] = caption[:1024]

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendVideo",
        json=payload,
        timeout=30,
    )
    log("Telegram video send result", {"status": response.status_code, "body": response.text})
    return response


def send_telegram_voice(chat_id, voice_file_id, reply_to_message_id=None, business: dict = None):
    token = get_telegram_bot_token_for_business(business)
    if not token:
        return None

    payload = {
        "chat_id": chat_id,
        "voice": voice_file_id,
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendVoice",
        json=payload,
        timeout=30,
    )
    log("Telegram voice send result", {"status": response.status_code, "body": response.text})
    return response


def get_file_url(file_id, business: dict = None):
    token = get_telegram_bot_token_for_business(business)
    if not token or not file_id:
        return None

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
            timeout=30,
        )

        if response.ok:
            file_path = response.json().get("result", {}).get("file_path")
            if file_path:
                return f"https://api.telegram.org/file/bot{token}/{file_path}"

    except Exception as exc:
        log("Could not get Telegram file URL", str(exc))

    return None


def append_voice_transcript(message_text: str, transcript: str):
    base = normalize_text(message_text)
    clean_transcript = normalize_text(transcript)
    if not clean_transcript:
        return base
    return f"{base}\nTranscript: {clean_transcript}" if base else f"Transcript: {clean_transcript}"


def transcribe_telegram_audio_url(file_url: str, filename: str, mime_type: str, business: dict = None):
    clean_url = normalize_text(file_url)
    if not clean_url:
        return ""
    try:
        res = requests.get(clean_url, timeout=60)
        if not res.ok:
            log("Telegram audio download failed", {"status": res.status_code, "body": res.text[:500]})
            return ""
        return transcribe_audio_bytes(
            res.content or b"",
            filename=filename or "telegram-audio.ogg",
            mime_type=mime_type or res.headers.get("Content-Type", "audio/ogg"),
            api_key=(business or {}).get("openai_api_key") or OPENAI_API_KEY,
            prompt="Transcribe customer voice messages clearly and keep the original language.",
            logger=log,
        )
    except Exception as exc:
        log("Telegram audio transcription download error", str(exc))
        return ""


def build_customer_name(user):
    first_name = normalize_text(user.get("first_name"))
    last_name = normalize_text(user.get("last_name"))
    username = normalize_text(user.get("username"))

    full_name = f"{first_name} {last_name}".strip()

    if username:
        return f"{full_name} (@{username})".strip()

    return full_name or str(user.get("id", ""))


def telegram_user_media_mime(message):
    file_info = getattr(message, "file", None)
    mime_type = getattr(file_info, "mime_type", "") if file_info else ""

    if mime_type:
        return mime_type

    if getattr(message, "voice", None):
        return "audio/ogg"
    if getattr(message, "video", None) or getattr(message, "video_note", None):
        return "video/mp4"
    if getattr(message, "photo", None):
        return "image/jpeg"

    return "application/octet-stream"


def parse_http_range(range_header: str, total_size: int):
    if not range_header or not range_header.startswith("bytes="):
        return None
    try:
        value = range_header.replace("bytes=", "", 1).strip()
        if "-" not in value:
            return None
        start_s, end_s = value.split("-", 1)
        if start_s == "":
            suffix = int(end_s)
            if suffix <= 0:
                return None
            start = max(0, total_size - suffix)
            end = total_size - 1
            return start, end
        start = int(start_s)
        end = int(end_s) if end_s else total_size - 1
        if start < 0 or end < start:
            return None
        end = min(end, total_size - 1)
        return start, end
    except Exception:
        return None


def buffer_message(buffer_store, buffer_key, text):
    current_time = time.time()

    if buffer_key not in buffer_store:
        buffer_store[buffer_key] = {
            "texts": [],
            "last_time": current_time,
        }

    buffer_store[buffer_key]["texts"].append(text)
    buffer_store[buffer_key]["last_time"] = current_time


async def pop_buffer_if_ready(buffer_store, buffer_key, wait_seconds=2):
    await asyncio.sleep(wait_seconds + 0.25)

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
    if not TELEGRAM_BOT_TOKEN:
        return JSONResponse({"ok": False, "error": "Missing TELEGRAM_BOT_TOKEN"}, status_code=400)

    if not PUBLIC_BASE_URL:
        return JSONResponse({"ok": False, "error": "Missing PUBLIC_BASE_URL"}, status_code=400)

    webhook_url = f"{PUBLIC_BASE_URL.rstrip('/')}/webhook/telegram"

    response = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
        params={"url": webhook_url},
        timeout=30,
    )

    return JSONResponse(safe_json(response), status_code=response.status_code)


@telegram_router.get("/api/telegram-user-media/{customer_id}/{message_id}")
async def get_telegram_user_media(
    customer_id: str,
    message_id: str,
    token: str = "",
    x_dashboard_secret: str = Header(default=""),
    range_header: str = Header(default="", alias="Range"),
):
    if DASHBOARD_SECRET and token != DASHBOARD_SECRET and x_dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    if not TELEGRAM_USER_CLIENT:
        return JSONResponse(
            {"status": "error", "message": "Telegram private user client is not running"},
            status_code=503,
        )

    try:
        entity = await TELEGRAM_USER_CLIENT.get_entity(int(customer_id))
        message = await TELEGRAM_USER_CLIENT.get_messages(entity, ids=int(message_id))

        if not message or not getattr(message, "media", None):
            return JSONResponse({"status": "error", "message": "Telegram media not found"}, status_code=404)

        media_bytes = await TELEGRAM_USER_CLIENT.download_media(message, file=bytes)
        if not media_bytes:
            return JSONResponse({"status": "error", "message": "Telegram media download failed"}, status_code=404)

        mime = telegram_user_media_mime(message)
        total = len(media_bytes)
        byte_range = parse_http_range(range_header, total)
        common_headers = {
            "Cache-Control": "private, max-age=3600",
            "Accept-Ranges": "bytes",
            "Content-Type": mime,
        }

        if byte_range is not None:
            start, end = byte_range
            chunk = media_bytes[start:end + 1]
            headers = {
                **common_headers,
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Content-Length": str(len(chunk)),
            }
            return Response(content=chunk, media_type=mime, status_code=206, headers=headers)

        return Response(
            content=media_bytes,
            media_type=mime,
            headers={**common_headers, "Content-Length": str(total)},
        )

    except Exception as exc:
        log("Telegram user media proxy error", str(exc))
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@telegram_router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
        log("TELEGRAM BOT WEBHOOK RECEIVED", update)

        message = update.get("message") or update.get("edited_message") or {}

        if not message:
            return JSONResponse({"status": "ignored"})

        chat = message.get("chat", {})
        user = message.get("from", {})

        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        is_group_chat = chat_type in ["group", "supergroup"]
        sender_id = user.get("id") or chat_id
        # Use chat_id as conversation identity for groups so one group = one dashboard thread.
        customer_id = chat_id if is_group_chat else sender_id
        message_id = message.get("message_id")

        event_id = f"bot:{chat_id}:{sender_id}:{message_id}"

        if already_processed(PROCESSED_BOT_MESSAGES, event_id):
            return JSONResponse({"status": "duplicate"})

        business = get_active_business()
        if not business:
            return JSONResponse({"status": "no_business"})
        if is_telegram_bot_authored_message(message, business):
            return JSONResponse({"status": "ignored_bot"})

        if is_group_chat and not should_reply_in_group(message):
                return JSONResponse({"status": "ignored_group_message"})

        channel = "telegram_bot_group" if is_group_chat else "telegram_bot_private"
        customer_name = build_customer_name(user)
        conversation_name = normalize_text(chat.get("title")) if is_group_chat else customer_name

        text = normalize_text(message.get("text"))

        if text:
            # Keep per-sender buffering in groups so two users talking at once do not merge together.
            buffer_key = f"bot:{chat_id}:{sender_id}"
            buffer_message(MESSAGE_BUFFER, buffer_key, text)

            combined_text = await pop_buffer_if_ready(MESSAGE_BUFFER, buffer_key, wait_seconds=2)

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
                customer_name=conversation_name or customer_name,
                chat_id=chat_id,
            )

            # Never auto-reply to group admins.
            if is_group_chat and is_group_admin(chat_id, sender_id, business):
                return JSONResponse({"status": "ignored_group_admin_message"})

            # If this message is in an admin-handled reply context, skip bot reply.
            if is_group_chat:
                reply_to = message.get("reply_to_message") or {}
                reply_from = reply_to.get("from") or {}
                reply_from_id = reply_from.get("id")
                if reply_to.get("sender_chat"):
                    return JSONResponse({"status": "ignored_admin_thread"})
                if reply_from_id and is_group_admin(chat_id, reply_from_id, business):
                    return JSONResponse({"status": "ignored_admin_thread"})

            if not business_allows_auto_reply(business, "telegram_bot"):
                return JSONResponse({"status": "automation_disabled"})

            if not is_chat_ai_enabled("telegram", channel, customer_id, business.get("id")):
                return JSONResponse({"status": "ai_disabled"})

            if is_low_signal_message(combined_text):
                return JSONResponse({"status": "ignored_low_signal"})

            sales_agent_decision = run_sales_agent_for_telegram(
                business=business,
                customer_id=str(customer_id),
                chat_id=str(chat_id),
                channel=channel,
                message_text=combined_text,
                message_id=str(message_id or ""),
                customer_name=conversation_name or customer_name,
            )
            handoff_result = (sales_agent_decision or {}).get("handoff") or {}
            agent_context = normalize_text((sales_agent_decision or {}).get("reply_context"))

            if handoff_result.get("handoff_required") and normalize_text(handoff_result.get("customer_reply")):
                reply = normalize_text(handoff_result.get("customer_reply"))
            else:
                reply = get_ai_reply(
                    user_text=combined_text,
                    business=business,
                    customer_id=customer_id,
                    channel=channel,
                    media_context=agent_context,
                    lead_state=(sales_agent_decision or {}).get("lead_state") or {},
                )

            should_send_catalog = bool(get_catalog_link(business)) and wants_catalog(combined_text) and not is_greeting_only(combined_text)

            if should_send_catalog:
                send_result = send_telegram_catalog_button(
                    chat_id=chat_id,
                    business=business,
                    text=reply,
                    reply_to_message_id=message_id if chat_type in ["group", "supergroup"] else None,
                )
                saved_reply_text = clean_ai_reply_for_catalog(reply, business) + "\n[Catalog button sent]"
            else:
                send_result = send_telegram_bot_message(
                    chat_id=chat_id,
                    text=reply,
                    reply_to_message_id=message_id if chat_type in ["group", "supergroup"] else None,
                    business=business,
                )
                saved_reply_text = reply

            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=saved_reply_text,
                direction="outbound",
                message_id=safe_json(send_result).get("result", {}).get("message_id", ""),
                raw_payload=safe_json(send_result),
                channel=channel,
                customer_name=conversation_name or customer_name,
                chat_id=chat_id,
            )
            record_sales_agent_action(
                business=business,
                channel=channel,
                customer_id=str(customer_id),
                action_type="reply_sent",
                input_message=combined_text,
                decision=sales_agent_decision,
                reply_sent=saved_reply_text,
            )
            if handoff_result.get("handoff_required"):
                set_chat_ai_enabled(business.get("id"), "telegram", channel, customer_id, False)

        elif message.get("photo"):
            photos = message.get("photo", [])
            largest_photo = photos[-1] if photos else {}
            file_id = largest_photo.get("file_id")
            caption = normalize_text(message.get("caption") or "📸 Photo")
            media_url = get_file_url(file_id, business)

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
                media_type="photo",
                media_url=media_url,
                media_file_id=file_id,
            )

            if not business_allows_auto_reply(business, "telegram_bot"):
                return JSONResponse({"status": "automation_disabled"})

            if not is_chat_ai_enabled("telegram", channel, customer_id, business.get("id")):
                return JSONResponse({"status": "ai_disabled"})

            media_match = analyze_catalog_media(
                media_url or "",
                caption or "📸 Photo",
                media_type="photo",
            )
            sales_agent_decision = run_sales_agent_for_telegram(
                business=business,
                customer_id=str(customer_id),
                chat_id=str(chat_id),
                channel=channel,
                message_text=caption or "Customer sent product photo.",
                message_id=str(message_id or ""),
                customer_name=conversation_name or customer_name,
                media_type="photo",
                media_match=media_match or {},
            )
            handoff_result = (sales_agent_decision or {}).get("handoff") or {}
            agent_context = normalize_text((sales_agent_decision or {}).get("reply_context"))
            media_context = "\n".join(
                item for item in [
                    media_match.get("context", "") if media_match else "",
                    agent_context,
                ] if normalize_text(item)
            )
            if handoff_result.get("handoff_required") and normalize_text(handoff_result.get("customer_reply")):
                reply = normalize_text(handoff_result.get("customer_reply"))
            else:
                reply = get_ai_reply(
                    user_text=caption or "📸 Photo",
                    business=business,
                    customer_id=customer_id,
                    channel=channel,
                    media_context=media_context,
                    media_reply_hint=media_match.get("reply_hint", "") if media_match else "",
                    lead_state=(sales_agent_decision or {}).get("lead_state") or {},
                )

            send_result = send_telegram_bot_message(
                chat_id=chat_id,
                text=reply,
                reply_to_message_id=message_id if chat_type in ["group", "supergroup"] else None,
                business=business,
            )
            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=reply,
                direction="outbound",
                message_id=safe_json(send_result).get("result", {}).get("message_id", ""),
                raw_payload=safe_json(send_result),
                channel=channel,
                customer_name=conversation_name or customer_name,
                chat_id=chat_id,
            )
            record_sales_agent_action(
                business=business,
                channel=channel,
                customer_id=str(customer_id),
                action_type="reply_sent",
                input_message=caption,
                decision=sales_agent_decision,
                reply_sent=reply,
                tool_used="product_matcher" if media_match else "",
            )
            if handoff_result.get("handoff_required"):
                set_chat_ai_enabled(business.get("id"), "telegram", channel, customer_id, False)

        elif message.get("video"):
            video = message.get("video", {})
            file_id = video.get("file_id")
            caption = normalize_text(message.get("caption") or "🎥 Video")

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
                media_type="video",
                media_url=get_file_url(file_id, business),
                media_file_id=file_id,
            )

        elif message.get("voice"):
            voice = message.get("voice", {})
            file_id = voice.get("file_id")
            duration = voice.get("duration", 0)
            media_url = get_file_url(file_id, business)
            transcript = transcribe_telegram_audio_url(
                media_url,
                filename=f"{message_id or file_id or 'telegram-voice'}.ogg",
                mime_type="audio/ogg",
                business=business,
            )

            save_telegram_message(
                business=business,
                customer_id=customer_id,
                text=append_voice_transcript(f"🎤 Voice message ({duration}s)", transcript),
                direction="inbound",
                message_id=message_id,
                raw_payload=update,
                channel=channel,
                customer_name=customer_name,
                chat_id=chat_id,
                media_type="voice",
                media_url=media_url,
                media_file_id=file_id,
            )

        elif message.get("document"):
            document = message.get("document", {})
            file_id = document.get("file_id")
            caption = normalize_text(message.get("caption") or document.get("file_name") or "📎 Document")

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
                media_type="file",
                media_url=get_file_url(file_id, business),
                media_file_id=file_id,
            )

        else:
            return JSONResponse({"status": "ignored_no_text_or_media"})

        return JSONResponse({"status": "ok"})

    except Exception as exc:
        log("Telegram bot webhook error", str(exc))
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


async def process_telegram_user_event(event):
    try:
        if event.out or not event.is_private:
            return

        text = normalize_text(event.raw_text)
        sender = await event.get_sender()
        if (
            getattr(sender, "bot", False)
            or getattr(sender, "is_self", False)
            or str(getattr(sender, "id", "")) == str(get_telegram_bot_id() or "")
            or (
                TELEGRAM_BOT_USERNAME
                and normalize_text(getattr(sender, "username", "")).lower().replace("@", "") == TELEGRAM_BOT_USERNAME
            )
        ):
            log("Ignored Telegram user-client bot/self message", {
                "sender_id": getattr(sender, "id", None),
                "username": getattr(sender, "username", None),
            })
            return

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

        name_parts = []
        if getattr(sender, "first_name", None):
            name_parts.append(sender.first_name)
        if getattr(sender, "last_name", None):
            name_parts.append(sender.last_name)

        customer_name = " ".join(name_parts).strip()
        if getattr(sender, "username", None):
            customer_name = f"{customer_name} (@{sender.username})".strip()
        customer_name = customer_name or sender_id

        if event.media:
            media_type = None
            caption = text or "📎 Media sent"
            media_url = ""

            if hasattr(event.media, "photo"):
                media_type = "photo"
                caption = text or "📸 Photo"
            elif hasattr(event.media, "document"):
                doc = event.media.document
                mime_type = getattr(doc, "mime_type", "") or ""
                if "video" in mime_type:
                    media_type = "video"
                    caption = text or "🎥 Video"
                elif "audio" in mime_type:
                    media_type = "voice"
                    caption = text or "🎤 Voice"
                else:
                    media_type = "file"

            if media_type:
                base_url = normalize_text(PUBLIC_BASE_URL).rstrip("/")
                media_url = f"{base_url}/api/telegram-user-media/{sender_id}/{message_id}" if base_url else f"/api/telegram-user-media/{sender_id}/{message_id}"
                if media_type == "voice":
                    try:
                        voice_bytes = await event.download_media(file=bytes)
                    except Exception as exc:
                        log("Telegram user voice download error", str(exc))
                        voice_bytes = b""
                    transcript = transcribe_audio_bytes(
                        voice_bytes,
                        filename=f"{message_id}.ogg",
                        mime_type="audio/ogg",
                        api_key=(business or {}).get("openai_api_key") or OPENAI_API_KEY,
                        prompt="Transcribe customer voice messages clearly and keep the original language.",
                        logger=log,
                    )
                    caption = append_voice_transcript(caption, transcript)

                save_telegram_message(
                    business=business,
                    customer_id=sender_id,
                    text=caption,
                    direction="inbound",
                    message_id=message_id,
                    raw_payload={
                        "chat_id": chat_id,
                        "sender_id": sender_id,
                        "message_id": message_id,
                        "source": "telethon_user_account",
                        "media_proxy": media_url,
                    },
                    channel="telegram_user_private",
                    customer_name=customer_name,
                    chat_id=chat_id,
                    media_type=media_type,
                    media_url=media_url,
                )

                if media_type == "photo" and business_allows_auto_reply(business, "telegram_bot") and is_chat_ai_enabled("telegram", "telegram_user_private", sender_id, business.get("id")):
                    media_match = analyze_catalog_media(media_url or "", caption or "📸 Photo", media_type="photo")
                    sales_agent_decision = run_sales_agent_for_telegram(
                        business=business,
                        customer_id=str(sender_id),
                        chat_id=str(chat_id),
                        channel="telegram_user_private",
                        message_text=caption or "Customer sent product photo.",
                        message_id=str(message_id or ""),
                        customer_name=customer_name,
                        media_type="photo",
                        media_match=media_match or {},
                    )
                    handoff_result = (sales_agent_decision or {}).get("handoff") or {}
                    agent_context = normalize_text((sales_agent_decision or {}).get("reply_context"))
                    media_context = "\n".join(
                        item for item in [
                            media_match.get("context", "") if media_match else "",
                            agent_context,
                        ] if normalize_text(item)
                    )
                    if handoff_result.get("handoff_required") and normalize_text(handoff_result.get("customer_reply")):
                        reply = normalize_text(handoff_result.get("customer_reply"))
                    else:
                        reply = get_ai_reply(
                            user_text=caption or "📸 Photo",
                            business=business,
                            customer_id=sender_id,
                            channel="telegram_user_private",
                            media_context=media_context,
                            media_reply_hint=media_match.get("reply_hint", "") if media_match else "",
                            lead_state=(sales_agent_decision or {}).get("lead_state") or {},
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
                    record_sales_agent_action(
                        business=business,
                        channel="telegram_user_private",
                        customer_id=str(sender_id),
                        action_type="reply_sent",
                        input_message=caption,
                        decision=sales_agent_decision,
                        reply_sent=reply,
                        tool_used="product_matcher" if media_match else "",
                    )
                    if handoff_result.get("handoff_required"):
                        set_chat_ai_enabled(business.get("id"), "telegram", "telegram_user_private", sender_id, False)

        elif text:
            buffer_key = f"user:{chat_id}:{sender_id}"
            buffer_message(USER_MESSAGE_BUFFER, buffer_key, text)

            combined_text = await pop_buffer_if_ready(USER_MESSAGE_BUFFER, buffer_key, wait_seconds=2)
            if not combined_text:
                return

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

            if is_low_signal_message(combined_text):
                return

            sales_agent_decision = run_sales_agent_for_telegram(
                business=business,
                customer_id=str(sender_id),
                chat_id=str(chat_id),
                channel="telegram_user_private",
                message_text=combined_text,
                message_id=str(message_id or ""),
                customer_name=customer_name,
            )
            handoff_result = (sales_agent_decision or {}).get("handoff") or {}
            agent_context = normalize_text((sales_agent_decision or {}).get("reply_context"))
            if handoff_result.get("handoff_required") and normalize_text(handoff_result.get("customer_reply")):
                reply = normalize_text(handoff_result.get("customer_reply"))
            else:
                reply = get_ai_reply(
                    user_text=combined_text,
                    business=business,
                    customer_id=sender_id,
                    channel="telegram_user_private",
                    media_context=agent_context,
                    lead_state=(sales_agent_decision or {}).get("lead_state") or {},
                )

            should_send_catalog = bool(get_catalog_link(business)) and wants_catalog(combined_text) and not is_greeting_only(combined_text)
            outbound_text = reply
            if should_send_catalog:
                outbound_text = (
                    clean_ai_reply_for_catalog(reply, business)
                    + f"\nKatalogni ko'rish: {get_catalog_link(business)}"
                ).strip()
                outbound_text += "\n[Catalog button sent]"

            sent = await event.respond(outbound_text)

            save_telegram_message(
                business=business,
                customer_id=sender_id,
                text=outbound_text,
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
            record_sales_agent_action(
                business=business,
                channel="telegram_user_private",
                customer_id=str(sender_id),
                action_type="reply_sent",
                input_message=combined_text,
                decision=sales_agent_decision,
                reply_sent=outbound_text,
            )
            if handoff_result.get("handoff_required"):
                set_chat_ai_enabled(business.get("id"), "telegram", "telegram_user_private", sender_id, False)

    except Exception as exc:
        log("Telegram user account event error", str(exc))


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

    except Exception as exc:
        return False, {"error": str(exc)}


async def send_telegram_user_file(customer_id, file_bytes, filename, caption=""):
    global TELEGRAM_USER_CLIENT

    if not TELEGRAM_USER_CLIENT:
        return False, {"error": "Telegram private user client is not running"}

    try:
        entity = await TELEGRAM_USER_CLIENT.get_entity(int(customer_id))
        file_obj = io.BytesIO(file_bytes)
        file_obj.name = filename or "image.jpg"

        sent = await TELEGRAM_USER_CLIENT.send_file(
            entity,
            file=file_obj,
            caption=caption or "",
            force_document=False,
        )

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

    except Exception as exc:
        return False, {"error": str(exc)}


async def send_telegram_user_voice_file(customer_id, file_bytes, filename):
    global TELEGRAM_USER_CLIENT

    if not TELEGRAM_USER_CLIENT:
        return False, {"error": "Telegram private user client is not running"}

    try:
        entity = await TELEGRAM_USER_CLIENT.get_entity(int(customer_id))
        file_obj = io.BytesIO(file_bytes)
        file_obj.name = filename or "voice.ogg"

        sent = await TELEGRAM_USER_CLIENT.send_file(
            entity,
            file=file_obj,
            voice_note=True,
        )

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

    except Exception as exc:
        return False, {"error": str(exc)}


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
                "Create telegram_user_session.session locally first, then deploy it."
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

    except Exception as exc:
        log("Telegram private user client startup error", str(exc))
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
