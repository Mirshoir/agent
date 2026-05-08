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

REDIRECT_URI = os.getenv("REDIRECT_URI", "https://agent-1-xi6h.onrender.com/auth/callback")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://instaagent.streamlit.app")

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_comment_ids = {}
processed_message_ids = {}
processing_message_ids = set()
processing_comment_ids = set()
DEDUP_TTL_SECONDS = 60 * 60


def normalize_id(value) -> str:
    return str(value or "").strip()


def safe_json(res):
    try:
        return res.json()
    except Exception:
        return res.text


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


def mark_processed(cache: dict, event_id: str):
    if event_id:
        cleanup_dedup_cache()
        cache[event_id] = time.time()


def is_processed(cache: dict, event_id: str) -> bool:
    if not event_id:
        return False
    cleanup_dedup_cache()
    return event_id in cache


def sanitize_business_row(row: dict):
    if not row:
        return None
    clean = dict(row)
    clean["access_token"] = safe_token(clean.get("access_token", ""))
    clean["page_access_token"] = safe_token(clean.get("page_access_token", ""))
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


def find_business_for_webhook(entry_id: str, recipient_id: str = ""):
    entry_id = normalize_id(entry_id)
    recipient_id = normalize_id(recipient_id)

    print("Finding business:", {"entry_id": entry_id, "recipient_id": recipient_id})

    for lookup_id in [entry_id, recipient_id]:
        business = get_business(lookup_id)
        if business:
            print("Matched by Instagram business ID:", lookup_id)
            return business

    for lookup_id in [entry_id, recipient_id]:
        business = get_business_by_page_id(lookup_id)
        if business:
            print("Matched by Facebook Page ID:", lookup_id)
            return business

    print("No business matched.")
    return None


def upsert_connected_business(data: dict):
    instagram_business_id = normalize_id(data.get("instagram_business_id"))
    if not instagram_business_id:
        raise ValueError("Missing instagram_business_id")

    existing = get_business(instagram_business_id)

    update_data = {
        "instagram_business_id": instagram_business_id,
        "facebook_page_id": normalize_id(data.get("facebook_page_id")),
        "facebook_page_name": data.get("facebook_page_name", ""),
        "business_name": data.get("username") or data.get("facebook_page_name", ""),
        "business_type": "Instagram Business",
        "access_token": data.get("page_access_token"),
        "page_access_token": data.get("page_access_token"),
        "bot_enabled": True,
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

    result = (
        supabase.table("businesses")
        .upsert(insert_data, on_conflict="instagram_business_id")
        .execute()
    )
    return result.data


def exchange_code_for_user_token(code: str) -> str:
    res = requests.get(
        f"{GRAPH_BASE}/oauth/access_token",
        params={
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=30,
    )
    print("User token exchange:", res.status_code, res.text)
    res.raise_for_status()

    token = res.json().get("access_token")
    if not token:
        raise RuntimeError(f"No user access token returned: {res.text}")
    return token


def exchange_for_long_lived_user_token(short_token: str) -> str:
    res = requests.get(
        f"{GRAPH_BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "fb_exchange_token": short_token,
        },
        timeout=30,
    )
    print("Long-lived user token:", res.status_code, res.text)

    if not res.ok:
        return short_token

    return res.json().get("access_token") or short_token


def get_pages(user_access_token: str) -> list:
    res = requests.get(
        f"{GRAPH_BASE}/me/accounts",
        params={
            "fields": "id,name,access_token,tasks,instagram_business_account{id,username,name}",
            "access_token": user_access_token,
        },
        timeout=30,
    )
    print("Pages response:", res.status_code, res.text)
    res.raise_for_status()
    return res.json().get("data", [])


def get_instagram_account_for_page(page_id: str, page_access_token: str):
    res = requests.get(
        f"{GRAPH_BASE}/{page_id}",
        params={
            "fields": "instagram_business_account{id,username,name}",
            "access_token": page_access_token,
        },
        timeout=30,
    )
    print("IG linked account response:", res.status_code, res.text)
    res.raise_for_status()
    return res.json().get("instagram_business_account")


def subscribe_page_to_webhooks(page_id: str, page_access_token: str):
    res = requests.post(
        f"{GRAPH_BASE}/{page_id}/subscribed_apps",
        params={
            "subscribed_fields": "messages,messaging_postbacks,messaging_seen,message_deliveries,feed",
            "access_token": page_access_token,
        },
        timeout=30,
    )
    print("Page subscription:", res.status_code, res.text)
    return {"status": res.status_code, "ok": res.ok, "response": safe_json(res)}


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
        return "Katalog havolasi hozircha mavjud emas. Tezroq ma'lumot olish uchun sales manager bilan bog'lanishingiz mumkin."

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
        return "Xabaringiz qabul qilindi. Hozir avtomatik javobda texnik muammo bor, tez orada javob beramiz."

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

        print("Mistral:", res.status_code, res.text)

        if not res.ok:
            return "Xabaringiz qabul qilindi. Hozir avtomatik javobda texnik muammo bor, tez orada javob beramiz."

        return res.json()["choices"][0]["message"]["content"]

    except Exception as e:
        print("Mistral error:", str(e))
        return "Xabaringiz qabul qilindi. Hozir avtomatik javobda texnik muammo bor, tez orada javob beramiz."


def send_dm(page_access_token: str, recipient_id: str, text: str):
    recipient_id = normalize_id(recipient_id)

    if not page_access_token or not recipient_id or not text:
        print("Cannot send DM: missing token, recipient_id, or text")
        return None

    res = requests.post(
        f"{GRAPH_BASE}/me/messages",
        params={"access_token": page_access_token},
        json={
            "recipient": {"id": recipient_id},
            "message": {"text": text[:1000]},
        },
        timeout=30,
    )

    print("DM send result:", res.status_code, res.text)
    return res


def reply_to_comment(page_access_token: str, comment_id: str, text: str):
    comment_id = normalize_id(comment_id)

    if not page_access_token or not comment_id or not text:
        print("Cannot reply to comment: missing token, comment_id, or text")
        return None

    res = requests.post(
        f"{GRAPH_BASE}/{comment_id}/replies",
        params={
            "access_token": page_access_token,
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
        print("Ignored event without message")
        return

    sender_id = normalize_id(messaging.get("sender", {}).get("id"))
    recipient_id = normalize_id(messaging.get("recipient", {}).get("id"))
    message_text = message.get("text")
    message_id = normalize_id(message.get("mid"))
    is_echo = bool(message.get("is_echo"))

    print("Message IDs:", {
        "entry_id": entry_id,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "message_id": message_id,
        "is_echo": is_echo,
    })

    if is_echo:
        print("Ignored echo")
        return

    if not sender_id or not recipient_id or not message_text:
        print("Skipped DM: missing sender, recipient, or text")
        return

    if is_processed(processed_message_ids, message_id):
        print("Ignored already processed DM:", message_id)
        return

    if message_id in processing_message_ids:
        print("Ignored currently processing DM:", message_id)
        return

    processing_message_ids.add(message_id)

    try:
        business = find_business_for_webhook(entry_id, recipient_id)

        if not business:
            print("Skipped DM: no business found")
            return

        if not business.get("bot_enabled", True):
            print("Bot disabled")
            return

        page_access_token = business.get("page_access_token") or business.get("access_token")

        if not page_access_token:
            print("Missing Page Access Token")
            return

        if is_catalog_request(message_text):
            reply_text = build_catalog_dm(business)
        else:
            reply_text = get_ai_reply(message_text, business)

        print("Reply:", reply_text)

        send_result = send_dm(page_access_token, sender_id, reply_text)

        if send_result is not None and send_result.ok:
            print("DM reply sent successfully. Marking processed:", message_id)
            mark_processed(processed_message_ids, message_id)
        else:
            print("DM reply failed. Not marking processed:", message_id)

    except Exception as e:
        print("DM processing error:", str(e))

    finally:
        processing_message_ids.discard(message_id)


async def process_comment_event(entry_id: str, change: dict):
    value = change.get("value", {})

    comment_id = normalize_id(value.get("comment_id") or value.get("id"))
    comment_text = value.get("message") or value.get("text")
    from_id = normalize_id(value.get("from", {}).get("id") or value.get("sender_id"))

    print("Comment event:", {
        "entry_id": entry_id,
        "comment_id": comment_id,
        "from_id": from_id,
        "text": comment_text,
    })

    if not comment_id or not comment_text:
        print("Skipped comment: missing comment_id or text")
        return

    if is_processed(processed_comment_ids, comment_id):
        print("Ignored already processed comment:", comment_id)
        return

    if comment_id in processing_comment_ids:
        print("Ignored currently processing comment:", comment_id)
        return

    processing_comment_ids.add(comment_id)

    try:
        business = find_business_for_webhook(entry_id, "")

        if not business:
            print("Skipped comment: no business found")
            return

        if not business.get("bot_enabled", True):
            print("Bot disabled")
            return

        page_access_token = business.get("page_access_token") or business.get("access_token")

        if not page_access_token:
            print("Missing Page Access Token")
            return

        success = False

        if is_catalog_request(comment_text):
            if from_id:
                dm_result = send_dm(page_access_token, from_id, build_catalog_dm(business))
                print("Catalog DM result:", dm_result.status_code if dm_result else None)

            comment_result = reply_to_comment(
                page_access_token,
                comment_id,
                "Katalog va narxlar haqida ma'lumotni DM orqali yubordik 😊",
            )
            success = comment_result is not None and comment_result.ok
        else:
            ai_reply = get_ai_reply(comment_text, business)
            comment_result = reply_to_comment(page_access_token, comment_id, ai_reply)
            success = comment_result is not None and comment_result.ok

        if success:
            print("Comment reply sent successfully. Marking processed:", comment_id)
            mark_processed(processed_comment_ids, comment_id)
        else:
            print("Comment reply failed. Not marking processed:", comment_id)

    except Exception as e:
        print("Comment processing error:", str(e))

    finally:
        processing_comment_ids.discard(comment_id)


@app.get("/")
async def home():
    return {
        "status": "ok",
        "version": "fixed_dedup_after_successful_send",
        "connect_instagram": "/connect-instagram",
        "webhook": "/webhook",
    }


@app.get("/connect-instagram")
async def connect_instagram():
    if not META_APP_ID:
        return PlainTextResponse("Missing META_APP_ID", status_code=500)

    params = {
        "client_id": META_APP_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": ",".join([
            "pages_show_list",
            "pages_manage_metadata",
            "pages_read_engagement",
            "pages_messaging",
            "instagram_basic",
            "instagram_manage_messages",
        ]),
        "response_type": "code",
        "state": secrets.token_urlsafe(16),
    }

    auth_url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urlencode(params)
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    error_description = request.query_params.get("error_description")

    if error:
        return PlainTextResponse(f"Facebook connection failed: {error} - {error_description}", status_code=400)

    if not code:
        return PlainTextResponse("Missing authorization code", status_code=400)

    if not META_APP_ID or not META_APP_SECRET:
        return PlainTextResponse("Missing META_APP_ID or META_APP_SECRET", status_code=500)

    try:
        short_user_token = exchange_code_for_user_token(code)
        user_token = exchange_for_long_lived_user_token(short_user_token)
        pages = get_pages(user_token)

        if not pages:
            return PlainTextResponse(
                "No Facebook Pages found. Connect your Instagram Business account to a Facebook Page first.",
                status_code=400,
            )

        connected_accounts = []

        for page in pages:
            page_id = normalize_id(page.get("id"))
            page_name = page.get("name", "")
            page_access_token = page.get("access_token")

            if not page_id or not page_access_token:
                continue

            ig_account = page.get("instagram_business_account") or get_instagram_account_for_page(page_id, page_access_token)

            if not ig_account:
                print(f"No Instagram account linked to page {page_name}")
                continue

            instagram_business_id = normalize_id(ig_account.get("id"))
            username = ig_account.get("username") or ig_account.get("name") or page_name

            if not instagram_business_id:
                continue

            stored = upsert_connected_business({
                "instagram_business_id": instagram_business_id,
                "username": username,
                "facebook_page_id": page_id,
                "facebook_page_name": page_name,
                "page_access_token": page_access_token,
            })

            sub_result = subscribe_page_to_webhooks(page_id, page_access_token)

            connected_accounts.append({
                "instagram_business_id": instagram_business_id,
                "username": username,
                "facebook_page_id": page_id,
                "facebook_page_name": page_name,
                "stored": bool(stored),
                "subscription": sub_result,
            })

        if not connected_accounts:
            return PlainTextResponse(
                "No linked Instagram Business accounts found. Make sure the Facebook Page is connected to an Instagram Business/Creator account.",
                status_code=400,
            )

        first_ig_id = connected_accounts[0]["instagram_business_id"]
        return RedirectResponse(f"{DASHBOARD_URL}?connected=success&ig_id={first_ig_id}")

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
        print("Webhook object:", data.get("object"))

        for entry in data.get("entry", []):
            entry_id = normalize_id(entry.get("id"))

            if not entry_id:
                print("Skipped entry without ID")
                continue

            print("Processing entry:", entry_id)

            for messaging in entry.get("messaging", []):
                await process_messaging_event(entry_id, messaging)

            for change in entry.get("changes", []):
                field = change.get("field")
                print("Processing change field:", field)

                if field in ["feed", "comments"]:
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
                    print("Ignored unsupported field:", field)

        return JSONResponse({"status": "ok"}, status_code=200)

    except Exception as e:
        print("Webhook error:", str(e))
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/debug/business-ids")
async def debug_business_ids():
    result = (
        supabase.table("businesses")
        .select("id,business_name,instagram_business_id,facebook_page_id,facebook_page_name,bot_enabled,access_token,page_access_token,catalog_link,created_at")
        .order("created_at", desc=True)
        .execute()
    )

    rows = []
    for row in result.data or []:
        rows.append({
            "id": row.get("id"),
            "business_name": row.get("business_name"),
            "instagram_business_id": row.get("instagram_business_id"),
            "facebook_page_id": row.get("facebook_page_id"),
            "facebook_page_name": row.get("facebook_page_name"),
            "bot_enabled": row.get("bot_enabled"),
            "has_access_token": bool(row.get("access_token")),
            "has_page_access_token": bool(row.get("page_access_token")),
            "access_token_preview": safe_token(row.get("access_token", "")),
            "page_access_token_preview": safe_token(row.get("page_access_token", "")),
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
    return {
        "count": len(result.data or []),
        "businesses": [sanitize_business_row(row) for row in result.data or []],
    }


@app.get("/debug/find-business")
async def debug_find_business(entry_id: str = "", recipient_id: str = ""):
    business = find_business_for_webhook(entry_id, recipient_id)

    return {
        "entry_id": entry_id,
        "recipient_id": recipient_id,
        "matched": bool(business),
        "business": sanitize_business_row(business) if business else None,
    }


@app.get("/debug/resubscribe")
async def debug_resubscribe(instagram_business_id: str = ""):
    if not instagram_business_id:
        return JSONResponse({"error": "instagram_business_id is required"}, status_code=400)

    business = get_business(instagram_business_id)

    if not business:
        return JSONResponse({"error": "Business not found"}, status_code=404)

    page_id = business.get("facebook_page_id")
    page_access_token = business.get("page_access_token") or business.get("access_token")

    if not page_id:
        return JSONResponse({"error": "Missing facebook_page_id"}, status_code=400)

    if not page_access_token:
        return JSONResponse({"error": "Missing page_access_token"}, status_code=400)

    result = subscribe_page_to_webhooks(page_id, page_access_token)

    return {
        "instagram_business_id": instagram_business_id,
        "facebook_page_id": page_id,
        "subscription_result": result,
    }


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
