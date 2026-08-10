import streamlit as st
import base64
from pathlib import Path


def load_css(background="home"):

    # HOME BACKGROUND
    image_path = Path(__file__).parent / "images" / "gym-background.png"

    with open(image_path, "rb") as image_file:
        encoded_image = base64.b64encode(
            image_file.read()
        ).decode()

    # GENERAL BACKGROUND
    general_image_path = Path(__file__).parent / "images" / "general-background.png"

    with open(general_image_path, "rb") as general_image_file:
        encoded_general_image = base64.b64encode(
            general_image_file.read()
        ).decode()

    # CHOOSE BACKGROUND
    if background == "home":
        active_background = encoded_image
    else:
        active_background = encoded_general_image

    # CSS STARTS AFTER THIS
    st.markdown(
        f"""
        <style>

        /* =====================================================
           BRAND COLORS
           ===================================================== */

  :root {{
    --fitbot-lime: #B7F34A;
    --fitbot-lime-hover: #C9FF60;

    --fitbot-white: #F5F5F5;
    --fitbot-text: #D9DDDA;
    --fitbot-grey: #A8AEA9;

    --fitbot-dark: #080B09;
    --fitbot-dark-2: #0D110E;

    --fitbot-card: rgba(10, 14, 11, 0.72);

    --fitbot-border: rgba(255, 255, 255, 0.10);
    --fitbot-lime-border: rgba(183, 243, 74, 0.30);
}}
:root {{
    --fitbot-lime: #B7F34A;
    --fitbot-lime-hover: #C9FF60;

    --fitbot-white: #F5F5F5;
    --fitbot-text: #D9DDDA;
    --fitbot-grey: #A8AEA9;

    --fitbot-dark: #080B09;
    --fitbot-dark-2: #0D110E;

    --fitbot-card: rgba(10, 14, 11, 0.72);

    --fitbot-border: rgba(255, 255, 255, 0.10);
    --fitbot-lime-border: rgba(183, 243, 74, 0.30);
}}


/* =====================================================
   GENERAL INNER PAGE HEADER — FINAL
   ===================================================== */

.general-page-header {{
    text-align: center !important;

    max-width: 760px !important;

    margin:
        12px auto
        30px auto !important;
}}

.general-page-title {{
    margin: 0 !important;

    font-size: 42px !important;
    font-weight: 900 !important;

    line-height: 1.05 !important;

    letter-spacing: 1.2px !important;

    color: var(--fitbot-white) !important;
}}


.general-page-divider {{
    width: 56px !important;
    height: 3px !important;

    margin:
        20px auto
        18px auto !important;

    background: var(--fitbot-lime) !important;

    border-radius: 20px !important;
}}

.general-page-subtitle {{
    max-width: 580px !important;

    margin: 0 auto !important;

    color: var(--fitbot-grey) !important;

    font-size: 15px !important;
    font-weight: 450 !important;

    line-height: 1.55 !important;

    text-align: center !important;
}}

 /* =====================================
   MAIN BACKGROUND
   ===================================== */

.stApp {{
    ...
}}
        /* =====================================================
           APP BACKGROUND
           ===================================================== */

        .stApp {{
            background-image:
                linear-gradient(
                    rgba(3, 5, 4, 0.22),
                    rgba(3, 5, 4, 0.43)
                ),
                url("data:image/png;base64,{active_background}");

            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            background-attachment: fixed;

            color: var(--fitbot-white);
        }}


        /* =====================================================
           MAIN PAGE WIDTH
           ===================================================== */

        .block-container {{
            max-width: 920px !important;

            padding-top: 3rem !important;
            padding-bottom: 3rem !important;

            padding-left: 2rem !important;
            padding-right: 2rem !important;
        }}
        /* =====================================================
   INNER PAGE VERTICAL SPACING
   ===================================================== */

.general-page-header {{
    padding-top: 10vh !important;
    margin-bottom: 28px !important;
}}


        /* =====================================================
           HOME BRANDING
           FITBOT = WHITE
           AI = LIME
           ===================================================== */

        .fitbot-title {{
            text-align: center !important;

            font-size: 50px !important;
            font-weight: 900 !important;

            line-height: 1 !important;

            letter-spacing: 1.5px !important;

            color: var(--fitbot-white) !important;

            margin-top: 8px !important;
            margin-bottom: 12px !important;

            text-shadow:
                0 4px 18px rgba(0, 0, 0, 0.35);
        }}
        .fitbot-title span:first-child {{
            color: #F5F7F5 !important;
        }}

        .fitbot-title span:last-child {{
            color: #B7F34A !important;
        }}

        


        /* =====================================================
           HOME SUBTITLE
           ===================================================== */

        .fitbot-subtitle {{
            text-align: center !important;

            color: #D0D5D0 !important;

            font-size: 16px !important;
            font-weight: 600 !important;

            letter-spacing: 0.4px !important;

            line-height: 1.4 !important;

            margin-top: 0 !important;
            margin-bottom: 32px !important;

            position: static !important;
            transform: none !important;
        }}


        /* =====================================================
           STANDARD TEXT
           ===================================================== */

        h1,
        h2,
        h3,
        h4 {{
            color: var(--fitbot-white) !important;
        }}

        p,
        li {{
            color: var(--fitbot-text);
            line-height: 1.6;
        }}

        strong {{
            color: var(--fitbot-white);
        }}


        /* =====================================================
           GENERAL STREAMLIT BUTTON
           ===================================================== */

        .stButton > button {{
            width: 100%;

            min-height: 48px;

            background:
                linear-gradient(
                    145deg,
                    rgba(17, 21, 17, 0.95),
                    rgba(7, 10, 8, 0.97)
                );

            color: var(--fitbot-white);

            border:
                1px solid var(--fitbot-border);

            border-radius: 10px;

            font-size: 14px;
            font-weight: 700;

            letter-spacing: 0.5px;

            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);

            transition:
                transform 0.2s ease,
                border-color 0.2s ease,
                color 0.2s ease,
                background 0.2s ease,
                box-shadow 0.2s ease;
        }}

        .stButton > button:hover {{
            color: var(--fitbot-lime);

            border-color: var(--fitbot-lime);

            background:
                rgba(183, 243, 74, 0.07);

            transform: translateY(-2px);

            box-shadow:
                0 9px 26px rgba(0, 0, 0, 0.30);
        }}


        /* =====================================================
           HOME 2 x 2 CATEGORY GRID
           ===================================================== */

        .st-key-home_workout button,
        .st-key-home_activities button,
        .st-key-home_trainers button,
        .st-key-home_gym_info button {{

            min-height: 64px !important;

            border-radius: 13px !important;

            font-size: 14px !important;
            font-weight: 800 !important;

            letter-spacing: 0.7px !important;

            color: #E7EAE7 !important;

            border:
                1px solid rgba(183, 243, 74, 0.28) !important;

            background:
                linear-gradient(
                    145deg,
                    rgba(16, 21, 17, 0.94),
                    rgba(7, 10, 8, 0.97)
                ) !important;

            box-shadow:
                0 9px 26px rgba(0, 0, 0, 0.22) !important;
        }}


        .st-key-home_workout button:hover,
        .st-key-home_activities button:hover,
        .st-key-home_trainers button:hover,
        .st-key-home_gym_info button:hover {{

            color: var(--fitbot-lime) !important;

            border-color:
                rgba(183, 243, 74, 0.75) !important;

            background:
                linear-gradient(
                    145deg,
                    rgba(183, 243, 74, 0.10),
                    rgba(8, 12, 9, 0.97)
                ) !important;

            transform:
                translateY(-2px);

            box-shadow:
                0 12px 30px rgba(0, 0, 0, 0.30),
                0 0 18px rgba(183, 243, 74, 0.05) !important;
        }}


        /* =====================================================
           SELECTED CATEGORY
           ===================================================== */

        button[kind="primary"] {{
            background:
                rgba(183, 243, 74, 0.12) !important;

            color:
                var(--fitbot-lime) !important;

            border-color:
                var(--fitbot-lime) !important;

            font-weight:
                850 !important;
        }}


        /* =====================================================
           DIVIDER
           ===================================================== */

        hr {{
            max-width: 620px;

            margin:
                30px auto
                26px auto !important;

            border: none !important;

            border-top:
                1px solid rgba(183, 243, 74, 0.18) !important;
        }}


        /* =====================================================
           "HOW CAN I HELP YOU?"
           ===================================================== */

        .fitbot-cta {{
            max-width: 620px;

            margin:
                0 auto
                15px auto;

            text-align: left;

            color:
                var(--fitbot-white);

            font-size:
                20px;

            font-weight:
                900;

            letter-spacing:
                1px;
        }}

        .fitbot-cta span {{
            color:
                var(--fitbot-lime);
        }}


        /* =====================================================
           HOME CHAT FORM CONTAINER
           ===================================================== */

        [data-testid="stForm"] {{
            max-width:
                620px !important;

            margin-left:
                auto !important;

            margin-right:
                auto !important;

            padding:
                12px !important;

            background:
                linear-gradient(
                    145deg,
                    rgba(10, 14, 11, 0.88),
                    rgba(5, 8, 6, 0.91)
                ) !important;

            border:
                1px solid rgba(183, 243, 74, 0.18) !important;

            border-radius:
                14px !important;

            box-shadow:
                0 12px 32px rgba(0, 0, 0, 0.25);

            backdrop-filter:
                blur(14px);

            -webkit-backdrop-filter:
                blur(14px);
        }}


        /* =====================================================
           HOME CHAT TEXT INPUT
           ===================================================== */

        [data-testid="stForm"] .stTextInput input {{
            min-height:
                52px !important;

            background:
                rgba(5, 8, 6, 0.93) !important;

            border:
                1px solid rgba(183, 243, 74, 0.27) !important;

            border-radius:
                10px !important;

            color:
                var(--fitbot-white) !important;

            font-size:
                14px !important;

            padding-left:
                17px !important;

            padding-right:
                17px !important;

            box-shadow:
                none !important;
        }}

        [data-testid="stForm"] .stTextInput input:hover {{
            border-color:
                rgba(183, 243, 74, 0.50) !important;
        }}

        [data-testid="stForm"] .stTextInput input:focus {{
            border-color:
                var(--fitbot-lime) !important;

            box-shadow:
                0 0 0 1px
                rgba(183, 243, 74, 0.35) !important;
        }}

        [data-testid="stForm"] .stTextInput input::placeholder {{
            color:
                #858C86 !important;
        }}


        /* =====================================================
           START CHAT BUTTON
           Dark normally — Lime on hover
           ===================================================== */

        [data-testid="stFormSubmitButton"] button {{
            min-height:
                48px !important;

            margin-top:
                4px !important;

            background:
                linear-gradient(
                    145deg,
                    rgba(14, 19, 15, 0.98),
                    rgba(7, 10, 8, 0.99)
                ) !important;

            color:
                var(--fitbot-lime) !important;

            border:
                1px solid rgba(183, 243, 74, 0.52) !important;

            border-radius:
                10px !important;

            font-size:
                13px !important;

            font-weight:
                850 !important;

            letter-spacing:
                0.9px !important;

            box-shadow:
                none !important;
        }}

        [data-testid="stFormSubmitButton"] button:hover {{
            background:
                var(--fitbot-lime) !important;

            color:
                #080A09 !important;

            border-color:
                var(--fitbot-lime) !important;

            transform:
                translateY(-1px);

            box-shadow:
                0 7px 22px
                rgba(183, 243, 74, 0.16) !important;
        }}


        /* =====================================================
           OTHER TEXT INPUTS
           ===================================================== */

        .stTextInput input {{
            background:
                rgba(9, 12, 10, 0.94) !important;

            color:
                var(--fitbot-white) !important;

            border:
                1px solid var(--fitbot-border) !important;

            border-radius:
                10px !important;
        }}


        /* =====================================================
           INFORMATION CARDS
           ===================================================== */

        .fitbot-card {{
            background:
                linear-gradient(
                    145deg,
                    rgba(18, 22, 18, 0.93),
                    rgba(8, 11, 9, 0.91)
                );

            border:
                1px solid rgba(183, 243, 74, 0.16);

            border-radius:
                14px;

            padding:
                22px;

            margin-bottom:
                18px;

            backdrop-filter:
                blur(14px);

            -webkit-backdrop-filter:
                blur(14px);

            box-shadow:
                0 12px 32px rgba(0, 0, 0, 0.24);
        }}


        /* =====================================================
           TRAINER IMAGES
           ===================================================== */

        [data-testid="stImage"] {{
            display:
                flex;

            justify-content:
                center;
        }}

        [data-testid="stImage"] img {{
            width:
                150px !important;

            height:
                150px !important;

            object-fit:
                cover !important;

            border-radius:
                50% !important;

            border:
                3px solid var(--fitbot-lime);

            box-shadow:
                0 0 0 5px rgba(183, 243, 74, 0.08),
                0 12px 30px rgba(0, 0, 0, 0.35);

            margin:
                5px auto
                15px auto;
        }}


        /* =====================================================
           CHAT PAGE BRANDING
           ===================================================== */

        .chat-page-header {{
            max-width:
                700px;

            margin:
                10px auto
                26px auto;

            text-align:
                center;
        }}

        .chat-page-title {{
            font-size:
                34px;

            font-weight:
                900;

            letter-spacing:
                1px;

            color:
                var(--fitbot-white);
        }}

        .chat-page-title span {{
            color:
                var(--fitbot-lime);
        }}

        .chat-page-subtitle {{
            margin-top:
                5px;

            color:
                var(--fitbot-grey);

            font-size:
                12px;

            font-weight:
                700;

            letter-spacing:
                1.4px;
        }}


        /* =====================================================
           CHAT MESSAGES
           ===================================================== */

        [data-testid="stChatMessage"] {{
            max-width:
                700px;

            margin-left:
                auto;

            margin-right:
                auto;

            margin-bottom:
                10px;

            background:
                rgba(9, 13, 10, 0.80);

            border:
                1px solid rgba(255, 255, 255, 0.08);

            border-radius:
                14px;

            padding:
                8px 12px;

            backdrop-filter:
                blur(12px);

            -webkit-backdrop-filter:
                blur(12px);
        }}


        /* =====================================================
           CONTINUOUS CHAT INPUT
           ===================================================== */

        [data-testid="stChatInput"] {{
            max-width:
                700px !important;

            margin-left:
                auto !important;

            margin-right:
                auto !important;
        }}

        [data-testid="stChatInput"] textarea {{
            background:
                rgba(8, 12, 9, 0.97) !important;

            color:
                var(--fitbot-white) !important;

            border:
                1px solid rgba(183, 243, 74, 0.30) !important;

            border-radius:
                12px !important;
        }}

        [data-testid="stChatInput"] textarea:focus {{
            border-color:
                var(--fitbot-lime) !important;

            box-shadow:
                0 0 0 1px
                rgba(183, 243, 74, 0.30) !important;
        }}


        /* =====================================================
           SPINNER
           ===================================================== */

        [data-testid="stSpinner"] {{
            color:
                var(--fitbot-lime) !important;
        }}


        /* =====================================================
           FOOTER
           ===================================================== */

        .fitbot-footer {{
            text-align:
                center;

            color:
                #747A75;

            font-size:
                12px;

            letter-spacing:
                0.4px;

            margin-top:
                45px;

            margin-bottom:
                15px;
        }}

        footer {{
            visibility:
                hidden;
        }}


        /* =====================================================
           MOBILE
           ===================================================== */

        @media (max-width: 768px) {{

            .block-container {{
                padding-top:
                    1.5rem !important;

                padding-left:
                    1rem !important;

                padding-right:
                    1rem !important;
            }}

            .fitbot-title {{
                font-size:
                    38px !important;
            }}

            .fitbot-subtitle {{
                font-size:
                    14px !important;

                margin-bottom:
                    25px !important;
            }}

            .fitbot-cta {{
                max-width:
                    100%;

                font-size:
                    18px;
            }}

            [data-testid="stForm"] {{
                max-width:
                    100% !important;
            }}

            [data-testid="stChatMessage"],
            [data-testid="stChatInput"] {{
                max-width:
                    100% !important;
            }}

            [data-testid="stImage"] img {{
                width:
                    125px !important;

                height:
                    125px !important;
            }}
        }}
/* =====================================================
   ALL INNER PAGE BACK LINKS
   ===================================================== */

.st-key-back_from_workout,
.st-key-back_from_activities,
.st-key-back_from_trainers,
.st-key-back_from_gym_info {{
    width: fit-content !important;
}}

.st-key-back_from_workout button,
.st-key-back_from_activities button,
.st-key-back_from_trainers button,
.st-key-back_from_gym_info button {{
    width: auto !important;
    min-height: auto !important;

    padding: 2px 0 !important;

    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;

    box-shadow: none !important;

    color: #5EA1FF !important;

    font-size: 14px !important;
    font-weight: 600 !important;

    text-decoration: underline !important;
    text-decoration-color: #5EA1FF !important;
    text-underline-offset: 4px !important;

    transform: none !important;
}}


/* Streamlit puts button text inside <p> */

.st-key-back_from_workout button p,
.st-key-back_from_activities button p,
.st-key-back_from_trainers button p,
.st-key-back_from_gym_info button p {{
    color: #5EA1FF !important;
    text-decoration: underline !important;
    text-decoration-color: #5EA1FF !important;
    text-underline-offset: 4px !important;
}}


/* Hover */

.st-key-back_from_workout button:hover,
.st-key-back_from_activities button:hover,
.st-key-back_from_trainers button:hover,
.st-key-back_from_gym_info button:hover {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    transform: none !important;
}}

.st-key-back_from_workout button:hover p,
.st-key-back_from_activities button:hover p,
.st-key-back_from_trainers button:hover p,
.st-key-back_from_gym_info button:hover p {{
    color: #8BBCFF !important;
}}
        /* =====================================================
   FINAL GENERAL PAGE TITLE COLORS
   ===================================================== */

.general-page-title {{
    color: #F5F5F5 !important;
}}

.general-page-title span {{
    color: #B7F34A !important;
}}

/* =====================================================
   GENERATED WORKOUT RESULT
   ===================================================== */

.workout-result-label {{
    width: fit-content;

    margin: 30px 0 18px 0;

    padding: 7px 12px;

    color: var(--fitbot-lime);

    background: rgba(183, 243, 74, 0.07);

    border: 1px solid rgba(183, 243, 74, 0.22);
    border-radius: 6px;

    font-size: 11px;
    font-weight: 800;

    letter-spacing: 1.4px;
}}


/* Gemini generated headings */

.stMarkdown h1,
.stMarkdown h2,
.stMarkdown h3 {{
    color: var(--fitbot-white) !important;

    font-weight: 750 !important;

    margin-top: 26px !important;
    margin-bottom: 12px !important;
}}


/* Gemini generated paragraph text */

.stMarkdown p {{
    color: var(--fitbot-text);

    font-size: 15px;

    line-height: 1.7;
}}


/* Gemini lists */

.stMarkdown li {{
    color: var(--fitbot-text);

    line-height: 1.7;

    margin-bottom: 5px;
}}


/* Bold important information */

.stMarkdown strong {{
    color: var(--fitbot-lime) !important;

    font-weight: 700;
}}
/* =====================================================
   CHAT PAGE POLISH
   ===================================================== */

.chat-page-header {{
    text-align: center !important;
    margin: 18px auto 30px auto !important;
}}

.chat-page-title {{
    font-size: 40px !important;
    font-weight: 900 !important;
    letter-spacing: 1.4px !important;
    line-height: 1.05 !important;
}}

.chat-page-divider {{
    width: 48px;
    height: 3px;

    margin: 16px auto 14px auto;

    background: var(--fitbot-lime);
    border-radius: 20px;
}}

.chat-page-subtitle {{
    color: var(--fitbot-grey) !important;

    font-size: 12px !important;
    font-weight: 700 !important;

    letter-spacing: 1.8px !important;
}}


/* Chat message area */

[data-testid="stChatMessage"] {{
    max-width: 760px !important;

    margin-left: auto !important;
    margin-right: auto !important;

    background: rgba(8, 12, 9, 0.68) !important;

    border: 1px solid rgba(255, 255, 255, 0.09) !important;
    border-radius: 14px !important;

    padding: 10px 14px !important;

    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
}}


/* Message text */

[data-testid="stChatMessage"] p {{
    color: var(--fitbot-text) !important;

    font-size: 15px !important;
    line-height: 1.65 !important;
}}


/* Chat input */

[data-testid="stChatInput"] {{
    max-width: 760px !important;

    margin-left: auto !important;
    margin-right: auto !important;
}}
        </style>
        """,
        unsafe_allow_html=True
    )