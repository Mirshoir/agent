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

PROCESSED_MESSAGES = {}


def log(title, data=None):
    print("\n" + "=" * 80)
    print(title)
    if data is not None:
        print(data)
    print("=" * 80 + "\n")


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
        "status": "WhatsApp backend is running",
        "has_verify_token": bool(VERIFY_TOKEN),
        "has_whatsapp_access_token": bool(WHATSAPP_ACCESS_TOKEN),
        "has_phone_number_id": bool(WHATSAPP_PHONE_NUMBER_ID),
        "has_business_account_id": bool(WHATSAPP_BUSINESS_ACCOUNT_ID),
        "graph_version": GRAPH_VERSION,
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
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        log(
            "WHATSAPP SEND ERROR",
            "Missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID",
        )
        return False, {"error": "Missing WhatsApp env variables"}

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": str(to_phone),
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
                        contacts[0]
                        .get("profile", {})
                        .get("name")
                        or from_phone
                    )

                if msg_type == "text":
                    text = message.get("text", {}).get("body", "")
                elif msg_type == "image":
                    text = message.get("image", {}).get("caption") or "Photo received"
                elif msg_type == "video":
                    text = message.get("video", {}).get("caption") or "Video received"
                elif msg_type == "audio":
                    text = "Voice message received"
                elif msg_type == "document":
                    text = message.get("document", {}).get("caption") or "Document received"
                elif msg_type == "button":
                    text = message.get("button", {}).get("text", "")
                elif msg_type == "interactive":
                    interactive = message.get("interactive", {})
                    text = (
                        interactive.get("button_reply", {}).get("title")
                        or interactive.get("list_reply", {}).get("title")
                        or "Interactive message received"
                    )
                else:
                    text = f"Unsupported message type: {msg_type}"

                log(
                    "CUSTOMER MESSAGE",
                    {
                        "from": from_phone,
                        "name": customer_name,
                        "type": msg_type,
                        "text": text,
                    },
                )

                reply = f"✅ WhatsApp backend received your message: {text}"
                send_whatsapp_text(from_phone, reply)

    return JSONResponse({"status": "ok"})
