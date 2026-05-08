import os
import hashlib
import hmac
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# Page configuration must be the first Streamlit command
st.set_page_config(
    page_title="Instagram Bot Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------- Custom CSS for enhanced UI ----------
st.markdown("""
<style>
    /* Main container styling */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }
    
    /* Card styling for various containers */
    .custom-card {
        background-color: #ffffff;
        border-radius: 16px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        border: 1px solid #eef2f6;
    }
    
    /* Header styling */
    .dashboard-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem 2rem;
        border-radius: 20px;
        color: white;
        margin-bottom: 2rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    
    /* Login card */
    .login-card {
        background-color: white;
        border-radius: 24px;
        padding: 2rem;
        box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        max-width: 450px;
        margin: 3rem auto;
        text-align: center;
    }
    
    /* Section titles */
    .section-title {
        font-size: 1.4rem;
        font-weight: 600;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 3px solid #667eea;
        display: inline-block;
    }
    
    /* Metric cards */
    .metric-card {
        background: #f8f9fc;
        border-radius: 16px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #e9ecef;
    }
    
    /* Button improvements */
    .stButton button {
        border-radius: 40px;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    
    /* Tabs styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #f8f9fa;
        border-radius: 40px;
        padding: 6px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 40px;
        padding: 6px 20px;
        background-color: transparent;
    }
    .stTabs [aria-selected="true"] {
        background-color: #667eea;
        color: white;
    }
    
    /* Dataframe styling */
    .dataframe-container {
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid #eef2f6;
    }
    
    /* Success/error messages */
    .stAlert {
        border-radius: 12px;
        border-left-width: 5px;
    }
</style>
""", unsafe_allow_html=True)

# ---------- Helper functions (unchanged) ----------
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
    st.error("Missing required environment variables. Please check your configuration.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()

def hash_password(password: str) -> str:
    return hashlib.sha256((password + DASHBOARD_SECRET).encode()).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    return hmac.compare_digest(hash_password(password), password_hash)

def login_user(email: str, password: str):
    email = normalize_email(email)
    result = supabase.table("dashboard_users").select("*").eq("email", email).eq("is_active", True).limit(1).execute()
    users = result.data or []
    if not users:
        return None
    user = users[0]
    if not verify_password(password, user.get("password_hash", "")):
        return None
    return user

def get_user_businesses(user_email: str):
    result = supabase.table("business_users").select("business_id, role").eq("user_email", normalize_email(user_email)).execute()
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

def logout():
    st.session_state.clear()
    st.rerun()

# ---------- Login Screen ----------
if "user" not in st.session_state:
    st.markdown("""
    <div class="login-card">
        <h1>🤖 Instagram Bot Dashboard</h1>
        <p style="color: #666; margin-bottom: 2rem;">Sign in to manage your businesses</p>
    </div>
    """, unsafe_allow_html=True)
    
    with st.container():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            email = st.text_input("Email", placeholder="your@email.com", label_visibility="collapsed")
            password = st.text_input("Password", type="password", placeholder="Password", label_visibility="collapsed")
            if st.button("Login", type="primary", use_container_width=True):
                user = login_user(email, password)
                if user:
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error("Invalid email or password.")
    st.stop()

# ---------- Main Dashboard ----------
user = st.session_state["user"]
user_email = normalize_email(user.get("email"))
is_admin = user_email == normalize_email(ADMIN_EMAIL)

# Header with user info and logout
st.markdown(f"""
<div class="dashboard-header">
    <div>
        <span style="font-size: 1.6rem;">🤖</span>
        <span style="font-weight: 600; margin-left: 0.5rem;">Instagram Bot Dashboard</span>
        <span style="font-size: 0.85rem; background: rgba(255,255,255,0.2); padding: 0.2rem 0.8rem; border-radius: 40px; margin-left: 1rem;">
            {user_email}
        </span>
        {"⭐ Admin" if is_admin else "👤 Business Owner"}
    </div>
</div>
""", unsafe_allow_html=True)

if st.button("🚪 Logout", key="logout_btn", help="Sign out from dashboard"):
    logout()

# Check for success message from Instagram connection
if st.query_params.get("connected") == "success":
    st.success("✅ Instagram connected successfully!", icon="🔗")
    st.query_params.clear()

# ---------- Tab Layout ----------
if is_admin:
    tabs = st.tabs(["📋 Edit Businesses", "➕ Add Business", "👤 Users", "🔗 Assign Business"])
else:
    tabs = st.tabs(["📋 Edit Business"])

# ---------- Tab 0: Edit Business(es) ----------
with tabs[0]:
    businesses = get_all_businesses() if is_admin else get_user_businesses(user_email)
    
    if not businesses:
        st.warning("No business assigned to your account. Please contact an administrator.")
        st.stop()
    
    # Business selection
    if len(businesses) == 1:
        business = businesses[0]
        st.info(f"✏️ Editing: **{business.get('business_name', 'Unnamed')}**")
    else:
        business_options = {
            f"{b.get('business_name', 'Unnamed')} — {b.get('instagram_business_id', 'No IG ID')}": b
            for b in businesses
        }
        selected_label = st.selectbox("Select business to edit", list(business_options.keys()))
        business = business_options[selected_label]
    
    # Edit form with expanders
    with st.form(key=f"edit_business_{business['id']}"):
        # Business Info expander
        with st.expander("🏢 Business Info", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                business_name = st.text_input("Business name", value=business.get("business_name") or "")
                business_type = st.text_input("Business type", value=business.get("business_type") or "")
            with col2:
                current_language = business.get("language") or "uz"
                if current_language not in ["uz", "ru", "en"]:
                    current_language = "uz"
                language = st.selectbox("Default language", ["uz", "ru", "en"], index=["uz", "ru", "en"].index(current_language))
                tone = st.text_input("Tone", value=business.get("tone") or "friendly, polite, sales-focused")
            bot_enabled = st.toggle("🤖 Bot enabled", value=bool(business.get("bot_enabled", True)))
        
        # Instagram Connection expander (read-only for non-admin)
        with st.expander("🔌 Instagram Connection"):
            col1, col2 = st.columns(2)
            with col1:
                st.text_input("Instagram Business ID", value=business.get("instagram_business_id") or "", disabled=True)
                st.text_input("Facebook Page ID", value=business.get("facebook_page_id") or "", disabled=True)
            with col2:
                st.text_input("OAuth provider", value=business.get("oauth_provider") or "", disabled=True)
                token_status = "Connected ✅" if (business.get("access_token") or business.get("page_access_token")) else "Not connected ❌"
                st.text_input("Access token status", value=token_status, disabled=True)
            
            if is_admin:
                col_reconnect1, col_reconnect2 = st.columns(2)
                with col_reconnect1:
                    st.link_button("Reconnect Instagram", f"{BACKEND_URL}/connect-instagram", use_container_width=True)
                with col_reconnect2:
                    st.link_button("Connect Facebook Page", f"{BACKEND_URL}/connect-facebook", use_container_width=True)
        
        # Business Knowledge expander
        with st.expander("📦 Business Knowledge"):
            products = st.text_area("Products / Services", value=business.get("products") or "", height=100, help="List your main products or services")
            prices = st.text_area("Prices", value=business.get("prices") or "", height=80, help="Pricing information for your products")
            delivery_info = st.text_area("Delivery info", value=business.get("delivery_info") or "", height=80)
            working_hours = st.text_area("Working hours", value=business.get("working_hours") or "", height=80)
            faq = st.text_area("FAQ", value=business.get("faq") or "", height=120, help="Frequently asked questions and answers")
            catalog_link = st.text_input("Catalog link", value=business.get("catalog_link") or "", help="Link to your full catalog or website")
            sales_phone = st.text_input("Sales phone", value=business.get("sales_phone") or "")
        
        # Telegram Links expander
        with st.expander("📱 Telegram Links"):
            col_tg1, col_tg2 = st.columns(2)
            with col_tg1:
                telegram_single = st.text_input("Single product Telegram link", value=business.get("telegram_single") or "")
                telegram_package = st.text_input("Package Telegram link", value=business.get("telegram_package") or "")
            with col_tg2:
                telegram_bag = st.text_input("Bag / Meshok Telegram link", value=business.get("telegram_bag") or "")
        
        # Main Knowledge Prompt expander
        with st.expander("🧠 Main Knowledge Prompt (AI Instructions)"):
            knowledge = st.text_area("General business knowledge", value=business.get("knowledge") or "", height=280, 
                                    help="This prompt will be used by the AI to generate responses. Include your brand voice, key selling points, etc.")
        
        # Save button
        col_save1, col_save2, col_save3 = st.columns([1, 2, 1])
        with col_save2:
            submitted = st.form_submit_button("💾 Save Business", type="primary", use_container_width=True)
        
        if submitted:
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
                try:
                    update_business(business["id"], update_data)
                    st.success("✅ Business updated successfully!", icon="🎉")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to update business: {e}")

# ---------- Admin Tabs (only visible for admin) ----------
if is_admin:
    # Tab 1: Add Business
    with tabs[1]:
        st.markdown('<p class="section-title">➕ Add New Business Profile</p>', unsafe_allow_html=True)
        with st.form("add_business_form"):
            col1, col2 = st.columns(2)
            with col1:
                new_business_name = st.text_input("Business name *", key="new_name")
                new_instagram_business_id = st.text_input("Instagram Business ID *", key="new_ig_id")
                new_facebook_page_id = st.text_input("Facebook Page ID", key="new_fb_id")
            with col2:
                new_business_type = st.text_input("Business type", key="new_type")
                new_language = st.selectbox("Default language", ["uz", "ru", "en"], key="new_lang")
                new_tone = st.text_input("Tone", value="friendly, polite, sales-focused", key="new_tone")
            
            submitted = st.form_submit_button("Create Business Profile", type="primary", use_container_width=True)
            if submitted:
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
                    try:
                        create_business(data)
                        st.success("✅ Business profile created successfully!", icon="🎉")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not create business: {e}")
    
    # Tab 2: Users management
    with tabs[2]:
        st.markdown('<p class="section-title">👤 Manage Dashboard Users</p>', unsafe_allow_html=True)
        
        # Create/Update user
        with st.expander("Create or Reset User Password", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                new_user_email = st.text_input("User email", key="user_email_input")
            with col2:
                new_user_password = st.text_input("Temporary/New password", type="password", key="user_pass_input")
            if st.button("Create / Reset Password", type="primary"):
                if not new_user_email.strip():
                    st.error("Email is required.")
                elif not new_user_password.strip():
                    st.error("Password is required.")
                else:
                    try:
                        create_or_update_dashboard_user(new_user_email, new_user_password)
                        st.success("✅ User created or password reset successfully.")
                    except Exception as e:
                        st.error(f"Could not save user: {e}")
        
        # Activate/Deactivate user
        with st.expander("Activate / Deactivate User"):
            status_email = st.text_input("User email for status change", key="status_email")
            col_act, col_deact = st.columns(2)
            with col_act:
                if st.button("✅ Activate User", use_container_width=True):
                    if status_email.strip():
                        set_user_active_status(status_email, True)
                        st.success("User activated.")
                        st.rerun()
                    else:
                        st.error("Email is required.")
            with col_deact:
                if st.button("⛔ Deactivate User", use_container_width=True):
                    if status_email.strip():
                        set_user_active_status(status_email, False)
                        st.success("User deactivated.")
                        st.rerun()
                    else:
                        st.error("Email is required.")
        
        # List existing users
        st.markdown("### Existing Dashboard Users")
        users_list = get_all_dashboard_users()
        if users_list:
            st.dataframe(users_list, use_container_width=True, column_config={
                "id": "User ID",
                "email": "Email",
                "is_active": "Active",
                "created_at": "Created At"
            })
        else:
            st.info("No dashboard users found.")
    
    # Tab 3: Assign Business to User
    with tabs[3]:
        st.markdown('<p class="section-title">🔗 Assign Business to User</p>', unsafe_allow_html=True)
        
        all_businesses = get_all_businesses()
        if not all_businesses:
            st.warning("No businesses found. Please create a business first.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                assign_email = st.text_input("User email to assign", key="assign_email")
                business_map = {
                    f"{b.get('business_name', 'Unnamed')} — {b.get('instagram_business_id', 'No IG ID')}": b["id"]
                    for b in all_businesses
                }
                selected_label = st.selectbox("Select Business", list(business_map.keys()), key="assign_business")
                role = st.selectbox("Role", ["owner", "editor"], key="assign_role")
            with col2:
                if st.button("➕ Assign Business", type="primary", use_container_width=True):
                    if not assign_email.strip():
                        st.error("User email is required.")
                    else:
                        assign_business_to_user(assign_email, business_map[selected_label], role)
                        st.success("✅ Business assigned successfully.")
                        st.rerun()
                if st.button("❌ Remove Assignment", use_container_width=True):
                    if not assign_email.strip():
                        st.error("User email is required.")
                    else:
                        remove_business_assignment(assign_email, business_map[selected_label])
                        st.success("Assignment removed.")
                        st.rerun()
        
        st.divider()
        st.markdown("### Current Business Assignments")
        assignments = get_business_assignments()
        if assignments:
            st.dataframe(assignments, use_container_width=True, column_config={
                "user_email": "User Email",
                "business_id": "Business ID",
                "role": "Role",
                "created_at": "Assigned On"
            })
        else:
            st.info("No assignments found.")
