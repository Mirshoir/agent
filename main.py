import os
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse

app = FastAPI()

VERIFY_TOKEN = "1234"

INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# ---------------- AI RESPONSE ----------------
def get_ai_reply(user_text: str) -> str:
    url = "https://api.mistral.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": "You are a friendly Instagram assistant. Reply shortly."},
            {"role": "user", "content": user_text}
        ]
    }

    res = requests.post(url, headers=headers, json=payload)
    return res.json()["choices"][0]["message"]["content"]


# ---------------- SEND MESSAGE ----------------
def send_message(recipient_id, text):
    url = "https://graph.facebook.com/v25.0/me/messages"

    params = {
        "access_token": INSTAGRAM_ACCESS_TOKEN
    }

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    res = requests.post(url, params=params, json=payload)
    print("Send result:", res.text)


# ---------------- ROUTES ----------------
@app.get("/")
async def home():
    return {"status": "ok", "message": "Instagram webhook server is running"}


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params

    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN
    ):
        return PlainTextResponse(params.get("hub.challenge"))

    return PlainTextResponse("Verification failed", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()
    print("Received webhook:", data)

    try:
        for entry in data.get("entry", []):
            for messaging in entry.get("messaging", []):

                sender_id = messaging.get("sender", {}).get("id")
                message_text = messaging.get("message", {}).get("text")

                if sender_id and message_text:
                    print("User said:", message_text)

                    ai_reply = get_ai_reply(message_text)

                    send_message(sender_id, ai_reply)

    except Exception as e:
        print("Webhook error:", str(e))

    return JSONResponse(content={"status": "ok"})


@app.get("/privacy")
async def privacy():
    return PlainTextResponse("Privacy Policy...")


@app.get("/terms")
async def terms():
    return PlainTextResponse("Terms of Service...")
