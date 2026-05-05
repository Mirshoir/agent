import os
import time
import logging
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")

INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
INSTAGRAM_BUSINESS_ID = os.getenv("INSTAGRAM_BUSINESS_ID")

BOT_ENABLED = os.getenv("BOT_ENABLED", "true").lower() == "true"

MAX_REPLIES_PER_USER = int(os.getenv("MAX_REPLIES_PER_USER", "5"))

processed_message_ids = set()
processed_comment_ids = set()
user_reply_count = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def can_reply(user_id: str) -> bool:
    count = user_reply_count.get(user_id, 0)

    if count >= MAX_REPLIES_PER_USER:
        logging.info(f"Reply limit reached for user: {user_id}")
        return False

    user_reply_count[user_id] = count + 1
    return True


def get_ai_reply(user_text: str) -> str:
    url = "https://api.mistral.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a friendly Instagram sales assistant. "
                    "Reply shortly and naturally. "
                    "Do not mention that you are AI."
                )
            },
            {
                "role": "user",
                "content": user_text
            }
        ],
        "temperature": 0.7,
        "max_tokens": 120
    }

    res = requests.post(url, headers=headers, json=payload, timeout=30)
    logging.info(f"Mistral status: {res.status_code}")

    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]


def send_dm(recipient_id: str, text: str):
    url = "https://graph.instagram.com/v25.0/me/messages"

    params = {
        "access_token": INSTAGRAM_ACCESS_TOKEN
    }

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    res = requests.post(url, params=params, json=payload, timeout=30)
    logging.info(f"DM send status: {res.status_code} | {res.text}")
    return res


def reply_to_comment(comment_id: str, text: str):
    url = f"https://graph.instagram.com/v25.0/{comment_id}/replies"

    params = {
        "access_token": INSTAGRAM_ACCESS_TOKEN,
        "message": text
    }

    res = requests.post(url, params=params, timeout=30)
    logging.info(f"Comment reply status: {res.status_code} | {res.text}")
    return res


@app.get("/")
async def home():
    return {
        "status": "ok",
        "bot_enabled": BOT_ENABLED,
        "message": "Instagram AI webhook server is running"
    }


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(challenge, status_code=200)

    return PlainTextResponse("Verification failed", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()

        if not BOT_ENABLED:
            logging.info("Bot disabled. Webhook received but ignored.")
            return JSONResponse(content={"status": "disabled"}, status_code=200)

        for entry in data.get("entry", []):

            # DM EVENTS ONLY
            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id")
                message = messaging.get("message", {})
                message_text = message.get("text")
                message_id = message.get("mid")

                if not sender_id or not message_text:
                    continue

                if INSTAGRAM_BUSINESS_ID and sender_id == INSTAGRAM_BUSINESS_ID:
                    logging.info("Ignored own DM event")
                    continue

                if message_id in processed_message_ids:
                    logging.info(f"Ignored duplicate DM: {message_id}")
                    continue

                processed_message_ids.add(message_id)

                if not can_reply(sender_id):
                    continue

                ai_reply = get_ai_reply(message_text)
                send_dm(sender_id, ai_reply)

            # COMMENT EVENTS ONLY
            for change in entry.get("changes", []):
                if change.get("field") != "comments":
                    continue

                value = change.get("value", {})

                comment_id = value.get("id")
                comment_text = value.get("text")
                from_id = value.get("from", {}).get("id")

                if not comment_id or not comment_text or not from_id:
                    continue

                if INSTAGRAM_BUSINESS_ID and from_id == INSTAGRAM_BUSINESS_ID:
                    logging.info("Ignored own comment")
                    continue

                if comment_id in processed_comment_ids:
                    logging.info(f"Ignored duplicate comment: {comment_id}")
                    continue

                processed_comment_ids.add(comment_id)

                if not can_reply(from_id):
                    continue

                ai_reply = get_ai_reply(comment_text)
                reply_to_comment(comment_id, ai_reply)

        return JSONResponse(content={"status": "ok"}, status_code=200)

    except Exception as e:
        logging.exception("Webhook error")
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500
        )


@app.get("/privacy")
async def privacy():
    return PlainTextResponse(
        "Privacy Policy: This app collects Instagram messages and comments to provide automated AI replies. "
        "No personal data is sold or shared with third parties."
    )


@app.get("/terms")
async def terms():
    return PlainTextResponse(
        "Terms of Service: This app provides automated Instagram replies using AI. "
        "Responses may not always be accurate. This service is provided as is."
    )
