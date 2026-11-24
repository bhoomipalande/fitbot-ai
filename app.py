import calendar
from datetime import date, datetime, timedelta
import hashlib
from io import BytesIO
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

BRANCH_NAMES = ["FitZone Pune", "FitZone Mumbai"]

BRANCH_MONTHLY_BUDGET_INR = {
    "FitZone Pune": 90000,
    "FitZone Mumbai": 135000,
}

PLAN_CATALOG = {
    "Monthly": {"duration_label": "1 Month (30 Days)", "days": 30, "default_fee": 1499},
    "Quarterly Pro": {"duration_label": "3 Months (90 Days)", "days": 90, "default_fee": 3999},
    "Annual Elite": {"duration_label": "12 Months (365 Days)", "days": 365, "default_fee": 12999},
    "Personal Training": {"duration_label": "12 Sessions / 30 Days", "days": 30, "default_fee": 4500},
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
# EXCEL EXPORT & DATE / PAYROLL HELPERS
# =========================================================

def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Report") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
        worksheet = writer.sheets[sheet_name[:31]]
        for idx, col in enumerate(df.columns, 1):
            max_len = max(
                df[col].astype(str).map(len).max() if not df.empty else 10,
                len(str(col))
            ) + 4
            col_letter = worksheet.cell(row=1, column=idx).column_letter
            worksheet.column_dimensions[col_letter].width = min(max_len, 42)
    return output.getvalue()


def parse_iso_date(val) -> date:
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if val:
        try:
            return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
        except Exception:
            pass
    return date.today()


def get_next_salary_due_date(pay_day: int, ref_date: date | None = None) -> date:
    today = ref_date or date.today()
    last_day_this_month = calendar.monthrange(today.year, today.month)[1]
    clamped_day = min(max(int(pay_day or 5), 1), last_day_this_month)
    due_this_month = date(today.year, today.month, clamped_day)
    return due_this_month


def compute_salary_alerts(employees: list[dict]) -> tuple[list[dict], list[dict]]:
    today = date.today()
    upcoming = []
    overdue = []
    for emp in employees:
        if emp.get("role") not in ("trainer", "reception"):
            continue
        if str(emp.get("salary_status", "Pending")).strip().lower() == "paid":
            continue
        pay_day = int(emp.get("salary_pay_day") or parse_iso_date(emp.get("joining_date")).day)
        due_dt = get_next_salary_due_date(pay_day, today)
        delta_days = (due_dt - today).days
        item = {
            "member_id": emp["member_id"],
            "full_name": emp["full_name"],
            "email": emp.get("email", ""),
            "role": emp.get("role", "").title(),
            "gym_name": emp.get("gym_name", ""),
            "salary": float(emp.get("monthly_salary") or 0),
            "due_date": due_dt.strftime("%Y-%m-%d"),
            "delta_days": delta_days,
        }
        if delta_days < 0:
            overdue.append(item)
        elif 0 <= delta_days <= 3:
            upcoming.append(item)
    return upcoming, overdue


def build_mailto_link(to_email: str, subject: str, body: str) -> str:
    params = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{urllib.parse.quote(to_email)}?{params}"


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

if "owner_scope" not in st.session_state:
    st.session_state["owner_scope"] = "Both Branches"

if "salary_mail_queue" not in st.session_state:
    st.session_state["salary_mail_queue"] = []

if "show_member_renew_box" not in st.session_state:
    st.session_state["show_member_renew_box"] = False

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
    today = date.today()
    upcoming_day = min(today.day + 2, 28)

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
            "joining_date": "2024-01-01",
            "monthly_salary": 0,
            "salary_pay_day": 1,
            "salary_status": "Paid",
        },
        # PUNE TEAM: 2 Trainers + 1 Receptionist
        {
            "member_id": "REC-PUN-01",
            "full_name": "Sneha Kulkarni",
            "email": "reception.pune@fitbot.ai",
            "phone_last4": "1111",
            "password_hash": hash_password("RECEP123"),
            "is_activated": True,
            "role": "reception",
            "gym_name": "FitZone Pune",
            "plan_type": "Front Desk Supervisor",
            "joining_date": "2024-06-05",
            "monthly_salary": 18000,
            "salary_pay_day": 5,
            "salary_status": "Paid",
            "last_paid_date": f"{today.year}-{today.month:02d}-05",
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
            "plan_type": "Senior Strength Coach",
            "joining_date": f"2024-04-{upcoming_day:02d}",
            "monthly_salary": 26000,
            "salary_pay_day": upcoming_day,
            "salary_status": "Pending",
        },
        {
            "member_id": "TRN-ARJUN",
            "full_name": "Arjun Patel",
            "email": "arjun@fitbot.ai",
            "phone_last4": "0003",
            "password_hash": hash_password("TRAINER123"),
            "is_activated": True,
            "role": "trainer",
            "gym_name": "FitZone Pune",
            "plan_type": "Cardio & HIIT Coach",
            "joining_date": "2024-09-10",
            "monthly_salary": 22000,
            "salary_pay_day": 10,
            "salary_status": "Paid",
            "last_paid_date": f"{today.year}-{today.month:02d}-10",
        },
        # MUMBAI TEAM: 3 Trainers + 1 Receptionist
        {
            "member_id": "REC-MUM-01",
            "full_name": "Neha Deshmukh",
            "email": "reception.mumbai@fitbot.ai",
            "phone_last4": "2222",
            "password_hash": hash_password("RECEP123"),
            "is_activated": True,
            "role": "reception",
            "gym_name": "FitZone Mumbai",
            "plan_type": "Front Desk Supervisor",
            "joining_date": "2024-05-05",
            "monthly_salary": 21000,
            "salary_pay_day": 5,
            "salary_status": "Paid",
            "last_paid_date": f"{today.year}-{today.month:02d}-05",
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
            "plan_type": "Functional & Mobility Coach",
            "joining_date": f"2024-07-{upcoming_day:02d}",
            "monthly_salary": 28000,
            "salary_pay_day": upcoming_day,
            "salary_status": "Pending",
        },
        {
            "member_id": "TRN-KABIR",
            "full_name": "Kabir Malhotra",
            "email": "kabir@fitbot.ai",
            "phone_last4": "0004",
            "password_hash": hash_password("TRAINER123"),
            "is_activated": True,
            "role": "trainer",
            "gym_name": "FitZone Mumbai",
            "plan_type": "Hypertrophy & Prep Coach",
            "joining_date": "2024-08-12",
            "monthly_salary": 27000,
            "salary_pay_day": 12,
            "salary_status": "Paid",
            "last_paid_date": f"{today.year}-{today.month:02d}-12",
        },
        {
            "member_id": "TRN-ANANYA",
            "full_name": "Ananya Verma",
            "email": "ananya@fitbot.ai",
            "phone_last4": "0005",
            "password_hash": hash_password("TRAINER123"),
            "is_activated": True,
            "role": "trainer",
            "gym_name": "FitZone Mumbai",
            "plan_type": "Pilates & Core Specialist",
            "joining_date": "2025-01-15",
            "monthly_salary": 24000,
            "salary_pay_day": 15,
            "salary_status": "Paid",
            "last_paid_date": f"{today.year}-{today.month:02d}-15",
        },
    ]
    for staff in defaults:
        try:
            existing = get_member_record(staff["member_id"])
            if not existing:
                supabase.table("members").insert(staff).execute()
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


def get_next_sequential_member_id(gym_name: str) -> str:
    prefix = "FZ-MUM-" if "mumbai" in gym_name.lower() else "FZ-PUN-"
    max_num = 1000
    if supabase:
        try:
            res = supabase.table("members").select("member_id").ilike("member_id", f"{prefix}%").execute()
            for row in res.data or []:
                tail = row["member_id"].replace(prefix, "")
                if tail.isdigit():
                    max_num = max(max_num, int(tail))
        except Exception:
            pass
    return f"{prefix}{max_num + 1}"


def fetch_gym_bookings(gym_name: str | None = None, member_filter: str | None = None, trainer_filter: str | None = None) -> list[dict]:
    if not supabase:
        return []
    try:
        query = supabase.table("bookings").select("*")
        if gym_name and gym_name != "Both Branches":
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
        q = supabase.table("members").select("*")
        if gym_name and gym_name != "Both Branches":
            q = q.eq("gym_name", gym_name)
        res = q.order("created_at", desc=False).execute()
        return res.data or []
    except Exception:
        return []


def fetch_payments(gym_name: str | None = None) -> list[dict]:
    if not supabase:
        return []
    try:
        q = supabase.table("payments").select("*")
        if gym_name and gym_name != "Both Branches":
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
        if gym_name and gym_name != "Both Branches":
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
        dt_start = dt_start.replace(hour=19, minute=0, second=0, microsecond=0)

    dt_end = dt_start + timedelta(hours=1)
    fmt = "%Y%m%dT%H%M%S"

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//FitBot AI//Gym Reminder//EN
BEGIN:VEVENT
SUMMARY:Gym Session: {focus} ({gym_name})
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
        "text": f"Gym Session: {focus} ({gym_name})",
        "dates": f"{dt_start.strftime(fmt)}/{dt_end.strftime(fmt)}",
        "details": "Time to hit the gym! 30-minute advance bell enabled via FitBot AI.",
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
        st.error(f"Too many failed attempts. Please wait **{wait_sec} seconds** before trying again.")
        st.stop()

    login_tab, activate_tab = st.tabs(["Login", "ID Activation"])

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
                st.error("Invalid ID. Please check the ID issued by your branch.")
            elif not record.get("is_activated"):
                st.warning(
                    "This ID has not been activated yet. "
                    "Switch to the **ID Activation** tab to verify your details and generate your password."
                )
            elif not verify_password(in_pass, record.get("password_hash")):
                st.session_state["failed_attempts"] += 1
                if st.session_state["failed_attempts"] >= 5:
                    st.session_state["lockout_until"] = time.time() + 60
                    st.session_state["failed_attempts"] = 0
                st.error("Incorrect password.")
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
                st.error("ID not found in our records.")
            elif record.get("is_activated"):
                st.error(
                    "This ID has already been activated. "
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

                        st.success("**Identity Verified! Save your credentials below:**")
                        st.info(
                            f"- **Issued ID:** `{record['member_id']}`\n"
                            f"- **Generated Password:** `{new_plain_pass}`\n"
                            f"- **Branch:** {record['gym_name']}\n\n"
                            f"Switch to the **Login** tab to enter."
                        )
                    except Exception as e:
                        st.error(f"Database error during activation: {e}")
                else:
                    st.session_state["failed_attempts"] += 1
                    st.error("Verification details do not match our records. Please check and try again.")

    st.stop()


# =========================================================
# AUTHENTICATED PORTAL (OWNER, RECEPTION, TRAINER & MEMBER)
# =========================================================

current_user = st.session_state["auth_user"]
user_role = current_user.get("role", "member")
is_owner = user_role == "owner"
is_reception = user_role == "reception"
is_trainer = user_role == "trainer"
is_member = user_role == "member"

# Refresh member record on load so renewal dates stay current
if is_member:
    fresh_rec = get_member_record(current_user["member_id"])
    if fresh_rec:
        current_user = fresh_rec
        st.session_state["auth_user"] = fresh_rec


# =========================================================
# SIDEBAR — ROLE-BASED BRANCH CONTROL & SAVED CHATS
# =========================================================

with st.sidebar:
    if is_owner:
        role_badge = "OWNER EXECUTIVE"
    elif is_reception:
        role_badge = "RECEPTION SUPERVISOR"
    elif is_trainer:
        role_badge = "PT COACH"
    else:
        role_badge = "MEMBER"

    st.markdown(f"### {role_badge}")
    st.caption(f"**{current_user['full_name']}** • ID: `{current_user['member_id']}`")

    if st.button("Log Out", use_container_width=True):
        st.session_state["auth_user"] = None
        st.session_state["messages"] = []
        st.session_state["current_session_id"] = None
        st.session_state["selected_category"] = None
        st.session_state["chat_open"] = False
        st.rerun()

    st.divider()

    if is_owner:
        st.markdown("### Business Scope")
        scope_options = ["FitZone Pune", "FitZone Mumbai", "Both Branches"]
        default_idx = scope_options.index(st.session_state["owner_scope"]) if st.session_state["owner_scope"] in scope_options else 2
        chosen_scope = st.selectbox("Active Scope", scope_options, index=default_idx)
        st.session_state["owner_scope"] = chosen_scope

        if chosen_scope == "Both Branches":
            st.session_state["active_gym"] = {
                "name": "FitZone Pune",
                "city": "Pune & Mumbai",
                "timings": "Mon-Sat: 6:00 AM - 11:00 PM",
                "monthly_fee": "₹1,499 – ₹1,799/month",
            }
            st.info(
                "**All-Access View** — Pune & Mumbai\n\n"
                "**Combined Branches:** 2 Active Clubs\n\n"
                "**Hours:** Mon-Sat: 6:00 AM - 11:00 PM"
            )
        else:
            st.session_state["active_gym"] = fetch_gym_by_name(chosen_scope)
            active_gym = st.session_state["active_gym"]
            st.info(
                f"**{active_gym['name']}** — {active_gym['city']}\n\n"
                f"**Hours:** {active_gym['timings']}\n\n"
                f"**Base Plan:** {active_gym['monthly_fee']}"
            )
    else:
        st.markdown("### Assigned Branch")
        st.session_state["active_gym"] = fetch_gym_by_name(current_user["gym_name"])
        active_gym = st.session_state["active_gym"]
        st.info(
            f"**{active_gym['name']}** — {active_gym['city']}\n\n"
            f"**Hours:** {active_gym['timings']}\n\n"
            f"**Membership:** {active_gym['monthly_fee']}"
        )

    active_gym = st.session_state["active_gym"]

    st.divider()
    st.markdown("### Saved Conversations")
    if st.button("+ New Chat", use_container_width=True):
        st.session_state["messages"] = []
        st.session_state["current_session_id"] = None
        st.session_state["latest_ics"] = None
        st.session_state["chat_open"] = True
        st.rerun()

    saved_sessions = fetch_chat_sessions(active_gym["name"], current_user["member_id"])
    if saved_sessions:
        for sess in saved_sessions:
            display_title = sess["title"].replace(f"[{current_user['member_id']}] ", "")
            if st.button(display_title, key=f"sess_{sess['id']}", use_container_width=True):
                st.session_state["current_session_id"] = sess["id"]
                st.session_state["messages"] = load_session_messages(sess["id"])
                st.session_state["chat_open"] = True
                st.rerun()
    else:
        st.caption("No saved chats yet.")

    if is_owner:
        st.divider()
        st.markdown("### Branch RAG Policies")
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
        "label": f"{workout_focus} — {reminder_date} at {reminder_time} (30-min advance bell)",
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
        f"Gym reminder set for {verified_name} on {reminder_date} at {reminder_time} ({workout_focus}) at {gym['name']}. "
        f"A 30-minute advance alert is configured."
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
        if st.button("+ NEW CHAT", key="end_conversation", use_container_width=True):
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
                        st.caption(f"**StateGraph Execution Path:** `{' → '.join(trace['nodes_visited'])}`")
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
                    st.caption(f"**StateGraph Execution Path:** `{' → '.join(trace['nodes_visited'])}`")
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
        st.info(f"**Workout Reminder Ready:** {rem['label']}")
        r_col1, r_col2 = st.columns(2)
        with r_col1:
            st.download_button(
                "DOWNLOAD CALENDAR INVITE (.ICS)",
                data=rem["ics"],
                file_name="fitbot_gym_reminder.ics",
                mime="text/calendar",
                use_container_width=True,
            )
        with r_col2:
            st.link_button(
                "OPEN GOOGLE CALENDAR",
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

        # -------------------------------------------------
        # 1. OWNER COMMAND CENTER (SCOPE TOGGLE + REAL-TIME KPIS + 3 BUTTONS)
        # -------------------------------------------------
        if is_owner:
            scope_choice = st.radio(
                "Branch Scope",
                ["FitZone Pune", "FitZone Mumbai", "Both Branches"],
                index=["FitZone Pune", "FitZone Mumbai", "Both Branches"].index(st.session_state["owner_scope"]),
                horizontal=True,
                label_visibility="collapsed",
            )
            if scope_choice != st.session_state["owner_scope"]:
                st.session_state["owner_scope"] = scope_choice
                st.rerun()

            all_accounts = fetch_branch_members(scope_choice)
            payments_data = fetch_payments(scope_choice)
            expenses_data = fetch_expenses(scope_choice)

            staff_accounts = [m for m in all_accounts if m.get("role") in ("trainer", "reception")]
            member_accounts = [m for m in all_accounts if m.get("role") == "member"]

            # Automated 2-3 Day Salary Due & Overdue Alerts
            upcoming_sal, overdue_sal = compute_salary_alerts(staff_accounts)
            if overdue_sal or upcoming_sal:
                alert_lines = []
                mail_body_lines = [f"Hello {current_user['full_name']},", "", "Upcoming / Overdue Staff Salary Payouts:"]
                for item in overdue_sal:
                    alert_lines.append(
                        f"- **OVERDUE:** {item['full_name']} ({item['role']} — {item['gym_name']}) • "
                        f"₹{item['salary']:,.0f} (Due: {item['due_date']})"
                    )
                    mail_body_lines.append(f"- OVERDUE: {item['full_name']} ({item['gym_name']}) - INR {item['salary']:,.0f} (Due {item['due_date']})")
                for item in upcoming_sal:
                    day_txt = "Due Today" if item["delta_days"] == 0 else f"Due in {item['delta_days']} day(s)"
                    alert_lines.append(
                        f"- **UPCOMING ({day_txt}):** {item['full_name']} ({item['role']} — {item['gym_name']}) • "
                        f"₹{item['salary']:,.0f} (Pay Date: {item['due_date']})"
                    )
                    mail_body_lines.append(f"- UPCOMING ({day_txt}): {item['full_name']} ({item['gym_name']}) - INR {item['salary']:,.0f} (Pay Date {item['due_date']})")

                st.warning("**SALARY PAYOUT REMINDER**\n\n" + "\n".join(alert_lines))
                reminder_mailto = build_mailto_link(
                    current_user.get("email", "bhoomi@fitbot.ai"),
                    f"FitZone Payroll Alert — {len(overdue_sal) + len(upcoming_sal)} Staff Payout(s) Due",
                    "\n".join(mail_body_lines),
                )
                st.link_button("EMAIL PAYOUT REMINDER TO MY INBOX", url=reminder_mailto)

            # Real-Time KPI Calculation
            total_rev = sum(float(p.get("paid_amount") if p.get("paid_amount") is not None else (p.get("amount_inr") if p.get("status") == "Paid" else 0)) for p in payments_data)
            pending_dues = sum(float(p.get("pending_balance") if p.get("pending_balance") is not None else (p.get("amount_inr") if p.get("status") != "Paid" else 0)) for p in payments_data)
            paid_payroll = sum(float(s.get("monthly_salary") or 0) for s in staff_accounts if str(s.get("salary_status", "")).lower() == "paid")
            facility_exp = sum(float(e.get("amount_inr") or 0) for e in expenses_data)
            total_budget_spent = paid_payroll + facility_exp

            if scope_choice == "Both Branches":
                budget_cap = sum(BRANCH_MONTHLY_BUDGET_INR.values())
            else:
                budget_cap = BRANCH_MONTHLY_BUDGET_INR.get(scope_choice, 90000)

            net_profit = total_rev - total_budget_spent
            activated_members = sum(1 for m in member_accounts if m.get("is_activated"))

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Revenue Collected", f"₹{total_rev:,.0f}", f"Pending: ₹{pending_dues:,.0f}")
            k2.metric("Budget Spent", f"₹{total_budget_spent:,.0f}", f"Cap: ₹{budget_cap:,.0f}")
            k3.metric("Net Profit", f"₹{net_profit:,.0f}", scope_choice)
            k4.metric("Members", f"{len(member_accounts)}", f"{activated_members} Activated")

            if scope_choice == "Both Branches":
                with st.expander("Branch-by-Branch P&L Breakdown (Pune vs. Mumbai)", expanded=False):
                    comp_rows = []
                    for b_name in BRANCH_NAMES:
                        b_pay = [p for p in payments_data if p.get("gym_name") == b_name]
                        b_staff = [s for s in staff_accounts if s.get("gym_name") == b_name]
                        b_exp = [e for e in expenses_data if e.get("gym_name") == b_name]
                        b_mem = [m for m in member_accounts if m.get("gym_name") == b_name]

                        b_rev = sum(float(p.get("paid_amount") if p.get("paid_amount") is not None else (p.get("amount_inr") if p.get("status") == "Paid" else 0)) for p in b_pay)
                        b_due = sum(float(p.get("pending_balance") if p.get("pending_balance") is not None else (p.get("amount_inr") if p.get("status") != "Paid" else 0)) for p in b_pay)
                        b_spent = sum(float(s.get("monthly_salary") or 0) for s in b_staff if str(s.get("salary_status", "")).lower() == "paid") + sum(float(e.get("amount_inr") or 0) for e in b_exp)
                        comp_rows.append({
                            "Branch": b_name,
                            "Members": len(b_mem),
                            "Staff": len(b_staff),
                            "Collected (₹)": b_rev,
                            "Pending Dues (₹)": b_due,
                            "Budget Spent (₹)": b_spent,
                            "Net Profit (₹)": b_rev - b_spent,
                        })
                    st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

        # -------------------------------------------------
        # 2. TRAINER KPI BAR (MINIMAL & FOCUSED)
        # -------------------------------------------------
        elif is_trainer:
            my_pt_sessions = fetch_gym_bookings(active_gym["name"], trainer_filter=current_user["full_name"])
            m1, m2, m3 = st.columns(3)
            m1.metric("Assigned Branch", active_gym["city"], active_gym["name"])
            m2.metric("Active PT Clients", f"{len(my_pt_sessions)}", "Assigned Roster")
            m3.metric("Specialty", current_user.get("plan_type", "PT Coach"), "On Duty")

        # -------------------------------------------------
        # 3. RECEPTION KPI BAR
        # -------------------------------------------------
        elif is_reception:
            branch_members = [m for m in fetch_branch_members(active_gym["name"]) if m.get("role") == "member"]
            branch_payments = fetch_payments(active_gym["name"])
            branch_bookings = fetch_gym_bookings(active_gym["name"])

            rec_collected = sum(float(p.get("paid_amount") if p.get("paid_amount") is not None else (p.get("amount_inr") if p.get("status") == "Paid" else 0)) for p in branch_payments)
            rec_pending = sum(float(p.get("pending_balance") if p.get("pending_balance") is not None else (p.get("amount_inr") if p.get("status") != "Paid" else 0)) for p in branch_payments)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Branch", active_gym["city"], active_gym["name"])
            m2.metric("Members", f"{len(branch_members)}", "Enrolled")
            m3.metric("Collected", f"₹{rec_collected:,.0f}", f"Pending: ₹{rec_pending:,.0f}")
            m4.metric("PT Bookings", f"{len(branch_bookings)}", "Scheduled")

        # -------------------------------------------------
        # 4. MEMBER KPI BAR + 2-DAY PRE-EXPIRY RENEWAL ALERT
        # -------------------------------------------------
        else:
            join_dt = parse_iso_date(current_user.get("joining_date"))
            plan_key = current_user.get("plan_type", "Monthly")
            default_days = PLAN_CATALOG.get(plan_key, PLAN_CATALOG["Monthly"])["days"]
            expiry_dt = parse_iso_date(current_user.get("plan_expiry_date")) if current_user.get("plan_expiry_date") else (join_dt + timedelta(days=default_days))
            days_left = (expiry_dt - date.today()).days

            # 2-Day Advance Expiry Alert & One-Click Renewal
            if days_left <= 2:
                if days_left < 0:
                    st.error(
                        f"**MEMBERSHIP EXPIRED:** Your **{plan_key}** plan expired on **{expiry_dt.strftime('%Y-%m-%d')}** "
                        f"({abs(days_left)} day(s) ago). Renew now to keep uninterrupted gym access."
                    )
                else:
                    due_label = "today" if days_left == 0 else f"in {days_left} day(s)"
                    st.warning(
                        f"**RENEWAL REMINDER:** Your **{plan_key}** membership ends **{due_label}** "
                        f"({expiry_dt.strftime('%Y-%m-%d')}). Renew directly below."
                    )

                if st.button("RENEW MEMBERSHIP NOW", key="trigger_self_renew", use_container_width=True):
                    st.session_state["show_member_renew_box"] = not st.session_state["show_member_renew_box"]

                if st.session_state.get("show_member_renew_box"):
                    with st.form("self_service_renewal_form"):
                        st.markdown("#### Instant Self-Service Membership Renewal")
                        r_c1, r_c2 = st.columns(2)
                        with r_c1:
                            renew_plan = st.selectbox(
                                "Choose Renewal Package",
                                ["Monthly", "Quarterly Pro", "Annual Elite"],
                                format_func=lambda k: f"{k} — {PLAN_CATALOG[k]['duration_label']} (₹{PLAN_CATALOG[k]['default_fee']:,})",
                            )
                        with r_c2:
                            renew_mode = st.selectbox("Payment Method", ["UPI", "Card"])

                        if st.form_submit_button("CONFIRM & PAY RENEWAL", use_container_width=True):
                            if supabase:
                                pkg = PLAN_CATALOG[renew_plan]
                                base_start = max(expiry_dt, date.today())
                                new_expiry = base_start + timedelta(days=pkg["days"])

                                supabase.table("members").update({
                                    "plan_type": renew_plan,
                                    "plan_expiry_date": new_expiry.strftime("%Y-%m-%d"),
                                }).eq("member_id", current_user["member_id"]).execute()

                                supabase.table("payments").insert({
                                    "gym_name": current_user["gym_name"],
                                    "member_id": current_user["member_id"],
                                    "member_name": current_user["full_name"],
                                    "plan_type": renew_plan,
                                    "duration_label": pkg["duration_label"],
                                    "joining_date": date.today().strftime("%Y-%m-%d"),
                                    "base_fee": pkg["default_fee"],
                                    "discount_inr": 0,
                                    "amount_inr": pkg["default_fee"],
                                    "paid_amount": pkg["default_fee"],
                                    "pending_balance": 0,
                                    "payment_mode": renew_mode,
                                    "status": "Paid",
                                }).execute()

                                st.session_state["show_member_renew_box"] = False
                                st.success(
                                    f"Membership renewed! Your **{renew_plan}** plan is now active until **{new_expiry.strftime('%Y-%m-%d')}**."
                                )
                                st.rerun()

            my_bookings = fetch_gym_bookings(active_gym["name"], member_filter=current_user["member_id"])
            my_reminders = fetch_gym_reminders(active_gym["name"], member_filter=current_user["member_id"])
            pt_label = f"{my_bookings[0]['trainer_name']}" if my_bookings else "None"

            m1, m2, m3 = st.columns(3)
            m1.metric("Assigned Branch", active_gym["city"], f"Valid till {expiry_dt.strftime('%d %b %Y')}")
            m2.metric("PT Bookings", f"{len(my_bookings)}", pt_label)
            m3.metric("Reminders", f"{len(my_reminders)}", "30-Min Alert Active")

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

        # -------------------------------------------------
        # ROLE-SPECIFIC ACTION BUTTONS (CLEAN & MINIMAL)
        # -------------------------------------------------
        if is_owner:
            b1, b2, b3 = st.columns(3, gap="small")
            with b1:
                if st.button("EMPLOYEES", key="open_owner_employees", use_container_width=True):
                    st.session_state["selected_category"] = "owner_employees"
                    st.rerun()
            with b2:
                if st.button("MEMBERS", key="open_owner_members", use_container_width=True):
                    st.session_state["selected_category"] = "owner_members"
                    st.rerun()
            with b3:
                if st.button("BOOKINGS", key="open_owner_bookings", use_container_width=True):
                    st.session_state["selected_category"] = "owner_bookings"
                    st.rerun()

        elif is_reception:
            b1, b2, b3 = st.columns(3, gap="small")
            with b1:
                if st.button("MEMBERS & FEES", key="open_rec_register", use_container_width=True):
                    st.session_state["selected_category"] = "reception_register"
                    st.rerun()
            with b2:
                if st.button("BOOKINGS", key="open_bookings", use_container_width=True):
                    st.session_state["selected_category"] = "bookings"
                    st.rerun()
            with b3:
                if st.button("REMINDERS", key="open_reminders", use_container_width=True):
                    st.session_state["selected_category"] = "reminders"
                    st.rerun()

        elif is_trainer:
            b1, b2 = st.columns(2, gap="small")
            with b1:
                if st.button("MY PT CLIENTS", key="open_trainer_hub", use_container_width=True):
                    st.session_state["selected_category"] = "trainer_hub"
                    st.rerun()
            with b2:
                if st.button("MACROS", key="open_calculator", use_container_width=True):
                    st.session_state["selected_category"] = "calculator"
                    st.rerun()

        else:
            b1, b2, b3, b4 = st.columns(4, gap="small")
            with b1:
                if st.button("MY ROUTINE", key="open_my_routine", use_container_width=True):
                    st.session_state["selected_category"] = "my_routine"
                    st.rerun()
            with b2:
                if st.button("MACROS", key="open_calculator", use_container_width=True):
                    st.session_state["selected_category"] = "calculator"
                    st.rerun()
            with b3:
                if st.button("BOOKINGS", key="open_bookings", use_container_width=True):
                    st.session_state["selected_category"] = "bookings"
                    st.rerun()
            with b4:
                if st.button("REMINDERS", key="open_reminders", use_container_width=True):
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
                placeholder="Ask about memberships, book a trainer, or set a 30-min gym reminder...",
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
    # OWNER BUTTON 1: EMPLOYEES (EDITABLE PAYROLL SHEET + .XLSX + AUTO MAIL)
    # =====================================================

    elif st.session_state["selected_category"] == "owner_employees" and is_owner:
        scope = st.session_state["owner_scope"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">EMPLOYEES &</span> '
            '<span style="color:#B7F34A !important;">PAYROLL</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Interactive monthly payroll sheet for {scope}. Edit salaries or status inline and download Excel.'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_owner_emp"):
            st.session_state["selected_category"] = None
            st.rerun()

        # Display auto-generated Salary Credited confirmation emails if any were just paid
        if st.session_state.get("salary_mail_queue"):
            st.success("**Salary Credited Confirmation Mail Ready:**")
            for mail_item in st.session_state["salary_mail_queue"]:
                m_c1, m_c2 = st.columns([3, 1.5])
                with m_c1:
                    st.markdown(
                        f"**{mail_item['name']}** (`{mail_item['email']}`) — "
                        f"₹{mail_item['amount']:,.0f} credited on {mail_item['date']}"
                    )
                with m_c2:
                    st.link_button("SEND PAYSLIP EMAIL", url=mail_item["mailto"], use_container_width=True)
            if st.button("Clear Mail Alerts", key="clear_sal_mails"):
                st.session_state["salary_mail_queue"] = []
                st.rerun()

        all_staff = [m for m in fetch_branch_members(scope) if m.get("role") in ("trainer", "reception")]

        # Hire New Employee Drawer
        with st.expander("+ Add New Employee (Trainer / Receptionist)", expanded=False):
            with st.form("owner_add_emp_form", clear_on_submit=True):
                e1, e2 = st.columns(2)
                with e1:
                    emp_branch = st.selectbox("Assigned Branch", BRANCH_NAMES)
                    emp_role = st.selectbox("Role", ["trainer", "reception"])
                    emp_name = st.text_input("Full Name", placeholder="e.g., Vikram Nair")
                with e2:
                    emp_email = st.text_input("Work Email", placeholder="e.g., vikram@fitbot.ai")
                    emp_phone4 = st.text_input("Last 4 Digits of Phone", max_chars=4, placeholder="e.g., 4512")
                    emp_join = st.date_input("Joining Date", value=date.today())

                s1, s2, s3 = st.columns(3)
                with s1:
                    emp_title = st.text_input("Designation", value="Senior PT Coach")
                with s2:
                    emp_salary = st.number_input("Monthly Salary (₹)", min_value=5000, max_value=200000, value=25000, step=1000)
                with s3:
                    emp_pay_day = st.number_input("Monthly Salary Pay Day (1-28)", min_value=1, max_value=28, value=min(date.today().day, 28))

                if st.form_submit_button("ADD EMPLOYEE TO PAYROLL", use_container_width=True):
                    if emp_name.strip() and emp_email.strip() and len(emp_phone4.strip()) == 4 and supabase:
                        city_code = "MUM" if "mumbai" in emp_branch.lower() else "PUN"
                        role_prefix = "TRN" if emp_role == "trainer" else "REC"
                        new_emp_id = f"{role_prefix}-{city_code}-{secrets.randbelow(899) + 100}"
                        try:
                            supabase.table("members").insert({
                                "member_id": new_emp_id,
                                "full_name": emp_name.strip(),
                                "email": emp_email.strip().lower(),
                                "phone_last4": emp_phone4.strip(),
                                "password_hash": None,
                                "is_activated": False,
                                "role": emp_role,
                                "gym_name": emp_branch,
                                "plan_type": emp_title.strip() or emp_role.title(),
                                "joining_date": emp_join.strftime("%Y-%m-%d"),
                                "monthly_salary": emp_salary,
                                "salary_pay_day": int(emp_pay_day),
                                "salary_status": "Pending",
                            }).execute()
                            st.success(f"Added **{emp_name.strip()}** (`{new_emp_id}`) to {emp_branch}.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Could not save employee: {e}")
                    else:
                        st.warning("Complete all fields including 4 phone digits.")

        # Payroll Summary Strip
        total_payroll = sum(float(s.get("monthly_salary") or 0) for s in all_staff)
        paid_payroll = sum(float(s.get("monthly_salary") or 0) for s in all_staff if str(s.get("salary_status", "")).lower() == "paid")
        pending_payroll = total_payroll - paid_payroll

        p1, p2, p3 = st.columns(3)
        p1.metric("Total Monthly Payroll", f"₹{total_payroll:,.0f}", f"{len(all_staff)} Employees")
        p2.metric("Paid This Month", f"₹{paid_payroll:,.0f}")
        p3.metric("Pending Payout", f"₹{pending_payroll:,.0f}")

        if all_staff:
            sheet_rows = []
            orig_status_map = {}
            for emp in all_staff:
                orig_status_map[emp["member_id"]] = str(emp.get("salary_status") or "Pending")
                pay_day = int(emp.get("salary_pay_day") or parse_iso_date(emp.get("joining_date")).day)
                next_due = get_next_salary_due_date(pay_day).strftime("%Y-%m-%d")
                sheet_rows.append({
                    "Employee ID": emp["member_id"],
                    "Full Name": emp["full_name"],
                    "Branch": emp["gym_name"],
                    "Role": emp["role"].title(),
                    "Designation": emp.get("plan_type", ""),
                    "Joining Date": str(emp.get("joining_date") or date.today().strftime("%Y-%m-%d"))[:10],
                    "Monthly Salary (₹)": float(emp.get("monthly_salary") or 0),
                    "Pay Day": pay_day,
                    "Current Cycle Due": next_due,
                    "Status": emp.get("salary_status") or "Pending",
                    "Last Paid Date": str(emp.get("last_paid_date") or ""),
                    "Email": emp.get("email", ""),
                })

            df_emp = pd.DataFrame(sheet_rows)
            edited_emp = st.data_editor(
                df_emp,
                use_container_width=True,
                hide_index=True,
                disabled=["Employee ID", "Branch", "Role", "Current Cycle Due", "Email"],
                column_config={
                    "Monthly Salary (₹)": st.column_config.NumberColumn(min_value=0, step=500, format="₹%d"),
                    "Pay Day": st.column_config.NumberColumn(min_value=1, max_value=28, step=1),
                    "Status": st.column_config.SelectboxColumn(options=["Pending", "Paid"], required=True),
                },
                key="owner_payroll_editor",
            )

            col_save, col_dl = st.columns(2)
            with col_save:
                if st.button("SAVE SHEET CHANGES", use_container_width=True):
                    if supabase:
                        newly_paid_mails = []
                        today_str = date.today().strftime("%Y-%m-%d")
                        for _, row in edited_emp.iterrows():
                            eid = row["Employee ID"]
                            new_stat = row["Status"]
                            old_stat = orig_status_map.get(eid, "Pending")
                            paid_dt = row["Last Paid Date"]
                            if new_stat == "Paid" and old_stat != "Paid":
                                paid_dt = today_str
                                mail_subj = f"Salary Credited — {date.today().strftime('%B %Y')} ({row['Branch']})"
                                mail_body = (
                                    f"Dear {row['Full Name']},\n\n"
                                    f"Your monthly salary of INR {float(row['Monthly Salary (₹)']):,.0f} for {date.today().strftime('%B %Y')} "
                                    f"({row['Branch']} — {row['Role']}) has been credited on {today_str}.\n\n"
                                    f"Employee ID: {eid}\n"
                                    f"Regards,\nBhoomi Palande\nFitZone Management"
                                )
                                newly_paid_mails.append({
                                    "name": row["Full Name"],
                                    "email": row["Email"],
                                    "amount": float(row["Monthly Salary (₹)"]),
                                    "date": today_str,
                                    "mailto": build_mailto_link(row["Email"], mail_subj, mail_body),
                                })

                            supabase.table("members").update({
                                "full_name": row["Full Name"],
                                "plan_type": row["Designation"],
                                "joining_date": str(row["Joining Date"])[:10],
                                "monthly_salary": float(row["Monthly Salary (₹)"]),
                                "salary_pay_day": int(row["Pay Day"]),
                                "salary_status": new_stat,
                                "last_paid_date": paid_dt if paid_dt else None,
                            }).eq("member_id", eid).execute()

                        if newly_paid_mails:
                            st.session_state["salary_mail_queue"] = newly_paid_mails
                        st.success("Payroll sheet saved and Owner KPIs updated.")
                        st.rerun()

            with col_dl:
                excel_bytes = df_to_excel_bytes(edited_emp, sheet_name="Monthly Payroll")
                st.download_button(
                    "DOWNLOAD PAYROLL (.XLSX)",
                    data=excel_bytes,
                    file_name=f"FitZone_Payroll_{scope.replace(' ', '_')}_{date.today().strftime('%Y_%m')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    # =====================================================
    # OWNER BUTTON 2: MEMBERS (READ-ONLY REVENUE & DURATION AUDIT + .XLSX)
    # =====================================================

    elif st.session_state["selected_category"] == "owner_members" and is_owner:
        scope = st.session_state["owner_scope"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">MEMBERS &</span> '
            '<span style="color:#B7F34A !important;">REVENUE LOG</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Executive read-only audit of all enrolled members, plan durations, and fee balances ({scope}).'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_owner_mem"):
            st.session_state["selected_category"] = None
            st.rerun()

        st.caption("Read-only executive view. Member onboarding, discounts, and installment collections are managed by branch reception.")

        members_list = [m for m in fetch_branch_members(scope) if m.get("role") == "member"]
        payments_list = fetch_payments(scope)
        latest_pay_by_member = {}
        for p in payments_list:
            mid = p.get("member_id")
            if mid and mid not in latest_pay_by_member:
                latest_pay_by_member[mid] = p

        audit_rows = []
        for m in members_list:
            pay = latest_pay_by_member.get(m["member_id"], {})
            plan = m.get("plan_type", "Monthly")
            pkg_meta = PLAN_CATALOG.get(plan, PLAN_CATALOG["Monthly"])
            base_f = float(pay.get("base_fee") or pay.get("amount_inr") or pkg_meta["default_fee"])
            disc_f = float(pay.get("discount_inr") or 0)
            net_f = float(pay.get("amount_inr") or max(base_f - disc_f, 0))
            paid_f = float(pay.get("paid_amount") if pay.get("paid_amount") is not None else (net_f if pay.get("status") == "Paid" else 0))
            pend_f = float(pay.get("pending_balance") if pay.get("pending_balance") is not None else max(net_f - paid_f, 0))

            audit_rows.append({
                "Member ID": m["member_id"],
                "Full Name": m["full_name"],
                "Branch": m["gym_name"],
                "Joining Date": str(m.get("joining_date") or "")[:10],
                "Package": plan,
                "Duration": pay.get("duration_label") or pkg_meta["duration_label"],
                "Expiry Date": str(m.get("plan_expiry_date") or "")[:10],
                "Total Fee (₹)": net_f,
                "Paid Amount (₹)": paid_f,
                "Pending Balance (₹)": pend_f,
                "Payment Status": pay.get("status", "Pending"),
                "Account Activated": "Yes" if m.get("is_activated") else "Pending",
            })

        if audit_rows:
            df_audit = pd.DataFrame(audit_rows)
            st.dataframe(df_audit, use_container_width=True, hide_index=True)

            excel_bytes = df_to_excel_bytes(df_audit, sheet_name="Member Revenue")
            st.download_button(
                "DOWNLOAD MEMBER REVENUE (.XLSX)",
                data=excel_bytes,
                file_name=f"FitZone_Members_{scope.replace(' ', '_')}_{date.today().strftime('%Y_%m_%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.info("No members enrolled in this scope yet.")

    # =====================================================
    # OWNER BUTTON 3: BOOKINGS (READ-ONLY PT WORKLOAD & SCHEDULE)
    # =====================================================

    elif st.session_state["selected_category"] == "owner_bookings" and is_owner:
        scope = st.session_state["owner_scope"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">PT BOOKINGS &</span> '
            '<span style="color:#B7F34A !important;">WORKLOAD</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Personal training session distribution and coach utilization across {scope}.'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_owner_bk"):
            st.session_state["selected_category"] = None
            st.rerun()

        pt_list = fetch_gym_bookings(scope)
        if pt_list:
            df_bk = pd.DataFrame(pt_list)

            st.subheader("Trainer Session Workload")
            workload = (
                df_bk.groupby(["gym_name", "trainer_name"], as_index=False)
                .agg(Active_PT_Sessions=("id", "count"))
                .rename(columns={"gym_name": "Branch", "trainer_name": "Trainer", "Active_PT_Sessions": "Scheduled Sessions"})
            )
            st.dataframe(workload, use_container_width=True, hide_index=True)

            st.subheader("Scheduled PT Sessions")
            cols = [c for c in ["gym_name", "trainer_name", "member_name", "time_slot", "pt_fee_inr"] if c in df_bk.columns]
            st.dataframe(df_bk[cols], use_container_width=True, hide_index=True)
        else:
            st.info("No personal training sessions booked in this scope yet.")

    # =====================================================
    # RECEPTION SUPERVISOR: EDITABLE MEMBER & SPLIT FEE REGISTER (.XLSX)
    # =====================================================

    elif st.session_state["selected_category"] == "reception_register" and is_reception:
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">MEMBER & FEE</span> '
            '<span style="color:#B7F34A !important;">REGISTER</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Enroll members, apply discounts, settle half/partial dues, and export {active_gym["name"]} register.'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_rec_reg"):
            st.session_state["selected_category"] = None
            st.rerun()

        next_seq_id = get_next_sequential_member_id(active_gym["name"])

        with st.expander(f"+ Enroll New Member (Next Sequential ID: {next_seq_id})", expanded=True):
            with st.form("rec_enroll_member_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    m_id_in = st.text_input("Member ID", value=next_seq_id)
                    m_name_in = st.text_input("Full Name", placeholder="e.g., Rohan Kulkarni")
                with c2:
                    m_email_in = st.text_input("Email ID", placeholder="e.g., rohan@gmail.com")
                    m_phone4_in = st.text_input("Last 4 Digits of Phone", max_chars=4, placeholder="e.g., 3210")
                with c3:
                    m_join_in = st.date_input("Joining Date", value=date.today())
                    m_pkg_in = st.selectbox("Package", ["Monthly", "Quarterly Pro", "Annual Elite", "Personal Training"])

                f1, f2, f3, f4 = st.columns(4)
                with f1:
                    m_base_fee = st.number_input("Base Fee (₹)", min_value=500, max_value=100000, value=1499, step=100)
                with f2:
                    m_discount = st.number_input("Discount (₹)", min_value=0, max_value=50000, value=0, step=100)
                with f3:
                    m_paid_now = st.number_input("Paid Now (₹)", min_value=0, max_value=100000, value=1499, step=100)
                with f4:
                    m_pay_mode = st.selectbox("Payment Mode", ["UPI", "Card", "Cash"])

                if st.form_submit_button("ENROLL & RECORD FEE", use_container_width=True):
                    if m_id_in.strip() and m_name_in.strip() and m_email_in.strip() and len(m_phone4_in.strip()) == 4 and supabase:
                        pkg_info = PLAN_CATALOG.get(m_pkg_in, PLAN_CATALOG["Monthly"])
                        net_fee = max(float(m_base_fee) - float(m_discount), 0.0)
                        paid_val = min(float(m_paid_now), net_fee)
                        pending_val = max(net_fee - paid_val, 0.0)
                        pay_stat = "Paid" if pending_val == 0 else ("Partial" if paid_val > 0 else "Pending")
                        expiry_dt = m_join_in + timedelta(days=pkg_info["days"])

                        try:
                            supabase.table("members").insert({
                                "member_id": m_id_in.strip().upper(),
                                "full_name": m_name_in.strip(),
                                "email": m_email_in.strip().lower(),
                                "phone_last4": m_phone4_in.strip(),
                                "password_hash": None,
                                "is_activated": False,
                                "role": "member",
                                "gym_name": active_gym["name"],
                                "plan_type": m_pkg_in,
                                "joining_date": m_join_in.strftime("%Y-%m-%d"),
                                "plan_expiry_date": expiry_dt.strftime("%Y-%m-%d"),
                            }).execute()

                            supabase.table("payments").insert({
                                "gym_name": active_gym["name"],
                                "member_id": m_id_in.strip().upper(),
                                "member_name": m_name_in.strip(),
                                "plan_type": m_pkg_in,
                                "duration_label": pkg_info["duration_label"],
                                "joining_date": m_join_in.strftime("%Y-%m-%d"),
                                "base_fee": float(m_base_fee),
                                "discount_inr": float(m_discount),
                                "amount_inr": net_fee,
                                "paid_amount": paid_val,
                                "pending_balance": pending_val,
                                "payment_mode": m_pay_mode,
                                "status": pay_stat,
                            }).execute()

                            st.success(
                                f"Enrolled **{m_name_in.strip()}** (`{m_id_in.strip().upper()}`) • "
                                f"Net Fee: ₹{net_fee:,.0f} | Paid: ₹{paid_val:,.0f} | Pending: ₹{pending_val:,.0f} ({pay_stat})"
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(f"Could not enroll member: {e}")
                    else:
                        st.warning("Please complete all member details including 4 phone digits.")

        st.subheader(f"Editable Branch Register — {active_gym['name']}")
        st.caption("Edit Discount (₹), Paid Amount (₹), Package, or Payment Mode directly in the sheet to settle half/partial balances.")

        branch_members = [m for m in fetch_branch_members(active_gym["name"]) if m.get("role") == "member"]
        branch_payments = fetch_payments(active_gym["name"])
        pay_lookup = {}
        for p in branch_payments:
            mid = p.get("member_id")
            if mid and mid not in pay_lookup:
                pay_lookup[mid] = p

        if branch_members:
            reg_rows = []
            for m in branch_members:
                pay = pay_lookup.get(m["member_id"], {})
                plan = m.get("plan_type", "Monthly")
                pkg_meta = PLAN_CATALOG.get(plan, PLAN_CATALOG["Monthly"])
                base_f = float(pay.get("base_fee") or pay.get("amount_inr") or pkg_meta["default_fee"])
                disc_f = float(pay.get("discount_inr") or 0)
                net_f = max(base_f - disc_f, 0.0)
                paid_f = float(pay.get("paid_amount") if pay.get("paid_amount") is not None else (net_f if pay.get("status") == "Paid" else 0))
                pend_f = max(net_f - paid_f, 0.0)
                stat_val = "Paid" if pend_f == 0 else ("Partial" if paid_f > 0 else "Pending")

                reg_rows.append({
                    "Payment Row ID": pay.get("id"),
                    "Member ID": m["member_id"],
                    "Full Name": m["full_name"],
                    "Joining Date": str(m.get("joining_date") or date.today().strftime("%Y-%m-%d"))[:10],
                    "Package": plan,
                    "Duration": pkg_meta["duration_label"],
                    "Base Fee (₹)": base_f,
                    "Discount (₹)": disc_f,
                    "Total Fee (₹)": net_f,
                    "Paid Amount (₹)": paid_f,
                    "Pending Balance (₹)": pend_f,
                    "Payment Mode": pay.get("payment_mode") or "UPI",
                    "Status": stat_val,
                    "Account Activated": "Yes" if m.get("is_activated") else "Pending",
                })

            df_reg = pd.DataFrame(reg_rows)
            edited_reg = st.data_editor(
                df_reg.drop(columns=["Payment Row ID"]),
                use_container_width=True,
                hide_index=True,
                disabled=["Member ID", "Duration", "Total Fee (₹)", "Pending Balance (₹)", "Status", "Account Activated"],
                column_config={
                    "Package": st.column_config.SelectboxColumn(options=list(PLAN_CATALOG.keys()), required=True),
                    "Base Fee (₹)": st.column_config.NumberColumn(min_value=0, step=100, format="₹%d"),
                    "Discount (₹)": st.column_config.NumberColumn(min_value=0, step=100, format="₹%d"),
                    "Paid Amount (₹)": st.column_config.NumberColumn(min_value=0, step=100, format="₹%d"),
                    "Payment Mode": st.column_config.SelectboxColumn(options=["UPI", "Card", "Cash"], required=True),
                },
                key="reception_register_editor",
            )

            rc1, rc2 = st.columns(2)
            with rc1:
                if st.button("SAVE REGISTER CHANGES", use_container_width=True):
                    if supabase:
                        for idx, row in edited_reg.iterrows():
                            mid = row["Member ID"]
                            pay_row_id = reg_rows[idx]["Payment Row ID"]
                            pkg_meta = PLAN_CATALOG.get(row["Package"], PLAN_CATALOG["Monthly"])
                            join_dt = parse_iso_date(row["Joining Date"])
                            exp_dt = join_dt + timedelta(days=pkg_meta["days"])

                            net_fee = max(float(row["Base Fee (₹)"]) - float(row["Discount (₹)"]), 0.0)
                            paid_amt = min(float(row["Paid Amount (₹)"]), net_fee)
                            pend_bal = max(net_fee - paid_amt, 0.0)
                            stat_str = "Paid" if pend_bal == 0 else ("Partial" if paid_amt > 0 else "Pending")

                            supabase.table("members").update({
                                "full_name": row["Full Name"],
                                "joining_date": join_dt.strftime("%Y-%m-%d"),
                                "plan_type": row["Package"],
                                "plan_expiry_date": exp_dt.strftime("%Y-%m-%d"),
                            }).eq("member_id", mid).execute()

                            pay_payload = {
                                "gym_name": active_gym["name"],
                                "member_id": mid,
                                "member_name": row["Full Name"],
                                "plan_type": row["Package"],
                                "duration_label": pkg_meta["duration_label"],
                                "joining_date": join_dt.strftime("%Y-%m-%d"),
                                "base_fee": float(row["Base Fee (₹)"]),
                                "discount_inr": float(row["Discount (₹)"]),
                                "amount_inr": net_fee,
                                "paid_amount": paid_amt,
                                "pending_balance": pend_bal,
                                "payment_mode": row["Payment Mode"],
                                "status": stat_str,
                            }
                            if pay_row_id:
                                supabase.table("payments").update(pay_payload).eq("id", pay_row_id).execute()
                            else:
                                supabase.table("payments").insert(pay_payload).execute()

                        st.success("Branch register saved. Pending balances and Owner KPIs updated.")
                        st.rerun()

            with rc2:
                export_df = edited_reg.copy()
                export_df["Total Fee (₹)"] = export_df["Base Fee (₹)"] - export_df["Discount (₹)"]
                export_df["Pending Balance (₹)"] = (export_df["Total Fee (₹)"] - export_df["Paid Amount (₹)"]).clip(lower=0)
                export_df["Status"] = export_df.apply(
                    lambda r: "Paid" if r["Pending Balance (₹)"] == 0 else ("Partial" if r["Paid Amount (₹)"] > 0 else "Pending"),
                    axis=1,
                )
                excel_bytes = df_to_excel_bytes(export_df, sheet_name="Branch Register")
                st.download_button(
                    "DOWNLOAD BRANCH REGISTER (.XLSX)",
                    data=excel_bytes,
                    file_name=f"{active_gym['name'].replace(' ', '_')}_Register_{date.today().strftime('%Y_%m_%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
        else:
            st.info("No members enrolled in this branch yet.")

    # =====================================================
    # TRAINER ONLY: ASSIGNED PT CLIENTS
    # =====================================================

    elif st.session_state["selected_category"] == "trainer_hub" and is_trainer:
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">MY PT</span> '
            '<span style="color:#B7F34A !important;">CLIENTS</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Assigned personal training roster for Coach {current_user["full_name"]} ({active_gym["name"]}).'
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
            st.info("No personal training clients assigned to your schedule yet.")

    # =====================================================
    # MEMBER SMART WORKOUT ROUTINE, CUSTOM BUILDER & ATTENDANCE TRACKER
    # =====================================================

    elif st.session_state["selected_category"] == "my_routine":
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">MY WORKOUT</span> '
            '<span style="color:#B7F34A !important;">PLANNER</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Follow your AI plan or build your own custom routine, track today vs. tomorrow, and log attendance.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_routine"):
            st.session_state["selected_category"] = None
            st.rerun()

        saved_plan = fetch_member_saved_plan(current_user["member_id"])

        preset_tab, custom_tab = st.tabs(["Active Routine & Daily Tracker", "Create / Edit My Custom Plan"])

        with preset_tab:
            if not saved_plan:
                st.info("You do not have an active routine saved yet. Activate a template below or build your own in the next tab:")
                chosen_lvl = st.selectbox("Select Plan Level", ["Beginner", "Intermediate", "Advanced", "Pro"])
                if st.button("ACTIVATE THIS PLAN", use_container_width=True):
                    preview_lines = "\n".join(f"- {line}" for line in WEEKLY_ROUTINE_PREVIEW[chosen_lvl])
                    save_member_plan_record(current_user["member_id"], active_gym["name"], chosen_lvl, preview_lines)
                    st.success(f"{chosen_lvl} routine saved.")
                    st.rerun()
            else:
                lvl = saved_plan["level"]
                if lvl == "Custom":
                    custom_lines = [ln.strip("- ").strip() for ln in saved_plan["plan_text"].splitlines() if ln.strip()]
                    days_list = custom_lines if custom_lines else WEEKLY_ROUTINE_PREVIEW["Beginner"]
                else:
                    days_list = WEEKLY_ROUTINE_PREVIEW.get(lvl, WEEKLY_ROUTINE_PREVIEW["Beginner"])

                comp = int(saved_plan.get("completed_days") or 0)
                missed = int(saved_plan.get("missed_days") or 0)

                today_idx = comp % len(days_list)
                tomorrow_idx = (comp + 1) % len(days_list)

                s1, s2, s3 = st.columns(3)
                s1.metric("Active Plan", lvl, saved_plan.get("last_status", "Active"))
                s2.metric("Completed Days", f"{comp}", "On Track")
                s3.metric("Missed Days", f"{missed}", "Catch-up Needed" if missed > 0 else "Zero Misses")

                st.success(f"**TODAY'S WORKOUT:** {days_list[today_idx]}")
                st.info(f"**TOMORROW'S WORKOUT:** {days_list[tomorrow_idx]}")

                a1, a2, a3 = st.columns(3)
                with a1:
                    if st.button("COMPLETED TODAY", use_container_width=True):
                        supabase.table("member_plans").update({
                            "completed_days": comp + 1,
                            "last_status": "Completed Today",
                        }).eq("member_id", current_user["member_id"]).execute()
                        st.rerun()
                with a2:
                    if st.button("MISSED TODAY", use_container_width=True):
                        supabase.table("member_plans").update({
                            "missed_days": missed + 1,
                            "last_status": "Missed Today — Rescheduled",
                        }).eq("member_id", current_user["member_id"]).execute()
                        st.rerun()
                with a3:
                    if st.button("REMIND TOMORROW 7 PM", use_container_width=True):
                        tmrw = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")
                        msg = set_gym_reminder(tmrw, "19:00", workout_focus=days_list[tomorrow_idx][:45])
                        st.success(msg)

                if st.session_state.get("latest_ics"):
                    rem = st.session_state["latest_ics"]
                    c1, c2 = st.columns(2)
                    with c1:
                        st.download_button(
                            "DOWNLOAD CALENDAR INVITE (.ICS)",
                            data=rem["ics"],
                            file_name="fitbot_workout_alert.ics",
                            mime="text/calendar",
                            use_container_width=True,
                        )
                    with c2:
                        st.link_button("GOOGLE CALENDAR", url=rem["gcal"], use_container_width=True)

                with st.expander("View Full Saved Plan", expanded=True):
                    st.markdown(saved_plan["plan_text"])

        with custom_tab:
            st.markdown("Customize your own 6-day training split and save it to your active daily tracker.")
            with st.form("custom_routine_builder_form"):
                d1 = st.text_input("Day 1 (Monday)", value="Day 1 (Mon): Chest & Triceps — Bench Press, Incline DB, Rope Pushdown")
                d2 = st.text_input("Day 2 (Tuesday)", value="Day 2 (Tue): Back & Biceps — Pull-ups, Barbell Row, Hammer Curls")
                d3 = st.text_input("Day 3 (Wednesday)", value="Day 3 (Wed): Legs & Abs — Squats, Leg Press, Hanging Leg Raises")
                d4 = st.text_input("Day 4 (Thursday)", value="Day 4 (Thu): Shoulders & Traps — Overhead Press, Lateral Raises")
                d5 = st.text_input("Day 5 (Friday)", value="Day 5 (Fri): Upper Body Hypertrophy & Core")
                d6 = st.text_input("Day 6 (Saturday)", value="Day 6 (Sat): Conditioning, Cardio & Mobility")

                if st.form_submit_button("SAVE MY CUSTOM PLAN", use_container_width=True):
                    custom_md = "\n".join(f"- {x.strip()}" for x in [d1, d2, d3, d4, d5, d6] if x.strip())
                    save_member_plan_record(current_user["member_id"], active_gym["name"], "Custom", custom_md)
                    st.success("Your custom plan is saved and active!")
                    st.rerun()

    # =====================================================
    # GYM REMINDERS & 30-MINUTE ADVANCE BELL CENTER
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
            'Schedule workout alerts with a built-in 30-minute advance notification bell (e.g., 6:30 PM alert for a 7:00 PM session).'
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
                rem_time = st.time_input("Workout Time", value=datetime.strptime("19:00", "%H:%M").time())
            with r2:
                rem_focus = st.selectbox(
                    "Workout Focus",
                    ["Full Body Strength", "Upper Body & Core", "Leg Day", "Cardio & HIIT", "Yoga / Mobility"]
                )

            if st.form_submit_button("SET GYM REMINDER (30-MIN ADVANCE BELL)", use_container_width=True):
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
                    "DOWNLOAD CALENDAR INVITE (.ICS)",
                    data=rem["ics"],
                    file_name="fitbot_gym_reminder.ics",
                    mime="text/calendar",
                    use_container_width=True,
                )
            with c2:
                st.link_button(
                    "SYNC WITH GOOGLE CALENDAR",
                    url=rem["gcal"],
                    use_container_width=True,
                )

        st.subheader("Scheduled Workout Reminders")
        member_filter = None if is_reception else current_user["member_id"]
        reminders_list = fetch_gym_reminders(active_gym["name"], member_filter=member_filter)
        if reminders_list:
            df_rem = pd.DataFrame(reminders_list)
            cols = [c for c in ["member_name", "workout_focus", "reminder_date", "reminder_time"] if c in df_rem.columns]
            st.dataframe(df_rem[cols], use_container_width=True, hide_index=True)
        else:
            st.info("No reminders scheduled yet.")

    # =====================================================
    # BOOKINGS & SLOT RESCHEDULING (RECEPTION & MEMBER)
    # =====================================================

    elif st.session_state["selected_category"] == "bookings":
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">PT BOOKINGS &</span> '
            '<span style="color:#B7F34A !important;">SCHEDULE</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Personal training sessions and slot management for {active_gym["name"]}.'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_bookings"):
            st.session_state["selected_category"] = None
            st.rerun()

        member_filter = None if is_reception else current_user["member_id"]
        bookings_data = fetch_gym_bookings(active_gym["name"], member_filter=member_filter)

        branch_trainers = [
            m["full_name"] for m in fetch_branch_members(active_gym["name"]) if m.get("role") == "trainer"
        ] or ["Rahul Sharma", "Priya Mehta", "Arjun Patel"]

        if is_reception:
            with st.expander("+ Book PT Session (Member ID, Trainer & Fixed Fee)", expanded=True):
                with st.form("walkin_booking_form", clear_on_submit=True):
                    wb_col1, wb_col2 = st.columns(2)
                    with wb_col1:
                        wb_mid = st.text_input("Member ID", placeholder="e.g., FZ-PUN-1001")
                        wb_member = st.text_input("Member Full Name", placeholder="e.g., Rohan Kulkarni")
                        wb_phone = st.text_input("Contact Number", placeholder="e.g., +91-98765-43210")
                    with wb_col2:
                        wb_trainer = st.selectbox("Assigned Trainer", branch_trainers)
                        wb_slot = st.text_input("Session Time Slot", placeholder="e.g., Mon-Wed-Fri 7:00 AM")
                        wb_pt_fee = st.number_input("Fixed PT Fee (₹)", min_value=0, max_value=50000, value=4500, step=500)

                    if st.form_submit_button("CONFIRM PT BOOKING", use_container_width=True):
                        if wb_member.strip() and wb_slot.strip() and supabase:
                            tag_name = f"{wb_member.strip()} ({wb_mid.strip().upper()})" if wb_mid.strip() else wb_member.strip()
                            try:
                                supabase.table("bookings").insert({
                                    "gym_name": active_gym["name"],
                                    "member_name": tag_name,
                                    "member_phone": wb_phone.strip() or "Not Provided",
                                    "trainer_name": wb_trainer,
                                    "time_slot": wb_slot.strip(),
                                    "pt_fee_inr": float(wb_pt_fee),
                                }).execute()
                                st.success(f"PT session confirmed for {tag_name} with {wb_trainer}.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Database error: {e}")

        st.subheader("Scheduled Sessions")
        if bookings_data:
            if is_reception:
                st.caption("Edit the Time Slot or Trainer directly in the table below if a member reschedules their PT slot.")
                bk_rows = []
                for b in bookings_data:
                    bk_rows.append({
                        "Booking ID": b["id"],
                        "Member": b.get("member_name", ""),
                        "Trainer": b.get("trainer_name", ""),
                        "Time Slot": b.get("time_slot", ""),
                        "Fixed Fee (₹)": float(b.get("pt_fee_inr") or 0),
                        "Contact": b.get("member_phone", ""),
                    })
                df_bk_edit = pd.DataFrame(bk_rows)
                edited_bk = st.data_editor(
                    df_bk_edit.drop(columns=["Booking ID"]),
                    use_container_width=True,
                    hide_index=True,
                    disabled=["Member", "Fixed Fee (₹)"],
                    column_config={
                        "Trainer": st.column_config.SelectboxColumn(options=branch_trainers, required=True),
                    },
                    key="reception_pt_editor",
                )
                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("SAVE SCHEDULE CHANGES", use_container_width=True):
                        if supabase:
                            for idx, r in edited_bk.iterrows():
                                bid = bk_rows[idx]["Booking ID"]
                                supabase.table("bookings").update({
                                    "trainer_name": r["Trainer"],
                                    "time_slot": r["Time Slot"],
                                    "member_phone": r["Contact"],
                                }).eq("id", bid).execute()
                            st.success("PT schedule updated.")
                            st.rerun()
                with bc2:
                    excel_bk = df_to_excel_bytes(edited_bk, sheet_name="PT Schedule")
                    st.download_button(
                        "DOWNLOAD SCHEDULE (.XLSX)",
                        data=excel_bk,
                        file_name=f"{active_gym['name'].replace(' ', '_')}_PT_Schedule.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
            else:
                df = pd.DataFrame(bookings_data)
                display_cols = [c for c in ["member_name", "trainer_name", "time_slot", "created_at"] if c in df.columns]
                st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
        else:
            st.info("No sessions scheduled yet. Book a trainer via chat or front desk.")

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

            if st.button("SAVE AS MY ACTIVE ROUTINE", use_container_width=True):
                save_member_plan_record(
                    current_user["member_id"],
                    st.session_state["active_gym"]["name"],
                    gen["level"],
                    gen["text"],
                )
                st.success("Saved. Open **MY ROUTINE** from the Home screen to track Today, Tomorrow, and Missed days.")

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