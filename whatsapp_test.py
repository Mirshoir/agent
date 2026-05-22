import os
import time
import re
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v25.0")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

CATALOG_LINK = os.getenv("CATALOG_LINK", "Catalog link will be shared soon.")

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
    chat = get_chat(phone)
    chat["messages"].append({"role": role, "content": content})
    chat["messages"] = chat["messages"][-limit:]


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
    user = str(user_text or "").lower()
    text = str(reply_text or "").strip()

    if wants_deal_handoff(user_text):
        if lang == "en":
            return "Great. To finalize the order, please contact our admin on Telegram: @milana_admin25."
        if lang == "ru":
            return "Отлично. Чтобы оформить заказ, напишите нашему админу в Telegram: @milana_admin25."
        if lang == "kk":
            return "Керемет. Тапсырысты рәсімдеу үшін Telegram-дағы әкімшіге жазыңыз: @milana_admin25."
        return "Zo'r. Buyurtmani rasmiylashtirish uchun Telegramdagi adminimizga yozing: @milana_admin25."

    if wants_catalog(user_text):
        if lang == "en":
            return complete_sentence_reply(f"You can view our catalog here: {CATALOG_LINK} Which products are you interested in?")
        if lang == "ru":
            return complete_sentence_reply(f"Вы можете посмотреть наш каталог здесь: {CATALOG_LINK} Какие товары вас интересуют?")
        if lang == "kk":
            return complete_sentence_reply(f"Біздің каталогты осы жерден көре аласыз: {CATALOG_LINK} Қай тауарлар сізді қызықтырады?")
        return complete_sentence_reply(f"Katalogimizni shu yerda ko'rishingiz mumkin: {CATALOG_LINK} Qaysi mahsulotlar sizni qiziqtirmoqda?")

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
    return (
        "Assalomu alaykum 😊 Men Milana Premium virtual assistentiman.\n\n"
        "Sizga tezroq va ustuvor yordam berishimiz uchun, xohlasangiz quyidagi ma’lumotlarni qoldiring:\n"
        "Ism, telefon raqam, manzil, qaysi mahsulot kerakligi va miqdori.\n\n"
        "Vakilimiz tez orada siz bilan bog‘lanadi."
    )


def build_system_prompt(intro_sent: bool):
    return f"""
You are Milana Premium's human-like WhatsApp sales assistant.

Important style:
- Reply in the customer's language: Uzbek, Russian, or English.
- Keep replies short, natural, and sales-focused.
- Usually 1-3 short sentences.
- Do not mention AI, bot, API, database, or automation.
- Do not invent prices, stock, addresses, or discounts.
- If something is missing, say the manager will clarify.
- Do not repeat the opening information request if it was already sent.
- If the user ignores the details request, continue naturally.

Opening conversation rule:
- If intro_sent is false, introduce yourself as Milana Premium virtual assistant.
- Ask politely for: name, phone number, address, product of interest, and quantity.
- Say a representative will contact them soon.
- Do not force them.
- Do not keep asking again.

Company:
Milana Premium sells clothing/textile products.
Website: https://milanapremium.com/

Catalog and price:
If customer asks price/catalog, send this catalog link:
{CATALOG_LINK}

Fast sales contact:
If customer wants to contact sales manager quickly:
+998 50 155 10 10
They can contact this number via Telegram and WhatsApp.

Social pages:
Instagram: https://www.instagram.com/milanapremium/
TikTok: tiktok.com/@milana_premium_rasmiy

Production/preparation:
If customer wants us to prepare products:
- Preparation takes about 2 weeks to 1 month.
- 50% advance payment is required.
- Minimum order for preparation is 600.

Delivery:
- Outside Uzbekistan: 3-5 days depending on location.
- Inside Uzbekistan: 2-3 days.
- Delivery options: postal service or Isuzu car.

Minimum order:
- Outside Uzbekistan: minimum 2000 USD.
- Inside Uzbekistan: no minimum amount.

KG purchase:
If they want to buy by KG, tell them to contact:
+998 93 400 44 33

Telegram groups:
- Single product: t.me/milanapremium1
- Package: t.me/milanapremium3
- Мешок / bag: t.me/milanapremium2

Buying flow:
Ask how many they want to purchase.
Then send the correct Telegram group depending on their answer:
single product, package, or мешок/bag.

End rule:
When the conversation is ending, thank them and ask them to follow:
Instagram: https://www.instagram.com/milanapremium/
TikTok: tiktok.com/@milana_premium_rasmiy
"""


def get_ai_reply(phone: str, user_text: str) -> str:
    chat = get_chat(phone)

    if not chat["intro_sent"]:
        chat["intro_sent"] = True
        intro = first_intro_message()
        add_memory(phone, "assistant", intro)
        return intro

    if not MISTRAL_API_KEY:
        return "Xabaringiz qabul qilindi 😊 Qanday yordam bera olaman?"

    messages = [{"role": "system", "content": build_system_prompt(chat["intro_sent"])}]
    messages.extend(chat["messages"])
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
                user_text = extract_message_text(message)

                log("CUSTOMER MESSAGE", {"from": from_phone, "text": user_text})

                add_memory(from_phone, "user", user_text)

                if is_low_signal_message(user_text):
                    log("IGNORED LOW SIGNAL MESSAGE", {"from": from_phone, "text": user_text})
                    continue

                reply = get_ai_reply(from_phone, user_text)

                add_memory(from_phone, "assistant", reply)

                send_whatsapp_text(from_phone, reply)

    return JSONResponse({"status": "ok"})
