import os
import streamlit as st
from dotenv import load_dotenv
from google import genai

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
# GEMINI SETUP
# =========================================================

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=api_key)


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
# HELPER — GENERATE FITBOT RESPONSE
# =========================================================

def generate_fitbot_response():

    conversation_history = ""

    for message in st.session_state["messages"]:

        role = (
            "USER"
            if message["role"] == "user"
            else "FITBOT"
        )

        conversation_history += (
            f"{role}: {message['content']}\n\n"
        )

    prompt = f"""
You are FitBot AI, the virtual gym receptionist and fitness assistant
for FitZone Fitness Club.

GYM INFORMATION:
{GYM_DATA}

CONVERSATION:
{conversation_history}

INSTRUCTIONS:

- Continue the conversation naturally.
- Remember information from earlier messages in this conversation.
- Understand follow-up questions using previous conversation context.

- For FitZone-specific information, use ONLY the provided GYM INFORMATION.
- Never invent gym timings, membership prices, trainer details,
  schedules, facilities, phone numbers or other FitZone information.

- If FitZone-specific information is unavailable, clearly say so.

- You may provide general fitness, exercise and workout guidance.
- Keep workout advice practical and structured.
- Do not unnecessarily repeat information already provided.
- Keep responses friendly, professional and concise.
"""

    try:

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt
        )

        return response.text

    except Exception:

        return (
            "I'm temporarily unable to respond. "
            "Please wait a moment and try again."
        )


# =========================================================
# CHAT SCREEN
# =========================================================

if st.session_state["chat_open"]:

    # -----------------------------------------------------
    # Chat navigation
    # -----------------------------------------------------

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


    # -----------------------------------------------------
    # Chat heading
    # -----------------------------------------------------

      # -----------------------------------------------------
    # Chat heading
    # -----------------------------------------------------

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


    # -----------------------------------------------------
    # Conversation
    # -----------------------------------------------------

    for message in st.session_state["messages"]:

        with st.chat_message(message["role"]):
            st.markdown(message["content"])


    # -----------------------------------------------------
    # Follow-up input
    # -----------------------------------------------------

    user_message = st.chat_input(
        "Ask a follow-up question..."
    )


    if user_message:

        # Save user message
        st.session_state["messages"].append(
            {
                "role": "user",
                "content": user_message
            }
        )

        # Display it
        with st.chat_message("user"):
            st.markdown(user_message)


        # Generate response
        with st.chat_message("assistant"):

            with st.spinner("FitBot is thinking..."):

                assistant_reply = generate_fitbot_response()

            st.markdown(assistant_reply)


        # Save assistant response
        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": assistant_reply
            }
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


        # ---------------------------------------------
        # Category navigation
        # ---------------------------------------------

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
                {
                    "role": "user",
                    "content": first_message.strip()
                }
            ]

            st.session_state["chat_open"] = True
            st.rerun()


        # =====================================================
    # WORKOUT PLANS
    # =====================================================

    elif st.session_state["selected_category"] == "workout":

        # -------------------------------------------------
# PAGE HEADER
# -------------------------------------------------

        
  
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

        # -------------------------------------------------
        # BACK LINK
        # -------------------------------------------------

        if st.button(
        "← Back",
        key="back_from_workout"
       ):
          st.session_state["selected_category"] = None
          st.session_state["workout_request"] = None
          st.rerun()


        # -------------------------------------------------
        # FITNESS LEVEL
        # -------------------------------------------------

                # -------------------------------------------------
        # WORKOUT FORM
        # -------------------------------------------------

        form_left, form_center, form_right = st.columns(
            [1.2, 3, 1.2]
        )

        with form_center:

            workout_level = st.selectbox(
                "Choose your fitness level",
                [
                    "Beginner",
                    "Intermediate",
                    "Advanced",
                    "Pro"
                ],
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
        

        # -------------------------------------------------
        # GENERATED WORKOUT PLAN
        # -------------------------------------------------

        if st.session_state["workout_request"]:

            with st.spinner(
                "Creating your workout plan..."
            ):

                try:

                    workout_response = (
                        client.models.generate_content(
                            model="gemini-3.6-flash",
                            contents=st.session_state[
                                "workout_request"
                            ]
                        )
                    )


                    # -----------------------------------------
                    # RESULT HEADING
                    # -----------------------------------------

                    st.markdown(
    '<div class="general-page-header" style="margin-top:40px;">'
    '<h2 class="general-page-title" style="font-size:30px;">'
    'YOUR <span>WORKOUT PLAN</span>'
    '</h2>'
    '<div class="general-page-divider"></div>'
    '</div>',
    unsafe_allow_html=True
)
                    

                   # -----------------------------------------
                   # RESULT
                   # -----------------------------------------
                                    # -----------------------------------------
                    # RESULT
                    # -----------------------------------------

                    result_left, result_center, result_right = st.columns(
                        [0.7, 4, 0.7]
                    )

                    with result_center:

                        st.markdown(
                            '<div class="workout-result-label">'
                            'FITBOT GENERATED PLAN'
                            '</div>',
                            unsafe_allow_html=True
                        )

                        st.markdown(
                            workout_response.text
                        )


                except Exception:

                    st.warning(
                        "FitBot is temporarily unable to "
                        "generate your workout plan. "
                        "Please try again shortly."
                    )


            # ---------------------------------------------
            # RESET REQUEST
            # ---------------------------------------------

            st.session_state["workout_request"] = None

        

    # =====================================================
    # ACTIVITIES
    # =====================================================

    
    # =====================================================
    # ACTIVITIES
    # =====================================================

    elif st.session_state["selected_category"] == "activities":

        # -------------------------------------------------
        # PAGE HEADER
        # -------------------------------------------------

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">OUR</span> '
            '<span style="color:#B7F34A !important;">ACTIVITIES</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Explore group fitness sessions designed to keep you active, '
            'energised and consistent.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )


        # -------------------------------------------------
        # BACK LINK
        # -------------------------------------------------

        if st.button(
            "← Back",
            key="back_from_activities"
        ):
            st.session_state["selected_category"] = None
            st.session_state["selected_activity"] = None
            st.rerun()


        # -------------------------------------------------
        # ACTIVITY SELECTOR
        # -------------------------------------------------

        st.markdown(
            '<p class="activity-select-label">CHOOSE AN ACTIVITY</p>',
            unsafe_allow_html=True
        )

        activity = st.session_state.get(
            "selected_activity"
        )

        activity_left, activity_center, activity_right = st.columns(
            [0.7, 4, 0.7]
        )

        with activity_center:

            col1, col2, col3 = st.columns(
                3,
                gap="medium"
            )


            # YOGA
            with col1:

                if st.button(
                    "YOGA",
                    use_container_width=True,
                    key="activity_yoga",
                    type=(
                        "primary"
                        if activity == "Yoga"
                        else "secondary"
                    )
                ):
                    st.session_state["selected_activity"] = "Yoga"
                    st.rerun()


            # ZUMBA
            with col2:

                if st.button(
                    "ZUMBA",
                    use_container_width=True,
                    key="activity_zumba",
                    type=(
                        "primary"
                        if activity == "Zumba"
                        else "secondary"
                    )
                ):
                    st.session_state["selected_activity"] = "Zumba"
                    st.rerun()


            # AEROBICS
            with col3:

                if st.button(
                    "AEROBICS",
                    use_container_width=True,
                    key="activity_aerobics",
                    type=(
                        "primary"
                        if activity == "Aerobics"
                        else "secondary"
                    )
                ):
                    st.session_state["selected_activity"] = "Aerobics"
                    st.rerun()


        # -------------------------------------------------
        # ACTIVITY INFORMATION
        # -------------------------------------------------

        activity = st.session_state.get(
            "selected_activity"
        )


        if activity == "Yoga":

            st.markdown(
                """


**Days**  
Monday, Wednesday and Friday

**Timing**  
7:00 AM – 8:00 AM
                """
            )


        elif activity == "Zumba":

            st.markdown(
                """


**Days**  
Tuesday and Thursday

**Timing**  
7:00 PM – 8:00 PM
                """
            )


        elif activity == "Aerobics":

            st.markdown(
                """


**Day**  
Saturday

**Timing**  
8:00 AM – 9:00 AM
                """
            )


       # =====================================================
    # TRAINERS
    # =====================================================

    elif st.session_state["selected_category"] == "trainers":

        # -------------------------------------------------
        # PAGE HEADER
        # -------------------------------------------------

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">MEET OUR</span> '
            '<span style="color:#B7F34A !important;">TRAINERS</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Meet our fitness professionals and find the right trainer '
            'to support your goals.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )


        # -------------------------------------------------
        # BACK LINK
        # -------------------------------------------------

        if st.button(
            "← Back",
            key="back_from_trainers"
        ):
            st.session_state["selected_category"] = None
            st.rerun()


        # -------------------------------------------------
        # TRAINER CARDS
        # -------------------------------------------------

        col1, col2, col3 = st.columns(
            3,
            gap="large"
        )


        # -------------------------------------------------
        # RAHUL
        # -------------------------------------------------

        with col1:

            st.image(
                "images/rahul.png",
                width=150
            )

            st.markdown(
                "### Rahul Sharma"
            )

            st.write(
                "Personal Trainer"
            )

            st.markdown(
                """
**Specialization**  
Strength Training & Muscle Building

**Experience**  
6 years

**Availability**  
Mon–Sat, 6:00 AM – 12:00 PM

**Contact**  
+91-90000-00001
                """
            )


        # -------------------------------------------------
        # PRIYA
        # -------------------------------------------------

        with col2:

            st.image(
                "images/priya.png",
                width=150
            )

            st.markdown(
                "### Priya Mehta"
            )

            st.write(
                "Personal Trainer"
            )

            st.markdown(
                """
**Specialization**  
Functional Training & General Fitness

**Experience**  
4 years

**Availability**  
Mon–Sat, 4:00 PM – 9:00 PM

**Contact**  
+91-90000-00002
                """
            )


        # -------------------------------------------------
        # ARJUN
        # -------------------------------------------------

        with col3:

            st.image(
                "images/arjun.png",
                width=150
            )

            st.markdown(
                "### Arjun Patel"
            )

            st.write(
                "Fitness Trainer"
            )

            st.markdown(
                """
**Specialization**  
Weight Management & Cardio Training

**Experience**  
5 years

**Availability**  
Mon–Sat, 8:00 AM – 2:00 PM

**Contact**  
+91-90000-00003
                """
            )


        # =====================================================
    # GYM INFORMATION
    # =====================================================

    elif st.session_state["selected_category"] == "gym_info":

        # -------------------------------------------------
        # PAGE HEADER
        # -------------------------------------------------

        st.markdown(
            '<div class="general-page-header">'
            '<h1 class="general-page-title">'
            '<span style="color:#F5F5F5 !important;">GYM</span> '
            '<span style="color:#B7F34A !important;">INFORMATION</span>'
            '</h1>'
            '<div class="general-page-divider"></div>'
            '<p class="general-page-subtitle">'
            'Everything you need to know about FitZone facilities, '
            'services and opening hours.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )


        # -------------------------------------------------
        # BACK LINK
        # -------------------------------------------------

        if st.button(
            "← Back",
            key="back_from_gym_info"
        ):
            st.session_state["selected_category"] = None
            st.rerun()


        # -------------------------------------------------
        # GYM INFORMATION CONTENT
        # -------------------------------------------------

        info_left, info_center, info_right = st.columns(
            [0.4, 5, 0.4]
        )

        with info_center:

            col1, col2 = st.columns(
                2,
                gap="large"
            )


            # ---------------------------------------------
            # LEFT COLUMN
            # ---------------------------------------------

            with col1:

                st.markdown(
                    """
### Timings

**Monday – Saturday**  
6:00 AM – 11:00 PM

**Sunday**  
Closed

**Public Holidays**  
Timings may vary.
                    """
                )


                st.markdown(
                    """
### Facilities

- Strength training area
- Cardio section
- Functional training area
- Personal training
- Changing rooms
- Lockers
                    """
                )


            # ---------------------------------------------
            # RIGHT COLUMN
            # ---------------------------------------------

            with col2:

                st.markdown(
                    """
### Member Services

- Personal training
- Group fitness activities
- Functional training area
- Changing rooms
- Lockers
                    """
                )


                st.markdown(
                    """
### About

FitZone Fitness Club is a modern fitness center offering
strength training, cardio, group fitness activities and
personal training.
                    """
                )