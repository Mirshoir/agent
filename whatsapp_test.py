import os
import time
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v25.0")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "AiAgent")
BUSINESS_INFO = os.getenv(
    "BUSINESS_INFO",
    """
You are a helpful WhatsApp sales assistant.
Reply shortly, naturally, and politely.
Ask follow-up questions when needed.
Do not mention that you are AI.
""",
)

PROCESSED_MESSAGES = {}


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


@app.get("/")
def home():
    return {
        "status": "WhatsApp AI backend is running",
        "has_verify_token": bool(VERIFY_TOKEN),
        "has_whatsapp_access_token": bool(WHATSAPP_ACCESS_TOKEN),
        "has_phone_number_id": bool(WHATSAPP_PHONE_NUMBER_ID),
        "has_business_account_id": bool(WHATSAPP_BUSINESS_ACCOUNT_ID),
        "has_mistral_api_key": bool(MISTRAL_API_KEY),
        "graph_version": GRAPH_VERSION,
        "business_name": BUSINESS_NAME,
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


def get_ai_reply(user_text: str) -> str:
    if not MISTRAL_API_KEY:
        return "Xabaringiz qabul qilindi 😊 Qanday yordam bera olaman?"

    system_prompt = f"""
You are a real human WhatsApp sales manager for {BUSINESS_NAME}.

Business information:
{BUSINESS_INFO}

Rules:
- Reply in the customer's language.
- Keep replies short and natural.
- Usually 1-3 short sentences.
- Do not write long lists unless asked.
- Do not invent prices, stock, delivery, discounts, or address.
- If information is missing, say the manager will clarify.
- Do not mention AI, bot, automation, API, or database.
- Focus on helping and selling.
"""

    try:
        res = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MISTRAL_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "temperature": 0.5,
                "max_tokens": 160,
            },
            timeout=30,
        )

        try:
            result = res.json()
        except Exception:
            result = {"raw": res.text}

        log("MISTRAL RESULT", {"status": res.status_code, "body": result})

        if not res.ok:
            return "Xabaringiz qabul qilindi 😊 Qanday yordam bera olaman?"

        reply = result["choices"][0]["message"]["content"].strip()
        return reply[:1500] if reply else "Qanday yordam bera olaman?"

    except Exception as e:
        log("MISTRAL ERROR", str(e))
        return "Xabaringiz qabul qilindi 😊 Qanday yordam bera olaman?"


def send_whatsapp_text(to_phone: str, text: str):
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        log("SEND ERROR", "Missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID")
        return False, {"error": "missing_env"}

    clean_phone = str(to_phone).replace("+", "").replace(" ", "").strip()

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone,
        "type": "text",
        "text": {
            "preview_url": False,
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
        log("WHATSAPP SEND EXCEPTION", str(e))
        return False, {"error": str(e)}


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
        return JSONResponse({"status": "ignored", "object": data.get("object")})

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            if "statuses" in value:
                log("WHATSAPP STATUS UPDATE", value.get("statuses"))
                continue

            messages = value.get("messages", [])
            contacts = value.get("contacts", [])

            if not messages:
                log("NO CUSTOMER MESSAGES FOUND", value)
                continue

            for message in messages:
                message_id = message.get("id", "")

                if already_processed(message_id):
                    log("DUPLICATE MESSAGE IGNORED", message_id)
                    continue

                from_phone = message.get("from", "")
                msg_type = message.get("type", "")
                customer_name = from_phone

                if contacts:
                    customer_name = (
                        contacts[0].get("profile", {}).get("name")
                        or from_phone
                    )

                user_text = extract_message_text(message)

                log(
                    "CUSTOMER MESSAGE",
                    {
                        "from": from_phone,
                        "name": customer_name,
                        "type": msg_type,
                        "text": user_text,
                    },
                )

                ai_reply = get_ai_reply(user_text)

                log("AI REPLY", ai_reply)

                send_whatsapp_text(from_phone, ai_reply)

    return JSONResponse({"status": "ok"})
