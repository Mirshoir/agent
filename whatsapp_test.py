import os
import time
import re
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from catalog_matcher import analyze_media_for_sales_reply_local as analyze_catalog_media

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v25.0")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

CATALOG_LINK = os.getenv("CATALOG_LINK", "Catalog link will be shared soon.")
BUSINESS_NAME = os.getenv("WHATSAPP_BUSINESS_NAME", os.getenv("BUSINESS_NAME", "your business"))
BUSINESS_TYPE = os.getenv("WHATSAPP_BUSINESS_TYPE", os.getenv("BUSINESS_TYPE", "business"))
BUSINESS_WEBSITE = os.getenv("WHATSAPP_BUSINESS_WEBSITE", os.getenv("BUSINESS_WEBSITE", ""))
BUSINESS_KNOWLEDGE = os.getenv("WHATSAPP_BUSINESS_KNOWLEDGE", os.getenv("BUSINESS_KNOWLEDGE", ""))
AI_REPLY_RULES = os.getenv("WHATSAPP_AI_REPLY_RULES", os.getenv("AI_REPLY_RULES", ""))
SALES_PHONE = os.getenv("WHATSAPP_SALES_PHONE", os.getenv("SALES_PHONE", os.getenv("CONTACT_PHONE", "")))
TELEGRAM_CONTACT = os.getenv("WHATSAPP_TELEGRAM_CONTACT", os.getenv("TELEGRAM_CONTACT", ""))
INSTAGRAM_LINK = os.getenv("WHATSAPP_INSTAGRAM_LINK", os.getenv("INSTAGRAM_LINK", ""))
TIKTOK_LINK = os.getenv("WHATSAPP_TIKTOK_LINK", os.getenv("TIKTOK_LINK", ""))
KG_PHONE = os.getenv("WHATSAPP_KG_PHONE", os.getenv("KG_PHONE", ""))
AUTOMATION_MODE = os.getenv("WHATSAPP_AUTOMATION_MODE", os.getenv("AUTOMATION_MODE", "FULL_AUTO"))
HUMAN_TAKEOVER_ENABLED = os.getenv("WHATSAPP_HUMAN_TAKEOVER_ENABLED", os.getenv("HUMAN_TAKEOVER_ENABLED", "true"))
MEMORY_ENABLED = os.getenv("WHATSAPP_MEMORY_ENABLED", os.getenv("MEMORY_ENABLED", "true"))
MEMORY_LIMIT = os.getenv("WHATSAPP_MEMORY_LIMIT", os.getenv("MEMORY_LIMIT", "12"))

PROCESSED_MESSAGES = {}
CHAT_MEMORY = {}


def log(title, data=None):
    print("\n" + "=" * 80, flush=True)
    print(title, flush=True)
    if data is not None:
        print(data, flush=True)
    print("=" * 80 + "\n", flush=True)


def already_processed(message_id: str, ttl: int = 3600) -> bool:
    if not message_id:
        return False

    now = time.time()

    for key, timestamp in list(PROCESSED_MESSAGES.items()):
        if now - timestamp > ttl:
            PROCESSED_MESSAGES.pop(key, None)

    if message_id in PROCESSED_MESSAGES:
        return True

    PROCESSED_MESSAGES[message_id] = now
    return False


def get_chat(phone: str):
    if phone not in CHAT_MEMORY:
        CHAT_MEMORY[phone] = {
            "intro_sent": False,
            "messages": [],
            "last_seen": time.time(),
        }

    CHAT_MEMORY[phone]["last_seen"] = time.time()
    return CHAT_MEMORY[phone]


def add_memory(phone: str, role: str, content: str, limit: int = 12):
    if limit <= 0:
        return
    chat = get_chat(phone)
    chat["messages"].append({"role": role, "content": content})
    chat["messages"] = chat["messages"][-limit:]


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


def get_memory_limit(default: int = 12) -> int:
    try:
        if not normalize_bool(MEMORY_ENABLED, True):
            return 0
        return max(0, min(20, int(MEMORY_LIMIT or default)))
    except Exception:
        return default


def business_allows_auto_reply() -> bool:
    if not normalize_bool(os.getenv("WHATSAPP_BOT_ENABLED", "true"), True):
        return False
    mode = str(AUTOMATION_MODE or "").strip().upper()
    if mode in {"OFF", "DISABLED", "MANUAL", "HUMAN_ONLY"}:
        return False
    return True


def business_allows_human_handoff() -> bool:
    return normalize_bool(HUMAN_TAKEOVER_ENABLED, True)


def get_whatsapp_media_download_url(media_id: str) -> str:
    clean_media_id = str(media_id or "").strip()
    if not clean_media_id or not WHATSAPP_ACCESS_TOKEN:
        return ""

    try:
        res = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{clean_media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            timeout=30,
        )
        if not res.ok:
            return ""
        data = res.json()
        return str(data.get("url") or "").strip()
    except Exception:
        return ""


def detect_customer_language(text: str) -> str:
    lower = str(text or "").strip().lower()
    if not lower:
        return ""
    english_words = {
        "hi", "hello", "hey", "can", "could", "would", "make", "purchase", "buy", "order",
        "price", "how", "much", "where", "shipping", "delivery", "catalog", "available",
    }
    uzbek_latin_markers = {
        "salom", "assalomu", "alaykum", "narx", "qancha", "qayer", "kerak", "olmoq",
        "mahsulot", "katalog", "manzil", "rahmat",
    }
    kazakh_markers = {"сәлем", "салем", "қалай", "баға", "қанша", "тапсырыс", "тауар"}
    russian_words = {"здравствуйте", "привет", "цена", "сколько", "купить", "заказ", "доставка", "каталог"}

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


def wants_catalog(text: str) -> bool:
    s = str(text or "").lower()
    keys = [
        "catalog", "katalog", "каталог", "price", "prices", "narx", "narxlari",
        "цена", "цены", "сколько", "model", "models", "mahsulot", "товар", "доставка",
    ]
    return any(k in s for k in keys)


def wants_deal_handoff(text: str) -> bool:
    s = str(text or "").lower()
    keys = [
        "deal", "order", "buy", "purchase", "ready to buy",
        "заказ", "оформить", "куплю", "сделка",
        "zakaz", "zakaz qilmoqchiman", "buyurtma", "buyurtma bermoqchiman", "olmoqchiman", "olaman",
        "тапсырыс", "сатып аламын",
    ]
    return any(k in s for k in keys)


def wants_phone_number(text: str) -> bool:
    s = str(text or "").lower()
    keys = [
        "phone", "phone number", "contact number", "number", "whatsapp number",
        "telefon", "telefon raqam", "telefon raqami", "raqam", "номер", "номер телефона",
        "menejer raqami", "menejer telefon", "manager number", "manager phone",
    ]
    return any(k in s for k in keys)


def is_low_signal_message(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    compact = re.sub(r"\s+", "", s)
    emoji_only_re = re.compile(r"^[\u2600-\u27BF\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF\u200d\ufe0f]+$")
    if compact and emoji_only_re.fullmatch(compact):
        return True
    if compact.lower() in {"+", "++", "ok", "okk"}:
        return True
    return False


def complete_sentence_reply(text: str, limit: int = 900) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?:link|havola|ссылка)\s*[:：]\s*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"(?:ko['‘’`]?rish|очень)\s+uchun\s*[:：]\s*$", "", text, flags=re.IGNORECASE).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].strip()
    if not re.search(r"[.!?…]$", text):
        text += "."
    return text


def clean_sales_reply(reply_text: str, user_text: str = "") -> str:
    lang = detect_customer_language(user_text)
    text = str(reply_text or "").strip()

    if wants_deal_handoff(user_text):
        if business_allows_human_handoff():
            if TELEGRAM_CONTACT:
                if lang == "en":
                    return f"Great. To finalize the order, please contact our manager on Telegram: {TELEGRAM_CONTACT}"
                if lang == "ru":
                    return f"Отлично. Чтобы оформить заказ, напишите нашему менеджеру в Telegram: {TELEGRAM_CONTACT}"
                if lang == "kk":
                    return f"Керемет. Тапсырысты рәсімдеу үшін Telegram-дағы менеджерге жазыңыз: {TELEGRAM_CONTACT}"
                return f"Zo'r. Buyurtmani rasmiylashtirish uchun Telegramdagi menejerimizga yozing: {TELEGRAM_CONTACT}"
            if lang == "en":
                return "Great. Our manager will contact you shortly to finalize the order."
            if lang == "ru":
                return "Отлично. Наш менеджер скоро свяжется с вами для оформления заказа."
            if lang == "kk":
                return "Керемет. Тапсырысты рәсімдеу үшін менеджеріміз сізбен жақын арада хабарласады."
            return "Zo'r. Buyurtmani rasmiylashtirish uchun menejerimiz siz bilan tez orada bog'lanadi."

    if wants_catalog(user_text):
        if lang == "en":
            return complete_sentence_reply(f"You can view our catalog here: {CATALOG_LINK} Which products are you interested in?")
        if lang == "ru":
            return complete_sentence_reply(f"Вы можете посмотреть наш каталог здесь: {CATALOG_LINK} Какие товары вас интересуют?")
        if lang == "kk":
            return complete_sentence_reply(f"Біздің каталогты осы жерден көре аласыз: {CATALOG_LINK} Қай тауарлар сізді қызықтырады?")
        return complete_sentence_reply(f"Katalogimizni shu yerda ko'rishingiz mumkin: {CATALOG_LINK} Qaysi mahsulotlar sizni qiziqtirmoqda?")

    if wants_phone_number(user_text):
        if SALES_PHONE:
            if lang == "en":
                return complete_sentence_reply(f"Our contact number is {SALES_PHONE}. Which product are you interested in?")
            if lang == "ru":
                return complete_sentence_reply(f"Наш контактный номер: {SALES_PHONE}. Какой товар вас интересует?")
            if lang == "kk":
                return complete_sentence_reply(f"Байланыс нөміріміз: {SALES_PHONE}. Қай тауар сізді қызықтырады?")
            return complete_sentence_reply(f"Bizning aloqa raqamimiz: {SALES_PHONE}. Qaysi mahsulot sizni qiziqtiradi?")
        if lang == "en":
            return "Our contact number will be shared by the manager shortly. Which product are you interested in?"
        if lang == "ru":
            return "Наш номер менеджер скоро отправит вам. Какой товар вас интересует?"
        if lang == "kk":
            return "Байланыс нөмірін менеджер жақын арада жібереді. Қай тауар сізді қызықтырады?"
        return "Aloqa raqamimizni menejerimiz tez orada yuboradi. Qaysi mahsulot sizni qiziqtiradi?"

    if not text:
        if lang == "en":
            return "Your message has been received. How can I help you?"
        if lang == "ru":
            return "Ваше сообщение получено. Чем могу помочь?"
        if lang == "kk":
            return "Хабарыңыз қабылданды. Қалай көмектесе аламын?"
        return "Xabaringiz qabul qilindi 😊 Qanday yordam bera olaman?"

    if lang == "en":
        low = text.lower()
        if re.search(r"[А-Яа-яЁё]", text) or any(x in low for x in ["assalomu", "salom", "qanday", "mahsulot", "katalog"]):
            return "Hello! Of course. Which products are you interested in?"

    return complete_sentence_reply(text)


@app.get("/")
def home():
    return {
        "status": "WhatsApp AI backend with memory is running",
        "has_whatsapp_access_token": bool(WHATSAPP_ACCESS_TOKEN),
        "has_phone_number_id": bool(WHATSAPP_PHONE_NUMBER_ID),
        "has_mistral_api_key": bool(MISTRAL_API_KEY),
        "graph_version": GRAPH_VERSION,
        "active_chats": len(CHAT_MEMORY),
    }


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    log("VERIFY REQUEST", params)

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or "")

    return PlainTextResponse("Verification failed", status_code=403)


def send_whatsapp_text(to_phone: str, text: str):
    clean_phone = str(to_phone).replace("+", "").replace(" ", "").strip()

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone,
        "type": "text",
        "text": {
            "preview_url": True,
            "body": text[:4096],
        },
    }

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)

        try:
            result = res.json()
        except Exception:
            result = {"raw": res.text}

        log("WHATSAPP SEND RESULT", {"status": res.status_code, "body": result})
        return res.ok, result

    except Exception as e:
        log("WHATSAPP SEND ERROR", str(e))
        return False, {"error": str(e)}


def first_intro_message():
    company = BUSINESS_NAME.strip()
    intro = (
        f"Assalomu alaykum 😊 Men {company} virtual assistentiman.\n\n"
        "Sizga tezroq yordam berishimiz uchun, xohlasangiz quyidagi ma'lumotlarni qoldiring:\n"
        "Ism, telefon raqam, qaysi mahsulot kerakligi va miqdori.\n\n"
        "Vakilimiz tez orada siz bilan bog'lanadi."
    )
    return intro


def build_business_context() -> str:
    return f"""
Business name:
{BUSINESS_NAME}

Business type:
{BUSINESS_TYPE}

Website:
{BUSINESS_WEBSITE}

Catalog link:
{CATALOG_LINK}

Phone:
{SALES_PHONE}

Telegram:
{TELEGRAM_CONTACT}

Instagram:
{INSTAGRAM_LINK}

TikTok:
{TIKTOK_LINK}

Knowledge:
{BUSINESS_KNOWLEDGE}

AI reply rules:
{AI_REPLY_RULES}

Runtime settings:
- automation_mode: {AUTOMATION_MODE}
- human_takeover_enabled: {HUMAN_TAKEOVER_ENABLED}
- memory_enabled: {MEMORY_ENABLED}
- memory_limit: {MEMORY_LIMIT}
"""


def build_system_prompt(intro_sent: bool):
    return f"""
You are a human-like WhatsApp sales assistant for this business.

Important style:
- Reply in the customer's language: Uzbek, Russian, or English.
- Keep replies short, natural, and sales-focused.
- Usually 1-3 short sentences.
- Do not mention AI, bot, API, database, or automation.
- Do not invent prices, stock, addresses, or discounts.
- If something is missing, ask a short follow-up question or hand off to the manager if the business allows it.
- Do not repeat the opening information request if it was already sent.
- If the user ignores the details request, continue naturally.

Opening conversation rule:
- If intro_sent is false, introduce yourself as the business's virtual assistant.
- Use the configured business name in the intro.
- Ask politely for: name, phone number, product of interest, and quantity.
- Say a representative will contact them soon.
- Do not force them.
- Do not keep asking again.

Business context:
{build_business_context()}
"""


def get_ai_reply(phone: str, user_text: str, media_context: str = "", media_reply_hint: str = "") -> str:
    chat = get_chat(phone)

    if not chat["intro_sent"]:
        chat["intro_sent"] = True
        intro = first_intro_message()
        add_memory(phone, "assistant", intro)
        return intro

    if not MISTRAL_API_KEY:
        return "Xabaringiz qabul qilindi 😊 Qanday yordam bera olaman?"

    messages = [{"role": "system", "content": build_system_prompt(chat["intro_sent"])}]
    if media_context:
        messages.append({"role": "system", "content": media_context})
    if media_reply_hint:
        messages.append({
            "role": "system",
            "content": f"Suggested product answer from media matcher: {media_reply_hint}. Keep the answer in the customer's language and do not ask which model if the matcher already found one.",
        })

    memory_limit = get_memory_limit()
    if memory_limit > 0:
        messages.extend(chat["messages"][-memory_limit:])
    messages.append({"role": "user", "content": user_text})

    try:
        res = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MISTRAL_MODEL,
                "messages": messages,
                "temperature": 0.45,
                "max_tokens": 180,
            },
            timeout=30,
        )

        result = res.json()
        log("MISTRAL RESULT", {"status": res.status_code, "body": result})

        if not res.ok:
            return "Xabaringiz qabul qilindi 😊 Menejerimiz tez orada aniqlashtirib beradi."

        reply = result["choices"][0]["message"]["content"].strip()
        return clean_sales_reply(reply[:1500], user_text) if reply else clean_sales_reply("", user_text)

    except Exception as e:
        log("MISTRAL ERROR", str(e))
        return clean_sales_reply("", user_text)


def extract_message_text(message: dict) -> str:
    msg_type = message.get("type", "")

    if msg_type == "text":
        return message.get("text", {}).get("body", "")

    if msg_type == "image":
        return message.get("image", {}).get("caption") or "Customer sent a photo."

    if msg_type == "video":
        return message.get("video", {}).get("caption") or "Customer sent a video."

    if msg_type == "audio":
        return "Customer sent a voice message."

    if msg_type == "document":
        return message.get("document", {}).get("caption") or "Customer sent a document."

    if msg_type == "button":
        return message.get("button", {}).get("text", "")

    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        return (
            interactive.get("button_reply", {}).get("title")
            or interactive.get("list_reply", {}).get("title")
            or "Customer sent an interactive reply."
        )

    return f"Customer sent unsupported message type: {msg_type}"


@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()

    log("WHATSAPP WEBHOOK RECEIVED", data)

    if data.get("object") != "whatsapp_business_account":
        return JSONResponse({"status": "ignored"})

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            if "statuses" in value:
                log("WHATSAPP STATUS UPDATE", value.get("statuses"))
                continue

            messages = value.get("messages", [])

            for message in messages:
                message_id = message.get("id", "")
                if already_processed(message_id):
                    continue

                from_phone = message.get("from", "")
                msg_type = message.get("type", "")
                whatsapp_media_id = ""
                if msg_type in {"image", "video", "audio", "document", "sticker"}:
                    media = message.get(msg_type, {}) or {}
                    whatsapp_media_id = media.get("id", "")
                user_text = extract_message_text(message)

                log("CUSTOMER MESSAGE", {"from": from_phone, "text": user_text})

                if is_low_signal_message(user_text):
                    log("IGNORED LOW SIGNAL MESSAGE", {"from": from_phone, "text": user_text})
                    continue

                if not business_allows_auto_reply():
                    log("AUTO REPLY DISABLED", {"from": from_phone, "text": user_text})
                    continue

                add_memory(from_phone, "user", user_text, limit=get_memory_limit() or 12)

                media_context = ""
                media_reply_hint = ""
                if msg_type in {"image", "document"} and whatsapp_media_id:
                    media_download_url = get_whatsapp_media_download_url(whatsapp_media_id)
                    if media_download_url:
                        media_match = analyze_catalog_media(
                            media_download_url,
                            user_text or "",
                            media_type="photo",
                            access_token=WHATSAPP_ACCESS_TOKEN,
                        )
                        if media_match:
                            media_context = media_match.get("context", "")
                            media_reply_hint = media_match.get("reply_hint", "")

                reply = get_ai_reply(from_phone, user_text, media_context=media_context, media_reply_hint=media_reply_hint)

                add_memory(from_phone, "assistant", reply, limit=get_memory_limit() or 12)

                send_whatsapp_text(from_phone, reply)

    return JSONResponse({"status": "ok"})
