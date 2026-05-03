import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import io
import html
import uuid

from shared import (
  load_smc_file,
  reset_index_display,
  make_copy_block,
  render_inline_copy_button,
  render_table_with_copy,
  scroll_to_top,
)

UNIFIED_PORTAL_URL = "https://unified-portal-eu.corp.amazon.com/#/appointment"
TASK_SHEET_URL = "https://amazongbr.sharepoint.com/sites/AmazonFreightOperations/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FAmazonFreightOperations%2FShared%20Documents%2FFTL%20Scheduling%2FScheduling%2FDaily%20Tasks%20Sheet&viewid=d2bea389%2Dda72%2D4ca8%2D8673%2D77ae91430301"

SCACS = "ATSIB, ATSIC, ATSID, ATSIE, ATSLL, AFENT, AFSMB"

EXTRACT_COLUMNS = [
  'inboundShipmentAppointment', 'scac', 'vrId',
  'appointmentStatus', 'appointmentType', 'fc'
]

RESULT_COLUMNS = ['scac', 'inboundShipmentAppointment', 'fc']

STEP_LABELS = {1: "1. Upload Portal CSVs", 2: "2. Results"}
STEP_COUNT = len(STEP_LABELS)

SESSION_DEFAULTS = {
  "ncns_step": 1,
  "ncns_results": None,
  "ncns_last_step": None,
   "ncns_upload_counter": 0,
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


def _process_ncns_data(dfs):
  combined = pd.concat(dfs, ignore_index=True)

  cm = {col.strip(): col for col in combined.columns}
  col_map = {}
  for req in EXTRACT_COLUMNS:
      matched = cm.get(req)
      if matched:
          col_map[req] = matched

  missing = [r for r in EXTRACT_COLUMNS if r not in col_map]
  if missing:
      return None, f"Missing columns: {', '.join(missing)}"

  df = combined[[col_map[r] for r in EXTRACT_COLUMNS]].copy()
  df.columns = EXTRACT_COLUMNS

  df = df[df['vrId'].fillna('').astype(str).str.strip() == ''].copy()
  df = df[df['appointmentStatus'].astype(str).str.strip().str.lower() == 'arrival scheduled'].copy()
  df = df[df['appointmentType'].astype(str).str.strip().str.lower() == 'carrier central'].copy()

  result = df[RESULT_COLUMNS].copy().reset_index(drop=True)
  return result, None


def _go_to_hub():
  st.session_state.active_audit = "home"
  for key in SESSION_DEFAULTS:
      if key in st.session_state:
          del st.session_state[key]
  if "ncns_csv_upload" in st.session_state:
      del st.session_state["ncns_csv_upload"]
  st.rerun()


@st.dialog("\u26a0\ufe0f Upload Warning")
def _show_upload_warning(messages):
  for msg in messages:
      st.warning(msg)


def render():
  for k, v in SESSION_DEFAULTS.items():
      if k not in st.session_state:
          st.session_state[k] = v

  step = st.session_state.ncns_step

  if st.session_state.ncns_last_step is None:
      st.session_state.ncns_last_step = step
  elif step != st.session_state.ncns_last_step:
      _scroll_to_top()
      st.session_state.ncns_last_step = step

  # Header
  top_left, top_right = st.columns([6, 1])
  with top_left:
      st.title("NCNS Prevention Audit")
      st.caption("Amazon Freight Scheduling Team \u2014 Identify No-Call-No-Show occurrences for proactive monitoring")
  with top_right:
      st.write("")
      st.write("")
      if st.button("Back to Audit Hub"):
          _go_to_hub()

  st.divider()

  # Progress bar
  pv = (step - 1) / (STEP_COUNT - 1) if STEP_COUNT > 1 else 1.0
  st.progress(pv, text=f"Step {step} of {STEP_COUNT}: {STEP_LABELS[step].split('. ', 1)[1]}")
  st.divider()

  # ── Step 1: Upload Unified Portal CSVs ───────────────────────────────
  if step == 1:
      left, right = st.columns([3, 2])
      with left:
          st.header("Step 1 \u2014 Upload Unified Portal CSVs")
      with right:
          st.write("")
          st.write("")
          st.markdown(
              f'<a href="{html.escape(UNIFIED_PORTAL_URL, quote=True)}" target="_blank" '
              f'style="display:inline-block; padding:0.5rem 1.2rem; border-radius:0.5rem; '
              f'border:2px solid #3b82f6; background:rgba(59,130,246,0.12); color:#1d4ed8; '
              f'font-size:1.1rem; font-weight:700; text-decoration:none;">Open Unified Portal \u2197</a>',
              unsafe_allow_html=True,
          )

      st.warning(
          "ACTION REQUIRED\n"
          "1. Open Unified Portal \u2192 Search \u2192 Appointment.\n"
          "2. Go to the SCAC tab.\n"
          "3. Set Data Type to 'Scheduled Arrival Date'.\n"
          "4. Set Start Date: current day. Set End Date: next day.\n"
          "5. Enter one SCAC at a time from the list below. For each SCAC entered click 'Submit' and download the CSV.\n"
          "6. Repeat for each SCAC (7 downloads total).\n"
          "7. Upload all CSV files below."
      )

      st.subheader("SCACs")
      st.code(SCACS, language=None)

      if st.button("Reset Uploads", key="ncns_reset_uploads"):
          st.session_state.ncns_upload_counter += 1
          st.rerun()

      uploaded = st.file_uploader(
          "Upload Unified Portal CSV exports (one per SCAC)",
          type=["csv"],
          accept_multiple_files=True,
          key=f"ncns_csv_upload_{st.session_state.ncns_upload_counter}",
      )

      if uploaded:
          dfs = []
          errors = 0
          filenames = []
          for f in uploaded:
              filenames.append(getattr(f, "name", "unknown.csv"))
              try:
                  raw = f.read()
                  dfs.append(pd.read_csv(io.BytesIO(raw), dtype=str))
              except Exception:
                  errors += 1

          st.info(f"Files uploaded: {len(uploaded)} | Parsed OK: {len(dfs)} | Errors: {errors}")

          with st.expander("Show uploaded filenames"):
              st.write(filenames)

          # Detect upload issues
          if dfs:
              upload_warnings = []
              expected_scacs = set(s.strip().upper() for s in SCACS.split(","))

              # Find which SCACs are present in uploaded data
              all_uploaded = pd.concat(dfs, ignore_index=True)
              scac_col = None
              for col in all_uploaded.columns:
                  if col.strip().lower() == 'scac':
                      scac_col = col
                      break

              if scac_col:
                  found_scacs = set(all_uploaded[scac_col].dropna().astype(str).str.strip().str.upper().unique())

                  # Check for missing SCACs
                  missing_scacs = expected_scacs - found_scacs
                  if missing_scacs:
                      upload_warnings.append(
                          f"**Missing SCAC data**\n\n"
                          f"The following SCACs were not found in the uploaded files:\n"
                          + "".join(f"- {s}\n" for s in sorted(missing_scacs))
                          + "\nPlease check that all SCACs have been searched and uploaded."
                      )

                  # Check for duplicate SCACs (same SCAC in multiple files)
                  scac_per_file = {}
                  for i, df in enumerate(dfs):
                      sc = None
                      for col in df.columns:
                          if col.strip().lower() == 'scac':
                              sc = col
                              break
                      if sc:
                          file_scacs = set(df[sc].dropna().astype(str).str.strip().str.upper().unique())
                          scac_per_file[filenames[i]] = file_scacs

                  # Check for files with mixed SCACs
                  for fname, file_scacs in scac_per_file.items():
                      if len(file_scacs) > 1:
                          scac_list = ", ".join(sorted(file_scacs))
                          upload_warnings.append(
                              f"**Possible wrong file: `{fname}`**\n\n"
                              f"This file contains multiple SCACs: {scac_list}. "
                              f"Each CSV export should contain only one SCAC. Please check this file."
                          )

                  # Find files with overlapping SCACs
                  fnames_list = list(scac_per_file.keys())
                  dup_pairs = []
                  for i in range(len(fnames_list)):
                      for j in range(i + 1, len(fnames_list)):
                          a, b = fnames_list[i], fnames_list[j]
                          overlap = scac_per_file[a] & scac_per_file[b]
                          if overlap:
                              dup_pairs.append((a, b, overlap))

                  if dup_pairs:
                      dup_msg = "**Possible duplicate uploads detected**\n\n"
                      dup_msg += "The following files contain the same SCAC data:\n"
                      for a, b, overlap in dup_pairs:
                          dup_msg += f"- `{a}` and `{b}` (SCAC: {', '.join(sorted(overlap))})\n"
                      dup_msg += "\nPlease check that each SCAC was only searched and uploaded once."
                      upload_warnings.append(dup_msg)

              if upload_warnings:
                  _show_upload_warning(upload_warnings)

              if st.button("Process and Produce Results", type="primary"):
                  result, error = _process_ncns_data(dfs)
                  if error:
                      st.error(error)
                  else:
                      st.session_state.ncns_results = result
                      st.session_state.ncns_step = 2
                      st.rerun()

  # ── Step 2: Results ──────────────────────────────────────────────────
  elif step == 2:
      left, right = st.columns([3, 2])
      with left:
          st.header("Step 2 \u2014 NCNS Results")
      with right:
          st.write("")
          st.write("")
          st.markdown(
              f'<a href="{html.escape(TASK_SHEET_URL, quote=True)}" target="_blank" '
              f'style="display:inline-block; padding:0.5rem 1.2rem; border-radius:0.5rem; '
              f'border:2px solid #3b82f6; background:rgba(59,130,246,0.12); color:#1d4ed8; '
              f'font-size:1.1rem; font-weight:700; text-decoration:none;">Open Task Sheet \u2197</a>',
              unsafe_allow_html=True,
          )
      st.balloons()

      results = st.session_state.ncns_results

      if results is not None and not results.empty:
          c1, c2 = st.columns(2)
          c1.metric("Total NCNS Appointments", len(results))
          c2.metric("SCACs Affected", results['scac'].nunique())

          st.divider()

          copy_df = results.copy()
          copy_df.insert(2, '_blank1', '')
          copy_df.insert(3, '_blank2', '')
          copy_df.insert(4, '_blank3', '')
          copy_text = make_copy_block(copy_df, exclude_cols=[])
          render_table_with_copy(
              title="NCNS Appointments \u2014 Copy to Scheduling Task Sheet",
              df=results,
              copy_text=copy_text,
              button_text="Copy to Task Sheet"
          )

          st.divider()
          st.warning(
              "ACTION REQUIRED\n"
              "1. Copy the appointments above to the NCNS tab on the Scheduling Task Sheet.\n"
              "Audit complete!"
          )
      else:
          st.success("No NCNS appointments found. All appointments have VRIDs assigned.")

      st.divider()
      c1, c2 = st.columns(2)
      with c1:
          if st.button("Back a step"):
              st.session_state.ncns_step = 1
              st.rerun()
      with c2:
          if st.button("Start a New Audit", type="primary"):
              for k in list(SESSION_DEFAULTS.keys()) + ["ncns_csv_upload"]:
                  if k in st.session_state:
                      del st.session_state[k]
              for k, v in SESSION_DEFAULTS.items():
                  st.session_state[k] = v
              st.rerun()
