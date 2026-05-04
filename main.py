import os
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse

app = FastAPI()

VERIFY_TOKEN = "1234"

INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")


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
                "content": "You are a friendly Instagram sales assistant. Reply shortly and naturally."
            },
            {
                "role": "user",
                "content": user_text
            }
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }

    res = requests.post(url, headers=headers, json=payload, timeout=30)
    print("Mistral result:", res.status_code, res.text)
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
    print("DM send result:", res.status_code, res.text)
    return res


def reply_to_comment(comment_id: str, text: str):
    url = f"https://graph.instagram.com/v25.0/{comment_id}/replies"

    params = {
        "access_token": INSTAGRAM_ACCESS_TOKEN,
        "message": text
    }

    res = requests.post(url, params=params, timeout=30)
    print("Comment reply result:", res.status_code, res.text)
    return res


@app.get("/")
async def home():
    return {
        "status": "ok",
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
        print("Received webhook:", data)

        for entry in data.get("entry", []):

            # DM EVENTS
            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id")
                message_text = messaging.get("message", {}).get("text")

                if sender_id and message_text:
                    print("DM user said:", message_text)

                    ai_reply = get_ai_reply(message_text)
                    print("AI DM reply:", ai_reply)

                    send_dm(sender_id, ai_reply)

            # COMMENT EVENTS
            for change in entry.get("changes", []):
                if change.get("field") == "comments":
                    value = change.get("value", {})

                    comment_id = value.get("id")
                    comment_text = value.get("text")

                    if comment_id and comment_text:
                        print("Comment received:", comment_text)

                        ai_reply = get_ai_reply(comment_text)
                        print("AI comment reply:", ai_reply)

                        reply_to_comment(comment_id, ai_reply)

        return JSONResponse(content={"status": "ok"}, status_code=200)

    except Exception as e:
        print("Webhook error:", str(e))
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
