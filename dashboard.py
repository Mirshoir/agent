import os
import hashlib
import hmac
import time
import requests
import pandas as pd
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="AI Sales OS", page_icon="🤖", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.stApp { background: #f8fafc; }
[data-testid="stSidebar"] { background: #111827; color: white; }
[data-testid="stSidebar"] * { color: inherit; }
.block-container { padding-top: 2rem; }
.hero { background: linear-gradient(135deg, #6366f1, #a855f7, #ec4899); border-radius: 28px; padding: 22px 28px; margin-bottom: 28px; color: white; display:flex; justify-content:space-between; align-items:center; font-weight:700; }
.card { background: white; border: 1px solid #e5e7eb; border-radius: 22px; padding: 20px; box-shadow: 0 10px 25px rgba(15,23,42,0.05); margin-bottom: 16px; }
.metric-card { background: white; border: 1px solid #e5e7eb; border-radius: 22px; padding: 22px; text-align:center; }
.metric-value { font-size: 34px; font-weight: 800; color:#4f46e5; }
.metric-label { font-size: 13px; color:#64748b; text-transform:uppercase; letter-spacing:.08em; }
.chat-bubble-in { background:#f1f5f9; border-radius:18px; padding:12px 15px; margin:8px 0; max-width:75%; }
.chat-bubble-out { background:#ede9fe; border-radius:18px; padding:12px 15px; margin:8px 0 8px auto; max-width:75%; }
.badge { display:inline-block; padding:4px 10px; border-radius:999px; font-size:12px; background:#eef2ff; color:#4338ca; font-weight:700; }
</style>
""", unsafe_allow_html=True)

T = {
    "en": {"dashboard":"Dashboard","inbox":"Inbox","automation":"Automation","knowledge":"Knowledge","customers":"Customers","analytics":"Analytics","settings":"Settings","sign_out":"Sign Out","business_owner":"Business Owner","admin":"Admin","welcome":"Welcome back","handled_today":"Messages Handled Today","ai_mode":"AI Mode","save":"Save","sync":"Sync Instagram Analytics"},
    "uz": {"dashboard":"Boshqaruv","inbox":"Xabarlar","automation":"Avtomatika","knowledge":"Bilimlar","customers":"Mijozlar","analytics":"Analitika","settings":"Sozlamalar","sign_out":"Chiqish","business_owner":"Biznes egasi","admin":"Admin","welcome":"Xush kelibsiz","handled_today":"Bugungi xabarlar","ai_mode":"AI rejimi","save":"Saqlash","sync":"Instagram analitikani yangilash"},
    "ru": {"dashboard":"Панель","inbox":"Входящие","automation":"Автоматизация","knowledge":"База знаний","customers":"Клиенты","analytics":"Аналитика","settings":"Настройки","sign_out":"Выйти","business_owner":"Владелец бизнеса","admin":"Админ","welcome":"Добро пожаловать","handled_today":"Сообщений сегодня","ai_mode":"AI режим","save":"Сохранить","sync":"Обновить Instagram аналитику"},
}


def get_secret(key, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = get_secret("SUPABASE_SERVICE_KEY")
BACKEND_URL = get_secret("BACKEND_URL", "https://agent-1-xi6h.onrender.com")
ADMIN_EMAIL = get_secret("ADMIN_EMAIL", "")
DASHBOARD_SECRET = get_secret("DASHBOARD_SECRET", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    st.error("Missing Supabase configuration.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def tr(key):
    lang = st.session_state.get("ui_lang", "en")
    return T.get(lang, T["en"]).get(key, key)


def normalize_email(email):
    return str(email or "").strip().lower()


def hash_password(password):
    return hashlib.sha256((password + DASHBOARD_SECRET).encode()).hexdigest()


def verify_password(password, password_hash):
    return bool(password and password_hash) and hmac.compare_digest(hash_password(password), password_hash)


def login_user(email, password):
    result = supabase.table("dashboard_users").select("*").eq("email", normalize_email(email)).eq("is_active", True).limit(1).execute()
    users = result.data or []
    if not users:
        return None
    user = users[0]
    return user if verify_password(password, user.get("password_hash", "")) else None


def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def get_all_businesses():
    return supabase.table("businesses").select("*").order("created_at", desc=True).execute().data or []


def get_user_businesses(user_email):
    result = supabase.table("business_users").select("business_id, role").eq("user_email", normalize_email(user_email)).execute()
    links = result.data or []
    if not links:
        return []
    business_ids = [x["business_id"] for x in links if x.get("business_id")]
    role_map = {x["business_id"]: x.get("role", "owner") for x in links}
    businesses = supabase.table("businesses").select("*").in_("id", business_ids).order("created_at", desc=True).execute().data or []
    for b in businesses:
        b["user_role"] = role_map.get(b["id"], "owner")
    return businesses


def update_business(business_id, data):
    return supabase.table("businesses").update(data).eq("id", business_id).execute()


def get_inbox_messages(business_id, customer_id="", limit=100):
    q = supabase.table("inbox_messages").select("*").eq("business_id", business_id)
    if customer_id:
        q = q.eq("customer_id", customer_id)
    return q.order("created_at", desc=True).limit(limit).execute().data or []


def get_conversations(business_id, limit=50):
    try:
        return supabase.table("conversations").select("*").eq("business_id", business_id).order("last_message_at", desc=True).limit(limit).execute().data or []
    except Exception:
        return []


def get_customers(business_id):
    try:
        return supabase.table("customers").select("*").eq("business_id", business_id).order("last_seen_at", desc=True).execute().data or []
    except Exception:
        return []


def get_buttons(business_id):
    try:
        return supabase.table("business_buttons").select("*").eq("business_id", business_id).order("sort_order").execute().data or []
    except Exception:
        return []


def upsert_button(row):
    return supabase.table("business_buttons").upsert(row).execute()


def update_conversation_state(business_id, platform, customer_id, channel, state):
    try:
        return requests.post(f"{BACKEND_URL}/dashboard/conversation/state", json={"dashboard_secret": DASHBOARD_SECRET, "business_id": business_id, "platform": platform, "customer_id": customer_id, "channel": channel, "state": state}, timeout=20)
    except Exception as e:
        st.error(str(e))
        return None


def get_daily_insights(business_id, days=30):
    try:
        return supabase.table("instagram_daily_insights").select("*").eq("business_id", business_id).order("insight_date").limit(days).execute().data or []
    except Exception:
        return []


def get_post_insights(business_id, limit=25):
    try:
        return supabase.table("instagram_post_insights").select("*").eq("business_id", business_id).order("post_timestamp", desc=True).limit(limit).execute().data or []
    except Exception:
        return []

if "user" not in st.session_state:
    col1, col2, col3 = st.columns([1,1.2,1])
    with col2:
        st.markdown("<div class='card' style='margin-top:100px;text-align:center'><h1>🤖 AI Sales OS</h1><p>Instagram + WhatsApp automation</p></div>", unsafe_allow_html=True)
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            user = login_user(email, password)
            if user:
                st.session_state["user"] = user
                st.rerun()
            else:
                st.error("Invalid email or password")
    st.stop()

user = st.session_state["user"]
user_email = normalize_email(user.get("email"))
is_admin = user_email == normalize_email(ADMIN_EMAIL)

with st.sidebar:
    st.markdown("<div style='text-align:center;padding:30px 0'><div style='font-size:42px'>🤖</div><h3>AI Sales OS</h3></div>", unsafe_allow_html=True)
    st.write(user_email)
    st.markdown(f"<span class='badge'>{tr('admin') if is_admin else tr('business_owner')}</span>", unsafe_allow_html=True)
    st.write("")
    lang_label = st.selectbox("🌐", ["English", "O'zbek", "Русский"])
    st.session_state["ui_lang"] = {"English":"en", "O'zbek":"uz", "Русский":"ru"}[lang_label]
    nav_items = [f"📊 {tr('dashboard')}", f"📥 {tr('inbox')}", f"⚙️ {tr('automation')}", f"📦 {tr('knowledge')}", f"👥 {tr('customers')}", f"📈 {tr('analytics')}", f"🔧 {tr('settings')}"]
    nav = st.radio("Navigation", nav_items, label_visibility="collapsed")
    st.divider()
    if st.button(f"🚪 {tr('sign_out')}", use_container_width=True):
        logout()

businesses = get_all_businesses() if is_admin else get_user_businesses(user_email)
if not businesses:
    st.warning("No businesses assigned.")
    st.stop()

if len(businesses) == 1:
    business = businesses[0]
else:
    options = {f"{b.get('business_name')} ({b.get('instagram_business_id')})": b for b in businesses}
    business = options[st.selectbox("Business", list(options.keys()))]

business_id = business["id"]
st.markdown("<div class='hero'><div>🤖 AI Sales OS</div><div>Instagram + WhatsApp Business Control Center</div></div>", unsafe_allow_html=True)


def metric_row():
    conversations = get_conversations(business_id, 200)
    messages = get_inbox_messages(business_id, limit=200)
    customers = get_customers(business_id)
    today = pd.Timestamp.utcnow().date()
    handled_today = 0
    for m in messages:
        try:
            if pd.to_datetime(m.get("created_at")).date() == today:
                handled_today += 1
        except Exception:
            pass
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f"<div class='metric-card'><div class='metric-value'>{len(conversations)}</div><div class='metric-label'>Conversations</div></div>", unsafe_allow_html=True)
    col2.markdown(f"<div class='metric-card'><div class='metric-value'>{handled_today}</div><div class='metric-label'>{tr('handled_today')}</div></div>", unsafe_allow_html=True)
    col3.markdown(f"<div class='metric-card'><div class='metric-value'>{len(customers)}</div><div class='metric-label'>Customers</div></div>", unsafe_allow_html=True)
    col4.markdown(f"<div class='metric-card'><div class='metric-value' style='font-size:24px'>{business.get('automation_mode','FULL_AUTO')}</div><div class='metric-label'>{tr('ai_mode')}</div></div>", unsafe_allow_html=True)

if nav.startswith("📊"):
    st.header(f"{tr('welcome')}, {business.get('business_name')}")
    metric_row()
    st.subheader("Quick Controls")
    col1, col2, col3 = st.columns(3)
    bot_enabled = col1.toggle("AI Bot Enabled", value=bool(business.get("bot_enabled", True)))
    auto_dms = col2.toggle("Auto Reply DMs", value=bool(business.get("auto_reply_dms", True)))
    auto_comments = col3.toggle("Auto Reply Comments", value=bool(business.get("auto_reply_comments", True)))
    if st.button("Save Quick Controls", type="primary"):
        update_business(business_id, {"bot_enabled": bot_enabled, "auto_reply_dms": auto_dms, "auto_reply_comments": auto_comments})
        st.success("Saved")
        time.sleep(0.5)
        st.rerun()

elif nav.startswith("📥"):
    st.header("📥 Unified Inbox")
    conversations = get_conversations(business_id, 100)
    if not conversations:
        st.info("No inbox messages yet. New Instagram/WhatsApp conversations will appear here.")
    else:
        left, right = st.columns([1,2])
        with left:
            conv_options = {f"{c.get('platform','instagram')} · {c.get('customer_id')} · {c.get('state','AI_ACTIVE')}": c for c in conversations}
            conv = conv_options[st.selectbox("Conversation", list(conv_options.keys()))]
            st.write("State:", conv.get("state", "AI_ACTIVE"))
            c1, c2, c3 = st.columns(3)
            if c1.button("AI", use_container_width=True):
                update_conversation_state(business_id, conv.get("platform"), conv.get("customer_id"), conv.get("channel"), "AI_ACTIVE"); st.rerun()
            if c2.button("Human", use_container_width=True):
                update_conversation_state(business_id, conv.get("platform"), conv.get("customer_id"), conv.get("channel"), "HUMAN_ACTIVE"); st.rerun()
            if c3.button("Pause", use_container_width=True):
                update_conversation_state(business_id, conv.get("platform"), conv.get("customer_id"), conv.get("channel"), "PAUSED"); st.rerun()
        with right:
            messages = get_inbox_messages(business_id, conv.get("customer_id"), 100)
            messages.reverse()
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            for m in messages:
                cls = "chat-bubble-out" if m.get("direction") == "outbound" else "chat-bubble-in"
                who = "AI" if m.get("direction") == "outbound" else "Customer"
                st.markdown(f"<div class='{cls}'><b>{who}</b><br>{m.get('content','')}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

elif nav.startswith("⚙️"):
    st.header("⚙️ Automation Control Center")
    with st.form("automation_form"):
        modes = ["FULL_AUTO", "SMART_AUTO", "PAUSED"]
        mode = st.selectbox("Automation Mode", modes, index=modes.index(business.get("automation_mode", "FULL_AUTO")) if business.get("automation_mode", "FULL_AUTO") in modes else 0)
        bot_enabled = st.toggle("AI Bot Enabled", value=bool(business.get("bot_enabled", True)))
        auto_reply_dms = st.toggle("Auto Reply Instagram DMs", value=bool(business.get("auto_reply_dms", True)))
        auto_reply_comments = st.toggle("Auto Reply Instagram Comments", value=bool(business.get("auto_reply_comments", True)))
        auto_send_catalog = st.toggle("Auto Send Catalog when asked", value=bool(business.get("auto_send_catalog", True)))
        human_takeover_enabled = st.toggle("Human Takeover Enabled", value=bool(business.get("human_takeover_enabled", True)))
        if st.form_submit_button(tr("save"), type="primary"):
            update_business(business_id, {"automation_mode": mode, "bot_enabled": bot_enabled, "auto_reply_dms": auto_reply_dms, "auto_reply_comments": auto_reply_comments, "auto_send_catalog": auto_send_catalog, "human_takeover_enabled": human_takeover_enabled})
            st.success("Automation saved")
            st.rerun()

    st.subheader("ManyChat-style Buttons")
    buttons = get_buttons(business_id)
    if buttons:
        st.dataframe(buttons, use_container_width=True)
    with st.expander("Add / Update Button", expanded=True):
        with st.form("button_form"):
            button_id = st.text_input("Existing Button ID (leave empty to create new)")
            title = st.text_input("Button Text", placeholder="Catalog")
            trigger = st.selectbox("Show When", ["default", "catalog", "wholesale", "delivery", "contact"])
            action_type = st.selectbox("Action Type", ["message", "url", "phone"])
            action_value = st.text_input("Action Value", placeholder="https://... or +998...")
            sort_order = st.number_input("Sort Order", min_value=0, max_value=100, value=0)
            is_active = st.toggle("Active", value=True)
            if st.form_submit_button("Save Button", type="primary"):
                row = {"business_id": business_id, "title": title.strip(), "trigger": trigger, "action_type": action_type, "action_value": action_value.strip(), "sort_order": int(sort_order), "is_active": is_active}
                if button_id.strip(): row["id"] = button_id.strip()
                upsert_button(row)
                st.success("Button saved")
                st.rerun()

elif nav.startswith("📦"):
    st.header("📦 Knowledge Center")
    with st.form("knowledge_form"):
        col1, col2 = st.columns(2)
        business_name = col1.text_input("Business Name", value=business.get("business_name", ""))
        business_type = col1.text_input("Business Type", value=business.get("business_type", ""))
        lang_opts = ["auto", "uz", "ru", "en"]
        language = col1.selectbox("Bot Default Language", lang_opts, index=lang_opts.index(business.get("bot_language_mode", "auto")) if business.get("bot_language_mode", "auto") in lang_opts else 0)
        tone = col1.text_input("Tone", value=business.get("tone", "friendly, polite, sales-focused"))
        catalog_link = col1.text_input("Catalog Link", value=business.get("catalog_link", ""))
        sales_phone = col1.text_input("Sales Phone", value=business.get("sales_phone", ""))
        telegram_single = col2.text_input("Telegram Single Product", value=business.get("telegram_single", ""))
        telegram_package = col2.text_input("Telegram Package", value=business.get("telegram_package", ""))
        telegram_bag = col2.text_input("Telegram Bag/Meshok", value=business.get("telegram_bag", ""))
        products = st.text_area("Products / Services", value=business.get("products", ""), height=130)
        prices = st.text_area("Prices", value=business.get("prices", ""), height=110)
        delivery_info = st.text_area("Delivery Info", value=business.get("delivery_info", ""), height=110)
        working_hours = st.text_area("Working Hours", value=business.get("working_hours", ""), height=90)
        faq = st.text_area("FAQ", value=business.get("faq", ""), height=140)
        knowledge = st.text_area("Unstructured Business Notes", value=business.get("knowledge", ""), height=220)
        if st.form_submit_button(tr("save"), type="primary"):
            update_business(business_id, {"business_name": business_name.strip(), "business_type": business_type.strip(), "bot_language_mode": language, "tone": tone.strip(), "catalog_link": catalog_link.strip(), "sales_phone": sales_phone.strip(), "telegram_single": telegram_single.strip(), "telegram_package": telegram_package.strip(), "telegram_bag": telegram_bag.strip(), "products": products.strip(), "prices": prices.strip(), "delivery_info": delivery_info.strip(), "working_hours": working_hours.strip(), "faq": faq.strip(), "knowledge": knowledge.strip()})
            st.success("Knowledge saved")
            st.rerun()

elif nav.startswith("👥"):
    st.header("👥 Customers")
    customers = get_customers(business_id)
    st.dataframe(customers, use_container_width=True) if customers else st.info("No customers yet.")

elif nav.startswith("📈"):
    st.header(f"📈 {business.get('business_name')} — Analytics")
    st.info("Meta analytics can be unstable for new/small accounts. Main dashboard metrics now focus on conversations, customers, and AI automation.")
    insights = get_daily_insights(business_id, 30)
    posts = get_post_insights(business_id, 25)
    latest = insights[-1] if insights else {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Followers", latest.get("followers_count", 0))
    c2.metric("Reach", latest.get("reach", 0))
    c3.metric("Profile Views", latest.get("profile_views", 0))
    c4.metric("Posts", len(posts))
    if insights:
        df = pd.DataFrame(insights)
        st.line_chart(df.set_index("insight_date")[["reach", "followers_count"]])
    if posts:
        st.dataframe(pd.DataFrame(posts), use_container_width=True)

elif nav.startswith("🔧"):
    st.header("🔧 Settings")
    with st.form("settings_form"):
        provider_opts = ["mistral", "openai"]
        ai_provider = st.selectbox("AI Provider", provider_opts, index=provider_opts.index(business.get("ai_provider", "mistral")) if business.get("ai_provider", "mistral") in provider_opts else 0)
        ai_model = st.text_input("AI Model", value=business.get("ai_model", "mistral-small-latest"))
        mistral_api_key = st.text_input("Mistral API Key", value=business.get("mistral_api_key", ""), type="password")
        openai_api_key = st.text_input("OpenAI API Key", value=business.get("openai_api_key", ""), type="password")
        memory_enabled = st.toggle("Memory Enabled", value=bool(business.get("memory_enabled", True)))
        memory_limit = st.number_input("Memory Limit", min_value=2, max_value=30, value=int(business.get("memory_limit", 12) or 12))
        st.link_button("Connect Instagram with Facebook", f"{BACKEND_URL}/connect-facebook", use_container_width=True)
        if st.form_submit_button(tr("save"), type="primary"):
            update_business(business_id, {"ai_provider": ai_provider, "ai_model": ai_model.strip(), "mistral_api_key": mistral_api_key.strip(), "openai_api_key": openai_api_key.strip(), "memory_enabled": memory_enabled, "memory_limit": int(memory_limit)})
            st.success("Settings saved")
            st.rerun()
