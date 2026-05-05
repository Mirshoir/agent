import os
import secrets
import requests
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse
from supabase import create_client

app = FastAPI()

VERIFY_TOKEN = "1234"

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")
REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://agent-1-xi6h.onrender.com/auth/callback"
)
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://your-dashboard-url")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_comment_ids = set()
processed_message_ids = set()


# ---------------- BUSINESS DB ----------------

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


def upsert_connected_business(profile: dict, access_token: str):
    instagram_business_id = str(profile.get("id", "")).strip()
    username = profile.get("username", "")

    if not instagram_business_id:
        raise ValueError("Instagram profile did not return an id")

    existing = get_business(instagram_business_id)

    data = {
        "instagram_business_id": instagram_business_id,
        "access_token": access_token,
        "bot_enabled": True,
    }

    if username:
        data["business_name"] = username

    if existing:
        result = (
            supabase.table("businesses")
            .update(data)
            .eq("id", existing["id"])
            .execute()
        )
        return result.data

    insert_data = {
        "instagram_business_id": instagram_business_id,
        "business_name": username or f"Instagram {instagram_business_id}",
        "business_type": "",
        "language": "uz",
        "tone": "friendly, polite, sales-focused",
        "knowledge": "",
        "products": "",
        "prices": "",
        "delivery_info": "",
        "working_hours": "",
        "faq": "",
        "catalog_link": "",
        "sales_phone": "",
        "telegram_single": "",
        "telegram_package": "",
        "telegram_bag": "",
        "access_token": access_token,
        "bot_enabled": True,
    }

    result = supabase.table("businesses").insert(insert_data).execute()
    return result.data


# ---------------- INSTAGRAM OAUTH ----------------

@app.get("/connect-instagram")
async def connect_instagram():
    if not META_APP_ID:
        return PlainTextResponse("Missing META_APP_ID", status_code=500)

    params = {
        "client_id": META_APP_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": ",".join([
            "instagram_business_basic",
            "instagram_business_manage_messages",
            "instagram_business_manage_comments"
        ]),
        "response_type": "code",
        "state": secrets.token_urlsafe(16),
    }

    auth_url = "https://www.instagram.com/oauth/authorize?" + urlencode(params)
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    error_description = request.query_params.get("error_description")

    if error:
        return PlainTextResponse(
            f"Instagram connection failed: {error} - {error_description}",
            status_code=400
        )

    if not code:
        return PlainTextResponse("Missing code from Instagram", status_code=400)

    if not META_APP_ID or not META_APP_SECRET:
        return PlainTextResponse(
            "Missing META_APP_ID or META_APP_SECRET",
            status_code=500
        )

    try:
        token_url = "https://api.instagram.com/oauth/access_token"

        token_payload = {
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        }

        token_res = requests.post(token_url, data=token_payload, timeout=30)
        print("OAuth token result:", token_res.status_code, token_res.text)
        token_res.raise_for_status()

        token_data = token_res.json()
        access_token = token_data.get("access_token")

        if not access_token:
            return PlainTextResponse("No access token returned", status_code=500)

        profile_url = "https://graph.instagram.com/me"
        profile_params = {
            "fields": "id,username,account_type",
            "access_token": access_token,
        }

        profile_res = requests.get(profile_url, params=profile_params, timeout=30)
        print("Instagram profile result:", profile_res.status_code, profile_res.text)
        profile_res.raise_for_status()

        profile = profile_res.json()

        upsert_connected_business(profile, access_token)

        return RedirectResponse(
            f"{DASHBOARD_URL}?connected=success&ig_id={profile.get('id')}"
        )

    except Exception as e:
        print("OAuth callback error:", str(e))
        return PlainTextResponse(f"OAuth error: {str(e)}", status_code=500)


# ---------------- CATALOG LOGIC ----------------

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
            "Tezroq ma’lumot olish uchun sales manager bilan bog‘lanishingiz mumkin."
        )

    return (
        f"Katalogni shu havola orqali ko‘rishingiz mumkin:\n{catalog_link}\n\n"
        "Qo‘shimcha ma’lumot kerak bo‘lsa, yozib qoldiring 😊"
    )


# ---------------- AI ----------------

def build_business_context(business: dict) -> str:
    return f"""
Business name:
{business.get("business_name", "")}

Business type:
{business.get("business_type", "")}

Tone:
{business.get("tone", "")}

Products / services:
{business.get("products", "")}

Prices:
{business.get("prices", "")}

Delivery info:
{business.get("delivery_info", "")}

Working hours:
{business.get("working_hours", "")}

FAQ:
{business.get("faq", "")}

Catalog link:
{business.get("catalog_link", "")}

Sales phone:
{business.get("sales_phone", "")}

Telegram single product:
{business.get("telegram_single", "")}

Telegram package:
{business.get("telegram_package", "")}

Telegram bag / meshok:
{business.get("telegram_bag", "")}

General knowledge:
{business.get("knowledge", "")}
"""


def get_ai_reply(user_text: str, business: dict) -> str:
    url = "https://api.mistral.ai/v1/chat/completions"

    language = business.get("language", "uz")
    business_context = build_business_context(business)

    system_prompt = f"""
You are the virtual Instagram sales assistant for this business.

Business profile:
{business_context}

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
- Use only the business profile above.
- Do NOT invent prices, stock, addresses, discounts, delivery details, or product availability.
- If information is missing, ask one short follow-up question.
- Do not force users to share phone/address/name.
- Do not repeatedly ask for contact details.
- If user wants a human/sales manager, provide the contact details from business profile.
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


# ---------------- INSTAGRAM ACTIONS ----------------

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


# ---------------- ROUTES ----------------

@app.get("/")
async def home():
    return {
        "status": "ok",
        "message": "Instagram AI webhook server is running",
        "connect_instagram": "/connect-instagram",
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
                    continue

                if message_id and message_id in processed_message_ids:
                    continue

                if message_id:
                    processed_message_ids.add(message_id)

                if sender_id and message_text:
                    if is_catalog_request(message_text):
                        send_dm(access_token, sender_id, build_catalog_dm(business))
                    else:
                        ai_reply = get_ai_reply(message_text, business)
                        send_dm(access_token, sender_id, ai_reply)

            for change in entry.get("changes", []):
                if change.get("field") == "comments":
                    value = change.get("value", {})
                    comment_id = value.get("id")
                    comment_text = value.get("text")
                    from_id = value.get("from", {}).get("id")

                    if from_id == instagram_business_id:
                        continue

                    if comment_id and comment_id in processed_comment_ids:
                        continue

                    if comment_id:
                        processed_comment_ids.add(comment_id)

                    if comment_id and comment_text:
                        if is_catalog_request(comment_text):
                            if from_id:
                                send_dm(access_token, from_id, build_catalog_dm(business))

                            reply_to_comment(
                                access_token,
                                comment_id,
                                "Katalog va narxlar haqida ma’lumotni DM orqali yubordik 😊"
                            )
                        else:
                            ai_reply = get_ai_reply(comment_text, business)
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
