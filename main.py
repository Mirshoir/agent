import os
import time
import secrets
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse, RedirectResponse
from supabase import create_client

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "1234")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")
DEFAULT_MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
DEFAULT_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0")
GRAPH_FACEBOOK = f"https://graph.facebook.com/{GRAPH_VERSION}"
GRAPH_INSTAGRAM = f"https://graph.instagram.com/{GRAPH_VERSION}"
FACEBOOK_REDIRECT_URI = os.getenv("FACEBOOK_REDIRECT_URI", "https://agent-1-xi6h.onrender.com/auth/facebook/callback")
INSTAGRAM_REDIRECT_URI = os.getenv("INSTAGRAM_REDIRECT_URI", "https://agent-1-xi6h.onrender.com/auth/instagram/callback")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://instaagent.streamlit.app")
MAX_MEMORY_MESSAGES = 12
DEDUP_TTL_SECONDS = 3600

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing Supabase env vars")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
processed_message_ids = {}
processed_comment_ids = {}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_id(value) -> str:
    return str(value or "").strip()


def safe_token(token: str) -> str:
    token = str(token or "")
    if not token:
        return ""
    return token[:10] + "..." + token[-6:] if len(token) > 18 else token[:4] + "..."


def cleanup_dedup_cache():
    now = time.time()
    for cache in (processed_message_ids, processed_comment_ids):
        for key in [k for k, v in cache.items() if now - v > DEDUP_TTL_SECONDS]:
            cache.pop(key, None)


def already_processed(cache: dict, event_id: str) -> bool:
    if not event_id:
        return False
    cleanup_dedup_cache()
    if event_id in cache:
        return True
    cache[event_id] = time.time()
    return False


def safe_insert(table: str, data: dict):
    try:
        return supabase.table(table).insert(data).execute()
    except Exception as e:
        print(f"{table} insert error:", e)
        return None


def safe_upsert(table: str, data: dict, on_conflict: str = ""):
    try:
        q = supabase.table(table).upsert(data, on_conflict=on_conflict) if on_conflict else supabase.table(table).upsert(data)
        return q.execute()
    except Exception as e:
        print(f"{table} upsert error:", e)
        return None


def get_business_by_id(business_id: str):
    res = supabase.table("businesses").select("*").eq("id", business_id).limit(1).execute()
    return res.data[0] if res.data else None


def get_business(instagram_business_id: str):
    iid = normalize_id(instagram_business_id)
    if not iid:
        return None
    res = supabase.table("businesses").select("*").eq("instagram_business_id", iid).limit(1).execute()
    return res.data[0] if res.data else None


def get_business_by_page_id(page_id: str):
    pid = normalize_id(page_id)
    if not pid:
        return None
    res = supabase.table("businesses").select("*").eq("facebook_page_id", pid).limit(1).execute()
    return res.data[0] if res.data else None


def find_business_for_webhook(entry_id: str, recipient_id: str = ""):
    return (
        get_business(entry_id)
        or get_business_by_page_id(entry_id)
        or get_business(recipient_id)
        or get_business_by_page_id(recipient_id)
    )


def sanitize_business_row(row: dict):
    clean = dict(row or {})
    for key in ["access_token", "page_access_token", "mistral_api_key", "openai_api_key", "gemini_api_key", "anthropic_api_key", "whatsapp_access_token"]:
        clean[key] = safe_token(clean.get(key, ""))
    return clean


def get_business_model(business: dict):
    provider = (business.get("ai_provider") or "mistral").lower().strip()
    model = (business.get("ai_model") or "").strip()
    if provider == "openai":
        return "openai", model or "gpt-4o-mini", (business.get("openai_api_key") or DEFAULT_OPENAI_API_KEY or "").strip()
    return "mistral", model or "mistral-small-latest", (business.get("mistral_api_key") or DEFAULT_MISTRAL_API_KEY or "").strip()


def get_chat_memory(business_id: str, customer_id: str, channel: str, limit: int):
    try:
        res = (
            supabase.table("chat_memory")
            .select("role,content,created_at")
            .eq("business_id", business_id)
            .eq("customer_id", customer_id)
            .eq("channel", channel)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = res.data or []
        rows.reverse()
        return [{"role": r["role"], "content": r["content"]} for r in rows if r.get("role") in ["user", "assistant"] and r.get("content")]
    except Exception as e:
        print("memory read error:", e)
        return []


def save_chat_message(business_id: str, customer_id: str, channel: str, role: str, content: str):
    if business_id and customer_id and role in ["user", "assistant"] and content:
        safe_insert("chat_memory", {"business_id": business_id, "customer_id": customer_id, "channel": channel, "role": role, "content": content[:4000]})


def get_memory_limit(business: dict) -> int:
    try:
        return max(2, min(int(business.get("memory_limit") or MAX_MEMORY_MESSAGES), 30))
    except Exception:
        return MAX_MEMORY_MESSAGES


def upsert_customer(business_id: str, platform: str, customer_id: str, name: str = ""):
    safe_upsert("customers", {
        "business_id": business_id,
        "platform": platform,
        "customer_id": customer_id,
        "display_name": name or customer_id,
        "status": "new",
        "last_seen_at": now_iso(),
        "updated_at": now_iso(),
    }, on_conflict="business_id,platform,customer_id")


def get_conversation_state(business_id: str, platform: str, customer_id: str, channel: str) -> str:
    try:
        res = (
            supabase.table("conversations")
            .select("state")
            .eq("business_id", business_id)
            .eq("platform", platform)
            .eq("customer_id", customer_id)
            .eq("channel", channel)
            .limit(1)
            .execute()
        )
        return (res.data[0].get("state") if res.data else "AI_ACTIVE") or "AI_ACTIVE"
    except Exception as e:
        print("conversation state read error:", e)
        return "AI_ACTIVE"


def upsert_conversation(business_id: str, platform: str, customer_id: str, channel: str, state: str = "AI_ACTIVE"):
    existing_state = get_conversation_state(business_id, platform, customer_id, channel)
    safe_upsert("conversations", {
        "business_id": business_id,
        "platform": platform,
        "customer_id": customer_id,
        "channel": channel,
        "state": existing_state or state,
        "last_message_at": now_iso(),
        "updated_at": now_iso(),
    }, on_conflict="business_id,platform,customer_id,channel")


def save_inbox_message(business_id: str, platform: str, customer_id: str, channel: str, direction: str, role: str, content: str, external_message_id: str = "", raw_payload: Optional[dict] = None):
    if business_id and customer_id and content:
        safe_insert("inbox_messages", {
            "business_id": business_id,
            "platform": platform,
            "customer_id": customer_id,
            "channel": channel,
            "direction": direction,
            "role": role,
            "content": content[:4000],
            "external_message_id": external_message_id or "",
            "raw_payload": raw_payload or {},
        })


def detect_button_trigger(text: str) -> str:
    t = (text or "").lower()
    if any(x in t for x in ["catalog", "katalog", "каталог", "price", "narx", "цена", "прайс", "nechpul"]):
        return "catalog"
    if any(x in t for x in ["optom", "оптом", "wholesale", "сотруд", "sotrud"]):
        return "wholesale"
    if any(x in t for x in ["delivery", "dostavka", "доставка", "yetkaz"]):
        return "delivery"
    if any(x in t for x in ["phone", "call", "tel", "номер", "aloqa", "связ"]):
        return "contact"
    return "default"


def get_business_buttons(business_id: str, trigger: str = "default") -> List[dict]:
    try:
        res = (
            supabase.table("business_buttons")
            .select("*")
            .eq("business_id", business_id)
            .eq("is_active", True)
            .or_(f"trigger.eq.{trigger},trigger.eq.default")
            .order("sort_order")
            .limit(4)
            .execute()
        )
        return res.data or []
    except Exception as e:
        print("buttons read error:", e)
        return []


def build_business_context(business: dict) -> str:
    return f"""
Business name: {business.get('business_name','')}
Business type: {business.get('business_type','')}
Bot language mode: {business.get('bot_language_mode','auto')}
Tone: {business.get('tone','')}
Products / Services: {business.get('products','')}
Prices: {business.get('prices','')}
Delivery information: {business.get('delivery_info','')}
Working hours: {business.get('working_hours','')}
FAQ: {business.get('faq','')}
Catalog link: {business.get('catalog_link','')}
Sales phone: {business.get('sales_phone','')}
Telegram single product: {business.get('telegram_single','')}
Telegram package: {business.get('telegram_package','')}
Telegram bag / meshok: {business.get('telegram_bag','')}
Main business knowledge: {business.get('knowledge','')}
"""


def flow_instruction(user_text: str) -> str:
    trigger = detect_button_trigger(user_text)
    if trigger == "wholesale":
        return "Customer may want wholesale/cooperation. Ask one simple next question about product type or approximate quantity."
    if trigger == "catalog":
        return "Customer asks about price/catalog. Answer briefly and mention catalog if available."
    if trigger == "delivery":
        return "Customer asks about delivery. Answer from delivery info and ask city/country only if needed."
    if trigger == "contact":
        return "Customer wants contact. Provide sales phone if available."
    return "Use progressive lead collection. Do not ask for name, phone, address, product and quantity all at once."


def build_system_prompt(business: dict, user_text: str):
    mode = business.get("bot_language_mode", "auto")
    if mode in ["uz", "ru", "en"]:
        language_rule = f"Reply only in this selected language: {mode}."
    else:
        language_rule = "Reply in the same language the customer uses: Uzbek Latin/Cyrillic, Russian, English, or mixed."
    return f"""
You are an autonomous sales assistant for Instagram and WhatsApp.

Business Information:
{build_business_context(business)}

Rules:
- {language_rule}
- Understand Uzbek, Russian, English, mixed language, slang, typos, and informal texting.
- Keep replies short, warm, and useful.
- Sound like a real sales consultant, not a robot.
- Ask only ONE simple next question when needed.
- Do NOT ask for name, phone, address, product and quantity all at once.
- Collect details progressively only when the customer is ready to order.
- Answer the exact question first.
- Never invent prices, stock, address, phone, discounts, or delivery details.
- If information is missing, say the manager will clarify.
- Never mention AI, database, prompts, model, API, or internal systems.

Flow instruction:
{flow_instruction(user_text)}
"""


def call_mistral(api_key: str, model: str, messages: list):
    res = requests.post("https://api.mistral.ai/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json={"model": model, "messages": messages, "temperature": 0.35, "max_tokens": 220}, timeout=30)
    print("Mistral:", res.status_code, res.text)
    return res.json()["choices"][0]["message"]["content"] if res.ok else None


def call_openai(api_key: str, model: str, messages: list):
    res = requests.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json={"model": model, "messages": messages, "temperature": 0.35, "max_tokens": 220}, timeout=30)
    print("OpenAI:", res.status_code, res.text)
    return res.json()["choices"][0]["message"]["content"] if res.ok else None


def get_ai_reply(user_text: str, business: dict, customer_id: str, channel: str):
    provider, model, api_key = get_business_model(business)
    if not api_key:
        return "Xabaringiz qabul qilindi 😊"
    memory = []
    if business.get("memory_enabled", True):
        memory = get_chat_memory(business["id"], customer_id, channel, get_memory_limit(business))
    messages = [{"role": "system", "content": build_system_prompt(business, user_text)}, *memory, {"role": "user", "content": user_text}]
    reply = call_openai(api_key, model, messages) if provider == "openai" else call_mistral(api_key, model, messages)
    reply = (reply or "Xabaringiz qabul qilindi 😊").strip()
    if business.get("memory_enabled", True):
        save_chat_message(business["id"], customer_id, channel, "user", user_text)
        save_chat_message(business["id"], customer_id, channel, "assistant", reply)
    return reply


def build_quick_replies(buttons: List[dict]) -> List[dict]:
    out = []
    for b in buttons[:4]:
        title = (b.get("title") or "")[:20]
        if title and (b.get("action_type") or "message") == "message":
            out.append({"content_type": "text", "title": title, "payload": f"BTN::{b.get('id', title)}::{b.get('action_value') or title}"[:1000]})
    return out


def format_buttons_text(buttons: List[dict]) -> str:
    lines = []
    for b in buttons[:4]:
        title = b.get("title") or "Button"
        value = b.get("action_value") or ""
        if b.get("action_type") in ["url", "phone"] and value:
            lines.append(f"{title}: {value}")
        else:
            lines.append(f"• {title}")
    return "\n\n" + "\n".join(lines) if lines else ""


def send_instagram_dm(access_token: str, recipient_id: str, text: str, business: dict, buttons: Optional[List[dict]] = None):
    url = f"{GRAPH_FACEBOOK}/me/messages" if business.get("oauth_provider") == "facebook_page" else f"{GRAPH_INSTAGRAM}/me/messages"
    message = {"text": text[:1000]}
    quick_replies = build_quick_replies(buttons or [])
    if quick_replies:
        message["quick_replies"] = quick_replies
    res = requests.post(url, params={"access_token": access_token}, json={"recipient": {"id": recipient_id}, "message": message}, timeout=30)
    print("DM:", res.status_code, res.text)
    if not res.ok and buttons:
        fallback = (text + format_buttons_text(buttons))[:1000]
        res = requests.post(url, params={"access_token": access_token}, json={"recipient": {"id": recipient_id}, "message": {"text": fallback}}, timeout=30)
        print("DM fallback:", res.status_code, res.text)
    return res


def reply_to_comment(access_token: str, comment_id: str, text: str, business: dict):
    url = f"{GRAPH_FACEBOOK}/{comment_id}/replies" if business.get("oauth_provider") == "facebook_page" else f"{GRAPH_INSTAGRAM}/{comment_id}/replies"
    res = requests.post(url, params={"access_token": access_token, "message": text[:1000]}, timeout=30)
    print("comment reply:", res.status_code, res.text)
    return res


async def handle_customer_message(business: dict, platform: str, customer_id: str, channel: str, text: str, external_message_id: str = "", raw_payload: Optional[dict] = None):
    business_id = business["id"]
    upsert_customer(business_id, platform, customer_id)
    upsert_conversation(business_id, platform, customer_id, channel)
    save_inbox_message(business_id, platform, customer_id, channel, "inbound", "customer", text, external_message_id, raw_payload)

    state = get_conversation_state(business_id, platform, customer_id, channel)
    if state in ["HUMAN_ACTIVE", "PAUSED"] or not business.get("bot_enabled", True):
        return None
    if channel == "dm" and business.get("auto_reply_dms") is False:
        return None
    if channel == "comment" and business.get("auto_reply_comments") is False:
        return None

    reply = get_ai_reply(text, business, customer_id, channel)
    buttons = get_business_buttons(business_id, detect_button_trigger(text))
    save_inbox_message(business_id, platform, customer_id, channel, "outbound", "assistant", reply, "", {"buttons": buttons})
    return {"reply": reply, "buttons": buttons}


async def process_messaging_event(entry_id: str, messaging: dict):
    if "read" in messaging or "delivery" in messaging:
        return
    message = messaging.get("message") or {}
    if message.get("is_echo"):
        return
    sender_id = normalize_id(messaging.get("sender", {}).get("id"))
    recipient_id = normalize_id(messaging.get("recipient", {}).get("id"))
    text = message.get("text") or ""
    mid = message.get("mid") or ""
    if not sender_id or not recipient_id or not text or already_processed(processed_message_ids, mid):
        return
    business = find_business_for_webhook(entry_id, recipient_id)
    if not business:
        return
    access_token = business.get("access_token") or business.get("page_access_token")
    result = await handle_customer_message(business, "instagram", sender_id, "dm", text, mid, messaging)
    if result and access_token:
        send_instagram_dm(access_token, sender_id, result["reply"], business, result.get("buttons"))


async def process_comment_event(entry_id: str, change: dict):
    value = change.get("value", {})
    comment_id = normalize_id(value.get("comment_id") or value.get("id"))
    text = value.get("message") or value.get("text") or ""
    commenter_id = normalize_id(value.get("from", {}).get("id") or value.get("sender", {}).get("id") or value.get("user_id") or comment_id)
    if not comment_id or not text or already_processed(processed_comment_ids, comment_id):
        return
    business = find_business_for_webhook(entry_id)
    if not business:
        return
    access_token = business.get("access_token") or business.get("page_access_token")
    result = await handle_customer_message(business, "instagram", commenter_id, "comment", text, comment_id, change)
    if result and access_token:
        reply_to_comment(access_token, comment_id, result["reply"], business)


@app.get("/")
async def home():
    return {"status": "ok", "version": "ai_sales_os_phase1_buttons_inbox_v1", "connect_facebook": "/connect-facebook", "webhook": "/webhook"}


@app.get("/connect-facebook")
async def connect_facebook():
    params = {"client_id": META_APP_ID, "redirect_uri": FACEBOOK_REDIRECT_URI, "scope": ",".join(["pages_show_list", "pages_read_engagement", "pages_manage_metadata", "pages_messaging", "instagram_basic", "instagram_manage_messages", "instagram_manage_comments", "instagram_manage_insights"]), "response_type": "code", "state": secrets.token_urlsafe(16)}
    return RedirectResponse(f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urlencode(params))


def exchange_facebook_code_for_token(code: str):
    res = requests.get(f"{GRAPH_FACEBOOK}/oauth/access_token", params={"client_id": META_APP_ID, "client_secret": META_APP_SECRET, "redirect_uri": FACEBOOK_REDIRECT_URI, "code": code}, timeout=30)
    print("FB token:", res.status_code, res.text)
    res.raise_for_status()
    return res.json()["access_token"]


def exchange_for_long_lived_facebook_token(short_token: str):
    try:
        res = requests.get(f"{GRAPH_FACEBOOK}/oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": META_APP_ID, "client_secret": META_APP_SECRET, "fb_exchange_token": short_token}, timeout=30)
        if res.ok and res.json().get("access_token"):
            return res.json()["access_token"]
    except Exception as e:
        print("long token error:", e)
    return short_token


def get_facebook_pages(user_access_token: str):
    res = requests.get(f"{GRAPH_FACEBOOK}/me/accounts", params={"fields": "id,name,access_token,connected_instagram_account,instagram_business_account{id,username,name}", "access_token": user_access_token}, timeout=30)
    print("pages:", res.status_code, res.text)
    res.raise_for_status()
    return res.json().get("data", [])


def get_page_instagram_account(page: dict):
    return page.get("instagram_business_account") or page.get("connected_instagram_account") or {}


def subscribe_page_to_webhooks(page_id: str, page_access_token: str):
    try:
        res = requests.post(f"{GRAPH_FACEBOOK}/{page_id}/subscribed_apps", params={"access_token": page_access_token, "subscribed_fields": "messages,messaging_postbacks,feed"}, timeout=30)
        return res.json()
    except Exception as e:
        return {"error": str(e)}


def upsert_business(instagram_business_id: str, username: str, access_token: str, oauth_provider: str, facebook_page_id: str = "", facebook_page_name: str = ""):
    instagram_business_id = normalize_id(instagram_business_id)
    existing = get_business(instagram_business_id)
    update_data = {"instagram_business_id": instagram_business_id, "business_name": username, "access_token": access_token, "oauth_provider": oauth_provider, "facebook_page_id": facebook_page_id, "facebook_page_name": facebook_page_name, "bot_enabled": True, "automation_mode": "FULL_AUTO", "auto_reply_dms": True, "auto_reply_comments": True}
    if existing:
        return supabase.table("businesses").update(update_data).eq("id", existing["id"]).execute().data
    insert_data = {**update_data, "business_type": "Instagram Business", "language": "uz", "dashboard_language": "en", "bot_language_mode": "auto", "tone": "friendly, polite, sales-focused", "knowledge": "", "products": "", "prices": "", "delivery_info": "", "working_hours": "", "faq": "", "catalog_link": "", "sales_phone": "", "telegram_single": "", "telegram_package": "", "telegram_bag": "", "ai_provider": "mistral", "ai_model": "mistral-small-latest", "mistral_api_key": "", "openai_api_key": "", "memory_enabled": True, "memory_limit": MAX_MEMORY_MESSAGES, "analytics_enabled": True}
    return supabase.table("businesses").upsert(insert_data, on_conflict="instagram_business_id").execute().data


@app.get("/auth/facebook/callback")
async def facebook_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return PlainTextResponse("Missing Facebook code", status_code=400)
    try:
        user_token = exchange_for_long_lived_facebook_token(exchange_facebook_code_for_token(code))
        pages = get_facebook_pages(user_token)
        connected = []
        for page in pages:
            ig = get_page_instagram_account(page)
            if not ig or not ig.get("id"):
                continue
            ig_id = normalize_id(ig.get("id"))
            username = ig.get("username") or ig.get("name") or f"instagram_{ig_id}"
            upsert_business(ig_id, username, page.get("access_token"), "facebook_page", page.get("id"), page.get("name"))
            connected.append({"page": page.get("name"), "instagram": username, "subscription": subscribe_page_to_webhooks(page.get("id"), page.get("access_token"))})
        if not connected:
            return PlainTextResponse("No Instagram returned from Meta API.", status_code=400)
        return RedirectResponse(f"{DASHBOARD_URL}?connected=success")
    except Exception as e:
        return PlainTextResponse(f"Facebook OAuth error: {str(e)}", status_code=500)


@app.get("/connect-instagram")
async def connect_instagram():
    params = {"client_id": META_APP_ID, "redirect_uri": INSTAGRAM_REDIRECT_URI, "scope": ",".join(["instagram_business_basic", "instagram_business_manage_messages", "instagram_business_manage_comments"]), "response_type": "code", "state": secrets.token_urlsafe(16)}
    return RedirectResponse("https://www.instagram.com/oauth/authorize?" + urlencode(params))


@app.get("/auth/instagram/callback")
async def instagram_callback(request: Request):
    return PlainTextResponse("Please use Facebook Login connection for full messaging/analytics support: /connect-facebook", status_code=400)


@app.post("/dashboard/conversation/state")
async def dashboard_update_conversation_state(request: Request):
    data = await request.json()
    if DASHBOARD_SECRET and data.get("dashboard_secret") != DASHBOARD_SECRET:
        return JSONResponse({"status": "error", "message": "Invalid dashboard secret"}, status_code=403)
    state = data.get("state", "AI_ACTIVE")
    if state not in ["AI_ACTIVE", "HUMAN_ACTIVE", "PAUSED"]:
        return JSONResponse({"status": "error", "message": "Invalid state"}, status_code=400)
    safe_upsert("conversations", {"business_id": data.get("business_id"), "platform": data.get("platform", "instagram"), "customer_id": data.get("customer_id"), "channel": data.get("channel", "dm"), "state": state, "updated_at": now_iso()}, on_conflict="business_id,platform,customer_id,channel")
    return {"status": "ok", "state": state}


@app.get("/debug/businesses")
async def debug_businesses():
    res = supabase.table("businesses").select("*").order("created_at", desc=True).execute()
    return {"count": len(res.data or []), "businesses": [sanitize_business_row(r) for r in (res.data or [])]}


@app.get("/debug/inbox")
async def debug_inbox(business_id: str, limit: int = 50):
    res = supabase.table("inbox_messages").select("*").eq("business_id", business_id).order("created_at", desc=True).limit(limit).execute()
    return {"count": len(res.data or []), "messages": res.data or []}


@app.get("/webhook")
async def verify_webhook(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == VERIFY_TOKEN and p.get("hub.challenge"):
        return PlainTextResponse(p.get("hub.challenge"), status_code=200)
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
                if field in ["comments", "feed"]:
                    await process_comment_event(entry_id, change)
                elif field == "messages":
                    value = change.get("value", {})
                    await process_messaging_event(entry_id, {"sender": value.get("sender", {}), "recipient": value.get("recipient", {}), "timestamp": value.get("timestamp"), "message": value.get("message", {})})
        return JSONResponse({"status": "ok"})
    except Exception as e:
        print("Webhook error:", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/privacy")
async def privacy():
    return PlainTextResponse("Privacy Policy: This app processes Instagram/WhatsApp messages, comments, and business data to provide AI sales automation.")


@app.get("/terms")
async def terms():
    return PlainTextResponse("Terms of Service: This app provides automated Instagram/WhatsApp replies, inbox, and business dashboard tools.")
