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
    page_title="Bot Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.modern-card {
    background: rgba(120,120,120,0.08);
    border: 1px solid rgba(120,120,120,0.18);
    border-radius: 24px;
    padding: 22px;
    margin-bottom: 18px;
}
.gradient-header {
    background: linear-gradient(135deg,#6366f1,#a855f7,#ec4899);
    border-radius: 28px;
    padding: 22px 28px;
    color: white;
    margin-bottom: 24px;
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
.inbox-card {
    background: rgba(120,120,120,0.08);
    border: 1px solid rgba(120,120,120,0.16);
    border-radius: 18px;
    padding: 14px;
    margin-bottom: 10px;
}
.inbound-msg {
    background: rgba(99,102,241,0.13);
    border: 1px solid rgba(99,102,241,0.20);
    border-radius: 18px;
    padding: 12px 14px;
    margin: 8px 0;
    max-width: 78%;
}
.outbound-msg {
    background: rgba(34,197,94,0.13);
    border: 1px solid rgba(34,197,94,0.20);
    border-radius: 18px;
    padding: 12px 14px;
    margin: 8px 0 8px auto;
    max-width: 78%;
}
.small-muted {
    opacity: .65;
    font-size: 12px;
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
- Sound natural like a real sales manager."""


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


def set_user_active_status(email, is_active):
    return (
        supabase.table("dashboard_users")
        .update({"is_active": is_active})
        .eq("email", normalize_email(email))
        .execute()
    )


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


def get_allowed_businesses():
    return get_all_businesses() if is_admin else get_user_businesses(user_email)


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


def get_instagram_conversations(business_ids, search_text="", limit=700):
    if not business_ids:
        return []

    try:
        rows = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", "instagram")
            .in_("business_id", business_ids)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as e:
        st.error(f"Could not load inbox messages: {e}")
        return []

    conversations = {}

    for row in rows:
        business_id = row.get("business_id")
        customer_id = str(row.get("customer_id") or "").strip()

        if not business_id or not customer_id:
            continue

        key = f"{business_id}::{customer_id}"

        if key not in conversations:
            conversations[key] = {
                "business_id": business_id,
                "customer_id": customer_id,
                "customer_name": row.get("customer_name") or customer_id,
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
            if q in f"{c.get('customer_id','')} {c.get('customer_name','')} {c.get('last_message','')}".lower()
        ]

    return results


def get_conversation_messages(business_id, customer_id, limit=250):
    try:
        return (
            supabase.table("inbox_messages")
            .select("*")
            .eq("platform", "instagram")
            .eq("business_id", business_id)
            .eq("customer_id", str(customer_id))
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as e:
        st.error(f"Could not load conversation: {e}")
        return []


def mark_conversation_read(business_id, customer_id):
    try:
        (
            supabase.table("inbox_messages")
            .update({"is_read": True})
            .eq("platform", "instagram")
            .eq("business_id", business_id)
            .eq("customer_id", str(customer_id))
            .eq("direction", "inbound")
            .execute()
        )
    except Exception:
        pass


def send_instagram_dm_from_backend(business_id, customer_id, text):
    payload = {
        "business_id": str(business_id),
        "customer_id": str(customer_id),
        "text": text,
    }

    response = requests.post(
        f"{BACKEND_URL}/dashboard/send-instagram-dm",
        json=payload,
        headers={
            "x-dashboard-secret": DASHBOARD_SECRET,
        },
        timeout=30,
    )

    try:
        data = response.json()
    except Exception:
        data = {"text": response.text}

    return response.ok, data


if "user" not in st.session_state:
    st.markdown("""
    <div class="modern-card" style="max-width:480px;margin:80px auto;text-align:center;">
        <h1>🤖 Bot Dashboard</h1>
        <p>Manage Instagram and Telegram bots</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        email = st.text_input("Email", placeholder="admin@example.com")
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
        <h1>🤖</h1>
        <h3>Bot Manager</h3>
        <p>{html.escape(user_email)}</p>
        <b>{"Admin" if is_admin else "Business Owner"}</b>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    if is_admin:
        nav_option = st.radio(
            "Navigation",
            [
                "📊 Dashboard",
                "📥 Inbox",
                "📋 Businesses",
                "➕ Add Business",
                "📲 Telegram",
                "👥 Users",
                "🔗 Assignments",
            ],
        )
    else:
        nav_option = st.radio(
            "Navigation",
            [
                "📊 Dashboard",
                "📥 Inbox",
                "📋 My Business",
                "📲 Telegram",
            ],
        )

    st.divider()

    if st.button("Sign Out", use_container_width=True):
        logout()


st.markdown("""
<div class="gradient-header">
    <h2 style="margin:0;">🤖 Instagram + Telegram Bot Dashboard</h2>
    <p style="margin:6px 0 0 0;">Manage business knowledge, inbox, bot status, and manual replies</p>
</div>
""", unsafe_allow_html=True)


def show_metrics():
    businesses = get_allowed_businesses()

    total_businesses = len(businesses)
    active_bots = sum(1 for b in businesses if b.get("bot_enabled"))
    instagram_connected = sum(1 for b in businesses if b.get("access_token") or b.get("page_access_token"))
    telegram_ready = 1 if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USERNAME else 0

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{total_businesses}</div>
            <div class="metric-label">Businesses</div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{active_bots}</div>
            <div class="metric-label">Active Bots</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{instagram_connected}</div>
            <div class="metric-label">Instagram Connected</div>
        </div>
        """, unsafe_allow_html=True)

    with c4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{telegram_ready}</div>
            <div class="metric-label">Telegram Configured</div>
        </div>
        """, unsafe_allow_html=True)


def business_editor(business):
    with st.form(key=f"edit_{business['id']}"):
        st.subheader("🏢 Business Info")

        col1, col2 = st.columns(2)

        with col1:
            business_name = st.text_input("Business Name", value=business.get("business_name", ""))
            business_type = st.text_input("Business Type", value=business.get("business_type", ""))

        with col2:
            language_options = ["uz", "ru", "en"]
            current_language = business.get("language", "uz")
            language_index = language_options.index(current_language) if current_language in language_options else 0
            language = st.selectbox("Language", language_options, index=language_index)
            tone = st.text_input("Tone", value=business.get("tone", "friendly, polite"))

        bot_enabled = st.toggle("Main Bot Enabled", value=bool(business.get("bot_enabled", True)))

        st.divider()
        st.subheader("💬 AI Reply Behavior")

        col1, col2 = st.columns(2)

        with col1:
            reply_style_options = ["short_comfortable", "very_short", "normal_sales"]
            current_reply_style = business.get("reply_style", "short_comfortable")
            reply_style_index = reply_style_options.index(current_reply_style) if current_reply_style in reply_style_options else 0

            reply_style = st.selectbox(
                "Reply Style",
                reply_style_options,
                index=reply_style_index,
                disabled="reply_style" not in business,
            )

            max_tokens = st.number_input(
                "AI Max Tokens",
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

            catalog_policy = st.selectbox(
                "Catalog Policy",
                catalog_policy_options,
                index=catalog_policy_index,
                disabled="catalog_policy" not in business,
            )

            temperature = st.number_input(
                "AI Temperature",
                min_value=0.0,
                max_value=1.0,
                value=float(business.get("ai_temperature", 0.5) or 0.5),
                step=0.1,
                disabled="ai_temperature" not in business,
            )

        ai_reply_rules = st.text_area(
            "AI Reply Rules",
            value=business.get("ai_reply_rules", DEFAULT_AI_REPLY_RULES),
            height=150,
            disabled="ai_reply_rules" not in business,
        )

        st.caption("Recommended: short_comfortable, only_when_customer_asks, max_tokens 130, temperature 0.5")

        st.divider()
        st.subheader("📸 Instagram")

        col1, col2 = st.columns(2)

        with col1:
            st.text_input("Instagram Business ID", value=business.get("instagram_business_id", ""), disabled=True)
            auto_reply_dms = st.toggle(
                "Auto Reply DMs",
                value=bool(business.get("auto_reply_dms", True)),
                disabled="auto_reply_dms" not in business,
            )

        with col2:
            st.text_input("Facebook Page ID", value=business.get("facebook_page_id", ""), disabled=True)
            auto_reply_comments = st.toggle(
                "Auto Reply Comments",
                value=bool(business.get("auto_reply_comments", True)),
                disabled="auto_reply_comments" not in business,
            )

        if business.get("access_token") or business.get("page_access_token"):
            st.success("Instagram connected")
        else:
            st.warning("Instagram is not connected")

        st.divider()
        st.subheader("📲 Telegram")

        telegram_enabled = st.toggle(
            "Telegram Bot Enabled for this Business",
            value=bool(business.get("telegram_bot_enabled", business.get("bot_enabled", True))),
            disabled="telegram_bot_enabled" not in business,
        )

        col1, col2 = st.columns(2)

        with col1:
            telegram_business_username = st.text_input(
                "Telegram Bot Username",
                value=business.get("telegram_bot_username", TELEGRAM_BOT_USERNAME or ""),
                disabled="telegram_bot_username" not in business,
            )

        with col2:
            telegram_chat_id = st.text_input(
                "Telegram Main Chat ID",
                value=str(business.get("telegram_chat_id", "")),
                disabled="telegram_chat_id" not in business,
            )

        if TELEGRAM_BOT_TOKEN:
            st.success("Telegram token exists in environment/secrets")
        else:
            st.error("TELEGRAM_BOT_TOKEN is missing")

        if TELEGRAM_BOT_USERNAME:
            st.info(f"Telegram username: @{TELEGRAM_BOT_USERNAME.replace('@', '')}")
        else:
            st.warning("TELEGRAM_BOT_USERNAME is missing")

        st.caption(f"Webhook URL: {telegram_webhook_url()}")

        st.divider()
        st.subheader("📦 Business Knowledge")

        products = st.text_area("Products / Services", value=business.get("products", ""), height=100)
        prices = st.text_area("Prices", value=business.get("prices", ""), height=90)
        delivery = st.text_area("Delivery Info", value=business.get("delivery_info", ""), height=90)
        hours = st.text_area("Working Hours", value=business.get("working_hours", ""), height=80)
        faq = st.text_area("FAQ", value=business.get("faq", ""), height=120)
        catalog = st.text_input("Catalog Link", value=business.get("catalog_link", ""))
        phone = st.text_input("Sales Phone", value=business.get("sales_phone", ""))

        st.divider()
        st.subheader("📱 Telegram Product Links")

        tg_single = st.text_input("Single Product Link", value=business.get("telegram_single", ""))
        tg_package = st.text_input("Package Link", value=business.get("telegram_package", ""))
        tg_bag = st.text_input("Bag / Meshok Link", value=business.get("telegram_bag", ""))

        st.divider()
        st.subheader("🧠 Main Knowledge Prompt")

        knowledge = st.text_area("Knowledge", value=business.get("knowledge", ""), height=260)

        submitted = st.form_submit_button("💾 Save Changes", type="primary", use_container_width=True)

        if submitted:
            if not business_name.strip():
                st.error("Business name is required.")
                return

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
                "auto_reply_dms": auto_reply_dms,
                "auto_reply_comments": auto_reply_comments,
                "telegram_bot_enabled": telegram_enabled,
                "telegram_bot_username": telegram_business_username.strip(),
                "telegram_chat_id": telegram_chat_id.strip(),
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


if nav_option == "📊 Dashboard":
    st.subheader(f"Welcome, {user_email.split('@')[0]}")
    show_metrics()

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Instagram Messages")
        st.metric("Total Instagram Messages", get_message_count("instagram"))

    with col2:
        st.markdown("### Telegram Messages")
        st.metric("Total Telegram Messages", get_message_count("telegram"))


elif nav_option == "📥 Inbox":
    st.subheader("📥 Instagram Inbox")

    businesses = get_allowed_businesses()
    business_map = {b.get("id"): b for b in businesses if b.get("id")}
    business_ids = list(business_map.keys())

    if not businesses:
        st.warning("No businesses found.")
    else:
        top1, top2, top3 = st.columns([1.5, 1, 1])

        with top1:
            search_text = st.text_input("Search conversations", placeholder="Customer ID, name, or message")

        with top2:
            business_filter_options = {"All businesses": None}
            for b in businesses:
                business_filter_options[b.get("business_name", "No name")] = b.get("id")

            selected_business_filter = st.selectbox("Business", list(business_filter_options.keys()))

        with top3:
            unread_only = st.toggle("Unread only", value=False)

        selected_business_id = business_filter_options[selected_business_filter]
        filtered_business_ids = [selected_business_id] if selected_business_id else business_ids

        conversations = get_instagram_conversations(filtered_business_ids, search_text=search_text)

        if unread_only:
            conversations = [c for c in conversations if c.get("unread_count", 0) > 0]

        if not conversations:
            st.info("No Instagram DM conversations yet. Send a DM from a tester/admin account to your connected Instagram business account.")
        else:
            left, right = st.columns([1, 2.2])

            with left:
                st.markdown("### Conversations")

                options = {}
                for c in conversations:
                    business = business_map.get(c["business_id"], {})
                    unread = c.get("unread_count", 0)
                    unread_badge = f" 🔴 {unread}" if unread else ""
                    label = f"{c.get('customer_name') or c.get('customer_id')} | {business.get('business_name', 'Business')}{unread_badge}"
                    options[label] = c

                selected_label = st.radio(
                    "Select chat",
                    list(options.keys()),
                    label_visibility="collapsed",
                )

                selected_conversation = options[selected_label]
                selected_business = business_map.get(selected_conversation["business_id"], {})

                st.markdown(f"""
                <div class="inbox-card">
                    <b>Customer</b><br>
                    {html.escape(str(selected_conversation.get("customer_name") or selected_conversation.get("customer_id")))}<br><br>
                    <b>Business</b><br>
                    {html.escape(str(selected_business.get("business_name", "")))}<br><br>
                    <b>Platform</b><br>
                    Instagram DM<br><br>
                    <b>Messages</b><br>
                    {selected_conversation.get("total_messages", 0)}
                </div>
                """, unsafe_allow_html=True)

            with right:
                selected_business = business_map.get(selected_conversation["business_id"])

                if not selected_business:
                    st.error("Business not found for this conversation.")
                    st.stop()

                customer_id = selected_conversation["customer_id"]

                mark_conversation_read(selected_business["id"], customer_id)
                messages = get_conversation_messages(selected_business["id"], customer_id)

                header_left, header_right = st.columns([2, 1])

                with header_left:
                    st.markdown(f"### Chat with `{customer_id}`")
                    st.caption(f"Business: {selected_business.get('business_name', '')}")

                with header_right:
                    if st.button("Refresh", use_container_width=True):
                        st.rerun()

                chat_box = st.container(height=480)

                with chat_box:
                    for msg in messages:
                        direction = msg.get("direction")
                        content = html.escape(str(msg.get("content", ""))).replace("\n", "<br>")
                        created_at = html.escape(str(msg.get("created_at", "")))

                        if direction == "outbound":
                            st.markdown(
                                f"""
                                <div class="outbound-msg">
                                    <b>You</b><br>
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
                                    <b>Customer</b><br>
                                    {content}
                                    <div class="small-muted">{created_at}</div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                with st.form("manual_instagram_reply", clear_on_submit=True):
                    reply_text = st.text_area("Reply", placeholder="Write your reply...", height=100)
                    send_clicked = st.form_submit_button("Send Instagram DM", type="primary", use_container_width=True)

                    if send_clicked:
                        clean_reply = reply_text.strip()

                        if not clean_reply:
                            st.error("Reply cannot be empty.")
                        else:
                            ok, result = send_instagram_dm_from_backend(
                                business_id=selected_business["id"],
                                customer_id=customer_id,
                                text=clean_reply,
                            )

                            if ok:
                                st.success("Reply sent.")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error("Failed to send Instagram DM.")
                                st.json(result)


elif nav_option in ["📋 Businesses", "📋 My Business"]:
    businesses = get_allowed_businesses()

    if not businesses:
        st.warning("No businesses found.")
    else:
        if len(businesses) == 1:
            business = businesses[0]
        else:
            business_options = {
                f"{b.get('business_name', 'No name')} | IG: {b.get('instagram_business_id', 'No ID')}": b
                for b in businesses
            }
            selected = st.selectbox("Select Business", list(business_options.keys()))
            business = business_options[selected]

        business_editor(business)


elif nav_option == "➕ Add Business" and is_admin:
    st.subheader("➕ Add Business")

    with st.form("add_business"):
        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input("Business Name *")
            ig_id = st.text_input("Instagram Business ID *")
            fb_id = st.text_input("Facebook Page ID")

        with col2:
            biz_type = st.text_input("Business Type")
            lang = st.selectbox("Language", ["uz", "ru", "en"])
            tone_val = st.text_input("Tone", value="friendly, polite")

        st.divider()

        products = st.text_area("Products / Services")
        prices = st.text_area("Prices")
        delivery_info = st.text_area("Delivery Info")
        faq = st.text_area("FAQ")
        catalog_link = st.text_input("Catalog Link")
        sales_phone = st.text_input("Sales Phone")

        st.divider()
        st.subheader("💬 Default AI Reply Behavior")

        reply_style = st.selectbox("Reply Style", ["short_comfortable", "very_short", "normal_sales"])
        catalog_policy = st.selectbox("Catalog Policy", ["only_when_customer_asks", "offer_when_relevant", "never_send"])
        ai_max_tokens = st.number_input("AI Max Tokens", min_value=50, max_value=500, value=130, step=10)
        ai_temperature = st.number_input("AI Temperature", min_value=0.0, max_value=1.0, value=0.5, step=0.1)
        ai_reply_rules = st.text_area("AI Reply Rules", value=DEFAULT_AI_REPLY_RULES, height=150)

        st.divider()

        knowledge = st.text_area("Main Knowledge Prompt", height=180)

        submitted = st.form_submit_button("Create Business", type="primary", use_container_width=True)

        if submitted:
            if not name.strip() or not ig_id.strip():
                st.error("Business Name and Instagram Business ID are required.")
            else:
                data = {
                    "business_name": name.strip(),
                    "instagram_business_id": ig_id.strip(),
                    "facebook_page_id": fb_id.strip(),
                    "business_type": biz_type.strip(),
                    "language": lang,
                    "tone": tone_val.strip(),
                    "bot_enabled": False,
                    "knowledge": knowledge.strip(),
                    "access_token": "",
                    "page_access_token": "",
                    "oauth_provider": "",
                    "facebook_page_name": "",
                    "products": products.strip(),
                    "prices": prices.strip(),
                    "delivery_info": delivery_info.strip(),
                    "working_hours": "",
                    "faq": faq.strip(),
                    "catalog_link": catalog_link.strip(),
                    "sales_phone": sales_phone.strip(),
                    "telegram_single": "",
                    "telegram_package": "",
                    "telegram_bag": "",
                    "reply_style": reply_style,
                    "catalog_policy": catalog_policy,
                    "ai_reply_rules": ai_reply_rules.strip(),
                    "ai_max_tokens": int(ai_max_tokens),
                    "ai_temperature": float(ai_temperature),
                }

                try:
                    create_business(data)
                    st.success("Business created.")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Creation failed: {e}")


elif nav_option == "📲 Telegram":
    st.subheader("📲 Telegram Bot Manager")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Telegram Token", "OK" if TELEGRAM_BOT_TOKEN else "Missing")

    with col2:
        st.metric("Bot Username", f"@{TELEGRAM_BOT_USERNAME.replace('@', '')}" if TELEGRAM_BOT_USERNAME else "Missing")

    with col3:
        st.metric("Telegram Messages", get_message_count("telegram"))

    st.divider()

    st.markdown("### Webhook")
    st.code(telegram_webhook_url())

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Set Telegram Webhook", use_container_width=True):
            ok, data = set_telegram_webhook()
            if ok and data.get("ok"):
                st.success("Telegram webhook set successfully.")
            else:
                st.error("Failed to set webhook.")
            st.json(data)

    with col2:
        if st.button("Check Webhook Info", use_container_width=True):
            ok, data = get_telegram_webhook_info()
            if ok:
                st.json(data)
            else:
                st.error("Could not get webhook info.")
                st.json(data)

    with col3:
        st.link_button("Open Backend Check", f"{BACKEND_URL}/webhook/telegram", use_container_width=True)

    st.divider()

    st.markdown("### Telegram Business Control")

    businesses = get_allowed_businesses()

    if not businesses:
        st.warning("No businesses found.")
    else:
        business_options = {
            f"{b.get('business_name', 'No name')} | {b.get('id', '')[:8]}": b
            for b in businesses
        }
        selected = st.selectbox("Select Business", list(business_options.keys()))
        business = business_options[selected]

        with st.form("telegram_business_settings"):
            telegram_enabled = st.toggle(
                "Telegram Enabled",
                value=bool(business.get("telegram_bot_enabled", business.get("bot_enabled", True))),
                disabled="telegram_bot_enabled" not in business,
            )

            telegram_bot_username = st.text_input(
                "Telegram Bot Username",
                value=business.get("telegram_bot_username", TELEGRAM_BOT_USERNAME or ""),
                disabled="telegram_bot_username" not in business,
            )

            telegram_chat_id = st.text_input(
                "Main Telegram Chat ID",
                value=str(business.get("telegram_chat_id", "")),
                disabled="telegram_chat_id" not in business,
            )

            telegram_notes = st.text_area(
                "Telegram Notes",
                value=business.get("telegram_notes", ""),
                height=100,
                disabled="telegram_notes" not in business,
            )

            if st.form_submit_button("Save Telegram Settings", type="primary", use_container_width=True):
                update_data = {
                    "telegram_bot_enabled": telegram_enabled,
                    "telegram_bot_username": telegram_bot_username.strip(),
                    "telegram_chat_id": telegram_chat_id.strip(),
                    "telegram_notes": telegram_notes.strip(),
                }

                try:
                    safe_update_business(business, update_data)
                    st.success("Telegram settings saved.")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")

        st.info(
            "If Telegram fields are disabled, add these columns to your businesses table: "
            "telegram_bot_enabled, telegram_bot_username, telegram_chat_id, telegram_notes."
        )


elif nav_option == "👥 Users" and is_admin:
    st.subheader("👥 Users")

    with st.expander("Create / Reset User", expanded=True):
        email_u = st.text_input("User Email")
        pwd_u = st.text_input("Password", type="password")

        if st.button("Create / Reset", use_container_width=True):
            if email_u and pwd_u:
                create_or_update_dashboard_user(email_u, pwd_u)
                st.success("User saved.")
                st.rerun()
            else:
                st.error("Email and password required.")

    with st.expander("Activate / Deactivate User"):
        email_status = st.text_input("Email")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Activate", use_container_width=True):
                if email_status:
                    set_user_active_status(email_status, True)
                    st.success("Activated.")
                else:
                    st.error("Email required.")

        with col2:
            if st.button("Deactivate", use_container_width=True):
                if email_status:
                    set_user_active_status(email_status, False)
                    st.success("Deactivated.")
                else:
                    st.error("Email required.")

    st.divider()

    users = get_all_dashboard_users()

    if users:
        st.dataframe(users, use_container_width=True)
    else:
        st.info("No users found.")


elif nav_option == "🔗 Assignments" and is_admin:
    st.subheader("🔗 Assignments")

    all_biz = get_all_businesses()

    if not all_biz:
        st.warning("No businesses found.")
    else:
        biz_map = {
            f"{b.get('business_name', 'No name')} ({b.get('id', '')[:8]})": b["id"]
            for b in all_biz
        }

        email_assign = st.text_input("User Email")
        selected_biz = st.selectbox("Business", list(biz_map.keys()))
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
            if st.button("Remove Assignment", use_container_width=True):
                if email_assign:
                    remove_business_assignment(email_assign, biz_map[selected_biz])
                    st.success("Removed.")
                    st.rerun()
                else:
                    st.error("Email required.")

    st.divider()

    assignments = get_business_assignments()

    if assignments:
        st.dataframe(assignments, use_container_width=True)
    else:
        st.info("No assignments found.")
