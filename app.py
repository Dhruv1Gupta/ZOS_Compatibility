"""
z/OS Product Compatibility Dashboard (Streamlit)

Tab 1  z/OS Version      : choose the z/OS version -> compatibility matrix for IBM, Broadcom, BMC,
                           Rocket, Precisely, ASG (compatible? PTF required? EOS, latest version) -> Excel
Tab 2  Check my products : pick vendor / product / your existing VRM (or upload an inventory) -> verdict -> Excel
Tab 3  Ask               : plain-English questions answered from the matrix rows
Tab 4  Sources           : official vendor links (all clickable)

Run locally:   pip install -r requirements.txt
               streamlit run app.py
Answer service (optional): local Ollama running Granite or Llama (no API key needed).
"""

import os
from datetime import datetime

import pandas as pd
import streamlit as st

from compatibility_db import (FIXCAT_CSS, PTF_CSS, SOURCES, VENDORS, VER, ZOS_VERSIONS, CompatibilityDB, build_excel,
                              fixcat_template, ptf_css, ptf_worklist, smpe_template, to_output, unique_fixcats,
                              unique_ptf_ids)
from rag_engine import DEFAULT_MODEL, RagIndex, generate_answer, llm_available

st.set_page_config(page_title="z/OS Product Compatibility", page_icon="🖥️", layout="wide")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LINK_COL = st.column_config.LinkColumn("Open link", display_text="Open ↗")
ALL_STATUS = ["Yes", "No", "In Progress", "Unverified", "N/A", "Unknown"]


# ------------------------------------------------------------------ data
@st.cache_resource
def load_base() -> CompatibilityDB:
    return CompatibilityDB.load(DATA_DIR)


def get_db() -> CompatibilityDB:
    return load_base().merged_with(st.session_state.get("extra"))


PTF_COL = "If Yes, PTF Required?"


def _color_ptf(series: pd.Series):
    return [ptf_css(v) for v in series]


def show_table(d: pd.DataFrame, version: str, height: int = 420):
    """Matrix table. PTF cell: YELLOW = PTFs/usermods required, ORANGE = use the vendor FIXCAT, none = no / unknown."""
    out = to_output(d, with_link_column=True, version=version)
    st.dataframe(
        out.style.apply(_color_ptf, subset=[PTF_COL]),
        width="stretch", hide_index=True, height=height,
        column_config={"Open link": LINK_COL,
                       "Comments / Links": st.column_config.TextColumn(width="large")},
    )


def ptf_section(d: pd.DataFrame, version: str, key: str, expanded: bool = False):
    """Worklist for ALL vendors: PTF IDs where published (yellow) and the SMP/E FIXCAT to run where not (orange)."""
    wl = ptf_worklist(d, version)
    ids, cats = unique_ptf_ids(d, version), unique_fixcats(d, version)
    with st.expander(f"🟨🟧 PTF / usermod worklist for z/OS {version}: {len(wl)} product(s), "
                     f"{len(ids)} PTF ID(s), {len(cats)} FIXCAT(s)", expanded=expanded and not wl.empty):
        if wl.empty:
            st.info("No PTFs, usermods or FIXCATs are listed for these products on this z/OS version.")
            return
        st.caption("🟨 **PTF IDs**: the vendor publishes the PTFs / usermods, so they are listed.  "
                   "🟧 **FIXCAT**: the vendor delivers them as an SMP/E fix category, so SMP/E lists what your zone is missing.")

        def paint(row: pd.Series):
            css = PTF_CSS if row["Type"].startswith("PTF") else FIXCAT_CSS
            return [css if c == "PTFs / Usermods / FIXCAT" else "" for c in row.index]

        st.dataframe(
            wl.style.apply(paint, axis=1),
            width="stretch", hide_index=True, height=min(60 + 36 * len(wl), 420),
            column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗"),
                           "Details": st.column_config.TextColumn(width="large")},
        )
        if ids:
            st.text_area("All PTF / usermod IDs (copy)", ", ".join(ids), height=90, key=f"{key}_ids")
            c1, c2 = st.columns(2)
            c1.download_button("⬇️ PTF list (.txt)", "\n".join(ids), file_name=f"zOS_{version}_ptf_list.txt",
                               mime="text/plain", key=f"{key}_txt")
            c2.download_button("⬇️ SMP/E PTF template (.txt)", smpe_template(ids),
                               file_name=f"zOS_{version}_smpe_ptf_template.txt", mime="text/plain", key=f"{key}_smpe")
            with st.expander("SMP/E RECEIVE / APPLY CHECK template for the PTF IDs (review before use)"):
                st.code(smpe_template(ids), language="text")
        if cats:
            c3, _ = st.columns(2)
            c3.download_button("⬇️ SMP/E FIXCAT report template (.txt)", fixcat_template(cats),
                               file_name=f"zOS_{version}_smpe_fixcat_report.txt", mime="text/plain", key=f"{key}_fix")
            with st.expander("SMP/E REPORT MISSINGFIX template for the FIXCATs (review before use)", expanded=not ids):
                st.code(fixcat_template(cats), language="text")
        st.caption("Rows with 'see Details / vendor link' have no PTF numbers or FIXCAT in the data. Open the link or ask the vendor.")


def metrics(d: pd.DataFrame, db: CompatibilityDB, version: str):
    s = db.summarize(d, version)
    c = st.columns(7)
    c[0].metric("Products", s["total"])
    c[1].metric("✅ Compatible", s["yes"])
    c[2].metric("🟨 Need PTFs", s["ptf"])
    c[3].metric("🟧 FIXCAT check", s["fixcat"])
    c[4].metric("⛔ Not compatible", s["no"])
    c[5].metric("⏳ In progress", s["in_progress"])
    c[6].metric("❔ Unverified", s["unverified"])


try:
    db = get_db()
except FileNotFoundError as e:
    st.error(f"Data files not found. {e}")
    st.stop()

use_llm = llm_available()

# ------------------------------------------------------------------ header + sidebar
st.title("🖥️ z/OS Product Compatibility")
st.caption("Choose a z/OS version to see which vendor products are compatible and whether a PTF is required.")

with st.sidebar:
    st.subheader("Data coverage")
    _sv = st.session_state.get("zos_ver", ZOS_VERSIONS[0])
    verified = int((~db.df[VER[_sv][0]].isin(["Unverified", "Unknown"])).sum())
    st.metric(f"Rows with a z/OS {_sv} statement", f"{verified} / {len(db.df)}")
    st.caption("Others are marked **Unverified** until a vendor statement is added.")
    st.divider()
    st.caption("🟨 **Yellow** = PTFs / usermods required (IDs listed)")
    st.caption("🟧 **Orange** = PTFs via vendor FIXCAT (SMP/E lists them)")
    st.caption(f"🟢 Local AI answers: {DEFAULT_MODEL}" if use_llm else "⚪ Local AI off (start Ollama for written answers)")

tab_ver, tab_check, tab_ask, tab_src = st.tabs(
    ["1 · z/OS Version", "2 · Check my products", "3 · Ask", "4 · Sources"]
)

# ================================================================== TAB 1 : z/OS version
with tab_ver:
    v1, v2 = st.columns([1, 3])
    ver = v1.selectbox("z/OS version", ZOS_VERSIONS, key="zos_ver",
                       help="Choose z/OS 3.2, 3.1 or 2.5. Rows with no vendor statement for a version show Unverified.")
    vendors = v2.multiselect("Vendors", VENDORS, default=VENDORS, key="ver_vendors")

    f1, f2, f3 = st.columns([2, 2, 3])
    status = f1.multiselect(f"R{ver} compatible", ALL_STATUS, default=ALL_STATUS, key="ver_status")
    ptf = f2.selectbox("PTF", ["Any", "PTF required", "Check FIXCAT", "No PTF needed", "Not published / unknown"], key="ver_ptf")
    q = f3.text_input("Search", key="ver_q", placeholder="product, VRM, comment…")
    breaking = False
    prev_ver = VER[ver][3]
    if prev_ver:
        breaking = st.checkbox(f"Only products that work on z/OS {prev_ver} but not on {ver}", key=f"ver_break_{ver}")

    view = db.filter(vendors, status, None if ptf == "Any" else ptf, breaking, q, version=ver)
    st.markdown(f"#### Products for z/OS {ver}")
    metrics(view, db, ver)
    show_table(view, ver, height=520)
    ptf_section(view, ver, key="ver")

    book = {f"zOS {ver} - All Vendors": db.df}
    for v in VENDORS:
        d = db.df[db.df["vendor"] == v]
        if not d.empty:
            book[v] = d
    c1, c2 = st.columns(2)
    c1.download_button(f"⬇️ Download z/OS {ver} workbook (all vendors)", build_excel(book, version=ver),
                       file_name=f"zOS_{ver}_compatibility.xlsx", mime=XLSX, type="primary", key="ver_dl_all")
    c2.download_button("⬇️ Download current filtered view", build_excel({"Filtered": view}, version=ver),
                       file_name=f"zOS_{ver}_filtered.xlsx", mime=XLSX, key="ver_dl_view")
    st.caption("Excel links are real hyperlinks: click the Comments / Links cell (or the Sources sheet) to open the vendor page. "
               "If Excel opens the file in Protected View, click Enable Editing first.")

    with st.expander("➕ Add or correct data (upload a CSV with the same columns as data/*.csv)"):
        st.write("Rows are matched on Vendor + Product + VRM and override the built-in data for this session. "
                 "To make them permanent, edit the CSV files in `data/` and redeploy.")
        upd = st.file_uploader("CSV", type=["csv"], key="ver_upd")
        if upd is not None and st.button("Apply uploaded data", key="ver_apply"):
            try:
                st.session_state["extra"] = pd.read_csv(upd, dtype=str, keep_default_na=False)
                st.rerun()
            except Exception as e:
                st.error(f"Could not read the file: {e}")

# ================================================================== TAB 2 : check my products
with tab_check:
    cver = st.session_state.get("zos_ver", ZOS_VERSIONS[0])
    st.markdown(f"#### Check your existing products against z/OS {cver}")
    st.caption("The z/OS version follows your choice on the first tab.")
    vendors2 = st.multiselect("Vendors", VENDORS, default=VENDORS, key="chk_vendors")
    pool = db.df[db.df["vendor"].isin(vendors2)]
    picked = st.multiselect(f"Products and existing versions ({len(pool)} available)", pool["label"].tolist(),
                            placeholder="Search e.g. 'Endevor', 'CICS', 'MFX' ...  (Vendor | Product | VRM)",
                            key="chk_picked")
    up = st.file_uploader("…or upload your product inventory (CSV/XLSX with columns Vendor, Product, VRM)",
                          type=["csv", "xlsx"], key="chk_inv")

    chosen = db.df[db.df["label"].isin(picked)]
    misses = []
    if up is not None:
        try:
            inv = (pd.read_csv(up, dtype=str, keep_default_na=False) if up.name.lower().endswith(".csv")
                   else pd.read_excel(up, dtype=str, keep_default_na=False))
            matched, misses = db.match_inventory(inv)
            chosen = pd.concat([chosen, matched], ignore_index=True).drop_duplicates(subset=["vendor", "product", "vrm"])
        except Exception as e:
            st.error(f"Could not read the inventory: {e}")

    if chosen.empty:
        st.info("Select at least one product above (or upload an inventory) to see the answer.")
    else:
        st.markdown("#### Result")
        metrics(chosen, db, cver)
        s = db.summarize(chosen, cver)
        scol = VER[cver][0]
        blockers = chosen[chosen[scol] == "No"]
        if not blockers.empty:
            st.error(f"{len(blockers)} selected product(s) are NOT compatible with z/OS {cver} and need an upgrade first: "
                     + "; ".join(f"{r.product} {r.vrm}" for r in blockers.itertuples()))
        if s["ptf"]:
            st.warning(f"{s['ptf']} compatible product(s) need PTFs applied (yellow).")
        if s["fixcat"]:
            st.info(f"{s['fixcat']} product(s) get their PTFs through a vendor FIXCAT (orange). "
                    "Use the SMP/E REPORT MISSINGFIX template in the worklist below.")
        if s["unverified"]:
            st.info(f"{s['unverified']} product(s) have no vendor statement in the data yet. Open their link and confirm.")
        if s["no"] == 0 and s["unverified"] == 0 and s["in_progress"] == 0:
            st.success(f"All selected products are compatible with z/OS {cver}." +
                       (" Apply the listed PTFs first." if s["ptf"] else " No PTFs required." if not s["fixcat"] else " Check the FIXCATs below."))
        show_table(chosen, cver)
        ptf_section(chosen, cver, key="chk", expanded=True)
        for m in misses:
            st.caption("⚠️ " + m)
        xl = build_excel(
            {f"My Products z{cver}": chosen, "Full Matrix": db.df},
            notes=[f"Generated {datetime.now():%Y-%m-%d %H:%M}. First sheet = your selection; 'Full Matrix' = everything."],
            version=cver,
        )
        st.download_button("⬇️ Download Excel (my products + full matrix)", xl,
                           file_name=f"zOS_{cver}_my_products.xlsx", mime=XLSX, type="primary", key="chk_dl")

# ================================================================== TAB 3 : ask
with tab_ask:
    st.markdown("Ask in plain English, e.g. *Which Broadcom products are not supported on z/OS 3.2?* "
                "or *Does Endevor 18.1 need PTFs?*")
    question = st.text_input("Question", key="ask_q")
    k = st.slider("Rows to retrieve", 5, 30, 12, key="ask_k")
    ask_ver = st.session_state.get("zos_ver", ZOS_VERSIONS[0])
    if question:
        rows = RagIndex.build(db.df).retrieve(question, k)
        if rows.empty:
            st.warning("No matching rows. Try a product name or vendor.")
        else:
            answered = False
            if use_llm:
                with st.spinner("Preparing answer…"):
                    try:
                        st.markdown(generate_answer(question, rows))
                        answered = True
                    except Exception:
                        st.info("The written answer is unavailable right now. The matching rows are shown below.")
            else:
                st.info("Showing the matching rows.")
            with st.expander("Matching rows", expanded=not answered):
                show_table(rows, ask_ver, height=320)

# ================================================================== TAB 4 : sources
with tab_src:
    st.markdown("Official places to confirm compatibility, PTFs, EOS dates and latest versions.")
    for v in VENDORS:
        items = [s for s in SOURCES if s[0] == v]
        if not items:
            continue
        st.markdown(f"**{v}**")
        for _, name, url, what in items:
            a, b = st.columns([6, 1])
            a.markdown(f"{name}  \n<small>{what}</small>", unsafe_allow_html=True)
            b.link_button("Open ↗", url)
        st.divider()

st.caption("Always confirm on the live vendor page before production changes.")
