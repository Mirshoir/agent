import os
import time
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import uvicorn

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "EAAXHWuBXZCp0BRSh17y3lX5lqfmbNOGYtlFPcAlMXl8ZAKmBBV25ApVm7bW8c3pCprJoGbs7u895gXRoR0u9XkLBCEsO9CC1e6v4YWaBwX3yxmEZBB8szgSCCTRZAjgviJv8FgwJi7KrJzPWtFqZAfB4VGzKykzYk3xuuJ4JJZAYNvMb60wn5Jq2TxWfbu7QZDZD")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "65748392018475")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")

PROCESSED_MESSAGES = {}


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
    return {"status": "WhatsApp backend is running"}


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    print("VERIFY REQUEST:", params)

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge)

    return PlainTextResponse("Verification failed", status_code=403)


def send_whatsapp_text(to_phone: str, text: str):
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("Missing WhatsApp env variables")
        return False

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

    res = requests.post(url, headers=headers, json=payload, timeout=30)

    print("SEND RESULT:", res.status_code, res.text)

    return res.ok


@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()

    print("\n========== WHATSAPP WEBHOOK RECEIVED ==========")
    print(data)
    print("==============================================\n")

    if data.get("object") != "whatsapp_business_account":
        return JSONResponse({"status": "ignored"})

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])

            for message in messages:
                message_id = message.get("id")

                if already_processed(message_id):
                    print("Duplicate message ignored:", message_id)
                    continue

                from_phone = message.get("from")
                msg_type = message.get("type")

                text = ""

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

                print("FROM:", from_phone)
                print("MESSAGE:", text)

                reply = f"Message received: {text}"

                send_whatsapp_text(from_phone, reply)

    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("whatsapp_backend:app", host="0.0.0.0", port=port)