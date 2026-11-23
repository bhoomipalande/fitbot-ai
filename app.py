import os
import time
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

from gym_data import GYM_DATA
from styles import load_css
from ui import show_header, show_categories


# =========================================================
# PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="FitBot AI",
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
# GEMINI SETUP (WORKS LOCALLY & ON STREAMLIT CLOUD)
# =========================================================

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        api_key = None

client = genai.Client(api_key=api_key)

MODELS = [
    "gemini-3.8-flash",
    "gemini-2.5-flash-lite",
]


# =========================================================
# SESSION STATE
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


# =========================================================
# TOOLS
# =========================================================

def calculate_macros(weight_kg: float, goal: str) -> str:
    """Calculates daily calories and macronutrients based on weight in kg and fitness goal (e.g., 'weight loss', 'muscle gain')."""
    if "loss" in goal.lower():
        calories = weight_kg * 22
        protein = weight_kg * 2.0
    else:
        calories = weight_kg * 30
        protein = weight_kg * 2.2

    return f"Target Calories: {calories:.0f} kcal, Protein target: {protein:.0f}g."


def book_trainer_session(trainer_name: str, time_slot: str) -> str:
    """Books a personal training session with a specific trainer at a specific time."""
    return f"Success! Mock session booked with {trainer_name} at {time_slot}."


# =========================================================
# HELPER — CALL GEMINI WITH RETRY & FALLBACK
# =========================================================

def call_gemini(prompt: str, use_tools: bool = False) -> str:
    if not api_key:
        return "API key is missing. Please add GEMINI_API_KEY to your .env file or Streamlit Secrets."

    last_error = ""

    for model_name in MODELS:
        config_kwargs = {"temperature": 0.4}

        if use_tools:
            config_kwargs["tools"] = [calculate_macros, book_trainer_session]

        if "3.8" in model_name or "2.5" in model_name:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

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
                return f"I'm temporarily unable to respond. Error: {last_error}"

    return f"All Gemini models are currently busy. Please try again in a minute. (Last error: {last_error})"


# =========================================================
# HELPER — GENERATE FITBOT RESPONSE
# =========================================================

def generate_fitbot_response():

    conversation_history = ""

    for message in st.session_state["messages"]:
        role = "USER" if message["role"] == "user" else "FITBOT"
        conversation_history += f"{role}: {message['content']}\n\n"

    prompt = f"""
You are FitBot AI, the virtual gym receptionist and fitness assistant
for FitZone Fitness Club.

GYM INFORMATION:
{GYM_DATA}

CONVERSATION:
{conversation_history}

INSTRUCTIONS:
- Continue the conversation naturally and remember earlier messages.
- For FitZone-specific information, use ONLY the provided GYM INFORMATION.
- If the user asks for calorie or macro targets based on their weight, use the calculate_macros tool.
- If the user asks to book a trainer, use the book_trainer_session tool.
- Keep responses friendly, professional, and concise.
"""

    return call_gemini(prompt, use_tools=True)


# =========================================================
# CHAT SCREEN
# =========================================================

if st.session_state["chat_open"]:

    back_col, space_col, end_col = st.columns([1.5, 3, 1.7])

    with back_col:
        if st.button(
            "← BACK TO HOME",
            key="back_from_chat",
            use_container_width=True
        ):
            st.session_state["chat_open"] = False
            st.rerun()

    with end_col:
        if st.button(
            "END CONVERSATION",
            key="end_conversation",
            use_container_width=True
        ):
            st.session_state["messages"] = []
            st.session_state["chat_open"] = False
            st.session_state["selected_category"] = None
            st.rerun()

    st.markdown(
        '<div class="chat-page-header">'
        '<div class="chat-page-title">'
        '<span style="color:#F5F5F5 !important;">FITBOT</span> '
        '<span style="color:#B7F34A !important;">AI</span>'
        '</div>'
        '<div class="chat-page-divider"></div>'
        '<div class="chat-page-subtitle">'
        'YOUR PERSONAL FITNESS ASSISTANT'
        '</div>'
        '</div>',
        unsafe_allow_html=True
    )

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_message = st.chat_input("Ask a follow-up question...")

    if user_message:
        st.session_state["messages"].append(
            {"role": "user", "content": user_message}
        )

        with st.chat_message("user"):
            st.markdown(user_message)

        with st.chat_message("assistant"):
            with st.spinner("FitBot is thinking..."):
                assistant_reply = generate_fitbot_response()
            st.markdown(assistant_reply)

        st.session_state["messages"].append(
            {"role": "assistant", "content": assistant_reply}
        )


# =========================================================
# NORMAL APP
# =========================================================

else:

    # =====================================================
    # HOME SCREEN
    # =====================================================

    if st.session_state["selected_category"] is None:
        show_header()
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

        # New Feature Button
        calc_left, calc_center, calc_right = st.columns([1, 2, 1])
        with calc_center:
            if st.button(
                "📊 BMI & MACRO CALCULATOR",
                key="open_calculator",
                use_container_width=True
            ):
                st.session_state["selected_category"] = "calculator"
                st.rerun()

        # =================================================
        # ASK FITBOT — HOME
        # =================================================

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
                placeholder="Ask about workouts, trainers, activities, gym timings, or fitness...",
                label_visibility="collapsed"
            )

            send_message = st.form_submit_button(
                "START CHAT →",
                use_container_width=True
            )

        if send_message and first_message.strip():
            st.session_state["messages"] = [
                {"role": "user", "content": first_message.strip()}
            ]
            st.session_state["chat_open"] = True
            st.rerun()

    # =====================================================
    # BMI & MACRO CALCULATOR (NEW FEATURE)
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
            weight = st.number_input(
                "Weight (kg)",
                min_value=30.0,
                max_value=200.0,
                value=70.0,
                step=0.5
            )
            height_cm = st.number_input(
                "Height (cm)",
                min_value=120.0,
                max_value=230.0,
                value=170.0,
                step=1.0
            )
            goal = st.selectbox(
                "Fitness Goal",
                ["Weight Loss", "Maintenance", "Muscle Gain"]
            )

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

            if st.button(
                "GET WORKOUT PLAN →",
                key="get_workout_plan",
                use_container_width=True
            ):
                st.session_state["workout_request"] = (
                    f"Create a {workout_level} level workout plan for me. "
                    "Make it clear, structured, practical and suitable "
                    "for a gym member."
                )

        if st.session_state["workout_request"]:
            with st.spinner("Creating your workout plan..."):
                workout_text = call_gemini(
                    st.session_