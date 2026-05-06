import os
import time
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

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_comment_ids = {}
processed_message_ids = {}
DEDUP_TTL_SECONDS = 60 * 60


def cleanup_dedup_cache():
    now = time.time()

    for cache in (processed_comment_ids, processed_message_ids):
        expired = [
            key for key, created_at in cache.items()
            if now - created_at > DEDUP_TTL_SECONDS
        ]

        for key in expired:
            cache.pop(key, None)


def already_processed(cache: dict, event_id: str) -> bool:
    if not event_id:
        return False

    cleanup_dedup_cache()

    if event_id in cache:
        return True

    cache[event_id] = time.time()
    return False


def safe_token(token: str) -> str:
    if not token:
        return ""

    token = str(token)

    if len(token) <= 18:
        return token[:4] + "..."

    return token[:10] + "..." + token[-6:]


def normalize_id(value) -> str:
    return str(value or "").strip()


def get_business(instagram_business_id: str):
    instagram_business_id = normalize_id(instagram_business_id)

    if not instagram_business_id:
        return None

    result = (
        supabase.table("businesses")
        .select("*")
        .eq("instagram_business_id", instagram_business_id)
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


def find_business_for_webhook(entry_id: str, recipient_id: str = ""):
    entry_id = normalize_id(entry_id)
    recipient_id = normalize_id(recipient_id)

    business = get_business(entry_id)
    if business:
        print("Business matched by entry_id:", entry_id)
        return business

    business = get_business(recipient_id)
    if business:
        print("Business matched by recipient_id:", recipient_id)
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
        bind_id = recipient_id or entry_id

        if bind_id:
            print(
                "SAFE AUTO-BIND:",
                "webhook_id=", bind_id,
                "business=", business.get("business_name")
            )

            updated = (
                supabase.table("businesses")
                .update({"instagram_business_id": bind_id})
                .eq("id", business["id"])
                .execute()
            )

            if updated.data:
                return updated.data[0]

        return business

    print(
        "No matching business found.",
        "entry_id=", entry_id,
        "recipient_id=", recipient_id,
        "enabled_business_count=", len(rows)
    )

    return None


def exchange_code_for_token(code: str):
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
    return token_res.json()


def get_instagram_profile(access_token: str, fallback_user_id: str = ""):
    try:
        res = requests.get(
            f"https://graph.instagram.com/{GRAPH_VERSION}/me",
            params={
                "fields": "id,user_id,username,account_type",
                "access_token": access_token,
            },
            timeout=30,
        )

        print("Profile status:", res.status_code)
        print("Profile response:", res.text)

        if res.ok:
            data = res.json()

            instagram_id = normalize_id(
                data.get("user_id") or data.get("id") or fallback_user_id
            )

            return {
                "id": instagram_id,
                "user_id": instagram_id,
                "username": data.get("username") or f"instagram_{instagram_id}",
                "account_type": data.get("account_type", ""),
            }

    except Exception as e:
        print("Profile fetch failed:", str(e))

    fallback_user_id = normalize_id(fallback_user_id)

    return {
        "id": fallback_user_id,
        "user_id": fallback_user_id,
        "username": f"instagram_{fallback_user_id}",
        "account_type": "",
    }


def upsert_connected_business(profile: dict, access_token: str):
    instagram_user_id = normalize_id(
        profile.get("user_id") or profile.get("id")
    )

    if not instagram_user_id:
        raise ValueError("Instagram profile did not return user_id/id")

    username = profile.get("username") or f"instagram_{instagram_user_id}"

    row = {
        "instagram_business_id": instagram_user_id,
        "access_token": access_token,
        "bot_enabled": True,
        "business_name": username,
        "business_type": "Instagram Business",
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

    existing = get_business(instagram_user_id)

    if existing:
        print("Updating existing business:", existing.get("id"))

        update_data = {
            "instagram_business_id": instagram_user_id,
            "access_token": access_token,
            "bot_enabled": True,
            "business_name": username,
            "business_type": "Instagram Business",
        }

        result = (
            supabase.table("businesses")
            .update(update_data)
            .eq("id", existing["id"])
            .execute()
        )

        return result.data

    print("Creating/upserting new business:", instagram_user_id)

    try:
        result = (
            supabase.table("businesses")
            .upsert(row, on_conflict="instagram_business_id")
            .execute()
        )

        return result.data

    except Exception as e:
        print("Upsert failed, trying update fallback:", str(e))

        existing = get_business(instagram_user_id)

        if existing:
            result = (
                supabase.table("businesses")
                .update({
                    "access_token": access_token,
                    "bot_enabled": True,
                    "business_name": username,
                    "business_type": "Instagram Business",
                })
                .eq("id", existing["id"])
                .execute()
            )

            return result.data

        raise


def sanitize_business_row(row: dict):
    clean = dict(row)
    clean["access_token"] = safe_token(clean.get("access_token", ""))
    return clean


@app.get("/")
async def home():
    return {
        "status": "ok",
        "oauth_mode": "direct_instagram_login_fixed_with_debug",
        "connect_instagram": "/connect-instagram",
        "debug_businesses": "/debug/businesses",
        "debug_enabled_businesses": "/debug/enabled-businesses",
    }


@app.get("/debug/businesses")
async def debug_businesses():
    result = (
        supabase.table("businesses")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    rows = [sanitize_business_row(row) for row in (result.data or [])]

    return {
        "count": len(rows),
        "businesses": rows,
    }


@app.get("/debug/business/{instagram_id}")
async def debug_business_by_instagram_id(instagram_id: str):
    instagram_id = normalize_id(instagram_id)

    result = (
        supabase.table("businesses")
        .select("*")
        .eq("instagram_business_id", instagram_id)
        .execute()
    )

    rows = [sanitize_business_row(row) for row in (result.data or [])]

    return {
        "instagram_id_searched": instagram_id,
        "count": len(rows),
        "rows": rows,
    }


@app.get("/debug/enabled-businesses")
async def debug_enabled_businesses():
    result = (
        supabase.table("businesses")
        .select("*")
        .eq("bot_enabled", True)
        .execute()
    )

    rows = [sanitize_business_row(row) for row in (result.data or [])]

    return {
        "count": len(rows),
        "rows": rows,
    }


@app.get("/debug/business-ids")
async def debug_business_ids():
    result = (
        supabase.table("businesses")
        .select("id,business_name,instagram_business_id,bot_enabled,access_token,created_at")
        .order("created_at", desc=True)
        .execute()
    )

    rows = []

    for row in result.data or []:
        rows.append({
            "id": row.get("id"),
            "business_name": row.get("business_name"),
            "instagram_business_id": row.get("instagram_business_id"),
            "bot_enabled": row.get("bot_enabled"),
            "has_access_token": bool(row.get("access_token")),
            "access_token_preview": safe_token(row.get("access_token", "")),
            "created_at": row.get("created_at"),
        })

    return {
        "count": len(rows),
        "rows": rows,
    }


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
        token_data = exchange_code_for_token(code)

        access_token = token_data.get("access_token")
        instagram_user_id = normalize_id(token_data.get("user_id"))

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

        profile = get_instagram_profile(access_token, instagram_user_id)

        print("Final profile used:", profile)

        stored = upsert_connected_business(profile, access_token)

        print("Stored business result:", stored)

        return RedirectResponse(
            f"{DASHBOARD_URL}?connected=success&ig_id={profile.get('user_id')}"
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


def is_catalog_request(text: str) -> bool:
    text = (text or "").lower()

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
    if not MISTRAL_API_KEY:
        return (
            "Hozircha avtomatik javob berishda texnik muammo bor. "
            "Iltimos, savolingizni yozib qoldiring, tez orada javob beramiz."
        )

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

    if not res.ok:
        return (
            "Xabaringiz qabul qilindi. "
            "Hozir avtomatik javobda texnik muammo bor, tez orada javob beramiz."
        )

    return res.json()["choices"][0]["message"]["content"]


def send_dm(access_token: str, recipient_id: str, text: str):
    recipient_id = normalize_id(recipient_id)

    if not access_token:
        print("Cannot send DM: missing access token")
        return None

    if not recipient_id:
        print("Cannot send DM: missing recipient_id")
        return None

    if not text:
        print("Cannot send DM: empty text")
        return None

    res = requests.post(
        f"https://graph.instagram.com/{GRAPH_VERSION}/me/messages",
        params={"access_token": access_token},
        json={
            "recipient": {"id": recipient_id},
            "message": {"text": text[:1000]},
        },
        timeout=30,
    )

    print("DM send result:", res.status_code, res.text)
    return res


def reply_to_comment(access_token: str, comment_id: str, text: str):
    comment_id = normalize_id(comment_id)

    if not access_token:
        print("Cannot reply comment: missing access token")
        return None

    if not comment_id:
        print("Cannot reply comment: missing comment_id")
        return None

    res = requests.post(
        f"https://graph.instagram.com/{GRAPH_VERSION}/{comment_id}/replies",
        params={
            "access_token": access_token,
            "message": text[:1000],
        },
        timeout=30,
    )

    print("Comment reply result:", res.status_code, res.text)
    return res


async def process_messaging_event(entry_id: str, messaging: dict):
    print("Raw messaging event:", messaging)

    if "read" in messaging:
        print("Ignored read receipt")
        return

    if "delivery" in messaging:
        print("Ignored delivery receipt")
        return

    message = messaging.get("message") or {}

    if not message:
        print("Ignored event without message object")
        return

    sender_id = normalize_id(messaging.get("sender", {}).get("id"))
    recipient_id = normalize_id(messaging.get("recipient", {}).get("id"))

    message_text = message.get("text")
    message_id = message.get("mid")
    is_echo = bool(message.get("is_echo"))

    print(
        "Messaging IDs:",
        "entry_id=", entry_id,
        "sender_id=", sender_id,
        "recipient_id=", recipient_id,
        "message_id=", message_id,
        "is_echo=", is_echo,
    )

    if is_echo:
        print("Ignored echo message")
        return

    if not sender_id or not recipient_id:
        print("Skipped DM: sender_id or recipient_id missing")
        return

    if sender_id == recipient_id:
        print("Ignored self-message where sender == recipient")
        return

    if not message_text:
        print("Skipped DM: no text message")
        return

    if already_processed(processed_message_ids, message_id):
        print("Ignored duplicate DM:", message_id)
        return

    business = find_business_for_webhook(entry_id, recipient_id)

    if not business:
        print("Skipped DM: no business matched")
        return

    if not business.get("bot_enabled", True):
        print("Bot disabled for business:", business.get("business_name"))
        return

    access_token = business.get("access_token")

    if not access_token:
        print("Missing access token for business:", business.get("business_name"))
        return

    print("Incoming customer DM:", message_text)

    try:
        if is_catalog_request(message_text):
            reply_text = build_catalog_dm(business)
        else:
            reply_text = get_ai_reply(message_text, business)

        print("Reply text:", reply_text)

        send_dm(
            access_token=access_token,
            recipient_id=sender_id,
            text=reply_text,
        )

    except Exception as e:
        print("DM processing error:", str(e))


async def process_comment_event(entry_id: str, change: dict):
    if change.get("field") != "comments":
        return

    value = change.get("value", {})

    comment_id = normalize_id(value.get("id"))
    comment_text = value.get("text")
    from_id = normalize_id(value.get("from", {}).get("id"))

    print(
        "Comment IDs:",
        "entry_id=", entry_id,
        "comment_id=", comment_id,
        "from_id=", from_id,
    )

    if not comment_id or not comment_text:
        print("Skipped comment: missing comment_id or text")
        return

    if from_id and from_id == normalize_id(entry_id):
        print("Ignored own comment")
        return

    if already_processed(processed_comment_ids, comment_id):
        print("Ignored duplicate comment:", comment_id)
        return

    business = find_business_for_webhook(entry_id, "")

    if not business:
        print("Skipped comment: no business matched")
        return

    if not business.get("bot_enabled", True):
        print("Bot disabled for business:", business.get("business_name"))
        return

    access_token = business.get("access_token")

    if not access_token:
        print("Missing access token for business:", business.get("business_name"))
        return

    try:
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

    except Exception as e:
        print("Comment processing error:", str(e))


@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()
        print("Received webhook:", data)

        for entry in data.get("entry", []):
            entry_id = normalize_id(entry.get("id"))

            if not entry_id:
                print("Skipped entry: missing entry.id")
                continue

            print("Processing webhook entry_id:", entry_id)

            for messaging in entry.get("messaging", []):
                await process_messaging_event(entry_id, messaging)

            for change in entry.get("changes", []):
                await process_comment_event(entry_id, change)

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
