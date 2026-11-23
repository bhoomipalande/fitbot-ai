from datetime import datetime, timedelta
import hashlib
import os
import secrets
import time
import urllib.parse
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client, Client

from agent_graph import build_fitbot_graph
from gym_data import GYM_DATA
from rag_engine import DEFAULT_KNOWLEDGE_DOCS, embed_texts
from styles import load_css
from ui import show_header, show_categories


# =========================================================
# PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="FitBot AI — Intelligent Gym Management & Concierge",
    page_icon="🏋️",
    layout="centered"
)

if (
    st.session_state.get("selected_category") is None
    and not st.session_state.get("chat_open", False)
):
    load_css(background="home")
else:
    load_css(background="general")


# =========================================================
# SECRETS & CLIENTS
# =========================================================

load_dotenv()


def get_secret(key_name: str):
    val = os.getenv(key_name)
    if not val:
        try:
            val = st.secrets[key_name]
        except Exception:
            val = None
    return val


api_key = get_secret("GEMINI_API_KEY")
supabase_url = get_secret("SUPABASE_URL")
supabase_key = get_secret("SUPABASE_KEY")

client = genai.Client(api_key=api_key)

supabase: Client | None = None
if supabase_url and supabase_key:
    try:
        supabase = create_client(supabase_url, supabase_key)
    except Exception:
        supabase = None

MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
]

BRANCH_MONTHLY_BUDGET_INR = {
    "FitZone Pune": 30000,
    "FitZone Mumbai": 45000,
}

WEEKLY_ROUTINE_PREVIEW = {
    "Beginner": [
        "Day 1 (Mon): Full Body Foundations — Squats, Push-ups, Seated Row, Plank (40 mins)",
        "Day 2 (Tue): Brisk Cardio & Core Mobility — Treadmill Walk + Deadbugs (30 mins)",
        "Day 3 (Wed): Upper Body & Posture — Lat Pulldown, Dumbbell Press, Face Pulls (40 mins)",
        "Day 4 (Thu): Active Recovery & Stretching (25 mins)",
        "Day 5 (Fri): Lower Body & Glutes — Leg Press, Lunges, Calf Raises (40 mins)",
        "Day 6 (Sat): Light Zumba / Cycling + Core (35 mins)",
    ],
    "Intermediate": [
        "Day 1 (Mon): Push (Chest, Shoulders, Triceps) — Bench Press, OHP, Dips (55 mins)",
        "Day 2 (Tue): Pull (Back, Biceps, Rear Delts) — Pull-ups, Barbell Row, Curls (55 mins)",
        "Day 3 (Wed): Legs & Core — Barbell Squats, RDL, Hanging Leg Raises (60 mins)",
        "Day 4 (Thu): HIIT Conditioning & Mobility (40 mins)",
        "Day 5 (Fri): Upper Hypertrophy — Incline DB Press, Cable Row, Lateral Raises (55 mins)",
        "Day 6 (Sat): Lower Strength & Sled Push (50 mins)",
    ],
    "Advanced": [
        "Day 1 (Mon): Heavy Chest & Triceps (65 mins)",
        "Day 2 (Tue): Heavy Back & Posterior Chain (65 mins)",
        "Day 3 (Wed): Quad-Focused Legs & Core (70 mins)",
        "Day 4 (Thu): Shoulders, Arms & Conditioning (60 mins)",
        "Day 5 (Fri): Hamstring & Glute Power Day (65 mins)",
        "Day 6 (Sat): Athletic Metcon & Mobility (50 mins)",
    ],
    "Pro": [
        "Day 1 (Mon): Maximal Strength Upper + Speed Work (75 mins)",
        "Day 2 (Tue): Maximal Strength Lower + Plyometrics (75 mins)",
        "Day 3 (Wed): Zone 2 Endurance + Core Stability (50 mins)",
        "Day 4 (Thu): Push Hypertrophy Volume (70 mins)",
        "Day 5 (Fri): Pull Hypertrophy Volume (70 mins)",
        "Day 6 (Sat): Legs Volume + Conditioning Finisher (75 mins)",
    ],
}


# =========================================================
# SECURITY & PASSWORD HASHING HELPERS
# =========================================================

SALT_PREFIX = "fitbot_salt_v1"


def hash_password(raw_password: str) -> str:
    digest = hashlib.sha256(f"{SALT_PREFIX}:{raw_password.strip()}".encode("utf-8")).hexdigest()
    return f"{SALT_PREFIX}${digest}"


def verify_password(raw_password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    return secrets.compare_digest(hash_password(raw_password), stored_hash)


def generate_secure_member_password(gym_name: str) -> str:
    city_code = "MUM" if "mumbai" in gym_name.lower() else "PUN"
    rand_digits = secrets.randbelow(9000) + 1000
    rand_letters = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(2))
    return f"FIT-{rand_digits}-{city_code}{rand_letters}"


# =========================================================
# SESSION STATE & VECTOR INDEX INITIALIZATION
# =========================================================

if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

if "failed_attempts" not in st.session_state:
    st.session_state["failed_attempts"] = 0

if "lockout_until" not in st.session_state:
    st.session_state["lockout_until"] = 0.0

if "selected_category" not in st.session_state:
    st.session_state["selected_category"] = None

if "selected_activity" not in st.session_state:
    st.session_state["selected_activity"] = None

if "workout_request" not in st.session_state:
    st.session_state["workout_request"] = None

if "latest_generated_plan" not in st.session_state:
    st.session_state["latest_generated_plan"] = None

if "messages" not in st.session_state:
    st.session_state["messages"] = []

if "current_session_id" not in st.session_state:
    st.session_state["current_session_id"] = None

if "latest_ics" not in st.session_state:
    st.session_state["latest_ics"] = None

if "chat_open" not in st.session_state:
    st.session_state["chat_open"] = False

if "active_gym" not in st.session_state:
    st.session_state["active_gym"] = {
        "name": "FitZone Pune",
        "city": "Pune",
        "timings": "Mon-Sat: 6:00 AM - 11:00 PM",
        "monthly_fee": "₹1,499/month",
    }

if "rag_docs" not in st.session_state:
    st.session_state["rag_docs"] = list(DEFAULT_KNOWLEDGE_DOCS)

if "rag_embeddings" not in st.session_state:
    if api_key:
        texts = [f"{d['title']}: {d['content']}" for d in st.session_state["rag_docs"]]
        st.session_state["rag_embeddings"] = embed_texts(client, texts)
    else:
        st.session_state["rag_embeddings"] = []


# =========================================================
# SUPABASE HELPERS & DEFAULT STAFF SEEDING
# =========================================================

def get_member_record(member_id: str) -> dict | None:
    if not supabase:
        return None
    try:
        res = (
            supabase.table("members")
            .select("*")
            .eq("member_id", member_id.strip().upper())
            .execute()
        )
        if res.data:
            return res.data[0]
    except Exception as e:
        st.error(f"Database lookup error: {e}")
    return None


def ensure_default_staff():
    if not supabase:
        return
    defaults = [
        {
            "member_id": "OWN-BHOOMI",
            "full_name": "Bhoomi Palande",
            "email": "bhoomi@fitbot.ai",
            "phone_last4": "0000",
            "password_hash": hash_password("OWNER123"),
            "is_activated": True,
            "role": "owner",
            "gym_name": "FitZone Pune",
            "plan_type": "All-Access Owner",
        },
        {
            "member_id": "REC-PUN-01",
            "full_name": "Pune Reception Desk",
            "email": "reception.pune@fitbot.ai",
            "phone_last4": "1111",
            "password_hash": hash_password("RECEP123"),
            "is_activated": True,
            "role": "reception",
            "gym_name": "FitZone Pune",
            "plan_type": "Front Desk PC",
        },
        {
            "member_id": "REC-MUM-01",
            "full_name": "Mumbai Reception Desk",
            "email": "reception.mumbai@fitbot.ai",
            "phone_last4": "2222",
            "password_hash": hash_password("RECEP123"),
            "is_activated": True,
            "role": "reception",
            "gym_name": "FitZone Mumbai",
            "plan_type": "Front Desk PC",
        },
        {
            "member_id": "TRN-RAHUL",
            "full_name": "Rahul Sharma",
            "email": "rahul@fitbot.ai",
            "phone_last4": "0001",
            "password_hash": hash_password("TRAINER123"),
            "is_activated": True,
            "role": "trainer",
            "gym_name": "FitZone Pune",
            "plan_type": "Senior PT Coach",
        },
        {
            "member_id": "TRN-PRIYA",
            "full_name": "Priya Mehta",
            "email": "priya@fitbot.ai",
            "phone_last4": "0002",
            "password_hash": hash_password("TRAINER123"),
            "is_activated": True,
            "role": "trainer",
            "gym_name": "FitZone Mumbai",
            "plan_type": "PT & Functional Coach",
        },
    ]
    for staff in defaults:
        try:
            supabase.table("members").upsert(staff, on_conflict="member_id").execute()
        except Exception:
            pass


if "staff_seeded" not in st.session_state:
    ensure_default_staff()
    st.session_state["staff_seeded"] = True


def fetch_gym_by_name(gym_name: str) -> dict:
    fallback = {
        "name": gym_name,
        "city": "Mumbai" if "mumbai" in gym_name.lower() else "Pune",
        "timings": "Mon-Sat: 6:00 AM - 11:00 PM",
        "monthly_fee": "₹1,499/month",
    }
    if not supabase:
        return fallback
    try:
        res = supabase.table("gyms").select("*").eq("name", gym_name).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return fallback


def fetch_gym_bookings(gym_name: str | None = None, member_filter: str | None = None, trainer_filter: str | None = None) -> list[dict]:
    if not supabase:
        return []
    try:
        query = supabase.table("bookings").select("*")
        if gym_name:
            query = query.eq("gym_name", gym_name)
        if member_filter:
            query = query.ilike("member_name", f"%{member_filter}%")
        if trainer_filter:
            query = query.ilike("trainer_name", f"%{trainer_filter}%")
        res = query.order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def fetch_gym_reminders(gym_name: str, member_filter: str | None = None) -> list[dict]:
    if not supabase:
        return []
    try:
        query = supabase.table("gym_reminders").select("*").eq("gym_name", gym_name)
        if member_filter:
            query = query.ilike("member_name", f"%{member_filter}%")
        res = query.order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def fetch_branch_members(gym_name: str | None = None) -> list[dict]:
    if not supabase:
        return []
    try:
        q = supabase.table("members").select("member_id, full_name, email, phone_last4, role, gym_name, plan_type, is_activated")
        if gym_name:
            q = q.eq("gym_name", gym_name)
        res = q.order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def fetch_payments(gym_name: str | None = None) -> list[dict]:
    if not supabase:
        return []
    try:
        q = supabase.table("payments").select("*")
        if gym_name:
            q = q.eq("gym_name", gym_name)
        res = q.order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def fetch_expenses(gym_name: str | None = None) -> list[dict]:
    if not supabase:
        return []
    try:
        q = supabase.table("expenses").select("*")
        if gym_name:
            q = q.eq("gym_name", gym_name)
        res = q.order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def fetch_member_saved_plan(member_id: str) -> dict | None:
    if not supabase:
        return None
    try:
        res = supabase.table("member_plans").select("*").eq("member_id", member_id).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return None


def save_member_plan_record(member_id: str, gym_name: str, level: str, plan_text: str):
    if not supabase:
        return
    try:
        supabase.table("member_plans").upsert({
            "member_id": member_id,
            "gym_name": gym_name,
            "level": level,
            "plan_text": plan_text,
            "completed_days": 0,
            "missed_days": 0,
            "last_status": "Active — Ready for Day 1",
        }, on_conflict="member_id").execute()
    except Exception:
        pass


def create_chat_session(gym_name: str, first_msg: str, owner_tag: str) -> str | None:
    if not supabase:
        return None
    try:
        short_msg = first_msg[:28] + ("..." if len(first_msg) > 28 else "")
        title = f"[{owner_tag}] {short_msg}"
        res = supabase.table("chat_sessions").insert({
            "gym_name": gym_name,
            "title": title,
        }).execute()
        if res.data:
            return res.data[0]["id"]
    except Exception:
        pass
    return None


def save_chat_message(session_id: str | None, role: str, content: str, trace: dict | None = None):
    if not supabase or not session_id:
        return
    try:
        supabase.table("chat_messages").insert({
            "session_id": session_id,
            "role": role,
            "content": content,
            "trace": trace,
        }).execute()
    except Exception:
        pass


def fetch_chat_sessions(gym_name: str, owner_tag: str) -> list[dict]:
    if not supabase:
        return []
    try:
        res = (
            supabase.table("chat_sessions")
            .select("*")
            .eq("gym_name", gym_name)
            .ilike("title", f"[{owner_tag}]%")
            .order("created_at", desc=True)
            .limit(15)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def load_session_messages(session_id: str) -> list[dict]:
    if not supabase:
        return []
    try:
        res = (
            supabase.table("chat_messages")
            .select("role, content, trace")
            .eq("session_id", session_id)
            .order("id", desc=False)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


# =========================================================
# CALENDAR NOTIFICATION (.ICS) GENERATOR
# =========================================================

def build_gym_ics(gym_name: str, city: str, date_str: str, time_str: str, focus: str) -> tuple[str, str]:
    try:
        dt_start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        dt_start = datetime.now() + timedelta(days=1)
        dt_start = dt_start.replace(hour=7, minute=0, second=0, microsecond=0)

    dt_end = dt_start + timedelta(hours=1)
    fmt = "%Y%m%dT%H%M%S"

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//FitBot AI//Gym Reminder//EN
BEGIN:VEVENT
SUMMARY:🏋️ Gym Session: {focus} ({gym_name})
DTSTART:{dt_start.strftime(fmt)}
DTEND:{dt_end.strftime(fmt)}
LOCATION:{gym_name}, {city}
DESCRIPTION:Time to hit the gym! Scheduled via FitBot AI.
BEGIN:VALARM
TRIGGER:-PT30M
ACTION:DISPLAY
DESCRIPTION:Gym Workout starts in 30 minutes at {gym_name}!
END:VALARM
END:VEVENT
END:VCALENDAR"""

    gcal_params = urllib.parse.urlencode({
        "action": "TEMPLATE",
        "text": f"🏋️ Gym Session: {focus} ({gym_name})",
        "dates": f"{dt_start.strftime(fmt)}/{dt_end.strftime(fmt)}",
        "details": "Time to hit the gym! Scheduled via FitBot AI.",
        "location": f"{gym_name}, {city}",
    })
    gcal_url = f"https://calendar.google.com/calendar/render?{gcal_params}"
    return ics_content, gcal_url


# =========================================================
# AUTHENTICATION GATE (LOGIN + SELF-SERVICE ID ACTIVATION)
# =========================================================

if st.session_state["auth_user"] is None:
    show_header()

    now_ts = time.time()
    if now_ts < st.session_state["lockout_until"]:
        wait_sec = int(st.session_state["lockout_until"] - now_ts)
        st.error(f"🔒 Too many failed attempts. Please wait **{wait_sec} seconds** before trying again.")
        st.stop()

    login_tab, activate_tab = st.tabs(["🔑 Login", "🆕 ID Activation"])

    with login_tab:
        st.markdown("Enter your issued ID and password to access your branch.")
        with st.form("member_login_form"):
            in_id = st.text_input("Issued ID", placeholder="Enter your issued ID")
            in_pass = st.text_input("Password", type="password", placeholder="Enter your password")
            submit_login = st.form_submit_button("LOGIN →", use_container_width=True)

        if submit_login:
            record = get_member_record(in_id)
            if not record:
                st.session_state["failed_attempts"] += 1
                st.error("❌ Invalid ID. Please check the ID issued by your branch.")
            elif not record.get("is_activated"):
                st.warning(
                    "⚠️ This ID has not been activated yet. "
                    "Switch to the **🆕 ID Activation** tab to verify your details and generate your password."
                )
            elif not verify_password(in_pass, record.get("password_hash")):
                st.session_state["failed_attempts"] += 1
                if st.session_state["failed_attempts"] >= 5:
                    st.session_state["lockout_until"] = time.time() + 60
                    st.session_state["failed_attempts"] = 0
                st.error("❌ Incorrect password.")
            else:
                st.session_state["failed_attempts"] = 0
                st.session_state["auth_user"] = record
                st.session_state["active_gym"] = fetch_gym_by_name(record["gym_name"])
                st.session_state["messages"] = []
                st.session_state["current_session_id"] = None
                st.rerun()

    with activate_tab:
        st.markdown("Verify your registered details to generate your personal login password.")
        with st.form("activate_id_form"):
            act_id = st.text_input("Issued Member ID", placeholder="Enter your issued ID")
            act_name = st.text_input("Full Name (as registered)", placeholder="Enter your full name")
            act_email = st.text_input("Email ID", placeholder="Enter your registered email")
            act_phone4 = st.text_input("Last 4 Digits of Registered Phone Number", max_chars=4, placeholder="e.g., 3210")
            submit_activate = st.form_submit_button("ACTIVATE & GENERATE PASSWORD →", use_container_width=True)

        if submit_activate:
            record = get_member_record(act_id)
            if not record:
                st.error("❌ ID not found in our records.")
            elif record.get("is_activated"):
                st.error(
                    "🔒 This ID has already been activated. "
                    "Please log in using your password or contact your branch desk for assistance."
                )
            else:
                name_ok = act_name.strip().lower() == record["full_name"].strip().lower()
                email_ok = act_email.strip().lower() == record["email"].strip().lower()
                phone_ok = act_phone4.strip() == str(record["phone_last4"]).strip()

                if name_ok and email_ok and phone_ok:
                    new_plain_pass = generate_secure_member_password(record["gym_name"])
                    new_hash = hash_password(new_plain_pass)
                    try:
                        supabase.table("members").update({
                            "password_hash": new_hash,
                            "is_activated": True,
                        }).eq("member_id", record["member_id"]).execute()

                        st.success("✅ **Identity Verified! Save your credentials below:**")
                        st.info(
                            f"- **Issued ID:** `{record['member_id']}`\n"
                            f"- **Generated Password:** `{new_plain_pass}`\n"
                            f"- **Branch:** {record['gym_name']}\n\n"
                            f"Switch to the **🔑 Login** tab to enter."
                        )
                    except Exception as e:
                        st.error(f"Database error during activation: {e}")
                else:
                    st.session_state["failed_attempts"] += 1
                    st.error("❌ Verification details do not match our records. Please check and try again.")

    st.stop()


# =========================================================
# AUTHENTICATED PORTAL (OWNER, RECEPTION, TRAINER & MEMBER)
# =========================================================

current_user = st.session_state["auth_user"]
user_role = current_user.get("role", "member")
is_owner = user_role == "owner"
is_reception = user_role == "reception"
is_trainer = user_role == "trainer"
is_staff = is_owner or is_reception

# =========================================================
# SIDEBAR — ROLE-BASED BRANCH CONTROL & SAVED CHATS
# =========================================================

with st.sidebar:
    if is_owner:
        role_badge = "👑 OWNER ADMIN"
    elif is_reception:
        role_badge = "🛎️ RECEPTION PC"
    elif is_trainer:
        role_badge = "💪 PT COACH"
    else:
        role_badge = "🏋️ MEMBER"

    st.markdown(f"### {role_badge}")
    st.caption(f"**{current_user['full_name']}** • ID: `{current_user['member_id']}`")

    if st.button("🚪 Log Out", use_container_width=True):
        st.session_state["auth_user"] = None
        st.session_state["messages"] = []
        st.session_state["current_session_id"] = None
        st.session_state["selected_category"] = None
        st.session_state["chat_open"] = False
        st.rerun()

    st.divider()

    if is_owner:
        st.markdown("### 🏢 Branch Control")
        gyms_list = [st.session_state["active_gym"]]
        if supabase:
            try:
                res = supabase.table("gyms").select("*").order("created_at").execute()
                if res.data:
                    gyms_list = res.data
            except Exception:
                pass

        gym_names = [g["name"] for g in gyms_list]
        current_name = st.session_state["active_gym"]["name"]
        default_idx = gym_names.index(current_name) if current_name in gym_names else 0

        chosen_gym_name = st.selectbox("Active Branch View", gym_names, index=default_idx)
        for g in gyms_list:
            if g["name"] == chosen_gym_name:
                st.session_state["active_gym"] = g
                break
    else:
        st.markdown("### 🏢 Assigned Branch")
        st.session_state["active_gym"] = fetch_gym_by_name(current_user["gym_name"])

    active_gym = st.session_state["active_gym"]
    st.info(
        f"**{active_gym['name']}** — {active_gym['city']}\n\n"
        f"🕒 {active_gym['timings']}\n\n"
        f"💳 {active_gym['monthly_fee']}"
    )

    if is_owner:
        with st.expander("➕ Onboard New Branch"):
            new_gym_name = st.text_input("Club Name", placeholder="e.g., FitZone Nashik")
            new_gym_city = st.text_input("City", placeholder="e.g., Nashik")
            new_gym_timings = st.text_input("Operating Hours", value="Mon-Sat: 6:00 AM - 10:00 PM")
            new_gym_fee = st.text_input("Base Membership", value="₹1,799/month")

            if st.button("SAVE BRANCH", use_container_width=True):
                if new_gym_name.strip() and new_gym_city.strip() and supabase:
                    new_record = {
                        "name": new_gym_name.strip(),
                        "city": new_gym_city.strip(),
                        "timings": new_gym_timings.strip(),
                        "monthly_fee": new_gym_fee.strip(),
                    }
                    try:
                        supabase.table("gyms").insert(new_record).execute()
                        st.session_state["active_gym"] = new_record
                        st.success(f"{new_gym_name} added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save branch: {e}")

    st.divider()
    st.markdown("### 💬 Your Saved Chats")
    if st.button("➕ New Chat", use_container_width=True):
        st.session_state["messages"] = []
        st.session_state["current_session_id"] = None
        st.session_state["latest_ics"] = None
        st.session_state["chat_open"] = True
        st.rerun()

    saved_sessions = fetch_chat_sessions(active_gym["name"], current_user["member_id"])
    if saved_sessions:
        for sess in saved_sessions:
            display_title = sess["title"].replace(f"[{current_user['member_id']}] ", "")
            if st.button(f"🗨️ {display_title}", key=f"sess_{sess['id']}", use_container_width=True):
                st.session_state["current_session_id"] = sess["id"]
                st.session_state["messages"] = load_session_messages(sess["id"])
                st.session_state["chat_open"] = True
                st.rerun()
    else:
        st.caption("No saved chats yet.")

    if is_owner:
        st.divider()
        st.markdown("### 📚 Branch RAG Policies")
        st.caption(f"Indexed docs: **{len(st.session_state['rag_docs'])}**")
        uploaded_doc = st.file_uploader("Upload Policy (.txt / .md)", type=["txt", "md"])
        if uploaded_doc is not None:
            doc_text = uploaded_doc.read().decode("utf-8").strip()
            if doc_text and not any(d["title"] == uploaded_doc.name for d in st.session_state["rag_docs"]):
                new_doc = {"title": uploaded_doc.name, "content": doc_text}
                st.session_state["rag_docs"].append(new_doc)
                if api_key:
                    new_emb = embed_texts(client, [f"{new_doc['title']}: {new_doc['content']}"])[0]
                    st.session_state["rag_embeddings"].append(new_emb)
                st.success(f"'{uploaded_doc.name}' indexed!")


# =========================================================
# AGENTIC TOOLS
# =========================================================

def calculate_macros(weight_kg: float, goal: str) -> str:
    st.session_state["last_tool_used"] = f"calculate_macros(weight_kg={weight_kg}, goal='{goal}')"
    if "loss" in goal.lower():
        calories = weight_kg * 22
        protein = weight_kg * 2.0
    else:
        calories = weight_kg * 30
        protein = weight_kg * 2.2

    return f"Target Calories: {calories:.0f} kcal, Protein target: {protein:.0f}g."


def book_trainer_session(
    trainer_name: str,
    time_slot: str,
    member_name: str = "",
    member_phone: str = "On File"
) -> str:
    verified_name = f"{current_user['full_name']} ({current_user['member_id']})"
    st.session_state["last_tool_used"] = (
        f"book_trainer_session(trainer='{trainer_name}', slot='{time_slot}', member='{verified_name}')"
    )
    gym_name = st.session_state["active_gym"]["name"]

    if supabase:
        try:
            supabase.table("bookings").insert({
                "gym_name": gym_name,
                "member_name": verified_name,
                "member_phone": member_phone,
                "trainer_name": trainer_name,
                "time_slot": time_slot,
            }).execute()
            return (
                f"Booking confirmed for {verified_name} with {trainer_name} at {time_slot} "
                f"({gym_name})."
            )
        except Exception as e:
            return f"Unable to complete booking: {str(e)}"

    return f"Booking confirmed for {verified_name} with {trainer_name} at {time_slot}."


def set_gym_reminder(
    reminder_date: str,
    reminder_time: str,
    workout_focus: str = "Gym Workout Session",
    member_name: str = ""
) -> str:
    verified_name = f"{current_user['full_name']} ({current_user['member_id']})"
    st.session_state["last_tool_used"] = (
        f"set_gym_reminder(date='{reminder_date}', time='{reminder_time}', focus='{workout_focus}')"
    )
    gym = st.session_state["active_gym"]
    ics_data, gcal_url = build_gym_ics(
        gym_name=gym["name"],
        city=gym["city"],
        date_str=reminder_date,
        time_str=reminder_time,
        focus=workout_focus,
    )
    st.session_state["latest_ics"] = {
        "ics": ics_data,
        "gcal": gcal_url,
        "label": f"{workout_focus} — {reminder_date} at {reminder_time}",
    }

    if supabase:
        try:
            supabase.table("gym_reminders").insert({
                "gym_name": gym["name"],
                "member_name": verified_name,
                "workout_focus": workout_focus,
                "reminder_date": reminder_date,
                "reminder_time": reminder_time,
            }).execute()
        except Exception:
            pass

    return (
        f"Gym reminder set for {verified_name} on {reminder_date} at {reminder_time} ({workout_focus}) at {gym['name']}."
    )


# =========================================================
# HELPER — CALL GEMINI
# =========================================================

def call_gemini(prompt: str) -> str:
    if not api_key:
        return "Service configuration error: GEMINI_API_KEY is missing."

    last_error = ""
    for model_name in MODELS:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.4),
                )
                return response.text
            except Exception as e:
                last_error = str(e)
                if "503" in last_error and attempt == 0:
                    time.sleep(2)
                    continue
                if "503" in last_error or "404" in last_error:
                    break
                return f"Unable to process request right now. Details: {last_error}"

    return f"Service temporarily busy. Please retry shortly. ({last_error})"


# =========================================================
# AGENTIC WORKFLOW — STATEGRAPH EXECUTION
# =========================================================

def generate_fitbot_response() -> tuple[str, dict]:
    active_gym = st.session_state["active_gym"]
    st.session_state["last_tool_used"] = None

    latest_user_query = ""
    conversation_history = (
        f"SYSTEM CONTEXT: Logged-in user is {current_user['full_name']} "
        f"(ID: {current_user['member_id']}, Role: {current_user['role']}).\n\n"
    )

    for message in st.session_state["messages"]:
        role = "USER" if message["role"] == "user" else "FITBOT"
        conversation_history += f"{role}: {message['content']}\n\n"
        if message["role"] == "user":
            latest_user_query = message["content"]

    graph = build_fitbot_graph(
        client=client,
        models=MODELS,
        calc_macros_fn=calculate_macros,
        book_trainer_fn=book_trainer_session,
        set_reminder_fn=set_gym_reminder,
    )

    final_state = graph.invoke({
        "query": latest_user_query,
        "conversation_history": conversation_history,
        "active_gym": active_gym,
        "gym_data": GYM_DATA,
        "rag_docs": st.session_state["rag_docs"],
        "rag_embeddings": st.session_state["rag_embeddings"],
        "retrieved_chunks": [],
        "tool_decision": {},
        "tool_output": "",
        "final_response": "",
        "nodes_visited": [],
    })

    trace = {
        "nodes_visited": final_state.get("nodes_visited", []),
        "rag_sources": final_state.get("retrieved_chunks", []),
        "tool_called": st.session_state.get("last_tool_used"),
        "gym": active_gym["name"],
    }
    return final_state["final_response"], trace


# =========================================================
# CHAT SCREEN
# =========================================================

if st.session_state["chat_open"]:

    back_col, space_col, end_col = st.columns([1.5, 3, 1.7])

    with back_col:
        if st.button("← BACK TO HOME", key="back_from_chat", use_container_width=True):
            st.session_state["chat_open"] = False
            st.rerun()

    with end_col:
        if st.button("➕ NEW CHAT", key="end_conversation", use_container_width=True):
            st.session_state["messages"] = []
            st.session_state["current_session_id"] = None
            st.session_state["latest_ics"] = None
            st.rerun()

    st.markdown(
        f'<div class="chat-page-header">'
        f'<div class="chat-page-title">'
        f'<span style="color:#F5F5F5 !important;">FITBOT</span> '
        f'<span style="color:#B7F34A !important;">AI</span>'
        f'</div>'
        f'<div class="chat-page-divider"></div>'
        f'<div class="chat-page-subtitle">'
        f'{st.session_state["active_gym"]["name"].upper()} • {current_user["full_name"].upper()}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("trace"):
                with st.expander("Sources & Agent Execution"):
                    trace = message["trace"]
                    if trace.get("nodes_visited"):
                        st.caption(f"🕸️ **StateGraph Execution Path:** `{' → '.join(trace['nodes_visited'])}`")
                    if trace.get("tool_called"):
                        st.success(f"Action Executed: `{trace['tool_called']}`")
                    st.markdown("**Referenced Club Policies:**")
                    for src in trace.get("rag_sources", []):
                        st.markdown(f"- **{src['title']}** (Match: `{src['score']}`): {src['content']}")

    if st.session_state["messages"] and st.session_state["messages"][-1]["role"] == "user":
        with st.chat_message("assistant"):
            with st.spinner("Running FitBot Agent Graph..."):
                assistant_reply, trace = generate_fitbot_response()
            st.markdown(assistant_reply)
            with st.expander("Sources & Agent Execution"):
                if trace.get("nodes_visited"):
                    st.caption(f"🕸️ **StateGraph Execution Path:** `{' → '.join(trace['nodes_visited'])}`")
                if trace.get("tool_called"):
                    st.success(f"Action Executed: `{trace['tool_called']}`")
                st.markdown("**Referenced Club Policies:**")
                for src in trace.get("rag_sources", []):
                    st.markdown(f"- **{src['title']}** (Match: `{src['score']}`): {src['content']}")

        st.session_state["messages"].append({
            "role": "assistant",
            "content": assistant_reply,
            "trace": trace,
        })
        save_chat_message(
            st.session_state.get("current_session_id"),
            "assistant",
            assistant_reply,
            trace,
        )

    if st.session_state.get("latest_ics"):
        rem = st.session_state["latest_ics"]
        st.info(f"🔔 **Workout Reminder Ready:** {rem['label']}")
        r_col1, r_col2 = st.columns(2)
        with r_col1:
            st.download_button(
                "📲 ADD PHONE ALERT (.ICS)",
                data=rem["ics"],
                file_name="fitbot_gym_reminder.ics",
                mime="text/calendar",
                use_container_width=True,
            )
        with r_col2:
            st.link_button(
                "📅 OPEN GOOGLE CALENDAR",
                url=rem["gcal"],
                use_container_width=True,
            )

    user_message = st.chat_input("Ask about memberships, set a gym reminder, or book a trainer...")

    if user_message:
        if not st.session_state.get("current_session_id"):
            st.session_state["current_session_id"] = create_chat_session(
                st.session_state["active_gym"]["name"],
                user_message,
                current_user["member_id"],
            )
        st.session_state["messages"].append({"role": "user", "content": user_message})
        save_chat_message(st.session_state["current_session_id"], "user", user_message)
        st.rerun()


# =========================================================
# MAIN PORTAL
# =========================================================

else:

    # =====================================================
    # HOME SCREEN (ROLE-SPECIFIC COMMAND CENTER)
    # =====================================================

    if st.session_state["selected_category"] is None:
        show_header()

        active_gym = st.session_state["active_gym"]

        # 1. OWNER KPI BAR
        if is_owner:
            payments_data = fetch_payments(active_gym["name"])
            expenses_data = fetch_expenses(active_gym["name"])
            branch_members = [m for m in fetch_branch_members(active_gym["name"]) if m.get("role") == "member"]

            total_rev = sum(float(p["amount_inr"]) for p in payments_data if p.get("status") == "Paid")
            pending_dues = sum(float(p["amount_inr"]) for p in payments_data if p.get("status") == "Pending")
            total_exp = sum(float(e["amount_inr"]) for e in expenses_data)
            budget_limit = BRANCH_MONTHLY_BUDGET_INR.get(active_gym["name"], 30000)

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Revenue", f"₹{total_rev:,.0f}", f"Dues: ₹{pending_dues:,.0f}")
            k2.metric("Budget Spent", f"₹{total_exp:,.0f}", f"of ₹{budget_limit:,.0f}")
            k3.metric("Net Profit", f"₹{total_rev - total_exp:,.0f}", active_gym["city"])
            k4.metric("Members", f"{len(branch_members)}", f"{sum(1 for m in branch_members if m.get('is_activated'))} Active")

        # 2. TRAINER KPI BAR
        elif is_trainer:
            my_pt_sessions = fetch_gym_bookings(active_gym["name"], trainer_filter=current_user["full_name"])
            m1, m2, m3 = st.columns(3)
            m1.metric("Coach Branch", active_gym["city"], active_gym["name"])
            m2.metric("Assigned PT Clients", f"{len(my_pt_sessions)}", "Active Roster")
            m3.metric("Specialty", "PT & Strength", "On Duty")

        # 3. RECEPTION & MEMBER KPI BAR
        else:
            member_filter = None if is_reception else current_user["member_id"]
            branch_bookings = fetch_gym_bookings(active_gym["name"], member_filter=member_filter)
            branch_reminders = fetch_gym_reminders(active_gym["name"], member_filter=member_filter)

            m1, m2, m3 = st.columns(3)
            m1.metric("Active Branch", active_gym["city"], active_gym["name"])
            m2.metric("PT Bookings", f"{len(branch_bookings)}", "Branch Total" if is_reception else "Your Sessions")
            m3.metric("Reminders", f"{len(branch_reminders)}", "Scheduled")

        st.write("")
        workout, activities, trainers, gym_info = show_categories()

        if workout:
            st.session_state["selected_category"] = "workout"
            st.rerun()

        if activities:
            st.session_state["selected_category"] = "activities"
            st.rerun()

        if trainers:
            st.session_state["selected_category"] = "trainers"
            st.rerun()

        if gym_info:
            st.session_state["selected_category"] = "gym_info"
            st.rerun()

        # ROLE-SPECIFIC ACTION BUTTONS
        if is_owner:
            b1, b2, b3, b4 = st.columns(4, gap="small")
            with b1:
                if st.button("💼 BUSINESS", key="open_business", use_container_width=True):
                    st.session_state["selected_category"] = "business_finance"
                    st.rerun()
            with b2:
                if st.button("📋 BOOKINGS", key="open_bookings", use_container_width=True):
                    st.session_state["selected_category"] = "bookings"
                    st.rerun()
            with b3:
                if st.button("⏰ REMINDERS", key="open_reminders", use_container_width=True):
                    st.session_state["selected_category"] = "reminders"
                    st.rerun()
            with b4:
                if st.button("🪪 MEMBERS", key="open_members", use_container_width=True):
                    st.session_state["selected_category"] = "members_admin"
                    st.rerun()

        elif is_reception:
            b1, b2, b3, b4 = st.columns(4, gap="small")
            with b1:
                if st.button("💳 COLLECT FEE", key="open_rec_pay", use_container_width=True):
                    st.session_state["selected_category"] = "reception_payments"
                    st.rerun()
            with b2:
                if st.button("📋 BOOKINGS", key="open_bookings", use_container_width=True):
                    st.session_state["selected_category"] = "bookings"
                    st.rerun()
            with b3:
                if st.button("⏰ REMINDERS", key="open_reminders", use_container_width=True):
                    st.session_state["selected_category"] = "reminders"
                    st.rerun()
            with b4:
                if st.button("🪪 MEMBERS", key="open_members", use_container_width=True):
                    st.session_state["selected_category"] = "members_admin"
                    st.rerun()

        elif is_trainer:
            b1, b2, b3 = st.columns(3, gap="small")
            with b1:
                if st.button("💪 MY PT CLIENTS", key="open_trainer_hub", use_container_width=True):
                    st.session_state["selected_category"] = "trainer_hub"
                    st.rerun()
            with b2:
                if st.button("📊 MACROS", key="open_calculator", use_container_width=True):
                    st.session_state["selected_category"] = "calculator"
                    st.rerun()
            with b3:
                if st.button("⏰ REMINDERS", key="open_reminders", use_container_width=True):
                    st.session_state["selected_category"] = "reminders"
                    st.rerun()

        else:
            b1, b2, b3, b4 = st.columns(4, gap="small")
            with b1:
                if st.button("💪 MY ROUTINE", key="open_my_routine", use_container_width=True):
                    st.session_state["selected_category"] = "my_routine"
                    st.rerun()
            with b2:
                if st.button("📊 MACROS", key="open_calculator", use_container_width=True):
                    st.session_state["selected_category"] = "calculator"
                    st.rerun()
            with b3:
                if st.button("📋 BOOKINGS", key="open_bookings", use_container_width=True):
                    st.session_state["selected_category"] = "bookings"
                    st.rerun()
            with b4:
                if st.button("⏰ REMINDERS", key="open_reminders", use_container_width=True):
                    st.session_state["selected_category"] = "reminders"
                    st.rerun()

        st.divider()

        st.markdown(
            f"""
<div class="fitbot-cta">
    HOW CAN <span>I</span> HELP YOU, {current_user['full_name'].split()[0].upper()}?
</div>
""",
            unsafe_allow_html=True
        )

        with st.form("home_chat_form", clear_on_submit=True):
            first_message = st.text_input(
                "Ask FitBot",
                placeholder="Ask about memberships, book a trainer, or set a gym reminder...",
                label_visibility="collapsed"
            )

            send_message = st.form_submit_button("START CHAT →", use_container_width=True)

        if send_message and first_message.strip():
            clean_msg = first_message.strip()
            sess_id = create_chat_session(
                st.session_state["active_gym"]["name"],
                clean_msg,
                current_user["member_id"],
            )
            st.session_state["current_session_id"] = sess_id
            st.session_state["messages"] = [{"role": "user", "content": clean_msg}]
            save_chat_message(sess_id, "user", clean_msg)
            st.session_state["chat_open"] = True
            st.rerun()

    # =====================================================
    # OWNER ONLY: BUSINESS, PAYMENTS & BUDGET HUB
    # =====================================================

    elif st.session_state["selected_category"] == "business_finance" and is_owner:
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">BUSINESS &</span> '
            '<span style="color:#B7F34A !important;">BUDGET</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Revenue, pending dues, operating budget, and Pune vs. Mumbai performance.'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_business"):
            st.session_state["selected_category"] = None
            st.rerun()

        payments_data = fetch_payments(active_gym["name"])
        expenses_data = fetch_expenses(active_gym["name"])
        total_rev = sum(float(p["amount_inr"]) for p in payments_data if p.get("status") == "Paid")
        pending_dues = sum(float(p["amount_inr"]) for p in payments_data if p.get("status") == "Pending")
        total_exp = sum(float(e["amount_inr"]) for e in expenses_data)
        budget_limit = BRANCH_MONTHLY_BUDGET_INR.get(active_gym["name"], 30000)

        m1, m2, m3 = st.columns(3)
        m1.metric("Collected Revenue", f"₹{total_rev:,.0f}", f"Pending: ₹{pending_dues:,.0f}")
        m2.metric("Expenses / Budget", f"₹{total_exp:,.0f}", f"Limit: ₹{budget_limit:,.0f}")
        m3.metric("Net Branch Profit", f"₹{total_rev - total_exp:,.0f}")

        st.progress(min(total_exp / budget_limit, 1.0) if budget_limit else 0.0)

        tab_pay, tab_exp, tab_all = st.tabs(["💳 Payments Ledger", "🧾 Budget & Expenses", "🏢 Pune vs Mumbai"])

        with tab_pay:
            with st.expander("➕ Record Payment", expanded=False):
                with st.form("record_pay_form", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    with c1:
                        p_id = st.text_input("Member ID", placeholder="e.g., FZ-PUN-1001")
                        p_name = st.text_input("Member Name", placeholder="e.g., Rohan Kulkarni")
                        p_plan = st.selectbox("Plan", ["Monthly", "Quarterly Pro", "Annual Elite", "Personal Training"])
                    with c2:
                        p_amt = st.number_input("Amount (₹)", min_value=100, max_value=100000, value=3999, step=500)
                        p_mode = st.selectbox("Payment Mode", ["UPI", "Card", "Cash"])
                        p_stat = st.selectbox("Status", ["Paid", "Pending"])

                    if st.form_submit_button("SAVE PAYMENT", use_container_width=True):
                        if p_id.strip() and p_name.strip() and supabase:
                            supabase.table("payments").insert({
                                "gym_name": active_gym["name"],
                                "member_id": p_id.strip().upper(),
                                "member_name": p_name.strip(),
                                "plan_type": p_plan,
                                "amount_inr": p_amt,
                                "payment_mode": p_mode,
                                "status": p_stat,
                            }).execute()
                            st.success("Payment saved!")
                            st.rerun()

            if payments_data:
                df_p = pd.DataFrame(payments_data)
                cols = [c for c in ["member_id", "member_name", "plan_type", "amount_inr", "payment_mode", "status"] if c in df_p.columns]
                st.dataframe(df_p[cols], use_container_width=True, hide_index=True)

        with tab_exp:
            with st.expander("➕ Log Expense", expanded=False):
                with st.form("record_exp_form", clear_on_submit=True):
                    e1, e2, e3 = st.columns(3)
                    with e1:
                        e_cat = st.selectbox("Category", ["Trainer Payroll", "Rent & Utilities", "Equipment", "Marketing"])
                    with e2:
                        e_desc = st.text_input("Description", placeholder="e.g., AC Servicing")
                    with e3:
                        e_amt = st.number_input("Amount (₹)", min_value=100, max_value=200000, value=2500, step=250)

                    if st.form_submit_button("SAVE EXPENSE", use_container_width=True):
                        if e_desc.strip() and supabase:
                            supabase.table("expenses").insert({
                                "gym_name": active_gym["name"],
                                "category": e_cat,
                                "description": e_desc.strip(),
                                "amount_inr": e_amt,
                            }).execute()
                            st.success("Expense logged!")
                            st.rerun()

            if expenses_data:
                df_e = pd.DataFrame(expenses_data)
                cols = [c for c in ["category", "description", "amount_inr"] if c in df_e.columns]
                st.dataframe(df_e[cols], use_container_width=True, hide_index=True)

        with tab_all:
            all_p = fetch_payments(None)
            all_e = fetch_expenses(None)
            all_m = fetch_branch_members(None)
            rows = []
            for b in ["FitZone Pune", "FitZone Mumbai"]:
                rev = sum(float(p["amount_inr"]) for p in all_p if p["gym_name"] == b and p["status"] == "Paid")
                dues = sum(float(p["amount_inr"]) for p in all_p if p["gym_name"] == b and p["status"] == "Pending")
                exp = sum(float(e["amount_inr"]) for e in all_e if e["gym_name"] == b)
                m_cnt = sum(1 for m in all_m if m["gym_name"] == b and m["role"] == "member")
                rows.append({
                    "Branch": b,
                    "Members": m_cnt,
                    "Revenue (₹)": rev,
                    "Pending (₹)": dues,
                    "Expenses (₹)": exp,
                    "Net Profit (₹)": rev - exp,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # =====================================================
    # RECEPTION ONLY: COLLECT BRANCH FEES
    # =====================================================

    elif st.session_state["selected_category"] == "reception_payments" and is_reception:
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">FRONT DESK</span> '
            '<span style="color:#B7F34A !important;">FEE COLLECTION</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">Record membership payments at {active_gym["name"]}.</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_rec_pay"):
            st.session_state["selected_category"] = None
            st.rerun()

        with st.form("rec_pay_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                p_id = st.text_input("Member ID", placeholder="e.g., FZ-PUN-1001")
                p_name = st.text_input("Member Name", placeholder="e.g., Rohan Kulkarni")
            with c2:
                p_plan = st.selectbox("Plan", ["Monthly", "Quarterly Pro", "Annual Elite", "Personal Training"])
                p_amt = st.number_input("Amount (₹)", min_value=100, max_value=100000, value=1499, step=500)
            p_mode = st.selectbox("Payment Mode", ["UPI", "Card", "Cash"])

            if st.form_submit_button("✅ RECORD PAID RECEIPT", use_container_width=True):
                if p_id.strip() and p_name.strip() and supabase:
                    supabase.table("payments").insert({
                        "gym_name": active_gym["name"],
                        "member_id": p_id.strip().upper(),
                        "member_name": p_name.strip(),
                        "plan_type": p_plan,
                        "amount_inr": p_amt,
                        "payment_mode": p_mode,
                        "status": "Paid",
                    }).execute()
                    st.success(f"Receipt recorded: ₹{p_amt:,} from {p_name.strip()} ({p_mode})!")
                    st.rerun()

        payments_data = fetch_payments(active_gym["name"])
        if payments_data:
            df_p = pd.DataFrame(payments_data)
            cols = [c for c in ["member_id", "member_name", "plan_type", "amount_inr", "payment_mode", "status"] if c in df_p.columns]
            st.dataframe(df_p[cols], use_container_width=True, hide_index=True)

    # =====================================================
    # TRAINER ONLY: ASSIGNED PT CLIENTS & COACHING LOG
    # =====================================================

    elif st.session_state["selected_category"] == "trainer_hub" and is_trainer:
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">PT COACH</span> '
            '<span style="color:#B7F34A !important;">SCHEDULE</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Assigned personal training sessions for Coach {current_user["full_name"]} ({active_gym["name"]}).'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_trainer_hub"):
            st.session_state["selected_category"] = None
            st.rerun()

        my_sessions = fetch_gym_bookings(active_gym["name"], trainer_filter=current_user["full_name"])
        if my_sessions:
            df_t = pd.DataFrame(my_sessions)
            cols = [c for c in ["member_name", "time_slot", "member_phone", "created_at"] if c in df_t.columns]
            st.dataframe(df_t[cols], use_container_width=True, hide_index=True)
        else:
            st.info("No personal training clients assigned to your slot yet.")

    # =====================================================
    # MEMBER SMART WORKOUT ROUTINE & ATTENDANCE TRACKER
    # =====================================================

    elif st.session_state["selected_category"] == "my_routine":
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">MY WORKOUT</span> '
            '<span style="color:#B7F34A !important;">TRACKER</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Follow your saved routine, track today vs. tomorrow, and log completed or missed workouts.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_routine"):
            st.session_state["selected_category"] = None
            st.rerun()

        saved_plan = fetch_member_saved_plan(current_user["member_id"])

        if not saved_plan:
            st.info("You don't have an active routine saved yet! Choose a level below to activate your daily tracker:")
            chosen_lvl = st.selectbox("Select Plan Level", ["Beginner", "Intermediate", "Advanced", "Pro"])
            if st.button("🚀 ACTIVATE THIS PLAN", use_container_width=True):
                preview_lines = "\n".join(f"- {line}" for line in WEEKLY_ROUTINE_PREVIEW[chosen_lvl])
                save_member_plan_record(current_user["member_id"], active_gym["name"], chosen_lvl, preview_lines)
                st.success(f"{chosen_lvl} routine saved!")
                st.rerun()
        else:
            lvl = saved_plan["level"]
            days_list = WEEKLY_ROUTINE_PREVIEW.get(lvl, WEEKLY_ROUTINE_PREVIEW["Beginner"])
            comp = int(saved_plan.get("completed_days") or 0)
            missed = int(saved_plan.get("missed_days") or 0)

            today_idx = comp % len(days_list)
            tomorrow_idx = (comp + 1) % len(days_list)

            s1, s2, s3 = st.columns(3)
            s1.metric("Active Level", lvl, saved_plan.get("last_status", "Active"))
            s2.metric("Completed Days", f"{comp}", "On Track")
            s3.metric("Missed Days", f"{missed}", "Catch-up Needed" if missed > 0 else "Zero Misses")

            st.success(f"🔥 **TODAY'S WORKOUT:** {days_list[today_idx]}")
            st.info(f"📅 **TOMORROW'S WORKOUT:** {days_list[tomorrow_idx]}")

            a1, a2, a3 = st.columns(3)
            with a1:
                if st.button("✅ COMPLETED TODAY", use_container_width=True):
                    supabase.table("member_plans").update({
                        "completed_days": comp + 1,
                        "last_status": "Completed Today ✅",
                    }).eq("member_id", current_user["member_id"]).execute()
                    st.rerun()
            with a2:
                if st.button("⚠️ MISSED TODAY", use_container_width=True):
                    supabase.table("member_plans").update({
                        "missed_days": missed + 1,
                        "last_status": "Missed Today — Rescheduled ⚠️",
                    }).eq("member_id", current_user["member_id"]).execute()
                    st.rerun()
            with a3:
                if st.button("🔔 REMIND TOMORROW 7 AM", use_container_width=True):
                    tmrw = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")
                    msg = set_gym_reminder(tmrw, "07:00", workout_focus=days_list[tomorrow_idx][:45])
                    st.success(msg)

            if st.session_state.get("latest_ics"):
                rem = st.session_state["latest_ics"]
                c1, c2 = st.columns(2)
                with c1:
                    st.download_button(
                        "📲 DOWNLOAD PHONE ALERT (.ICS)",
                        data=rem["ics"],
                        file_name="fitbot_workout_alert.ics",
                        mime="text/calendar",
                        use_container_width=True,
                    )
                with c2:
                    st.link_button("📅 GOOGLE CALENDAR", url=rem["gcal"], use_container_width=True)

            with st.expander("📋 View Full Saved Plan", expanded=True):
                st.markdown(saved_plan["plan_text"])

    # =====================================================
    # STAFF ONLY (OWNER & RECEPTION): ISSUE IDs & ROSTER
    # =====================================================

    elif st.session_state["selected_category"] == "members_admin" and is_staff:
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">MEMBER</span> '
            '<span style="color:#B7F34A !important;">ENROLLMENT</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Issue new IDs for {active_gym["name"]}. Users activate their own password on first login.'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_members"):
            st.session_state["selected_category"] = None
            st.rerun()

        city_prefix = "MUM" if "mumbai" in active_gym["name"].lower() else "PUN"
        suggested_id = f"FZ-{city_prefix}-{secrets.randbelow(8999) + 1000}"

        with st.form("issue_member_id_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                new_m_id = st.text_input("New Issued ID", value=suggested_id)
                new_m_name = st.text_input("Full Name", placeholder="e.g., Siddharth Joshi")
            with c2:
                new_m_email = st.text_input("Email ID", placeholder="e.g., siddharth@gmail.com")
                new_m_phone4 = st.text_input("Last 4 Digits of Phone", max_chars=4, placeholder="e.g., 7890")

            r_col1, r_col2 = st.columns(2)
            with r_col1:
                new_m_plan = st.selectbox(
                    "Membership / Role Plan",
                    ["Monthly", "Quarterly Pro", "Annual Elite", "Front Desk Staff", "PT Coach"]
                )
            with r_col2:
                role_options = ["member", "reception", "trainer"] if is_owner else ["member"]
                new_m_role = st.selectbox("Account Role", role_options)

            if st.form_submit_button("🪪 ISSUE ID", use_container_width=True):
                if new_m_id.strip() and new_m_name.strip() and new_m_email.strip() and len(new_m_phone4.strip()) == 4 and supabase:
                    try:
                        supabase.table("members").insert({
                            "member_id": new_m_id.strip().upper(),
                            "full_name": new_m_name.strip(),
                            "email": new_m_email.strip().lower(),
                            "phone_last4": new_m_phone4.strip(),
                            "password_hash": None,
                            "is_activated": False,
                            "role": new_m_role,
                            "gym_name": active_gym["name"],
                            "plan_type": new_m_plan,
                        }).execute()
                        st.success(
                            f"✅ Issued ID **`{new_m_id.strip().upper()}`** ({new_m_role}) to **{new_m_name.strip()}** ({active_gym['name']})."
                        )
                    except Exception as e:
                        st.error(f"Could not create record: {e}")
                else:
                    st.warning("Please fill in all fields including 4 phone digits.")

        st.subheader(f"Enrolled Roster — {active_gym['name']}")
        roster = fetch_branch_members(active_gym["name"])
        if roster:
            st.dataframe(pd.DataFrame(roster), use_container_width=True, hide_index=True)
        else:
            st.info("No members enrolled in this branch yet.")

    # =====================================================
    # GYM REMINDERS & NOTIFICATION CENTER
    # =====================================================

    elif st.session_state["selected_category"] == "reminders":
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">GYM</span> '
            '<span style="color:#B7F34A !important;">REMINDERS</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Schedule workout alerts and sync 30-minute notifications directly to your phone calendar.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_reminders"):
            st.session_state["selected_category"] = None
            st.rerun()

        with st.form("schedule_reminder_form", clear_on_submit=True):
            r1, r2 = st.columns(2)
            with r1:
                rem_date = st.date_input("Workout Date", value=datetime.now().date() + timedelta(days=1))
                rem_time = st.time_input("Workout Time", value=datetime.strptime("07:00", "%H:%M").time())
            with r2:
                rem_focus = st.selectbox(
                    "Workout Focus",
                    ["Full Body Strength", "Upper Body & Core", "Leg Day", "Cardio & HIIT", "Yoga / Mobility"]
                )

            if st.form_submit_button("🔔 SET GYM REMINDER", use_container_width=True):
                d_str = rem_date.strftime("%Y-%m-%d")
                t_str = rem_time.strftime("%H:%M")
                msg = set_gym_reminder(
                    reminder_date=d_str,
                    reminder_time=t_str,
                    workout_focus=rem_focus,
                )
                st.success(msg)

        if st.session_state.get("latest_ics"):
            rem = st.session_state["latest_ics"]
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "📲 DOWNLOAD PHONE NOTIFICATION (.ICS)",
                    data=rem["ics"],
                    file_name="fitbot_gym_reminder.ics",
                    mime="text/calendar",
                    use_container_width=True,
                )
            with c2:
                st.link_button(
                    "📅 SYNC WITH GOOGLE CALENDAR",
                    url=rem["gcal"],
                    use_container_width=True,
                )

        st.subheader("Scheduled Workout Reminders")
        member_filter = None if is_staff else current_user["member_id"]
        reminders_list = fetch_gym_reminders(active_gym["name"], member_filter=member_filter)
        if reminders_list:
            df_rem = pd.DataFrame(reminders_list)
            cols = [c for c in ["member_name", "workout_focus", "reminder_date", "reminder_time"] if c in df_rem.columns]
            st.dataframe(df_rem[cols], use_container_width=True, hide_index=True)
        else:
            st.info("No reminders scheduled yet.")

    # =====================================================
    # BOOKINGS & FRONT-DESK OPERATIONS
    # =====================================================

    elif st.session_state["selected_category"] == "bookings":
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">BOOKINGS &</span> '
            '<span style="color:#B7F34A !important;">SCHEDULE</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Personal training sessions for {active_gym["name"]}.'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_bookings"):
            st.session_state["selected_category"] = None
            st.rerun()

        member_filter = None if is_staff else current_user["member_id"]
        bookings_data = fetch_gym_bookings(active_gym["name"], member_filter=member_filter)

        if is_staff:
            with st.expander("➕ Log Walk-In / Phone Booking", expanded=False):
                with st.form("walkin_booking_form", clear_on_submit=True):
                    wb_col1, wb_col2 = st.columns(2)
                    with wb_col1:
                        wb_member = st.text_input("Member Name & ID", placeholder="e.g., Rohan Kulkarni (FZ-PUN-1001)")
                        wb_phone = st.text_input("Phone Number", placeholder="e.g., +91-98765-43210")
                    with wb_col2:
                        wb_trainer = st.selectbox("Trainer", ["Rahul Sharma", "Priya Mehta", "Arjun Patel"])
                        wb_slot = st.text_input("Date & Time Slot", placeholder="e.g., Tomorrow 8:00 AM")

                    if st.form_submit_button("CONFIRM BOOKING", use_container_width=True):
                        if wb_member.strip() and wb_slot.strip() and supabase:
                            try:
                                supabase.table("bookings").insert({
                                    "gym_name": active_gym["name"],
                                    "member_name": wb_member.strip(),
                                    "member_phone": wb_phone.strip() or "Not Provided",
                                    "trainer_name": wb_trainer,
                                    "time_slot": wb_slot.strip(),
                                }).execute()
                                st.success("Walk-in booking recorded!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Database error: {e}")

        st.subheader("Scheduled Sessions")
        if bookings_data:
            df = pd.DataFrame(bookings_data)
            display_cols = [c for c in ["member_name", "trainer_name", "time_slot", "created_at"] if c in df.columns]
            st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

            if is_staff:
                csv_bytes = df[display_cols].to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ EXPORT BRANCH SCHEDULE (CSV)",
                    data=csv_bytes,
                    file_name=f"{active_gym['name'].lower().replace(' ', '_')}_bookings.csv",
                    mime="text/csv",
                )
        else:
            st.info("No sessions scheduled yet. Book a trainer via chat!")

    # =====================================================
    # BMI & MACRO CALCULATOR
    # =====================================================

    elif st.session_state["selected_category"] == "calculator":
        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">BMI & MACRO</span> '
            '<span style="color:#B7F34A !important;">CALCULATOR</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Calculate your Body Mass Index and daily nutrition targets instantly.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_calculator"):
            st.session_state["selected_category"] = None
            st.rerun()

        calc_l, calc_c, calc_r = st.columns([0.8, 3.5, 0.8])

        with calc_c:
            weight = st.number_input("Weight (kg)", min_value=30.0, max_value=200.0, value=70.0, step=0.5)
            height_cm = st.number_input("Height (cm)", min_value=120.0, max_value=230.0, value=170.0, step=1.0)
            goal = st.selectbox("Fitness Goal", ["Weight Loss", "Maintenance", "Muscle Gain"])

            if st.button("CALCULATE →", key="run_calc", use_container_width=True):
                height_m = height_cm / 100
                bmi = weight / (height_m ** 2)

                if bmi < 18.5:
                    bmi_status = "Underweight"
                elif bmi < 25:
                    bmi_status = "Healthy Weight"
                elif bmi < 30:
                    bmi_status = "Overweight"
                else:
                    bmi_status = "Obese"

                if goal == "Weight Loss":
                    calories = weight * 22
                    protein = weight * 2.0
                elif goal == "Maintenance":
                    calories = weight * 26
                    protein = weight * 1.8
                else:
                    calories = weight * 30
                    protein = weight * 2.2

                st.divider()
                m1, m2, m3 = st.columns(3)
                m1.metric("BMI", f"{bmi:.1f}", bmi_status)
                m2.metric("Daily Calories", f"{calories:.0f} kcal")
                m3.metric("Daily Protein", f"{protein:.0f} g")

    # =====================================================
    # WORKOUT PLANS (WITH ONE-CLICK SAVE TO MY ROUTINE)
    # =====================================================

    elif st.session_state["selected_category"] == "workout":
        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">WORKOUT</span> '
            '<span style="color:#B7F34A !important;">PLANS</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Generate a structured workout plan and save it directly to your daily routine tracker.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_workout"):
            st.session_state["selected_category"] = None
            st.session_state["workout_request"] = None
            st.rerun()

        form_left, form_center, form_right = st.columns([1.2, 3, 1.2])

        with form_center:
            workout_level = st.selectbox(
                "Choose your fitness level",
                ["Beginner", "Intermediate", "Advanced", "Pro"],
                key="workout_level"
            )

            if st.button("GET WORKOUT PLAN →", key="get_workout_plan", use_container_width=True):
                st.session_state["workout_request"] = (
                    f"Create a {workout_level} level 6-day workout plan for {current_user['full_name']}. "
                    "Make it clear, structured, practical and suitable for a gym member."
                )

        if st.session_state["workout_request"]:
            with st.spinner("Creating your workout plan..."):
                workout_text = call_gemini(st.session_state["workout_request"])
            st.session_state["latest_generated_plan"] = {
                "level": workout_level,
                "text": workout_text,
            }
            st.session_state["workout_request"] = None

        if st.session_state.get("latest_generated_plan"):
            gen = st.session_state["latest_generated_plan"]
            st.markdown(
                '<div class="general-page-header" style="margin-top:30px;">'
                '<h2 class="general-page-title" style="font-size:30px;">'
                'YOUR <span>WORKOUT PLAN</span>'
                '</h2>'
                '<div class="general-page-divider"></div>'
                '</div>',
                unsafe_allow_html=True
            )

            if st.button("💾 SAVE AS MY ACTIVE ROUTINE", use_container_width=True):
                save_member_plan_record(
                    current_user["member_id"],
                    st.session_state["active_gym"]["name"],
                    gen["level"],
                    gen["text"],
                )
                st.success("✅ Saved! Open **💪 MY ROUTINE** from the Home screen to track Today, Tomorrow, and Missed days.")

            result_left, result_center, result_right = st.columns([0.7, 4, 0.7])
            with result_center:
                st.markdown('<div class="workout-result-label">PERSONALIZED TRAINING PROGRAM</div>', unsafe_allow_html=True)
                st.markdown(gen["text"])

    # =====================================================
    # ACTIVITIES
    # =====================================================

    elif st.session_state["selected_category"] == "activities":
        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">OUR</span> '
            '<span style="color:#B7F34A !important;">ACTIVITIES</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Explore group fitness sessions designed to keep you active, energised and consistent.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_activities"):
            st.session_state["selected_category"] = None
            st.session_state["selected_activity"] = None
            st.rerun()

        st.markdown('<p class="activity-select-label">CHOOSE AN ACTIVITY</p>', unsafe_allow_html=True)
        activity = st.session_state.get("selected_activity")
        activity_left, activity_center, activity_right = st.columns([0.7, 4, 0.7])

        with activity_center:
            col1, col2, col3 = st.columns(3, gap="medium")

            with col1:
                if st.button("YOGA", use_container_width=True, key="activity_yoga", type="primary" if activity == "Yoga" else "secondary"):
                    st.session_state["selected_activity"] = "Yoga"
                    st.rerun()

            with col2:
                if st.button("ZUMBA", use_container_width=True, key="activity_zumba", type="primary" if activity == "Zumba" else "secondary"):
                    st.session_state["selected_activity"] = "Zumba"
                    st.rerun()

            with col3:
                if st.button("AEROBICS", use_container_width=True, key="activity_aerobics", type="primary" if activity == "Aerobics" else "secondary"):
                    st.session_state["selected_activity"] = "Aerobics"
                    st.rerun()

        activity = st.session_state.get("selected_activity")

        if activity == "Yoga":
            st.markdown("**Days**  \nMonday, Wednesday and Friday\n\n**Timing**  \n7:00 AM – 8:00 AM")
        elif activity == "Zumba":
            st.markdown("**Days**  \nTuesday and Thursday\n\n**Timing**  \n7:00 PM – 8:00 PM")
        elif activity == "Aerobics":
            st.markdown("**Day**  \nSaturday\n\n**Timing**  \n8:00 AM – 9:00 AM")

    # =====================================================
    # TRAINERS
    # =====================================================

    elif st.session_state["selected_category"] == "trainers":
        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">MEET OUR</span> '
            '<span style="color:#B7F34A !important;">TRAINERS</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Meet our fitness professionals and find the right trainer to support your goals.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_trainers"):
            st.session_state["selected_category"] = None
            st.rerun()

        col1, col2, col3 = st.columns(3, gap="large")

        with col1:
            st.image("images/rahul.png", width=150)
            st.markdown("### Rahul Sharma")
            st.write("Personal Trainer")
            st.markdown("**Specialization**  \nStrength Training & Muscle Building\n\n**Experience**  \n6 years\n\n**Availability**  \nMon–Sat, 6:00 AM – 12:00 PM\n\n**Contact**  \n+91-90000-00001")

        with col2:
            st.image("images/priya.png", width=150)
            st.markdown("### Priya Mehta")
            st.write("Personal Trainer")
            st.markdown("**Specialization**  \nFunctional Training & General Fitness\n\n**Experience**  \n4 years\n\n**Availability**  \nMon–Sat, 4:00 PM – 9:00 PM\n\n**Contact**  \n+91-90000-00002")

        with col3:
            st.image("images/arjun.png", width=150)
            st.markdown("### Arjun Patel")
            st.write("Fitness Trainer")
            st.markdown("**Specialization**  \nWeight Management & Cardio Training\n\n**Experience**  \n5 years\n\n**Availability**  \nMon–Sat, 8:00 AM – 2:00 PM\n\n**Contact**  \n+91-90000-00003")

    # =====================================================
    # GYM INFORMATION
    # =====================================================

    elif st.session_state["selected_category"] == "gym_info":
        active_gym = st.session_state["active_gym"]

        st.markdown(
            f'<div class="general-page-header">'
            f'<h1 class="general-page-title">'
            f'<span style="color:#F5F5F5 !important;">{active_gym["name"].upper()}</span> '
            f'<span style="color:#B7F34A !important;">INFO</span>'
            f'</h1>'
            f'<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Facilities, membership pricing, and hours for {active_gym["name"]} ({active_gym["city"]}).'
            f'</p>'
            f'</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_gym_info"):
            st.session_state["selected_category"] = None
            st.rerun()

        info_left, info_center, info_right = st.columns([0.4, 5, 0.4])

        with info_center:
            col1, col2 = st.columns(2, gap="large")

            with col1:
                st.markdown(f"### Timings\n\n**Schedule**  \n{active_gym['timings']}\n\n**Public Holidays**  \nTimings may vary.")
                st.markdown("### Facilities\n\n- Strength training area\n- Cardio section\n- Functional training area\n- Personal training\n- Changing rooms & Lockers")

            with col2:
                st.markdown(f"### Membership\n\n**Standard Plan**  \n{active_gym['monthly_fee']}\n\n- Full gym floor access\n- Group fitness classes\n- AI workout & macro guidance")
                st.markdown(f"### About\n\n{active_gym['name']} in {active_gym['city']} is powered by FitBot AI to streamline member onboarding, personal training bookings, and workout guidance.")