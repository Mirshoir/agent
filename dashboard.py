import os
import hmac
import time
import html
import base64
import hashlib
import requests
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

st.set_page_config(
    page_title="Milana · Sales Chat",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Mono:wght@300;400;500&family=Instrument+Sans:wght@400;500;600&display=swap');

:root {
    --ink: #0a0a0f;
    --ink-2: #1a1a24;
    --ink-3: #2d2d3d;
    --smoke: #f4f3f0;
    --smoke-2: #eceae5;
    --smoke-3: #e0ddd6;
    --amber: #e8a020;
    --amber-light: #f5c84a;
    --amber-dim: rgba(232, 160, 32, 0.12);
    --red: #e03030;
    --green: #1e9e60;
    --blue: #2060d0;
    --border: rgba(10, 10, 15, 0.09);
    --border-strong: rgba(10, 10, 15, 0.18);
    --r: 12px;
    --r-sm: 8px;
    --font-display: 'Syne', sans-serif;
    --font-body: 'Instrument Sans', sans-serif;
    --font-mono: 'DM Mono', monospace;
    --shadow-1: 0 1px 3px rgba(10,10,15,0.06), 0 1px 2px rgba(10,10,15,0.04);
    --shadow-2: 0 4px 16px rgba(10,10,15,0.10), 0 1px 4px rgba(10,10,15,0.06);
    --shadow-3: 0 16px 40px rgba(10,10,15,0.14), 0 4px 12px rgba(10,10,15,0.08);
}

*, *::before, *::after { box-sizing: border-box; }

html, body, [data-testid="stAppViewContainer"] {
    font-family: var(--font-body);
    background: var(--smoke);
    color: var(--ink);
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: var(--ink) !important;
    border-right: none;
}
[data-testid="stSidebar"] > div:first-child { padding: 24px 16px; }
[data-testid="stSidebar"] * { color: rgba(244,243,240,0.85) !important; }
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: var(--r-sm) !important;
    margin-bottom: 4px !important;
    padding: 10px 14px !important;
    transition: all .18s ease !important;
    font-family: var(--font-body) !important;
    font-size: 13.5px !important;
}
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label:hover {
    background: rgba(255,255,255,0.08) !important;
    border-color: rgba(232,160,32,0.3) !important;
}
[data-testid="stSidebar"] .stDivider { border-color: rgba(255,255,255,0.08) !important; }
[data-testid="stSidebar"] .stButton button {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    color: rgba(244,243,240,0.7) !important;
    border-radius: var(--r-sm) !important;
    font-size: 13px !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: rgba(255,255,255,0.10) !important;
    color: rgba(244,243,240,1) !important;
}

/* ── Topbar ── */
.topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 28px;
    background: var(--ink);
    border-radius: var(--r);
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
}
.topbar::after {
    content: '';
    position: absolute; inset: 0;
    background: radial-gradient(ellipse 60% 100% at 85% 50%, rgba(232,160,32,0.08) 0%, transparent 70%);
    pointer-events: none;
}
.topbar-left { display: flex; align-items: center; gap: 16px; }
.topbar-logo {
    width: 40px; height: 40px;
    background: var(--amber);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-family: var(--font-display);
    font-weight: 800; font-size: 18px;
    color: var(--ink);
    flex-shrink: 0;
}
.topbar-title {
    font-family: var(--font-display);
    font-size: 22px; font-weight: 700;
    color: var(--smoke); letter-spacing: -0.02em;
}
.topbar-sub { font-size: 13px; color: rgba(244,243,240,0.45); margin-top: 2px; }
.topbar-stat {
    display: flex; gap: 20px;
}
.topbar-stat-item { text-align: right; }
.topbar-stat-num {
    font-family: var(--font-display);
    font-size: 20px; font-weight: 700; color: var(--amber);
}
.topbar-stat-label { font-size: 11px; color: rgba(244,243,240,0.4); text-transform: uppercase; letter-spacing: .08em; }

/* ── Metric Cards ── */
.metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
.metric-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--r);
    padding: 20px 22px;
    box-shadow: var(--shadow-1);
    position: relative; overflow: hidden;
    transition: box-shadow .2s ease, transform .2s ease;
}
.metric-card:hover { box-shadow: var(--shadow-2); transform: translateY(-2px); }
.metric-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, var(--amber) 0%, var(--amber-light) 100%);
}
.metric-num {
    font-family: var(--font-display);
    font-size: 34px; font-weight: 800;
    color: var(--ink); letter-spacing: -0.03em;
    line-height: 1;
}
.metric-label { font-size: 12px; font-weight: 600; color: #888; text-transform: uppercase; letter-spacing: .07em; margin-top: 8px; }
.metric-icon { position: absolute; top: 18px; right: 18px; font-size: 22px; opacity: 0.18; }

/* ── Chat Layout ── */
.chat-wrap { display: flex; gap: 0; height: calc(100vh - 220px); border-radius: var(--r); overflow: hidden; border: 1px solid var(--border); box-shadow: var(--shadow-2); }
.conv-list { width: 300px; flex-shrink: 0; background: white; border-right: 1px solid var(--border); overflow-y: auto; }
.conv-head { padding: 16px; border-bottom: 1px solid var(--border); font-family: var(--font-display); font-size: 15px; font-weight: 700; color: var(--ink); }
.conv-item {
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    cursor: pointer; transition: background .15s ease;
    display: flex; gap: 12px; align-items: flex-start;
}
.conv-item:hover { background: var(--smoke); }
.conv-item.active { background: var(--amber-dim); border-left: 3px solid var(--amber); }
.conv-avatar {
    width: 38px; height: 38px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 13px; flex-shrink: 0;
    font-family: var(--font-display);
}
.av-ig { background: linear-gradient(135deg, #e03090, #f06020); color: white; }
.av-tg { background: linear-gradient(135deg, #2090d0, #30c0f0); color: white; }
.conv-meta { flex: 1; min-width: 0; }
.conv-name { font-size: 13.5px; font-weight: 600; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-preview { font-size: 12px; color: #888; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px; }
.conv-badge { background: var(--amber); color: var(--ink); border-radius: 12px; font-size: 10px; font-weight: 700; padding: 2px 6px; margin-left: 4px; }

/* ── Chat Panel ── */
.chat-panel { flex: 1; display: flex; flex-direction: column; background: var(--smoke); min-width: 0; }
.chat-header {
    padding: 14px 20px;
    background: white;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    flex-shrink: 0;
}
.chat-header-left { display: flex; align-items: center; gap: 12px; }
.chat-name { font-family: var(--font-display); font-size: 16px; font-weight: 700; color: var(--ink); }
.platform-tag {
    padding: 3px 8px; border-radius: 6px;
    font-size: 11px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
}
.pt-ig { background: rgba(224,48,144,0.10); color: #c02080; }
.pt-tg { background: rgba(32,144,208,0.10); color: #1070a0; }
.ai-chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 12px; border-radius: 20px;
    font-size: 12px; font-weight: 600;
    border: 1px solid var(--border);
    background: white;
    cursor: pointer;
    transition: all .15s ease;
}
.ai-chip.on { background: rgba(30,158,96,0.10); border-color: rgba(30,158,96,0.25); color: var(--green); }
.ai-chip.off { background: rgba(224,48,48,0.08); border-color: rgba(224,48,48,0.20); color: var(--red); }
.ai-dot { width: 7px; height: 7px; border-radius: 50%; }
.ai-dot.on { background: var(--green); }
.ai-dot.off { background: var(--red); }

/* ── Messages ── */
.messages-area { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; }
.msg-row { display: flex; gap: 10px; max-width: 72%; }
.msg-row.out { align-self: flex-end; flex-direction: row-reverse; }
.msg-row.in { align-self: flex-start; }
.msg-av { width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; margin-top: 2px; }
.msg-body { }
.msg-bubble {
    padding: 10px 14px;
    border-radius: 16px;
    font-size: 14px; line-height: 1.55;
    position: relative;
    word-break: break-word;
}
.msg-row.in .msg-bubble {
    background: white;
    border: 1px solid var(--border);
    border-bottom-left-radius: 4px;
    color: var(--ink);
    box-shadow: var(--shadow-1);
}
.msg-row.out .msg-bubble {
    background: var(--ink);
    border-bottom-right-radius: 4px;
    color: var(--smoke);
}
.msg-time { font-size: 11px; color: #aaa; margin-top: 4px; font-family: var(--font-mono); }
.msg-row.out .msg-time { text-align: right; }
.msg-media { border-radius: 10px; overflow: hidden; margin-bottom: 4px; max-width: 240px; }
.msg-media img { width: 100%; display: block; border-radius: 10px; }
.msg-media video { width: 100%; display: block; border-radius: 10px; }
.msg-media audio { width: 220px; }
.msg-voice-icon { font-size: 22px; margin-right: 8px; vertical-align: middle; }
.msg-file-card {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; background: rgba(255,255,255,0.12);
    border-radius: 10px; border: 1px solid rgba(255,255,255,0.15);
    font-size: 13px; color: var(--smoke); text-decoration: none;
    max-width: 220px; margin-bottom: 4px;
}
.msg-file-icon { font-size: 20px; }

/* ── Reply Box ── */
.reply-box {
    padding: 14px 16px;
    background: white;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
}
.media-tabs { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.media-tab {
    padding: 5px 12px; border-radius: 20px;
    font-size: 12px; font-weight: 600;
    border: 1px solid var(--border);
    background: var(--smoke); color: #555;
    cursor: pointer; transition: all .15s ease;
}
.media-tab.active { background: var(--ink); color: var(--smoke); border-color: var(--ink); }
.quick-btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.quick-btn {
    padding: 6px 14px; border-radius: 20px;
    font-size: 12px; font-weight: 600;
    border: 1px solid var(--border);
    background: var(--smoke); color: var(--ink-3);
    cursor: pointer; transition: all .15s ease;
}
.quick-btn:hover { background: var(--amber-dim); border-color: var(--amber); }

/* ── Form inputs override ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    border-radius: var(--r-sm) !important;
    border: 1px solid var(--border-strong) !important;
    font-family: var(--font-body) !important;
    font-size: 14px !important;
    background: var(--smoke) !important;
    color: var(--ink) !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--amber) !important;
    box-shadow: 0 0 0 3px var(--amber-dim) !important;
    background: white !important;
}
.stSelectbox > div > div {
    border-radius: var(--r-sm) !important;
    border-color: var(--border-strong) !important;
}
.stButton button {
    border-radius: var(--r-sm) !important;
    font-family: var(--font-body) !important;
    font-weight: 600 !important;
    font-size: 13.5px !important;
    border: 1px solid transparent !important;
    transition: all .2s ease !important;
}
.stButton button[kind="primary"] {
    background: var(--ink) !important;
    color: var(--smoke) !important;
}
.stButton button[kind="primary"]:hover {
    background: var(--ink-2) !important;
    box-shadow: var(--shadow-2) !important;
    transform: translateY(-1px) !important;
}
.stButton button[kind="secondary"] {
    background: white !important;
    color: var(--ink) !important;
    border-color: var(--border-strong) !important;
}

/* ── File uploader ── */
.stFileUploader { border: 2px dashed var(--border-strong) !important; border-radius: var(--r) !important; background: var(--smoke) !important; }

/* ── Toggle ── */
.stCheckbox label { font-family: var(--font-body); font-size: 14px; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] { border-bottom: 2px solid var(--border); gap: 4px; }
.stTabs [data-baseweb="tab"] { font-family: var(--font-body); font-size: 14px; font-weight: 600; color: #888; padding: 8px 16px; border-radius: var(--r-sm) var(--r-sm) 0 0; }
.stTabs [data-baseweb="tab"][aria-selected="true"] { color: var(--ink); border-bottom: 2px solid var(--amber); background: var(--amber-dim); }

/* ── Alert overrides ── */
.stSuccess { border-radius: var(--r-sm) !important; border: 1px solid rgba(30,158,96,0.3) !important; }
.stError { border-radius: var(--r-sm) !important; border: 1px solid rgba(224,48,48,0.25) !important; }

/* ── Section card ── */
.section-card { background: white; border: 1px solid var(--border); border-radius: var(--r); padding: 24px; margin-bottom: 20px; box-shadow: var(--shadow-1); }
.section-title { font-family: var(--font-display); font-size: 16px; font-weight: 700; color: var(--ink); margin: 0 0 16px 0; display: flex; align-items: center; gap: 8px; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--smoke); }
::-webkit-scrollbar-thumb { background: rgba(10,10,15,0.15); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: rgba(10,10,15,0.3); }

/* ── Sidebar logo area ── */
.sb-brand { text-align: center; padding: 8px 0 20px; }
.sb-logo { font-family: 'Syne', sans-serif; font-size: 28px; font-weight: 800; color: #e8a020; letter-spacing: -0.02em; }
.sb-tagline { font-size: 11px; color: rgba(244,243,240,0.35); text-transform: uppercase; letter-spacing: .12em; margin-top: 2px; }
.sb-user { font-size: 12px; color: rgba(244,243,240,0.4); margin-top: 6px; word-break: break-all; }

/* ── Badge ── */
.badge { display: inline-block; padding: 2px 8px; border-radius: 20px; font-size: 11px; font-weight: 700; }
.badge-green { background: rgba(30,158,96,0.12); color: var(--green); }
.badge-red { background: rgba(224,48,48,0.10); color: var(--red); }
.badge-amber { background: var(--amber-dim); color: #a06010; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

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
    st.error("Missing SUPABASE_URL, SUPABASE_SERVICE_KEY, ADMIN_EMAIL, or DASHBOARD_SECRET.")
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
        .data or []
    )


def get_user_businesses(user_email):
    links = (
        supabase.table("business_users")
        .select("business_id, role")
        .eq("user_email", normalize_email(user_email))
        .execute()
        .data or []
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
        .data or []
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
        .data or []
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
        .data or []
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
        st.error(f"Could not load chats: {e}")
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
        fallback_name = f"{'Telegram' if platform == 'telegram' else 'Instagram'} Client …{customer_id[-4:]}"
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
            .data or []
        )
    except Exception as e:
        st.error(f"Could not load conversation: {e}")
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


def save_outbound_message(business, customer_id, text, platform, channel, chat_id="",
                          raw_payload=None, media_type=None, media_url=None):
    content = text
    if media_type and media_url:
        content = f"[{media_type.upper()}] {media_url}" + (f"\n{text}" if text else "")
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
        "content": content,
        "media_type": media_type or "",
        "media_url": media_url or "",
        "external_message_id": "",
        "raw_payload": raw_payload or {},
        "is_read": True,
    }
    try:
        supabase.table("inbox_messages").insert(data).execute()
    except Exception:
        fallback = dict(data)
        for k in ["customer_name", "chat_id", "is_read", "media_type", "media_url"]:
            fallback.pop(k, None)
        supabase.table("inbox_messages").insert(fallback).execute()


def send_instagram_dm_from_backend(business_id, customer_id, text,
                                   media_type=None, media_url=None, file_bytes=None, file_name=None):
    payload = {
        "business_id": str(business_id),
        "customer_id": str(customer_id),
        "text": text,
    }
    if media_type:
        payload["media_type"] = media_type
    if media_url:
        payload["media_url"] = media_url

    # If raw bytes provided, upload via multipart
    if file_bytes and file_name:
        try:
            response = requests.post(
                f"{BACKEND_URL}/dashboard/send-instagram-media",
                data={"business_id": str(business_id), "customer_id": str(customer_id), "text": text},
                files={"file": (file_name, file_bytes)},
                headers={"x-dashboard-secret": DASHBOARD_SECRET},
                timeout=60,
            )
        except Exception as e:
            return False, {"error": str(e)}
    else:
        try:
            response = requests.post(
                f"{BACKEND_URL}/dashboard/send-instagram-dm",
                json=payload,
                headers={"x-dashboard-secret": DASHBOARD_SECRET},
                timeout=30,
            )
        except Exception as e:
            return False, {"error": str(e)}

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}
    return response.ok, data


def send_telegram_bot_message(chat_id, text, media_type=None, file_bytes=None, file_name=None):
    if not TELEGRAM_BOT_TOKEN:
        return False, {"error": "TELEGRAM_BOT_TOKEN is missing"}

    if file_bytes and media_type:
        method_map = {
            "photo": "sendPhoto",
            "video": "sendVideo",
            "voice": "sendVoice",
            "audio": "sendAudio",
            "document": "sendDocument",
        }
        method = method_map.get(media_type, "sendDocument")
        field_map = {
            "photo": "photo",
            "video": "video",
            "voice": "voice",
            "audio": "audio",
            "document": "document",
        }
        field = field_map.get(media_type, "document")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
        data_fields = {"chat_id": str(chat_id)}
        if text:
            data_fields["caption"] = text[:1024]
        try:
            response = requests.post(
                url,
                data=data_fields,
                files={field: (file_name or "media", file_bytes)},
                timeout=60,
            )
        except Exception as e:
            return False, {"error": str(e)}
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            response = requests.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False}, timeout=30)
        except Exception as e:
            return False, {"error": str(e)}

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}
    return response.ok and data.get("ok", False), data


def send_telegram_user_message_from_backend(customer_id, text, media_type=None,
                                            file_bytes=None, file_name=None):
    if file_bytes and media_type:
        try:
            response = requests.post(
                f"{BACKEND_URL}/dashboard/send-telegram-user-media",
                data={"customer_id": str(customer_id), "text": text or "", "media_type": media_type},
                files={"file": (file_name or "media", file_bytes)},
                headers={"x-dashboard-secret": DASHBOARD_SECRET},
                timeout=60,
            )
        except Exception as e:
            return False, {"error": str(e)}
    else:
        try:
            response = requests.post(
                f"{BACKEND_URL}/dashboard/send-telegram-user-message",
                json={"customer_id": str(customer_id), "text": text},
                headers={"x-dashboard-secret": DASHBOARD_SECRET},
                timeout=30,
            )
        except Exception as e:
            return False, {"error": str(e)}

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}
    return response.ok, data


def render_message_bubble(msg):
    direction = msg.get("direction", "inbound")
    content = str(msg.get("content", ""))
    created_at = str(msg.get("created_at", ""))[:16]
    media_type = msg.get("media_type", "")
    media_url = msg.get("media_url", "")

    # Parse legacy [TYPE] prefix
    if not media_type and content.startswith("[") and "]" in content:
        bracket_end = content.index("]")
        possible_type = content[1:bracket_end].lower()
        if possible_type in ["photo", "image", "video", "voice", "audio", "document"]:
            media_type = possible_type
            rest = content[bracket_end + 1:].strip()
            if rest.startswith("http"):
                media_url = rest.split("\n")[0]
                content = rest[len(media_url):].strip()
            else:
                content = rest

    css_dir = "out" if direction == "outbound" else "in"
    av_text = "ME" if direction == "outbound" else "👤"
    av_class = "av-tg" if direction == "outbound" else ""

    media_html = ""
    if media_type in ["photo", "image"] and media_url:
        media_html = f'<div class="msg-media"><img src="{html.escape(media_url)}" alt="photo" loading="lazy"/></div>'
    elif media_type == "video" and media_url:
        media_html = f'<div class="msg-media"><video controls src="{html.escape(media_url)}"></video></div>'
    elif media_type in ["voice", "audio"] and media_url:
        media_html = f'<div class="msg-media"><span class="msg-voice-icon">🎙️</span><audio controls src="{html.escape(media_url)}"></audio></div>'
    elif media_type == "document" and media_url:
        fname = media_url.split("/")[-1] or "Document"
        media_html = f'<a href="{html.escape(media_url)}" target="_blank" class="msg-file-card"><span class="msg-file-icon">📎</span>{html.escape(fname)}</a>'
    elif media_type and not media_url:
        media_html = f'<div style="font-size:13px;opacity:.6;font-style:italic;">📎 {media_type} received</div>'

    text_html = ""
    if content:
        text_html = f'<div>{html.escape(content).replace(chr(10), "<br>")}</div>'

    return f"""
<div class="msg-row {css_dir}">
    <div class="msg-av {av_class}">{av_text}</div>
    <div class="msg-body">
        <div class="msg-bubble">
            {media_html}
            {text_html}
        </div>
        <div class="msg-time">{created_at}</div>
    </div>
</div>
"""


# ── Login ──────────────────────────────────────────────────────────────────────

if "user" not in st.session_state:
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
        <div style="padding: 60px 0 32px; text-align: center;">
            <div style="font-family: 'Syne', sans-serif; font-size: 52px; font-weight: 800; color: #0a0a0f; letter-spacing: -0.04em; line-height: 1;">Milana</div>
            <div style="font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: .14em; margin-top: 6px;">Sales Chat Platform</div>
        </div>
        """, unsafe_allow_html=True)

        with st.container():
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">🔐 Sign in to your account</div>', unsafe_allow_html=True)
            email = st.text_input("Email address", placeholder="manager@milana.uz")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            st.markdown("</div>", unsafe_allow_html=True)

        if st.button("Continue →", type="primary", use_container_width=True):
            user = login_user(email, password)
            if user:
                st.session_state["user"] = user
                st.rerun()
            else:
                st.error("Invalid email or password.")
    st.stop()


user = st.session_state["user"]
user_email = normalize_email(user.get("email"))
is_admin = user_email == normalize_email(ADMIN_EMAIL)

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(f"""
    <div class="sb-brand">
        <div class="sb-logo">✦ Milana</div>
        <div class="sb-tagline">Sales Platform</div>
        <div class="sb-user">{html.escape(user_email)}</div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    if is_admin:
        nav_option = st.radio(
            "Navigation",
            ["📊 Overview", "💬 Chat", "📦 Business", "➕ Add Account",
             "📲 Telegram", "👥 Managers", "🔗 Access"],
        )
    else:
        nav_option = st.radio(
            "Navigation",
            ["📊 Overview", "💬 Chat", "📦 Business", "📲 Telegram"],
        )

    st.divider()

    if st.button("Sign Out", use_container_width=True):
        logout()


# ── Topbar ─────────────────────────────────────────────────────────────────────

businesses_for_header = get_allowed_businesses()
ig_cnt = get_message_count("instagram")
tg_cnt = get_message_count("telegram")

st.markdown(f"""
<div class="topbar">
    <div class="topbar-left">
        <div class="topbar-logo">M</div>
        <div>
            <div class="topbar-title">Sales Dashboard</div>
            <div class="topbar-sub">Instagram & Telegram · {'Admin' if is_admin else 'Manager'}</div>
        </div>
    </div>
    <div class="topbar-stat">
        <div class="topbar-stat-item">
            <div class="topbar-stat-num">{ig_cnt}</div>
            <div class="topbar-stat-label">IG Msgs</div>
        </div>
        <div class="topbar-stat-item">
            <div class="topbar-stat-num">{tg_cnt}</div>
            <div class="topbar-stat-label">TG Msgs</div>
        </div>
        <div class="topbar-stat-item">
            <div class="topbar-stat-num">{len(businesses_for_header)}</div>
            <div class="topbar-stat-label">Accounts</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)


# ── Pages ──────────────────────────────────────────────────────────────────────

def show_metrics():
    businesses = get_allowed_businesses()
    total = len(businesses)
    active = sum(1 for b in businesses if b.get("bot_enabled"))
    ig = get_message_count("instagram")
    tg = get_message_count("telegram")

    st.markdown(f"""
    <div class="metrics-row">
        <div class="metric-card">
            <div class="metric-icon">🏢</div>
            <div class="metric-num">{total}</div>
            <div class="metric-label">Sales Accounts</div>
        </div>
        <div class="metric-card">
            <div class="metric-icon">🤖</div>
            <div class="metric-num">{active}</div>
            <div class="metric-label">Auto Reply On</div>
        </div>
        <div class="metric-card">
            <div class="metric-icon">📸</div>
            <div class="metric-num">{ig}</div>
            <div class="metric-label">Instagram Messages</div>
        </div>
        <div class="metric-card">
            <div class="metric-icon">✈️</div>
            <div class="metric-num">{tg}</div>
            <div class="metric-label">Telegram Messages</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">🏢 Connected Accounts</div>', unsafe_allow_html=True)
    if businesses:
        for b in businesses[:8]:
            bot_badge = '<span class="badge badge-green">Auto reply ON</span>' if b.get("bot_enabled") else '<span class="badge badge-red">Off</span>'
            st.markdown(f"""
            <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border);">
                <span style="font-weight:600;font-size:14px;">{html.escape(b.get('business_name','—'))}</span>
                {bot_badge}
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No accounts configured yet.")
    st.markdown("</div>", unsafe_allow_html=True)


def show_chat():
    businesses = get_allowed_businesses()
    business_map = {b.get("id"): b for b in businesses if b.get("id")}
    business_ids = list(business_map.keys())

    if not businesses:
        st.warning("No sales accounts configured yet.")
        return

    # Filters
    f1, f2, f3 = st.columns([3, 1.2, 1])
    with f1:
        search_text = st.text_input("", placeholder="🔍  Search conversations…", label_visibility="collapsed")
    with f2:
        pf_label = st.selectbox("", ["All Platforms", "Instagram", "Telegram"], label_visibility="collapsed")
        pf = {"All Platforms": "all", "Instagram": "instagram", "Telegram": "telegram"}[pf_label]
    with f3:
        unread_only = st.toggle("Unread only", value=False)

    conversations = get_social_conversations(business_ids=business_ids, platform_filter=pf, search_text=search_text)
    if unread_only:
        conversations = [c for c in conversations if c.get("unread_count", 0) > 0]

    if not conversations:
        st.info("No conversations yet.")
        return

    left, right = st.columns([1, 2.5])

    with left:
        st.markdown('<div style="font-family:\'Syne\',sans-serif;font-weight:700;font-size:14px;color:#0a0a0f;margin-bottom:10px;">Conversations</div>', unsafe_allow_html=True)
        options = {}
        for c in conversations:
            platform = c.get("platform", "instagram")
            channel = c.get("channel", "")
            unread = c.get("unread_count", 0)
            unread_str = f" 🔴 {unread}" if unread else ""
            preview = str(c.get("last_message", ""))[:35]
            icon = "✈️" if platform == "telegram" else "📸"
            name = c.get("customer_name") or f"Client …{str(c.get('customer_id'))[-4:]}"
            if platform == "telegram" and channel == "telegram_user_private":
                src = "Private"
            elif platform == "telegram":
                src = "Bot"
            else:
                src = "Instagram"
            label = f"{icon} {name}{unread_str}\n{src} · {preview}"
            options[label] = c

        selected_label = st.radio("conv", list(options.keys()), label_visibility="collapsed")
        selected_conv = options[selected_label]

    with right:
        biz = business_map.get(selected_conv["business_id"])
        if not biz:
            st.error("Account not found.")
            return

        customer_id = selected_conv["customer_id"]
        chat_id = selected_conv.get("chat_id") or customer_id
        platform = selected_conv.get("platform", "instagram")
        channel = selected_conv.get("channel", "")
        customer_name = selected_conv.get("customer_name") or f"Client …{str(customer_id)[-4:]}"

        ai_enabled = get_chat_ai_enabled(biz["id"], platform, channel, customer_id)
        mark_conversation_read(biz["id"], customer_id, platform, channel)
        messages = get_conversation_messages(biz["id"], customer_id, platform, channel)

        # Chat header
        pt_class = "pt-tg" if platform == "telegram" else "pt-ig"
        pt_label = "Telegram" if platform == "telegram" else "Instagram"
        ai_chip_class = "on" if ai_enabled else "off"
        ai_dot_class = "on" if ai_enabled else "off"
        ai_label = "AI Reply ON" if ai_enabled else "AI Reply OFF"

        h1, h2 = st.columns([3, 1])
        with h1:
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:12px;padding:4px 0 12px;">
                <div class="conv-avatar {'av-tg' if platform == 'telegram' else 'av-ig'}">
                    {'TG' if platform == 'telegram' else 'IG'}
                </div>
                <div>
                    <div style="font-family:'Syne',sans-serif;font-weight:700;font-size:16px;color:var(--ink);">{html.escape(customer_name)}</div>
                    <span class="platform-tag {pt_class}">{pt_label}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with h2:
            new_ai = st.toggle("AI Reply", value=ai_enabled, key=f"ai_{platform}_{channel}_{customer_id}")
            if new_ai != ai_enabled:
                set_chat_ai_enabled(biz["id"], platform, channel, customer_id, new_ai)
                st.rerun()

        # Messages
        chat_container = st.container(height=420)
        with chat_container:
            bubbles_html = ""
            for msg in messages:
                bubbles_html += render_message_bubble(msg)
            st.markdown(bubbles_html, unsafe_allow_html=True)

        # Reply box
        st.divider()
        st.markdown("**Send a message**")

        media_mode = st.radio(
            "Type",
            ["✉️ Text", "📷 Photo", "🎥 Video", "🎙️ Voice/Audio", "📎 Document"],
            horizontal=True,
            key=f"media_mode_{customer_id}",
        )

        with st.form(key=f"reply_{customer_id}", clear_on_submit=True):
            reply_text = st.text_area("Message text", placeholder="Type your reply…", height=80, label_visibility="collapsed")

            uploaded_file = None
            if media_mode != "✉️ Text":
                type_map = {
                    "📷 Photo": ["jpg", "jpeg", "png", "gif", "webp"],
                    "🎥 Video": ["mp4", "mov", "avi", "mkv"],
                    "🎙️ Voice/Audio": ["ogg", "mp3", "m4a", "wav", "oga"],
                    "📎 Document": None,
                }
                accepted = type_map.get(media_mode)
                uploaded_file = st.file_uploader(
                    f"Upload {media_mode}",
                    type=accepted,
                    key=f"fu_{customer_id}_{media_mode}",
                )

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                send_btn = st.form_submit_button("Send ↗", type="primary", use_container_width=True)
            with c2:
                catalog_btn = st.form_submit_button("Catalog", use_container_width=True)
            with c3:
                phone_btn = st.form_submit_button("Contact", use_container_width=True)
            with c4:
                ask_btn = st.form_submit_button("Ask Product", use_container_width=True)

            quick_text = ""
            if catalog_btn:
                link = biz.get("catalog_link", "")
                quick_text = f"Katalogimiz: {link}" if link else "Qaysi mahsulot katalogi kerak edi?"
            elif phone_btn:
                phone = biz.get("sales_phone", "")
                quick_text = f"Savdo bo'limi: {phone}" if phone else "Telefon raqamingizni qoldiring."
            elif ask_btn:
                quick_text = "Qaysi mahsulot sizni qiziqtiryapti?"

            final_text = quick_text or reply_text.strip()

            mt_map = {
                "📷 Photo": "photo",
                "🎥 Video": "video",
                "🎙️ Voice/Audio": "voice",
                "📎 Document": "document",
            }
            send_media_type = mt_map.get(media_mode) if media_mode != "✉️ Text" else None

            if send_btn or catalog_btn or phone_btn or ask_btn:
                if not final_text.strip() and not uploaded_file:
                    st.error("Message or file required.")
                else:
                    file_bytes = uploaded_file.read() if uploaded_file else None
                    file_name = uploaded_file.name if uploaded_file else None

                    if platform == "instagram":
                        ok, result = send_instagram_dm_from_backend(
                            business_id=biz["id"],
                            customer_id=customer_id,
                            text=final_text,
                            media_type=send_media_type,
                            file_bytes=file_bytes,
                            file_name=file_name,
                        )

                    elif platform == "telegram" and channel in ["telegram_bot_private", "telegram_bot_group", "private", "group", "supergroup"]:
                        ok, result = send_telegram_bot_message(
                            chat_id=chat_id,
                            text=final_text,
                            media_type=send_media_type,
                            file_bytes=file_bytes,
                            file_name=file_name,
                        )
                        if ok:
                            save_outbound_message(
                                business=biz,
                                customer_id=customer_id,
                                text=final_text,
                                platform="telegram",
                                channel=channel or "telegram_bot_private",
                                chat_id=chat_id,
                                raw_payload=result,
                                media_type=send_media_type,
                            )

                    elif platform == "telegram" and channel == "telegram_user_private":
                        ok, result = send_telegram_user_message_from_backend(
                            customer_id=customer_id,
                            text=final_text,
                            media_type=send_media_type,
                            file_bytes=file_bytes,
                            file_name=file_name,
                        )
                    else:
                        ok, result = False, {"error": "Unsupported channel"}

                    if ok:
                        st.success("✅ Sent.")
                        time.sleep(0.4)
                        st.rerun()
                    else:
                        st.error("❌ Failed to send.")
                        st.json(result)


def business_editor(business):
    with st.form(key=f"edit_{business['id']}"):
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">🏢 Basic Info</div>', unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            bname = st.text_input("Account Name", value=business.get("business_name", "Milana Premium"))
            btype = st.text_input("Business Type", value=business.get("business_type", "Textile and Clothing"))
        with c2:
            lang_opts = ["uz", "ru", "en"]
            lang = business.get("language", "uz")
            language = st.selectbox("Language", lang_opts, index=lang_opts.index(lang) if lang in lang_opts else 0)
            tone = st.text_input("Sales Tone", value=business.get("tone", "friendly, polite, sales-focused"))

        bot_enabled = st.toggle("Enable Auto Reply", value=bool(business.get("bot_enabled", True)))
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">🤖 AI Configuration</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            rs_opts = ["short_comfortable", "very_short", "normal_sales"]
            rs = business.get("reply_style", "short_comfortable")
            reply_style = st.selectbox("Reply Style", rs_opts, index=rs_opts.index(rs) if rs in rs_opts else 0, disabled="reply_style" not in business)
            max_tokens = st.number_input("Answer Length", min_value=50, max_value=500, value=int(business.get("ai_max_tokens", 130) or 130), step=10, disabled="ai_max_tokens" not in business)
        with c2:
            cp_opts = ["only_when_customer_asks", "offer_when_relevant", "never_send"]
            cp = business.get("catalog_policy", "only_when_customer_asks")
            catalog_policy = st.selectbox("Catalog Rule", cp_opts, index=cp_opts.index(cp) if cp in cp_opts else 0, disabled="catalog_policy" not in business)
            temperature = st.number_input("Creativity", min_value=0.0, max_value=1.0, value=float(business.get("ai_temperature", 0.5) or 0.5), step=0.1, disabled="ai_temperature" not in business)
        ai_rules = st.text_area("AI Rules", value=business.get("ai_reply_rules", DEFAULT_AI_REPLY_RULES), height=140, disabled="ai_reply_rules" not in business)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">📦 Products & Info</div>', unsafe_allow_html=True)
        products = st.text_area("Products / Services", value=business.get("products", ""), height=90)
        prices = st.text_area("Prices", value=business.get("prices", ""), height=80)
        delivery = st.text_area("Delivery Info", value=business.get("delivery_info", ""), height=80)
        hours = st.text_area("Working Hours", value=business.get("working_hours", ""), height=70)
        faq = st.text_area("FAQ", value=business.get("faq", ""), height=110)
        catalog = st.text_input("Catalog Link", value=business.get("catalog_link", ""))
        phone = st.text_input("Sales Phone", value=business.get("sales_phone", ""))
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">🔗 Quick Links</div>', unsafe_allow_html=True)
        tg_single = st.text_input("Single Product Link", value=business.get("telegram_single", ""))
        tg_package = st.text_input("Package Link", value=business.get("telegram_package", ""))
        tg_bag = st.text_input("Bulk Order Link", value=business.get("telegram_bag", ""))
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">🧠 Knowledge Base</div>', unsafe_allow_html=True)
        knowledge = st.text_area("Knowledge", value=business.get("knowledge", ""), height=200)
        st.markdown("</div>", unsafe_allow_html=True)

        submitted = st.form_submit_button("💾 Save Configuration", type="primary", use_container_width=True)
        if submitted:
            update_data = {
                "business_name": bname.strip(), "business_type": btype.strip(),
                "language": language, "tone": tone.strip(), "bot_enabled": bot_enabled,
                "reply_style": reply_style, "catalog_policy": catalog_policy,
                "ai_reply_rules": ai_rules.strip(), "ai_max_tokens": int(max_tokens),
                "ai_temperature": float(temperature), "products": products.strip(),
                "prices": prices.strip(), "delivery_info": delivery.strip(),
                "working_hours": hours.strip(), "faq": faq.strip(),
                "catalog_link": catalog.strip(), "sales_phone": phone.strip(),
                "telegram_single": tg_single.strip(), "telegram_package": tg_package.strip(),
                "telegram_bag": tg_bag.strip(), "knowledge": knowledge.strip(),
            }
            try:
                safe_update_business(business, update_data)
                st.success("✅ Saved.")
                time.sleep(0.4)
                st.rerun()
            except Exception as e:
                st.error(f"❌ {e}")


# ── Page routing ───────────────────────────────────────────────────────────────

if nav_option == "📊 Overview":
    show_metrics()

elif nav_option == "💬 Chat":
    show_chat()

elif nav_option == "📦 Business":
    businesses = get_allowed_businesses()
    if not businesses:
        st.warning("No accounts configured.")
    else:
        if len(businesses) == 1:
            business = businesses[0]
        else:
            opts = {f"{b.get('business_name','Milana')} | IG: {b.get('instagram_business_id','—')}": b for b in businesses}
            selected = st.selectbox("Account", list(opts.keys()))
            business = opts[selected]
        business_editor(business)

elif nav_option == "➕ Add Account" and is_admin:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">➕ New Sales Account</div>', unsafe_allow_html=True)
    with st.form("add_biz"):
        name = st.text_input("Account Name", value="Milana Premium")
        ig_id = st.text_input("Instagram Business ID *")
        fb_id = st.text_input("Facebook Page ID")
        knowledge = st.text_area("Knowledge Base", height=150)
        if st.form_submit_button("✨ Create", type="primary", use_container_width=True):
            if not name.strip() or not ig_id.strip():
                st.error("Name and Instagram ID required.")
            else:
                try:
                    create_business({
                        "business_name": name.strip(), "instagram_business_id": ig_id.strip(),
                        "facebook_page_id": fb_id.strip(), "business_type": "Textile and Clothing",
                        "language": "uz", "tone": "friendly, polite, sales-focused",
                        "bot_enabled": False, "knowledge": knowledge.strip(),
                        "access_token": "", "page_access_token": "", "oauth_provider": "",
                        "facebook_page_name": "", "products": "", "prices": "",
                        "delivery_info": "", "working_hours": "", "faq": "",
                        "catalog_link": "", "sales_phone": "",
                        "telegram_single": "", "telegram_package": "", "telegram_bag": "",
                    })
                    st.success("✅ Created.")
                    time.sleep(0.4)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {e}")
    st.markdown("</div>", unsafe_allow_html=True)

elif nav_option == "📲 Telegram":
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">📲 Telegram Bot Setup</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Bot Token", "✅ Set" if TELEGRAM_BOT_TOKEN else "❌ Missing")
    with c2:
        st.metric("Bot Username", f"@{TELEGRAM_BOT_USERNAME.replace('@','')}" if TELEGRAM_BOT_USERNAME else "—")
    with c3:
        st.metric("Telegram Messages", get_message_count("telegram"))

    st.markdown("**Webhook URL**")
    st.code(telegram_webhook_url())

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("🔗 Set Webhook"):
            ok, data = set_telegram_webhook()
            st.json(data)
    with b2:
        if st.button("✓ Check Webhook"):
            ok, data = get_telegram_webhook_info()
            st.json(data)
    with b3:
        st.link_button("📌 Open", f"{BACKEND_URL}/webhook/telegram", use_container_width=True)

    st.markdown("**Media Support**")
    st.info("Bot supports receiving and sending: photos, videos, voice notes, audio files, and documents. "
            "Private user client (Telethon) also supports full media via the backend.")
    st.markdown("</div>", unsafe_allow_html=True)

elif nav_option == "👥 Managers" and is_admin:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">👥 Manager Accounts</div>', unsafe_allow_html=True)
    with st.expander("Create / Reset Manager", expanded=True):
        eu = st.text_input("Email")
        pu = st.text_input("Password", type="password")
        if st.button("Save", use_container_width=True):
            if eu and pu:
                create_or_update_dashboard_user(eu, pu)
                st.success("✅ Saved.")
                st.rerun()
            else:
                st.error("Email and password required.")
    users = get_all_dashboard_users()
    if users:
        st.dataframe(users, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

elif nav_option == "🔗 Access" and is_admin:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">🔗 Access Control</div>', unsafe_allow_html=True)
    all_biz = get_all_businesses()
    if not all_biz:
        st.warning("No accounts found.")
    else:
        biz_map = {f"{b.get('business_name','—')} ({b.get('id','')[:8]})": b["id"] for b in all_biz}
        ea = st.text_input("Manager Email")
        sb = st.selectbox("Account", list(biz_map.keys()))
        role = st.selectbox("Role", ["owner", "editor"])
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✓ Assign", use_container_width=True):
                if ea:
                    assign_business_to_user(ea, biz_map[sb], role)
                    st.success("✅ Assigned.")
                    st.rerun()
        with c2:
            if st.button("✕ Remove", use_container_width=True):
                if ea:
                    remove_business_assignment(ea, biz_map[sb])
                    st.success("✅ Removed.")
                    st.rerun()
        assignments = get_business_assignments()
        if assignments:
            st.dataframe(assignments, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)
