import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import io
import html
import uuid


FMC_URL = "https://trans-logistics-eu.amazon.com/fmc/execution/kKTzE"
SMC_URL = "https://smc-eu-dub.dub.proxy.amazon.com/orders/list/tab/1"
TASK_SHEET_URL = "https://amazongbr.sharepoint.com/sites/AmazonFreightOperations/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FAmazonFreightOperations%2FShared%20Documents%2FFTL%20Scheduling%2FScheduling%2FDaily%20Tasks%20Sheet&viewid=d2bea389%2Dda72%2D4ca8%2D8673%2D77ae91430301"

VRID_COL = "Load #"
SMC_VRID_COL = "VR ID(s)"
SUBCARRIER_COL = "Subcarrier"
CARRIER_REF_COL = "Carrier Reference ID"
EXCLUDE_KEYWORDS = ["enrichment", "test", "pilot", "wepay"]

STEP_LABELS = {1: "1. Upload FMC Data", 2: "2. Copy VRIDs to SMC", 3: "3. Upload SMC Export", 4: "4. Results"}
STEP_COUNT = len(STEP_LABELS)

SESSION_DEFAULTS = {
   "ov_step": 1,
   "ov_fmc_vrids": [],
   "ov_orphan_vrids": [],
   "ov_last_step": None,
}


def _scroll_to_top():
   components.html(
       """
       <script>
         const main = window.parent.document.querySelector('section.main');
         if (main) { main.scrollTo(0,0); }
         window.parent.scrollTo(0,0);
       </script>
       """,
       height=0,
   )


def _render_copy_button(text: str, button_text: str = "Copy"):
   if not text:
       return
   btn_id = f"copy_btn_{uuid.uuid4().hex}"
   text_id = f"copy_text_{uuid.uuid4().hex}"
   safe_text = html.escape(text)
   safe_button_text = html.escape(button_text)
   components.html(
       f"""
       <div style="display:flex; justify-content:flex-end; margin-top:0.25rem; margin-bottom:0.25rem;">
           <textarea id="{text_id}" readonly style="position:absolute; left:-9999px; top:-9999px;">{safe_text}</textarea>
           <button
               id="{btn_id}"
               onclick="
                   const btn = document.getElementById('{btn_id}');
                   const textarea = document.getElementById('{text_id}');
                   const originalText = btn.innerText;
                   const showCopied = () => {{
                       btn.innerText = 'Copied ✓';
                       btn.style.background = '#d1fae5';
                       btn.style.border = '1px solid #10b981';
                       setTimeout(() => {{
                           btn.innerText = originalText;
                           btn.style.background = '#f0f2f6';
                           btn.style.border = '1px solid #999';
                       }}, 1500);
                   }};
                   const showFailed = () => {{
                       btn.innerText = 'Copy failed';
                       btn.style.background = '#fee2e2';
                       btn.style.border = '1px solid #ef4444';
                       setTimeout(() => {{
                           btn.innerText = originalText;
                           btn.style.background = '#f0f2f6';
                           btn.style.border = '1px solid #999';
                       }}, 1500);
                   }};
                   const copyWithFallback = () => {{
                       textarea.focus();
                       textarea.select();
                       try {{
                           const ok = document.execCommand('copy');
                           if (ok) {{ showCopied(); }} else {{ showFailed(); }}
                       }} catch (e) {{ showFailed(); }}
                   }};
                   if (navigator.clipboard && window.isSecureContext) {{
                       navigator.clipboard.writeText(textarea.value)
                           .then(() => showCopied())
                           .catch(() => copyWithFallback());
                   }} else {{
                       copyWithFallback();
                   }}
               "
               style="
                   padding: 0.35rem 0.75rem;
                   border-radius: 0.5rem;
                   border: 1px solid #999;
                   cursor: pointer;
                   background: #f0f2f6;
                   font-size: 0.9rem;
                   font-weight: 500;
                   white-space: nowrap;
               "
           >
               {safe_button_text}
           </button>
       </div>
       """,
       height=45,
   )


def _load_fmc_csv(f) -> pd.DataFrame:
   raw = f.read()
   return pd.read_csv(io.BytesIO(raw), dtype=str)


def _extract_vrids_from_fmc(df: pd.DataFrame) -> tuple[list[str], int]:
   cm = {col.strip(): col for col in df.columns}
   vrid_col = cm.get(VRID_COL)
   if vrid_col is None:
       return [], 0

   # Find exclusion columns by name
   sub_col = cm.get(SUBCARRIER_COL)
   crid_col = cm.get(CARRIER_REF_COL)

   # Build exclusion mask: rows where Subcarrier or Carrier Reference ID contain excluded keywords
   exclude_mask = pd.Series(False, index=df.index)
   for col in [sub_col, crid_col]:
       if col is not None:
           vals = df[col].fillna("").astype(str).str.lower()
           for kw in EXCLUDE_KEYWORDS:
               exclude_mask = exclude_mask | vals.str.contains(kw, na=False)

   excluded_count = int(exclude_mask.sum())
   filtered = df[~exclude_mask]

   vrids = filtered[vrid_col].dropna().astype(str).str.strip().tolist()
   return list(dict.fromkeys([v for v in vrids if v])), excluded_count


def _load_smc_file(f) -> pd.DataFrame:
   raw = f.read()
   if raw[:6] == b"Sheet0" or raw[:5] == b"Sheet":
       df = pd.read_csv(io.BytesIO(raw), sep="\t", dtype=str, skiprows=1)
       if "Unnamed: 0" in df.columns:
           df = df.drop(columns=["Unnamed: 0"])
       return df
   return pd.read_excel(io.BytesIO(raw), dtype=str, engine="openpyxl")


def _extract_smc_vrids(df: pd.DataFrame) -> set[str]:
   cm = {col.strip(): col for col in df.columns}
   col = cm.get(SMC_VRID_COL)
   if col is None:
       return set()
   vrids = set()
   for val in df[col].dropna().astype(str):
       for v in val.split(","):
           v = v.strip()
           if v:
               vrids.add(v)
   return vrids


def _go_back(current_step: int):
   st.session_state.ov_step = max(1, current_step - 1)
   st.rerun()


def _go_to_hub():
   st.session_state.active_audit = "home"
   for key in SESSION_DEFAULTS:
       if key in st.session_state:
           del st.session_state[key]
   st.rerun()


def render():
   for k, v in SESSION_DEFAULTS.items():
       if k not in st.session_state:
           st.session_state[k] = v

   step = st.session_state.ov_step

   if st.session_state.ov_last_step is None:
       st.session_state.ov_last_step = step
   elif step != st.session_state.ov_last_step:
       _scroll_to_top()
       st.session_state.ov_last_step = step

   # Header
   top_left, top_right = st.columns([6, 1])
   with top_left:
       st.title("Orphan VRID Audit")
       st.caption("Amazon Freight Scheduling Team — Identify VRIDs not attached to any active order")
   with top_right:
       st.write("")
       st.write("")
       if st.button("Back to Audit Hub"):
           _go_to_hub()

   st.divider()

   # Progress bar
   pv = (step - 1) / (STEP_COUNT - 1)
   st.progress(pv, text=f"Step {step} of {STEP_COUNT}: {STEP_LABELS[step].split('. ', 1)[1]}")
   st.divider()

   # ── Step 1: Upload FMC CSV ──────────────────────────────────────────
   if step == 1:
       left, right = st.columns([3, 2])
       with left:
           st.header("Step 1 — Upload FMC Data")
       with right:
           st.write("")
           st.write("")
           st.markdown(
               f'<a href="{html.escape(FMC_URL, quote=True)}" target="_blank" '
               f'style="display:inline-block; padding:0.5rem 1.2rem; border-radius:0.5rem; '
               f'border:2px solid #3b82f6; background:rgba(59,130,246,0.12); color:#1d4ed8; '
               f'font-size:1.1rem; font-weight:700; text-decoration:none;">Go to FMC ↗</a>',
               unsafe_allow_html=True,
           )
       st.info(
           "Download the CSV from the FMC filtered view "
           "(ATSExternal + ATSExternalWeb, yesterday to +29 days), then upload it here."
       )

       uploaded = st.file_uploader(
           "Upload FMC CSV export",
           type=["csv"],
           key="ov_fmc_upload",
       )

       if uploaded is not None:
           try:
               df = _load_fmc_csv(uploaded)
               vrids, excluded_count = _extract_vrids_from_fmc(df)
               if not vrids:
                   st.error(f"Could not find a '{VRID_COL}' column or no VRIDs found in the file.")
               else:
                   st.success(f"File loaded: {len(vrids)} unique VRIDs extracted from {len(df)} rows.")
                   st.dataframe(df.head(10), use_container_width=True)
                   st.caption(f"Showing first 10 of {len(df)} rows.")

                   if st.button("Proceed to Step 2 — Copy VRIDs to SMC", type="primary"):
                       st.session_state.ov_fmc_vrids = vrids
                       st.session_state.ov_step = 2
                       st.rerun()
           except Exception as e:
               st.error(f"Error reading file: {e}")

   # ── Step 2: Copy VRIDs to SMC ───────────────────────────────────────
   elif step == 2:
       left, right = st.columns([3, 2])
       with left:
           st.header("Step 2 — Copy VRIDs to SMC")
       with right:
           st.write("")
           st.write("")
           st.markdown(
               f'<a href="{html.escape(SMC_URL, quote=True)}" target="_blank" '
               f'style="display:inline-block; padding:0.5rem 1.2rem; border-radius:0.5rem; '
               f'border:2px solid #3b82f6; background:rgba(59,130,246,0.12); color:#1d4ed8; '
               f'font-size:1.1rem; font-weight:700; text-decoration:none;">Open SMC ↗</a>',
               unsafe_allow_html=True,
           )

       vrids = st.session_state.ov_fmc_vrids
       comma_separated = ",".join(vrids)

       st.info(f"{len(vrids)} VRIDs ready to search in SMC.")
       st.warning(
           "ACTION REQUIRED\n"
           "1. Copy the comma-separated VRIDs below.\n"
           "2. Go to SMC → Orders, set search reference to **VR IDs**.\n"
           "3. Under the order types (e.g. SMC, EDI, WEB etc) tick DIG ensuring its selected as well.\n"
           "4. Paste and search.\n"
           "5. Click **Export** to download the results.\n"
           "6. On this auditing page select: Done - Proceed to Step 3."
       )

       st.code(comma_separated, language=None)
       _render_copy_button(comma_separated, button_text="Copy VRIDs")


       st.divider()
       c1, c2 = st.columns(2)
       with c1:
           if st.button("Back a step"):
               _go_back(2)
       with c2:
           if st.button("Done — Proceed to Step 3", type="primary"):
               st.session_state.ov_step = 3
               st.rerun()

   # ── Step 3: Upload SMC Export ────────────────────────────────────────
   elif step == 3:
       st.header("Step 3 — Upload SMC Export")
       st.info(
           "Upload the SMC export file from your VRID search. "
           "The tool will cross-reference to identify orphan VRIDs."
       )

       uploaded = st.file_uploader(
           "Upload SMC export (.xlsx, .xls, or .csv)",
           type=["xlsx", "xls", "csv"],
           key="ov_smc_upload",
       )

       if uploaded is not None:
           try:
               smc_df = _load_smc_file(uploaded)
               smc_vrids = _extract_smc_vrids(smc_df)

               if not smc_vrids:
                   st.error(
                       f"Could not find a '{SMC_VRID_COL}' column or no VRIDs found in the SMC export."
                   )
               else:
                   st.success(
                       f"SMC export loaded: {len(smc_df)} rows, "
                       f"{len(smc_vrids)} unique VRIDs found."
                   )
                   st.dataframe(smc_df.head(10), use_container_width=True)
                   st.caption(f"Showing first 10 of {len(smc_df)} rows.")

                   fmc_vrids = set(st.session_state.ov_fmc_vrids)
                   orphans = sorted(fmc_vrids - smc_vrids)

                   c1, c2, c3 = st.columns(3)
                   c1.metric("FMC VRIDs", len(fmc_vrids))
                   c2.metric("Found in SMC", len(fmc_vrids - set(orphans)))
                   c3.metric("Orphan VRIDs", len(orphans))

                   if st.button("Produce Final Results", type="primary"):
                       st.session_state.ov_orphan_vrids = orphans
                       st.session_state.ov_step = 4
                       st.rerun()
           except Exception as e:
               st.error(f"Error reading SMC export: {e}")

       st.divider()
       if st.button("Back a step"):
           _go_back(3)

   # ── Step 4: Results ─────────────────────────────────────────────────
   elif step == 4:
       left, right = st.columns([3, 2])
       with left:
           st.header("Step 4 — Orphan VRID Results")
       with right:
           st.write("")
           st.write("")
           st.markdown(
               '<a href="https://amazongbr.sharepoint.com/sites/AmazonFreightOperations/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FAmazonFreightOperations%2FShared%20Documents%2FFTL%20Scheduling%2FScheduling%2FDaily%20Tasks%20Sheet&viewid=d2bea389%2Dda72%2D4ca8%2D8673%2D77ae91430301" target="_blank" '
               'style="display:inline-block; padding:0.5rem 1.2rem; border-radius:0.5rem; '
               'border:2px solid #3b82f6; background:rgba(59,130,246,0.12); color:#1d4ed8; '
               'font-size:1.1rem; font-weight:700; text-decoration:none;">Open Task Sheet ↗</a>',
               unsafe_allow_html=True,
           )
       st.balloons()

       orphans = st.session_state.ov_orphan_vrids
       total_fmc = len(st.session_state.ov_fmc_vrids)
       matched = total_fmc - len(orphans)

       c1, c2, c3 = st.columns(3)
       c1.metric("Total VRIDs Checked", total_fmc)
       c2.metric("Attached to Orders", matched)
       c3.metric("Orphan VRIDs", len(orphans))

       st.divider()

       if orphans:
           orphan_text = "\n".join(orphans)

           left, right = st.columns([6, 1])
           with left:
               st.subheader(f"Orphan VRIDs ({len(orphans)})")
           with right:
               _render_copy_button(orphan_text, button_text="Copy to Task Sheet")

           st.dataframe(
               pd.DataFrame({"Orphan VRID": orphans}).reset_index(drop=True).assign(
                   **{"#": lambda d: d.index + 1}
               )[["#", "Orphan VRID"]],
               use_container_width=True,
           )

           st.divider()
           st.warning(
               "ACTION REQUIRED\n"
               "1. Copy the orphan VRIDs above to the daily task sheet.\n"
               "2. Investigate each VRID following Steps 6–9 of the SOP.\n"
               "Audit identification complete!"
           )
       else:
           st.success("No orphan VRIDs found. All FMC VRIDs are attached to active orders in SMC.")

       st.divider()
       if st.button("Start a New Audit", type="primary"):
           for k in list(SESSION_DEFAULTS.keys()) + ["ov_fmc_upload", "ov_smc_upload"]:
               if k in st.session_state:
                   del st.session_state[k]
           for k, v in SESSION_DEFAULTS.items():
               st.session_state[k] = v
           st.rerun()
