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

TASK_SHEET_URL = "https://amazongbr.sharepoint.com/sites/AmazonFreightOperations/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FAmazonFreightOperations%2FShared%20Documents%2FFTL%20Scheduling%2FScheduling%2FDaily%20Tasks%20Sheet&viewid=d2bea389%2Dda72%2D4ca8%2D8673%2D77ae91430301"

TMS_SHIPPERS = [
  {"name": "Josera Erbacher Service GmbH & Co. KG", "url": "https://smc-eu-dub.dub.proxy.amazon.com/shipper/2818197079/pending-orders"},
  {"name": "H. Von Gimborn GmbH", "url": "https://smc-eu-dub.dub.proxy.amazon.com/shipper/4510132091/pending-orders"},
  {"name": "Animonda petcare gmbh", "url": "https://smc-eu-dub.dub.proxy.amazon.com/shipper/5181379714/pending-orders"},
  {"name": "SIG Combibloc GmbH - Linnich", "url": "https://smc-eu-dub.dub.proxy.amazon.com/shipper/3497489165/pending-orders"},
  {"name": "SIG Combibloc GmbH - Wittenberg", "url": "https://smc-eu-dub.dub.proxy.amazon.com/shipper/4800908590/pending-orders"},
  {"name": "Compo GmbH", "url": "https://smc-eu-dub.dub.proxy.amazon.com/shipper/8143035127/pending-orders"},
]

TMS_SHIPPER_NAMES = set(s["name"].strip().lower() for s in TMS_SHIPPERS)

REQUIRED_COLUMNS = ['Order ID', 'Shipper', 'Origin Instructions']

STEP_LABELS = {1: "1. Upload Shipper Exports", 2: "2. Results"}
STEP_COUNT = len(STEP_LABELS)

SESSION_DEFAULTS = {
  "tms_step": 1,
  "tms_results": None,
  "tms_upload_counter": 0,
  "tms_last_step": None,
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


def _render_copy_button(text, button_text="Copy"):
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


def _process_tms_data(dfs):
  combined = pd.concat(dfs, ignore_index=True)

  cm = {col.strip(): col for col in combined.columns}
  col_map = {}
  for req in REQUIRED_COLUMNS:
      matched = cm.get(req)
      if matched:
          col_map[req] = matched

  missing = [r for r in REQUIRED_COLUMNS if r not in col_map]
  if missing:
      return None, f"Missing columns: {', '.join(missing)}"

  df = combined[[col_map[r] for r in REQUIRED_COLUMNS]].copy()
  df.columns = REQUIRED_COLUMNS

  df = df[~df['Origin Instructions'].fillna('').astype(str).str.contains('Cargoclix', case=False, na=False)].copy()

  result = df[['Order ID', 'Shipper']].copy().reset_index(drop=True)
  return result, None


@st.dialog("\u26a0\ufe0f Upload Warning")
def _show_upload_warning(messages):
  for msg in messages:
      st.warning(msg)


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

  step = st.session_state.tms_step

  if st.session_state.tms_last_step is None:
      st.session_state.tms_last_step = step
  elif step != st.session_state.tms_last_step:
      _scroll_to_top()
      st.session_state.tms_last_step = step

  top_left, top_right = st.columns([6, 1])
  with top_left:
      st.title("TMS Audit")
      st.caption("Amazon Freight Scheduling Team — Identify orders without TMS collection bookings")
  with top_right:
      st.write("")
      st.write("")
      if st.button("Back to Audit Hub"):
          _go_to_hub()

  st.divider()

  pv = (step - 1) / (STEP_COUNT - 1) if STEP_COUNT > 1 else 1.0
  st.progress(pv, text=f"Step {step} of {STEP_COUNT}: {STEP_LABELS[step].split('. ', 1)[1]}")
  st.divider()

  # ── Step 1: Upload Shipper Exports ───────────────────────────────────
  if step == 1:
      st.header("Step 1 — Upload Shipper Pending Orders")

      st.warning(
          "ACTION REQUIRED\n"
          "1. Click each shipper link below to open their pending orders page on SMC.\n"
          "1. Click each shipper link below to open their pending orders page on SMC.\n"
          "2. Untick 'Less Than Truck Load' and 'Intermodal'.\n"
          "3. Export the pending orders for each shipper.\n"
          "4. Upload all exported files below."
      )

      st.subheader("TMS Shippers")
      for s in TMS_SHIPPERS:
          st.markdown(
              f'<a href="{html.escape(s["url"], quote=True)}" target="_blank" '
              f'style="display:inline-block; padding:0.3rem 0.8rem; margin:0.2rem 0; border-radius:0.4rem; '
              f'border:1px solid #3b82f6; background:rgba(59,130,246,0.08); color:#1d4ed8; '
              f'font-size:0.9rem; font-weight:600; text-decoration:none;">'
              f'{html.escape(s["name"])} ↗</a>',
              unsafe_allow_html=True,
          )

      st.divider()

      if st.button("Reset Uploads", key="tms_reset_uploads"):
          st.session_state.tms_upload_counter += 1
          st.rerun()

      uploaded = st.file_uploader(
          "Upload shipper pending orders exports (.xlsx, .xls, or .csv)",
          type=["xlsx", "xls", "csv"],
          accept_multiple_files=True,
          key=f"tms_upload_{st.session_state.tms_upload_counter}",
      )

      if uploaded:
          dfs = []
          errors = 0
          filenames = []
          file_shippers = {}

          for f in uploaded:
              fname = getattr(f, "name", "unknown")
              filenames.append(fname)
              try:
                  raw = f.read()
                  df = load_smc_file(io.BytesIO(raw))
                  dfs.append(df)

                  cm = {col.strip(): col for col in df.columns}
                  shipper_col = cm.get('Shipper')
                  if shipper_col:
                      shippers = set(df[shipper_col].dropna().astype(str).str.strip().unique())
                      file_shippers[fname] = shippers
              except Exception:
                  errors += 1

          st.info(f"Files uploaded: {len(uploaded)} | Parsed OK: {len(dfs)} | Errors: {errors}")

          with st.expander("Show uploaded filenames"):
              st.write(filenames)

          # Detect upload issues
          upload_warnings = []

          for fname, shippers in file_shippers.items():
              if len(shippers) > 1:
                  shipper_list = ", ".join(sorted(shippers))
                  upload_warnings.append(
                      f"**Possible wrong file: `{fname}`**\n\n"
                      f"This file contains multiple shippers: {shipper_list}. "
                      f"Each file should contain orders from one shipper only."
                  )

              for s in shippers:
                  if s.strip().lower() not in TMS_SHIPPER_NAMES:
                      upload_warnings.append(
                          f"**Possible wrong file: `{fname}`**\n\n"
                          f"Shipper `{s}` is not in the TMS shippers list. "
                          f"Please check this file."
                      )

          shipper_to_files = {}
          for fname, shippers in file_shippers.items():
              for s in shippers:
                  sl = s.strip().lower()
                  if sl not in shipper_to_files:
                      shipper_to_files[sl] = []
                  shipper_to_files[sl].append(fname)

          for shipper, fnames in shipper_to_files.items():
              if len(fnames) > 1:
                  upload_warnings.append(
                      f"**Possible duplicate upload**\n\n"
                      f"Shipper `{shipper}` appears in multiple files: "
                      + ", ".join(f"`{f}`" for f in fnames)
                      + ". Each shipper should only be uploaded once."
                  )

          if upload_warnings:
              _show_upload_warning(upload_warnings)

          if dfs:
              if st.button("Process and Produce Results", type="primary"):
                  result, error = _process_tms_data(dfs)
                  if error:
                      st.error(error)
                  else:
                      st.session_state.tms_results = result
                      st.session_state.tms_step = 2
                      st.rerun()

  # ── Step 2: Results ──────────────────────────────────────────────────
  elif step == 2:
      left, right = st.columns([3, 2])
      with left:
          st.header("Step 2 — Final Results")
      with right:
          st.write("")
          st.write("")
          st.markdown(
              f'<a href="{html.escape(TASK_SHEET_URL, quote=True)}" target="_blank" '
              f'style="display:inline-block; padding:0.5rem 1.2rem; border-radius:0.5rem; '
              f'border:2px solid #3b82f6; background:rgba(59,130,246,0.12); color:#1d4ed8; '
              f'font-size:1.1rem; font-weight:700; text-decoration:none;">Open Task Sheet ↗</a>',
              unsafe_allow_html=True,
          )
      st.balloons()

      results = st.session_state.tms_results

      if results is not None and not results.empty:
          c1, c2 = st.columns(2)
          c1.metric("Orders Without TMS Bookings", len(results))
          c2.metric("Shippers Affected", results['Shipper'].nunique())

          st.divider()

          display_df = results[['Order ID', 'Shipper']].copy()

          copy_df = results[['Order ID']].copy()
          for i in range(5):
              copy_df[f'_blank{i}'] = ''
          copy_df['Shipper'] = results['Shipper']
          copy_text = make_copy_block(copy_df, exclude_cols=[])

          render_table_with_copy(
              title="Orders Without TMS Bookings — Copy to Task Sheet",
              df=display_df,
              copy_text=copy_text,
              button_text="Copy to Task Sheet"
          )

          st.divider()
          st.warning(
              "ACTION REQUIRED\n"
              "1. Copy the orders above to the TMS tab on the Scheduling Task Sheet.\n"
              "Audit complete!"
          )
      else:
          st.success("All orders have TMS bookings. No action required.")

      st.divider()
      c1, c2 = st.columns(2)
      with c1:
          if st.button("Back a step"):
              st.session_state.tms_step = 1
              st.rerun()
      with c2:
          if st.button("Start a New Audit", type="primary"):
              for k in list(SESSION_DEFAULTS.keys()):
                  if k in st.session_state:
                      del st.session_state[k]
              for k, v in SESSION_DEFAULTS.items():
                  st.session_state[k] = v
              st.rerun()