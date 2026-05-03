import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import io
import math
import html
import uuid

from shared import (
  UNIFIED_PORTAL_URL,
  CST_SHIPPERS,
  AMAZON_ALIAS_PATTERN,
  FC_PATTERN,
  is_cst_shipper,
  is_fc_facility,
  classify_source,
  load_smc_file,
  reset_index_display,
  drop_if_exists,
  make_copy_block,
  render_inline_copy_button,
  render_table_with_copy,
  render_portal_link,
  render_portal_batch_card,
  render_wrapped_batches,
  scroll_to_top,
)

SMC_URL = "https://smc-eu-dub.dub.proxy.amazon.com/orders/list/tab/1"

REQUIRED_COLUMNS = [
  'Order ID', 'Source', 'Shipper', 'Destination Stop Date and Time',
  'Destination Stop Facility Name', 'Creation Date and Time', 'Created by'
]
REQUIRED_COLUMNS_CST = [
  'Order ID', 'Source', 'Shipper', 'Destination Stop Date and Time',
  'Creation Date and Time', 'Created by'
]

VISIBLE_STEP_ORDER = [1, 4, 5]
VISIBLE_STEP_LABELS = {
  1: '1. Upload File',
  4: '2. Portal Check',
  5: '3. Final Results',
}
VISIBLE_STEP_NUMBER = {
  1: 1,
  4: 2,
  5: 3,
}

SESSION_DEFAULTS = {
  'step': 1,
  'df_raw': None,
  'df_formatted': None,
  'df_step4': None,
  'cst_ext': None,
  'non_cst_ext': None,
  'portal_ids': [],
  'cst_final': None,
  'non_cst_final': None,
  'unmatched_count': 0,
  'step3_skipped': False,
  'arrival_ids_ready': False,
  'portal_export_filenames': [],
  'last_step': None,
   'portal_upload_counter': 0,
}

RESET_KEYS = list(SESSION_DEFAULTS.keys()) + [
  'smc_upload', 'portal_export_upload_multi', 'manual_arrivals_paste'
]


def _norm_col(s: str) -> str:
  import re
  return re.sub(r'[\s_\-]+', '', str(s).strip().lower())


def _norm_val(s: str) -> str:
  import re
  return re.sub(r'\s+', ' ', str(s).strip().lower())


def extract_arrival_scheduled_ids_from_unified_portal_csv(df: pd.DataFrame):
  if df is None or df.empty:
      return []
  norm_map = {_norm_col(c): c for c in df.columns}
  search_col = norm_map.get('searchid')
  status_col = norm_map.get('appointmentstatus')
  if not search_col or not status_col:
      return None
  s_search = df[search_col].astype(str).map(str.strip)
  s_status = df[status_col].astype(str).map(_norm_val)
  mask = (s_status == 'arrival scheduled')
  ids = s_search[mask].dropna().astype(str).str.strip().tolist()
  return list(dict.fromkeys([x for x in ids if x]))


def process_step2_backend(df_raw: pd.DataFrame) -> pd.DataFrame:
  df = df_raw.copy()
  cm = {col.strip().lower(): col for col in df.columns}

  df_str = df.astype(str)
  dummy_mask = df_str.apply(lambda col: col.str.strip().str.lower().eq('dummy'), axis=0).any(axis=1)

  shipper_col = cm.get('shipper')
  if shipper_col:
      test_mask = df[shipper_col].astype(str).str.contains('test', case=False, na=False)
  else:
      test_mask = pd.Series([False] * len(df), index=df.index)

  remove_mask = dummy_mask | test_mask
  df = df.loc[~remove_mask].copy()


  # Keep only Uncovered orders
  cm_status = {col.strip().lower(): col for col in df.columns}
  status_col = cm_status.get('status')
  if status_col:
      df = df[df[status_col].astype(str).str.strip().str.lower() == 'uncovered'].copy()
  cols = list(df.columns)
  if len(cols) >= 2:
      old_b = cols[1]
      df = df.rename(columns={old_b: 'Source'})

  cm2 = {col.strip().lower(): col for col in df.columns}
  keep_cols = [cm2[c.lower()] for c in REQUIRED_COLUMNS if c.lower() in cm2]
  df = df[keep_cols].copy()

  cm3 = {col.strip().lower(): col for col in df.columns}
  created_by_col = cm3.get('created by')
  if created_by_col:
      df['Source'] = df[created_by_col].apply(classify_source)

  return df


def _split_external_internal(df: pd.DataFrame):
  """Split formatted data into external (CST/non-CST) and internal orders."""
  cm = {col.strip().lower(): col for col in df.columns}
  fc = cm.get('destination stop facility name')
  shc = cm.get('shipper')

  if not fc or not shc:
      return pd.DataFrame(columns=REQUIRED_COLUMNS_CST), pd.DataFrame(columns=REQUIRED_COLUMNS), df

  df['_is_fc'] = df[fc].apply(is_fc_facility)
  ext = df[df['_is_fc'] == False].copy()
  intr = df[df['_is_fc'] == True].copy().drop(columns=['_is_fc'])

  if ext.empty:
      cst_ext = pd.DataFrame(columns=REQUIRED_COLUMNS_CST)
      non_cst_ext = pd.DataFrame(columns=REQUIRED_COLUMNS)
  else:
      ext['_is_cst'] = ext[shc].apply(is_cst_shipper)
      cst_ext_raw = ext[ext['_is_cst'] == True].drop(columns=['_is_fc', '_is_cst'])
      non_cst_ext = ext[ext['_is_cst'] == False].drop(columns=['_is_fc', '_is_cst'])
      cst_cols_to_keep = [c for c in cst_ext_raw.columns if c.lower() != 'destination stop facility name']
      cst_ext = cst_ext_raw[cst_cols_to_keep].copy()

  return cst_ext, non_cst_ext, intr


def run_cross_reference():
  ds5 = st.session_state.df_step4
  cm = {col.strip().lower(): col for col in ds5.columns}
  oic = cm.get('order id')
  if not oic:
      st.error("Missing 'Order ID' column for Portal Check.")
      st.stop()

  portal_ids = st.session_state.portal_ids
  ps = set(portal_ids)

  dfc = ds5.copy()
  dfc['_in_portal'] = dfc[oic].astype(str).str.strip().isin(ps)

  matched_df = dfc[dfc['_in_portal'] == True].drop(columns=['_in_portal'])
  unmatched_count = int((dfc['_in_portal'] == False).sum())

  shc2 = cm.get('shipper')
  if shc2 and not matched_df.empty:
      matched_df = matched_df.copy()
      matched_df['_is_cst'] = matched_df[shc2].apply(is_cst_shipper)
      cst_f = matched_df[matched_df['_is_cst'] == True].drop(columns=['_is_cst'])
      non_cst_f = matched_df[matched_df['_is_cst'] == False].drop(columns=['_is_cst'])
  else:
      cst_f = pd.DataFrame(columns=REQUIRED_COLUMNS)
      non_cst_f = matched_df if not matched_df.empty else pd.DataFrame(columns=REQUIRED_COLUMNS)

  st.session_state.cst_final = cst_f
  st.session_state.non_cst_final = non_cst_f
  st.session_state.unmatched_count = unmatched_count
  st.session_state.step = 5
  st.rerun()


def _go_back_one_step():
  cur = int(st.session_state.step or 1)

  if cur == 5:
      st.session_state.step = 4
  elif cur == 4:
      st.session_state.step = 1
  else:
      st.session_state.step = 1

  st.rerun()


def _go_to_hub():
  st.session_state.active_audit = "home"
  for key in RESET_KEYS:
      if key in st.session_state:
          del st.session_state[key]
  st.rerun()


@st.dialog("⚠️ Upload Warning")
def _show_upload_warning(messages):
  for msg in messages:
      st.warning(msg)


def render():
  for k, v in SESSION_DEFAULTS.items():
      if k not in st.session_state:
          st.session_state[k] = v

  if st.session_state.last_step is None:
      st.session_state.last_step = st.session_state.step
  elif st.session_state.step != st.session_state.last_step:
      scroll_to_top()
      st.session_state.last_step = st.session_state.step

  top_left, top_right = st.columns([6, 1])
  with top_left:
      st.title('Uncovered Orders Audit')
      st.caption('Amazon Freight Scheduling Team - Automated Audit Workflow')
  with top_right:
      st.write("")
      st.write("")
      if st.button("Back to Audit Hub"):
          _go_to_hub()

  st.divider()

  visible_step_count = len(VISIBLE_STEP_ORDER)
  current_visible_step_number = VISIBLE_STEP_NUMBER.get(st.session_state.step, 1)
  current_visible_step_label = VISIBLE_STEP_LABELS.get(st.session_state.step, VISIBLE_STEP_LABELS[1])
  pv = (current_visible_step_number - 1) / (visible_step_count - 1)

  st.progress(
      pv,
      text='Step {} of {}: {}'.format(
          current_visible_step_number,
          visible_step_count,
          current_visible_step_label.split('. ', 1)[1]
      )
  )
  st.divider()

  if st.session_state.step == 1:
      left, right = st.columns([3, 2])
      with left:
          st.header('Step 1 - Upload SMC Export File')
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
          "4. Browse file/upload below."
      )

      uploaded = st.file_uploader(
          'Upload your SMC uncovered orders export (.xlsx, .xls, or .csv)',
          type=['xlsx', 'xls', 'csv'],
          key='smc_upload'
      )

      if uploaded is not None:
          try:
              df = load_smc_file(uploaded)
              st.session_state.df_raw = df
              st.success('File loaded: {} orders, {} columns detected.'.format(len(df), len(df.columns)))
              st.dataframe(df.head(10), use_container_width=True)
              st.caption('Showing first 10 of {} rows.'.format(len(df)))

              if st.button('Proceed To Step 2 - Unified Portal Check', type='primary'):
                  formatted = process_step2_backend(df)
                  st.session_state.df_formatted = formatted
                  cst_ext, non_cst_ext, intr = _split_external_internal(formatted)
                  st.session_state.cst_ext = cst_ext
                  st.session_state.non_cst_ext = non_cst_ext
                  st.session_state.df_step4 = intr
                  st.session_state.portal_ids = []
                  st.session_state.arrival_ids_ready = False
                  st.session_state.portal_export_filenames = []
                  st.session_state.step = 4
                  st.rerun()

          except Exception as e:
              st.error('Error reading file: {}. Please check the file and try again.'.format(e))

  elif st.session_state.step == 4:
      st.header('Step 2 - Unified Portal ISA Check')

      ds4 = st.session_state.df_step4
      cm = {col.strip().lower(): col for col in ds4.columns}
      oic = cm.get('order id')
      if not oic:
          st.error("Missing 'Order ID' column for Portal Check.")
          st.stop()

      rids = ds4[oic].dropna().astype(str).str.strip().tolist()
      st.info('{} internal Order IDs need to be checked in the Unified Portal.'.format(len(rids)))

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

      if st.button("Reset Portal Inputs", key="reset_step4"):
          st.session_state.portal_ids = []
          st.session_state.arrival_ids_ready = False
          st.session_state.portal_export_filenames = []
          st.session_state.portal_upload_counter = st.session_state.get("portal_upload_counter", 0) + 1
          st.rerun()

      portal_csvs = st.file_uploader(
          "Upload Unified Portal export CSV file(s). You can upload multiple files (one per 50-ID search batch). "
          "Each CSV must contain columns: searchId and appointmentStatus.",
          type=['csv'],
          accept_multiple_files=True,
          key=f'portal_export_upload_{st.session_state.get("portal_upload_counter", 0)}'
      )

      if portal_csvs:
          all_arrival_ids = []
          per_file_ids = {}
          files_ok = 0
          files_missing_cols = 0
          files_read_error = 0
          zero_arrivals = 0
          filenames = []

          for f in portal_csvs:
              fname = getattr(f, "name", "unknown.csv")
              filenames.append(fname)
              try:
                  raw = f.read()
                  pdf = pd.read_csv(io.BytesIO(raw), dtype=str)

                  arrival_ids = extract_arrival_scheduled_ids_from_unified_portal_csv(pdf)
                  if arrival_ids is None:
                      files_missing_cols += 1
                      continue

                  files_ok += 1
                  per_file_ids[fname] = set(arrival_ids)
                  if len(arrival_ids) == 0:
                      zero_arrivals += 1
                  else:
                      all_arrival_ids.extend(arrival_ids)

              except Exception:
                  files_read_error += 1

          total_before_dedup = len(all_arrival_ids)
          all_arrival_ids = list(dict.fromkeys([x for x in all_arrival_ids if x]))
          duplicates_removed = total_before_dedup - len(all_arrival_ids)

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
              f"0 arrivals: {zero_arrivals} | Arrival Scheduled IDs extracted: {len(all_arrival_ids)}{dedup_note}"
          )

          with st.expander("Show uploaded filenames"):
              st.write(filenames)

          if len(all_arrival_ids) == 0:
              st.session_state.portal_ids = []
              st.session_state.arrival_ids_ready = False
              st.session_state.portal_export_filenames = filenames
              st.warning("No 'Arrival Scheduled' rows were found across the uploaded file(s).")
          else:
              st.session_state.portal_ids = all_arrival_ids
              st.session_state.arrival_ids_ready = True
              st.session_state.portal_export_filenames = filenames
              st.success(
                  f"Done. Combined {len(all_arrival_ids)} unique 'Arrival Scheduled' Order IDs "
                  f"from {files_ok} CSV file(s)."
              )
              with st.expander("Preview extracted Arrival Scheduled IDs"):
                  st.caption("One-click copy via copy icon (top-right of code box)")
                  st.code("\n".join(all_arrival_ids), language=None)


      st.divider()
      ready = bool(st.session_state.arrival_ids_ready and len(st.session_state.portal_ids) > 0)
      if ready:
          st.info("Arrival Scheduled Order IDs are ready. You can now run the final cross-reference.")

      c1, c2 = st.columns(2)
      with c1:
          if st.button('Back a step'):
              _go_back_one_step()
      with c2:
          run_clicked = st.button(
              'Run Cross-Reference and Produce Final Results',
              type='primary',
              disabled=(not ready)
          )

      if run_clicked:
          run_cross_reference()

  elif st.session_state.step == 5:
      st.header('Step 3 - Audit Complete')
      st.balloons()

      # Internal orders matched from portal
      cf_internal = st.session_state.cst_final if st.session_state.cst_final is not None else pd.DataFrame(columns=REQUIRED_COLUMNS_CST)
      ncf_internal = st.session_state.non_cst_final if st.session_state.non_cst_final is not None else pd.DataFrame(columns=REQUIRED_COLUMNS)
      uc = int(st.session_state.unmatched_count or 0)

      # External orders from earlier split
      cst_ext = st.session_state.cst_ext if st.session_state.cst_ext is not None else pd.DataFrame(columns=REQUIRED_COLUMNS_CST)
      non_cst_ext = st.session_state.non_cst_ext if st.session_state.non_cst_ext is not None else pd.DataFrame(columns=REQUIRED_COLUMNS)

      # Combine: external first, then internal
      cf_internal_clean = drop_if_exists(cf_internal, 'Destination Stop Facility Name')
      cst_combined = pd.concat([cst_ext, cf_internal_clean], ignore_index=True)
      non_cst_combined = pd.concat([non_cst_ext, ncf_internal], ignore_index=True)

      total_cst = len(cst_combined)
      total_non_cst = len(non_cst_combined)

      ext_cst = len(cst_ext)
      ext_non_cst = len(non_cst_ext)
      int_cst = len(cf_internal_clean)
      int_non_cst = len(ncf_internal)

      c1, c2, c3 = st.columns(3)
      c1.metric('Total Uncovered Orders', total_cst + total_non_cst)
      c2.metric('CST Orders', total_cst)
      c3.metric('Non-CST Orders', total_non_cst)

      c1, c2, c3 = st.columns(3)
      c1.markdown(f'**External:** {ext_cst + ext_non_cst} &nbsp;|&nbsp; **Inbound:** {int_cst + int_non_cst}')
      c2.markdown(f'**External:** {ext_cst} &nbsp;|&nbsp; **Inbound:** {int_cst}')
      c3.markdown(f'**External:** {ext_non_cst} &nbsp;|&nbsp; **Inbound:** {int_non_cst}')

      st.divider()
      cst_copy = make_copy_block(cst_combined, exclude_cols=['Created by'])
      st.markdown(
          '<a href="https://amazongbr.sharepoint.com/sites/AmazonFreightOperations/Shared%20Documents/Forms/AllItems.aspx?csf=1&web=1&e=ZGRKFP&CID=05b9c2ec%2D9a50%2D439d%2D88c4%2D230ddf9f4411&FolderCTID=0x012000F123BBE5033B5E40BE7845C90C7F488D&id=%2Fsites%2FAmazonFreightOperations%2FShared%20Documents%2FCST%2FCST%20Operations%2FCST%20Scheduling%2FMonthly%20task%20sheets" target="_blank" '
          'style="display:inline-block; padding:0.4rem 1rem; border-radius:0.5rem; '
          'border:2px solid #3b82f6; background:rgba(59,130,246,0.12); color:#1d4ed8; '
          'font-size:0.95rem; font-weight:700; text-decoration:none;">Open CST Task Sheet ↗</a>',
          unsafe_allow_html=True,
      )
      render_table_with_copy(
          title='CST Orders - copy to CST Task Sheet (Uncovered tab)',
          df=cst_combined,
          copy_text=cst_copy,
          button_text='Copy to CST Sheet'
      )

      ncf_copy = make_copy_block(non_cst_combined, exclude_cols=['Created by'])
      st.markdown(
          '<a href="https://amazongbr.sharepoint.com/sites/AmazonFreightOperations/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FAmazonFreightOperations%2FShared%20Documents%2FFTL%20Scheduling%2FScheduling%2FDaily%20Tasks%20Sheet&viewid=d2bea389%2Dda72%2D4ca8%2D8673%2D77ae91430301" target="_blank" '
          'style="display:inline-block; padding:0.4rem 1rem; border-radius:0.5rem; '
          'border:2px solid #3b82f6; background:rgba(59,130,246,0.12); color:#1d4ed8; '
          'font-size:0.95rem; font-weight:700; text-decoration:none;">Open Scheduling Task Sheet ↗</a>',
          unsafe_allow_html=True,
      )
      render_table_with_copy(
          title='Non-CST Orders - copy to AF Scheduling Daily Task Workbook (Uncovered tab)',
          df=non_cst_combined,
          copy_text=ncf_copy,
          button_text='Copy to Scheduling Sheet'
      )

      st.divider()
      st.warning(
          "FINAL ACTION REQUIRED\n"
          "1. Copy CST Orders to the CST Task Sheet (Uncovered tab).\n"
          "2. Copy Non-CST Orders to the AF Scheduling Daily Task Workbook (Uncovered tab).\n"
          "Audit complete!"
      )

      st.divider()
      if st.button('Start a New Audit', type='primary'):
          for k in RESET_KEYS:
              if k in st.session_state:
                  del st.session_state[k]
          for k, v in SESSION_DEFAULTS.items():
              if k not in st.session_state:
                  st.session_state[k] = v
          st.session_state.step = 1
          st.rerun()