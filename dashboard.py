import os
import hmac
import html
import hashlib
import requests
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

st.set_page_config(
    page_title="InsaAgent Sales Dashboard",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
* { font-family: Inter, Arial, sans-serif; }

html, body, [data-testid="stAppViewContainer"] {
    background: #f8fafc;
}

.main-header {
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    border-radius: 18px;
    padding: 34px;
    color: white;
    margin-bottom: 24px;
    box-shadow: 0 18px 40px rgba(99,102,241,.2);
}

.main-header h1 {
    margin: 0;
    font-size: 38px;
    font-weight: 800;
}

.main-header p {
    margin-top: 8px;
    color: rgba(255,255,255,.9);
}

.stat-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    padding: 20px;
    text-align: center;
    box-shadow: 0 1px 4px rgba(0,0,0,.04);
}

.stat-value {
    font-size: 34px;
    font-weight: 800;
    color: #4f46e5;
}

.stat-label {
    font-size: 12px;
    color: #64748b;
    text-transform: uppercase;
    font-weight: 700;
}

.conversation-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    padding: 14px;
    margin-bottom: 10px;
}

.conversation-card:hover {
    border-color: #6366f1;
    background: #f8f7ff;
}

.badge {
    display: inline-block;
    padding: 4px 9px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
}

.badge-instagram { background: #fce7f3; color: #db2777; }
.badge-telegram { background: #dbeafe; color: #2563eb; }
.badge-whatsapp { background: #dcfce7; color: #16a34a; }

.message {
    display: flex;
    width: 100%;
    margin-bottom: 10px;
}

.message.inbound {
    justify-content: flex-start;
}

.message.outbound {
    justify-content: flex-end;
}

.message-bubble {
    max-width: 74%;
    padding: 12px 14px;
    border-radius: 14px;
    font-size: 14px;
    line-height: 1.5;
    word-wrap: break-word;
}

.message.inbound .message-bubble {
    background: white;
    border: 1px solid #e5e7eb;
    color: #0f172a;
    border-bottom-left-radius: 4px;
}

.message.outbound .message-bubble {
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    color: white;
    border-bottom-right-radius: 4px;
}

.message-media {
    max-width: 100%;
    max-height: 320px;
    border-radius: 10px;
    margin-bottom: 8px;
}

.message-time {
    font-size: 10px;
    opacity: .65;
    margin-top: 5px;
}

.small-muted {
    color: #64748b;
    font-size: 12px;
}

.login-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 18px;
    padding: 38px;
    max-width: 520px;
    margin: 80px auto;
    box-shadow: 0 10px 30px rgba(0,0,0,.06);
}

.stButton button {
    border-radius: 10px !important;
    font-weight: 700 !important;
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
DASHBOARD_SECRET = get_secret("DASHBOARD_SECRET", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not DASHBOARD_SECRET:
    st.error("Missing SUPABASE_URL, SUPABASE_SERVICE_KEY, or DASHBOARD_SECRET.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def normalize_email(email):
    return str(email or "").strip().lower()


def hash_password(password):
    return hashlib.sha256((password + DASHBOARD_SECRET).encode()).hexdigest()


def verify_password(password, password_hash):
    if not password or not password_hash:
        return False
    return hmac.compare_digest(hash_password(password), password_hash)


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def login_user(email, password):
    try:
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

    except Exception as e:
        st.error(f"Login error: {e}")
        return None


def list_dashboard_users():
    try:
        return (
            supabase.table("dashboard_users")
            .select("id,email,is_active,created_at")
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
    except Exception as e:
        st.error(f"Could not load users: {e}")
        return []


def create_or_update_dashboard_user(email, password, is_active=True):
    clean_email = normalize_email(email)
    if not clean_email or not password:
        raise ValueError("Email and password are required.")

    payload = {
        "email": clean_email,
        "password_hash": hash_password(password),
        "is_active": bool(is_active),
    }
    return (
        supabase.table("dashboard_users")
        .upsert(payload, on_conflict="email")
        .execute()
    )


def set_dashboard_user_active(email, is_active):
    clean_email = normalize_email(email)
    if not clean_email:
        return None
    return (
        supabase.table("dashboard_users")
        .update({"is_active": bool(is_active)})
        .eq("email", clean_email)
        .execute()
    )


def assign_user_business(user_email, business_id, role="owner"):
    clean_email = normalize_email(user_email)
    if not clean_email or not business_id:
        raise ValueError("Email and business are required.")
    payload = {
        "user_email": clean_email,
        "business_id": business_id,
        "role": role or "owner",
    }
    return (
        supabase.table("business_users")
        .upsert(payload, on_conflict="user_email,business_id")
        .execute()
    )


def remove_user_business(user_email, business_id):
    clean_email = normalize_email(user_email)
    if not clean_email or not business_id:
        return None
    return (
        supabase.table("business_users")
        .delete()
        .eq("user_email", clean_email)
        .eq("business_id", business_id)
        .execute()
    )


def get_user_business_links(user_email):
    clean_email = normalize_email(user_email)
    if not clean_email:
        return []
    try:
        return (
            supabase.table("business_users")
            .select("business_id,role")
            .eq("user_email", clean_email)
            .execute()
            .data
            or []
        )
    except Exception:
        return []


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

    if not business_ids:
        return []

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


def get_message_count(platform=None, business_ids=None):
    try:
        q = supabase.table("inbox_messages").select("id", count="exact")

        if platform:
            q = q.eq("platform", platform)

        if business_ids:
            q = q.in_("business_id", business_ids)

        result = q.execute()
        return result.count or 0

    except Exception:
        return 0


def update_business(business_id, data):
    return supabase.table("businesses").update(data).eq("id", business_id).execute()


def safe_update_business(business, data):
    existing_keys = set(business.keys())
    filtered = {k: v for k, v in data.items() if k in existing_keys}

    if not filtered:
        return None

    return update_business(business["id"], filtered)


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
    }

    try:
        return (
            supabase.table("chat_ai_settings")
            .upsert(data, on_conflict="business_id,platform,channel,customer_id")
            .execute()
        )
    except Exception:
        return (
            supabase.table("chat_ai_settings")
            .upsert(data, on_conflict="platform,channel,customer_id")
            .execute()
        )


def normalized_platform_channel(platform, channel, chat_id=""):
    p = str(platform or "").strip().lower() or "instagram"
    ch = str(channel or "").strip().lower()
    chat = str(chat_id or "").strip()

    if p == "instagram":
        return "instagram", "dm"
    if p == "whatsapp":
        return "whatsapp", "whatsapp"
    if p == "telegram":
        if "group" in ch or chat.startswith("-"):
            return "telegram", "telegram_bot_group"
        if ch == "telegram_user_private":
            return "telegram", "telegram_user_private"
        return "telegram", "telegram_bot_private"
    return p, ch


def is_telegram_group(platform, channel, chat_id):
    p = str(platform or "").lower()
    ch = str(channel or "").lower()
    chat = str(chat_id or "")
    return p == "telegram" and ("group" in ch or chat.startswith("-"))


def conversation_identity_from_row(row):
    business_id = row.get("business_id")
    platform, channel = normalized_platform_channel(
        row.get("platform"),
        row.get("channel"),
        row.get("chat_id"),
    )
    customer_id = str(row.get("customer_id") or "").strip()
    chat_id = str(row.get("chat_id") or "").strip()

    if is_telegram_group(platform, channel, chat_id):
        thread_scope = "group"
        thread_id = chat_id
        ai_customer_key = chat_id
        ai_channel = "telegram_group"
    else:
        thread_scope = "private"
        thread_id = customer_id
        ai_customer_key = customer_id
        if platform == "telegram":
            ai_channel = "telegram_private"
        elif platform == "instagram":
            ai_channel = "dm"
        elif platform == "whatsapp":
            ai_channel = "whatsapp"
        else:
            ai_channel = channel or ""

    conversation_id = f"{business_id}::{platform}::{thread_scope}::{thread_id}"
    return {
        "business_id": business_id,
        "platform": platform,
        "channel": channel,
        "customer_id": customer_id,
        "chat_id": chat_id or customer_id,
        "thread_scope": thread_scope,
        "thread_id": thread_id,
        "conversation_id": conversation_id,
        "ai_customer_key": ai_customer_key,
        "ai_channel": ai_channel,
    }


def get_chat_ai_enabled_for_conversation(conversation):
    business_id = conversation["business_id"]
    platform = conversation["platform"]
    ai_channel = conversation.get("ai_channel", conversation.get("channel") or "")
    ai_customer_key = conversation.get("ai_customer_key") or conversation["customer_id"]
    return get_chat_ai_enabled(business_id, platform, ai_channel, ai_customer_key)


def set_chat_ai_enabled_for_conversation(conversation, enabled):
    business_id = conversation["business_id"]
    platform = conversation["platform"]
    ai_channel = conversation.get("ai_channel", conversation.get("channel") or "")
    ai_customer_key = conversation.get("ai_customer_key") or conversation["customer_id"]
    return set_chat_ai_enabled(business_id, platform, ai_channel, ai_customer_key, enabled)


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
        identity = conversation_identity_from_row(row)
        business_id = identity["business_id"]
        platform = identity["platform"]
        channel = identity["channel"]
        customer_id = identity["customer_id"]
        chat_id = identity["chat_id"]
        thread_scope = identity["thread_scope"]
        thread_id = identity["thread_id"]
        key = identity["conversation_id"]

        if not business_id or not thread_id:
            continue

        if platform == "telegram":
            if thread_scope == "group":
                fallback_name = f"Telegram Group {thread_id[-6:]}"
            else:
                fallback_name = f"Telegram Client {customer_id[-4:]}"
        elif platform == "whatsapp":
            fallback_name = f"WhatsApp Client {customer_id[-4:]}"
        else:
            fallback_name = f"Instagram Client {customer_id[-4:]}"

        if key not in conversations:
            conversations[key] = {
                "conversation_id": identity["conversation_id"],
                "business_id": business_id,
                "platform": platform,
                "channel": channel,
                "customer_id": customer_id,
                "chat_id": chat_id,
                "thread_scope": thread_scope,
                "thread_id": thread_id,
                "ai_channel": identity["ai_channel"],
                "ai_customer_key": identity["ai_customer_key"],
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
        st.error(f"Could not load conversation: {e}")
        return []


def get_conversation_messages_for_conversation(conversation, limit=250):
    try:
        business_id = conversation["business_id"]
        platform = conversation["platform"]
        thread_scope = conversation.get("thread_scope", "private")
        customer_id = str(conversation.get("customer_id") or "")
        chat_id = str(conversation.get("chat_id") or customer_id)

        query = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", platform)
            .eq("business_id", business_id)
        )

        if platform == "telegram" and thread_scope == "group":
            query = query.eq("chat_id", chat_id)
        else:
            query = query.eq("customer_id", customer_id)

        return (
            query.order("created_at", desc=False)
            .limit(limit)
            .execute()
            .data
            or []
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


def mark_conversation_read_for_conversation(conversation):
    try:
        business_id = conversation["business_id"]
        platform = conversation["platform"]
        thread_scope = conversation.get("thread_scope", "private")
        customer_id = str(conversation.get("customer_id") or "")
        chat_id = str(conversation.get("chat_id") or customer_id)

        query = (
            supabase.table("inbox_messages")
            .update({"is_read": True})
            .eq("platform", platform)
            .eq("business_id", business_id)
            .eq("direction", "inbound")
        )

        if platform == "telegram" and thread_scope == "group":
            query = query.eq("chat_id", chat_id)
        else:
            query = query.eq("customer_id", customer_id)

        query.execute()
    except Exception:
        pass


def save_local_outbound_message(conversation, text, raw_payload=None):
    try:
        data = {
            "business_id": conversation["business_id"],
            "platform": conversation["platform"],
            "customer_id": str(conversation["customer_id"]),
            "customer_name": conversation.get("customer_name") or str(conversation["customer_id"]),
            "chat_id": str(conversation.get("chat_id") or conversation["customer_id"]),
            "channel": conversation.get("channel") or "",
            "direction": "outbound",
            "role": "assistant",
            "content": text,
            "external_message_id": "",
            "raw_payload": raw_payload or {},
            "is_read": True,
        }

        try:
            supabase.table("inbox_messages").insert(data).execute()
        except Exception:
            fallback = dict(data)
            fallback.pop("customer_name", None)
            fallback.pop("chat_id", None)
            fallback.pop("is_read", None)
            supabase.table("inbox_messages").insert(fallback).execute()

    except Exception:
        pass


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


def send_telegram_message_from_backend(customer_id, text, chat_id=None):
    target_chat_id = str(chat_id or customer_id)
    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-telegram-message",
        json={
            "customer_id": str(customer_id),
            "chat_id": target_chat_id,
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


def send_whatsapp_message_from_backend(customer_id, text):
    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-whatsapp-message",
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


def send_message_by_platform(conversation, text):
    platform = conversation["platform"]
    business_id = conversation["business_id"]
    customer_id = conversation["customer_id"]
    chat_id = conversation.get("chat_id") or customer_id

    if platform == "instagram":
        return send_instagram_dm_from_backend(business_id, customer_id, text)

    if platform == "telegram":
        return send_telegram_message_from_backend(customer_id, text, chat_id=chat_id)

    if platform == "whatsapp":
        return send_whatsapp_message_from_backend(customer_id, text)

    return False, {"error": f"Unsupported platform: {platform}"}


def platform_badge(platform):
    if platform == "telegram":
        return '<span class="badge badge-telegram">Telegram</span>'
    if platform == "whatsapp":
        return '<span class="badge badge-whatsapp">WhatsApp</span>'
    return '<span class="badge badge-instagram">Instagram</span>'


def render_message(msg):
    direction = msg.get("direction")
    content = html.escape(str(msg.get("content", ""))).replace("\n", "<br>")
    created_at = html.escape(str(msg.get("created_at", "")))
    media_type = msg.get("media_type")
    media_url = msg.get("media_url")

    message_class = "outbound" if direction == "outbound" else "inbound"

    html_content = f'<div class="message {message_class}"><div class="message-bubble">'

    if media_type == "photo" and media_url:
        html_content += f'<img src="{html.escape(media_url)}" class="message-media" loading="lazy" alt="Photo">'
    elif media_type == "video" and media_url:
        html_content += f'<video controls class="message-media"><source src="{html.escape(media_url)}" type="video/mp4"></video>'
    elif media_type in ["voice", "audio"] and media_url:
        html_content += f'<audio controls class="message-media"><source src="{html.escape(media_url)}"></audio>'
    elif media_type == "file" and media_url:
        html_content += f'<a href="{html.escape(media_url)}" target="_blank">Open file</a><br>'

    if content:
        html_content += f'<div>{content}</div>'

    html_content += f'<div class="message-time">{created_at}</div>'
    html_content += '</div></div>'

    st.markdown(html_content, unsafe_allow_html=True)


def business_editor(business):
    st.subheader("Business Settings")

    with st.form(key=f"business_form_{business['id']}"):
        col1, col2 = st.columns(2)

        with col1:
            business_name = st.text_input("Business name", value=business.get("business_name", ""))
            business_type = st.text_input("Business type", value=business.get("business_type", ""))

        with col2:
            language_options = ["uz", "ru", "en"]
            current_language = business.get("language", "uz")
            language_index = language_options.index(current_language) if current_language in language_options else 0
            language = st.selectbox("Main language", language_options, index=language_index)
            tone = st.text_input("Tone", value=business.get("tone", "friendly, polite, sales-focused"))

        bot_enabled = st.toggle("Enable automation for this business", value=bool(business.get("bot_enabled", True)))
        auto_reply_dms = st.toggle("Instagram DM auto-reply", value=bool(business.get("auto_reply_dms", True)))
        auto_reply_comments = st.toggle("Instagram comment auto-reply", value=bool(business.get("auto_reply_comments", True)))

        st.caption("WhatsApp and Telegram auto-replies use the main business automation toggle plus per-chat AI toggles.")

        st.divider()

        products = st.text_area("Products / Services", value=business.get("products", ""), height=120)
        prices = st.text_area("Prices", value=business.get("prices", ""), height=100)
        delivery_info = st.text_area("Delivery info", value=business.get("delivery_info", ""), height=100)
        working_hours = st.text_input("Working hours", value=business.get("working_hours", ""))
        faq = st.text_area("FAQ", value=business.get("faq", ""), height=120)
        catalog_link = st.text_input("Catalog link", value=business.get("catalog_link", ""))
        sales_phone = st.text_input("Sales phone", value=business.get("sales_phone", ""))

        knowledge = st.text_area("Main knowledge prompt", value=business.get("knowledge", ""), height=180)

        col1, col2 = st.columns(2)
        with col1:
            ai_max_tokens = st.slider(
                "AI answer length",
                50,
                500,
                safe_int(business.get("ai_max_tokens", 130), 130),
                10,
            )
        with col2:
            ai_temperature = st.slider(
                "AI creativity",
                0.0,
                1.0,
                safe_float(business.get("ai_temperature", 0.5), 0.5),
                0.1,
            )

        submitted = st.form_submit_button("Save settings", type="primary")

        if submitted:
            data = {
                "business_name": business_name,
                "business_type": business_type,
                "language": language,
                "tone": tone,
                "bot_enabled": bot_enabled,
                "auto_reply_dms": auto_reply_dms,
                "auto_reply_comments": auto_reply_comments,
                "products": products,
                "prices": prices,
                "delivery_info": delivery_info,
                "working_hours": working_hours,
                "faq": faq,
                "catalog_link": catalog_link,
                "sales_phone": sales_phone,
                "knowledge": knowledge,
                "ai_max_tokens": ai_max_tokens,
                "ai_temperature": ai_temperature,
            }

            try:
                safe_update_business(business, data)
                st.success("Saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")


def render_social_inbox(businesses):
    business_ids = [b["id"] for b in businesses]

    st.subheader("Social Sales Chat")

    left, right = st.columns([1, 2.1])

    with left:
        platform_filter = st.selectbox(
            "Platform",
            ["all", "instagram", "telegram", "whatsapp"],
            format_func=lambda x: {
                "all": "All platforms",
                "instagram": "Instagram",
                "telegram": "Telegram",
                "whatsapp": "WhatsApp",
            }.get(x, x),
        )

        search_text = st.text_input("Search chats", placeholder="Name, phone, ID, message...")

        conversations = get_social_conversations(
            business_ids=business_ids,
            platform_filter=platform_filter,
            search_text=search_text,
        )

        st.caption(f"{len(conversations)} conversations")

        if not conversations:
            st.info("No conversations yet.")
            return

        for i, conv in enumerate(conversations):
            unread = conv.get("unread_count", 0)
            selected = st.session_state.get("selected_conversation_id") == conv["conversation_id"]

            with st.container():
                st.markdown(
                    f"""
                    <div class="conversation-card">
                        {platform_badge(conv["platform"])}
                        <b style="display:block;margin-top:8px;">{html.escape(conv["customer_name"])}</b>
                        <div class="small-muted">{html.escape(conv["customer_id"])}</div>
                        <div style="margin-top:8px;color:#475569;font-size:13px;">
                            {html.escape(str(conv.get("last_message", ""))[:90])}
                        </div>
                        <div class="small-muted" style="margin-top:6px;">
                            Unread: {unread} · Messages: {conv.get("total_messages", 0)}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if st.button(
                    "Open" if not selected else "Opened",
                    key=f"open_conv_{i}_{conv['conversation_id']}",
                    use_container_width=True,
                    type="primary" if selected else "secondary",
                ):
                    st.session_state["selected_conversation_id"] = conv["conversation_id"]
                    st.session_state["selected_conversation"] = conv
                    mark_conversation_read_for_conversation(conv)
                    st.rerun()

    with right:
        conv = st.session_state.get("selected_conversation")

        if not conv:
            st.info("Open a conversation from the left.")
            return

        selected_business = next((b for b in businesses if b["id"] == conv["business_id"]), None)

        st.markdown(
            f"""
            <div style="background:white;border:1px solid #e5e7eb;border-radius:16px;padding:18px;margin-bottom:16px;">
                {platform_badge(conv["platform"])}
                <h3 style="margin:10px 0 4px 0;">{html.escape(conv["customer_name"])}</h3>
                <div class="small-muted">
                    Customer ID: {html.escape(conv["customer_id"])}<br>
                    Channel: {html.escape(conv.get("channel") or "-")}<br>
                    Business: {html.escape(selected_business.get("business_name", "") if selected_business else "")}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        ai_enabled = get_chat_ai_enabled_for_conversation(conv)

        new_ai_enabled = st.toggle(
            f"AI auto-reply for this {conv['platform']} chat",
            value=ai_enabled,
            key=f"ai_toggle_{conv['conversation_id']}",
        )

        if new_ai_enabled != ai_enabled:
            set_chat_ai_enabled_for_conversation(conv, new_ai_enabled)
            st.success("AI setting updated.")
            st.rerun()

        messages = get_conversation_messages_for_conversation(conv)

        st.divider()

        message_box = st.container(height=520)

        with message_box:
            for msg in messages:
                render_message(msg)

        st.divider()

        draft_key = f"reply_text_{conv['conversation_id']}"
        if draft_key not in st.session_state:
            st.session_state[draft_key] = ""

        reply_text = st.text_area(
            "Message",
            placeholder=f"Write a {conv['platform']} reply...",
            height=100,
            key=draft_key,
        )

        col1, col2 = st.columns([1, 4])

        with col1:
            send_clicked = st.button("Send", type="primary", use_container_width=True, key=f"send_{conv['conversation_id']}")

        with col2:
            st.caption("Manual messages are sent through your backend.")

        if send_clicked:
            message_to_send = reply_text.strip()

            if not message_to_send:
                st.warning("Write a message first.")
            else:
                ok, data = send_message_by_platform(conv, message_to_send)

                if ok and data.get("status") != "error":
                    save_local_outbound_message(conv, message_to_send, data)
                    st.success("Message sent.")
                    st.session_state.pop(draft_key, None)
                    st.rerun()
                else:
                    st.error(f"Send failed: {data}")


def render_overview(businesses):
    business_ids = [b["id"] for b in businesses]

    total_accounts = len(businesses)
    active_accounts = sum(1 for b in businesses if b.get("bot_enabled"))

    instagram_count = get_message_count("instagram", business_ids)
    telegram_count = get_message_count("telegram", business_ids)
    whatsapp_count = get_message_count("whatsapp", business_ids)

    st.markdown("""
    <div class="main-header">
        <h1>InsaAgent Dashboard</h1>
        <p>Instagram, Telegram, and WhatsApp sales automation in one inbox.</p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)

    cards = [
        ("Accounts", total_accounts),
        ("Active", active_accounts),
        ("Instagram", instagram_count),
        ("Telegram", telegram_count),
        ("WhatsApp", whatsapp_count),
    ]

    for col, (label, value) in zip([c1, c2, c3, c4, c5], cards):
        with col:
            st.markdown(
                f"""
                <div class="stat-card">
                    <div class="stat-value">{value}</div>
                    <div class="stat-label">{label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_admin_users_page(businesses):
    st.subheader("User Management")
    st.caption("Create business logins, assign business access, reset passwords, and deactivate users.")

    business_options = {
        (b.get("business_name") or str(b.get("id"))): b["id"]
        for b in businesses
    }

    with st.form("create_user_form"):
        st.markdown("### Create or update login")
        col1, col2 = st.columns(2)
        with col1:
            user_email = st.text_input("User email", placeholder="owner@company.com")
        with col2:
            user_password = st.text_input("Temporary password", type="password")
        col3, col4 = st.columns(2)
        with col3:
            user_active = st.toggle("Active", value=True)
        with col4:
            user_role = st.selectbox("Role", ["owner", "manager", "agent"])
        assigned_business = st.selectbox("Assign business", list(business_options.keys()) if business_options else [])
        submit_create = st.form_submit_button("Create / Update user", type="primary")

        if submit_create:
            try:
                create_or_update_dashboard_user(user_email, user_password, user_active)
                if assigned_business:
                    assign_user_business(user_email, business_options[assigned_business], user_role)
                st.success("User saved and business access assigned.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save user: {e}")

    st.divider()

    users = list_dashboard_users()
    if not users:
        st.info("No users found.")
        return

    for idx, user in enumerate(users):
        email = normalize_email(user.get("email"))
        if not email:
            continue
        links = get_user_business_links(email)
        link_text = ", ".join([f"{x.get('business_id')} ({x.get('role','owner')})" for x in links]) or "No business assigned"

        with st.expander(f"{email} · {'active' if user.get('is_active') else 'inactive'}"):
            st.caption(f"Created: {user.get('created_at')}")
            st.caption(f"Business links: {link_text}")

            col1, col2 = st.columns(2)
            with col1:
                new_password = st.text_input("Reset password", type="password", key=f"pw_{idx}")
                if st.button("Save new password", key=f"save_pw_{idx}", use_container_width=True):
                    if not new_password:
                        st.warning("Password cannot be empty.")
                    else:
                        try:
                            create_or_update_dashboard_user(email, new_password, bool(user.get("is_active", True)))
                            st.success("Password updated.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Password update failed: {e}")

            with col2:
                activate = not bool(user.get("is_active", True))
                btn = "Activate user" if activate else "Deactivate user"
                if st.button(btn, key=f"toggle_{idx}", use_container_width=True):
                    try:
                        set_dashboard_user_active(email, activate)
                        st.success("User status updated.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Status update failed: {e}")

            if business_options:
                st.markdown("#### Business access")
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    selected_business = st.selectbox(
                        "Business",
                        list(business_options.keys()),
                        key=f"biz_pick_{idx}",
                    )
                with c2:
                    selected_role = st.selectbox("Role", ["owner", "manager", "agent"], key=f"role_pick_{idx}")
                with c3:
                    if st.button("Assign", key=f"assign_{idx}", use_container_width=True):
                        try:
                            assign_user_business(email, business_options[selected_business], selected_role)
                            st.success("Business assigned.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Assign failed: {e}")

                if links:
                    for j, link in enumerate(links):
                        bid = link.get("business_id")
                        role = link.get("role", "owner")
                        row_c1, row_c2 = st.columns([4, 1])
                        with row_c1:
                            st.write(f"{bid} ({role})")
                        with row_c2:
                            if st.button("Remove", key=f"unlink_{idx}_{j}", use_container_width=True):
                                try:
                                    remove_user_business(email, bid)
                                    st.success("Business access removed.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Remove failed: {e}")


def login_screen():
    st.markdown('<div class="login-card">', unsafe_allow_html=True)
    st.title("InsaAgent Login")
    st.caption("Login to manage Instagram, Telegram, and WhatsApp automation.")

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if st.button("Login", type="primary", use_container_width=True):
        user = login_user(email, password)

        if user:
            st.session_state["logged_in"] = True
            st.session_state["user_email"] = normalize_email(email)
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("Invalid email or password.")

    st.markdown("</div>", unsafe_allow_html=True)


if not st.session_state.get("logged_in"):
    login_screen()
    st.stop()


user_email = st.session_state.get("user_email", "")
is_admin = normalize_email(user_email) == normalize_email(ADMIN_EMAIL)

with st.sidebar:
    st.title("InsaAgent")
    st.caption(user_email)

    if st.button("Logout", use_container_width=True):
        logout()

    st.divider()

    menu_items = ["Overview", "Social Sales Chat", "Business Settings", "Webhook Info"]
    if is_admin:
        menu_items.insert(3, "User Management")
    page = st.radio("Menu", menu_items)

if is_admin:
    businesses = get_all_businesses()
else:
    businesses = get_user_businesses(user_email)

if not businesses:
    st.warning("No businesses assigned to this user.")
    st.stop()

if page == "Overview":
    render_overview(businesses)

elif page == "Social Sales Chat":
    render_overview(businesses)
    st.divider()
    render_social_inbox(businesses)

elif page == "Business Settings":
    selected_business_name = st.selectbox(
        "Select business",
        [b.get("business_name", b["id"]) for b in businesses],
    )

    selected_business = next(
        b for b in businesses
        if b.get("business_name", b["id"]) == selected_business_name
    )

    business_editor(selected_business)

elif page == "User Management":
    if not is_admin:
        st.error("Only admin can access user management.")
    else:
        render_admin_users_page(get_all_businesses())

elif page == "Webhook Info":
    st.subheader("Webhook URLs")

    st.code(f"{PUBLIC_BASE_URL}/webhook", language="text")
    st.caption("Use this for Meta Instagram/Facebook/WhatsApp shared webhook.")

    st.code(f"{PUBLIC_BASE_URL}/webhook/telegram", language="text")
    st.caption("Use this for Telegram bot webhook.")

    st.subheader("Backend")
    st.code(BACKEND_URL, language="text")

    st.subheader("Required backend env vars for WhatsApp")
    st.code("""
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
VERIFY_TOKEN=1234
GRAPH_VERSION=v21.0
""", language="env")

    st.subheader("Dashboard required env vars / secrets")
    st.code("""
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
DASHBOARD_SECRET=...
ADMIN_EMAIL=...
BACKEND_URL=https://agent-1-xi6h.onrender.com
PUBLIC_BASE_URL=https://agent-1-xi6h.onrender.com
""", language="env")
