import os
import time
import secrets
import requests
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse
from supabase import create_client


app = FastAPI()

# ─────────────────────────────────────────────
# Environment variables
# ─────────────────────────────────────────────
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")

REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://agent-1-xi6h.onrender.com/auth/callback",
)

DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL",
    "https://instaagent.streamlit.app",
)

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ─────────────────────────────────────────────
# In-memory dedup caches
# ─────────────────────────────────────────────
processed_comment_ids: dict = {}
processed_message_ids: dict = {}
DEDUP_TTL_SECONDS = 60 * 60  # 1 hour


# ─────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────

def normalize_id(value) -> str:
    return str(value or "").strip()


def safe_token(token: str) -> str:
    if not token:
        return ""
    token = str(token)
    if len(token) <= 18:
        return token[:4] + "..."
    return token[:10] + "..." + token[-6:]


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


def sanitize_business_row(row: dict):
    clean = dict(row)
    clean["access_token"] = safe_token(clean.get("access_token", ""))
    return clean


# ─────────────────────────────────────────────
# Supabase helpers
# ─────────────────────────────────────────────

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
    return result.data[0] if result.data else None


def find_business_for_webhook(entry_id: str, recipient_id: str = ""):
    entry_id = normalize_id(entry_id)
    recipient_id = normalize_id(recipient_id)

    print("Finding business for:", {"entry_id": entry_id, "recipient_id": recipient_id})

    business = get_business(entry_id)
    if business:
        print("Business matched by entry_id:", entry_id)
        return business

    business = get_business(recipient_id)
    if business:
        print("Business matched by recipient_id:", recipient_id)
        return business

    print("No business matched for webhook.")
    return None


# ─────────────────────────────────────────────
# OAuth — Instagram Business Login
#
# ARCHITECTURE DECISION:
# We use Instagram's own OAuth (instagram.com/oauth/authorize) with the
# instagram_business_* permissions. This gives us an Instagram User token
# that works on graph.instagram.com for sending DMs and replying to comments.
#
# The webhook subscription step uses the same Instagram token on
# graph.instagram.com/me/subscribed_apps — which is the correct endpoint
# for Instagram Business Login tokens (NOT graph.facebook.com).
#
# Clients do NOT need a Facebook account. They only need:
#   - An Instagram Business or Creator account
#   - Nothing else
# ─────────────────────────────────────────────

def exchange_code_for_token(code: str) -> dict:
    """
    Exchange the Instagram OAuth code for a short-lived Instagram User token.
    Returns dict with access_token and user_id.
    """
    res = requests.post(
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
    print("Instagram OAuth token status:", res.status_code)
    print("Instagram OAuth token response:", res.text)
    res.raise_for_status()
    return res.json()


def exchange_for_long_lived_token(short_lived_token: str) -> str:
    """
    Exchange a short-lived Instagram token (~1 hour) for a long-lived one (~60 days).
    Uses graph.instagram.com with ig_exchange_token grant.
    This is the correct endpoint for Instagram Business Login tokens.
    Falls back to short-lived token on error.
    """
    try:
        res = requests.get(
            f"https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": META_APP_SECRET,
                "access_token": short_lived_token,
            },
            timeout=30,
        )
        print("Long-lived token status:", res.status_code)
        print("Long-lived token response:", res.text)

        if res.ok:
            long_token = res.json().get("access_token")
            if long_token:
                print("Successfully obtained long-lived Instagram token.")
                return long_token

        print("Long-lived token exchange failed; using short-lived token as fallback.")
    except Exception as e:
        print("Long-lived token exchange error:", str(e))

    return short_lived_token


def get_instagram_profile(access_token: str, fallback_user_id: str = "") -> dict:
    """
    Fetch the Instagram Business profile for the authenticated user.
    Uses graph.instagram.com/me — correct for Instagram Business Login tokens.
    """
    try:
        res = requests.get(
            "https://graph.instagram.com/me",
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
            app_scoped_id = normalize_id(data.get("id"))
            real_user_id = normalize_id(data.get("user_id") or fallback_user_id)
            username = data.get("username") or f"instagram_{real_user_id}"
            return {
                "app_scoped_id": app_scoped_id,
                "id": real_user_id,
                "user_id": real_user_id,
                "username": username,
                "account_type": data.get("account_type", ""),
            }

    except Exception as e:
        print("Profile fetch failed:", str(e))

    fallback_user_id = normalize_id(fallback_user_id)
    return {
        "app_scoped_id": "",
        "id": fallback_user_id,
        "user_id": fallback_user_id,
        "username": f"instagram_{fallback_user_id}",
        "account_type": "",
    }


def subscribe_to_instagram_webhooks(access_token: str, instagram_user_id: str) -> dict:
    """
    Subscribe this Instagram account to receive webhook events (messages, comments).

    Uses graph.instagram.com/{user_id}/subscribed_apps with the Instagram User token.
    This is the correct endpoint for Instagram Business Login — NOT graph.facebook.com.

    Calling /me/subscribed_apps sometimes fails; using the explicit user_id endpoint
    is more reliable.

    This call tells Meta: "send webhook events for this Instagram account to the
    app whose token this is."
    """
    # Try with explicit user_id first (more reliable)
    if instagram_user_id:
        try:
            res = requests.post(
                f"https://graph.instagram.com/{GRAPH_VERSION}/{instagram_user_id}/subscribed_apps",
                params={
                    "access_token": access_token,
                    "subscribed_fields": "messages,comments",
                },
                timeout=30,
            )
            print("Subscription (by user_id) status:", res.status_code)
            print("Subscription (by user_id) response:", res.text)

            if res.ok:
                return res.json()

            print("user_id subscription attempt failed, trying /me/subscribed_apps...")

        except Exception as e:
            print("user_id subscription error:", str(e))

    # Fallback: try /me/subscribed_apps
    try:
        res = requests.post(
            f"https://graph.instagram.com/{GRAPH_VERSION}/me/subscribed_apps",
            params={
                "access_token": access_token,
                "subscribed_fields": "messages,comments",
            },
            timeout=30,
        )
        print("Subscription (/me) status:", res.status_code)
        print("Subscription (/me) response:", res.text)
        return res.json()

    except Exception as e:
        print("Subscription (/me) error:", str(e))
        return {"error": str(e)}


def upsert_connected_business(profile: dict, access_token: str):
    instagram_business_id = normalize_id(profile.get("user_id"))
    username = profile.get("username") or f"instagram_{instagram_business_id}"

    if not instagram_business_id:
        raise ValueError("Instagram profile did not return user_id")

    print("Saving business:", {
        "instagram_business_id": instagram_business_id,
        "username": username,
    })

    existing = get_business(instagram_business_id)

    update_data = {
        "instagram_business_id": instagram_business_id,
        "access_token": access_token,
        "bot_enabled": True,
        "business_name": username,
        "business_type": "Instagram Business",
    }

    if existing:
        print("Updating existing business:", existing.get("id"))
        result = (
            supabase.table("businesses")
            .update(update_data)
            .eq("id", existing["id"])
            .execute()
        )
        return result.data

    print("Creating new business:", instagram_business_id)
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
    result = (
        supabase.table("businesses")
        .upsert(insert_data, on_conflict="instagram_business_id")
        .execute()
    )
    return result.data


# ─────────────────────────────────────────────
# Business logic helpers
# ─────────────────────────────────────────────

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
            "Tezroq ma'lumot olish uchun sales manager bilan bog'lanishingiz mumkin."
        )
    return (
        f"Katalogni shu havola orqali ko'rishingiz mumkin:\n{catalog_link}\n\n"
        "Qo'shimcha ma'lumot kerak bo'lsa, yozib qoldiring 😊"
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
            "Xabaringiz qabul qilindi. "
            "Hozir avtomatik javobda texnik muammo bor, tez orada javob beramiz."
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

    try:
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

    except Exception as e:
        print("Mistral error:", str(e))
        return (
            "Xabaringiz qabul qilindi. "
            "Hozir avtomatik javobda texnik muammo bor, tez orada javob beramiz."
        )


# ─────────────────────────────────────────────
# Instagram Graph API senders
# ─────────────────────────────────────────────

def send_dm(access_token: str, recipient_id: str, text: str):
    recipient_id = normalize_id(recipient_id)
    if not access_token or not recipient_id or not text:
        print("Cannot send DM: missing token, recipient_id, or text")
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
    if not access_token or not comment_id or not text:
        print("Cannot reply comment: missing token, comment_id, or text")
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


# ─────────────────────────────────────────────
# Webhook event processors
# ─────────────────────────────────────────────

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

    if not sender_id or not recipient_id or not message_text:
        print("Skipped DM: missing sender, recipient, or text")
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

    try:
        if is_catalog_request(message_text):
            reply_text = build_catalog_dm(business)
        else:
            reply_text = get_ai_reply(message_text, business)

        print("Reply text:", reply_text)
        send_dm(access_token=access_token, recipient_id=sender_id, text=reply_text)

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
                "Katalog va narxlar haqida ma'lumotni DM orqali yubordik 😊",
            )
        else:
            ai_reply = get_ai_reply(comment_text, business)
            reply_to_comment(access_token, comment_id, ai_reply)

    except Exception as e:
        print("Comment processing error:", str(e))


async def process_message_change_event(entry_id: str, change: dict):
    if change.get("field") != "messages":
        return

    value = change.get("value", {})
    fake_messaging = {
        "sender": value.get("sender", {}),
        "recipient": value.get("recipient", {}),
        "timestamp": value.get("timestamp"),
        "message": value.get("message", {}),
    }
    print("Converted changes.messages payload to messaging event:", fake_messaging)
    await process_messaging_event(entry_id, fake_messaging)


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.get("/")
async def home():
    return {
        "status": "ok",
        "version": "instagram_business_login_with_subscription",
        "note": "Clients only need an Instagram Business/Creator account — no Facebook required",
        "endpoints": {
            "connect_instagram": "/connect-instagram",
            "debug_business_ids": "/debug/business-ids",
            "debug_businesses": "/debug/businesses",
            "debug_find_business": "/debug/find-business?entry_id=&recipient_id=",
            "debug_check_subscription": "/debug/check-subscription?instagram_business_id=",
            "debug_resubscribe": "/debug/resubscribe?instagram_business_id=",
        },
    }


@app.get("/debug/business-ids")
async def debug_business_ids():
    result = (
        supabase.table("businesses")
        .select(
            "id,business_name,instagram_business_id,bot_enabled,access_token,catalog_link,created_at"
        )
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
            "catalog_link": row.get("catalog_link"),
            "created_at": row.get("created_at"),
        })
    return {"count": len(rows), "rows": rows}


@app.get("/debug/businesses")
async def debug_businesses():
    result = (
        supabase.table("businesses")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    rows = [sanitize_business_row(row) for row in (result.data or [])]
    return {"count": len(rows), "businesses": rows}


@app.get("/debug/find-business")
async def debug_find_business(entry_id: str = "", recipient_id: str = ""):
    business = find_business_for_webhook(entry_id, recipient_id)
    return {
        "entry_id": entry_id,
        "recipient_id": recipient_id,
        "matched": bool(business),
        "business": sanitize_business_row(business) if business else None,
    }


@app.get("/debug/check-subscription")
async def debug_check_subscription(instagram_business_id: str = ""):
    """
    Check the current webhook subscription status for an Instagram account.
    """
    if not instagram_business_id:
        return JSONResponse({"error": "instagram_business_id is required"}, status_code=400)

    business = get_business(instagram_business_id)
    if not business:
        return JSONResponse({"error": "Business not found in Supabase"}, status_code=404)

    access_token = business.get("access_token")
    if not access_token:
        return JSONResponse({"error": "No access token stored"}, status_code=400)

    results = {}

    # Check via explicit user_id endpoint
    try:
        res = requests.get(
            f"https://graph.instagram.com/{GRAPH_VERSION}/{instagram_business_id}/subscribed_apps",
            params={"access_token": access_token},
            timeout=30,
        )
        results["by_user_id"] = {
            "status": res.status_code,
            "data": res.json(),
        }
    except Exception as e:
        results["by_user_id"] = {"error": str(e)}

    # Check via /me endpoint
    try:
        res = requests.get(
            f"https://graph.instagram.com/{GRAPH_VERSION}/me/subscribed_apps",
            params={"access_token": access_token},
            timeout=30,
        )
        results["by_me"] = {
            "status": res.status_code,
            "data": res.json(),
        }
    except Exception as e:
        results["by_me"] = {"error": str(e)}

    return {
        "instagram_business_id": instagram_business_id,
        "business_name": business.get("business_name"),
        "subscription_checks": results,
    }


@app.get("/debug/resubscribe")
async def debug_resubscribe(instagram_business_id: str = ""):
    """
    Manually re-trigger the Instagram webhook subscription for an existing account.
    Useful for fixing accounts connected before the subscription step was added.
    """
    if not instagram_business_id:
        return JSONResponse({"error": "instagram_business_id is required"}, status_code=400)

    business = get_business(instagram_business_id)
    if not business:
        return JSONResponse({"error": "Business not found in Supabase"}, status_code=404)

    access_token = business.get("access_token")
    if not access_token:
        return JSONResponse({"error": "No access token stored"}, status_code=400)

    sub_result = subscribe_to_instagram_webhooks(access_token, instagram_business_id)
    return {
        "instagram_business_id": instagram_business_id,
        "business_name": business.get("business_name"),
        "subscription_result": sub_result,
    }


@app.get("/connect-instagram")
async def connect_instagram():
    """
    Redirect clients to Instagram Business Login OAuth.

    Clients only need an Instagram Business or Creator account.
    No Facebook account required.

    Permissions requested:
      instagram_business_basic          — read profile and media
      instagram_business_manage_messages — send and receive DMs
      instagram_business_manage_comments — reply to comments
    """
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
        return PlainTextResponse("Missing authorization code from Instagram", status_code=400)

    if not META_APP_ID or not META_APP_SECRET:
        return PlainTextResponse("Missing META_APP_ID or META_APP_SECRET", status_code=500)

    try:
        # Step 1: Exchange code for short-lived Instagram token
        token_data = exchange_code_for_token(code)
        short_lived_token = token_data.get("access_token")
        token_user_id = normalize_id(token_data.get("user_id"))

        if not short_lived_token:
            return PlainTextResponse(
                f"No access token returned: {token_data}",
                status_code=500,
            )

        if not token_user_id:
            return PlainTextResponse(
                f"No user_id returned: {token_data}",
                status_code=500,
            )

        print("Short-lived token:", safe_token(short_lived_token))
        print("Token user_id:", token_user_id)

        # Step 2: Exchange for long-lived Instagram token (~60 days)
        access_token = exchange_for_long_lived_token(short_lived_token)
        print("Access token in use:", safe_token(access_token))

        # Step 3: Fetch Instagram profile
        profile = get_instagram_profile(access_token, token_user_id)
        print("Profile:", profile)

        instagram_user_id = normalize_id(profile.get("user_id") or token_user_id)

        # Step 4: Save to Supabase
        stored = upsert_connected_business(profile, access_token)
        print("Stored:", stored)

        # Step 5: Subscribe this Instagram account to receive webhook events
        # This is the critical step that activates DM delivery to our server.
        # Without this, Meta will not send any messaging events for this account.
        sub_result = subscribe_to_instagram_webhooks(access_token, instagram_user_id)
        print("Webhook subscription result:", sub_result)

        return RedirectResponse(
            f"{DASHBOARD_URL}?connected=success&ig_id={instagram_user_id}"
        )

    except requests.HTTPError as e:
        response_text = e.response.text if e.response else str(e)
        print("OAuth HTTP error:", response_text)
        return PlainTextResponse(f"OAuth HTTP error: {response_text}", status_code=400)

    except Exception as e:
        print("OAuth callback error:", str(e))
        return PlainTextResponse(f"OAuth error: {str(e)}", status_code=500)


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
            entry_id = normalize_id(entry.get("id"))

            if not entry_id:
                print("Skipped entry: missing entry.id")
                continue

            print("Processing webhook entry_id:", entry_id)

            for messaging in entry.get("messaging", []):
                await process_messaging_event(entry_id, messaging)

            for change in entry.get("changes", []):
                field = change.get("field")

                if field == "comments":
                    await process_comment_event(entry_id, change)
                elif field == "messages":
                    await process_message_change_event(entry_id, change)
                else:
                    print("Ignored unsupported change field:", field)

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
        "Privacy Policy: This app collects Instagram messages and comments to provide "
        "automated AI replies. No personal data is sold or shared with third parties."
    )


@app.get("/terms")
async def terms():
    return PlainTextResponse(
        "Terms of Service: This app provides automated Instagram replies using AI. "
        "Responses may not always be accurate. This service is provided as is."
    )
