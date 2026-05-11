import os
import hashlib
import hmac
import time
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Instagram Bot Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    :root {
        --bg-primary: #ffffff;
        --bg-secondary: #f8f9fa;
        --text-primary: #1e293b;
        --text-secondary: #475569;
        --border-color: #e2e8f0;
        --card-shadow: 0 10px 15px -3px rgba(0,0,0,0.05), 0 4px 6px -2px rgba(0,0,0,0.025);
        --accent: #6366f1;
        --accent-hover: #4f46e5;
    }
    @media (prefers-color-scheme: dark) {
        :root {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --text-primary: #f1f5f9;
            --text-secondary: #cbd5e1;
            --border-color: #334155;
            --card-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
        }
    }
    .stApp { background-color: var(--bg-primary); }
    .modern-card {
        background-color: var(--bg-secondary);
        border-radius: 1.5rem;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        border: 1px solid var(--border-color);
        box-shadow: var(--card-shadow);
    }
    .gradient-header {
        background: linear-gradient(135deg, #6366f1, #a855f7, #ec4899);
        border-radius: 2rem;
        padding: 1.2rem 2rem;
        margin-bottom: 2rem;
        color: white;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .stButton button {
        border-radius: 40px;
        font-weight: 500;
        transition: all 0.2s ease;
        border: none;
        background-color: var(--accent);
        color: white;
    }
    .stButton button:hover {
        transform: scale(1.02);
        background-color: var(--accent-hover);
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
    }
    [data-testid="stSidebar"] {
        background-color: var(--bg-secondary);
        border-right: 1px solid var(--border-color);
    }
    .metric-card {
        background: var(--bg-secondary);
        border-radius: 1.25rem;
        padding: 1.25rem;
        text-align: center;
        border: 1px solid var(--border-color);
    }
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: var(--accent);
    }
    .metric-label {
        font-size: 0.85rem;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .stTextInput > div > div > input, .stTextArea textarea, .stSelectbox > div > div {
        background-color: var(--bg-primary);
        color: var(--text-primary);
        border-color: var(--border-color);
        border-radius: 0.75rem;
    }
</style>
""", unsafe_allow_html=True)

T = {
    "en": {
        "login_title": "Instagram Bot Dashboard",
        "login_subtitle": "Sign in to manage your businesses",
        "login": "Login",
        "invalid_login": "Invalid email or password.",
        "nav_dashboard": "📊 Dashboard",
        "nav_analytics": "📈 Analytics",
        "nav_businesses": "📋 Businesses",
        "nav_my_business": "📋 My Business",
        "nav_add_business": "➕ Add Business",
        "nav_users": "👥 Users",
        "nav_assignments": "🔗 Assignments",
        "sign_out": "🚪 Sign Out",
        "welcome": "Welcome back",
        "total_businesses": "Total Businesses",
        "active_bots": "Active Bots",
        "connected_ig": "Instagram Connected",
        "select_business": "Select Business",
        "sync_analytics": "Sync Instagram Analytics",
        "followers": "Followers",
        "reach": "Reach",
        "profile_views": "Profile Views",
        "website_clicks": "Website Clicks",
        "engagement_rate": "Engagement Rate",
        "daily_reach": "Daily Reach",
        "daily_followers": "Daily Followers",
        "top_posts": "Top Posts",
        "business_info": "🏢 Business Info",
        "business_name": "Business Name",
        "business_type": "Business Type",
        "dashboard_language": "Dashboard Language",
        "bot_language": "Bot Reply Language",
        "tone": "Tone",
        "bot_enabled": "Bot Enabled",
        "analytics_enabled": "Analytics Enabled",
        "instagram_connection": "🔌 Instagram Connection",
        "connected": "✅ Connected",
        "not_connected": "❌ Not connected",
        "connect_facebook": "Connect Instagram / Facebook",
        "ai_settings": "🧠 AI Model & Company API Keys",
        "ai_provider": "AI Provider",
        "model": "Model",
        "memory": "💬 Chat Memory",
        "memory_enable": "Enable memory for this company",
        "memory_limit": "Previous messages sent to AI",
        "knowledge": "📦 Business Knowledge",
        "products": "Products/Services",
        "prices": "Prices",
        "delivery": "Delivery Info",
        "hours": "Working Hours",
        "faq": "FAQ",
        "catalog": "Catalog Link",
        "phone": "Sales Phone",
        "telegram": "📱 Telegram Links",
        "main_prompt": "🧠 Main Knowledge Prompt",
        "save": "💾 Save Changes",
        "saved": "✅ Business updated successfully!",
        "clear_memory": "Clear all memory for this company",
        "users": "Manage Dashboard Users",
        "create_reset": "Create / Reset User",
        "activate": "Activate",
        "deactivate": "Deactivate",
        "assign": "Assign",
        "remove_assignment": "Remove Assignment",
    },
    "uz": {
        "login_title": "Instagram Bot Boshqaruvi",
        "login_subtitle": "Bizneslaringizni boshqarish uchun kiring",
        "login": "Kirish",
        "invalid_login": "Email yoki parol noto‘g‘ri.",
        "nav_dashboard": "📊 Bosh sahifa",
        "nav_analytics": "📈 Analitika",
        "nav_businesses": "📋 Bizneslar",
        "nav_my_business": "📋 Mening biznesim",
        "nav_add_business": "➕ Biznes qo‘shish",
        "nav_users": "👥 Foydalanuvchilar",
        "nav_assignments": "🔗 Biriktirish",
        "sign_out": "🚪 Chiqish",
        "welcome": "Xush kelibsiz",
        "total_businesses": "Jami bizneslar",
        "active_bots": "Faol botlar",
        "connected_ig": "Instagram ulangan",
        "select_business": "Biznesni tanlang",
        "sync_analytics": "Instagram analitikani yangilash",
        "followers": "Obunachilar",
        "reach": "Qamrov",
        "profile_views": "Profil ko‘rishlar",
        "website_clicks": "Sayt bosishlar",
        "engagement_rate": "Faollik foizi",
        "daily_reach": "Kunlik qamrov",
        "daily_followers": "Kunlik obunachilar",
        "top_posts": "Eng yaxshi postlar",
        "business_info": "🏢 Biznes ma’lumotlari",
        "business_name": "Biznes nomi",
        "business_type": "Biznes turi",
        "dashboard_language": "Dashboard tili",
        "bot_language": "Bot javob tili",
        "tone": "Muloqot uslubi",
        "bot_enabled": "Bot yoqilgan",
        "analytics_enabled": "Analitika yoqilgan",
        "instagram_connection": "🔌 Instagram ulanishi",
        "connected": "✅ Ulangan",
        "not_connected": "❌ Ulanmagan",
        "connect_facebook": "Instagram / Facebook ulash",
        "ai_settings": "🧠 AI model va kompaniya API kalitlari",
        "ai_provider": "AI provayder",
        "model": "Model",
        "memory": "💬 Chat xotirasi",
        "memory_enable": "Bu kompaniya uchun xotirani yoqish",
        "memory_limit": "AI ga yuboriladigan oldingi xabarlar",
        "knowledge": "📦 Biznes ma’lumotlari",
        "products": "Mahsulotlar/Xizmatlar",
        "prices": "Narxlar",
        "delivery": "Yetkazib berish",
        "hours": "Ish vaqti",
        "faq": "Ko‘p so‘raladigan savollar",
        "catalog": "Katalog linki",
        "phone": "Sotuv telefoni",
        "telegram": "📱 Telegram linklar",
        "main_prompt": "🧠 Asosiy bilim prompti",
        "save": "💾 Saqlash",
        "saved": "✅ Biznes muvaffaqiyatli yangilandi!",
        "clear_memory": "Bu kompaniya xotirasini tozalash",
        "users": "Dashboard foydalanuvchilari",
        "create_reset": "Foydalanuvchi yaratish / parol yangilash",
        "activate": "Faollashtirish",
        "deactivate": "O‘chirish",
        "assign": "Biriktirish",
        "remove_assignment": "Biriktirishni olib tashlash",
    },
    "ru": {
        "login_title": "Панель Instagram Бота",
        "login_subtitle": "Войдите, чтобы управлять бизнесами",
        "login": "Войти",
        "invalid_login": "Неверный email или пароль.",
        "nav_dashboard": "📊 Главная",
        "nav_analytics": "📈 Аналитика",
        "nav_businesses": "📋 Бизнесы",
        "nav_my_business": "📋 Мой бизнес",
        "nav_add_business": "➕ Добавить бизнес",
        "nav_users": "👥 Пользователи",
        "nav_assignments": "🔗 Назначения",
        "sign_out": "🚪 Выйти",
        "welcome": "Добро пожаловать",
        "total_businesses": "Всего бизнесов",
        "active_bots": "Активные боты",
        "connected_ig": "Instagram подключен",
        "select_business": "Выберите бизнес",
        "sync_analytics": "Обновить аналитику Instagram",
        "followers": "Подписчики",
        "reach": "Охват",
        "profile_views": "Просмотры профиля",
        "website_clicks": "Клики на сайт",
        "engagement_rate": "Вовлеченность",
        "daily_reach": "Дневной охват",
        "daily_followers": "Дневные подписчики",
        "top_posts": "Лучшие посты",
        "business_info": "🏢 Информация о бизнесе",
        "business_name": "Название бизнеса",
        "business_type": "Тип бизнеса",
        "dashboard_language": "Язык панели",
        "bot_language": "Язык ответа бота",
        "tone": "Тон общения",
        "bot_enabled": "Бот включен",
        "analytics_enabled": "Аналитика включена",
        "instagram_connection": "🔌 Подключение Instagram",
        "connected": "✅ Подключено",
        "not_connected": "❌ Не подключено",
        "connect_facebook": "Подключить Instagram / Facebook",
        "ai_settings": "🧠 AI модель и API ключи компании",
        "ai_provider": "AI провайдер",
        "model": "Модель",
        "memory": "💬 Память чата",
        "memory_enable": "Включить память для этой компании",
        "memory_limit": "Предыдущие сообщения для AI",
        "knowledge": "📦 Информация бизнеса",
        "products": "Товары/Услуги",
        "prices": "Цены",
        "delivery": "Доставка",
        "hours": "Рабочие часы",
        "faq": "FAQ",
        "catalog": "Ссылка на каталог",
        "phone": "Телефон продаж",
        "telegram": "📱 Telegram ссылки",
        "main_prompt": "🧠 Основной prompt знаний",
        "save": "💾 Сохранить",
        "saved": "✅ Бизнес успешно обновлен!",
        "clear_memory": "Очистить память этой компании",
        "users": "Пользователи панели",
        "create_reset": "Создать / сбросить пользователя",
        "activate": "Активировать",
        "deactivate": "Деактивировать",
        "assign": "Назначить",
        "remove_assignment": "Удалить назначение",
    },
}


def get_secret(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = get_secret("SUPABASE_SERVICE_KEY")
BACKEND_URL = get_secret("BACKEND_URL", "https://agent-1-xi6h.onrender.com")
ADMIN_EMAIL = get_secret("ADMIN_EMAIL", "")
DASHBOARD_SECRET = get_secret("DASHBOARD_SECRET")

if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY, ADMIN_EMAIL, DASHBOARD_SECRET]):
    st.error("Missing required environment variables. Please check .env or Streamlit secrets.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

AI_MODELS = {
    "mistral": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"],
}

LANGUAGE_LABELS = {
    "auto": "Auto-detect customer language",
    "uz": "Uzbek",
    "ru": "Russian",
    "en": "English",
}

DASHBOARD_LANG_LABELS = {"en": "English", "uz": "O‘zbek", "ru": "Русский"}


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def hash_password(password: str) -> str:
    return hashlib.sha256((password + DASHBOARD_SECRET).encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    return hmac.compare_digest(hash_password(password), password_hash)


def mask_secret(value: str) -> str:
    value = str(value or "")
    if not value:
        return "Not set"
    if len(value) <= 12:
        return value[:4] + "..."
    return value[:6] + "..." + value[-4:]


def tr(key: str) -> str:
    lang = st.session_state.get("ui_lang", "en")
    return T.get(lang, T["en"]).get(key, T["en"].get(key, key))


def login_user(email: str, password: str):
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


def get_user_businesses(user_email: str):
    result = (
        supabase.table("business_users")
        .select("business_id, role")
        .eq("user_email", normalize_email(user_email))
        .execute()
    )
    links = result.data or []
    if not links:
        return []
    business_ids = [item["business_id"] for item in links if item.get("business_id")]
    role_map = {item["business_id"]: item.get("role", "owner") for item in links}
    result = supabase.table("businesses").select("*").in_("id", business_ids).order("created_at", desc=True).execute()
    businesses = result.data or []
    for business in businesses:
        business["user_role"] = role_map.get(business["id"], "owner")
    return businesses


def get_all_businesses():
    result = supabase.table("businesses").select("*").order("created_at", desc=True).execute()
    return result.data or []


def get_all_dashboard_users():
    result = supabase.table("dashboard_users").select("id, email, is_active, created_at").order("created_at", desc=True).execute()
    return result.data or []


def get_business_assignments():
    result = supabase.table("business_users").select("*").order("created_at", desc=True).execute()
    return result.data or []


def update_business(business_id: str, data: dict):
    return supabase.table("businesses").update(data).eq("id", business_id).execute()


def create_or_update_dashboard_user(email: str, password: str):
    data = {"email": normalize_email(email), "password_hash": hash_password(password), "is_active": True}
    return supabase.table("dashboard_users").upsert(data, on_conflict="email").execute()


def set_user_active_status(email: str, is_active: bool):
    return supabase.table("dashboard_users").update({"is_active": is_active}).eq("email", normalize_email(email)).execute()


def assign_business_to_user(email: str, business_id: str, role: str):
    data = {"user_email": normalize_email(email), "business_id": business_id, "role": role}
    return supabase.table("business_users").upsert(data, on_conflict="user_email,business_id").execute()


def remove_business_assignment(email: str, business_id: str):
    return supabase.table("business_users").delete().eq("user_email", normalize_email(email)).eq("business_id", business_id).execute()


def create_business(data: dict):
    return supabase.table("businesses").insert(data).execute()


def get_memory_count(business_id: str):
    try:
        result = supabase.table("chat_memory").select("id", count="exact").eq("business_id", business_id).execute()
        return result.count or 0
    except Exception:
        return 0


def clear_business_memory(business_id: str):
    return supabase.table("chat_memory").delete().eq("business_id", business_id).execute()


def get_daily_insights(business_id: str, days: int = 30):
    start = (date.today() - timedelta(days=days)).isoformat()
    try:
        result = (
            supabase.table("instagram_daily_insights")
            .select("*")
            .eq("business_id", business_id)
            .gte("date", start)
            .order("date", desc=False)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def get_post_insights(business_id: str):
    try:
        result = (
            supabase.table("instagram_post_insights")
            .select("*")
            .eq("business_id", business_id)
            .order("engagement_rate", desc=True)
            .limit(50)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def sync_analytics(business_id: str, days: int = 30, limit: int = 25):
    url = f"{BACKEND_URL.rstrip('/')}/analytics/sync"
    res = requests.post(
        url,
        params={"business_id": business_id, "days": days, "limit": limit, "dashboard_secret": DASHBOARD_SECRET},
        timeout=90,
    )
    res.raise_for_status()
    return res.json()


def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "en"

if "user" not in st.session_state:
    st.markdown(f"""
    <div style="display: flex; justify-content: center; align-items: center; min-height: 42vh;">
        <div class="modern-card" style="width: 100%; max-width: 450px; text-align: center;">
            <h1 style="font-size: 2.5rem;">🤖</h1>
            <h2>{tr('login_title')}</h2>
            <p style="color: var(--text-secondary); margin-bottom: 2rem;">{tr('login_subtitle')}</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        lang_choice = st.selectbox("Language", list(DASHBOARD_LANG_LABELS.keys()), format_func=lambda x: DASHBOARD_LANG_LABELS[x], index=list(DASHBOARD_LANG_LABELS.keys()).index(st.session_state["ui_lang"]))
        st.session_state["ui_lang"] = lang_choice
        email = st.text_input("Email", placeholder="admin@example.com", label_visibility="collapsed")
        password = st.text_input("Password", type="password", placeholder="••••••••", label_visibility="collapsed")
        if st.button(tr("login"), type="primary", use_container_width=True):
            with st.spinner("Authenticating..."):
                user = login_user(email, password)
            if user:
                st.session_state["user"] = user
                st.toast("Welcome back! 🎉", icon="✅")
                st.rerun()
            else:
                st.error(tr("invalid_login"))
    st.stop()

user = st.session_state["user"]
user_email = normalize_email(user.get("email"))
is_admin = user_email == normalize_email(ADMIN_EMAIL)

with st.sidebar:
    st.markdown(f"""
    <div style="text-align: center; margin-bottom: 2rem;">
        <div style="font-size: 3rem;">🤖</div>
        <h3>Bot Manager</h3>
        <p style="color: var(--text-secondary); font-size: 0.85rem;">{user_email}</p>
        <div style="background: var(--accent); border-radius: 40px; padding: 0.2rem 0.8rem; display: inline-block; color: white;">
            {"⭐ Admin" if is_admin else "👤 Business Owner"}
        </div>
    </div>
    """, unsafe_allow_html=True)

    lang_choice = st.selectbox("🌐", list(DASHBOARD_LANG_LABELS.keys()), format_func=lambda x: DASHBOARD_LANG_LABELS[x], index=list(DASHBOARD_LANG_LABELS.keys()).index(st.session_state.get("ui_lang", "en")))
    if lang_choice != st.session_state.get("ui_lang"):
        st.session_state["ui_lang"] = lang_choice
        st.rerun()

    if is_admin:
        nav_items = [tr("nav_dashboard"), tr("nav_analytics"), tr("nav_businesses"), tr("nav_add_business"), tr("nav_users"), tr("nav_assignments")]
    else:
        nav_items = [tr("nav_dashboard"), tr("nav_analytics"), tr("nav_my_business")]
    nav_option = st.radio("Navigation", nav_items, index=0, label_visibility="collapsed")

    st.divider()
    if st.button(tr("sign_out"), use_container_width=True):
        logout()


def business_selector(businesses):
    if not businesses:
        return None
    if len(businesses) == 1:
        return businesses[0]
    business_options = {f"{b.get('business_name','')} ({b.get('instagram_business_id', 'No ID')})": b for b in businesses}
    selected = st.selectbox(tr("select_business"), list(business_options.keys()))
    return business_options[selected]


def show_metrics():
    businesses = get_all_businesses() if is_admin else get_user_businesses(user_email)
    total_businesses = len(businesses)
    active_bots = sum(1 for b in businesses if b.get("bot_enabled", False))
    connected_ig = sum(1 for b in businesses if b.get("access_token") or b.get("page_access_token"))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"<div class='metric-card'><div class='metric-value'>{total_businesses}</div><div class='metric-label'>{tr('total_businesses')}</div></div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div class='metric-card'><div class='metric-value'>{active_bots}</div><div class='metric-label'>{tr('active_bots')}</div></div>", unsafe_allow_html=True)
    with col3:
        st.markdown(f"<div class='metric-card'><div class='metric-value'>{connected_ig}</div><div class='metric-label'>{tr('connected_ig')}</div></div>", unsafe_allow_html=True)


st.markdown("<div class='gradient-header'><div><span style='font-size:1.8rem;'>🤖</span> <strong>Instagram Bot Dashboard</strong></div><div>✨ AI-Powered Engagement</div></div>", unsafe_allow_html=True)

if nav_option == tr("nav_dashboard"):
    st.markdown(f"## {tr('welcome')}, {user_email.split('@')[0]}!")
    show_metrics()

elif nav_option == tr("nav_analytics"):
    businesses = get_all_businesses() if is_admin else get_user_businesses(user_email)
    business = business_selector(businesses)
    if not business:
        st.warning("No businesses found.")
    else:
        st.markdown(f"## 📈 {business.get('business_name', '')} — {tr('nav_analytics').replace('📈 ', '')}")
        col_s1, col_s2, col_s3 = st.columns([1, 1, 2])
        with col_s1:
            days = st.selectbox("Days", [7, 14, 30, 60, 90], index=2)
        with col_s2:
            post_limit = st.selectbox("Posts", [10, 25, 50, 100], index=1)
        with col_s3:
            if st.button(tr("sync_analytics"), type="primary", use_container_width=True):
                try:
                    with st.spinner("Syncing from Meta..."):
                        result = sync_analytics(business["id"], days, post_limit)
                    st.success(f"Synced: {result}")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Sync failed: {e}")

        daily_rows = get_daily_insights(business["id"], days)
        post_rows = get_post_insights(business["id"])

        if not daily_rows and not post_rows:
            st.info("No analytics yet. Click Sync Instagram Analytics first. You also need instagram_manage_insights permission.")
        else:
            df_daily = pd.DataFrame(daily_rows)
            df_posts = pd.DataFrame(post_rows)

            total_reach = int(df_daily["reach"].sum()) if not df_daily.empty and "reach" in df_daily else 0
            total_profile_views = int(df_daily["profile_views"].sum()) if not df_daily.empty and "profile_views" in df_daily else 0
            total_website_clicks = int(df_daily["website_clicks"].sum()) if not df_daily.empty and "website_clicks" in df_daily else 0
            avg_engagement = round(float(df_posts["engagement_rate"].mean()), 2) if not df_posts.empty and "engagement_rate" in df_posts else 0
            latest_followers = int(df_daily["followers"].iloc[-1]) if not df_daily.empty and "followers" in df_daily and len(df_daily) else 0

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric(tr("followers"), latest_followers)
            c2.metric(tr("reach"), total_reach)
            c3.metric(tr("profile_views"), total_profile_views)
            c4.metric(tr("website_clicks"), total_website_clicks)
            c5.metric(tr("engagement_rate"), f"{avg_engagement}%")

            if not df_daily.empty:
                df_daily["date"] = pd.to_datetime(df_daily["date"])
                chart_df = df_daily.set_index("date")
                if "reach" in chart_df.columns:
                    st.subheader(tr("daily_reach"))
                    st.bar_chart(chart_df[["reach"]])
                if "followers" in chart_df.columns:
                    st.subheader(tr("daily_followers"))
                    st.line_chart(chart_df[["followers"]])

            if not df_posts.empty:
                st.subheader(tr("top_posts"))
                columns = ["caption", "media_type", "likes", "comments", "reach", "views", "saved", "shares", "engagement_rate", "permalink"]
                existing = [c for c in columns if c in df_posts.columns]
                st.dataframe(df_posts[existing], use_container_width=True)

elif nav_option in [tr("nav_businesses"), tr("nav_my_business")]:
    businesses = get_all_businesses() if is_admin else get_user_businesses(user_email)
    business = business_selector(businesses)
    if not business:
        st.warning("No businesses found.")
    else:
        st.markdown(f"### Editing: {business.get('business_name', '')}")
        with st.form(key=f"edit_{business['id']}"):
            with st.expander(tr("business_info"), expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    business_name = st.text_input(tr("business_name"), value=business.get("business_name", ""))
                    business_type = st.text_input(tr("business_type"), value=business.get("business_type", ""))
                    dashboard_language = st.selectbox(tr("dashboard_language"), list(DASHBOARD_LANG_LABELS.keys()), format_func=lambda x: DASHBOARD_LANG_LABELS[x], index=list(DASHBOARD_LANG_LABELS.keys()).index(business.get("dashboard_language") if business.get("dashboard_language") in DASHBOARD_LANG_LABELS else st.session_state.get("ui_lang", "en")))
                with col2:
                    lang_keys = list(LANGUAGE_LABELS.keys())
                    current_lang = business.get("language", "auto")
                    if current_lang not in lang_keys:
                        current_lang = "auto"
                    language = st.selectbox(tr("bot_language"), lang_keys, format_func=lambda x: LANGUAGE_LABELS[x], index=lang_keys.index(current_lang))
                    tone = st.text_input(tr("tone"), value=business.get("tone", "friendly, polite"))
                    bot_enabled = st.toggle(tr("bot_enabled"), value=business.get("bot_enabled", True))
                    analytics_enabled = st.toggle(tr("analytics_enabled"), value=business.get("analytics_enabled", True))

            with st.expander(tr("instagram_connection")):
                st.text_input("Instagram Business ID", value=business.get("instagram_business_id", ""), disabled=True)
                st.text_input("Facebook Page ID", value=business.get("facebook_page_id", ""), disabled=True)
                if business.get("access_token") or business.get("page_access_token"):
                    st.success(tr("connected"))
                else:
                    st.error(tr("not_connected"))
                if is_admin:
                    st.link_button(tr("connect_facebook"), f"{BACKEND_URL}/connect-facebook", use_container_width=True)

            with st.expander(tr("ai_settings"), expanded=True):
                current_provider = business.get("ai_provider") or "mistral"
                if current_provider not in AI_MODELS:
                    current_provider = "mistral"
                ai_provider = st.selectbox(tr("ai_provider"), list(AI_MODELS.keys()), index=list(AI_MODELS.keys()).index(current_provider))
                available_models = AI_MODELS[ai_provider]
                current_model = business.get("ai_model") or available_models[0]
                if current_model not in available_models:
                    current_model = available_models[0]
                ai_model = st.selectbox(tr("model"), available_models, index=available_models.index(current_model))
                col_key1, col_key2, col_key3 = st.columns(3)
                with col_key1:
                    st.caption(f"Mistral key: {mask_secret(business.get('mistral_api_key', ''))}")
                    mistral_api_key_new = st.text_input("New Mistral API Key", type="password", placeholder="Leave blank to keep existing key")
                with col_key2:
                    st.caption(f"OpenAI key: {mask_secret(business.get('openai_api_key', ''))}")
                    openai_api_key_new = st.text_input("New OpenAI API Key", type="password", placeholder="Leave blank to keep existing key")
                with col_key3:
                    st.caption(f"Gemini key: {mask_secret(business.get('gemini_api_key', ''))}")
                    gemini_api_key_new = st.text_input("New Gemini API Key", type="password", placeholder="Leave blank to keep existing key")

            with st.expander(tr("memory")):
                memory_enabled = st.toggle(tr("memory_enable"), value=business.get("memory_enabled", True))
                memory_limit = st.slider(tr("memory_limit"), min_value=2, max_value=30, value=int(business.get("memory_limit") or 12), step=2)

            with st.expander(tr("knowledge")):
                products = st.text_area(tr("products"), value=business.get("products", ""), height=100)
                prices = st.text_area(tr("prices"), value=business.get("prices", ""), height=80)
                delivery = st.text_area(tr("delivery"), value=business.get("delivery_info", ""), height=80)
                hours = st.text_area(tr("hours"), value=business.get("working_hours", ""), height=80)
                faq = st.text_area(tr("faq"), value=business.get("faq", ""), height=120)
                catalog = st.text_input(tr("catalog"), value=business.get("catalog_link", ""))
                phone = st.text_input(tr("phone"), value=business.get("sales_phone", ""))

            with st.expander(tr("telegram")):
                tg_single = st.text_input("Single Product Link", value=business.get("telegram_single", ""))
                tg_package = st.text_input("Package Link", value=business.get("telegram_package", ""))
                tg_bag = st.text_input("Bag/Meshok Link", value=business.get("telegram_bag", ""))

            with st.expander(tr("main_prompt")):
                knowledge = st.text_area("Main Knowledge", value=business.get("knowledge", ""), height=250)

            if st.form_submit_button(tr("save"), type="primary", use_container_width=True):
                if not business_name.strip():
                    st.error("Business name is required.")
                else:
                    update_data = {
                        "business_name": business_name.strip(),
                        "business_type": business_type.strip(),
                        "dashboard_language": dashboard_language,
                        "language": language,
                        "tone": tone.strip(),
                        "bot_enabled": bot_enabled,
                        "analytics_enabled": analytics_enabled,
                        "ai_provider": ai_provider,
                        "ai_model": ai_model,
                        "memory_enabled": memory_enabled,
                        "memory_limit": memory_limit,
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
                    if mistral_api_key_new.strip():
                        update_data["mistral_api_key"] = mistral_api_key_new.strip()
                    if openai_api_key_new.strip():
                        update_data["openai_api_key"] = openai_api_key_new.strip()
                    if gemini_api_key_new.strip():
                        update_data["gemini_api_key"] = gemini_api_key_new.strip()
                    try:
                        update_business(business["id"], update_data)
                        st.session_state["ui_lang"] = dashboard_language
                        st.success(tr("saved"))
                        st.balloons()
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        with st.expander("🧹 Memory Admin Tools"):
            memory_count = get_memory_count(business["id"])
            st.write(f"Stored memory messages for this company: **{memory_count}**")
            if st.button(tr("clear_memory"), type="secondary"):
                try:
                    clear_business_memory(business["id"])
                    st.success("Memory cleared.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not clear memory: {e}")

elif nav_option == tr("nav_add_business") and is_admin:
    st.markdown(f"## {tr('nav_add_business')}")
    with st.form("add_business"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input(f"{tr('business_name')} *")
            ig_id = st.text_input("Instagram Business ID *")
            fb_id = st.text_input("Facebook Page ID")
        with col2:
            biz_type = st.text_input(tr("business_type"))
            lang = st.selectbox(tr("bot_language"), list(LANGUAGE_LABELS.keys()), format_func=lambda x: LANGUAGE_LABELS[x])
            dashboard_language = st.selectbox(tr("dashboard_language"), list(DASHBOARD_LANG_LABELS.keys()), format_func=lambda x: DASHBOARD_LANG_LABELS[x])
            tone_val = st.text_input(tr("tone"), value="friendly, polite")
        ai_provider = st.selectbox(tr("ai_provider"), list(AI_MODELS.keys()))
        ai_model = st.selectbox(tr("model"), AI_MODELS[ai_provider])
        if st.form_submit_button("Create Business", type="primary"):
            if not name.strip() or not ig_id.strip():
                st.error("Business Name and Instagram ID are required.")
            else:
                data = {
                    "business_name": name.strip(),
                    "instagram_business_id": ig_id.strip(),
                    "facebook_page_id": fb_id.strip(),
                    "business_type": biz_type.strip(),
                    "dashboard_language": dashboard_language,
                    "language": lang,
                    "tone": tone_val.strip(),
                    "bot_enabled": False,
                    "analytics_enabled": True,
                    "knowledge": "",
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
                    "ai_provider": ai_provider,
                    "ai_model": ai_model,
                    "mistral_api_key": "",
                    "openai_api_key": "",
                    "gemini_api_key": "",
                    "memory_enabled": True,
                    "memory_limit": 12,
                }
                try:
                    create_business(data)
                    st.success("Business created!")
                    st.balloons()
                    st.rerun()
                except Exception as e:
                    st.error(f"Creation failed: {e}")

elif nav_option == tr("nav_users") and is_admin:
    st.markdown(f"## 👥 {tr('users')}")
    with st.expander(tr("create_reset")):
        email_u = st.text_input("User Email")
        pwd_u = st.text_input("Password", type="password")
        if st.button("Create/Reset"):
            if email_u and pwd_u:
                create_or_update_dashboard_user(email_u, pwd_u)
                st.success("User saved.")
                st.rerun()
            else:
                st.error("Email and password required.")
    with st.expander("Activate / Deactivate User"):
        email_status = st.text_input("Email for status change")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button(tr("activate")):
                if email_status:
                    set_user_active_status(email_status, True)
                    st.success("Activated")
                else:
                    st.error("Email required")
        with col_b:
            if st.button(tr("deactivate")):
                if email_status:
                    set_user_active_status(email_status, False)
                    st.success("Deactivated")
                else:
                    st.error("Email required")
    users_list = get_all_dashboard_users()
    if users_list:
        st.dataframe(users_list, use_container_width=True)
    else:
        st.info("No users.")

elif nav_option == tr("nav_assignments") and is_admin:
    st.markdown(f"## {tr('nav_assignments')}")
    all_biz = get_all_businesses()
    if not all_biz:
        st.warning("No businesses exist.")
    else:
        biz_map = {f"{b['business_name']} ({b['id'][:8]})": b["id"] for b in all_biz}
        email_assign = st.text_input("User Email")
        selected_biz = st.selectbox("Business", list(biz_map.keys()))
        role = st.selectbox("Role", ["owner", "editor"])
        col1, col2 = st.columns(2)
        with col1:
            if st.button(tr("assign"), use_container_width=True):
                if email_assign:
                    assign_business_to_user(email_assign, biz_map[selected_biz], role)
                    st.success("Assigned!")
                    st.rerun()
                else:
                    st.error("Email required")
        with col2:
            if st.button(tr("remove_assignment"), use_container_width=True):
                if email_assign:
                    remove_business_assignment(email_assign, biz_map[selected_biz])
                    st.success("Removed")
                    st.rerun()
                else:
                    st.error("Email required")
    st.divider()
    assignments = get_business_assignments()
    if assignments:
        st.dataframe(assignments, use_container_width=True)
    else:
        st.info("No assignments.")
