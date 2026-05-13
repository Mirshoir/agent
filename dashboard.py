import os
import hmac
import time
import html
import hashlib
import requests
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

st.set_page_config(
    page_title="Milana Premium Social Sales Chat",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.main-header {
    background: linear-gradient(135deg,#111827,#7c2d12,#be123c);
    border-radius: 26px;
    padding: 22px 28px;
    color: white;
    margin-bottom: 22px;
}
.metric-card {
    background: rgba(120,120,120,0.08);
    border-radius: 22px;
    border: 1px solid rgba(120,120,120,0.18);
    padding: 20px;
    text-align: center;
}
.metric-value {
    font-size: 34px;
    font-weight: 800;
}
.metric-label {
    opacity: .75;
    font-size: 13px;
}
.login-card {
    background: rgba(120,120,120,0.08);
    border: 1px solid rgba(120,120,120,0.18);
    border-radius: 24px;
    padding: 26px;
    margin-bottom: 18px;
}
.chat-shell {
    border: 1px solid rgba(120,120,120,0.18);
    border-radius: 24px;
    padding: 16px;
    background: rgba(120,120,120,0.04);
}
.chat-top {
    border-bottom: 1px solid rgba(120,120,120,0.18);
    padding-bottom: 12px;
    margin-bottom: 12px;
}
.inbound-msg {
    background: rgba(229,231,235,0.22);
    border: 1px solid rgba(120,120,120,0.15);
    border-radius: 20px 20px 20px 6px;
    padding: 12px 14px;
    margin: 10px 0;
    max-width: 76%;
}
.outbound-msg {
    background: linear-gradient(135deg,#c026d3,#e11d48);
    color: white;
    border-radius: 20px 20px 6px 20px;
    padding: 12px 14px;
    margin: 10px 0 10px auto;
    max-width: 76%;
}
.small-muted {
    opacity: .65;
    font-size: 12px;
    margin-top: 4px;
}
.avatar {
    width: 38px;
    height: 38px;
    border-radius: 999px;
    background: linear-gradient(135deg,#c026d3,#e11d48);
    color: white;
    display: inline-flex;
    align-items:center;
    justify-content:center;
    font-weight:800;
    margin-right:10px;
}
.platform-badge {
    display:inline-block;
    padding:4px 9px;
    border-radius:999px;
    font-size:12px;
    font-weight:700;
    margin-left:6px;
}
.ig-badge {
    background:rgba(225,29,72,0.12);
    color:#e11d48;
}
.tg-badge {
    background:rgba(14,165,233,0.13);
    color:#0284c7;
}
.client-card {
    border: 1px solid rgba(120,120,120,0.15);
    border-radius: 18px;
    padding: 12px;
    margin-bottom: 8px;
    background: rgba(120,120,120,0.06);
}
.stButton button {
    border-radius: 999px;
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
        st.error(f"Could not load sales chats: {e}")
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


def save_outbound_message(business, customer_id, text, platform, channel, chat_id="", raw_payload=None):
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


if "user" not in st.session_state:
    st.markdown("""
    <div class="login-card" style="max-width:480px;margin:80px auto;text-align:center;">
        <h1>💬 Milana Premium</h1>
        <h3>Social Sales Chat</h3>
        <p>Instagram va Telegram mijozlar bilan savdo suhbati</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        email = st.text_input("Email", placeholder="manager@milana.uz")
        password = st.text_input("Password", type="password", placeholder="Password")

        if st.button("Login", type="primary", use_container_width=True):
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

with st.sidebar:
    st.markdown(f"""
    <div style="text-align:center;">
        <h1>💬</h1>
        <h3>Milana Premium</h3>
        <p>Social Sales Chat</p>
        <small>{html.escape(user_email)}</small>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    if is_admin:
        nav_option = st.radio(
            "Menu",
            [
                "📊 Sales Overview",
                "💬 Social Sales Chat",
                "📦 Business Setup",
                "➕ Add Account",
                "📲 Telegram Setup",
                "👥 Managers",
                "🔗 Access",
            ],
        )
    else:
        nav_option = st.radio(
            "Menu",
            [
                "📊 Sales Overview",
                "💬 Social Sales Chat",
                "📦 Business Setup",
                "📲 Telegram Setup",
            ],
        )

    st.divider()

    if st.button("Sign Out", use_container_width=True):
        logout()


st.markdown("""
<div class="main-header">
    <h2 style="margin:0;">Milana Premium Social Sales Chat</h2>
    <p style="margin:6px 0 0 0;">Instagram va Telegram mijozlar bilan savdo suhbatlari uchun yagona panel</p>
</div>
""", unsafe_allow_html=True)


def show_metrics():
    businesses = get_allowed_businesses()

    total_businesses = len(businesses)
    active_bots = sum(1 for b in businesses if b.get("bot_enabled"))
    instagram_count = get_message_count("instagram")
    telegram_count = get_message_count("telegram")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{total_businesses}</div><div class="metric-label">Sales Accounts</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{active_bots}</div><div class="metric-label">Auto Reply Active</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{instagram_count}</div><div class="metric-label">Instagram Messages</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{telegram_count}</div><div class="metric-label">Telegram Messages</div></div>', unsafe_allow_html=True)


def business_editor(business):
    with st.form(key=f"edit_{business['id']}"):
        st.subheader("📦 Milana Premium Business Setup")

        col1, col2 = st.columns(2)

        with col1:
            business_name = st.text_input("Account Name", value=business.get("business_name", "Milana Premium"))
            business_type = st.text_input("Business Type", value=business.get("business_type", "Textile and Clothing"))

        with col2:
            language_options = ["uz", "ru", "en"]
            current_language = business.get("language", "uz")
            language_index = language_options.index(current_language) if current_language in language_options else 0
            language = st.selectbox("Main Reply Language", language_options, index=language_index)
            tone = st.text_input("Sales Tone", value=business.get("tone", "friendly, polite, sales-focused"))

        bot_enabled = st.toggle("Auto Reply Enabled", value=bool(business.get("bot_enabled", True)))

        st.divider()
        st.subheader("💬 Sales Reply Behavior")

        col1, col2 = st.columns(2)

        with col1:
            reply_style_options = ["short_comfortable", "very_short", "normal_sales"]
            current_reply_style = business.get("reply_style", "short_comfortable")
            reply_style_index = reply_style_options.index(current_reply_style) if current_reply_style in reply_style_options else 0
            reply_style = st.selectbox("Reply Style", reply_style_options, index=reply_style_index, disabled="reply_style" not in business)

            max_tokens = st.number_input(
                "Answer Length",
                min_value=50,
                max_value=500,
                value=int(business.get("ai_max_tokens", 130) or 130),
                step=10,
                disabled="ai_max_tokens" not in business,
            )

        with col2:
            catalog_policy_options = ["only_when_customer_asks", "offer_when_relevant", "never_send"]
            current_catalog_policy = business.get("catalog_policy", "only_when_customer_asks")
            catalog_policy_index = catalog_policy_options.index(current_catalog_policy) if current_catalog_policy in catalog_policy_options else 0
            catalog_policy = st.selectbox("Catalog Sending Rule", catalog_policy_options, index=catalog_policy_index, disabled="catalog_policy" not in business)

            temperature = st.number_input(
                "Reply Creativity",
                min_value=0.0,
                max_value=1.0,
                value=float(business.get("ai_temperature", 0.5) or 0.5),
                step=0.1,
                disabled="ai_temperature" not in business,
            )

        ai_reply_rules = st.text_area(
            "Sales Assistant Rules",
            value=business.get("ai_reply_rules", DEFAULT_AI_REPLY_RULES),
            height=150,
            disabled="ai_reply_rules" not in business,
        )

        st.divider()
        st.subheader("📦 Products and Sales Knowledge")

        products = st.text_area("Products / Services", value=business.get("products", ""), height=100)
        prices = st.text_area("Prices", value=business.get("prices", ""), height=90)
        delivery = st.text_area("Delivery Info", value=business.get("delivery_info", ""), height=90)
        hours = st.text_area("Working Hours", value=business.get("working_hours", ""), height=80)
        faq = st.text_area("FAQ", value=business.get("faq", ""), height=120)
        catalog = st.text_input("Catalog Link", value=business.get("catalog_link", ""))
        phone = st.text_input("Sales Manager Phone", value=business.get("sales_phone", ""))

        st.divider()
        st.subheader("📱 Product Quick Links")

        tg_single = st.text_input("Single Product Link", value=business.get("telegram_single", ""))
        tg_package = st.text_input("Package Link", value=business.get("telegram_package", ""))
        tg_bag = st.text_input("Bag / Meshok Link", value=business.get("telegram_bag", ""))

        st.divider()
        st.subheader("🧠 Main Sales Knowledge")

        knowledge = st.text_area("Knowledge", value=business.get("knowledge", ""), height=260)

        submitted = st.form_submit_button("💾 Save Milana Premium Setup", type="primary", use_container_width=True)

        if submitted:
            update_data = {
                "business_name": business_name.strip(),
                "business_type": business_type.strip(),
                "language": language,
                "tone": tone.strip(),
                "bot_enabled": bot_enabled,
                "reply_style": reply_style,
                "catalog_policy": catalog_policy,
                "ai_reply_rules": ai_reply_rules.strip(),
                "ai_max_tokens": int(max_tokens),
                "ai_temperature": float(temperature),
                "products": products.strip(),
                "prices": prices.strip(),
                "delivery_info": delivery.strip(),
                "working_hours": hours.strip(),
                "faq": faq.strip(),
                "catalog_link": catalog.strip(),
                "sales_phone": phone.strip(),
                "telegram_single": tg_single.strip(),
                "telegram_package": tg_package.strip(),
                "telegram_bag": tg_bag.strip(),
                "knowledge": knowledge.strip(),
            }

            try:
                safe_update_business(business, update_data)
                st.success("Saved successfully.")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")


if nav_option == "📊 Sales Overview":
    st.subheader("Sales Overview")
    show_metrics()


elif nav_option == "💬 Social Sales Chat":
    st.subheader("💬 Milana Premium Social Sales Chat")

    businesses = get_allowed_businesses()
    business_map = {b.get("id"): b for b in businesses if b.get("id")}
    business_ids = list(business_map.keys())

    if not businesses:
        st.warning("No Milana Premium account found.")
    else:
        top1, top2, top3 = st.columns([2, 1, 1])

        with top1:
            search_text = st.text_input("Search clients", placeholder="Search by client, message, or ID")

        with top2:
            platform_filter_label = st.selectbox("Platform", ["All", "Instagram", "Telegram"])
            platform_filter = {
                "All": "all",
                "Instagram": "instagram",
                "Telegram": "telegram",
            }[platform_filter_label]

        with top3:
            unread_only = st.toggle("Unread only", value=False)

        conversations = get_social_conversations(
            business_ids=business_ids,
            platform_filter=platform_filter,
            search_text=search_text,
        )

        if unread_only:
            conversations = [c for c in conversations if c.get("unread_count", 0) > 0]

        if not conversations:
            st.info("No social sales conversations yet.")
        else:
            left, right = st.columns([1.08, 2.45])

            with left:
                st.markdown("### Clients")
                options = {}

                for c in conversations:
                    platform = c.get("platform", "instagram")
                    channel = c.get("channel", "")
                    unread = c.get("unread_count", 0)
                    unread_badge = f" 🔴 {unread}" if unread else ""
                    preview = str(c.get("last_message", ""))[:38]
                    icon = "📲" if platform == "telegram" else "📸"
                    name = c.get("customer_name") or f"Client {str(c.get('customer_id'))[-4:]}"

                    if platform == "telegram" and channel == "telegram_user_private":
                        source = "Private"
                    elif platform == "telegram":
                        source = "Bot"
                    else:
                        source = "Instagram"

                    label = f"{icon} {name}{unread_badge}\n{source} · {preview}"
                    options[label] = c

                selected_label = st.radio("Select chat", list(options.keys()), label_visibility="collapsed")
                selected_conversation = options[selected_label]

            with right:
                selected_business = business_map.get(selected_conversation["business_id"])

                if not selected_business:
                    st.error("Sales account not found for this conversation.")
                    st.stop()

                customer_id = selected_conversation["customer_id"]
                chat_id = selected_conversation.get("chat_id") or customer_id
                platform = selected_conversation.get("platform", "instagram")
                channel = selected_conversation.get("channel", "")
                customer_name = selected_conversation.get("customer_name") or f"Client {str(customer_id)[-4:]}"

                mark_conversation_read(selected_business["id"], customer_id, platform, channel)
                messages = get_conversation_messages(selected_business["id"], customer_id, platform, channel)

                badge_class = "tg-badge" if platform == "telegram" else "ig-badge"

                if platform == "telegram" and channel == "telegram_user_private":
                    badge_text = "Telegram Private"
                elif platform == "telegram":
                    badge_text = "Telegram Bot"
                else:
                    badge_text = "Instagram"

                st.markdown('<div class="chat-shell">', unsafe_allow_html=True)

                st.markdown(f"""
                <div class="chat-top">
                    <span class="avatar">{'TG' if platform == 'telegram' else 'IG'}</span>
                    <b>{html.escape(customer_name)}</b>
                    <span class="platform-badge {badge_class}">{badge_text}</span><br>
                    <span class="small-muted">Milana Premium social sales chat</span>
                </div>
                """, unsafe_allow_html=True)

                chat_box = st.container(height=500)

                with chat_box:
                    for msg in messages:
                        direction = msg.get("direction")
                        content = html.escape(str(msg.get("content", ""))).replace("\n", "<br>")
                        created_at = html.escape(str(msg.get("created_at", "")))

                        if direction == "outbound":
                            st.markdown(
                                f"""
                                <div class="outbound-msg">
                                    {content}
                                    <div class="small-muted">{created_at}</div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                f"""
                                <div class="inbound-msg">
                                    {content}
                                    <div class="small-muted">{created_at}</div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                with st.form("manual_social_reply", clear_on_submit=True):
                    reply_text = st.text_area("Message", placeholder="Reply as Milana Premium...", height=90)

                    c1, c2, c3, c4 = st.columns(4)

                    with c1:
                        send_clicked = st.form_submit_button("Send", type="primary", use_container_width=True)
                    with c2:
                        catalog_clicked = st.form_submit_button("Catalog", use_container_width=True)
                    with c3:
                        phone_clicked = st.form_submit_button("Contact", use_container_width=True)
                    with c4:
                        product_clicked = st.form_submit_button("Ask Product", use_container_width=True)

                    quick_text = ""
                    if catalog_clicked:
                        link = selected_business.get("catalog_link", "")
                        quick_text = f"Katalogimiz: {link}" if link else "Qaysi mahsulot katalogi kerak edi?"
                    elif phone_clicked:
                        phone = selected_business.get("sales_phone", "")
                        quick_text = f"Savdo bo‘limi bilan bog‘lanish: {phone}" if phone else "Telefon raqamingizni qoldiring, menejerimiz bog‘lanadi."
                    elif product_clicked:
                        quick_text = "Qaysi mahsulot sizni qiziqtiryapti?"

                    final_text = quick_text or reply_text.strip()

                    if send_clicked or catalog_clicked or phone_clicked or product_clicked:
                        if not final_text.strip():
                            st.error("Message cannot be empty.")
                        else:
                            if platform == "instagram":
                                ok, result = send_instagram_dm_from_backend(
                                    business_id=selected_business["id"],
                                    customer_id=customer_id,
                                    text=final_text.strip(),
                                )

                            elif platform == "telegram" and channel in ["telegram_bot_private", "telegram_bot_group", "private", "group", "supergroup"]:
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
                                ok, result = False, {"error": "Unsupported channel for manual reply", "channel": channel}

                            if ok:
                                st.success("Sent.")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error("Failed to send message.")
                                st.json(result)

                st.markdown("</div>", unsafe_allow_html=True)


elif nav_option == "📦 Business Setup":
    businesses = get_allowed_businesses()

    if not businesses:
        st.warning("No Milana Premium account found.")
    else:
        if len(businesses) == 1:
            business = businesses[0]
        else:
            business_options = {
                f"{b.get('business_name', 'Milana Premium')} | IG: {b.get('instagram_business_id', 'No ID')}": b
                for b in businesses
            }
            selected = st.selectbox("Select Account", list(business_options.keys()))
            business = business_options[selected]

        business_editor(business)


elif nav_option == "➕ Add Account" and is_admin:
    st.subheader("➕ Add Milana Premium Account")

    with st.form("add_business"):
        name = st.text_input("Account Name", value="Milana Premium")
        ig_id = st.text_input("Instagram Business ID *")
        fb_id = st.text_input("Facebook Page ID")
        knowledge = st.text_area("Main Sales Knowledge", height=180)

        submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)

        if submitted:
            if not name.strip() or not ig_id.strip():
                st.error("Account Name and Instagram Business ID are required.")
            else:
                data = {
                    "business_name": name.strip(),
                    "instagram_business_id": ig_id.strip(),
                    "facebook_page_id": fb_id.strip(),
                    "business_type": "Textile and Clothing",
                    "language": "uz",
                    "tone": "friendly, polite, sales-focused",
                    "bot_enabled": False,
                    "knowledge": knowledge.strip(),
                    "access_token": "",
                    "page_access_token": "",
                    "oauth_provider": "",
                    "facebook_page_name": "",
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

                try:
                    create_business(data)
                    st.success("Account created.")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Creation failed: {e}")


elif nav_option == "📲 Telegram Setup":
    st.subheader("📲 Telegram Setup")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Telegram Bot Token", "OK" if TELEGRAM_BOT_TOKEN else "Missing")

    with col2:
        st.metric("Bot Username", f"@{TELEGRAM_BOT_USERNAME.replace('@', '')}" if TELEGRAM_BOT_USERNAME else "Missing")

    with col3:
        st.metric("Telegram Messages", get_message_count("telegram"))

    st.divider()

    st.markdown("### Bot Webhook")
    st.code(telegram_webhook_url())

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Set Telegram Bot Webhook", use_container_width=True):
            ok, data = set_telegram_webhook()
            st.json(data)

    with col2:
        if st.button("Check Bot Webhook", use_container_width=True):
            ok, data = get_telegram_webhook_info()
            st.json(data)

    with col3:
        st.link_button("Open Telegram Webhook Check", f"{BACKEND_URL}/webhook/telegram", use_container_width=True)

    st.divider()

    st.markdown("### Private Telegram Account")
    st.info(
        "Private Telegram account automation works only if the Telethon session file exists on the backend "
        "and ENABLE_TELEGRAM_USER_CLIENT=true is set."
    )

    st.code(
        "TELEGRAM_API_ID=...\n"
        "TELEGRAM_API_HASH=...\n"
        "TELEGRAM_USER_SESSION=milana_user_session\n"
        "ENABLE_TELEGRAM_USER_CLIENT=true"
    )


elif nav_option == "👥 Managers" and is_admin:
    st.subheader("👥 Managers")

    with st.expander("Create / Reset Manager", expanded=True):
        email_u = st.text_input("Manager Email")
        pwd_u = st.text_input("Password", type="password")

        if st.button("Create / Reset", use_container_width=True):
            if email_u and pwd_u:
                create_or_update_dashboard_user(email_u, pwd_u)
                st.success("Manager saved.")
                st.rerun()
            else:
                st.error("Email and password required.")

    users = get_all_dashboard_users()
    if users:
        st.dataframe(users, use_container_width=True)


elif nav_option == "🔗 Access" and is_admin:
    st.subheader("🔗 Access")

    all_biz = get_all_businesses()

    if not all_biz:
        st.warning("No account found.")
    else:
        biz_map = {
            f"{b.get('business_name', 'Milana Premium')} ({b.get('id', '')[:8]})": b["id"]
            for b in all_biz
        }

        email_assign = st.text_input("Manager Email")
        selected_biz = st.selectbox("Milana Account", list(biz_map.keys()))
        role = st.selectbox("Role", ["owner", "editor"])

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Assign", use_container_width=True):
                if email_assign:
                    assign_business_to_user(email_assign, biz_map[selected_biz], role)
                    st.success("Assigned.")
                    st.rerun()
                else:
                    st.error("Email required.")

        with col2:
            if st.button("Remove Access", use_container_width=True):
                if email_assign:
                    remove_business_assignment(email_assign, biz_map[selected_biz])
                    st.success("Removed.")
                    st.rerun()
                else:
                    st.error("Email required.")

        assignments = get_business_assignments()
        if assignments:
            st.dataframe(assignments, use_container_width=True)
