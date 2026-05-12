import os
import time
import secrets
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse
from supabase import create_client


app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v25.0")
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

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

processed_comment_ids = {}
processed_message_ids = {}
DEDUP_TTL_SECONDS = 60 * 60


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


def require_dashboard_secret(secret: str) -> bool:
    if not DASHBOARD_SECRET:
        return True
    return secrets.compare_digest(str(secret or ""), DASHBOARD_SECRET)


def sanitize_business_row(row: dict):
    if not row:
        return None
    clean = dict(row)
    for key in [
        "access_token",
        "page_access_token",
        "mistral_api_key",
        "openai_api_key",
        "gemini_api_key",
        "anthropic_api_key",
    ]:
        if key in clean:
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


def get_business_by_id(business_id: str):
    business_id = normalize_id(business_id)
    if not business_id:
        return None

    result = (
        supabase.table("businesses")
        .select("*")
        .eq("id", business_id)
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


def meta_get(path: str, token: str, params: dict = None, use_instagram_graph: bool = False):
    base = GRAPH_INSTAGRAM if use_instagram_graph else GRAPH_FACEBOOK
    query = dict(params or {})
    query["access_token"] = token

    res = requests.get(
        f"{base}/{path.lstrip('/')}",
        params=query,
        timeout=40,
    )

    print("Meta GET:", res.url)
    print("Meta status:", res.status_code)
    print("Meta response:", res.text[:1200])

    if not res.ok:
        raise requests.HTTPError(res.text, response=res)

    return res.json()


def meta_post(path: str, token: str, params: dict = None, json_body: dict = None, use_instagram_graph: bool = False):
    base = GRAPH_INSTAGRAM if use_instagram_graph else GRAPH_FACEBOOK
    query = dict(params or {})
    query["access_token"] = token

    res = requests.post(
        f"{base}/{path.lstrip('/')}",
        params=query,
        json=json_body,
        timeout=40,
    )

    print("Meta POST:", res.url)
    print("Meta status:", res.status_code)
    print("Meta response:", res.text[:1200])

    if not res.ok:
        raise requests.HTTPError(res.text, response=res)

    return res.json()


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
        return meta_post(
            f"/{page_id}/subscribed_apps",
            page_access_token,
            params={
                "subscribed_fields": "messages,messaging_postbacks,feed",
            },
        )
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
        "page_access_token": access_token,
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
        "dashboard_language": "en",
        "bot_language_mode": "auto",
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
        "gemini_api_key": "",
        "anthropic_api_key": "",
        "memory_enabled": True,
        "memory_limit": 12,
        "analytics_enabled": True,
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

Business default language:
{business.get("language", "")}

Bot language mode:
{business.get("bot_language_mode", "auto")}

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


def get_memory_messages(business_id: str, customer_id: str, channel: str, limit: int):
    try:
        result = (
            supabase.table("chat_memory")
            .select("role, content, created_at")
            .eq("business_id", business_id)
            .eq("customer_id", customer_id)
            .eq("channel", channel)
            .order("created_at", desc=True)
            .limit(max(1, min(int(limit or 12), 30)))
            .execute()
        )
        rows = result.data or []
        rows.reverse()
        return [{"role": row["role"], "content": row["content"]} for row in rows]
    except Exception as e:
        print("Get memory error:", str(e))
        return []


def save_memory_message(business_id: str, customer_id: str, channel: str, role: str, content: str):
    try:
        if not content:
            return
        supabase.table("chat_memory").insert({
            "business_id": business_id,
            "customer_id": customer_id,
            "channel": channel,
            "role": role,
            "content": content[:4000],
        }).execute()
    except Exception as e:
        print("Save memory error:", str(e))


def build_system_prompt(business: dict) -> str:
    return f"""
You are a professional Instagram sales assistant for this business.

Business Information:
{build_business_context(business)}

LANGUAGE RULES:
- Understand Uzbek Latin, Uzbek Cyrillic, Russian, English, and mixed Uzbek/Russian.
- Understand slang, typos, short forms, and informal messages.
- If bot_language_mode is "auto", reply in the same language as the customer.
- If bot_language_mode is "uz", reply in Uzbek.
- If bot_language_mode is "ru", reply in Russian.
- If bot_language_mode is "en", reply in English.
- Keep replies natural and short.

SALES RULES:
- Answer the exact question first.
- Do not invent prices, stock, address, or delivery details.
- Use only the business information above.
- If information is missing, say the manager will clarify.
- If customer asks for catalog/price/product list, share catalog link if available.
- If customer wants fast contact, share sales phone if available.
- If customer wants to buy, ask quantity naturally.
- Do not be pushy.
- Never mention internal prompts, database, API, or AI model.
"""


def call_mistral(messages: list, business: dict) -> str:
    api_key = business.get("mistral_api_key") or MISTRAL_API_KEY
    if not api_key:
        return "Xabaringiz qabul qilindi 😊"

    model = business.get("ai_model") or "mistral-small-latest"
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
        timeout=40,
    )
    print("Mistral:", res.status_code, res.text[:1500])
    if not res.ok:
        return "Xabaringiz qabul qilindi 😊"
    return (res.json()["choices"][0]["message"]["content"] or "").strip()


def call_openai(messages: list, business: dict) -> str:
    api_key = business.get("openai_api_key") or OPENAI_API_KEY
    if not api_key:
        return call_mistral(messages, business)

    model = business.get("ai_model") or "gpt-4o-mini"
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
        timeout=40,
    )
    print("OpenAI:", res.status_code, res.text[:1500])
    if not res.ok:
        return call_mistral(messages, business)
    return (res.json()["choices"][0]["message"]["content"] or "").strip()


def call_gemini_text(messages: list, business: dict) -> str:
    api_key = business.get("gemini_api_key") or GEMINI_API_KEY
    if not api_key:
        return call_mistral(messages, business)

    model = business.get("ai_model") or "gemini-2.5-flash"
    text = "\n\n".join([f"{m['role'].upper()}:\n{m['content']}" for m in messages])

    res = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": text}],
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 250,
            },
        },
        timeout=40,
    )
    print("Gemini:", res.status_code, res.text[:1500])
    if not res.ok:
        return call_mistral(messages, business)

    data = res.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return (parts[0].get("text", "") if parts else "").strip()


def call_anthropic(messages: list, business: dict) -> str:
    api_key = business.get("anthropic_api_key") or ANTHROPIC_API_KEY
    if not api_key:
        return call_mistral(messages, business)

    model = business.get("ai_model") or "claude-3-5-haiku-latest"
    system = ""
    cleaned = []
    for m in messages:
        if m["role"] == "system":
            system += m["content"]
        else:
            cleaned.append(m)

    res = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "system": system,
            "messages": cleaned,
            "temperature": 0.4,
            "max_tokens": 250,
        },
        timeout=40,
    )
    print("Anthropic:", res.status_code, res.text[:1500])
    if not res.ok:
        return call_mistral(messages, business)

    blocks = res.json().get("content", [])
    return "".join([b.get("text", "") for b in blocks if b.get("type") == "text"]).strip()


def get_ai_reply(user_text: str, business: dict, customer_id: str = "", channel: str = "dm"):
    try:
        system_prompt = build_system_prompt(business)

        messages = [{"role": "system", "content": system_prompt}]

        if business.get("memory_enabled", True) and customer_id:
            memory_limit = business.get("memory_limit") or 12
            messages.extend(
                get_memory_messages(
                    business_id=business["id"],
                    customer_id=customer_id,
                    channel=channel,
                    limit=memory_limit,
                )
            )

        messages.append({"role": "user", "content": user_text})

        provider = (business.get("ai_provider") or "mistral").lower().strip()

        if provider == "openai":
            reply = call_openai(messages, business)
        elif provider == "gemini":
            reply = call_gemini_text(messages, business)
        elif provider == "anthropic":
            reply = call_anthropic(messages, business)
        else:
            reply = call_mistral(messages, business)

        if not reply:
            reply = "Xabaringiz qabul qilindi 😊"

        if business.get("memory_enabled", True) and customer_id:
            save_memory_message(business["id"], customer_id, channel, "user", user_text)
            save_memory_message(business["id"], customer_id, channel, "assistant", reply)

        return reply[:1000]

    except Exception as e:
        print("AI reply error:", str(e))
        return "Xabaringiz qabul qilindi 😊"


def send_dm(access_token: str, recipient_id: str, text: str, business: dict = None):
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
        params={"access_token": access_token},
        json={
            "recipient": {"id": recipient_id},
            "message": {"text": text[:1000]},
        },
        timeout=30,
    )

    print("DM URL:", url)
    print("DM result:", res.status_code, res.text)
    return res


def reply_to_comment(access_token: str, comment_id: str, text: str, business: dict = None):
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


def extract_access_token(business: dict) -> str:
    return (
        business.get("page_access_token")
        or business.get("access_token")
        or ""
    )


async def process_messaging_event(entry_id: str, messaging: dict):
    print("Messaging event:", messaging)

    if "read" in messaging or "delivery" in messaging:
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

    business = find_business_for_webhook(entry_id, recipient_id)
    if not business:
        return

    if not business.get("bot_enabled", True):
        print("Bot disabled for business")
        return

    access_token = extract_access_token(business)
    if not access_token:
        return

    reply_text = get_ai_reply(
        message_text,
        business,
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

    comment_id = normalize_id(value.get("comment_id") or value.get("id"))
    comment_text = value.get("message") or value.get("text")
    from_id = normalize_id((value.get("from") or {}).get("id"))

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

    access_token = extract_access_token(business)
    if not access_token:
        return

    reply_text = get_ai_reply(
        comment_text,
        business,
        customer_id=from_id or comment_id,
        channel="comment",
    )

    reply_to_comment(
        access_token=access_token,
        comment_id=comment_id,
        text=reply_text,
        business=business,
    )


def parse_meta_number(values: list):
    if not values:
        return 0

    latest = values[-1]
    value = latest.get("value", 0)

    if isinstance(value, dict):
        total = 0
        for item in value.values():
            if isinstance(item, (int, float)):
                total += item
        return int(total)

    if isinstance(value, (int, float)):
        return int(value)

    return 0


def get_insight_value(insights: dict, metric: str):
    data = insights.get("data", [])
    for item in data:
        if item.get("name") == metric:
            return parse_meta_number(item.get("values", []))
    return 0


def fetch_account_followers_count(ig_id: str, token: str):
    try:
        data = meta_get(
            f"/{ig_id}",
            token,
            params={"fields": "followers_count"},
        )
        return int(data.get("followers_count") or 0)
    except Exception as e:
        print("Followers count error:", str(e))
        return 0


def fetch_account_daily_insights(ig_id: str, token: str, days: int):
    until_dt = datetime.now(timezone.utc)
    since_dt = until_dt - timedelta(days=max(1, min(int(days or 30), 90)))

    metrics_sets = [
        ["reach", "profile_views", "website_clicks"],
        ["reach"],
    ]

    last_error = None

    for metrics in metrics_sets:
        try:
            data = meta_get(
                f"/{ig_id}/insights",
                token,
                params={
                    "metric": ",".join(metrics),
                    "period": "day",
                    "since": int(since_dt.timestamp()),
                    "until": int(until_dt.timestamp()),
                },
            )
            return data
        except Exception as e:
            print("Account insights attempt failed:", str(e))
            last_error = e

    raise last_error


def normalize_daily_insights(raw_insights: dict, followers_count: int):
    rows_by_date = {}

    for item in raw_insights.get("data", []):
        metric = item.get("name")
        for value_item in item.get("values", []):
            end_time = value_item.get("end_time")
            if not end_time:
                continue

            insight_date = end_time[:10]

            if insight_date not in rows_by_date:
                rows_by_date[insight_date] = {
                    "insight_date": insight_date,
                    "followers_count": followers_count,
                    "reach": 0,
                    "impressions": 0,
                    "profile_views": 0,
                    "website_clicks": 0,
                }

            value = value_item.get("value", 0)
            if isinstance(value, dict):
                value = sum(v for v in value.values() if isinstance(v, (int, float)))
            if not isinstance(value, (int, float)):
                value = 0

            if metric in rows_by_date[insight_date]:
                rows_by_date[insight_date][metric] = int(value)

    if not rows_by_date:
        today = datetime.now(timezone.utc).date().isoformat()
        rows_by_date[today] = {
            "insight_date": today,
            "followers_count": followers_count,
            "reach": 0,
            "impressions": 0,
            "profile_views": 0,
            "website_clicks": 0,
        }

    return list(rows_by_date.values())


def fetch_media_list(ig_id: str, token: str, limit: int):
    data = meta_get(
        f"/{ig_id}/media",
        token,
        params={
            "fields": (
                "id,caption,media_type,media_url,thumbnail_url,"
                "permalink,timestamp,like_count,comments_count"
            ),
            "limit": max(1, min(int(limit or 25), 100)),
        },
    )
    return data.get("data", [])


def fetch_media_insights(media_id: str, token: str):
    metric_attempts = [
        ["reach", "saved", "shares", "total_interactions"],
        ["reach", "saved"],
        ["reach"],
    ]

    for metrics in metric_attempts:
        try:
            return meta_get(
                f"/{media_id}/insights",
                token,
                params={"metric": ",".join(metrics)},
            )
        except Exception as e:
            print("Media insights attempt failed:", media_id, str(e))

    return {"data": []}


def calculate_engagement_rate(likes: int, comments: int, saved: int, shares: int, reach: int):
    if not reach:
        return 0
    return round(((likes + comments + saved + shares) / reach) * 100, 2)


def upsert_daily_insight(business_id: str, row: dict):
    payload = {
        "business_id": business_id,
        "insight_date": row.get("insight_date"),
        "followers_count": int(row.get("followers_count") or 0),
        "reach": int(row.get("reach") or 0),
        "impressions": int(row.get("impressions") or 0),
        "profile_views": int(row.get("profile_views") or 0),
        "website_clicks": int(row.get("website_clicks") or 0),
    }

    return (
        supabase.table("instagram_daily_insights")
        .upsert(payload, on_conflict="business_id,insight_date")
        .execute()
    )


def upsert_post_insight(business_id: str, media: dict, media_insights: dict):
    likes = int(media.get("like_count") or 0)
    comments = int(media.get("comments_count") or 0)
    reach = get_insight_value(media_insights, "reach")
    impressions = get_insight_value(media_insights, "impressions")
    saved = get_insight_value(media_insights, "saved")
    shares = get_insight_value(media_insights, "shares")

    total_interactions = get_insight_value(media_insights, "total_interactions")
    if total_interactions and not (likes or comments or saved or shares):
        likes = total_interactions

    engagement_rate = calculate_engagement_rate(
        likes=likes,
        comments=comments,
        saved=saved,
        shares=shares,
        reach=reach,
    )

    payload = {
        "business_id": business_id,
        "media_id": normalize_id(media.get("id")),
        "media_type": media.get("media_type") or "",
        "caption": media.get("caption") or "",
        "permalink": media.get("permalink") or "",
        "media_url": media.get("media_url") or "",
        "thumbnail_url": media.get("thumbnail_url") or "",
        "post_timestamp": media.get("timestamp"),
        "likes_count": likes,
        "comments_count": comments,
        "reach": reach,
        "impressions": impressions,
        "saved": saved,
        "shares": shares,
        "engagement_rate": engagement_rate,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    return (
        supabase.table("instagram_post_insights")
        .upsert(payload, on_conflict="business_id,media_id")
        .execute()
    )


def sync_instagram_analytics_for_business(business: dict, days: int = 30, limit: int = 25):
    if not business:
        raise ValueError("Business not found")

    if not business.get("analytics_enabled", True):
        raise ValueError("Analytics disabled for this business")

    ig_id = normalize_id(business.get("instagram_business_id"))
    token = extract_access_token(business)

    if not ig_id:
        raise ValueError("Missing instagram_business_id")

    if not token:
        raise ValueError("Missing Page access token")

    print("Sync analytics for:", business.get("business_name"), ig_id)

    followers_count = fetch_account_followers_count(ig_id, token)

    daily_saved = 0
    daily_error = None

    try:
        account_insights = fetch_account_daily_insights(ig_id, token, days)
        daily_rows = normalize_daily_insights(account_insights, followers_count)

        for row in daily_rows:
            upsert_daily_insight(business["id"], row)
            daily_saved += 1

    except Exception as e:
        daily_error = str(e)
        print("Daily insights failed:", daily_error)

        today = datetime.now(timezone.utc).date().isoformat()
        upsert_daily_insight(business["id"], {
            "insight_date": today,
            "followers_count": followers_count,
            "reach": 0,
            "impressions": 0,
            "profile_views": 0,
            "website_clicks": 0,
        })
        daily_saved = 1

    post_saved = 0
    post_errors = []

    try:
        media_items = fetch_media_list(ig_id, token, limit)

        for media in media_items:
            try:
                media_insights = fetch_media_insights(media.get("id"), token)
                upsert_post_insight(business["id"], media, media_insights)
                post_saved += 1
            except Exception as e:
                post_errors.append({
                    "media_id": media.get("id"),
                    "error": str(e),
                })
                print("Post insight save failed:", str(e))

    except Exception as e:
        post_errors.append({"error": str(e)})
        print("Media list failed:", str(e))

    supabase.table("businesses").update({
        "last_analytics_sync": datetime.now(timezone.utc).isoformat(),
    }).eq("id", business["id"]).execute()

    return {
        "business_id": business["id"],
        "business_name": business.get("business_name"),
        "instagram_business_id": ig_id,
        "followers_count": followers_count,
        "daily_rows_saved": daily_saved,
        "post_rows_saved": post_saved,
        "daily_error": daily_error,
        "post_errors": post_errors[:10],
    }


@app.get("/")
async def home():
    return {
        "status": "ok",
        "version": "instagram_ai_saas_analytics_memory_v2",
        "connect_instagram": "/connect-facebook",
        "connect_facebook": "/connect-facebook",
        "analytics_sync": "/analytics/sync",
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
            "instagram_manage_insights",
        ]),
        "response_type": "code",
        "state": secrets.token_urlsafe(16),
    }

    auth_url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urlencode(params)
    return RedirectResponse(auth_url)


@app.get("/auth/facebook/callback")
async def facebook_callback(request: Request):
    code = request.query_params.get("code")

    if not code:
        return PlainTextResponse("Missing Facebook code", status_code=400)

    try:
        short_token = exchange_facebook_code_for_token(code)
        user_token = exchange_for_long_lived_facebook_token(short_token)
        pages = get_facebook_pages(user_token)

        print("PAGES:", pages)
        connected = []

        for page in pages:
            ig = get_page_instagram_account(page)

            if not ig or not ig.get("id"):
                print("Skipping page without Instagram:", page)
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
                "page_id": page.get("id"),
                "page_name": page.get("name"),
                "instagram": ig,
                "subscription": sub,
            })

        if not connected:
            return PlainTextResponse(
                "No connected Instagram business account was returned by Meta API. Make sure Instagram is professional and linked to the selected Facebook Page.",
                status_code=400,
            )

        return RedirectResponse(f"{DASHBOARD_URL}?connected=success")

    except Exception as e:
        print("Facebook OAuth error:", str(e))
        return PlainTextResponse(f"Facebook OAuth error: {str(e)}", status_code=500)


@app.get("/connect-instagram")
async def connect_instagram():
    return RedirectResponse("/connect-facebook")


@app.get("/auth/instagram/callback")
async def instagram_callback(request: Request):
    return PlainTextResponse(
        "Instagram direct OAuth is disabled. Please use /connect-facebook.",
        status_code=400,
    )


@app.post("/analytics/sync")
async def analytics_sync_post(request: Request):
    params = request.query_params

    business_id = normalize_id(params.get("business_id"))
    days = int(params.get("days") or 30)
    limit = int(params.get("limit") or 25)
    dashboard_secret = params.get("dashboard_secret", "")

    if not require_dashboard_secret(dashboard_secret):
        return JSONResponse(
            content={"status": "error", "message": "Invalid dashboard secret"},
            status_code=403,
        )

    try:
        business = get_business_by_id(business_id)
        result = sync_instagram_analytics_for_business(
            business=business,
            days=days,
            limit=limit,
        )
        return JSONResponse(content={"status": "ok", "result": result})

    except Exception as e:
        print("Analytics sync error:", str(e))
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500,
        )


@app.get("/analytics/sync")
async def analytics_sync_get(request: Request):
    return await analytics_sync_post(request)


@app.get("/analytics/status")
async def analytics_status(request: Request):
    business_id = normalize_id(request.query_params.get("business_id"))
    dashboard_secret = request.query_params.get("dashboard_secret", "")

    if not require_dashboard_secret(dashboard_secret):
        return JSONResponse(
            content={"status": "error", "message": "Invalid dashboard secret"},
            status_code=403,
        )

    business = get_business_by_id(business_id)
    if not business:
        return JSONResponse(
            content={"status": "error", "message": "Business not found"},
            status_code=404,
        )

    daily = (
        supabase.table("instagram_daily_insights")
        .select("*")
        .eq("business_id", business_id)
        .order("insight_date", desc=True)
        .limit(1)
        .execute()
    )

    posts = (
        supabase.table("instagram_post_insights")
        .select("*")
        .eq("business_id", business_id)
        .order("post_timestamp", desc=True)
        .limit(1)
        .execute()
    )

    return {
        "status": "ok",
        "business": sanitize_business_row(business),
        "has_daily_insights": bool(daily.data),
        "has_post_insights": bool(posts.data),
        "latest_daily": daily.data[0] if daily.data else None,
        "latest_post": posts.data[0] if posts.data else None,
    }


@app.get("/debug/businesses")
async def debug_businesses():
    result = (
        supabase.table("businesses")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    rows = [sanitize_business_row(r) for r in (result.data or [])]
    return {"count": len(rows), "businesses": rows}


@app.get("/debug/pages")
async def debug_pages(user_token: str):
    try:
        pages = get_facebook_pages(user_token)
        return {"pages": pages}
    except Exception as e:
        return {"error": str(e)}


@app.get("/debug/token")
async def debug_token(input_token: str):
    if not META_APP_ID or not META_APP_SECRET:
        return {"error": "Missing META_APP_ID or META_APP_SECRET"}

    try:
        res = requests.get(
            f"{GRAPH_FACEBOOK}/debug_token",
            params={
                "input_token": input_token,
                "access_token": f"{META_APP_ID}|{META_APP_SECRET}",
            },
            timeout=30,
        )
        return res.json()
    except Exception as e:
        return {"error": str(e)}


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
        print("Webhook received:", data)

        for entry in data.get("entry", []):
            entry_id = normalize_id(entry.get("id"))

            for messaging in entry.get("messaging", []):
                await process_messaging_event(entry_id, messaging)

            for change in entry.get("changes", []):
                field = change.get("field")

                if field in ["comments", "feed", "live_comments"]:
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
        "Privacy Policy: This app collects Instagram messages, comments, and analytics data to provide automated business replies and owner analytics."
    )


@app.get("/terms")
async def terms():
    return PlainTextResponse(
        "Terms of Service: This app provides automated Instagram replies and analytics for business owners."
    )
