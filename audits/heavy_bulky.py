import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import io
import html
import uuid
import os
import json
from datetime import datetime, date
import boto3

from shared import (
  is_cst_shipper,
  load_smc_file,
  reset_index_display,
  make_copy_block,
  render_inline_copy_button,
  render_table_with_copy,
  scroll_to_top,
)

SMC_URL = "https://smc-eu-dub.dub.proxy.amazon.com/orders/list/tab/1"
TASK_SHEET_URL = "https://amazongbr.sharepoint.com/sites/AmazonFreightOperations/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FAmazonFreightOperations%2FShared%20Documents%2FFTL%20Scheduling%2FScheduling%2FDaily%20Tasks%20Sheet&viewid=d2bea389%2Dda72%2D4ca8%2D8673%2D77ae91430301"

HB_SITES = "DTM3,STR2,XDEA,XDEV,XFR7,XGEB,DSA7,LTN7,XUKA,XUKS,XFRL,XFRN,FCO5,XITF,BCN3,XIBA"

REQUIRED_COLUMNS = [
  'Order ID', 'Shipper', 'Destination Stop Date and Time',
  'Destination Stop Facility Name', 'Weight', 'Pallet Count'
]

WEIGHT_THRESHOLD = 1000

STEP_LABELS = {1: "1. Upload SMC Export", 2: "2. Results"}
STEP_COUNT = len(STEP_LABELS)

SESSION_DEFAULTS = {
  "hb_step": 1,
  "hb_results": None,
  "hb_last_step": None,
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



BUCKET_NAME = os.environ.get("AUDIT_DATA_BUCKET", "")
S3_KEY = "heavy_bulky/audit_history.json"


def _get_s3_client():
   try:
       return boto3.client("s3")
   except Exception:
       return None


def _load_audit_history():
   if not BUCKET_NAME:
       return {}
   s3 = _get_s3_client()
   if not s3:
       return {}
   try:
       obj = s3.get_object(Bucket=BUCKET_NAME, Key=S3_KEY)
       data = json.loads(obj["Body"].read().decode("utf-8"))
       # Clean up: keep only current month and previous month
       today = date.today()
       if today.month == 1:
           keep_months = [(today.year, 1), (today.year - 1, 12)]
       else:
           keep_months = [(today.year, today.month), (today.year, today.month - 1)]
       cleaned = {}
       for key, ids in data.items():
           try:
               d = datetime.strptime(key, "%Y-%m-%d").date()
               if (d.year, d.month) in keep_months:
                   cleaned[key] = ids
           except ValueError:
               pass
       return cleaned
   except s3.exceptions.NoSuchKey:
       return {}
   except Exception as e:
       st.caption(f"S3 read error: {e}")
       return {}


def _save_audit_history(history, new_order_ids):
   if not BUCKET_NAME:
       return
   s3 = _get_s3_client()
   if not s3:
       return
   try:
       today_key = date.today().strftime("%Y-%m-%d")
       existing = history.get(today_key, [])
       combined = list(set(existing + new_order_ids))
       history[today_key] = combined
       s3.put_object(
           Bucket=BUCKET_NAME,
           Key=S3_KEY,
           Body=json.dumps(history).encode("utf-8"),
           ContentType="application/json",
       )
   except Exception as e:
       st.caption(f"S3 write error: {e}")


def _get_previous_order_ids(history):
   all_ids = set()
   today_key = date.today().strftime("%Y-%m-%d")
   for key, ids in history.items():
       if key != today_key:
           all_ids.update(ids)
   return all_ids

def _process_hb_data(df: pd.DataFrame):
  cm = {col.strip(): col for col in df.columns}

  col_map = {}
  for req in REQUIRED_COLUMNS:
      matched = cm.get(req)
      if matched:
          col_map[req] = matched

  missing = [r for r in REQUIRED_COLUMNS if r not in col_map]
  if missing:
      return None, f"Missing columns: {', '.join(missing)}"

  df = df[[col_map[r] for r in REQUIRED_COLUMNS]].copy()
  df.columns = REQUIRED_COLUMNS

  df = df[~df['Shipper'].apply(is_cst_shipper)].copy()

  df['Weight'] = pd.to_numeric(df['Weight'].astype(str).str.replace(r'[^0-9.]', '', regex=True), errors='coerce').fillna(0)
  df['Pallet Count'] = pd.to_numeric(df['Pallet Count'], errors='coerce').fillna(0).astype(int)

  loose = df[df['Pallet Count'] == 0].copy()
  with_pallets = df[df['Pallet Count'] > 0].copy()
  heavy = with_pallets[with_pallets['Weight'] / with_pallets['Pallet Count'] > WEIGHT_THRESHOLD].copy()

  result = pd.concat([loose, heavy], ignore_index=True)
  return result, None


def _go_to_hub():
  st.session_state.active_audit = "home"
  for key in SESSION_DEFAULTS:
      if key in st.session_state:
          del st.session_state[key]
  if "hb_smc_upload" in st.session_state:
      del st.session_state["hb_smc_upload"]
  st.rerun()


def render():
  for k, v in SESSION_DEFAULTS.items():
      if k not in st.session_state:
          st.session_state[k] = v

  step = st.session_state.hb_step

  if st.session_state.hb_last_step is None:
      st.session_state.hb_last_step = step
  elif step != st.session_state.hb_last_step:
      _scroll_to_top()
      st.session_state.hb_last_step = step

  # Header
  top_left, top_right = st.columns([6, 1])
  with top_left:
      st.title("Heavy & Bulky Orders Audit")
      st.caption("Amazon Freight Scheduling Team — Identify orders exceeding weight thresholds")
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

  # ── Step 1: Upload SMC Export ────────────────────────────────────────
  if step == 1:
      left, right = st.columns([3, 2])
      with left:
          st.header("Step 1 — Upload SMC Export")
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

      st.warning(
          "ACTION REQUIRED\n"
           "1. Go to SMC → Advanced Search.\n"
           "2. Untick LTL and Intermodal.\n"
           "3. Click 'Additional'.\n"
           "4. Unselect all statuses → Select Covered, Tendered & Uncovered.\n"
           "5. Set Creation Date Range: minus 1 day to plus 1 day (if running the audit on a Saturday, select Friday to Monday).\n"
           "6. Click 'Search Options' at the bottom of the additional search box.\n"
           "7. Under search options, select 'Destination Stop Location Codes'.\n"
           "8. Paste the H&B sites below in the 'Destination Stop Location Codes' box and search.\n"
           "9. Click Export to download the results.\n"
           "10. Upload the file below."
      )

      st.subheader("H&B Sites")
      st.code(HB_SITES, language=None)
      _render_copy_button(HB_SITES, button_text="Copy H&B Sites")

      uploaded = st.file_uploader(
          "Upload SMC export (.xlsx, .xls, or .csv)",
          type=["xlsx", "xls", "csv"],
          key="hb_smc_upload",
      )

      if uploaded is not None:
          try:
              df = load_smc_file(uploaded)
              st.success(f"File loaded: {len(df)} orders, {len(df.columns)} columns detected.")
              st.dataframe(df.head(10), use_container_width=True)
              st.caption(f"Showing first 10 of {len(df)} rows.")

              if st.button("Process and Produce Results", type="primary"):
                  result, error = _process_hb_data(df)
                  if error:
                      st.error(error)
                  else:
                      st.session_state.hb_results = result
                      st.session_state.hb_step = 2
                      st.rerun()

          except Exception as e:
              st.error(f"Error reading file: {e}")

  # ── Step 2: Results ──────────────────────────────────────────────────
  elif step == 2:
      left, right = st.columns([3, 2])
      with left:
          st.header("Step 2 — Heavy & Bulky Results")
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

      results = st.session_state.hb_results

      if results is not None and not results.empty:
          # Load history and split into new vs previously seen
          st.caption(f"S3 Bucket: {BUCKET_NAME or 'NOT SET'}")
          history = _load_audit_history()
          prev_ids = _get_previous_order_ids(history)
          results['_prev'] = results['Order ID'].astype(str).str.strip().isin(prev_ids)
          new_orders = results[results['_prev'] == False].drop(columns=['_prev']).copy()
          prev_orders = results[results['_prev'] == True].drop(columns=['_prev']).copy()

          loose_count = int((new_orders['Pallet Count'] == 0).sum()) if not new_orders.empty else 0
          heavy_count = len(new_orders) - loose_count

          c1, c2, c3, c4 = st.columns(4)
          c1.metric("New Orders", len(new_orders))
          c2.metric("Loose Loads (0 pallets)", loose_count)
          c3.metric("Heavy (>1000kg/pallet)", heavy_count)
          c4.metric("Duplicates", len(prev_orders))

          st.divider()

          if not new_orders.empty:
              copy_text = make_copy_block(new_orders, exclude_cols=[])
              render_table_with_copy(
                  title="New Heavy & Bulky Orders — Copy to Task Sheet",
                  df=new_orders,
                  copy_text=copy_text,
                  button_text="Copy to Task Sheet"
              )
          else:
              st.success("No new heavy or bulky orders found.")

          if not prev_orders.empty:
              st.divider()
              st.subheader(f"Duplicate Orders From Past Audits ({len(prev_orders)})")
              st.caption("These orders appeared in previous audits.")
              st.dataframe(reset_index_display(prev_orders), use_container_width=True)

          # Save current results to history
          all_order_ids = results['Order ID'].astype(str).str.strip().tolist()
          _save_audit_history(history, all_order_ids)

          st.divider()
          st.warning(
              "ACTION REQUIRED\n"
              "1. Copy the new orders above to the Heavy & Bulky Orders Task Sheet.\n"
              "Audit complete!"
          )
      else:
          st.success("No heavy or bulky orders found. All orders are within acceptable thresholds.")

      st.divider()
      c1, c2 = st.columns(2)
      with c1:
          if st.button("Back a step"):
              st.session_state.hb_step = 1
              st.rerun()
      with c2:
          if st.button("Start a New Audit", type="primary"):
              for k in list(SESSION_DEFAULTS.keys()) + ["hb_smc_upload"]:
                  if k in st.session_state:
                      del st.session_state[k]
              for k, v in SESSION_DEFAULTS.items():
                  st.session_state[k] = v
              st.rerun()