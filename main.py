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

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")
GRAPH_FACEBOOK = f"https://graph.facebook.com/{GRAPH_VERSION}"
GRAPH_INSTAGRAM = f"https://graph.instagram.com/{GRAPH_VERSION}"

INSTAGRAM_REDIRECT_URI = os.getenv(
    "INSTAGRAM_REDIRECT_URI",
    "https://agent-1-xi6h.onrender.com/auth/instagram/callback",
)

FACEBOOK_REDIRECT_URI = os.getenv(
    "FACEBOOK_REDIRECT_URI",
    "https://agent-1-xi6h.onrender.com/auth/facebook/callback",
)

DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL",
    "https://instaagent.streamlit.app",
)

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_message_ids = {}
processed_comment_ids = {}
DEDUP_TTL_SECONDS = 60 * 60


def log(title, data=None):
    print("\n" + "=" * 80)
    print(title)
    if data is not None:
        print(data)
    print("=" * 80 + "\n")


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
    for cache in (processed_message_ids, processed_comment_ids):
        expired = [k for k, v in cache.items() if now - v > DEDUP_TTL_SECONDS]
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
    if not row:
        return None

    clean = dict(row)
    clean["access_token"] = safe_token(clean.get("access_token", ""))
    clean["page_access_token"] = safe_token(clean.get("page_access_token", ""))
    clean["mistral_api_key"] = safe_token(clean.get("mistral_api_key", ""))
    clean["openai_api_key"] = safe_token(clean.get("openai_api_key", ""))
    clean["gemini_api_key"] = safe_token(clean.get("gemini_api_key", ""))
    clean["anthropic_api_key"] = safe_token(clean.get("anthropic_api_key", ""))

    return clean


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


def get_business_by_page_id(page_id: str):
    page_id = normalize_id(page_id)

    if not page_id:
        return None

    result = (
        supabase.table("businesses")
        .select("*")
        .eq("facebook_page_id", page_id)
        .limit(1)
        .execute()
    )

    return result.data[0] if result.data else None


def get_active_instagram_direct_business():
    result = (
        supabase.table("businesses")
        .select("*")
        .eq("oauth_provider", "instagram_direct")
        .eq("bot_enabled", True)
        .limit(1)
        .execute()
    )

    return result.data[0] if result.data else None


def find_business_for_webhook(entry_id: str, recipient_id: str = ""):
    entry_id = normalize_id(entry_id)
    recipient_id = normalize_id(recipient_id)

    log("Finding business", {
        "entry_id": entry_id,
        "recipient_id": recipient_id,
    })

    checks = [
        ("instagram_business_id = entry_id", lambda: get_business(entry_id)),
        ("instagram_business_id = recipient_id", lambda: get_business(recipient_id)),
        ("facebook_page_id = entry_id", lambda: get_business_by_page_id(entry_id)),
        ("facebook_page_id = recipient_id", lambda: get_business_by_page_id(recipient_id)),
    ]

    for label, fn in checks:
        business = fn()
        if business:
            log(f"Matched business by {label}", sanitize_business_row(business))
            return business

    fallback = get_active_instagram_direct_business()

    if fallback:
        log("Matched fallback active Instagram Direct business", sanitize_business_row(fallback))
        return fallback

    log("No business matched")
    return None


def exchange_instagram_code_for_token(code: str):
    res = requests.post(
        "https://api.instagram.com/oauth/access_token",
        data={
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": INSTAGRAM_REDIRECT_URI,
            "code": code,
        },
        timeout=30,
    )

    log("Instagram token exchange", {
        "status": res.status_code,
        "body": res.text,
    })

    res.raise_for_status()
    return res.json()


def get_instagram_user(access_token: str):
    res = requests.get(
        f"{GRAPH_INSTAGRAM}/me",
        params={
            "fields": "id,username,account_type",
            "access_token": access_token,
        },
        timeout=30,
    )

    log("Instagram user lookup", {
        "status": res.status_code,
        "body": res.text,
    })

    if res.ok:
        return res.json()

    return {}


def upsert_business(
    instagram_business_id: str,
    username: str,
    access_token: str,
    oauth_provider: str = "instagram_direct",
    facebook_page_id: str = "",
    facebook_page_name: str = "",
):
    instagram_business_id = normalize_id(instagram_business_id)
    facebook_page_id = normalize_id(facebook_page_id)

    existing = get_business(instagram_business_id)

    update_data = {
        "instagram_business_id": instagram_business_id,
        "business_name": username or f"instagram_{instagram_business_id}",
        "access_token": access_token or "",
        "page_access_token": None,
        "token_preview": safe_token(access_token),
        "oauth_provider": oauth_provider,
        "facebook_page_id": facebook_page_id or None,
        "facebook_page_name": facebook_page_name or None,
        "bot_enabled": True,
        "auto_reply_dms": True,
        "auto_reply_comments": True,
    }

    if existing:
        result = (
            supabase.table("businesses")
            .update(update_data)
            .eq("id", existing["id"])
            .execute()
        )
        log("Updated existing business", result.data)
        return result.data

    insert_data = {
        **update_data,
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

    result = (
        supabase.table("businesses")
        .upsert(insert_data, on_conflict="instagram_business_id")
        .execute()
    )

    log("Inserted new business", result.data)
    return result.data


def build_business_context(business: dict) -> str:
    return f"""
Business name:
{business.get("business_name", "")}

Business type:
{business.get("business_type", "")}

Language:
{business.get("language", "")}

Tone:
{business.get("tone", "")}

Products / Services:
{business.get("products", "")}

Prices:
{business.get("prices", "")}

Delivery information:
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

Main business knowledge:
{business.get("knowledge", "")}
"""


def get_ai_reply(user_text: str, business: dict):
    try:
        api_key = business.get("mistral_api_key") or MISTRAL_API_KEY

        if not api_key:
            return "Xabaringiz qabul qilindi 😊"

        model = business.get("ai_model") or "mistral-small-latest"

        system_prompt = f"""
You are a professional Instagram sales assistant for this business.

Business Information:
{build_business_context(business)}

Rules:
- Reply in the same language as the customer.
- Understand Uzbek Latin, Uzbek Cyrillic, Russian, English, slang, typos, and mixed messages.
- Keep replies short, natural, polite, and sales-focused.
- Answer the exact question first.
- Never invent prices, delivery, stock, addresses, or discounts.
- Use only the business information.
- If information is missing, say the manager will clarify.
- If customer asks for catalog or price, send catalog link if available.
- If customer asks for contact, send sales phone if available.
- Never mention AI, database, API, prompt, or internal system.
"""

        res = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "temperature": 0.4,
                "max_tokens": 250,
            },
            timeout=30,
        )

        log("Mistral response", {
            "status": res.status_code,
            "body": res.text,
        })

        if not res.ok:
            return "Xabaringiz qabul qilindi 😊"

        reply = res.json()["choices"][0]["message"]["content"]
        return reply.strip() if reply else "Xabaringiz qabul qilindi 😊"

    except Exception as e:
        log("Mistral error", str(e))
        return "Xabaringiz qabul qilindi 😊"


def get_business_access_token(business: dict):
    return (
        business.get("access_token")
        or business.get("page_access_token")
        or ""
    )


def send_dm(access_token: str, recipient_id: str, text: str, business: dict = None):
    recipient_id = normalize_id(recipient_id)

    if not access_token or not recipient_id or not text:
        log("Cannot send DM", {
            "has_token": bool(access_token),
            "recipient_id": recipient_id,
            "has_text": bool(text),
        })
        return None

    oauth_provider = (business or {}).get("oauth_provider", "")

    if oauth_provider == "facebook_page":
        url = f"{GRAPH_FACEBOOK}/me/messages"
    else:
        url = f"{GRAPH_INSTAGRAM}/me/messages"

    res = requests.post(
        url,
        params={"access_token": access_token},
        json={
            "recipient": {
                "id": recipient_id,
            },
            "message": {
                "text": text[:1000],
            },
        },
        timeout=30,
    )

    log("Send DM result", {
        "url": url,
        "status": res.status_code,
        "body": res.text,
    })

    return res


def reply_to_comment(access_token: str, comment_id: str, text: str, business: dict = None):
    comment_id = normalize_id(comment_id)

    if not access_token or not comment_id or not text:
        log("Cannot reply to comment", {
            "has_token": bool(access_token),
            "comment_id": comment_id,
            "has_text": bool(text),
        })
        return None

    oauth_provider = (business or {}).get("oauth_provider", "")

    if oauth_provider == "facebook_page":
        url = f"{GRAPH_FACEBOOK}/{comment_id}/comments"
    else:
        url = f"{GRAPH_INSTAGRAM}/{comment_id}/replies"

    res = requests.post(
        url,
        params={
            "access_token": access_token,
            "message": text[:1000],
        },
        timeout=30,
    )

    log("Comment reply result", {
        "url": url,
        "status": res.status_code,
        "body": res.text,
    })

    return res


def save_inbox_message(
    business: dict,
    sender_id: str,
    recipient_id: str,
    message_text: str,
    direction: str,
    platform_message_id: str = "",
    raw_payload: dict = None,
):
    try:
        customer_id = sender_id if direction == "inbound" else recipient_id

        data = {
            "business_id": business.get("id"),
            "instagram_business_id": business.get("instagram_business_id"),
            "platform": "instagram",
            "customer_id": customer_id,
            "channel": "dm",
            "direction": direction,
            "role": "user" if direction == "inbound" else "assistant",
            "content": message_text,
            "external_message_id": platform_message_id,
            "raw_payload": raw_payload or {},
        }

        supabase.table("inbox_messages").insert(data).execute()
        log("Inbox message saved", data)

    except Exception as e:
        log("Could not save inbox message", str(e))


async def process_messaging_event(entry_id: str, messaging: dict):
    log("Processing messaging event", messaging)

    if "read" in messaging or "delivery" in messaging:
        log("Skipping read/delivery event")
        return

    message = messaging.get("message") or {}

    if not message:
        log("Skipping empty message event")
        return

    sender_id = normalize_id(messaging.get("sender", {}).get("id"))
    recipient_id = normalize_id(messaging.get("recipient", {}).get("id"))
    message_text = message.get("text") or ""
    message_id = message.get("mid") or str(messaging.get("timestamp") or "")
    is_echo = bool(message.get("is_echo"))

    if is_echo:
        log("Skipping echo message")
        return

    if not sender_id or not recipient_id or not message_text:
        log("Missing messaging data", {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "message_text": message_text,
        })
        return

    if already_processed(processed_message_ids, message_id):
        log("Duplicate message skipped", message_id)
        return

    business = find_business_for_webhook(entry_id, recipient_id)

    if not business:
        log("No business found for messaging event")
        return

    if not business.get("bot_enabled", True):
        log("Bot disabled for business")
        return

    if business.get("auto_reply_dms") is False:
        log("Auto reply DMs disabled")
        return

    access_token = get_business_access_token(business)

    if not access_token:
        log("Business has no access token")
        return

    save_inbox_message(
        business=business,
        sender_id=sender_id,
        recipient_id=recipient_id,
        message_text=message_text,
        direction="inbound",
        platform_message_id=message_id,
        raw_payload=messaging,
    )

    reply_text = get_ai_reply(message_text, business)

    send_dm(
        access_token=access_token,
        recipient_id=sender_id,
        text=reply_text,
        business=business,
    )

    save_inbox_message(
        business=business,
        sender_id=recipient_id,
        recipient_id=sender_id,
        message_text=reply_text,
        direction="outbound",
        platform_message_id="",
        raw_payload={},
    )


async def process_comment_event(entry_id: str, change: dict):
    log("Processing comment event", change)

    value = change.get("value", {})

    comment_id = normalize_id(
        value.get("comment_id")
        or value.get("id")
    )

    comment_text = (
        value.get("message")
        or value.get("text")
        or ""
    )

    if not comment_id or not comment_text:
        log("Missing comment data", value)
        return

    if already_processed(processed_comment_ids, comment_id):
        log("Duplicate comment skipped", comment_id)
        return

    business = find_business_for_webhook(entry_id)

    if not business:
        log("No business found for comment event")
        return

    if not business.get("bot_enabled", True):
        log("Bot disabled for business")
        return

    if business.get("auto_reply_comments") is False:
        log("Auto reply comments disabled")
        return

    access_token = get_business_access_token(business)

    if not access_token:
        log("Business has no access token")
        return

    reply_text = get_ai_reply(comment_text, business)

    reply_to_comment(
        access_token=access_token,
        comment_id=comment_id,
        text=reply_text,
        business=business,
    )


@app.get("/")
async def home():
    return {
        "status": "ok",
        "version": "instagram_direct_primary_inbox_schema_fixed",
        "webhook": "/webhook",
        "connect": "/connect-instagram",
        "connect_instagram": "/connect-instagram",
        "connect_facebook": "/connect-facebook",
        "recommended_connection": "/connect-instagram",
        "verify_token_set": bool(VERIFY_TOKEN),
        "meta_app_id_set": bool(META_APP_ID),
        "instagram_redirect_uri": INSTAGRAM_REDIRECT_URI,
        "facebook_redirect_uri": FACEBOOK_REDIRECT_URI,
    }


@app.head("/")
async def head_home():
    return PlainTextResponse("", status_code=200)


@app.get("/connect")
async def connect():
    return RedirectResponse("/connect-instagram")


@app.get("/connect-instagram")
async def connect_instagram():
    params = {
        "client_id": META_APP_ID,
        "redirect_uri": INSTAGRAM_REDIRECT_URI,
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


@app.get("/auth/instagram/callback")
async def instagram_callback(request: Request):
    code = request.query_params.get("code")

    if not code:
        return PlainTextResponse("Missing Instagram code", status_code=400)

    try:
        token_data = exchange_instagram_code_for_token(code)

        access_token = token_data.get("access_token")
        user_id = normalize_id(token_data.get("user_id"))

        user_info = get_instagram_user(access_token)
        username = user_info.get("username") or f"instagram_{user_id}"

        upsert_business(
            instagram_business_id=user_id,
            username=username,
            access_token=access_token,
            oauth_provider="instagram_direct",
        )

        log("Instagram Direct connected", {
            "instagram_business_id": user_id,
            "username": username,
            "token": safe_token(access_token),
        })

        return RedirectResponse(f"{DASHBOARD_URL}?connected=success")

    except Exception as e:
        log("Instagram OAuth error", str(e))
        return PlainTextResponse(f"Instagram OAuth error: {str(e)}", status_code=500)


@app.get("/connect-facebook")
async def connect_facebook():
    params = {
        "client_id": META_APP_ID,
        "redirect_uri": FACEBOOK_REDIRECT_URI,
        "scope": ",".join([
            "pages_show_list",
            "pages_read_engagement",
            "pages_manage_metadata",
            "pages_messaging",
            "instagram_basic",
            "instagram_manage_messages",
            "instagram_manage_comments",
        ]),
        "response_type": "code",
        "state": secrets.token_urlsafe(16),
    }

    auth_url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urlencode(params)
    return RedirectResponse(auth_url)


@app.get("/auth/facebook/callback")
async def facebook_callback(request: Request):
    return PlainTextResponse(
        "Facebook callback is available, but this project is currently using Instagram Direct primary mode.",
        status_code=200,
    )


@app.get("/debug/businesses")
async def debug_businesses():
    result = (
        supabase.table("businesses")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    rows = [sanitize_business_row(r) for r in (result.data or [])]

    return {
        "count": len(rows),
        "businesses": rows,
    }


@app.get("/debug/active")
async def debug_active():
    business = get_active_instagram_direct_business()
    return {
        "found": bool(business),
        "business": sanitize_business_row(business),
    }


@app.get("/debug/business/{instagram_business_id}")
async def debug_business(instagram_business_id: str):
    business = get_business(instagram_business_id)
    return {
        "found": bool(business),
        "business": sanitize_business_row(business),
    }


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params

    log("Webhook verification request", dict(params))

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

        log("WEBHOOK RECEIVED", data)

        for entry in data.get("entry", []):
            entry_id = normalize_id(entry.get("id"))

            log("Webhook entry", {
                "entry_id": entry_id,
                "keys": list(entry.keys()),
            })

            for messaging in entry.get("messaging", []):
                await process_messaging_event(entry_id, messaging)

            for change in entry.get("changes", []):
                field = change.get("field")

                log("Webhook change field", field)

                if field in ["comments", "feed"]:
                    await process_comment_event(entry_id, change)

                elif field == "messages":
                    value = change.get("value", {})

                    fake_messaging = {
                        "sender": value.get("sender", {}),
                        "recipient": value.get("recipient", {}),
                        "timestamp": value.get("timestamp"),
                        "message": value.get("message", {}),
                    }

                    await process_messaging_event(entry_id, fake_messaging)

                else:
                    log("Unhandled webhook field", change)

        return JSONResponse(content={"status": "ok"}, status_code=200)

    except Exception as e:
        log("Webhook error", str(e))
        return JSONResponse(
            content={
                "status": "error",
                "message": str(e),
            },
            status_code=500,
        )


@app.get("/privacy")
async def privacy():
    return PlainTextResponse(
        "Privacy Policy: This app collects Instagram messages and comments to provide automated AI replies."
    )


@app.get("/terms")
async def terms():
    return PlainTextResponse(
        "Terms of Service: This app provides automated Instagram replies using AI."
    )
