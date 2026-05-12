import os
import time
import secrets
import requests
from urllib.parse import urlencode
from typing import Optional, List, Dict
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse
from supabase import create_client


app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")

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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def safe_db_insert(table: str, data: dict):
    try:
        return supabase.table(table).insert(data).execute()
    except Exception as e:
        print(f"{table} insert skipped/error:", str(e))
        return None


def safe_db_upsert(table: str, data: dict, on_conflict: str = ""):
    try:
        if on_conflict:
            return supabase.table(table).upsert(data, on_conflict=on_conflict).execute()
        return supabase.table(table).upsert(data).execute()
    except Exception as e:
        print(f"{table} upsert skipped/error:", str(e))
        return None


def safe_db_select(builder, fallback=None):
    try:
        result = builder.execute()
        return result.data or fallback or []
    except Exception as e:
        print("DB select skipped/error:", str(e))
        return fallback or []


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
        "whatsapp_access_token",
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


def get_conversation_state(
    business_id: str,
    platform: str,
    customer_id: str,
    channel: str,
) -> str:
    try:
        result = (
            supabase.table("conversations")
            .select("state")
            .eq("business_id", business_id)
            .eq("platform", platform)
            .eq("customer_id", customer_id)
            .eq("channel", channel)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0].get("state") or "AI_ACTIVE"

    except Exception as e:
        print("Conversation state unavailable:", str(e))

    return "AI_ACTIVE"


def upsert_customer(
    business_id: str,
    platform: str,
    customer_id: str,
    display_name: str = "",
):
    if not business_id or not customer_id:
        return

    safe_db_upsert(
        "customers",
        {
            "business_id": business_id,
            "platform": platform,
            "customer_id": customer_id,
            "display_name": display_name or customer_id,
            "status": "new",
            "last_seen_at": now_iso(),
            "updated_at": now_iso(),
        },
        on_conflict="business_id,platform,customer_id",
    )


def upsert_conversation(
    business_id: str,
    platform: str,
    customer_id: str,
    channel: str,
):
    if not business_id or not customer_id:
        return

    current_state = get_conversation_state(
        business_id=business_id,
        platform=platform,
        customer_id=customer_id,
        channel=channel,
    )

    safe_db_upsert(
        "conversations",
        {
            "business_id": business_id,
            "platform": platform,
            "customer_id": customer_id,
            "channel": channel,
            "state": current_state,
            "last_message_at": now_iso(),
            "updated_at": now_iso(),
        },
        on_conflict="business_id,platform,customer_id,channel",
    )


def save_inbox_message(
    business_id: str,
    platform: str,
    customer_id: str,
    channel: str,
    direction: str,
    role: str,
    content: str,
    external_message_id: str = "",
    raw_payload: Optional[dict] = None,
):
    if not business_id or not customer_id or not content:
        return

    safe_db_insert(
        "inbox_messages",
        {
            "business_id": business_id,
            "platform": platform,
            "customer_id": customer_id,
            "channel": channel,
            "direction": direction,
            "role": role,
            "content": content[:4000],
            "external_message_id": external_message_id or "",
            "raw_payload": raw_payload or {},
            "created_at": now_iso(),
        },
    )


def detect_button_trigger(text: str) -> str:
    t = (text or "").lower()

    if any(x in t for x in ["catalog", "katalog", "каталог", "price", "narx", "цена", "прайс", "nechpul", "qancha"]):
        return "catalog"

    if any(x in t for x in ["optom", "оптом", "wholesale", "sotrud", "сотруд", "hamkor", "kazakhstan", "казахстан"]):
        return "wholesale"

    if any(x in t for x in ["delivery", "dostavka", "доставка", "yetkaz", "достав"]):
        return "delivery"

    if any(x in t for x in ["phone", "call", "tel", "номер", "aloqa", "связ", "whatsapp", "telegram"]):
        return "contact"

    return "default"


def get_business_buttons(business_id: str, trigger: str = "default") -> List[dict]:
    try:
        result = (
            supabase.table("business_buttons")
            .select("*")
            .eq("business_id", business_id)
            .eq("is_active", True)
            .or_(f"trigger.eq.{trigger},trigger.eq.default")
            .order("sort_order")
            .limit(4)
            .execute()
        )

        return result.data or []

    except Exception as e:
        print("Buttons unavailable:", str(e))
        return []


def build_quick_replies(buttons: List[dict]) -> List[dict]:
    quick_replies = []

    for b in buttons[:4]:
        title = (b.get("title") or "").strip()[:20]
        action_type = (b.get("action_type") or "message").strip()
        action_value = (b.get("action_value") or title).strip()

        if not title:
            continue

        if action_type == "message":
            quick_replies.append({
                "content_type": "text",
                "title": title,
                "payload": f"BTN::{b.get('id', title)}::{action_value}"[:1000],
            })

    return quick_replies


def format_buttons_as_text(buttons: List[dict]) -> str:
    if not buttons:
        return ""

    lines = []

    for b in buttons[:4]:
        title = (b.get("title") or "").strip()
        action_type = (b.get("action_type") or "message").strip()
        action_value = (b.get("action_value") or "").strip()

        if not title:
            continue

        if action_type in ["url", "phone"] and action_value:
            lines.append(f"{title}: {action_value}")
        else:
            lines.append(f"• {title}")

    if not lines:
        return ""

    return "\n\n" + "\n".join(lines)


def meta_get(url: str, params: dict, timeout: int = 30) -> dict:
    try:
        res = requests.get(url, params=params, timeout=timeout)
        print("Meta GET:", res.url)
        print("Meta status:", res.status_code)
        print("Meta body:", res.text)

        if not res.ok:
            return {
                "ok": False,
                "status_code": res.status_code,
                "error": res.text,
            }

        data = res.json()
        data["ok"] = True
        return data

    except Exception as e:
        print("Meta GET exception:", str(e))
        return {
            "ok": False,
            "error": str(e),
        }


def extract_insight_value(insights_data: dict, metric_name: str, default: int = 0) -> int:
    try:
        for item in insights_data.get("data", []):
            if item.get("name") == metric_name:
                values = item.get("values") or []
                if not values:
                    return default

                latest = values[-1].get("value", default)

                if isinstance(latest, dict):
                    total = 0
                    for value in latest.values():
                        try:
                            total += int(value or 0)
                        except Exception:
                            pass
                    return total

                return int(latest or 0)
    except Exception:
        pass

    return default


def get_account_basic_metrics(ig_id: str, access_token: str) -> dict:
    data = meta_get(
        f"{GRAPH_FACEBOOK}/{ig_id}",
        params={
            "fields": "id,username,followers_count,follows_count,media_count,profile_picture_url",
            "access_token": access_token,
        },
    )

    if not data.get("ok"):
        return {
            "followers_count": 0,
            "media_count": 0,
            "username": "",
            "raw": data,
        }

    return {
        "followers_count": int(data.get("followers_count") or 0),
        "media_count": int(data.get("media_count") or 0),
        "username": data.get("username") or "",
        "raw": data,
    }


def get_account_advanced_insights(ig_id: str, access_token: str, days: int = 30) -> dict:
    metrics = "reach,profile_views,website_clicks"

    data = meta_get(
        f"{GRAPH_FACEBOOK}/{ig_id}/insights",
        params={
            "metric": metrics,
            "period": "day",
            "metric_type": "total_value",
            "access_token": access_token,
        },
    )

    if not data.get("ok"):
        data = meta_get(
            f"{GRAPH_FACEBOOK}/{ig_id}/insights",
            params={
                "metric": "reach",
                "period": "day",
                "access_token": access_token,
            },
        )

    return {
        "reach": extract_insight_value(data, "reach", 0),
        "profile_views": extract_insight_value(data, "profile_views", 0),
        "website_clicks": extract_insight_value(data, "website_clicks", 0),
        "impressions": extract_insight_value(data, "impressions", 0),
        "raw": data,
    }


def get_media_list(ig_id: str, access_token: str, limit: int = 25) -> dict:
    fields = ",".join([
        "id",
        "caption",
        "media_type",
        "media_url",
        "thumbnail_url",
        "permalink",
        "timestamp",
        "like_count",
        "comments_count",
    ])

    data = meta_get(
        f"{GRAPH_FACEBOOK}/{ig_id}/media",
        params={
            "fields": fields,
            "limit": max(1, min(int(limit or 25), 100)),
            "access_token": access_token,
        },
    )

    if not data.get("ok"):
        return {
            "posts": [],
            "raw": data,
        }

    return {
        "posts": data.get("data", []) or [],
        "raw": data,
    }


def get_media_advanced_insights(media_id: str, access_token: str) -> dict:
    data = meta_get(
        f"{GRAPH_FACEBOOK}/{media_id}/insights",
        params={
            "metric": "reach,saved,shares,total_interactions",
            "access_token": access_token,
        },
    )

    if not data.get("ok"):
        data = meta_get(
            f"{GRAPH_FACEBOOK}/{media_id}/insights",
            params={
                "metric": "reach,saved",
                "access_token": access_token,
            },
        )

    return {
        "reach": extract_insight_value(data, "reach", 0),
        "saved": extract_insight_value(data, "saved", 0),
        "shares": extract_insight_value(data, "shares", 0),
        "total_interactions": extract_insight_value(data, "total_interactions", 0),
        "raw": data,
    }


def parse_meta_timestamp(value: str):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except Exception:
        return None


def upsert_daily_insight(
    business_id: str,
    followers_count: int,
    reach: int,
    impressions: int,
    profile_views: int,
    website_clicks: int,
):
    today = datetime.now(timezone.utc).date().isoformat()

    row = {
        "business_id": business_id,
        "insight_date": today,
        "followers_count": int(followers_count or 0),
        "reach": int(reach or 0),
        "impressions": int(impressions or 0),
        "profile_views": int(profile_views or 0),
        "website_clicks": int(website_clicks or 0),
    }

    return (
        supabase.table("instagram_daily_insights")
        .upsert(row, on_conflict="business_id,insight_date")
        .execute()
    )


def upsert_post_insights(
    business_id: str,
    post: dict,
    followers_count: int,
    advanced: dict,
):
    likes_count = int(post.get("like_count") or post.get("likes_count") or 0)
    comments_count = int(post.get("comments_count") or 0)
    reach = int(advanced.get("reach") or 0)
    saved = int(advanced.get("saved") or 0)
    shares = int(advanced.get("shares") or 0)

    denominator = reach if reach > 0 else max(int(followers_count or 0), 1)
    engagement_rate = round(((likes_count + comments_count + saved + shares) / denominator) * 100, 2)

    row = {
        "business_id": business_id,
        "media_id": str(post.get("id") or ""),
        "media_type": post.get("media_type") or "",
        "caption": post.get("caption") or "",
        "permalink": post.get("permalink") or "",
        "media_url": post.get("media_url") or "",
        "thumbnail_url": post.get("thumbnail_url") or "",
        "post_timestamp": parse_meta_timestamp(post.get("timestamp") or ""),
        "likes_count": likes_count,
        "comments_count": comments_count,
        "reach": reach,
        "impressions": 0,
        "saved": saved,
        "shares": shares,
        "engagement_rate": engagement_rate,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not row["media_id"]:
        return None

    return (
        supabase.table("instagram_post_insights")
        .upsert(row, on_conflict="business_id,media_id")
        .execute()
    )


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
        "memory_limit": MAX_MEMORY_MESSAGES,
        "analytics_enabled": True,
        "automation_mode": "FULL_AUTO",
        "auto_reply_dms": True,
        "auto_reply_comments": True,
        "auto_send_catalog": True,
        "human_takeover_enabled": True,
        "whatsapp_enabled": False,
        "whatsapp_phone_number_id": "",
        "whatsapp_access_token": "",
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


def build_flow_instruction(user_text: str) -> str:
    trigger = detect_button_trigger(user_text)

    if trigger == "wholesale":
        return "Customer likely wants wholesale/cooperation. Ask only one simple next question about product type or approximate quantity. Do not ask for all details at once."

    if trigger == "catalog":
        return "Customer asks about price/catalog. Give a short answer and mention catalog if available. Do not collect full order details yet."

    if trigger == "delivery":
        return "Customer asks about delivery. Answer using delivery information. Ask city/country only if needed."

    if trigger == "contact":
        return "Customer wants contact. Provide sales phone or contact link if available. Keep it short."

    return "Use progressive lead collection. Do not ask for name, phone, address, product and quantity all at once unless the customer is clearly ready to order."


def build_system_prompt(business: dict, user_text: str = "") -> str:
    bot_language_mode = business.get("bot_language_mode", "auto")

    language_rule = """
- Reply naturally in the SAME language the customer uses.
- If customer writes in Uzbek Latin, reply in Uzbek Latin.
- If customer writes in Uzbek Cyrillic, reply in Uzbek Cyrillic.
- If customer writes in Russian, reply in Russian.
- If customer writes in English, reply in English.
"""

    if bot_language_mode in ["uz", "ru", "en"]:
        language_rule = f"""
- Reply in this business selected language only: {bot_language_mode}.
- Keep the reply natural and suitable for Instagram/WhatsApp.
"""

    return f"""
You are an autonomous Instagram and WhatsApp sales assistant for this business.

Business Information:
{build_business_context(business)}

IMPORTANT LANGUAGE RULES:

- Understand Uzbek, Russian, English, mixed language, slang, typos, and informal texting.
- Understand ALL Uzbek dialects and regional speaking styles.
- Understand Uzbek written in BOTH Latin and Cyrillic alphabets.
{language_rule}
- Never say you do not understand because of dialect, spelling, or grammar.
- Infer the customer’s meaning from context.

SALES RULES:

- Keep replies short, clear, natural, and sales-focused.
- Sound like a real human sales consultant, not a robot.
- Do not write long paragraphs.
- Do not repeat the same request multiple times.
- Do not force customers to give information.
- Ask only ONE simple next question when needed.
- Answer the exact question first.
- Continue naturally using previous conversation memory.

FLOW RULES:
{build_flow_instruction(user_text)}

LEAD COLLECTION RULES:

- Do not ask for name, phone, address, product, and quantity all at once.
- Collect details step by step only when the customer is ready to order.
- First help the customer choose product / quantity / delivery direction.
- Ask phone/address only near the order stage.

CATALOG AND PRICE RULES:

- If customer asks about price, catalog, product list, "narx", "nechpul", "прайс", "каталог", or similar:
  send or mention the catalog link if available.
- If catalog link is empty, politely say the manager will clarify.

CONTACT RULES:

- If customer wants fast contact, phone number, Telegram, WhatsApp, manager, or "aloqa":
  provide the sales phone if available.
- Mention Telegram and WhatsApp are available only if business information says so.

DELIVERY RULES:

- If customer asks about delivery, use delivery information from business data.
- Do not invent delivery details.

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
            "temperature": 0.35,
            "max_tokens": 220,
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
            "temperature": 0.35,
            "max_tokens": 220,
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
        system_prompt = build_system_prompt(business, user_text)

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
    buttons: Optional[List[dict]] = None,
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

    message_payload = {
        "text": text[:1000],
    }

    quick_replies = build_quick_replies(buttons or [])

    if quick_replies:
        message_payload["quick_replies"] = quick_replies

    res = requests.post(
        url,
        params={
            "access_token": access_token,
        },
        json={
            "recipient": {
                "id": recipient_id,
            },
            "message": message_payload,
        },
        timeout=30,
    )

    print("DM URL:", url)
    print("DM result:", res.status_code, res.text)

    if not res.ok and buttons:
        fallback_text = (text + format_buttons_as_text(buttons))[:1000]

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
                    "text": fallback_text,
                },
            },
            timeout=30,
        )

        print("DM fallback result:", res.status_code, res.text)

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


async def handle_customer_message(
    business: dict,
    platform: str,
    customer_id: str,
    channel: str,
    text: str,
    external_message_id: str = "",
    raw_payload: Optional[dict] = None,
):
    business_id = business.get("id")

    upsert_customer(
        business_id=business_id,
        platform=platform,
        customer_id=customer_id,
    )

    upsert_conversation(
        business_id=business_id,
        platform=platform,
        customer_id=customer_id,
        channel=channel,
    )

    save_inbox_message(
        business_id=business_id,
        platform=platform,
        customer_id=customer_id,
        channel=channel,
        direction="inbound",
        role="customer",
        content=text,
        external_message_id=external_message_id,
        raw_payload=raw_payload,
    )

    state = get_conversation_state(
        business_id=business_id,
        platform=platform,
        customer_id=customer_id,
        channel=channel,
    )

    if state in ["HUMAN_ACTIVE", "PAUSED"]:
        print("AI paused for conversation:", {
            "business_id": business_id,
            "platform": platform,
            "customer_id": customer_id,
            "channel": channel,
            "state": state,
        })
        return None

    if not business.get("bot_enabled", True):
        print("Bot disabled for business")
        return None

    if channel == "dm" and business.get("auto_reply_dms") is False:
        print("Auto reply DMs disabled")
        return None

    if channel == "comment" and business.get("auto_reply_comments") is False:
        print("Auto reply comments disabled")
        return None

    reply_text = get_ai_reply(
        user_text=text,
        business=business,
        customer_id=customer_id,
        channel=channel,
    )

    trigger = detect_button_trigger(text)
    buttons = get_business_buttons(business_id, trigger=trigger)

    save_inbox_message(
        business_id=business_id,
        platform=platform,
        customer_id=customer_id,
        channel=channel,
        direction="outbound",
        role="assistant",
        content=reply_text,
        external_message_id="",
        raw_payload={"buttons": buttons},
    )

    return {
        "reply": reply_text,
        "buttons": buttons,
    }


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

    access_token = business.get("access_token") or business.get("page_access_token")

    if not access_token:
        return

    result = await handle_customer_message(
        business=business,
        platform="instagram",
        customer_id=sender_id,
        channel="dm",
        text=message_text,
        external_message_id=message_id,
        raw_payload=messaging,
    )

    if result:
        send_dm(
            access_token=access_token,
            recipient_id=sender_id,
            text=result["reply"],
            business=business,
            buttons=result.get("buttons"),
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

    access_token = business.get("access_token") or business.get("page_access_token")

    if not access_token:
        return

    result = await handle_customer_message(
        business=business,
        platform="instagram",
        customer_id=commenter_id,
        channel="comment",
        text=comment_text,
        external_message_id=comment_id,
        raw_payload=change,
    )

    if result:
        reply_to_comment(
            access_token=access_token,
            comment_id=comment_id,
            text=result["reply"],
            business=business,
        )


@app.get("/")
async def home():
    return {
        "status": "ok",
        "version": "previous_working_plus_phase1_v1",
        "connect_instagram": "/connect-instagram",
        "connect_facebook": "/connect-facebook",
        "analytics_sync": "/analytics/sync",
        "debug_businesses": "/debug/businesses",
        "webhook": "/webhook",
    }


@app.head("/")
async def home_head():
    return PlainTextResponse("", status_code=200)


@app.api_route("/analytics/sync", methods=["GET", "POST"])
async def sync_instagram_analytics(
    request: Request,
    business_id: str = "",
    days: int = 30,
    limit: int = 25,
    dashboard_secret: str = "",
):
    if DASHBOARD_SECRET and dashboard_secret != DASHBOARD_SECRET:
        return JSONResponse(
            content={
                "status": "error",
                "message": "Invalid dashboard secret",
            },
            status_code=403,
        )

    business = get_business_by_id(business_id)

    if not business:
        return JSONResponse(
            content={
                "status": "error",
                "message": "Business not found",
                "business_id": business_id,
            },
            status_code=404,
        )

    if not business.get("analytics_enabled", True):
        return {
            "status": "disabled",
            "message": "Analytics disabled for this business",
        }

    ig_id = normalize_id(business.get("instagram_business_id"))
    access_token = business.get("access_token") or business.get("page_access_token")

    if not ig_id or not access_token:
        return JSONResponse(
            content={
                "status": "error",
                "message": "Missing Instagram Business ID or access token",
                "business": sanitize_business_row(business),
            },
            status_code=400,
        )

    basic = get_account_basic_metrics(ig_id, access_token)
    advanced = get_account_advanced_insights(ig_id, access_token, days=days)
    media = get_media_list(ig_id, access_token, limit=limit)

    followers_count = int(basic.get("followers_count") or 0)
    media_count = int(basic.get("media_count") or 0)

    upsert_daily_insight(
        business_id=business["id"],
        followers_count=followers_count,
        reach=int(advanced.get("reach") or 0),
        impressions=int(advanced.get("impressions") or 0),
        profile_views=int(advanced.get("profile_views") or 0),
        website_clicks=int(advanced.get("website_clicks") or 0),
    )

    saved_posts = 0
    post_debug = []

    for post in media.get("posts", []):
        media_id = normalize_id(post.get("id"))

        if not media_id:
            continue

        post_advanced = get_media_advanced_insights(media_id, access_token)

        try:
            upsert_post_insights(
                business_id=business["id"],
                post=post,
                followers_count=followers_count,
                advanced=post_advanced,
            )
            saved_posts += 1
        except Exception as e:
            print("Post upsert error:", str(e))
            post_debug.append({
                "media_id": media_id,
                "error": str(e),
            })

    try:
        supabase.table("businesses").update({
            "last_analytics_sync": datetime.now(timezone.utc).isoformat(),
        }).eq("id", business["id"]).execute()
    except Exception as e:
        print("Update last analytics sync error:", str(e))

    return {
        "status": "ok",
        "message": "Analytics synced",
        "business_id": business["id"],
        "instagram_business_id": ig_id,
        "username": basic.get("username"),
        "followers_count": followers_count,
        "media_count": media_count,
        "daily_insights": {
            "reach": advanced.get("reach", 0),
            "impressions": advanced.get("impressions", 0),
            "profile_views": advanced.get("profile_views", 0),
            "website_clicks": advanced.get("website_clicks", 0),
        },
        "posts_found": len(media.get("posts", [])),
        "posts_saved": saved_posts,
        "debug": {
            "account_basic_raw": basic.get("raw"),
            "account_advanced_raw": advanced.get("raw"),
            "media_raw_sample": media.get("raw"),
            "post_errors": post_debug[:5],
        },
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
                "page": {
                    "id": page.get("id"),
                    "name": page.get("name"),
                },
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


@app.get("/debug/inbox")
async def debug_inbox(business_id: str, limit: int = 50):
    result = safe_db_select(
        supabase.table("inbox_messages")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .limit(limit),
        fallback=[],
    )

    return {
        "count": len(result),
        "messages": result,
    }


@app.post("/dashboard/conversation/state")
async def dashboard_update_conversation_state(request: Request):
    data = await request.json()

    if DASHBOARD_SECRET and data.get("dashboard_secret") != DASHBOARD_SECRET:
        return JSONResponse(
            content={
                "status": "error",
                "message": "Invalid dashboard secret",
            },
            status_code=403,
        )

    business_id = data.get("business_id")
    platform = data.get("platform", "instagram")
    customer_id = data.get("customer_id")
    channel = data.get("channel", "dm")
    state = data.get("state", "AI_ACTIVE")

    if state not in ["AI_ACTIVE", "HUMAN_ACTIVE", "PAUSED"]:
        return JSONResponse(
            content={
                "status": "error",
                "message": "Invalid state",
            },
            status_code=400,
        )

    safe_db_upsert(
        "conversations",
        {
            "business_id": business_id,
            "platform": platform,
            "customer_id": customer_id,
            "channel": channel,
            "state": state,
            "updated_at": now_iso(),
            "last_message_at": now_iso(),
        },
        on_conflict="business_id,platform,customer_id,channel",
    )

    return {
        "status": "ok",
        "state": state,
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
        "Privacy Policy: This app collects Instagram messages, comments, and analytics data to provide automated AI replies, inbox tools, buttons, human takeover, and business dashboard analytics."
    )


@app.get("/terms")
async def terms():
    return PlainTextResponse(
        "Terms of Service: This app provides automated Instagram replies, inbox tools, buttons, human takeover, and analytics dashboard tools using AI."
    )
