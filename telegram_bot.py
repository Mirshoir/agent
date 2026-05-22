import os
import re
import time
import asyncio
import io
import requests
from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from supabase import create_client

try:
    from telethon import TelegramClient, events
except Exception:
    TelegramClient = None
    events = None


telegram_router = APIRouter()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").lower().replace("@", "")
TELEGRAM_GROUP_REPLY_MODE = os.getenv("TELEGRAM_GROUP_REPLY_MODE", "all").strip().lower()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_USER_SESSION = os.getenv("TELEGRAM_USER_SESSION", "milana_user_session")
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


def normalize_text(value):
    return str(value or "").strip()


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


def get_catalog_link(business: dict) -> str:
    link = (business or {}).get("catalog_link") or (business or {}).get("catalog") or (business or {}).get("website") or ""
    link = normalize_text(link)
    if link and not link.startswith(("http://", "https://")):
        link = f"https://{link}"
    return link


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
    mode = TELEGRAM_GROUP_REPLY_MODE or "all"
    if mode == "all":
        return True

    text = normalize_text(message.get("text")).lower()
    mention = f"@{TELEGRAM_BOT_USERNAME}" if TELEGRAM_BOT_USERNAME else ""
    has_mention = bool(mention and mention in text)

    reply_from = (message.get("reply_to_message") or {}).get("from") or {}
    replied_to_bot = is_own_or_any_bot_user(reply_from)

    return has_mention or replied_to_bot


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


def get_telegram_bot_id():
    global TELEGRAM_BOT_ID

    if TELEGRAM_BOT_ID:
        return TELEGRAM_BOT_ID

    if not TELEGRAM_BOT_TOKEN:
        return None

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe",
            timeout=15,
        )
        data = safe_json(response)
        if response.ok and data.get("ok"):
            TELEGRAM_BOT_ID = str(data.get("result", {}).get("id") or "")
            return TELEGRAM_BOT_ID or None
    except Exception as exc:
        log("Could not resolve Telegram bot id", str(exc))

    return None


def is_own_or_any_bot_user(user):
    if not user:
        return False

    user_id = str(user.get("id") or "")
    username = normalize_text(user.get("username")).lower().replace("@", "")
    bot_id = get_telegram_bot_id()

    return (
        bool(user.get("is_bot"))
        or bool(bot_id and user_id == bot_id)
        or bool(TELEGRAM_BOT_USERNAME and username == TELEGRAM_BOT_USERNAME)
    )


def is_telegram_bot_authored_message(message):
    if not message:
        return True

    if is_own_or_any_bot_user(message.get("from") or {}):
        return True

    if is_own_or_any_bot_user(message.get("via_bot") or {}):
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


DEFAULT_AI_PROMPT_SETTINGS = {
    "global_prompt": (
        "You are a real human sales assistant for this business. "
        "Sound like a real Uzbek Telegram seller, not customer support software. "
        "Represent the company clearly, answer in the customer's language, and guide the customer toward the next useful buying step. "
        "Keep every reply short, natural, and human. Ask one question at a time. "
        "Do not repeat product names in every message or sound corporate."
    ),
    "telegram_prompt": (
        "Telegram rules:\n"
        "- Sound like a natural Telegram sales manager.\n"
        "- In groups, answer only when mentioned or replied to.\n"
        "- Avoid long lists unless the customer asks for a list.\n"
        "- Share Telegram catalog/group links only when relevant."
    ),
    "opening_message": "Assalomu alaykum 😊 Qanday yordam kerak?",
    "lead_collection_rules": (
        "Do not ask for name, phone, address, or full details at the beginning. "
        "First answer naturally and understand what the customer wants. "
        "Ask only one small follow-up question at a time. "
        "Ask for phone/address only after the customer is clearly ready to order."
    ),
    "sales_rules": (
        "Answer the exact question first. Ask only one follow-up question at a time. "
        "For price questions ('narx', 'nechpul', 'qancha', 'цена', 'сколько'), answer price directly first if known. "
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

Knowledge:
{business.get("knowledge", "")}
"""


def get_recent_chat_history(customer_id, platform="telegram", channel=None, limit=10):
    try:
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

Safety rules:
- Reply in the same language as the customer.
- Ask one question at a time.
- Never invent prices, stock, delivery, discounts, addresses, or availability.
- Use only the business facts above.
- If information is missing, ask one short clarifying question first.
- Only mention a manager when the customer asks for a human or is ready to order.
- Never mention AI, database, API, prompt, automation, or internal system.
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



def clean_sales_reply(reply_text, user_text=""):
    user = normalize_text(user_text).lower()
    lang = detect_customer_language(user_text)

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

def get_ai_reply(user_text, business, customer_id, channel="telegram_bot_private"):
    history = get_recent_chat_history(
        customer_id=customer_id,
        platform="telegram",
        channel=channel,
        limit=8,
    )

    messages = [{"role": "system", "content": build_telegram_system_prompt(business)}]

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
            return clean_sales_reply(reply[:1500], user_text)
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


def send_telegram_bot_message(chat_id, text, reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
        log("Missing TELEGRAM_BOT_TOKEN")
        return None

    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": False,
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json=payload,
        timeout=30,
    )

    log("Telegram bot send result", {"status": response.status_code, "body": response.text})
    return response


def send_telegram_catalog_button(chat_id, business, text="", reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
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
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json=payload,
        timeout=30,
    )
    log("Telegram catalog button send result", {"status": response.status_code, "body": response.text})
    return response


def send_telegram_photo(chat_id, photo_file_id, caption="", reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
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
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
        json=payload,
        timeout=30,
    )
    log("Telegram photo send result", {"status": response.status_code, "body": response.text})
    return response


def send_telegram_video(chat_id, video_file_id, caption="", reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
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
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo",
        json=payload,
        timeout=30,
    )
    log("Telegram video send result", {"status": response.status_code, "body": response.text})
    return response


def send_telegram_voice(chat_id, voice_file_id, reply_to_message_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return None

    payload = {
        "chat_id": chat_id,
        "voice": voice_file_id,
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVoice",
        json=payload,
        timeout=30,
    )
    log("Telegram voice send result", {"status": response.status_code, "body": response.text})
    return response


def get_file_url(file_id):
    if not TELEGRAM_BOT_TOKEN or not file_id:
        return None

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=30,
        )

        if response.ok:
            file_path = response.json().get("result", {}).get("file_path")
            if file_path:
                return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

    except Exception as exc:
        log("Could not get Telegram file URL", str(exc))

    return None


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

        if is_telegram_bot_authored_message(message):
            return JSONResponse({"status": "ignored_bot"})

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

            if not is_chat_ai_enabled("telegram", channel, customer_id, business.get("id")):
                return JSONResponse({"status": "ai_disabled"})

            reply = get_ai_reply(
                user_text=combined_text,
                business=business,
                customer_id=customer_id,
                channel=channel,
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

        elif message.get("photo"):
            photos = message.get("photo", [])
            largest_photo = photos[-1] if photos else {}
            file_id = largest_photo.get("file_id")
            caption = normalize_text(message.get("caption") or "📸 Photo")

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
                media_url=get_file_url(file_id),
                media_file_id=file_id,
            )

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
                media_url=get_file_url(file_id),
                media_file_id=file_id,
            )

        elif message.get("voice"):
            voice = message.get("voice", {})
            file_id = voice.get("file_id")
            duration = voice.get("duration", 0)

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
                media_type="voice",
                media_url=get_file_url(file_id),
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
                media_url=get_file_url(file_id),
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
                        "media_proxy": f"/api/telegram-user-media/{sender_id}/{message_id}",
                    },
                    channel="telegram_user_private",
                    customer_name=customer_name,
                    chat_id=chat_id,
                    media_type=media_type,
                )

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

            reply = get_ai_reply(
                user_text=combined_text,
                business=business,
                customer_id=sender_id,
                channel="telegram_user_private",
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
