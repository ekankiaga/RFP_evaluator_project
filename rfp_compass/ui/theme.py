"""RFP Compass visual system."""

import streamlit as st


def apply_theme() -> None:
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
    :root { --ink:#142b2a; --muted:#617673; --teal:#1f6b64; --mint:#d9eee5; --paper:#f7f8f5; --line:#dfe7e3; --amber:#b66a18; --rose:#a54242; }
    html, body, [class*="css"] { font-family:'DM Sans', sans-serif; }
    .stApp { background: radial-gradient(ellipse at 82% 0%, #e4f1eb 0%, transparent 35%), var(--paper); color:var(--ink); }
    .main .block-container { max-width:1440px; padding-top:1.4rem; padding-bottom:3rem; }
    h1,h2,h3 { font-family:'Manrope',sans-serif !important; letter-spacing:-.035em; color:var(--ink); }
    h1 { font-size:2.25rem !important; }
    [data-testid="stSidebar"] { background:#102e2c; }
    [data-testid="stSidebar"] * { color:#ecf5f1 !important; }
    [data-testid="stSidebar"] [data-testid="stRadio"] label { padding:.3rem .15rem; }
    div[data-testid="stMetric"] { background:white; border:1px solid var(--line); padding:.85rem 1rem; border-radius:16px; box-shadow:0 5px 20px #102e2c0a; min-width:0; }
    div[data-testid="stMetricLabel"] { color:var(--muted); }
    div[data-testid="stMetricValue"] { font-size:clamp(1.15rem, 2vw, 1.7rem); overflow-wrap:anywhere; }
    [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"] { overflow-wrap:anywhere; }
    [data-testid="stPlotlyChart"] { width:100%; max-width:100%; }
    [data-testid="stDataFrame"] { width:100%; max-width:100%; }
    [data-testid="stExpander"] summary p { font-weight:600; }
    div.stButton > button, div.stDownloadButton > button { border-radius:10px; border:1px solid #b9cdc5; font-weight:600; transition:all .18s ease; }
    div.stButton > button, div.stDownloadButton > button { min-height:2.55rem; white-space:normal; }
    div.stButton > button:hover, div.stDownloadButton > button:hover { border-color:var(--teal); color:var(--teal); transform:translateY(-1px); box-shadow:0 5px 14px #1f6b6418; }
    div.stButton > button[kind="primary"] { background:var(--teal); border-color:var(--teal); color:white; }
    [data-testid="stExpander"] { background:white; border:1px solid var(--line); border-radius:14px; }
    div[data-testid="stForm"] { background:white; border:1px solid var(--line); padding:1rem; border-radius:16px; }
    .rc-card { background:linear-gradient(145deg,#fff,#fbfcfa); border:1px solid var(--line); border-radius:18px; padding:1.05rem 1.15rem; box-shadow:0 7px 24px #102e2c0b; margin:.25rem 0 .8rem; }
    .rc-kicker { color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.09em; font-weight:700; }
    .rc-title { font-family:'Manrope',sans-serif; color:var(--ink); font-weight:750; font-size:1.12rem; margin:.2rem 0; }
    .rc-muted { color:var(--muted); font-size:.9rem; }
    .rc-chip { display:inline-block; max-width:100%; white-space:normal; overflow-wrap:anywhere; border-radius:999px; padding:.22rem .6rem; font-size:.76rem; font-weight:700; margin:.15rem .15rem .15rem 0; background:#e7f2ee; color:#1d625b; }
    .rc-chip.warn { background:#fff0d9; color:#91510f; } .rc-chip.bad { background:#fbe7e5; color:#9b3636; } .rc-chip.gray { background:#edf0ef; color:#52625e; }
    .rc-score { font-family:'Manrope',sans-serif; font-size:1.6rem; font-weight:800; color:var(--teal); }
    .rc-evidence { border-left:3px solid #51a28a; background:#f0f7f3; padding:.75rem .9rem; border-radius:0 10px 10px 0; color:#304541; }
    .rc-header { display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--line); padding:.2rem 0 .8rem; margin-bottom:1.2rem; }
    @media (max-width: 800px) {
      .main .block-container { padding-left:1rem; padding-right:1rem; }
      h1 { font-size:1.8rem !important; }
      div[data-testid="stMetric"] { padding:.7rem; }
    }
    </style>""", unsafe_allow_html=True)
