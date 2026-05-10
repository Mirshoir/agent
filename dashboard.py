import os
import hashlib
import hmac
import time
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

    .stApp {
        background-color: var(--bg-primary);
    }

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
        background-size: 200% 200%;
        animation: gradientShift 6s ease infinite;
        border-radius: 2rem;
        padding: 1.2rem 2rem;
        margin-bottom: 2rem;
        color: white;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    @keyframes gradientShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
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

    hr {
        border-color: var(--border-color);
    }
</style>
""", unsafe_allow_html=True)


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
    "mistral": [
        "mistral-small-latest",
        "mistral-medium-latest",
        "mistral-large-latest",
    ],
    "openai": [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1-mini",
        "gpt-4.1",
    ],
}


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


def login_user(email: str, password: str):
    email = normalize_email(email)

    result = (
        supabase.table("dashboard_users")
        .select("*")
        .eq("email", email)
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

    business_ids = [
        item["business_id"]
        for item in links
        if item.get("business_id")
    ]

    role_map = {
        item["business_id"]: item.get("role", "owner")
        for item in links
    }

    result = (
        supabase.table("businesses")
        .select("*")
        .in_("id", business_ids)
        .order("created_at", desc=True)
        .execute()
    )

    businesses = result.data or []

    for business in businesses:
        business["user_role"] = role_map.get(business["id"], "owner")

    return businesses


def get_all_businesses():
    result = (
        supabase.table("businesses")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


def get_all_dashboard_users():
    result = (
        supabase.table("dashboard_users")
        .select("id, email, is_active, created_at")
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


def get_business_assignments():
    result = (
        supabase.table("business_users")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


def update_business(business_id: str, data: dict):
    return (
        supabase.table("businesses")
        .update(data)
        .eq("id", business_id)
        .execute()
    )


def create_or_update_dashboard_user(email: str, password: str):
    data = {
        "email": normalize_email(email),
        "password_hash": hash_password(password),
        "is_active": True,
    }

    return (
        supabase.table("dashboard_users")
        .upsert(data, on_conflict="email")
        .execute()
    )


def set_user_active_status(email: str, is_active: bool):
    return (
        supabase.table("dashboard_users")
        .update({"is_active": is_active})
        .eq("email", normalize_email(email))
        .execute()
    )


def assign_business_to_user(email: str, business_id: str, role: str):
    data = {
        "user_email": normalize_email(email),
        "business_id": business_id,
        "role": role,
    }

    return (
        supabase.table("business_users")
        .upsert(data, on_conflict="user_email,business_id")
        .execute()
    )


def remove_business_assignment(email: str, business_id: str):
    return (
        supabase.table("business_users")
        .delete()
        .eq("user_email", normalize_email(email))
        .eq("business_id", business_id)
        .execute()
    )


def create_business(data: dict):
    return supabase.table("businesses").insert(data).execute()


def get_memory_count(business_id: str):
    try:
        result = (
            supabase.table("chat_memory")
            .select("id", count="exact")
            .eq("business_id", business_id)
            .execute()
        )

        return result.count or 0
    except Exception:
        return 0


def clear_business_memory(business_id: str):
    return (
        supabase.table("chat_memory")
        .delete()
        .eq("business_id", business_id)
        .execute()
    )


def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]

    st.rerun()


if "user" not in st.session_state:
    st.markdown("""
    <div style="display: flex; justify-content: center; align-items: center; min-height: 42vh;">
        <div class="modern-card" style="width: 100%; max-width: 450px; text-align: center;">
            <h1 style="font-size: 2.5rem;">🤖</h1>
            <h2>Instagram Bot Dashboard</h2>
            <p style="color: var(--text-secondary); margin-bottom: 2rem;">Sign in to manage your businesses</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        email = st.text_input("Email", placeholder="admin@example.com", label_visibility="collapsed")
        password = st.text_input("Password", type="password", placeholder="••••••••", label_visibility="collapsed")

        if st.button("Login", type="primary", use_container_width=True):
            with st.spinner("Authenticating..."):
                user = login_user(email, password)

            if user:
                st.session_state["user"] = user
                st.toast("Welcome back! 🎉", icon="✅")
                st.rerun()
            else:
                st.error("Invalid email or password.")

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

    if is_admin:
        nav_option = st.radio(
            "Navigation",
            ["📊 Dashboard", "📋 Businesses", "➕ Add Business", "👥 Users", "🔗 Assignments"],
            index=0,
            label_visibility="collapsed",
        )
    else:
        nav_option = st.radio(
            "Navigation",
            ["📊 Dashboard", "📋 My Business"],
            label_visibility="collapsed",
        )

    st.divider()

    if st.button("🚪 Sign Out", use_container_width=True):
        logout()


def show_metrics():
    businesses = get_all_businesses() if is_admin else get_user_businesses(user_email)
    total_businesses = len(businesses)
    active_bots = sum(1 for b in businesses if b.get("bot_enabled", False))
    connected_ig = sum(1 for b in businesses if b.get("access_token") or b.get("page_access_token"))

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{total_businesses}</div>
            <div class="metric-label">Total Businesses</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{active_bots}</div>
            <div class="metric-label">Active Bots</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{connected_ig}</div>
            <div class="metric-label">Instagram Connected</div>
        </div>
        """, unsafe_allow_html=True)


st.markdown(
    '<div class="gradient-header"><div><span style="font-size:1.8rem;">🤖</span> <strong>Instagram Bot Dashboard</strong></div><div>✨ AI-Powered Engagement</div></div>',
    unsafe_allow_html=True,
)

if nav_option == "📊 Dashboard":
    st.markdown("## Welcome back, " + user_email.split("@")[0] + "!")
    show_metrics()

    with st.expander("📈 Recent Activity", expanded=True):
        st.info("Coming soon: Real-time bot activity logs and analytics.")

elif nav_option in ["📋 Businesses", "📋 My Business"]:
    businesses = get_all_businesses() if is_admin else get_user_businesses(user_email)

    if not businesses:
        st.warning("No businesses found. Contact admin or add a business.")
    else:
        if len(businesses) == 1:
            business = businesses[0]
        else:
            business_options = {
                f"{b['business_name']} ({b.get('instagram_business_id', 'No ID')})": b
                for b in businesses
            }

            selected = st.selectbox("Select Business", list(business_options.keys()))
            business = business_options[selected]

        st.markdown(f"### Editing: {business.get('business_name', '')}")

        with st.form(key=f"edit_{business['id']}"):
            with st.expander("🏢 Business Info", expanded=True):
                col1, col2 = st.columns(2)

                with col1:
                    business_name = st.text_input(
                        "Business Name",
                        value=business.get("business_name", ""),
                    )

                with col2:
                    business_type = st.text_input(
                        "Business Type",
                        value=business.get("business_type", ""),
                    )

                language_options = ["uz", "ru", "en"]
                language_value = business.get("language", "uz")

                if language_value not in language_options:
                    language_value = "uz"

                language = st.selectbox(
                    "Language",
                    language_options,
                    index=language_options.index(language_value),
                )

                tone = st.text_input(
                    "Tone",
                    value=business.get("tone", "friendly, polite"),
                )

                bot_enabled = st.toggle(
                    "Bot Enabled",
                    value=business.get("bot_enabled", True),
                )

            with st.expander("🔌 Instagram Connection"):
                st.text_input(
                    "Instagram Business ID",
                    value=business.get("instagram_business_id", ""),
                    disabled=True,
                )

                st.text_input(
                    "Facebook Page ID",
                    value=business.get("facebook_page_id", ""),
                    disabled=True,
                )

                if business.get("access_token") or business.get("page_access_token"):
                    st.success("✅ Connected")
                else:
                    st.error("❌ Not connected")

                if is_admin:
                    col_a, col_b = st.columns(2)

                    with col_a:
                        st.link_button(
                            "Reconnect Instagram",
                            f"{BACKEND_URL}/connect-instagram",
                            use_container_width=True,
                        )

                    with col_b:
                        st.link_button(
                            "Connect FB Page",
                            f"{BACKEND_URL}/connect-facebook",
                            use_container_width=True,
                        )

            with st.expander("🧠 AI Model & Company API Keys", expanded=True):
                current_provider = business.get("ai_provider") or "mistral"

                if current_provider not in AI_MODELS:
                    current_provider = "mistral"

                ai_provider = st.selectbox(
                    "AI Provider",
                    ["mistral", "openai"],
                    index=["mistral", "openai"].index(current_provider),
                )

                available_models = AI_MODELS[ai_provider]
                current_model = business.get("ai_model") or available_models[0]

                if current_model not in available_models:
                    current_model = available_models[0]

                ai_model = st.selectbox(
                    "Model",
                    available_models,
                    index=available_models.index(current_model),
                )

                col_key1, col_key2 = st.columns(2)

                with col_key1:
                    st.caption(f"Mistral key: {mask_secret(business.get('mistral_api_key', ''))}")
                    mistral_api_key_new = st.text_input(
                        "New Mistral API Key",
                        type="password",
                        placeholder="Leave blank to keep existing key",
                    )

                with col_key2:
                    st.caption(f"OpenAI key: {mask_secret(business.get('openai_api_key', ''))}")
                    openai_api_key_new = st.text_input(
                        "New OpenAI API Key",
                        type="password",
                        placeholder="Leave blank to keep existing key",
                    )

                st.warning(
                    "Each company should add its own API key. If the selected provider key is missing, the bot will use fallback response only."
                )

            with st.expander("💬 Chat Memory"):
                memory_enabled = st.toggle(
                    "Enable memory for this company",
                    value=business.get("memory_enabled", True),
                )

                memory_limit = st.slider(
                    "How many previous messages to send to AI",
                    min_value=2,
                    max_value=30,
                    value=int(business.get("memory_limit") or 12),
                    step=2,
                )

                st.caption(
                    "Memory is separated by business_id + customer_id + channel, so different users and companies do not mix."
                )

            with st.expander("📦 Business Knowledge"):
                products = st.text_area(
                    "Products/Services",
                    value=business.get("products", ""),
                    height=100,
                )

                prices = st.text_area(
                    "Prices",
                    value=business.get("prices", ""),
                    height=80,
                )

                delivery = st.text_area(
                    "Delivery Info",
                    value=business.get("delivery_info", ""),
                    height=80,
                )

                hours = st.text_area(
                    "Working Hours",
                    value=business.get("working_hours", ""),
                    height=80,
                )

                faq = st.text_area(
                    "FAQ",
                    value=business.get("faq", ""),
                    height=120,
                )

                catalog = st.text_input(
                    "Catalog Link",
                    value=business.get("catalog_link", ""),
                )

                phone = st.text_input(
                    "Sales Phone",
                    value=business.get("sales_phone", ""),
                )

            with st.expander("📱 Telegram Links"):
                tg_single = st.text_input(
                    "Single Product Link",
                    value=business.get("telegram_single", ""),
                )

                tg_package = st.text_input(
                    "Package Link",
                    value=business.get("telegram_package", ""),
                )

                tg_bag = st.text_input(
                    "Bag/Meshok Link",
                    value=business.get("telegram_bag", ""),
                )

            with st.expander("🧠 Main Knowledge Prompt"):
                knowledge = st.text_area(
                    "Main Knowledge",
                    value=business.get("knowledge", ""),
                    height=250,
                )

            if st.form_submit_button("💾 Save Changes", type="primary", use_container_width=True):
                if not business_name.strip():
                    st.error("Business name is required.")
                else:
                    update_data = {
                        "business_name": business_name.strip(),
                        "business_type": business_type.strip(),
                        "language": language,
                        "tone": tone.strip(),
                        "bot_enabled": bot_enabled,
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

                    try:
                        update_business(business["id"], update_data)
                        st.success("✅ Business updated successfully!")
                        st.balloons()
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        with st.expander("🧹 Memory Admin Tools"):
            memory_count = get_memory_count(business["id"])
            st.write(f"Stored memory messages for this company: **{memory_count}**")

            if st.button("Clear all memory for this company", type="secondary"):
                try:
                    clear_business_memory(business["id"])
                    st.success("Memory cleared.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not clear memory: {e}")

elif nav_option == "➕ Add Business" and is_admin:
    st.markdown("## ➕ Add New Business")

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

        ai_provider = st.selectbox("AI Provider", ["mistral", "openai"])
        ai_model = st.selectbox("Model", AI_MODELS[ai_provider])

        if st.form_submit_button("Create Business", type="primary"):
            if not name.strip() or not ig_id.strip():
                st.error("Business Name and Instagram ID are required.")
            else:
                data = {
                    "business_name": name.strip(),
                    "instagram_business_id": ig_id.strip(),
                    "facebook_page_id": fb_id.strip(),
                    "business_type": biz_type.strip(),
                    "language": lang,
                    "tone": tone_val.strip(),
                    "bot_enabled": False,
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

elif nav_option == "👥 Users" and is_admin:
    st.markdown("## 👥 Manage Dashboard Users")

    with st.expander("Create / Reset User"):
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
            if st.button("Activate"):
                if email_status:
                    set_user_active_status(email_status, True)
                    st.success("Activated")
                else:
                    st.error("Email required")

        with col_b:
            if st.button("Deactivate"):
                if email_status:
                    set_user_active_status(email_status, False)
                    st.success("Deactivated")
                else:
                    st.error("Email required")

    st.subheader("Existing Users")
    users_list = get_all_dashboard_users()

    if users_list:
        st.dataframe(users_list, use_container_width=True)
    else:
        st.info("No users.")

elif nav_option == "🔗 Assignments" and is_admin:
    st.markdown("## 🔗 Assign Business to User")
    all_biz = get_all_businesses()

    if not all_biz:
        st.warning("No businesses exist.")
    else:
        biz_map = {
            f"{b['business_name']} ({b['id'][:8]})": b["id"]
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
                    st.success("Assigned!")
                    st.rerun()
                else:
                    st.error("Email required")

        with col2:
            if st.button("Remove Assignment", use_container_width=True):
                if email_assign:
                    remove_business_assignment(email_assign, biz_map[selected_biz])
                    st.success("Removed")
                    st.rerun()
                else:
                    st.error("Email required")

    st.divider()
    st.subheader("Current Assignments")
    assignments = get_business_assignments()

    if assignments:
        st.dataframe(assignments, use_container_width=True)
    else:
        st.info("No assignments.")
