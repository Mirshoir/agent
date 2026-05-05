import os
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Instagram Bot Dashboard",
    page_icon="🤖",
    layout="wide"
)

# ---------------- CONFIG ----------------

def get_secret(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = get_secret("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL:
    st.error("Missing SUPABASE_URL. Add it in Streamlit Secrets.")
    st.stop()

if not SUPABASE_SERVICE_KEY:
    st.error("Missing SUPABASE_SERVICE_KEY. Add it in Streamlit Secrets.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------------- DATABASE ----------------

def get_businesses():
    try:
        result = (
            supabase.table("businesses")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        st.error(f"Failed to load businesses: {e}")
        return []


def find_business_by_instagram_id(instagram_business_id):
    try:
        result = (
            supabase.table("businesses")
            .select("id, business_name, instagram_business_id")
            .eq("instagram_business_id", instagram_business_id)
            .execute()
        )
        return result.data or []
    except Exception as e:
        st.error(f"Failed to check duplicate business: {e}")
        return []


def create_business(data):
    try:
        existing = find_business_by_instagram_id(data["instagram_business_id"])

        if existing:
            st.warning("Business with this Instagram Business ID already exists.")
            return None

        return supabase.table("businesses").insert(data).execute()

    except Exception as e:
        st.error(f"Supabase insert error: {e}")
        return None


def update_business(business_id, data):
    try:
        return (
            supabase.table("businesses")
            .update(data)
            .eq("id", business_id)
            .execute()
        )
    except Exception as e:
        st.error(f"Supabase update error: {e}")
        return None


# ---------------- UI ----------------

st.title("🤖 Instagram Bot Business Dashboard")
st.info("Manage Instagram bot business data without editing code.")

businesses = get_businesses()

tab1, tab2 = st.tabs(["📋 Edit Business", "➕ Add Business"])


# ---------------- ADD BUSINESS ----------------

with tab2:
    st.subheader("Add New Business")

    new_business_name = st.text_input("Business name", key="new_business_name")
    new_instagram_business_id = st.text_input("Instagram Business ID", key="new_ig_id")
    new_access_token = st.text_area("Instagram Access Token", height=120, key="new_token")

    new_business_type = st.text_input("Business type", key="new_type")
    new_language = st.selectbox("Default language", ["uz", "ru", "en"], key="new_language")
    new_tone = st.text_input(
        "Tone",
        value="friendly, polite, sales-focused",
        key="new_tone"
    )

    if st.button("➕ Create Business", type="primary"):
        if not new_business_name.strip():
            st.error("Business name is required.")
        elif not new_instagram_business_id.strip():
            st.error("Instagram Business ID is required.")
        elif not new_access_token.strip():
            st.error("Instagram Access Token is required.")
        else:
            result = create_business({
                "business_name": new_business_name.strip(),
                "instagram_business_id": new_instagram_business_id.strip(),
                "access_token": new_access_token.strip(),
                "business_type": new_business_type.strip(),
                "language": new_language,
                "tone": new_tone.strip(),
                "bot_enabled": True,

                # Empty defaults to avoid NOT NULL insert errors
                "knowledge": "",
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
            })

            if result:
                st.success("Business created successfully.")
                st.rerun()


# ---------------- EDIT BUSINESS ----------------

with tab1:
    if not businesses:
        st.warning("No businesses found. Add your first business in the Add Business tab.")
        st.stop()

    business_names = {
        f"{b.get('business_name', 'Unnamed')} — {b.get('instagram_business_id', 'No ID')}": b
        for b in businesses
    }

    selected_label = st.selectbox("Select business", list(business_names.keys()))
    business = business_names[selected_label]

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
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

    with col2:
        st.subheader("Instagram Connection")

        instagram_business_id = st.text_input(
            "Instagram Business ID",
            value=business.get("instagram_business_id") or ""
        )

        access_token = st.text_area(
            "Instagram Access Token",
            value=business.get("access_token") or "",
            height=120
        )

        st.caption("Access token is sensitive. Do not share it publicly.")

    st.divider()

    st.subheader("Business Knowledge")

    products = st.text_area(
        "Products / Services",
        value=business.get("products") or business.get("products_services") or "",
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
        height=250
    )

    if st.button("💾 Save Business", type="primary"):
        if not business_name.strip():
            st.error("Business name is required.")
        elif not instagram_business_id.strip():
            st.error("Instagram Business ID is required.")
        elif not access_token.strip():
            st.error("Instagram Access Token is required.")
        else:
            update_data = {
                "business_name": business_name.strip(),
                "business_type": business_type.strip(),
                "language": language,
                "tone": tone.strip(),
                "bot_enabled": bot_enabled,
                "instagram_business_id": instagram_business_id.strip(),
                "access_token": access_token.strip(),
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

            result = update_business(business["id"], update_data)

            if result:
                st.success("Business updated successfully.")
                st.rerun()
