"""Run with:  python tests/test_project.py   (or: pytest tests)"""
import glob
import os
import shutil
import sys
import tempfile

import pandas as pd
from openpyxl import load_workbook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from compatibility_db import (FIXCAT_FILL, PTF_FILL, CompatibilityDB, build_excel, extract_fixcats,  # noqa: E402
                              extract_ptf_ids, fixcat_template, needs_ptf, ptf_state, ptf_worklist,
                              unique_fixcats, unique_ptf_ids)
import apply_ptf_sources  # noqa: E402
import import_xlsx  # noqa: E402

REF = os.path.join(ROOT, "tests", "reference_zOS_3_2_filtered.xlsx")
DB = CompatibilityDB.load(os.path.join(ROOT, "data"))
D = DB.df


def _fill(cell):
    return (cell.fill.fgColor.rgb or "")[-6:] if cell.fill.fill_type else None


def test_loads_all_rows():
    assert len(D) == 240
    assert set(D.vendor) == {"ASG", "BMC", "Broadcom", "IBM", "Precisely", "Rocket"}


def test_states():
    assert ptf_state("Yes - LU1") == "yes" and ptf_state("Check FIXCAT - X") == "check"
    assert ptf_state("No") == "no" and ptf_state("N/A (3.2 support in progress)") == "na"
    for t in ("Verify", "Not stated - x", "Not found publicly - x", ""):
        assert ptf_state(t) == "unknown", t


def test_extract_ids_and_fixcats():
    assert extract_ptf_ids("Yes - LU18313 (corrects PE PTF LU18249); LU19547 if IGGDAU01 has RMID UJ98216") == ["LU18313", "LU19547"]
    assert extract_ptf_ids("also LU05157/58/59 prerequisites") == ["LU05157", "LU05158", "LU05159"]
    assert extract_ptf_ids("Yes - ESP 12.0.08 maintenance level") == []
    assert extract_fixcats("Check FIXCAT - IBM.TargetSystem-RequiredService.z/OS.3.2 (x)") == ["IBM.TargetSystem-RequiredService.z/OS.3.2"]
    assert extract_fixcats("Yes - LU1 (Broadcom FIXCAT list (CA.TargetSystem-RequiredService.z/OS.V3R2))") == ["CA.TargetSystem-RequiredService.z/OS.V3R2"]


def test_every_vendor_shows_ptf_information_for_32():
    """The reported bug: only Broadcom had PTF information. No vendor may be left with a bare 'Verify'."""
    for vendor, g in D.groupby("vendor"):
        bare = g[g.ptf_required.str.strip().str.lower().isin(["verify", "", "not stated"])]
        assert bare.empty, (vendor, bare[["product", "ptf_required"]].values.tolist())
    for vendor in ("IBM", "BMC"):
        g = D[D.vendor == vendor]
        assert (g.ptf_required.map(ptf_state) == "check").all(), vendor
        assert g.ptf_required.map(extract_fixcats).map(len).min() == 1
    for vendor in ("IBM", "BMC"):                      # 3.1 and 2.5 columns too
        g = D[D.vendor == vendor]
        assert (g.ptf_required_31.map(ptf_state) == "check").all()
        assert (g.ptf_required_25.map(ptf_state) == "check").all()
    iron = D[D["product"].str.contains("Ironstream")].iloc[0]
    assert needs_ptf(iron.ptf_required) and extract_ptf_ids(iron.ptf_required) == ["SDF21QS", "SDF21R0"]
    assert "IBM.TargetSystem-RequiredService.z/OS.3.2" in D[D.vendor == "IBM"].iloc[0].ptf_required
    assert "BMC.TargetSystem-RequiredService.z/OS.V3R2" in D[D.vendor == "BMC"].iloc[0].ptf_required


def test_broadcom_ptf_data_unchanged_vs_reference():
    ws = load_workbook(REF)["Filtered"]
    key = {(r.vendor, r["product"], r.vrm): r for _, r in D.iterrows()}
    for row in range(2, ws.max_row + 1):
        v, p, vrm, st, ptf = (str(ws.cell(row, c).value) for c in range(1, 6))
        r = key[(v, p, vrm)]
        assert r.zos32 == st
        if ptf_state(ptf) != "unknown":
            assert r.ptf_required == ptf, (p, vrm)


def test_four_rows_that_used_to_say_no_now_need_ptfs():
    for prod, vrm in [("Compress Data Compression", "5.5"), ("Earl", "6.1"),
                      ("ESP Workload Automation", "12.0"), ("IDMS/DB", "19.0")]:
        row = D[(D["product"] == prod) & (D["vrm"] == vrm)].iloc[0]
        assert needs_ptf(row.ptf_required), (prod, row.ptf_required)


def test_summary_counts():
    s = DB.summarize(D, "3.2")
    assert s["ptf"] == 30 and s["fixcat"] == 21 and s["yes"] == 153 and s["no"] == 44


def test_filters():
    assert len(DB.filter(ptf="PTF required", version="3.2")) == 30
    assert len(DB.filter(ptf="Check FIXCAT", version="3.2")) == 21
    assert DB.filter(ptf="Check FIXCAT", version="3.2").vendor.isin(["IBM", "BMC", "Broadcom", "Rocket"]).all()
    assert len(DB.filter(ptf="Check FIXCAT", version="2.5")) == 19


def test_worklist_and_templates():
    wl = ptf_worklist(D, "3.2")
    assert len(wl) == 51 and set(wl.Type) == {"PTF IDs", "PTFs (no IDs published)", "FIXCAT"}
    ids, cats = unique_ptf_ids(D, "3.2"), unique_fixcats(D, "3.2")
    assert "LU16693" in ids and "SDF21QS" in ids and "LU18249" not in ids and "UJ98216" not in ids
    assert {"IBM.TargetSystem-RequiredService.z/OS.3.2", "BMC.TargetSystem-RequiredService.z/OS.V3R2",
            "CA.TargetSystem-RequiredService.z/OS.V3R2"} <= set(cats)
    t = fixcat_template(cats)
    assert "REPORT MISSINGFIX" in t and all(c in t for c in cats)


def test_excel_colours():
    path = os.path.join(tempfile.mkdtemp(), "o.xlsx")
    open(path, "wb").write(build_excel({"All": D}, version="3.2"))
    ours, ref = load_workbook(path)["All"], load_workbook(REF)["Filtered"]
    assert ours.max_row == ref.max_row
    yellow = orange = 0
    for row in range(2, ours.max_row + 1):
        text, f = ours.cell(row, 5).value, _fill(ours.cell(row, 5))
        assert f == {"yes": PTF_FILL, "check": FIXCAT_FILL}.get(ptf_state(text)), (row, text, f)
        yellow += f == PTF_FILL
        orange += f == FIXCAT_FILL
        if _fill(ref.cell(row, 5)) == PTF_FILL:          # every reference-yellow cell is still yellow
            assert f == PTF_FILL
    assert yellow == 30 and orange == 21
    wb = load_workbook(path)
    assert "PTF Worklist" in wb.sheetnames and wb["PTF Worklist"].max_row == 52


def test_apply_sources_is_idempotent_and_never_overwrites_real_data():
    tmp = os.path.join(tempfile.mkdtemp(), "data")
    shutil.copytree(os.path.join(ROOT, "data"), tmp)
    before = {f: open(f, "rb").read() for f in glob.glob(os.path.join(tmp, "*.csv"))}
    apply_ptf_sources.main(["--data-dir", tmp])
    assert before == {f: open(f, "rb").read() for f in before}            # nothing left to fill


def test_apply_sources_fills_placeholders_from_scratch():
    tmp = os.path.join(tempfile.mkdtemp(), "data")
    shutil.copytree(os.path.join(ROOT, "data"), tmp)
    f = os.path.join(tmp, "ibm_compat.csv")
    df = pd.read_csv(f, dtype=str, keep_default_na=False)
    df["ptf_required"] = "Verify"
    df.to_csv(f, index=False)
    apply_ptf_sources.main(["--data-dir", tmp])
    out = pd.read_csv(f, dtype=str, keep_default_na=False)
    assert (out.ptf_required.map(ptf_state) == "check").all()


def test_importer_is_idempotent_and_does_not_downgrade():
    tmp = os.path.join(tempfile.mkdtemp(), "data")
    shutil.copytree(os.path.join(ROOT, "data"), tmp)
    before = {f: open(f, "rb").read() for f in glob.glob(os.path.join(tmp, "*.csv"))}
    assert import_xlsx.main([REF, "--data-dir", tmp]) == 0     # the reference has 'Verify' for IBM: must not erase FIXCAT
    assert before == {f: open(f, "rb").read() for f in before}


def test_streamlit_app_runs_without_errors():
    try:
        from streamlit.testing.v1 import AppTest
    except Exception:
        return
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=90).run()
    assert not at.exception, at.exception
    for v in ("3.1", "2.5", "3.2"):
        at.selectbox(key="zos_ver").select(v).run()
        assert not at.exception, (v, at.exception)
    at.selectbox(key="ver_ptf").select("Check FIXCAT").run()
    assert not at.exception, at.exception


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("PASS", name)
            except Exception as e:
                fails += 1; print("FAIL", name, "->", repr(e)[:400])
    sys.exit(1 if fails else 0)
