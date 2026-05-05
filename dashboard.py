import os
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

st.set_page_config(
    page_title="Instagram Bot Dashboard",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 Instagram Bot Business Dashboard")

st.info("Phase 4 dashboard: edit business info without changing code.")


def get_businesses():
    result = (
        supabase.table("businesses")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def update_business(business_id, data):
    return (
        supabase.table("businesses")
        .update(data)
        .eq("id", business_id)
        .execute()
    )


businesses = get_businesses()

if not businesses:
    st.warning("No businesses found in Supabase.")
    st.stop()

business_names = {
    f"{b.get('business_name')} — {b.get('instagram_business_id')}": b
    for b in businesses
}

selected_label = st.selectbox(
    "Select business",
    list(business_names.keys())
)

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

    language = st.selectbox(
        "Default language",
        ["uz", "ru", "en"],
        index=["uz", "ru", "en"].index(business.get("language", "uz"))
        if business.get("language", "uz") in ["uz", "ru", "en"]
        else 0
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

    st.caption("Token is sensitive. Later this should be handled by OAuth, not manual input.")

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
    height=250
)

if st.button("💾 Save Business", type="primary"):
    update_data = {
        "business_name": business_name,
        "business_type": business_type,
        "language": language,
        "tone": tone,
        "bot_enabled": bot_enabled,
        "instagram_business_id": instagram_business_id,
        "access_token": access_token,
        "products": products,
        "prices": prices,
        "delivery_info": delivery_info,
        "working_hours": working_hours,
        "faq": faq,
        "catalog_link": catalog_link,
        "sales_phone": sales_phone,
        "telegram_single": telegram_single,
        "telegram_package": telegram_package,
        "telegram_bag": telegram_bag,
        "knowledge": knowledge
    }

    update_business(business["id"], update_data)
    st.success("Business updated successfully.")
    st.rerun()
