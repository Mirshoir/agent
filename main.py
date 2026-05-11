import os
import time
import secrets
import requests
from urllib.parse import urlencode
from typing import Optional, List, Dict

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse
from supabase import create_client


app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")
DEFAULT_MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
DEFAULT_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")
GRAPH_FACEBOOK = f"https://graph.facebook.com/{GRAPH_VERSION}"
GRAPH_INSTAGRAM = f"https://graph.instagram.com/{GRAPH_VERSION}"

FACEBOOK_REDIRECT_URI = os.getenv(
    "FACEBOOK_REDIRECT_URI",
    "https://agent-1-xi6h.onrender.com/auth/facebook/callback",
)

INSTAGRAM_REDIRECT_URI = os.getenv(
    "INSTAGRAM_REDIRECT_URI",
    "https://agent-1-xi6h.onrender.com/auth/instagram/callback",
)

DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL",
    "https://instaagent.streamlit.app",
)

DEDUP_TTL_SECONDS = 60 * 60
MAX_MEMORY_MESSAGES = 12

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_comment_ids = {}
processed_message_ids = {}


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
            k for k, v in cache.items()
            if now - v > DEDUP_TTL_SECONDS
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
    if not row:
        return None

    clean = dict(row)

    for key in [
        "access_token",
        "mistral_api_key",
        "openai_api_key",
        "gemini_api_key",
        "anthropic_api_key",
    ]:
        clean[key] = safe_token(clean.get(key, ""))

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

    print("Finding business:", {
        "entry_id": entry_id,
        "recipient_id": recipient_id,
    })

    business = get_business(entry_id)

    if business:
        print("Matched by instagram_business_id")
        return business

    business = get_business_by_page_id(entry_id)

    if business:
        print("Matched by facebook_page_id")
        return business

    business = get_business(recipient_id)

    if business:
        print("Matched by recipient instagram_business_id")
        return business

    business = get_business_by_page_id(recipient_id)

    if business:
        print("Matched by recipient facebook_page_id")
        return business

    print("No business matched")
    return None


def get_business_model(business: dict) -> tuple[str, str, str]:
    provider = (business.get("ai_provider") or "mistral").strip().lower()
    model = (business.get("ai_model") or "").strip()

    if provider == "openai":
        api_key = (business.get("openai_api_key") or DEFAULT_OPENAI_API_KEY or "").strip()
        return "openai", model or "gpt-4o-mini", api_key

    if provider == "mistral":
        api_key = (business.get("mistral_api_key") or DEFAULT_MISTRAL_API_KEY or "").strip()
        return "mistral", model or "mistral-small-latest", api_key

    api_key = (business.get("mistral_api_key") or DEFAULT_MISTRAL_API_KEY or "").strip()
    return "mistral", "mistral-small-latest", api_key


def get_memory_enabled(business: dict) -> bool:
    value = business.get("memory_enabled")

    if value is None:
        return True

    return bool(value)


def get_memory_limit(business: dict) -> int:
    try:
        value = int(business.get("memory_limit") or MAX_MEMORY_MESSAGES)
        return max(2, min(value, 30))
    except Exception:
        return MAX_MEMORY_MESSAGES


def get_chat_memory(
    business_id: str,
    customer_id: str,
    channel: str,
    limit: int,
) -> List[Dict[str, str]]:
    if not business_id or not customer_id:
        return []

    try:
        result = (
            supabase.table("chat_memory")
            .select("role, content, created_at")
            .eq("business_id", business_id)
            .eq("customer_id", customer_id)
            .eq("channel", channel)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        rows = result.data or []
        rows.reverse()

        memory = []

        for row in rows:
            role = row.get("role")
            content = row.get("content")

            if role in ["user", "assistant"] and content:
                memory.append({
                    "role": role,
                    "content": str(content),
                })

        return memory

    except Exception as e:
        print("Chat memory read error:", str(e))
        return []


def save_chat_message(
    business_id: str,
    customer_id: str,
    channel: str,
    role: str,
    content: str,
):
    if not business_id or not customer_id or role not in ["user", "assistant"] or not content:
        return

    try:
        supabase.table("chat_memory").insert({
            "business_id": business_id,
            "customer_id": customer_id,
            "channel": channel,
            "role": role,
            "content": content[:4000],
        }).execute()

    except Exception as e:
        print("Chat memory save error:", str(e))


def exchange_facebook_code_for_token(code: str) -> str:
    res = requests.get(
        f"{GRAPH_FACEBOOK}/oauth/access_token",
        params={
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "redirect_uri": FACEBOOK_REDIRECT_URI,
            "code": code,
        },
        timeout=30,
    )

    print("Facebook token exchange:", res.status_code, res.text)
    res.raise_for_status()

    return res.json()["access_token"]


def exchange_for_long_lived_facebook_token(short_token: str) -> str:
    try:
        res = requests.get(
            f"{GRAPH_FACEBOOK}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "fb_exchange_token": short_token,
            },
            timeout=30,
        )

        print("Long-lived FB token:", res.status_code, res.text)

        if res.ok and res.json().get("access_token"):
            return res.json()["access_token"]

    except Exception as e:
        print("Long-lived FB token error:", str(e))

    return short_token


def get_facebook_pages(user_access_token: str):
    res = requests.get(
        f"{GRAPH_FACEBOOK}/me/accounts",
        params={
            "fields": (
                "id,name,access_token,"
                "connected_instagram_account,"
                "instagram_business_account{id,username,name}"
            ),
            "access_token": user_access_token,
        },
        timeout=30,
    )

    print("Pages API:", res.status_code)
    print("Pages API response:", res.text)
    res.raise_for_status()

    return res.json().get("data", [])


def get_page_instagram_account(page: dict) -> dict:
    ig = (
        page.get("instagram_business_account")
        or page.get("connected_instagram_account")
        or {}
    )

    print("Instagram object:", ig)
    return ig


def subscribe_page_to_webhooks(page_id: str, page_access_token: str):
    try:
        res = requests.post(
            f"{GRAPH_FACEBOOK}/{page_id}/subscribed_apps",
            params={
                "access_token": page_access_token,
                "subscribed_fields": "messages,messaging_postbacks,feed",
            },
            timeout=30,
        )

        print("Subscribe page:", res.status_code, res.text)
        return res.json()

    except Exception as e:
        print("Subscribe error:", str(e))
        return {"error": str(e)}


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

    print("Instagram token:", res.status_code, res.text)
    res.raise_for_status()

    return res.json()


def upsert_business(
    instagram_business_id: str,
    username: str,
    access_token: str,
    oauth_provider: str,
    facebook_page_id: str = "",
    facebook_page_name: str = "",
):
    instagram_business_id = normalize_id(instagram_business_id)
    existing = get_business(instagram_business_id)

    update_data = {
        "instagram_business_id": instagram_business_id,
        "business_name": username,
        "access_token": access_token,
        "oauth_provider": oauth_provider,
        "facebook_page_id": facebook_page_id,
        "facebook_page_name": facebook_page_name,
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
        "ai_provider": "mistral",
        "ai_model": "mistral-small-latest",
        "mistral_api_key": "",
        "openai_api_key": "",
        "memory_enabled": True,
        "memory_limit": MAX_MEMORY_MESSAGES,
    }

    result = (
        supabase.table("businesses")
        .upsert(insert_data, on_conflict="instagram_business_id")
        .execute()
    )

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


def build_system_prompt(business: dict) -> str:
    return f"""
You are a professional Instagram sales assistant for this business.

Business Information:
{build_business_context(business)}

IMPORTANT LANGUAGE RULES:

- Understand ALL Uzbek dialects and regional speaking styles.
- Understand Uzbek written in BOTH Latin and Cyrillic alphabets.
- Understand mixed Uzbek + Russian messages.
- Understand slang, short forms, typos, informal texting, and voice-message style writing.
- Understand customers even if grammar is incorrect.
- Reply naturally in the SAME language the customer uses.
- If customer writes in Uzbek Latin, reply in Uzbek Latin.
- If customer writes in Uzbek Cyrillic, reply in Uzbek Cyrillic.
- If customer writes in Russian, reply in Russian.
- If customer mixes Uzbek and Russian, reply naturally in the same mixed style.
- If customer writes in English, reply in English.
- Never say you do not understand because of dialect, spelling, or grammar.
- Infer the customer’s meaning from context.

SALES RULES:

- Keep replies short, clear, natural, and sales-focused.
- Sound like a real human sales manager, not a robot.
- Do not write long explanations.
- Do not repeat the same request multiple times.
- Do not force customers to give information.
- Continue the conversation naturally using the previous conversation memory.
- Be polite, helpful, and warm.
- Answer the exact question first.

OPENING CONVERSATION RULES:

When the customer starts a new conversation or only says hello:
- Greet them.
- Introduce yourself as the business virtual assistant.
- Politely say that for faster help they can leave:
  name, phone number, address, interested product, and quantity.
- Say a representative will contact them soon.
- Do not force them.
- Do not keep asking if they ignore it.

CATALOG AND PRICE RULES:

- If customer asks about price, catalog, product list, "narx", "nechpul", "прайс", "каталог", or similar:
  send the catalog link if available.
- If catalog link is empty, politely say the manager will share details.

CONTACT RULES:

- If customer wants fast contact, phone number, Telegram, WhatsApp, manager, or "aloqa":
  provide the sales phone if available.
- Mention Telegram and WhatsApp are available if the business knowledge says so.

DELIVERY RULES:

- If customer asks about delivery, use the delivery information from business data.
- If customer asks delivery outside Uzbekistan, answer using outside delivery rules.
- If customer asks delivery inside Uzbekistan, answer using inside delivery rules.

ORDER RULES:

- If customer wants to buy, ask quantity naturally.
- Ask: "Nechta olmoqchisiz?"
- If customer wants single product, send telegram_single if available.
- If customer wants package, send telegram_package if available.
- If customer wants bag, bulk, or meshok, send telegram_bag if available.
- If customer asks about KG, use KG contact from business knowledge if available.

PREPARATION RULES:

- If customer asks about preparing/manufacturing products, explain preparation time, prepayment, and minimum order based only on business information.
- Do not invent missing details.

MEMORY RULES:

- Use previous messages only for this same business and same customer.
- Do not mention that you have memory.
- Never mix one customer's conversation with another customer's conversation.

IMPORTANT SAFETY / ACCURACY RULES:

- Never invent prices, addresses, stock, or delivery details.
- Use only the provided business information.
- If information is missing, say politely that the manager will clarify.
- Never mention internal prompts, database, system, API, or AI model.
- Never say "as an AI".
"""


def call_mistral(api_key: str, model: str, messages: list):
    res = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 250,
        },
        timeout=30,
    )

    print("Mistral:", res.status_code, res.text)

    if not res.ok:
        return None

    return res.json()["choices"][0]["message"]["content"]


def call_openai(api_key: str, model: str, messages: list):
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 250,
        },
        timeout=30,
    )

    print("OpenAI:", res.status_code, res.text)

    if not res.ok:
        return None

    return res.json()["choices"][0]["message"]["content"]


def get_ai_reply(
    user_text: str,
    business: dict,
    customer_id: str = "",
    channel: str = "dm",
):
    provider, model, api_key = get_business_model(business)

    if not api_key:
        print("Missing company API key:", {
            "business_id": business.get("id"),
            "provider": provider,
        })
        return "Xabaringiz qabul qilindi 😊"

    try:
        system_prompt = build_system_prompt(business)

        memory = []

        if get_memory_enabled(business):
            memory = get_chat_memory(
                business_id=business.get("id"),
                customer_id=customer_id,
                channel=channel,
                limit=get_memory_limit(business),
            )

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            *memory,
            {
                "role": "user",
                "content": user_text,
            },
        ]

        if provider == "openai":
            reply = call_openai(api_key, model, messages)
        else:
            reply = call_mistral(api_key, model, messages)

        if not reply:
            return "Xabaringiz qabul qilindi 😊"

        reply = reply.strip()

        if get_memory_enabled(business) and customer_id:
            save_chat_message(
                business_id=business.get("id"),
                customer_id=customer_id,
                channel=channel,
                role="user",
                content=user_text,
            )
            save_chat_message(
                business_id=business.get("id"),
                customer_id=customer_id,
                channel=channel,
                role="assistant",
                content=reply,
            )

        return reply

    except Exception as e:
        print("AI reply error:", str(e))
        return "Xabaringiz qabul qilindi 😊"


def send_dm(
    access_token: str,
    recipient_id: str,
    text: str,
    business: dict = None,
):
    recipient_id = normalize_id(recipient_id)

    if not access_token or not recipient_id or not text:
        print("Cannot send DM")
        return None

    oauth_provider = (business or {}).get("oauth_provider", "")

    if oauth_provider == "facebook_page":
        url = f"{GRAPH_FACEBOOK}/me/messages"
    else:
        url = f"{GRAPH_INSTAGRAM}/me/messages"

    res = requests.post(
        url,
        params={
            "access_token": access_token,
        },
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

    print("DM URL:", url)
    print("DM result:", res.status_code, res.text)

    return res


def reply_to_comment(
    access_token: str,
    comment_id: str,
    text: str,
    business: dict = None,
):
    oauth_provider = (business or {}).get("oauth_provider", "")

    if oauth_provider == "facebook_page":
        url = f"{GRAPH_FACEBOOK}/{comment_id}/replies"
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

    print("Comment URL:", url)
    print("Comment result:", res.status_code, res.text)

    return res


async def process_messaging_event(entry_id: str, messaging: dict):
    print("Messaging event:", messaging)

    if "read" in messaging:
        return

    if "delivery" in messaging:
        return

    message = messaging.get("message") or {}

    if not message:
        return

    sender_id = normalize_id(messaging.get("sender", {}).get("id"))
    recipient_id = normalize_id(messaging.get("recipient", {}).get("id"))
    message_text = message.get("text")
    message_id = message.get("mid")
    is_echo = bool(message.get("is_echo"))

    if is_echo:
        return

    if not sender_id or not recipient_id or not message_text:
        return

    if already_processed(processed_message_ids, message_id):
        return

    business = find_business_for_webhook(
        entry_id,
        recipient_id,
    )

    if not business:
        return

    if not business.get("bot_enabled", True):
        print("Bot disabled for business")
        return

    access_token = business.get("access_token")

    if not access_token:
        return

    reply_text = get_ai_reply(
        user_text=message_text,
        business=business,
        customer_id=sender_id,
        channel="dm",
    )

    send_dm(
        access_token=access_token,
        recipient_id=sender_id,
        text=reply_text,
        business=business,
    )


async def process_comment_event(entry_id: str, change: dict):
    value = change.get("value", {})

    comment_id = normalize_id(
        value.get("comment_id") or value.get("id")
    )

    comment_text = (
        value.get("message")
        or value.get("text")
    )

    commenter_id = normalize_id(
        value.get("from", {}).get("id")
        or value.get("sender", {}).get("id")
        or value.get("user_id")
        or comment_id
    )

    if not comment_id or not comment_text:
        return

    if already_processed(processed_comment_ids, comment_id):
        return

    business = find_business_for_webhook(entry_id)

    if not business:
        return

    if not business.get("bot_enabled", True):
        print("Bot disabled for business")
        return

    access_token = business.get("access_token")

    if not access_token:
        return

    reply_text = get_ai_reply(
        user_text=comment_text,
        business=business,
        customer_id=commenter_id,
        channel="comment",
    )

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
        "version": "chat_memory_company_keys_model_select",
        "connect_instagram": "/connect-instagram",
        "connect_facebook": "/connect-facebook",
    }


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

    auth_url = (
        f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?"
        + urlencode(params)
    )

    return RedirectResponse(auth_url)


@app.get("/auth/facebook/callback")
async def facebook_callback(request: Request):
    code = request.query_params.get("code")

    if not code:
        return PlainTextResponse(
            "Missing Facebook code",
            status_code=400,
        )

    try:
        short_token = exchange_facebook_code_for_token(code)
        user_token = exchange_for_long_lived_facebook_token(short_token)
        pages = get_facebook_pages(user_token)

        print("PAGES:", pages)

        connected = []

        for page in pages:
            ig = get_page_instagram_account(page)

            if not ig or not ig.get("id"):
                print("Skipping page:", page)
                continue

            instagram_business_id = normalize_id(ig.get("id"))

            username = (
                ig.get("username")
                or ig.get("name")
                or f"instagram_{instagram_business_id}"
            )

            upsert_business(
                instagram_business_id=instagram_business_id,
                username=username,
                access_token=page.get("access_token"),
                oauth_provider="facebook_page",
                facebook_page_id=page.get("id"),
                facebook_page_name=page.get("name"),
            )

            sub = subscribe_page_to_webhooks(
                page_id=page.get("id"),
                page_access_token=page.get("access_token"),
            )

            connected.append({
                "page": page,
                "instagram": ig,
                "subscription": sub,
            })

        if not connected:
            return PlainTextResponse(
                "No Instagram returned from Meta API.",
                status_code=400,
            )

        return RedirectResponse(
            f"{DASHBOARD_URL}?connected=success"
        )

    except Exception as e:
        print("Facebook OAuth error:", str(e))

        return PlainTextResponse(
            f"Facebook OAuth error: {str(e)}",
            status_code=500,
        )


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

    auth_url = (
        "https://www.instagram.com/oauth/authorize?"
        + urlencode(params)
    )

    return RedirectResponse(auth_url)


@app.get("/auth/instagram/callback")
async def instagram_callback(request: Request):
    code = request.query_params.get("code")

    if not code:
        return PlainTextResponse(
            "Missing Instagram code",
            status_code=400,
        )

    try:
        token_data = exchange_instagram_code_for_token(code)

        access_token = token_data.get("access_token")
        user_id = normalize_id(token_data.get("user_id"))
        username = f"instagram_{user_id}"

        upsert_business(
            instagram_business_id=user_id,
            username=username,
            access_token=access_token,
            oauth_provider="instagram_direct",
        )

        return RedirectResponse(
            f"{DASHBOARD_URL}?connected=success"
        )

    except Exception as e:
        print("Instagram OAuth error:", str(e))

        return PlainTextResponse(
            f"Instagram OAuth error: {str(e)}",
            status_code=500,
        )


@app.get("/debug/businesses")
async def debug_businesses():
    result = (
        supabase.table("businesses")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    rows = [
        sanitize_business_row(r)
        for r in (result.data or [])
    ]

    return {
        "count": len(rows),
        "businesses": rows,
    }


@app.get("/debug/pages")
async def debug_pages(user_token: str):
    try:
        pages = get_facebook_pages(user_token)

        return {
            "pages": pages,
        }

    except Exception as e:
        return {
            "error": str(e),
        }


@app.get("/debug/memory")
async def debug_memory(business_id: str, customer_id: str, channel: str = "dm"):
    result = (
        supabase.table("chat_memory")
        .select("*")
        .eq("business_id", business_id)
        .eq("customer_id", customer_id)
        .eq("channel", channel)
        .order("created_at", desc=True)
        .limit(30)
        .execute()
    )

    return {
        "count": len(result.data or []),
        "memory": result.data or [],
    }


@app.delete("/debug/memory")
async def clear_memory(business_id: str, customer_id: str, channel: str = "dm"):
    result = (
        supabase.table("chat_memory")
        .delete()
        .eq("business_id", business_id)
        .eq("customer_id", customer_id)
        .eq("channel", channel)
        .execute()
    )

    return {
        "status": "deleted",
        "data": result.data,
    }


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params

    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN
        and params.get("hub.challenge")
    ):
        return PlainTextResponse(
            params.get("hub.challenge"),
            status_code=200,
        )

    return PlainTextResponse(
        "Verification failed",
        status_code=403,
    )


@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()

        print("Webhook received:", data)

        for entry in data.get("entry", []):
            entry_id = normalize_id(entry.get("id"))

            for messaging in entry.get("messaging", []):
                await process_messaging_event(
                    entry_id,
                    messaging,
                )

            for change in entry.get("changes", []):
                field = change.get("field")

                if field in ["comments", "feed"]:
                    await process_comment_event(
                        entry_id,
                        change,
                    )

                elif field == "messages":
                    value = change.get("value", {})

                    fake_messaging = {
                        "sender": value.get("sender", {}),
                        "recipient": value.get("recipient", {}),
                        "timestamp": value.get("timestamp"),
                        "message": value.get("message", {}),
                    }

                    await process_messaging_event(
                        entry_id,
                        fake_messaging,
                    )

        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    except Exception as e:
        print("Webhook error:", str(e))

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
        "Privacy Policy: This app collects Instagram messages "
        "and comments to provide automated AI replies."
    )


@app.get("/terms")
async def terms():
    return PlainTextResponse(
        "Terms of Service: This app provides automated "
        "Instagram replies using AI."
    )
