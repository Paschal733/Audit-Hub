import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import re
import io
import unicodedata
import html
import uuid

UNIFIED_PORTAL_URL = "https://unified-portal-eu.corp.amazon.com/#/appointment?searchType=PRO&searchCategory=appointment&searchIds=&searchIds=9524366171"

CST_SHIPPERS = [
   'Amazon Business','AEG Electrolux Hausgeräte GmbH',
   'Anheuser-Busch InBev Deutschland GmbH & Co KG',
   'ARTSANA S.P.A.',
   'Brita France',
   'BRITA SE - Shipments Beselich',
   'Brita Italia s.r.l. Unipersonale',
   'Coyote Logistics UK Ltd',
   'Danone UK',
   'DANONE IT SN',
   'Danone UK SN',
   'DELONGHI APPLIANCES',
   'Electrolux Hausgeräte GmbH',
   'Fressnapf Logistics Management GmbH',
   'Hachette UK Distribution',
   'HarperCollins Publishers Ltd',
   'Hisense UK',
   'Howard Tenens',
   'Eddie Stobart (Appleton Culina House- Culina Group)',
   'Eddie Stobart (Appleton Culina House- Culina Group) Unilever',
   'Geodis D&E Normandie',
   'Great Bear Distribution MV1',
   'Great Bear Port Salford Mars',
   'H.J. Heinz BV',
   'home24 eLogistics GmbH & Co. KG',
   'Hoover Ltd',
   'iRobot UK Ltd',
   'JACOBS DOUWE EGBERTS GB LTD',
   'Kellogg Marketing And Sales Company (UK) Limited',
   'Keter Italia S.p.A.',
   'Keter Iberia S.L.U',
   'Keter Germany Gmbh',
   'Keter France Sas',
   'Mars PF France',
   'Mars GmbH (CBT-DE)',
   'Mars GmbH FLOERSHEIM',
   'Mars GmbH MINDEN',
   'Messaggerie Libri Spa',
   'Mömax Logistik GmbH',
   'Mondi Logistik GmbH',
   'Nestlé Enterprises SA, Business Growth Solutions Division',
   'Nestlé UK',
   'Nestrade S.A. T-Hub Central',
   'Nestrade SA (t-hub North)',
   'Nestrade S.A. T-Hub South',
   'Nestrade T-hub West',
   'PepsiCo Deutschland GmbH',
   'Procter & Gamble International Operations SA',
   'REHAU Industries SE & Co. KG',
   'Robert Bosch Power Tools GmbH',
   'Skechers EDC',
   'SharkNinja Europe Ltd',
   'SharkNinja Germany Gmbh',
   'Schlaadt HighCut GmbH',
   'S.L. Systemlogistik GmbH',
   'Soffass spa',
   'Sofidel Germany GmbH',
   'Sofidel France SAS',
   'Sofidel Spain',
   'Sofidel UK',
   'tegut… gute Lebensmittel GmbH & Co. KG',
   'Tetra GmbH',
   'The Book Service Limited',
   'Unilever Europe B.V. (UK)',
   'Unilever Europe B.V. (DE)',
   'Unilever Europe B.V. (EU)',
   'Vendor Returns',
   'Versuni Nederland B.V',
   'Walkers Snacks Distribution Ltd',
   'Wincanton (J SAINSBURY PLC)',
   'Yankee Candle Co (Europe) LTD',
   'Yankee Candle Co - DE',
   'Zeitfracht Medien GmbH',
   'Danone Deutschland GmbH',
   'Danone UK Waters',
   'Danone FR',
   'Wacker Chemie AG',
   'Sharp Consumer Electronics Poland sp. z o.o.',
   'Cargill Poland Sp. z o.o.',
   'Nitto Advanced Film Gronau GmbH',
   'Cargill S.L.U.',
   'Coca-Cola Europacific Partners Deutschland GmbH',
   'Bio Springer',
   'La Palette Rouge Iberica s.a. succ.le in Italia',
   'COLGATE PALMOLIVE EUROPE',
   'ECOSCOOTING DELIVERY SL',
   'EDT BE SRL (TEMU)',
   "L 'Oreal Italy",
   'Hager Electro SAS',
   'Heineken Deutschland GmbH',
   'Euro Pool System UK Ltd',
   '3M EMEA GmbH',
   'Falken Tyre Europe GmbH',
   'SACHSENMILCH Leppersdorf GmbH',
   'XPO Transport Solutions UK Limited',
   'La Palette Rouge Iberica Sa',
   'LPR - LA PALETTE ROUGE (GB) LTD',
   'BONDUELLE RE',
   'HARIBO Sp. z o.o.',
   'Groupe SEB WMF Consumer GmbH',
   'HOYER GmbH Internationale Fachspedition',
   'BLACK & DECKER LIMITED BV',
   'Cycleon B.v.',
   'Wella International Operations Switzerland Sarl',
   'INTERFORUM',
   'Beiersdorf Customer Supply GmbH',
   'BDSK Handels GmbH & Co.KG',
   'DGL- Ingram (KSP) ES',
   'JYSK SE',
   'Mars Multisales Spain S.L.',
   'Mars Food Europe CV',
   'Nestrade SA',
   'Philips Consumer Lifestyle BV',
   'Pregis Ltd',
   'TYRE ECO CHAIN',
   'Zalando SE',
   'Tchibo GmbH',
   'Nagel-Group Logistics SE',
   'Nagel-Goup Logistics SE',
]

_STOPWORDS = {
   'the', 'and', 'for', 'von', 'van', 'de', 'di', 'du', 'der', 'gmbh', 'bv', 'sa', 'ltd', 'llc', 'inc', 'co',
   'kg', 'spa', 'sas', 'sl', 'nv', 'ag', 'plc', 'ug', 'bvba', 'srl', 'spzoo'
}


AMAZON_ALIAS_PATTERN = re.compile(r'^[a-z]{5,8}$')
FC_PATTERN = re.compile(r'^(?:[A-Z]{3}\d|[A-Z]{4})$')

# ── Shared Helper Functions ─────────────────────────────────────────────

def _de_umlaut_fold(s: str) -> str:
   if not isinstance(s, str):
       return ""
   s = (
       s.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
        .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
        .replace("ß", "ss")
   )
   s = unicodedata.normalize("NFKD", s)
   s = "".join(ch for ch in s if not unicodedata.combining(ch))
   return s


def _normalise(s):
   if not isinstance(s, str):
       return ''
   s = _de_umlaut_fold(s)
   s = re.sub(r'[^\w\s]', '', s)
   s = re.sub(r'\s+', ' ', s)
   return s.strip().lower()


def _core_tokens(s):
   s = _de_umlaut_fold(str(s))
   words = re.sub(r'[^\w\s]', ' ', s).lower().split()
   return frozenset(w for w in words if len(w) > 2 and w not in _STOPWORDS)


_CST_EXACT = set(s.strip().lower() for s in CST_SHIPPERS)
_CST_FUZZY = set(_normalise(s) for s in CST_SHIPPERS)
_CST_TOKENS = [_core_tokens(s) for s in CST_SHIPPERS]


def is_cst_shipper(name):
   if not isinstance(name, str) or not name.strip():
       return False
   if name.strip().lower() in _CST_EXACT:
       return True
   if _normalise(name) in _CST_FUZZY:
       return True
   t = _core_tokens(name)
   if len(t) < 2:
       return False
   for ct in _CST_TOKENS:
       if not ct:
           continue
       ov = len(t & ct)
       if ov >= 2 and ov / len(t) >= 0.8:
           return True
   return False


def is_fc_facility(name):
   if not isinstance(name, str):
       return False
   return bool(FC_PATTERN.match(name.strip()))


def classify_source(created_by):
   if not isinstance(created_by, str):
       return 'R4S'
   return 'SMC' if AMAZON_ALIAS_PATTERN.match(created_by.strip()) else 'R4S'


def load_smc_file(f):
   raw = f.read()
   if raw[:6] == b'Sheet0' or raw[:5] == b'Sheet':
       df = pd.read_csv(io.BytesIO(raw), sep='\t', dtype=str, skiprows=1)
       if 'Unnamed: 0' in df.columns:
           df = df.drop(columns=['Unnamed: 0'])
       return df
   return pd.read_excel(io.BytesIO(raw), dtype=str, engine='openpyxl')


def reset_index_display(df):
   df = df.copy().reset_index(drop=True)
   df.index = df.index + 1
   return df


def drop_if_exists(df, col_name):
   if df is None or df.empty:
       return df
   if col_name in df.columns:
       return df.drop(columns=[col_name])
   return df


@st.cache_data(show_spinner=False)
def _make_copy_block_cached(df: pd.DataFrame, exclude_cols: tuple[str, ...]) -> str:
   if df is None or df.empty:
       return ""
   out = df.copy()
   for c in exclude_cols:
       if c in out.columns:
           out = out.drop(columns=[c])
   out = out.fillna("")
   lines = ["\t".join(map(str, row)) for row in out.to_numpy()]
   return "\n".join(lines)


def make_copy_block(df: pd.DataFrame, exclude_cols: list[str]) -> str:
   return _make_copy_block_cached(df, tuple(exclude_cols))


def render_inline_copy_button(text: str, button_text: str = "Copy"):
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
                           if (ok) {{
                               showCopied();
                           }} else {{
                               showFailed();
                           }}
                       }} catch (e) {{
                           showFailed();
                       }}
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


def render_table_with_copy(title: str, df: pd.DataFrame, copy_text: str, button_text: str):
   left, right = st.columns([6, 1])

   with left:
       st.subheader(title)

   with right:
       if df is not None and not df.empty and copy_text:
           render_inline_copy_button(copy_text, button_text=button_text)

   st.dataframe(reset_index_display(df), use_container_width=True)


def render_portal_link(url: str):
   safe_url = html.escape(url, quote=True)
   components.html(
       f"""
       <div style="display:flex; justify-content:center; margin: 0.35rem 0 0.9rem 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
           <a
               href="{safe_url}"
               target="_blank"
               style="
                   display:inline-block;
                   text-decoration:none;
                   padding: 0.55rem 1rem;
                   border-radius: 0.6rem;
                   border: 1px solid #3b82f6;
                   background: rgba(59,130,246,0.14);
                   color: #1d4ed8;
                   font-weight: 600;
                   font-size: 0.95rem;
                   text-align:center;
               "
           >
               Open Unified Portal
           </a>
       </div>
       """,
       height=60,
   )


def render_portal_batch_card(label: str, subtitle: str, text: str, button_text: str = "Copy Batch", box_height: int = 260):
   if not text:
       return

   btn_id = f"portal_copy_btn_{uuid.uuid4().hex}"
   text_id = f"portal_copy_text_{uuid.uuid4().hex}"
   safe_label = html.escape(label)
   safe_subtitle = html.escape(subtitle)
   safe_text = html.escape(text)
   safe_button_text = html.escape(button_text)

   components.html(
       f"""
       <div style="margin-bottom: 0.75rem; max-width: 220px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
           <div
               style="
                   width: 100%;
                   background: #1f2937;
                   border-radius: 0.7rem;
                   padding: 0.9rem 1rem 1rem 1rem;
                   box-sizing: border-box;
               "
           >
               <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.65rem; gap:0.5rem;">
                   <div>
                       <div style="font-weight:700; font-size:1rem; color:#f9fafb; margin-bottom:0.18rem;">{safe_label}</div>
                       <div style="font-size:0.95rem; color:#d1d5db;">{safe_subtitle}</div>
                   </div>

                   <div style="flex-shrink:0;">
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
                                       if (ok) {{
                                           showCopied();
                                       }} else {{
                                           showFailed();
                                       }}
                                   }} catch (e) {{
                                       showFailed();
                                   }}
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
                               padding: 0.3rem 0.65rem;
                               border-radius: 0.5rem;
                               border: 1px solid #999;
                               cursor: pointer;
                               background: #f0f2f6;
                               font-size: 0.85rem;
                               font-weight: 500;
                               white-space: nowrap;
                               color: #111827;
                           "
                       >
                           {safe_button_text}
                       </button>
                   </div>
               </div>

               <div
                   style="
                       width: 100%;
                       height: {box_height}px;
                       overflow-y: auto;
                       overflow-x: hidden;
                       background: rgba(255,255,255,0.04);
                       border-radius: 0.6rem;
                       padding: 0.95rem 1rem;
                       box-sizing: border-box;
                       font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
                       font-size: 0.98rem;
                       line-height: 1.55;
                       white-space: pre;
                       color: #f9fafb;
                   "
               >{safe_text}</div>
           </div>
       </div>
       """,
       height=box_height + 120,
   )


def render_wrapped_batches(batch_texts, per_row=6, box_height=260):
   import math
   if not batch_texts:
       return
   per_row = max(1, int(per_row))
   rows = math.ceil(len(batch_texts) / per_row)
   idx = 0
   for _ in range(rows):
       cols = st.columns(per_row)
       for c in range(per_row):
           if idx >= len(batch_texts):
               break
           b = batch_texts[idx]
           with cols[c]:
               render_portal_batch_card(
                   label=b["label"],
                   subtitle=b["subtitle"],
                   text=b["text"],
                   button_text="Copy Batch",
                   box_height=box_height
               )
           idx += 1


def scroll_to_top():
   components.html(
       """
       <script>
         const main = window.parent.document.querySelector('section.main');
         if (main) { main.scrollTo(0,0); }
         window.parent.scrollTo(0,0);
       </script>
       """,
       height=0
   )


