import os
import secrets
import requests
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse
from supabase import create_client

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")

REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://agent-1-xi6h.onrender.com/auth/callback"
)

DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL",
    "https://instaagent.streamlit.app"
)

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_comment_ids = set()
processed_message_ids = set()


def safe_token(token: str) -> str:
    if not token:
        return ""
    return token[:10] + "..." + token[-6:]


def get_business(instagram_business_id: str):
    result = (
        supabase.table("businesses")
        .select("*")
        .eq("instagram_business_id", str(instagram_business_id).strip())
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    print("Business not found:", instagram_business_id)
    return None


def get_business_for_webhook(webhook_entry_id: str):
    webhook_entry_id = str(webhook_entry_id).strip()

    business = get_business(webhook_entry_id)
    if business:
        return business

    fallback = (
        supabase.table("businesses")
        .select("*")
        .eq("bot_enabled", True)
        .limit(2)
        .execute()
    )

    rows = fallback.data or []

    if len(rows) == 1:
        business = rows[0]

        print(
            "Auto-binding webhook entry id",
            webhook_entry_id,
            "to business",
            business.get("business_name")
        )

        updated = (
            supabase.table("businesses")
            .update({"instagram_business_id": webhook_entry_id})
            .eq("id", business["id"])
            .execute()
        )

        if updated.data:
            return updated.data[0]

    print("No safe business fallback found for webhook id:", webhook_entry_id)
    return None


def upsert_connected_business(profile: dict, access_token: str):
    instagram_user_id = str(
        profile.get("user_id") or profile.get("id") or ""
    ).strip()

    username = profile.get("username") or f"instagram_{instagram_user_id}"

    if not instagram_user_id:
        raise ValueError("Instagram token response did not return user_id")

    existing = get_business(instagram_user_id)

    update_data = {
        "instagram_business_id": instagram_user_id,
        "access_token": access_token,
        "bot_enabled": True,
        "business_name": username,
        "business_type": "Instagram Business",
    }

    if existing:
        result = (
            supabase.table("businesses")
            .update(update_data)
            .eq("id", existing["id"])
            .execute()
        )
        return result.data

    insert_data = {
        **update_data,
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
    }

    result = supabase.table("businesses").insert(insert_data).execute()
    return result.data


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
            "instagram_business_manage_comments",
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
            status_code=400,
        )

    if not code:
        return PlainTextResponse("Missing code from Instagram", status_code=400)

    if not META_APP_ID or not META_APP_SECRET:
        return PlainTextResponse(
            "Missing META_APP_ID or META_APP_SECRET",
            status_code=500,
        )

    try:
        token_res = requests.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
                "code": code,
            },
            timeout=30,
        )

        print("OAuth token status:", token_res.status_code)
        print("OAuth token response:", token_res.text)

        token_res.raise_for_status()
        token_data = token_res.json()

        access_token = token_data.get("access_token")
        instagram_user_id = token_data.get("user_id")

        if not access_token:
            return PlainTextResponse(
                f"No access token returned: {token_data}",
                status_code=500,
            )

        if not instagram_user_id:
            return PlainTextResponse(
                f"No user_id returned from Instagram token response: {token_data}",
                status_code=500,
            )

        print("Received Instagram token:", safe_token(access_token))
        print("Instagram OAuth user_id:", instagram_user_id)

        profile = {
            "id": str(instagram_user_id),
            "user_id": str(instagram_user_id),
            "username": f"instagram_{instagram_user_id}",
        }

        upsert_connected_business(profile, access_token)

        return RedirectResponse(
            f"{DASHBOARD_URL}?connected=success&ig_id={instagram_user_id}"
        )

    except requests.HTTPError as e:
        response_text = e.response.text if e.response else str(e)
        print("OAuth HTTP error:", response_text)
        return PlainTextResponse(
            f"OAuth HTTP error: {response_text}",
            status_code=400,
        )

    except Exception as e:
        print("OAuth callback error:", str(e))
        return PlainTextResponse(
            f"OAuth error: {str(e)}",
            status_code=500,
        )


def is_catalog_request(text: str) -> bool:
    text = text.lower()

    keywords = [
        "catalog", "katalog", "каталог",
        "price", "narx", "narxi", "цена", "прайс",
        "cost", "how much", "qancha", "сколько",
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
    language = business.get("language", "uz")
    business_context = build_business_context(business)

    system_prompt = f"""
You are the virtual Instagram sales assistant for this business.

Business profile:
{business_context}

Language rules:
- Detect the user's language.
- If Uzbek, reply in Uzbek.
- If Russian, reply in Russian.
- If English, reply in English.
- If unclear, use this default language: {language}.

Opening conversation rules:
- If this is the beginning of a conversation, greet the user.
- Introduce yourself as the business virtual assistant.
- Politely say the user may leave name, phone number, address, interested product, and quantity for faster help.
- Do not force details.
- Do not repeat this request many times.
- If user ignores it, continue naturally.

Sales style:
- Reply shortly, naturally, and politely.
- Be helpful and sales-focused.
- Do not sound robotic.
- Do not say you are an AI model.

Strict business rules:
- Use only the business profile above.
- Do not invent prices, stock, addresses, discounts, delivery details, or product availability.
- If information is missing, ask one short follow-up question.
- If user wants a human/sales manager, provide contact details from business profile.
"""

    res = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "mistral-small-latest",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.4,
            "max_tokens": 220,
        },
        timeout=30,
    )

    print("Mistral result:", res.status_code, res.text)
    res.raise_for_status()

    return res.json()["choices"][0]["message"]["content"]


def send_dm(access_token: str, recipient_id: str, text: str):
    res = requests.post(
        "https://graph.instagram.com/v21.0/me/messages",
        params={"access_token": access_token},
        json={
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        },
        timeout=30,
    )

    print("DM send result:", res.status_code, res.text)
    return res


def reply_to_comment(access_token: str, comment_id: str, text: str):
    res = requests.post(
        f"https://graph.instagram.com/v21.0/{comment_id}/replies",
        params={
            "access_token": access_token,
            "message": text,
        },
        timeout=30,
    )

    print("Comment reply result:", res.status_code, res.text)
    return res


@app.get("/")
async def home():
    return {
        "status": "ok",
        "oauth_mode": "direct_instagram_login_auto_bind_webhook_id",
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
            webhook_entry_id = str(entry.get("id", "")).strip()

            if not webhook_entry_id:
                continue

            business = get_business_for_webhook(webhook_entry_id)

            if not business:
                continue

            if not business.get("bot_enabled", True):
                print("Bot disabled for:", webhook_entry_id)
                continue

            access_token = business.get("access_token")

            if not access_token:
                print("Missing access token for:", webhook_entry_id)
                continue

            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id")
                message = messaging.get("message", {})
                message_text = message.get("text")
                message_id = message.get("mid")
                is_echo = message.get("is_echo", False)

                if is_echo:
                    print("Ignored echo message")
                    continue

                if sender_id == webhook_entry_id:
                    print("Ignored own sender message")
                    continue

                if message_id and message_id in processed_message_ids:
                    print("Ignored duplicate DM:", message_id)
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
                if change.get("field") != "comments":
                    continue

                value = change.get("value", {})

                comment_id = value.get("id")
                comment_text = value.get("text")
                from_id = value.get("from", {}).get("id")

                if from_id == webhook_entry_id:
                    print("Ignored own comment")
                    continue

                if comment_id and comment_id in processed_comment_ids:
                    print("Ignored duplicate comment:", comment_id)
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
                            "Katalog va narxlar haqida ma’lumotni DM orqali yubordik 😊",
                        )
                    else:
                        ai_reply = get_ai_reply(comment_text, business)
                        reply_to_comment(access_token, comment_id, ai_reply)

        return JSONResponse(content={"status": "ok"}, status_code=200)

    except Exception as e:
        print("Webhook error:", str(e))

        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500,
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
