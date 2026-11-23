import os
import time
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client, Client

from gym_data import GYM_DATA
from rag_engine import DEFAULT_KNOWLEDGE_DOCS, embed_texts, retrieve_relevant_context
from agent_graph import build_fitbot_graph
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
# SECRETS & CLIENTS (LOCAL .ENV + STREAMLIT CLOUD)
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


# =========================================================
# SESSION STATE & VECTOR INDEX INITIALIZATION
# =========================================================

if "selected_category" not in st.session_state:
    st.session_state["selected_category"] = None

if "selected_activity" not in st.session_state:
    st.session_state["selected_activity"] = None

if "workout_request" not in st.session_state:
    st.session_state["workout_request"] = None

if "messages" not in st.session_state:
    st.session_state["messages"] = []

if "chat_open" not in st.session_state:
    st.session_state["chat_open"] = False

if "active_gym" not in st.session_state:
    st.session_state["active_gym"] = {
        "name": "FitZone Fitness Club",
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
# HELPER — FETCH BOOKINGS FROM SUPABASE
# =========================================================

def fetch_gym_bookings(gym_name: str) -> list[dict]:
    if not supabase:
        return []
    try:
        res = (
            supabase.table("bookings")
            .select("*")
            .eq("gym_name", gym_name)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


# =========================================================
# SIDEBAR — MULTI-BRANCH SELECTOR & KNOWLEDGE BASE
# =========================================================

with st.sidebar:
    st.markdown("### 🏢 Fitness Club Portal")
    st.caption("Select an active branch or onboard a new location.")

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

    chosen_gym_name = st.selectbox("Active Branch", gym_names, index=default_idx)
    for g in gyms_list:
        if g["name"] == chosen_gym_name:
            st.session_state["active_gym"] = g
            break

    active_gym = st.session_state["active_gym"]
    st.info(
        f"**{active_gym['name']}** — {active_gym['city']}\n\n"
        f"🕒 {active_gym['timings']}\n\n"
        f"💳 Starting at {active_gym['monthly_fee']}"
    )

    with st.expander("➕ Onboard New Branch"):
        new_gym_name = st.text_input("Club Name", placeholder="e.g., Gold's Gym Koregaon Park")
        new_gym_city = st.text_input("City", placeholder="e.g., Pune")
        new_gym_timings = st.text_input("Operating Hours", value="Mon-Sat: 6:00 AM - 10:00 PM")
        new_gym_fee = st.text_input("Base Membership", value="₹1,999/month")

        if st.button("SAVE BRANCH", use_container_width=True):
            if new_gym_name.strip() and new_gym_city.strip():
                new_record = {
                    "name": new_gym_name.strip(),
                    "city": new_gym_city.strip(),
                    "timings": new_gym_timings.strip(),
                    "monthly_fee": new_gym_fee.strip(),
                }
                if supabase:
                    try:
                        supabase.table("gyms").insert(new_record).execute()
                        st.session_state["active_gym"] = new_record
                        st.success(f"{new_gym_name} added successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save branch: {e}")
                else:
                    st.warning("Configure Supabase credentials to persist branches.")

    st.divider()
    st.markdown("### 📚 Policy & Knowledge Store")
    st.caption(f"Active documents indexed: **{len(st.session_state['rag_docs'])}**")

    uploaded_doc = st.file_uploader("Upload Branch Policy (.txt / .md)", type=["txt", "md"])
    if uploaded_doc is not None:
        doc_text = uploaded_doc.read().decode("utf-8").strip()
        if doc_text and not any(d["title"] == uploaded_doc.name for d in st.session_state["rag_docs"]):
            new_doc = {"title": uploaded_doc.name, "content": doc_text}
            st.session_state["rag_docs"].append(new_doc)
            if api_key:
                new_emb = embed_texts(client, [f"{new_doc['title']}: {new_doc['content']}"])[0]
                st.session_state["rag_embeddings"].append(new_emb)
            st.success(f"'{uploaded_doc.name}' indexed and live!")

    st.divider()
    if supabase:
        st.success("🟢 Cloud Database Connected")
    else:
        st.warning("🟡 Cloud Database Offline")


# =========================================================
# AGENTIC TOOLS (MACRO CALCULATOR + SUPABASE BOOKING)
# =========================================================

def calculate_macros(weight_kg: float, goal: str) -> str:
    """Calculates daily calories and macronutrients based on weight in kg and fitness goal (e.g., 'weight loss', 'muscle gain')."""
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
    member_name: str = "Walk-in Member",
    member_phone: str = "Not Provided"
) -> str:
    """Books a personal training session with a specific trainer at a specific time and saves it to the gym's Supabase database."""
    st.session_state["last_tool_used"] = (
        f"book_trainer_session(trainer='{trainer_name}', slot='{time_slot}', member='{member_name}')"
    )
    gym_name = st.session_state["active_gym"]["name"]

    if supabase:
        try:
            supabase.table("bookings").insert({
                "gym_name": gym_name,
                "member_name": member_name,
                "member_phone": member_phone,
                "trainer_name": trainer_name,
                "time_slot": time_slot,
            }).execute()
            return (
                f"Booking confirmed for {member_name} with {trainer_name} at {time_slot} "
                f"({gym_name})."
            )
        except Exception as e:
            return f"Unable to complete booking: {str(e)}"

    return f"Booking confirmed for {member_name} with {trainer_name} at {time_slot}."


# =========================================================
# HELPER — CALL GEMINI WITH RETRY & FALLBACK
# =========================================================

def call_gemini(prompt: str, use_tools: bool = False) -> str:
    if not api_key:
        return "Service configuration error: GEMINI_API_KEY is missing."

    last_error = ""

    for model_name in MODELS:
        config_kwargs = {"temperature": 0.4}

        if use_tools:
            config_kwargs["tools"] = [calculate_macros, book_trainer_session]

        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs)
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
# AGENTIC WORKFLOW — RAG RETRIEVAL + TOOL ROUTING
# =========================================================
def generate_fitbot_response() -> tuple[str, dict]:
    active_gym = st.session_state["active_gym"]
    st.session_state["last_tool_used"] = None

    latest_user_query = ""
    conversation_history = ""

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
        if st.button("CLEAR CHAT", key="end_conversation", use_container_width=True):
            st.session_state["messages"] = []
            st.session_state["chat_open"] = False
            st.session_state["selected_category"] = None
            st.rerun()

    st.markdown(
        f'<div class="chat-page-header">'
        f'<div class="chat-page-title">'
        f'<span style="color:#F5F5F5 !important;">FITBOT</span> '
        f'<span style="color:#B7F34A !important;">AI</span>'
        f'</div>'
        f'<div class="chat-page-divider"></div>'
        f'<div class="chat-page-subtitle">'
        f'{st.session_state["active_gym"]["name"].upper()} • MEMBER CONCIERGE'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("trace"):
                if trace.get("nodes_visited"):
                 st.caption(f"🕸️ **LangGraph Execution Path:** `{' → '.join(trace['nodes_visited'])}`")
                with st.expander("Sources & Actions"):
                    trace = message["trace"]
                    if trace.get("tool_called"):
                        st.success(f"Action Executed: `{trace['tool_called']}`")
                    st.markdown("**Referenced Club Policies:**")
                    for src in trace.get("rag_sources", []):
                        st.markdown(f"- **{src['title']}** (Match: `{src['score']}`): {src['content']}")

    if st.session_state["messages"] and st.session_state["messages"][-1]["role"] == "user":
        with st.chat_message("assistant"):
            with st.spinner("Checking club policies & availability..."):
                assistant_reply, trace = generate_fitbot_response()
            st.markdown(assistant_reply)
            st.caption(f"🕸️ **LangGraph Execution Path:** `{' → '.join(trace['nodes_visited'])}`")
            with st.expander("Sources & Actions"):
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

    user_message = st.chat_input("Ask about memberships, calculate macros, or book a trainer...")

    if user_message:
        st.session_state["messages"].append({"role": "user", "content": user_message})
        st.rerun()


# =========================================================
# MAIN PORTAL
# =========================================================

else:

    # =====================================================
    # HOME SCREEN
    # =====================================================

    if st.session_state["selected_category"] is None:
        show_header()

        active_gym = st.session_state["active_gym"]
        branch_bookings = fetch_gym_bookings(active_gym["name"])

        # Live Branch Status Strip
        m1, m2, m3 = st.columns(3)
        m1.metric("Active Branch", active_gym["city"], active_gym["name"])
        m2.metric("Standard Plan", active_gym["monthly_fee"], "Full Floor Access")
        m3.metric("PT Bookings", f"{len(branch_bookings)}", "Live Synced")

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

        b_space1, b_col1, b_col2, b_space2 = st.columns([0.6, 2, 2, 0.6], gap="medium")
        with b_col1:
            if st.button("📊 BMI & MACROS", key="open_calculator", use_container_width=True):
                st.session_state["selected_category"] = "calculator"
                st.rerun()

        with b_col2:
            if st.button("📋 BOOKINGS & DESK", key="open_bookings", use_container_width=True):
                st.session_state["selected_category"] = "bookings"
                st.rerun()

        st.divider()

        st.markdown(
            """
<div class="fitbot-cta">
    HOW CAN <span>I</span> HELP YOU?
</div>
""",
            unsafe_allow_html=True
        )

        with st.form("home_chat_form", clear_on_submit=True):
            first_message = st.text_input(
                "Ask FitBot",
                placeholder="Ask about memberships, freeze policy, nutrition, or book a trainer...",
                label_visibility="collapsed"
            )

            send_message = st.form_submit_button("START CHAT →", use_container_width=True)

        if send_message and first_message.strip():
            st.session_state["messages"] = [{"role": "user", "content": first_message.strip()}]
            st.session_state["chat_open"] = True
            st.rerun()

    # =====================================================
    # BOOKINGS & FRONT-DESK OPERATIONS
    # =====================================================

    elif st.session_state["selected_category"] == "bookings":
        active_gym = st.session_state["active_gym"]

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">BOOKINGS &</span> '
            '<span style="color:#B7F34A !important;">FRONT DESK</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            f'<p class="general-page-subtitle">'
            f'Live personal training schedule and walk-in booking desk for {active_gym["name"]}.'
            f'</p>'
            '</div>',
            unsafe_allow_html=True
        )

        if st.button("← Back", key="back_from_bookings"):
            st.session_state["selected_category"] = None
            st.rerun()

        bookings_data = fetch_gym_bookings(active_gym["name"])

        k1, k2, k3 = st.columns(3)
        k1.metric("Total Sessions", len(bookings_data))
        k2.metric("Active Trainers", "3")
        k3.metric("Branch", active_gym["city"])

        with st.expander("➕ Log Walk-In / Phone Booking", expanded=False):
            with st.form("walkin_booking_form", clear_on_submit=True):
                wb_col1, wb_col2 = st.columns(2)
                with wb_col1:
                    wb_member = st.text_input("Member Name", placeholder="e.g., Rohan Kulkarni")
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
        if not supabase:
            st.warning("Connect Supabase credentials to view and manage live bookings.")
        elif bookings_data:
            df = pd.DataFrame(bookings_data)
            display_cols = [c for c in ["member_name", "member_phone", "trainer_name", "time_slot", "created_at"] if c in df.columns]
            st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

            csv_bytes = df[display_cols].to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ EXPORT SCHEDULE (CSV)",
                data=csv_bytes,
                file_name=f"{active_gym['name'].lower().replace(' ', '_')}_bookings.csv",
                mime="text/csv",
            )
        else:
            st.info(f"No sessions scheduled yet for **{active_gym['name']}**. Book via chat or use the walk-in form above.")

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
    # WORKOUT PLANS
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
            'Choose your fitness level and let FitBot build a structured workout plan designed for your goals.'
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
                    f"Create a {workout_level} level workout plan for me. "
                    "Make it clear, structured, practical and suitable for a gym member."
                )

        if st.session_state["workout_request"]:
            with st.spinner("Creating your workout plan..."):
                workout_text = call_gemini(st.session_state["workout_request"], use_tools=False)

            st.markdown(
                '<div class="general-page-header" style="margin-top:40px;">'
                '<h2 class="general-page-title" style="font-size:30px;">'
                'YOUR <span>WORKOUT PLAN</span>'
                '</h2>'
                '<div class="general-page-divider"></div>'
                '</div>',
                unsafe_allow_html=True
            )

            result_left, result_center, result_right = st.columns([0.7, 4, 0.7])

            with result_center:
                st.markdown('<div class="workout-result-label">PERSONALIZED TRAINING PROGRAM</div>', unsafe_allow_html=True)
                st.markdown(workout_text)

            st.session_state["workout_request"] = None

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