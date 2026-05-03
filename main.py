import streamlit as st
import importlib
import html

from shared import *

st.set_page_config(page_title='Audit Hub-AF Scheduling', page_icon='🚛', layout='wide')

# ── Audit Registry ──────────────────────────────────────────────────────
# To add a new audit: create audits/<name>.py with a render() function,
# then add an entry here with "render" pointing to the module path.
# Set "render" to None for audits still in development (shows "Coming Soon").
AUDIT_OPTIONS = [
   {"key": "uncovered",        "icon": "📦", "title": "Uncovered Audit",         "status": "LIVE",           "render": "audits.uncovered"},
    {"key": "heavy_bulky",      "icon": "⚖️", "title": "Heavy and Bulky Audit",  "status": "LIVE", "render": "audits.heavy_bulky"},
    {"key": "ncns_prevention",  "icon": "🚷", "title": "NCNS Prevention Audit",  "status": "LIVE", "render": "audits.ncns_prevention"},
    {"key": "orphan_orders",    "icon": "🔍", "title": "Orphan Orders Audit",   "status": "LIVE",           "render": "audits.orphan_orders"},
    {"key": "tms",              "icon": "🖥", "title": "TMS Audit",              "status": "LIVE", "render": "audits.tms"},
   {"key": "orphan_vrid",      "icon": "🧩", "title": "Orphan VRID Audit",       "status": "LIVE",           "render": "audits.orphan_vrid"},
   {"key": "driving_ban",      "icon": "⛔", "title": "Driving Ban Audit",       "status": "IN DEVELOPMENT", "render": None},
    {"key": "fixed_slot",       "icon": "📌", "title": "Fixed Slot Audit",       "status": "IN DEVELOPMENT", "render": None},
   {"key": "infeasible_isa",   "icon": "🚫", "title": "Infeasible ISA Audit",    "status": "IN DEVELOPMENT", "render": None},
    {"key": "tpl_isa",          "icon": "🔗", "title": "3PL ISA Disruptions Audit", "status": "IN DEVELOPMENT", "render": None},
   {"key": "cancelled_orders", "icon": "❌", "title": "Cancelled Orders Audit",  "status": "IN DEVELOPMENT", "render": None},
    {"key": "max_pallet",       "icon": "🏗", "title": "Max Pallet Count Audit", "status": "IN DEVELOPMENT", "render": None},
    {"key": "r4s_cc_azng",      "icon": "📋", "title": "R4S CC + AZNG Audit",    "status": "IN DEVELOPMENT", "render": None},
    {"key": "box_detached",     "icon": "📎", "title": "BOX<>Detached Audit",    "status": "IN DEVELOPMENT", "render": None},
]


# ── Navigation ──────────────────────────────────────────────────────────

def _open_audit(key: str):
   st.session_state.active_audit = key
   st.rerun()


# ── Home Page ───────────────────────────────────────────────────────────

def inject_home_page_styles():
   st.markdown(
       """
       <style>
       html, body, [class*="css"] {
           background: transparent !important;
       }

       .stApp {
           background:
               radial-gradient(circle at top center, rgba(56, 189, 248, 0.10), transparent 28%),
               radial-gradient(circle at 20% 20%, rgba(59, 130, 246, 0.10), transparent 18%),
               radial-gradient(circle at 80% 15%, rgba(14, 165, 233, 0.08), transparent 20%),
               linear-gradient(180deg, #0b1220 0%, #0a0f18 100%);
           color: #e5eefc;
           min-height: 100vh;
       }

       [data-testid="stAppViewContainer"] {
           background:
               radial-gradient(circle at top center, rgba(56, 189, 248, 0.10), transparent 28%),
               radial-gradient(circle at 20% 20%, rgba(59, 130, 246, 0.10), transparent 18%),
               radial-gradient(circle at 80% 15%, rgba(14, 165, 233, 0.08), transparent 20%),
               linear-gradient(180deg, #0b1220 0%, #0a0f18 100%);
           min-height: 100vh;
       }

       [data-testid="stHeader"] {
           background: transparent !important;
       }

       [data-testid="stToolbar"] {
           background: transparent !important;
       }

       header[data-testid="stHeader"] {
           background: transparent !important;
       }

       .home-hero {
           text-align: center;
           padding: 1.25rem 0 1.75rem 0;
           margin-bottom: 0.75rem;
       }

       .home-hero-title {
           font-size: 2.65rem;
           font-weight: 800;
           line-height: 1.1;
           color: #f8fbff;
           margin-bottom: 0.65rem;
           text-shadow: 0 2px 14px rgba(0,0,0,0.35);
       }

       .home-hero-subtitle {
           font-size: 1.05rem;
           color: #d3dfef;
           text-shadow: 0 1px 10px rgba(0,0,0,0.35);
       }

       .home-section-title {
           font-size: 1.9rem;
           font-weight: 800;
           color: #f8fbff;
           text-align: center;
           margin: 0.75rem 0 1.25rem 0;
           text-shadow: 0 1px 10px rgba(0,0,0,0.3);
       }

       .audit-card {
           border: 1px solid rgba(148, 163, 184, 0.16);
           border-radius: 20px;
           padding: 18px 18px 16px 18px;
           min-height: 132px;
           background: linear-gradient(180deg, rgba(20, 28, 40, 0.95) 0%, rgba(15, 23, 33, 0.98) 100%);
           box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
           box-sizing: border-box;
           transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease, background 0.18s ease;
       }

       .audit-card:hover {
           transform: translateY(-4px);
           border-color: rgba(56, 189, 248, 0.45);
           box-shadow: 0 16px 34px rgba(0, 0, 0, 0.34), 0 0 0 1px rgba(56, 189, 248, 0.08);
           background: linear-gradient(180deg, rgba(24, 34, 48, 0.98) 0%, rgba(18, 27, 40, 1) 100%);
       }

       .audit-card-top {
           display: flex;
           justify-content: space-between;
           align-items: flex-start;
           gap: 12px;
           margin-bottom: 0.85rem;
       }

       .audit-card-title-wrap {
           display: flex;
           align-items: center;
           gap: 10px;
           min-width: 0;
       }

       .audit-card-icon {
           font-size: 1.2rem;
           line-height: 1;
           filter: drop-shadow(0 0 6px rgba(56, 189, 248, 0.18));
       }

       .audit-card-title {
           font-size: 1.15rem;
           font-weight: 800;
           line-height: 1.35;
           color: #f8fbff;
       }

       .audit-pill-live {
           padding: 0.26rem 0.72rem;
           border-radius: 999px;
           border: 1px solid #22c55e;
           background: rgba(34, 197, 94, 0.16);
           color: #4ade80;
           font-size: 0.72rem;
           font-weight: 800;
           letter-spacing: 0.02em;
           white-space: nowrap;
       }

       .audit-pill-dev {
           padding: 0.26rem 0.72rem;
           border-radius: 999px;
           border: 1px solid #38bdf8;
           background: rgba(56, 189, 248, 0.14);
           color: #38bdf8;
           font-size: 0.72rem;
           font-weight: 800;
           letter-spacing: 0.02em;
           white-space: nowrap;
       }

       div.stButton > button {
           border-radius: 12px !important;
           font-weight: 700 !important;
       }

       div.stButton > button:disabled {
           background: rgba(255,255,255,0.14) !important;
           color: #f3f7fd !important;
           border: 1px solid rgba(243,247,253,0.22) !important;
           opacity: 1 !important;
       }

       section.main > div.block-container {
           padding-top: 2.2rem;
           padding-bottom: 2rem;
       }
       </style>
       """,
       unsafe_allow_html=True,
   )


def render_home_card(audit: dict):
   icon = audit["icon"]
   title = audit["title"]
   status = audit["status"]
   key = audit["key"]
   active = audit["render"] is not None

   pill_class = "audit-pill-live" if status == "LIVE" else "audit-pill-dev"

   card_html = f"""
   <div class="audit-card">
       <div class="audit-card-top">
           <div class="audit-card-title-wrap">
               <div class="audit-card-icon">{html.escape(icon)}</div>
               <div class="audit-card-title">{html.escape(title)}</div>
           </div>
           <div class="{pill_class}">{html.escape(status)}</div>
       </div>
   </div>
   """

   st.markdown(card_html, unsafe_allow_html=True)

   if active:
       if st.button("Launch Audit", key=f"open_{key}", type="primary", use_container_width=True):
           _open_audit(key)
   else:
       st.button("Coming Soon", key=f"coming_{key}", disabled=True, use_container_width=True)


def render_audit_hub_home():
   inject_home_page_styles()

   st.markdown(
       """
       <div class="home-hero">
           <div class="home-hero-title">AFOPS FTL Scheduling Audit Hub</div>
           <div class="home-hero-subtitle">
               A centralised location for all audit automation tools
           </div>
       </div>
       """,
       unsafe_allow_html=True,
   )

   st.divider()
   st.markdown('<div class="home-section-title">Available Audits</div>', unsafe_allow_html=True)

   cols = st.columns(3)
   for i, audit in enumerate(AUDIT_OPTIONS):
       with cols[i % 3]:
           render_home_card(audit)


# ── Router ──────────────────────────────────────────────────────────────

if "active_audit" not in st.session_state:
   st.session_state.active_audit = "home"

if st.session_state.active_audit == "home":
   render_audit_hub_home()
else:
   audit = next((a for a in AUDIT_OPTIONS if a["key"] == st.session_state.active_audit), None)
   if audit and audit["render"]:
       module = importlib.import_module(audit["render"])
       module.render()
   else:
       render_audit_hub_home()