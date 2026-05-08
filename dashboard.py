import os
import hashlib
import hmac
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Instagram Bot Dashboard",
    page_icon="🤖",
    layout="wide"
)


def get_secret(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = get_secret("SUPABASE_SERVICE_KEY")
BACKEND_URL = get_secret("BACKEND_URL", "https://agent-1-xi6h.onrender.com")
ADMIN_EMAIL = get_secret("ADMIN_EMAIL", "")
DASHBOARD_SECRET = get_secret("DASHBOARD_SECRET", "change-this-secret")

if not SUPABASE_URL:
    st.error("Missing SUPABASE_URL")
    st.stop()

if not SUPABASE_SERVICE_KEY:
    st.error("Missing SUPABASE_SERVICE_KEY")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def hash_password(password: str) -> str:
    return hashlib.sha256((password + DASHBOARD_SECRET).encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)


def login_user(email: str, password: str):
    email = email.strip().lower()

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
        .eq("user_email", user_email.strip().lower())
        .execute()
    )

    links = result.data or []

    if not links:
        return []

    business_ids = [item["business_id"] for item in links if item.get("business_id")]
    role_map = {item["business_id"]: item.get("role", "owner") for item in links}

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


def create_dashboard_user(email: str, password: str):
    data = {
        "email": email.strip().lower(),
        "password_hash": hash_password(password),
        "is_active": True,
    }

    return supabase.table("dashboard_users").insert(data).execute()


def assign_business_to_user(email: str, business_id: str, role: str):
    data = {
        "user_email": email.strip().lower(),
        "business_id": business_id,
        "role": role,
    }

    return supabase.table("business_users").upsert(
        data,
        on_conflict="user_email,business_id"
    ).execute()


def create_business(data: dict):
    return supabase.table("businesses").insert(data).execute()


def logout():
    st.session_state.clear()
    st.rerun()


if "user" not in st.session_state:
    st.title("🔐 Business Dashboard Login")

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if st.button("Login", type="primary"):
        user = login_user(email, password)

        if user:
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("Invalid email or password.")

    st.stop()


user = st.session_state["user"]
user_email = user["email"].strip().lower()
is_admin = user_email == ADMIN_EMAIL.strip().lower()

st.title("🤖 Instagram Bot Business Dashboard")

col1, col2 = st.columns([3, 1])

with col1:
    st.write(f"Logged in as: **{user_email}**")

with col2:
    if st.button("Logout"):
        logout()

query_params = st.query_params

if query_params.get("connected") == "success":
    st.success("Instagram connected successfully.")

st.divider()

if is_admin:
    tabs = st.tabs([
        "📋 Edit Businesses",
        "➕ Add Business",
        "👤 Users",
        "🔗 Assign Business",
    ])
else:
    tabs = st.tabs(["📋 Edit Business"])

with tabs[0]:
    if is_admin:
        businesses = get_all_businesses()
    else:
        businesses = get_user_businesses(user_email)

    if not businesses:
        st.warning("No business assigned to your account.")
        st.stop()

    if len(businesses) == 1:
        business = businesses[0]
        st.info(f"Editing: {business.get('business_name', 'Unnamed')}")
    else:
        business_options = {
            f"{b.get('business_name', 'Unnamed')} — {b.get('instagram_business_id', 'No IG ID')}": b
            for b in businesses
        }

        selected_business = st.selectbox(
            "Select your assigned business",
            list(business_options.keys())
        )

        business = business_options[selected_business]

    st.divider()

    left, right = st.columns(2)

    with left:
        st.subheader("Business Info")

        business_name = st.text_input(
            "Business name",
            value=business.get("business_name") or ""
        )

        business_type = st.text_input(
            "Business type",
            value=business.get("business_type") or ""
        )

        current_language = business.get("language") or "uz"

        if current_language not in ["uz", "ru", "en"]:
            current_language = "uz"

        language = st.selectbox(
            "Default language",
            ["uz", "ru", "en"],
            index=["uz", "ru", "en"].index(current_language)
        )

        tone = st.text_input(
            "Tone",
            value=business.get("tone") or "friendly, polite, sales-focused"
        )

        bot_enabled = st.toggle(
            "Bot enabled",
            value=bool(business.get("bot_enabled", True))
        )

    with right:
        st.subheader("Instagram Connection")

        st.text_input(
            "Instagram Business ID",
            value=business.get("instagram_business_id") or "",
            disabled=True
        )

        st.text_input(
            "Facebook Page ID",
            value=business.get("facebook_page_id") or "",
            disabled=True
        )

        st.write("Access token status:")

        if business.get("access_token") or business.get("page_access_token"):
            st.success("Connected ✅")
        else:
            st.error("Not connected ❌")

        if is_admin:
            st.link_button(
                "Reconnect Instagram",
                f"{BACKEND_URL}/connect-instagram"
            )

            st.link_button(
                "Connect Facebook Page",
                f"{BACKEND_URL}/connect-facebook"
            )

    st.divider()

    st.subheader("Business Knowledge")

    products = st.text_area(
        "Products / Services",
        value=business.get("products") or "",
        height=120
    )

    prices = st.text_area(
        "Prices",
        value=business.get("prices") or "",
        height=100
    )

    delivery_info = st.text_area(
        "Delivery info",
        value=business.get("delivery_info") or "",
        height=100
    )

    working_hours = st.text_area(
        "Working hours",
        value=business.get("working_hours") or "",
        height=80
    )

    faq = st.text_area(
        "FAQ",
        value=business.get("faq") or "",
        height=150
    )

    catalog_link = st.text_input(
        "Catalog link",
        value=business.get("catalog_link") or ""
    )

    sales_phone = st.text_input(
        "Sales phone",
        value=business.get("sales_phone") or ""
    )

    st.divider()

    st.subheader("Telegram Links")

    telegram_single = st.text_input(
        "Single product Telegram link",
        value=business.get("telegram_single") or ""
    )

    telegram_package = st.text_input(
        "Package Telegram link",
        value=business.get("telegram_package") or ""
    )

    telegram_bag = st.text_input(
        "Bag / Meshok Telegram link",
        value=business.get("telegram_bag") or ""
    )

    st.divider()

    st.subheader("Main Knowledge Prompt")

    knowledge = st.text_area(
        "General business knowledge",
        value=business.get("knowledge") or "",
        height=280
    )

    if st.button("💾 Save Business", type="primary"):
        if not business_name.strip():
            st.error("Business name is required.")
        else:
            update_data = {
                "business_name": business_name.strip(),
                "business_type": business_type.strip(),
                "language": language,
                "tone": tone.strip(),
                "bot_enabled": bot_enabled,
                "products": products.strip(),
                "prices": prices.strip(),
                "delivery_info": delivery_info.strip(),
                "working_hours": working_hours.strip(),
                "faq": faq.strip(),
                "catalog_link": catalog_link.strip(),
                "sales_phone": sales_phone.strip(),
                "telegram_single": telegram_single.strip(),
                "telegram_package": telegram_package.strip(),
                "telegram_bag": telegram_bag.strip(),
                "knowledge": knowledge.strip(),
            }

            update_business(business["id"], update_data)
            st.success("Business updated successfully.")
            st.rerun()


if is_admin:
    with tabs[1]:
        st.subheader("➕ Add Business Profile")

        new_business_name = st.text_input("Business name", key="new_business_name")
        new_instagram_business_id = st.text_input("Instagram Business ID", key="new_ig_id")
        new_facebook_page_id = st.text_input("Facebook Page ID", key="new_page_id")
        new_business_type = st.text_input("Business type", key="new_type")
        new_language = st.selectbox("Default language", ["uz", "ru", "en"], key="new_language")
        new_tone = st.text_input(
            "Tone",
            value="friendly, polite, sales-focused",
            key="new_tone"
        )

        if st.button("Create Business Profile", type="primary"):
            if not new_business_name.strip():
                st.error("Business name is required.")
            elif not new_instagram_business_id.strip():
                st.error("Instagram Business ID is required.")
            else:
                data = {
                    "business_name": new_business_name.strip(),
                    "instagram_business_id": new_instagram_business_id.strip(),
                    "facebook_page_id": new_facebook_page_id.strip(),
                    "business_type": new_business_type.strip(),
                    "language": new_language,
                    "tone": new_tone.strip(),
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
                }

                create_business(data)
                st.success("Business profile created.")
                st.rerun()

    with tabs[2]:
        st.subheader("👤 Create Dashboard User")

        new_user_email = st.text_input("New user email")
        new_user_password = st.text_input("Temporary password", type="password")

        if st.button("Create User", type="primary"):
            if not new_user_email.strip():
                st.error("Email is required.")
            elif not new_user_password.strip():
                st.error("Password is required.")
            else:
                try:
                    create_dashboard_user(new_user_email, new_user_password)
                    st.success("User created successfully.")
                except Exception as e:
                    st.error(f"Could not create user: {e}")

        st.divider()

        st.subheader("Existing Dashboard Users")

        users = get_all_dashboard_users()

        if users:
            st.dataframe(users, use_container_width=True)
        else:
            st.info("No dashboard users found.")

    with tabs[3]:
        st.subheader("🔗 Assign Business to User")

        all_businesses = get_all_businesses()

        assign_email = st.text_input("User email to assign")

        if all_businesses:
            business_map = {
                f"{b.get('business_name', 'Unnamed')} — {b.get('instagram_business_id', 'No IG ID')}": b["id"]
                for b in all_businesses
            }

            selected_label = st.selectbox(
                "Business",
                list(business_map.keys())
            )

            role = st.selectbox("Role", ["owner", "editor"])

            if st.button("Assign Business", type="primary"):
                if not assign_email.strip():
                    st.error("User email is required.")
                else:
                    assign_business_to_user(
                        assign_email,
                        business_map[selected_label],
                        role
                    )
                    st.success("Business assigned successfully.")
                    st.rerun()
        else:
            st.warning("No businesses found.")

        st.divider()

        st.subheader("Current Assignments")

        assignments = get_business_assignments()

        if assignments:
            st.dataframe(assignments, use_container_width=True)
        else:
            st.info("No assignments found.")
