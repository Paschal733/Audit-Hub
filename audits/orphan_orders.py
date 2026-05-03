import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import re
import io
import math
import html
import uuid

from shared import (
  UNIFIED_PORTAL_URL,
  is_fc_facility,
  load_smc_file,
  reset_index_display,
  make_copy_block,
  render_inline_copy_button,
  render_table_with_copy,
  render_portal_link,
  render_portal_batch_card,
  render_wrapped_batches,
  scroll_to_top,
)

SMC_URL = "https://smc-eu-dub.dub.proxy.amazon.com/orders/list/tab/1"
TASK_SHEET_URL = "https://amazongbr.sharepoint.com/sites/AmazonFreightOperations/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FAmazonFreightOperations%2FShared%20Documents%2FFTL%20Scheduling%2FScheduling%2FDaily%20Tasks%20Sheet&viewid=d2bea389%2Dda72%2D4ca8%2D8673%2D77ae91430301"

AMAZON_ALIAS_PATTERN = re.compile(r'^[a-z]{5,8}$')

SMC_KEEP_COLUMNS = [
  'Order ID', 'Destination Stop Facility Name', 'Shipper',
  'Status', 'Requested Delivery Date', 'Pallet Count'
]

PORTAL_EXCLUDE_STATUSES = ['cancelled', 'deleted', 'defect']

STEP_LABELS = {1: "1. Upload SMC Export", 2: "2. Portal Check", 3: "3. Results"}
STEP_COUNT = len(STEP_LABELS)

SESSION_DEFAULTS = {
  'oo_step': 1,
  'oo_internal_df': None,
  'oo_results': None,
  'oo_portal_ids': [],
  'oo_arrival_ids_ready': False,
  'oo_portal_upload_counter': 0,
  'oo_last_step': None,
}

RESET_KEYS = list(SESSION_DEFAULTS.keys()) + ['oo_smc_upload']


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


def _norm_col(s):
  return re.sub(r'[\s_\-]+', '', str(s).strip().lower())


def _norm_val(s):
  return re.sub(r'\s+', ' ', str(s).strip().lower())


def _process_smc_export(df_raw):
  df = df_raw.copy()
  cm = {col.strip(): col for col in df.columns}

  col_map = {}
  for req in SMC_KEEP_COLUMNS:
      matched = cm.get(req)
      if matched:
          col_map[req] = matched

  missing = [r for r in SMC_KEEP_COLUMNS if r not in col_map]
  if missing:
      return None, f"Missing columns: {', '.join(missing)}"

  # Remove dummy/test rows
  df_str = df.astype(str)
  dummy_mask = df_str.apply(lambda col: col.str.strip().str.lower().eq('dummy'), axis=0).any(axis=1)

  shipper_col = col_map.get('Shipper')
  if shipper_col:
      test_mask = df[shipper_col].astype(str).str.contains('test', case=False, na=False)
  else:
      test_mask = pd.Series([False] * len(df), index=df.index)

  df = df.loc[~(dummy_mask | test_mask)].copy()

  # Remove external (non-FC) orders
  fc_col = col_map['Destination Stop Facility Name']
  df['_is_fc'] = df[fc_col].apply(is_fc_facility)
  df = df[df['_is_fc'] == True].drop(columns=['_is_fc']).copy()

  # Keep only required columns
  df = df[[col_map[r] for r in SMC_KEEP_COLUMNS]].copy()
  df.columns = SMC_KEEP_COLUMNS

  return df, None


def _extract_portal_ids(df):
  if df is None or df.empty:
      return []
  norm_map = {_norm_col(c): c for c in df.columns}
  search_col = norm_map.get('searchid')
  status_col = norm_map.get('appointmentstatus')
  if not search_col or not status_col:
      return None
  s_search = df[search_col].astype(str).map(str.strip)
  s_status = df[status_col].astype(str).map(_norm_val)
  exclude_mask = s_status.isin(PORTAL_EXCLUDE_STATUSES)
  ids = s_search[~exclude_mask].dropna().astype(str).str.strip().tolist()
  return list(dict.fromkeys([x for x in ids if x]))


def _build_final_results(internal_df, portal_ids):
  cm = {col.strip(): col for col in internal_df.columns}
  oic = cm.get('Order ID')
  if not oic:
      return None

  ps = set(portal_ids)
  df = internal_df.copy()
  df['_in_portal'] = df[oic].astype(str).str.strip().isin(ps)
  orphans = df[df['_in_portal'] == False].drop(columns=['_in_portal']).copy()

  orphans = orphans.rename(columns={
      'Destination Stop Facility Name': 'FC',
      'Requested Delivery Date': 'CRDD',
  })

  orphans['Pallet Count'] = pd.to_numeric(orphans['Pallet Count'], errors='coerce').fillna(0)
  orphans['Load Type'] = orphans['Pallet Count'].apply(lambda x: 'Palletized' if x > 0 else 'Floor Loaded')
  orphans = orphans.drop(columns=['Pallet Count'])

  orphans = orphans[['Order ID', 'FC', 'Shipper', 'Status', 'CRDD', 'Load Type']].copy()
  return orphans.reset_index(drop=True)


@st.dialog("\u26a0\ufe0f Upload Warning")
def _show_upload_warning(messages):
  for msg in messages:
      st.warning(msg)


def _go_to_hub():
  st.session_state.active_audit = "home"
  for key in RESET_KEYS:
      if key in st.session_state:
          del st.session_state[key]
  st.rerun()


def render():
  for k, v in SESSION_DEFAULTS.items():
      if k not in st.session_state:
          st.session_state[k] = v

  step = st.session_state.oo_step

  if st.session_state.oo_last_step is None:
      st.session_state.oo_last_step = step
  elif step != st.session_state.oo_last_step:
      _scroll_to_top()
      st.session_state.oo_last_step = step

  top_left, top_right = st.columns([6, 1])
  with top_left:
      st.title('Orphan Orders Audit')
      st.caption('Amazon Freight Scheduling Team — Identify orders with no ISA appointment')
  with top_right:
      st.write("")
      st.write("")
      if st.button("Back to Audit Hub"):
          _go_to_hub()

  st.divider()

  pv = (step - 1) / (STEP_COUNT - 1)
  st.progress(pv, text=f"Step {step} of {STEP_COUNT}: {STEP_LABELS[step].split('. ', 1)[1]}")
  st.divider()

  # ── Step 1: Upload SMC Export ────────────────────────────────────────
  if step == 1:
      left, right = st.columns([3, 2])
      with left:
          st.header('Step 1 — Upload SMC Export')
      with right:
          st.write('')
          st.write('')
          st.markdown(
              f'<a href="{html.escape(SMC_URL, quote=True)}" target="_blank" '
              f'style="display:inline-block; padding:0.5rem 1.2rem; border-radius:0.5rem; '
              f'border:2px solid #3b82f6; background:rgba(59,130,246,0.12); color:#1d4ed8; '
              f'font-size:1.1rem; font-weight:700; text-decoration:none;">Open SMC ↗</a>',
              unsafe_allow_html=True,
          )
      st.warning(
          "ACTION REQUIRED\n"
          "1. Open SMC Uncovered Page using the link above.\n"
          "2. Untick LTL and Intermodal.\n"
          "3. Click Export File.\n"
          "4. Upload the file below."
      )

      uploaded = st.file_uploader(
          'Upload your SMC export (.xlsx, .xls, or .csv)',
          type=['xlsx', 'xls', 'csv'],
          key='oo_smc_upload'
      )

      if uploaded is not None:
          try:
              df = load_smc_file(uploaded)
              st.success(f'File loaded: {len(df)} orders, {len(df.columns)} columns detected.')
              st.dataframe(df.head(10), use_container_width=True)
              st.caption(f'Showing first 10 of {len(df)} rows.')

              if st.button('Proceed To Step 2 — Unified Portal Check', type='primary'):
                  result, error = _process_smc_export(df)
                  if error:
                      st.error(error)
                  else:
                      st.session_state.oo_internal_df = result
                      st.session_state.oo_step = 2
                      st.rerun()

          except Exception as e:
              st.error(f'Error reading file: {e}')

  # ── Step 2: Unified Portal Check ────────────────────────────────────
  elif step == 2:
      st.header('Step 2 — Unified Portal Check')

      ds = st.session_state.oo_internal_df
      cm = {col.strip(): col for col in ds.columns}
      oic = cm.get('Order ID')
      if not oic:
          st.error("Missing 'Order ID' column.")
          st.stop()

      rids = ds[oic].dropna().astype(str).str.strip().tolist()
      st.info(f'{len(rids)} Order IDs need to be checked in the Unified Portal.')

      render_portal_link(UNIFIED_PORTAL_URL)

      batch_size = 50
      total = len(rids)
      batch_count = max(1, math.ceil(total / batch_size))

      with st.expander('View / Copy Order IDs in Batches'):
          if total == 0:
              st.warning("No Order IDs available to copy.")
          else:
              st.info(
                  "1. Go to Unified Portal by clicking the link above.\n"
                  "2. On Unified Portal, change 'ID Type' to 'Progressive Number'.\n"
                  "3. Copy the Order IDs in Batches, search on Unified Portal and download the results.\n"
                  "4. Upload the CSV results back on this audit page in the section below."
              )

              batches = []
              for i in range(batch_count):
                  start = i * batch_size
                  end = min(start + batch_size, total)
                  batch_ids = rids[start:end]
                  if not batch_ids:
                      continue
                  batches.append({
                      "label": f"Batch {i+1}",
                      "subtitle": f"{start+1}–{end} of {total}",
                      "text": "\n".join(batch_ids),
                  })

              render_wrapped_batches(batches, per_row=6, box_height=260)

      st.divider()
      st.subheader('Upload Unified Portal Results CSV(s)')

      if st.button("Reset Uploads", key="oo_reset_uploads"):
          st.session_state.oo_portal_ids = []
          st.session_state.oo_arrival_ids_ready = False
          st.session_state.oo_portal_upload_counter += 1
          st.rerun()

      portal_csvs = st.file_uploader(
          "Upload Unified Portal export CSV file(s). You can upload multiple files (one per 50-ID search batch). "
          "Each CSV must contain columns: searchId and appointmentStatus.",
          type=['csv'],
          accept_multiple_files=True,
          key=f'oo_portal_upload_{st.session_state.oo_portal_upload_counter}'
      )

      if portal_csvs:
          all_portal_ids = []
          per_file_ids = {}
          files_ok = 0
          files_missing_cols = 0
          files_read_error = 0
          filenames = []

          for f in portal_csvs:
              fname = getattr(f, "name", "unknown.csv")
              filenames.append(fname)
              try:
                  raw = f.read()
                  pdf = pd.read_csv(io.BytesIO(raw), dtype=str)

                  ids = _extract_portal_ids(pdf)
                  if ids is None:
                      files_missing_cols += 1
                      continue

                  files_ok += 1
                  per_file_ids[fname] = set(ids)
                  all_portal_ids.extend(ids)

              except Exception:
                  files_read_error += 1

          total_before_dedup = len(all_portal_ids)
          all_portal_ids = list(dict.fromkeys([x for x in all_portal_ids if x]))
          duplicates_removed = total_before_dedup - len(all_portal_ids)

          # Collect warnings for popup
          upload_warnings = []
          if files_ok < batch_count:
              upload_warnings.append(
                  f"**Fewer files uploaded than expected**\n\n"
                  f"There are {batch_count} batches to search but only {files_ok} file(s) were uploaded. "
                  f"Each batch search should produce one export file. "
                  f"Please check that all batches have been searched and uploaded."
              )

          # Detect duplicate uploads
          fnames_list = list(per_file_ids.keys())
          dup_pairs = []
          for i in range(len(fnames_list)):
              for j in range(i + 1, len(fnames_list)):
                  a, b = fnames_list[i], fnames_list[j]
                  ids_a, ids_b = per_file_ids[a], per_file_ids[b]
                  if ids_a and ids_b:
                      overlap = len(ids_a & ids_b)
                      smaller = min(len(ids_a), len(ids_b))
                      if smaller > 0 and overlap / smaller >= 0.8:
                          dup_pairs.append((a, b, overlap, smaller))

          if dup_pairs:
              dup_msg = "**Possible duplicate uploads detected**\n\n"
              dup_msg += "The following files appear to contain the same search results:\n"
              for a, b, overlap, smaller in dup_pairs:
                  dup_msg += f"- `{a}` and `{b}` ({overlap} of {smaller} IDs overlap)\n"
              dup_msg += "\nThis may mean a batch was searched twice and another batch was missed. "
              dup_msg += "Please check that all batches have been searched before proceeding."
              upload_warnings.append(dup_msg)

          if upload_warnings:
              _show_upload_warning(upload_warnings)

          if files_missing_cols > 0:
              st.error(
                  f"{files_missing_cols} file(s) did not contain required columns "
                  f"('searchId' and 'appointmentStatus')."
              )
          if files_read_error > 0:
              st.error(f"{files_read_error} file(s) could not be read as CSV.")

          dedup_note = f" ({duplicates_removed} duplicates removed)" if duplicates_removed > 0 else ""
          st.info(
              f"Files uploaded: {len(portal_csvs)} | Parsed OK: {files_ok} | "
              f"Order IDs extracted: {len(all_portal_ids)}{dedup_note}"
          )

          with st.expander("Show uploaded filenames"):
              st.write(filenames)

          if all_portal_ids:
              st.session_state.oo_portal_ids = all_portal_ids
              st.session_state.oo_arrival_ids_ready = True
              st.success(f"{len(all_portal_ids)} unique Order IDs extracted from portal results.")

      st.divider()
      ready = bool(st.session_state.oo_arrival_ids_ready and len(st.session_state.oo_portal_ids) > 0)
      if ready:
          st.info("Portal results are ready. You can now run the cross-reference.")

      c1, c2 = st.columns(2)
      with c1:
          if st.button('Back a step'):
              st.session_state.oo_step = 1
              st.rerun()
      with c2:
          run_clicked = st.button(
              'Run Cross-Reference and Produce Final Results',
              type='primary',
              disabled=(not ready)
          )

      if run_clicked:
          results = _build_final_results(
              st.session_state.oo_internal_df,
              st.session_state.oo_portal_ids
          )
          st.session_state.oo_results = results
          st.session_state.oo_step = 3
          st.rerun()

  # ── Step 3: Results ──────────────────────────────────────────────────
  elif step == 3:
      left, right = st.columns([3, 2])
      with left:
          st.header('Step 3 — Orphan Orders Results')
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

      results = st.session_state.oo_results

      if results is not None and not results.empty:
          c1, c2, c3 = st.columns(3)
          c1.metric("Orphan Orders Found", len(results))
          c2.metric("Floor Loaded", int((results['Load Type'] == 'Floor Loaded').sum()))
          c3.metric("Palletized", int((results['Load Type'] == 'Palletized').sum()))

          st.divider()

          # Display table without blank column
          display_df = results[['Order ID', 'FC', 'Shipper', 'Status', 'CRDD', 'Load Type']].copy()

          # Copy text with blank column for task sheet alignment
          # Two copy buttons: C-E and G-I (skipping protected column F)
          copy_ce = make_copy_block(display_df[['Order ID', 'FC', 'Shipper']], exclude_cols=[])
          copy_gi = make_copy_block(display_df[['Status', 'CRDD', 'Load Type']], exclude_cols=[])

          st.subheader("Orphan Orders — Copy to Scheduling Task Sheet")
          c1, c2 = st.columns(2)
          with c1:
              _render_copy_button(copy_ce, button_text="Copy C-E (Order ID, FC, Shipper)")
          with c2:
              _render_copy_button(copy_gi, button_text="Copy G-I (Status, CRDD, Load Type)")

          st.dataframe(reset_index_display(display_df), use_container_width=True)


          st.divider()
          st.warning(
              "ACTION REQUIRED\n"
              "1. Copy the orphan orders above to the Orphan Orders tab on the Scheduling Task Sheet.\n"
              "Audit complete!"
          )
      else:
          st.success("No orphan orders found. All internal orders have ISA appointments.")

      st.divider()
      c1, c2 = st.columns(2)
      with c1:
          if st.button("Back a step"):
              st.session_state.oo_step = 2
              st.rerun()
      with c2:
          if st.button('Start a New Audit', type='primary'):
              for k in RESET_KEYS:
                  if k in st.session_state:
                      del st.session_state[k]
              for k, v in SESSION_DEFAULTS.items():
                  st.session_state[k] = v
              st.rerun()
