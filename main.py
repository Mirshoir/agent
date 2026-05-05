import os
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from supabase import create_client

app = FastAPI()

VERIFY_TOKEN = "1234"

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_comment_ids = set()
processed_message_ids = set()


def get_business(instagram_business_id: str):
    instagram_business_id = str(instagram_business_id).strip()

    print("Looking for business ID:", instagram_business_id)

    result = (
        supabase.table("businesses")
        .select("*")
        .eq("instagram_business_id", instagram_business_id)
        .limit(1)
        .execute()
    )

    print("Supabase result:", result.data)

    if not result.data:
        return None

    return result.data[0]


def get_ai_reply(user_text: str, business: dict) -> str:
    url = "https://api.mistral.ai/v1/chat/completions"

    system_prompt = f"""
You are the virtual assistant for {business.get('business_name')}.

Business type:
{business.get('business_type')}

Tone:
{business.get('tone')}

Business knowledge:
{business.get('knowledge')}

Rules:
- Reply naturally and shortly.
- Use the business knowledge only.
- Do not invent prices, addresses, stock, or delivery details.
- If information is missing, ask one short follow-up question.
- Do not repeatedly ask for contact details.
"""

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        "temperature": 0.5,
        "max_tokens": 180
    }

    res = requests.post(url, headers=headers, json=payload, timeout=30)
    print("Mistral result:", res.status_code, res.text)
    res.raise_for_status()

    return res.json()["choices"][0]["message"]["content"]


def send_dm(access_token: str, recipient_id: str, text: str):
    url = "https://graph.instagram.com/v25.0/me/messages"

    params = {"access_token": access_token}

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    res = requests.post(url, params=params, json=payload, timeout=30)
    print("DM send result:", res.status_code, res.text)
    return res


def reply_to_comment(access_token: str, comment_id: str, text: str):
    url = f"https://graph.instagram.com/v25.0/{comment_id}/replies"

    params = {
        "access_token": access_token,
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

    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN
        and params.get("hub.challenge")
    ):
        return PlainTextResponse(params.get("hub.challenge"), status_code=200)

    return PlainTextResponse("Verification failed", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()
        print("Received webhook:", data)

        for entry in data.get("entry", []):
            instagram_business_id = str(entry.get("id", "")).strip()
            print("ENTRY ID FROM META:", instagram_business_id)

            if not instagram_business_id:
                print("No Instagram Business ID in entry")
                continue

            business = get_business(instagram_business_id)

            if not business:
                print("Business not found:", instagram_business_id)
                continue

            if not business.get("bot_enabled", True):
                print("Bot disabled for:", business.get("business_name"))
                continue

            access_token = business.get("access_token")

            if not access_token:
                print("No access token for business:", business.get("business_name"))
                continue

            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id")
                message = messaging.get("message", {})
                message_text = message.get("text")
                message_id = message.get("mid")

                if sender_id == instagram_business_id:
                    print("Ignored own DM")
                    continue

                if message_id and message_id in processed_message_ids:
                    print("Ignored duplicate DM:", message_id)
                    continue

                if message_id:
                    processed_message_ids.add(message_id)

                if sender_id and message_text:
                    print("DM user said:", message_text)

                    ai_reply = get_ai_reply(message_text, business)
                    print("AI DM reply:", ai_reply)

                    send_dm(access_token, sender_id, ai_reply)

            for change in entry.get("changes", []):
                if change.get("field") == "comments":
                    value = change.get("value", {})

                    comment_id = value.get("id")
                    comment_text = value.get("text")
                    from_id = value.get("from", {}).get("id")

                    if from_id == instagram_business_id:
                        print("Ignored own comment")
                        continue

                    if comment_id and comment_id in processed_comment_ids:
                        print("Ignored duplicate comment:", comment_id)
                        continue

                    if comment_id:
                        processed_comment_ids.add(comment_id)

                    if comment_id and comment_text:
                        print("Comment received:", comment_text)

                        ai_reply = get_ai_reply(comment_text, business)
                        print("AI comment reply:", ai_reply)

                        reply_to_comment(access_token, comment_id, ai_reply)

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
