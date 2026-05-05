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

    print("Looking for business ID:", repr(instagram_business_id))

    result = (
        supabase.table("businesses")
        .select("*")
        .ilike("instagram_business_id", instagram_business_id)
        .limit(1)
        .execute()
    )

    print("Supabase result:", result.data)

    if not result.data:
        debug_rows = (
            supabase.table("businesses")
            .select("instagram_business_id,business_name")
            .limit(10)
            .execute()
        )
        print("Available businesses:", debug_rows.data)
        return None

    return result.data[0]


def is_catalog_request(text: str) -> bool:
    text = text.lower()

    keywords = [
        "catalog", "katalog", "каталог",
        "price", "narx", "narxi", "цена", "прайс",
        "cost", "how much", "qancha", "сколько"
    ]

    return any(keyword in text for keyword in keywords)


def get_catalog_link(business: dict) -> str:
    catalog_link = business.get("catalog_link")

    if catalog_link:
        return catalog_link

    knowledge = business.get("knowledge", "")

    if "https://bitly.cx/eIbT0" in knowledge:
        return "https://bitly.cx/eIbT0"

    return ""


def build_catalog_dm(business: dict) -> str:
    catalog_link = get_catalog_link(business)

    if not catalog_link:
        return (
            "Katalog havolasi hozircha mavjud emas. "
            "Tezroq ma’lumot olish uchun sales manager bilan bog‘lanishingiz mumkin: +998 50 155 10 10"
        )

    return (
        f"Katalogni shu havola orqali ko‘rishingiz mumkin:\n{catalog_link}\n\n"
        "Qo‘shimcha ma’lumot kerak bo‘lsa, yozib qoldiring 😊"
    )


def get_ai_reply(user_text: str, business: dict) -> str:
    url = "https://api.mistral.ai/v1/chat/completions"

    business_name = business.get("business_name", "this business")
    business_type = business.get("business_type", "business")
    tone = business.get("tone", "friendly and professional")
    language = business.get("language", "uz")
    knowledge = business.get("knowledge", "")
    catalog_link = get_catalog_link(business)

    system_prompt = f"""
You are the virtual Instagram sales assistant for {business_name}.

Business type:
{business_type}

Business tone:
{tone}

Business knowledge:
{knowledge}

Catalog link:
{catalog_link}

Language rules:
- Detect the user's language.
- If the user writes in Uzbek, reply in Uzbek.
- If the user writes in Russian, reply in Russian.
- If the user writes in English, reply in English.
- If unclear, use this default language: {language}.

Sales style:
- Reply shortly, naturally, and politely.
- Be helpful and sales-focused.
- Do not sound robotic.
- Do not say you are an AI model.

Strict business rules:
- Use only the business knowledge above.
- Do NOT invent prices, stock, addresses, discounts, delivery details, or product availability.
- If information is missing, ask one short follow-up question.
- Do not force users to share phone/address/name.
- Do not repeatedly ask for contact details.
- If user wants a human/sales manager, provide the contact details from business knowledge.
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
        "temperature": 0.4,
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
            print("ENTRY ID FROM META:", repr(instagram_business_id))

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

            # DM EVENTS
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

                    if is_catalog_request(message_text):
                        dm_reply = build_catalog_dm(business)
                        send_dm(access_token, sender_id, dm_reply)
                    else:
                        ai_reply = get_ai_reply(message_text, business)
                        print("AI DM reply:", ai_reply)
                        send_dm(access_token, sender_id, ai_reply)

            # COMMENT EVENTS
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

                        if is_catalog_request(comment_text):
                            dm_reply = build_catalog_dm(business)

                            if from_id:
                                send_dm(access_token, from_id, dm_reply)

                            public_reply = (
                                "Katalog va narxlar haqida ma’lumotni DM orqali yubordik 😊"
                            )

                            reply_to_comment(access_token, comment_id, public_reply)

                        else:
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
