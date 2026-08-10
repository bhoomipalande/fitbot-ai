import streamlit as st


# =========================================================
# HOME HEADER
# =========================================================
def show_header():
    st.markdown(
        '<h1 class="fitbot-title"><span style="color:#F5F5F5;">FITBOT</span> <span style="color:#B7F34A;">AI</span></h1>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<p class="fitbot-subtitle">Your Virtual Gym Receptionist & Fitness Assistant</p>',
        unsafe_allow_html=True
    )
    

# =========================================================
# HOME CATEGORY GRID
# =========================================================

def show_categories():

    # -------------------------
    # ROW 1
    # -------------------------

    left_space_1, workout_col, activities_col, right_space_1 = st.columns(
        [1.5, 2, 2, 1.5],
        gap="medium"
    )

    with workout_col:
        workout = st.button(
            "WORKOUT PLANS",
            key="home_workout",
            use_container_width=True
        )

    with activities_col:
        activities = st.button(
            "ACTIVITIES",
            key="home_activities",
            use_container_width=True
        )


    # -------------------------
    # ROW 2
    # -------------------------

    left_space_2, trainers_col, gym_col, right_space_2 = st.columns(
        [1.5, 2, 2, 1.5],
        gap="medium"
    )

    with trainers_col:
        trainers = st.button(
            "TRAINERS",
            key="home_trainers",
            use_container_width=True
        )

    with gym_col:
        gym_info = st.button(
            "GYM INFORMATION",
            key="home_gym_info",
            use_container_width=True
        )


    return workout, activities, trainers, gym_info


# =========================================================
# FOOTER
# =========================================================

def show_footer():
    st.markdown(
        """
        <div class="fitbot-footer">
            FITBOT AI &nbsp;•&nbsp; Powered by Google Gemini
        </div>
        """,
        unsafe_allow_html=True
    )