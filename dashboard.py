import os
import hmac
import time
import html
import hashlib
import requests
import streamlit as st
import base64
from dotenv import load_dotenv
from supabase import create_client
from io import BytesIO

load_dotenv()

st.set_page_config(
    page_title="Milana Premium Sales Dashboard",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

* {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

:root {
    --primary: #6366f1;
    --primary-light: #818cf8;
    --primary-dark: #4f46e5;
    --secondary: #8b5cf6;
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --info: #0ea5e9;
    --dark: #1f2937;
    --light: #f9fafb;
    --border: #e5e7eb;
    --text-primary: #111827;
    --text-secondary: #6b7280;
}

html, body, [data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #f9fafb 0%, #f3f4f6 100%);
}

/* Main Header */
.main-header {
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
    border-radius: 16px;
    padding: 40px;
    color: white;
    margin-bottom: 32px;
    position: relative;
    overflow: hidden;
    box-shadow: 0 20px 40px rgba(99, 102, 241, 0.2);
}

.main-header::before {
    content: '';
    position: absolute;
    top: -50%;
    right: -10%;
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.1) 0%, transparent 70%);
    border-radius: 50%;
}

.main-header h1 {
    font-size: 42px;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin: 0;
    position: relative;
    z-index: 1;
}

.main-header p {
    margin: 12px 0 0 0;
    opacity: 0.95;
    font-size: 16px;
    position: relative;
    z-index: 1;
    font-weight: 300;
}

/* Stat Card */
.stat-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    transition: all 0.3s ease;
}

.stat-card:hover {
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
    border-color: var(--primary);
    transform: translateY(-4px);
}

.stat-value {
    font-size: 42px;
    font-weight: 800;
    color: var(--primary);
    letter-spacing: -0.02em;
    margin: 0;
}

.stat-label {
    color: var(--text-secondary);
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-top: 12px;
}

/* Chat Container */
.chat-container {
    background: white;
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    height: 100%;
    display: flex;
    flex-direction: column;
}

.chat-header {
    border-bottom: 1px solid var(--border);
    padding: 20px 24px;
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(139, 92, 246, 0.05) 100%);
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.chat-header-info {
    display: flex;
    align-items: center;
    gap: 16px;
}

.chat-avatar {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 16px;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.chat-meta {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.chat-name {
    font-weight: 600;
    color: var(--text-primary);
    font-size: 15px;
    margin: 0;
}

.chat-info {
    color: var(--text-secondary);
    font-size: 12px;
    margin: 0;
}

.platform-badge {
    display: inline-block;
    padding: 6px 12px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.badge-telegram {
    background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(59, 130, 246, 0.1));
    color: #0ea5e9;
}

.badge-instagram {
    background: linear-gradient(135deg, rgba(236, 72, 153, 0.1), rgba(139, 92, 246, 0.1));
    color: #ec4899;
}

/* Messages Area */
.messages-area {
    flex: 1;
    overflow-y: auto;
    padding: 16px 24px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: white;
}

.message {
    display: flex;
    gap: 12px;
    animation: slideIn 0.3s ease-out;
    width: 100%;
    margin-bottom: 8px;
}

.message.outbound {
    justify-content: flex-end;
}

.message-bubble {
    max-width: 75%;
    padding: 12px 16px;
    border-radius: 12px;
    word-wrap: break-word;
    font-size: 14px;
    line-height: 1.5;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.message.inbound .message-bubble {
    background: var(--light);
    border: 1px solid var(--border);
    color: var(--text-primary);
    border-radius: 12px 12px 12px 2px;
}

.message.outbound .message-bubble {
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
    color: white;
    border-radius: 12px 12px 2px 12px;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.message-media {
    max-width: 100%;
    max-height: 350px;
    border-radius: 8px;
    object-fit: cover;
    border: none;
}

.message-text {
    word-wrap: break-word;
    white-space: pre-wrap;
}

.message-time {
    font-size: 11px;
    opacity: 0.7;
    margin-top: 4px;
}

@keyframes slideIn {
    from {
        opacity: 0;
        transform: translateY(12px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* Input Area */
.input-area {
    border-top: 1px solid var(--border);
    padding: 20px 24px;
    background: white;
}

.input-section {
    display: flex;
    gap: 12px;
    margin-bottom: 12px;
}

.stTextArea textarea,
.stTextInput input,
.stSelectbox select {
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    font-size: 14px !important;
    transition: all 0.2s ease !important;
}

.stTextArea textarea:focus,
.stTextInput input:focus,
.stSelectbox select:focus {
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1) !important;
}

/* Buttons */
.stButton button {
    border-radius: 8px;
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0.05em;
    padding: 10px 20px !important;
    border: none;
    transition: all 0.3s ease;
    text-transform: uppercase;
}

.stButton button[kind="primary"] {
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%) !important;
    color: white !important;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.stButton button[kind="primary"]:hover {
    box-shadow: 0 8px 24px rgba(99, 102, 241, 0.4);
    transform: translateY(-2px);
}

.stButton button[kind="secondary"] {
    background: var(--light) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border) !important;
}

.stButton button[kind="secondary"]:hover {
    background: white !important;
    border-color: var(--primary) !important;
}

/* Conversation List */
.conversation-item {
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 10px;
    background: white;
    cursor: pointer;
    transition: all 0.2s ease;
}

.conversation-item:hover {
    border-color: var(--primary);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    transform: translateX(4px);
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.02) 0%, rgba(139, 92, 246, 0.02) 100%);
}

.conversation-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.conversation-name {
    font-weight: 600;
    color: var(--text-primary);
    font-size: 14px;
}

.conversation-unread {
    background: var(--danger);
    color: white;
    border-radius: 50%;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
}

.conversation-preview {
    color: var(--text-secondary);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: white;
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] > div:first-child {
    padding: 28px 20px;
}

/* Divider */
.stDivider {
    border-color: var(--border) !important;
    margin: 24px 0;
}

/* Login Card */
.login-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 48px 40px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    backdrop-filter: blur(10px);
}

.login-card h1 {
    font-size: 48px;
    font-weight: 800;
    letter-spacing: -0.03em;
    margin: 0 0 16px 0;
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.login-card h3 {
    font-size: 24px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0 0 8px 0;
}

.login-card p {
    color: var(--text-secondary);
    margin: 0;
    font-size: 15px;
    font-weight: 300;
}

/* Success/Error Messages */
.stSuccess {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(52, 211, 153, 0.1));
    border: 1px solid rgba(16, 185, 129, 0.3);
    border-radius: 8px;
    padding: 14px 16px;
}

.stError {
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.1), rgba(248, 113, 113, 0.1));
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 8px;
    padding: 14px 16px;
}

.stWarning {
    background: linear-gradient(135deg, rgba(245, 158, 11, 0.1), rgba(251, 191, 36, 0.1));
    border: 1px solid rgba(245, 158, 11, 0.3);
    border-radius: 8px;
    padding: 14px 16px;
}

.stInfo {
    background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(59, 130, 246, 0.1));
    border: 1px solid rgba(14, 165, 233, 0.3);
    border-radius: 8px;
    padding: 14px 16px;
}

/* Headings */
h1, h2, h3 {
    color: var(--text-primary);
    letter-spacing: -0.01em;
}

h1 { font-size: 32px; font-weight: 800; }
h2 { font-size: 24px; font-weight: 700; }
h3 { font-size: 18px; font-weight: 700; }

/* Text */
p, span {
    color: var(--text-secondary);
    line-height: 1.6;
}

/* Scrollbar */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: var(--light);
}

::-webkit-scrollbar-thumb {
    background: var(--primary);
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--primary-dark);
}

/* Expanders */
.streamlit-expanderHeader {
    border-radius: 8px;
    border: 1px solid var(--border) !important;
    padding: 12px 16px !important;
    background: white !important;
    font-weight: 600;
}

.streamlit-expanderHeader:hover {
    background: var(--light) !important;
}

/* Toggle/Checkbox */
.stCheckbox > label {
    font-weight: 500;
    color: var(--text-primary);
}

/* Forms */
.stForm {
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    background: white;
}

/* Media Upload */
.stFileUploader {
    border: 2px dashed var(--primary) !important;
    border-radius: 12px !important;
    padding: 20px !important;
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(139, 92, 246, 0.05) 100%) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 12px 24px;
}

.stTabs [aria-selected="true"] [data-baseweb="tab"] {
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
    color: white;
}
</style>
""", unsafe_allow_html=True)


def get_secret(key, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = get_secret("SUPABASE_SERVICE_KEY")
BACKEND_URL = get_secret("BACKEND_URL", "https://agent-1-xi6h.onrender.com").rstrip("/")
PUBLIC_BASE_URL = get_secret("PUBLIC_BASE_URL", BACKEND_URL).rstrip("/")
ADMIN_EMAIL = get_secret("ADMIN_EMAIL", "")
DASHBOARD_SECRET = get_secret("DASHBOARD_SECRET")
TELEGRAM_BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = get_secret("TELEGRAM_BOT_USERNAME", "")

if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY, ADMIN_EMAIL, DASHBOARD_SECRET]):
    st.error("❌ Missing SUPABASE_URL, SUPABASE_SERVICE_KEY, ADMIN_EMAIL, or DASHBOARD_SECRET.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

DEFAULT_AI_REPLY_RULES = """- Keep answers short and comfortable.
- Usually 1-3 short sentences.
- Do not send catalog automatically.
- Send catalog only if customer asks for catalog, prices, models, collection, or photos.
- If customer only greets, greet back and ask what they need.
- Do not overload customer with too much information.
- Sound natural like a real Milana Premium sales manager."""


def normalize_email(email):
    return str(email or "").strip().lower()


def hash_password(password):
    return hashlib.sha256((password + DASHBOARD_SECRET).encode()).hexdigest()


def verify_password(password, password_hash):
    if not password or not password_hash:
        return False
    return hmac.compare_digest(hash_password(password), password_hash)


def login_user(email, password):
    result = (
        supabase.table("dashboard_users")
        .select("*")
        .eq("email", normalize_email(email))
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    users = result.data or []
    if not users:
        return None
    user = users[0]
    if not verify_password(password, user.get("password_hash", "")):
        return None
    return user


def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def get_all_businesses():
    return (
        supabase.table("businesses")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )


def get_user_businesses(user_email):
    links = (
        supabase.table("business_users")
        .select("business_id, role")
        .eq("user_email", normalize_email(user_email))
        .execute()
        .data
        or []
    )

    if not links:
        return []

    business_ids = [x["business_id"] for x in links if x.get("business_id")]
    role_map = {x["business_id"]: x.get("role", "owner") for x in links}

    businesses = (
        supabase.table("businesses")
        .select("*")
        .in_("id", business_ids)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )

    for b in businesses:
        b["user_role"] = role_map.get(b["id"], "owner")

    return businesses


def get_allowed_businesses():
    return get_all_businesses() if is_admin else get_user_businesses(user_email)


def update_business(business_id, data):
    return supabase.table("businesses").update(data).eq("id", business_id).execute()


def safe_update_business(business, data):
    existing_keys = set(business.keys())
    filtered = {k: v for k, v in data.items() if k in existing_keys}
    if not filtered:
        return None
    return update_business(business["id"], filtered)


def create_business(data):
    return supabase.table("businesses").insert(data).execute()


def get_all_dashboard_users():
    return (
        supabase.table("dashboard_users")
        .select("id,email,is_active,created_at")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )


def create_or_update_dashboard_user(email, password):
    data = {
        "email": normalize_email(email),
        "password_hash": hash_password(password),
        "is_active": True,
    }
    return supabase.table("dashboard_users").upsert(data, on_conflict="email").execute()


def get_business_assignments():
    return (
        supabase.table("business_users")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )


def assign_business_to_user(email, business_id, role):
    data = {
        "user_email": normalize_email(email),
        "business_id": business_id,
        "role": role,
    }
    return supabase.table("business_users").upsert(data, on_conflict="user_email,business_id").execute()


def remove_business_assignment(email, business_id):
    return (
        supabase.table("business_users")
        .delete()
        .eq("user_email", normalize_email(email))
        .eq("business_id", business_id)
        .execute()
    )


def get_message_count(platform=None):
    try:
        q = supabase.table("inbox_messages").select("id", count="exact")
        if platform:
            q = q.eq("platform", platform)
        result = q.execute()
        return result.count or 0
    except Exception:
        return 0


def get_chat_ai_enabled(business_id, platform, channel, customer_id):
    try:
        result = (
            supabase.table("chat_ai_settings")
            .select("ai_enabled")
            .eq("business_id", business_id)
            .eq("platform", platform)
            .eq("channel", channel or "")
            .eq("customer_id", str(customer_id))
            .limit(1)
            .execute()
        )

        rows = result.data or []
        if not rows:
            return True

        return bool(rows[0].get("ai_enabled", True))
    except Exception:
        return True


def set_chat_ai_enabled(business_id, platform, channel, customer_id, enabled):
    data = {
        "business_id": business_id,
        "platform": platform,
        "channel": channel or "",
        "customer_id": str(customer_id),
        "ai_enabled": bool(enabled),
        "updated_at": "now()",
    }

    try:
        return (
            supabase.table("chat_ai_settings")
            .upsert(data, on_conflict="business_id,platform,channel,customer_id")
            .execute()
        )
    except Exception:
        data.pop("updated_at", None)
        return (
            supabase.table("chat_ai_settings")
            .upsert(data, on_conflict="business_id,platform,channel,customer_id")
            .execute()
        )


def telegram_webhook_url():
    return f"{PUBLIC_BASE_URL}/webhook/telegram"


def set_telegram_webhook():
    if not TELEGRAM_BOT_TOKEN:
        return False, {"error": "TELEGRAM_BOT_TOKEN is missing"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    response = requests.get(url, params={"url": telegram_webhook_url()}, timeout=30)

    try:
        return response.ok, response.json()
    except Exception:
        return response.ok, {"text": response.text}


def get_telegram_webhook_info():
    if not TELEGRAM_BOT_TOKEN:
        return False, {"error": "TELEGRAM_BOT_TOKEN is missing"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo"
    response = requests.get(url, timeout=30)

    try:
        return response.ok, response.json()
    except Exception:
        return response.ok, {"text": response.text}


def get_social_conversations(business_ids, platform_filter="all", search_text="", limit=900):
    if not business_ids:
        return []

    try:
        query = (
            supabase.table("inbox_messages")
            .select("*")
            .in_("business_id", business_ids)
            .order("created_at", desc=True)
            .limit(limit)
        )

        if platform_filter != "all":
            query = query.eq("platform", platform_filter)

        rows = query.execute().data or []

    except Exception as e:
        st.error(f"❌ Could not load sales chats: {e}")
        return []

    conversations = {}

    for row in rows:
        business_id = row.get("business_id")
        platform = row.get("platform", "instagram")
        channel = row.get("channel", "")
        customer_id = str(row.get("customer_id") or "").strip()

        if not business_id or not customer_id:
            continue

        key = f"{platform}::{business_id}::{channel}::{customer_id}"

        fallback_name = f"{'Telegram' if platform == 'telegram' else 'Instagram'} Client {customer_id[-4:]}"

        if key not in conversations:
            conversations[key] = {
                "business_id": business_id,
                "platform": platform,
                "channel": channel,
                "customer_id": customer_id,
                "chat_id": str(row.get("chat_id") or customer_id),
                "customer_name": row.get("customer_name") or fallback_name,
                "last_message": row.get("content", ""),
                "last_message_at": row.get("created_at", ""),
                "unread_count": 0,
                "total_messages": 0,
            }

        conversations[key]["total_messages"] += 1

        if row.get("direction") == "inbound" and not bool(row.get("is_read", False)):
            conversations[key]["unread_count"] += 1

    results = list(conversations.values())

    if search_text.strip():
        q = search_text.lower().strip()
        results = [
            c for c in results
            if q in f"{c.get('customer_id','')} {c.get('customer_name','')} {c.get('last_message','')} {c.get('platform','')} {c.get('channel','')}".lower()
        ]

    return results


def get_conversation_messages(business_id, customer_id, platform, channel, limit=250):
    try:
        query = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", platform)
            .eq("business_id", business_id)
            .eq("customer_id", str(customer_id))
        )

        if channel:
            query = query.eq("channel", channel)

        return (
            query.order("created_at", desc=False)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as e:
        st.error(f"❌ Could not load conversation: {e}")
        return []


def mark_conversation_read(business_id, customer_id, platform, channel):
    try:
        query = (
            supabase.table("inbox_messages")
            .update({"is_read": True})
            .eq("platform", platform)
            .eq("business_id", business_id)
            .eq("customer_id", str(customer_id))
            .eq("direction", "inbound")
        )

        if channel:
            query = query.eq("channel", channel)

        query.execute()
    except Exception:
        pass


def save_outbound_message(business, customer_id, text, platform, channel, chat_id="", raw_payload=None, media_type=None, media_url=None):
    data = {
        "business_id": business.get("id"),
        "instagram_business_id": business.get("instagram_business_id"),
        "platform": platform,
        "customer_id": str(customer_id),
        "customer_name": f"{platform.title()} Client {str(customer_id)[-4:]}",
        "chat_id": str(chat_id or customer_id),
        "channel": channel,
        "direction": "outbound",
        "role": "assistant",
        "content": text,
        "external_message_id": "",
        "raw_payload": raw_payload or {},
        "is_read": True,
        "media_type": media_type,
        "media_url": media_url,
    }

    try:
        supabase.table("inbox_messages").insert(data).execute()
    except Exception:
        fallback = dict(data)
        fallback.pop("customer_name", None)
        fallback.pop("chat_id", None)
        fallback.pop("is_read", None)
        supabase.table("inbox_messages").insert(fallback).execute()


def send_instagram_dm_from_backend(business_id, customer_id, text):
    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-instagram-dm",
        json={
            "business_id": str(business_id),
            "customer_id": str(customer_id),
            "text": text,
        },
        headers={"x-dashboard-secret": DASHBOARD_SECRET},
        timeout=30,
    )

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    return response.ok, data


def send_instagram_media_from_backend(business_id, customer_id, caption, media_type, media_url):
    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-instagram-media",
        json={
            "business_id": str(business_id),
            "customer_id": str(customer_id),
            "caption": caption,
            "media_type": media_type,
            "media_url": media_url,
        },
        headers={"x-dashboard-secret": DASHBOARD_SECRET},
        timeout=30,
    )

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    return response.ok, data


def send_telegram_bot_message(chat_id, text):
    if not TELEGRAM_BOT_TOKEN:
        return False, {"error": "TELEGRAM_BOT_TOKEN is missing"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    return response.ok and data.get("ok", False), data


def send_telegram_user_message_from_backend(customer_id, text):
    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-telegram-user-message",
        json={
            "customer_id": str(customer_id),
            "text": text,
        },
        headers={"x-dashboard-secret": DASHBOARD_SECRET},
        timeout=30,
    )

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    return response.ok, data


def send_telegram_media_from_backend(customer_id, caption, media_type, media_file_id):
    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-telegram-media",
        json={
            "customer_id": str(customer_id),
            "caption": caption,
            "media_type": media_type,
            "media_file_id": media_file_id,
        },
        headers={"x-dashboard-secret": DASHBOARD_SECRET},
        timeout=30,
    )

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    return response.ok, data


def send_telegram_file_from_backend(customer_id, caption, media_type, file_data, filename, chat_id):
    """Send file (photo/video) to Telegram via base64"""
    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-telegram-file",
        json={
            "customer_id": str(customer_id),
            "chat_id": str(chat_id),
            "caption": caption,
            "media_type": media_type,
            "file_data": file_data,
            "filename": filename,
        },
        headers={"x-dashboard-secret": DASHBOARD_SECRET},
        timeout=60,
    )

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    return response.ok, data


def send_telegram_voice_file_from_backend(customer_id, file_data, filename, chat_id):
    """Send voice message to Telegram via base64"""
    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-telegram-voice-file",
        json={
            "customer_id": str(customer_id),
            "chat_id": str(chat_id),
            "file_data": file_data,
            "filename": filename,
        },
        headers={"x-dashboard-secret": DASHBOARD_SECRET},
        timeout=60,
    )

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    return response.ok, data


def send_instagram_file_from_backend(business_id, customer_id, caption, media_type, file_data, filename):
    """Send file (photo/video) to Instagram via base64"""
    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-instagram-file",
        json={
            "business_id": str(business_id),
            "customer_id": str(customer_id),
            "caption": caption,
            "media_type": media_type,
            "file_data": file_data,
            "filename": filename,
        },
        headers={"x-dashboard-secret": DASHBOARD_SECRET},
        timeout=60,
    )

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    return response.ok, data


if "user" not in st.session_state:
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        <div style="text-align: center; padding: 80px 0 40px;">
            <div style="font-size: 80px; margin-bottom: 24px;">💬</div>
            <div class="login-card">
                <h1>Milana Premium</h1>
                <h3>Sales Chat Dashboard</h3>
                <p>Unified messaging platform for Instagram & Telegram</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown('<div style="margin: 40px 0;"></div>', unsafe_allow_html=True)
        
        email = st.text_input("📧 Email", placeholder="manager@milana.uz")
        password = st.text_input("🔐 Password", type="password", placeholder="••••••••")

        st.markdown('<div style="margin: 20px 0;"></div>', unsafe_allow_html=True)
        
        if st.button("🚀 Sign In", type="primary", use_container_width=True):
            user = login_user(email, password)
            if user:
                st.session_state["user"] = user
                st.rerun()
            else:
                st.error("❌ Invalid email or password.")

    st.stop()


user = st.session_state["user"]
user_email = normalize_email(user.get("email"))
is_admin = user_email == normalize_email(ADMIN_EMAIL)

with st.sidebar:
    st.markdown("""
    <div style="text-align: center; padding: 16px 0; margin-bottom: 24px; border-bottom: 1px solid #e5e7eb;">
        <h2 style="margin: 0 0 12px 0; font-size: 32px;">💬</h2>
        <h3 style="margin: 0 0 4px 0; font-size: 18px;">Milana Premium</h3>
        <p style="margin: 0 0 12px 0; font-size: 12px; opacity: 0.7;">Sales Chat Dashboard</p>
        <small style="color: #6b7280; word-break: break-all;">📧 {}</small>
    </div>
    """.format(html.escape(user_email)), unsafe_allow_html=True)

    if is_admin:
        nav_option = st.radio(
            "📊 Navigation",
            [
                "📈 Analytics",
                "💬 Conversations",
                "⚙️ Business Config",
                "➕ Add Business",
                "👥 Team Members",
                "🔗 Access Control",
            ],
        )
    else:
        nav_option = st.radio(
            "📊 Navigation",
            [
                "📈 Analytics",
                "💬 Conversations",
                "⚙️ Business Config",
            ],
        )

    st.divider()

    if st.button("🚪 Sign Out", use_container_width=True):
        logout()


st.markdown("""
<div class="main-header">
    <h1>💬 Sales Dashboard</h1>
    <p>Unified messaging for Instagram & Telegram — manage all customer conversations in one place</p>
</div>
""", unsafe_allow_html=True)


def show_metrics():
    businesses = get_allowed_businesses()

    total_businesses = len(businesses)
    active_bots = sum(1 for b in businesses if b.get("bot_enabled"))
    instagram_count = get_message_count("instagram")
    telegram_count = get_message_count("telegram")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f'<div class="stat-card"><div class="stat-value">{total_businesses}</div><div class="stat-label">Sales Accounts</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stat-card"><div class="stat-value">{active_bots}</div><div class="stat-label">Auto Reply Active</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="stat-card"><div class="stat-value">{instagram_count:,}</div><div class="stat-label">Instagram Messages</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="stat-card"><div class="stat-value">{telegram_count:,}</div><div class="stat-label">Telegram Messages</div></div>', unsafe_allow_html=True)


def render_message(msg, selected_business):
    direction = msg.get("direction")
    content = html.escape(str(msg.get("content", ""))).replace("\n", "<br>")
    created_at = html.escape(str(msg.get("created_at", "")))
    media_type = msg.get("media_type")
    media_url = msg.get("media_url")

    message_class = "outbound" if direction == "outbound" else "inbound"
    
    html_content = f'<div class="message {message_class}">'
    html_content += f'<div class="message-bubble">'
    
    # Display media
    if media_type == "photo" and media_url:
        html_content += f'<img src="{media_url}" class="message-media" loading="lazy" alt="Photo">'
    elif media_type == "video" and media_url:
        html_content += f'<video controls class="message-media"><source src="{media_url}" type="video/mp4">Your browser does not support the video tag.</video>'
    elif media_type == "voice" and media_url:
        html_content += f'<audio controls class="message-media"><source src="{media_url}" type="audio/ogg">Your browser does not support the audio element.</audio>'
    
    # Display text
    if content and content.strip() not in ["📸 Photo", "🎥 Video", "🎤 Voice message", "📸 Photo sent", "🎥 Video sent"]:
        html_content += f'<div class="message-text">{content}</div>'
    elif media_type:
        if media_type == "photo":
            html_content += '<div class="message-text">📸 Photo</div>'
        elif media_type == "video":
            html_content += '<div class="message-text">🎥 Video</div>'
        elif media_type == "voice":
            html_content += '<div class="message-text">🎤 Voice Message</div>'
    
    html_content += f'<div class="message-time">{created_at}</div>'
    html_content += '</div></div>'
    
    st.markdown(html_content, unsafe_allow_html=True)


def business_editor(business):
    with st.form(key=f"edit_{business['id']}"):
        st.subheader("⚙️ Configuration")

        col1, col2 = st.columns(2)

        with col1:
            business_name = st.text_input("Account Name", value=business.get("business_name", "Milana Premium"))
            business_type = st.text_input("Business Type", value=business.get("business_type", "Textile and Clothing"))

        with col2:
            language_options = ["uz", "ru", "en"]
            current_language = business.get("language", "uz")
            language_index = language_options.index(current_language) if current_language in language_options else 0
            language = st.selectbox("Main Reply Language", language_options, index=language_index)

        bot_enabled = st.toggle("🤖 Enable Auto Reply", value=bool(business.get("bot_enabled", True)))

        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            max_tokens = st.slider("Answer Length", 50, 500, int(business.get("ai_max_tokens", 130) or 130), 10)
        with col2:
            temperature = st.slider("Reply Creativity", 0.0, 1.0, float(business.get("ai_temperature", 0.5) or 0.5), 0.1)

        st.divider()
        st.subheader("📦 Products & Services")

        products = st.text_area("Products", value=business.get("products", ""), height=80)
        prices = st.text_area("Prices", value=business.get("prices", ""), height=80)
        catalog = st.text_input("Catalog Link", value=business.get("catalog_link", ""))
        phone = st.text_input("Sales Phone", value=business.get("sales_phone", ""))

        submitted = st.form_submit_button("💾 Save", type="primary", use_container_width=True)

        if submitted:
            update_data = {
                "business_name": business_name.strip(),
                "business_type": business_type.strip(),
                "language": language,
                "bot_enabled": bot_enabled,
                "ai_max_tokens": int(max_tokens),
                "ai_temperature": float(temperature),
                "products": products.strip(),
                "prices": prices.strip(),
                "catalog_link": catalog.strip(),
                "sales_phone": phone.strip(),
            }

            try:
                safe_update_business(business, update_data)
                st.success("✅ Configuration saved!")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Save failed: {e}")


if nav_option == "📈 Analytics":
    show_metrics()

elif nav_option == "💬 Conversations":
    businesses = get_allowed_businesses()
    business_map = {b.get("id"): b for b in businesses if b.get("id")}
    business_ids = list(business_map.keys())

    if not businesses:
        st.warning("⚠️ No sales accounts configured yet.")
    else:
        col1, col2, col3 = st.columns([2, 1, 1])

        with col1:
            search_text = st.text_input("🔍 Search conversations", placeholder="Search by name, ID, or message...")

        with col2:
            platform_filter_label = st.selectbox("Platform", ["All", "Instagram", "Telegram"])
            platform_filter = {"All": "all", "Instagram": "instagram", "Telegram": "telegram"}[platform_filter_label]

        with col3:
            unread_only = st.toggle("Unread", value=False)

        conversations = get_social_conversations(
            business_ids=business_ids,
            platform_filter=platform_filter,
            search_text=search_text,
        )

        if unread_only:
            conversations = [c for c in conversations if c.get("unread_count", 0) > 0]

        if not conversations:
            st.info("ℹ️ No conversations yet.")
        else:
            left, right = st.columns([1.05, 2.45])

            with left:
                st.markdown("### Conversations")
                options = {}

                for c in conversations:
                    platform = c.get("platform", "instagram")
                    unread = c.get("unread_count", 0)
                    icon = "📲" if platform == "telegram" else "📸"
                    name = c.get("customer_name") or f"Client {str(c.get('customer_id'))[-4:]}"
                    preview = str(c.get("last_message", ""))[:35]

                    label = f"{icon} {name} {'🔴' if unread else ''}\n{preview}"
                    options[label] = c

                selected_label = st.radio("", list(options.keys()), label_visibility="collapsed")
                selected_conversation = options[selected_label]

            with right:
                selected_business = business_map.get(selected_conversation["business_id"])

                if not selected_business:
                    st.error("❌ Business not found.")
                    st.stop()

                customer_id = selected_conversation["customer_id"]
                chat_id = selected_conversation.get("chat_id") or customer_id
                platform = selected_conversation.get("platform", "instagram")
                channel = selected_conversation.get("channel", "")
                customer_name = selected_conversation.get("customer_name") or f"Client {str(customer_id)[-4:]}"

                ai_enabled = get_chat_ai_enabled(
                    business_id=selected_business["id"],
                    platform=platform,
                    channel=channel,
                    customer_id=customer_id,
                )

                mark_conversation_read(selected_business["id"], customer_id, platform, channel)
                messages = get_conversation_messages(selected_business["id"], customer_id, platform, channel)

                badge_class = "badge-telegram" if platform == "telegram" else "badge-instagram"
                badge_text = "Telegram" if platform == "telegram" else "Instagram"

                st.markdown(f"""
                <div class="chat-container">
                    <div class="chat-header">
                        <div class="chat-header-info">
                            <div class="chat-avatar">{'TG' if platform == 'telegram' else 'IG'}</div>
                            <div class="chat-meta">
                                <p class="chat-name">{html.escape(customer_name)}</p>
                                <p class="chat-info">{selected_business.get('business_name', 'Milana Premium')}</p>
                            </div>
                        </div>
                        <span class="platform-badge {badge_class}">{badge_text}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                col_ai_1, col_ai_2 = st.columns([3, 1])
                with col_ai_2:
                    new_ai_enabled = st.toggle("AI", value=ai_enabled, key=f"ai_{platform}_{channel}_{customer_id}")
                    if new_ai_enabled != ai_enabled:
                        set_chat_ai_enabled(
                            business_id=selected_business["id"],
                            platform=platform,
                            channel=channel,
                            customer_id=customer_id,
                            enabled=new_ai_enabled,
                        )
                        st.rerun()

                st.markdown('<div class="messages-area">', unsafe_allow_html=True)
                for msg in messages:
                    render_message(msg, selected_business)
                st.markdown('</div>', unsafe_allow_html=True)
                
                # Add spacing for input
                st.markdown('<div style="height: 20px;"></div>', unsafe_allow_html=True)

                # Message input tabs
                msg_tab1, msg_tab2, msg_tab3 = st.tabs(["💬 Text", "📎 Files", "🎤 Voice"])
                
                with msg_tab1:
                    with st.form("manual_reply", clear_on_submit=True):
                        reply_text = st.text_area("Message", placeholder="Type your reply...", height=80)

                        col1, col2, col3, col4 = st.columns(4)

                        with col1:
                            send_clicked = st.form_submit_button("💬 Send", type="primary", use_container_width=True)
                        with col2:
                            catalog_clicked = st.form_submit_button("📚 Catalog", use_container_width=True)
                        with col3:
                            phone_clicked = st.form_submit_button("☎️ Contact", use_container_width=True)
                        with col4:
                            product_clicked = st.form_submit_button("📦 Product", use_container_width=True)

                        quick_text = ""
                        if catalog_clicked:
                            link = selected_business.get("catalog_link", "")
                            quick_text = f"Katalogimiz: {link}" if link else "Qaysi mahsulot katalogi kerak?"
                        elif phone_clicked:
                            p = selected_business.get("sales_phone", "")
                            quick_text = f"Savdo: {p}" if p else "Telefon raqam qoldiring."
                        elif product_clicked:
                            quick_text = "Qaysi mahsulot sizni qiziqtiryapti?"

                        final_text = quick_text or reply_text.strip()

                        if send_clicked or catalog_clicked or phone_clicked or product_clicked:
                            if not final_text.strip():
                                st.error("❌ Message cannot be empty.")
                            else:
                                if platform == "instagram":
                                    ok, result = send_instagram_dm_from_backend(
                                        business_id=selected_business["id"],
                                        customer_id=customer_id,
                                        text=final_text.strip(),
                                    )
                                elif platform == "telegram" and channel in ["telegram_bot_private", "telegram_bot_group"]:
                                    ok, result = send_telegram_bot_message(
                                        chat_id=chat_id,
                                        text=final_text.strip(),
                                    )
                                    if ok:
                                        save_outbound_message(
                                            business=selected_business,
                                            customer_id=customer_id,
                                            text=final_text.strip(),
                                            platform="telegram",
                                            channel=channel or "telegram_bot_private",
                                            chat_id=chat_id,
                                            raw_payload=result,
                                        )
                                elif platform == "telegram" and channel == "telegram_user_private":
                                    ok, result = send_telegram_user_message_from_backend(
                                        customer_id=customer_id,
                                        text=final_text.strip(),
                                    )
                                else:
                                    ok, result = False, {"error": "Unsupported channel"}

                                if ok:
                                    st.success("✅ Message sent!")
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error("❌ Failed to send.")
                
                with msg_tab2:
                    st.markdown("**📎 Send Photo or Video**")
                    uploaded_file = st.file_uploader(
                        "Choose image or video",
                        type=["jpg", "jpeg", "png", "gif", "mp4", "mov", "avi", "webm"],
                        key=f"file_upload_{customer_id}"
                    )
                    
                    file_caption = st.text_input("Caption (optional)", placeholder="Add a caption...")
                    
                    if uploaded_file:
                        file_size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
                        st.info(f"📦 File: {uploaded_file.name} ({file_size_mb:.2f} MB)")
                        
                        if file_size_mb > 100:
                            st.error("❌ File too large (max 100 MB)")
                        else:
                            if st.button("📤 Send File", type="primary", use_container_width=True, key=f"send_file_{customer_id}"):
                                # Determine media type
                                file_ext = uploaded_file.name.split(".")[-1].lower()
                                if file_ext in ["jpg", "jpeg", "png", "gif"]:
                                    media_type = "photo"
                                else:
                                    media_type = "video"
                                
                                # Convert file to base64 for sending
                                file_bytes = uploaded_file.getvalue()
                                file_base64 = base64.b64encode(file_bytes).decode()
                                
                                try:
                                    if platform == "instagram":
                                        # For Instagram, we'll need to upload to a service first
                                        ok, result = send_instagram_file_from_backend(
                                            business_id=selected_business["id"],
                                            customer_id=customer_id,
                                            caption=file_caption or f"Sent {media_type}",
                                            media_type=media_type,
                                            file_data=file_base64,
                                            filename=uploaded_file.name,
                                        )
                                    elif platform == "telegram":
                                        ok, result = send_telegram_file_from_backend(
                                            customer_id=customer_id,
                                            caption=file_caption or f"Sent {media_type}",
                                            media_type=media_type,
                                            file_data=file_base64,
                                            filename=uploaded_file.name,
                                            chat_id=chat_id,
                                        )
                                    else:
                                        ok, result = False, {"error": "Unsupported platform"}
                                    
                                    if ok:
                                        st.success("✅ File sent!")
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(f"❌ Failed: {result.get('error', 'Unknown error')}")
                                except Exception as e:
                                    st.error(f"❌ Error: {str(e)}")
                
                with msg_tab3:
                    st.markdown("**🎤 Send Voice Message**")
                    
                    voice_option = st.radio("Voice input method", ["Upload File", "Record Now"], horizontal=True)
                    
                    if voice_option == "Upload File":
                        voice_file = st.file_uploader(
                            "Upload voice message (MP3, OGG, WAV, M4A)",
                            type=["mp3", "ogg", "wav", "m4a", "opus"],
                            key=f"voice_upload_{customer_id}"
                        )
                        
                        if voice_file:
                            file_size_mb = len(voice_file.getvalue()) / (1024 * 1024)
                            st.audio(voice_file)
                            st.info(f"🎵 Voice: {voice_file.name} ({file_size_mb:.2f} MB)")
                            
                            if st.button("📤 Send Voice", type="primary", use_container_width=True, key=f"send_voice_{customer_id}"):
                                if file_size_mb > 50:
                                    st.error("❌ File too large (max 50 MB)")
                                else:
                                    file_bytes = voice_file.getvalue()
                                    file_base64 = base64.b64encode(file_bytes).decode()
                                    
                                    try:
                                        ok, result = send_telegram_voice_file_from_backend(
                                            customer_id=customer_id,
                                            file_data=file_base64,
                                            filename=voice_file.name,
                                            chat_id=chat_id,
                                        )
                                        
                                        if ok:
                                            st.success("✅ Voice message sent!")
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error(f"❌ Failed: {result.get('error', 'Unknown error')}")
                                    except Exception as e:
                                        st.error(f"❌ Error: {str(e)}")
                    else:
                        st.info("🎙️ Speak clearly for 1-60 seconds")
                        st.warning("💡 Note: Recording requires browser microphone permission")
                        st.markdown("""
                        **How to record:**
                        1. Click the microphone button below
                        2. Speak your message (1-60 seconds)
                        3. Stop recording when done
                        4. Click Send
                        """)
                        
                        # Placeholder for audio recording - requires webrtc-audio-processing
                        st.info("📱 Use 'Upload File' tab to send recorded voice messages from your device")

elif nav_option == "⚙️ Business Config":
    st.subheader("⚙️ Configuration")
    
    businesses = get_allowed_businesses()

    if not businesses:
        st.warning("⚠️ No accounts configured yet.")
    else:
        if len(businesses) == 1:
            business = businesses[0]
        else:
            business_options = {f"{b.get('business_name', 'Milana Premium')}": b for b in businesses}
            selected = st.selectbox("Select Account", list(business_options.keys()))
            business = business_options[selected]

        business_editor(business)

elif nav_option == "➕ Add Business" and is_admin:
    st.subheader("➕ Create New Business")

    with st.form("add_business"):
        name = st.text_input("Account Name", value="Milana Premium")
        ig_id = st.text_input("Instagram Business ID *")
        knowledge = st.text_area("Knowledge Base", height=150)

        submitted = st.form_submit_button("✨ Create", type="primary", use_container_width=True)

        if submitted:
            if not name.strip() or not ig_id.strip():
                st.error("❌ Name and Instagram ID required.")
            else:
                data = {
                    "business_name": name.strip(),
                    "instagram_business_id": ig_id.strip(),
                    "business_type": "Textile and Clothing",
                    "language": "uz",
                    "bot_enabled": False,
                    "knowledge": knowledge.strip(),
                }

                try:
                    create_business(data)
                    st.success("✅ Business created!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed: {e}")

elif nav_option == "👥 Team Members" and is_admin:
    st.subheader("👥 Team Management")

    with st.expander("➕ Add / Reset Member", expanded=True):
        email_u = st.text_input("Email")
        pwd_u = st.text_input("Password", type="password")

        if st.button("💾 Save", use_container_width=True):
            if email_u and pwd_u:
                create_or_update_dashboard_user(email_u, pwd_u)
                st.success("✅ Saved!")
                st.rerun()
            else:
                st.error("❌ Email and password required.")

    users = get_all_dashboard_users()
    if users:
        st.dataframe(users, use_container_width=True)

elif nav_option == "🔗 Access Control" and is_admin:
    st.subheader("🔗 Access Control")

    all_biz = get_all_businesses()

    if not all_biz:
        st.warning("⚠️ No accounts found.")
    else:
        biz_map = {f"{b.get('business_name', 'Milana Premium')}": b["id"] for b in all_biz}

        email_assign = st.text_input("Manager Email")
        selected_biz = st.selectbox("Account", list(biz_map.keys()))
        role = st.selectbox("Role", ["owner", "editor"])

        col1, col2 = st.columns(2)

        with col1:
            if st.button("✓ Assign", use_container_width=True):
                if email_assign:
                    assign_business_to_user(email_assign, biz_map[selected_biz], role)
                    st.success("✅ Assigned!")
                    st.rerun()

        with col2:
            if st.button("✕ Remove", use_container_width=True):
                if email_assign:
                    remove_business_assignment(email_assign, biz_map[selected_biz])
                    st.success("✅ Removed!")
                    st.rerun()

        assignments = get_business_assignments()
        if assignments:
            st.dataframe(assignments, use_container_width=True)
