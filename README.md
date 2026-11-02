# z/OS Product Compatibility

Streamlit app: pick a z/OS version (3.2 / 3.1 / 2.5) and see which vendor products are compatible and what
**PTFs / usermods** they need, plus EOS dates and latest versions. Download the result as Excel.
Written answers (Tab 3) use a local Granite/Llama model through Ollama (optional, no API key, nothing leaves your machine).

## Quick start

Windows: double-click `run.bat`   |   Mac/Linux: `./run.sh`

or manually:

    python -m venv venv
    .\venv\Scripts\activate
    pip install -r requirements.txt
    streamlit run app.py             -> http://localhost:8501

## How PTF information is shown (all vendors)

Vendors publish PTF requirements in different ways, so the **If Yes, PTF Required?** cell has three colours:

| Colour | Meaning | Vendors today |
|---|---|---|
| 🟨 **Yellow** `Yes - LU16693, ...` | PTFs / usermods are required and the IDs are published | Broadcom (29 products), Precisely Ironstream (`SDF21QS`) |
| 🟧 **Orange** `Check FIXCAT - IBM.TargetSystem-RequiredService.z/OS.3.2 ...` | The vendor delivers the PTFs through an SMP/E **fix category**; SMP/E lists what your zone is missing | IBM (all products), BMC (all products), Broadcom VTAPE, Zowe |
| no fill | `No`, `N/A`, or `Not found publicly - ask <vendor>` | Rocket, ASG, Precisely MFX have no public PTF list |

IBM and BMC do not publish a fixed PTF list per product: required fixes are identified by the SMP/E fix categories
`IBM.TargetSystem-RequiredService.z/OS.3.2` and `BMC.TargetSystem-RequiredService.z/OS.V3R2` (also 3.1 and 2.5).
Under every table the **PTF / usermod worklist** lists the PTF IDs *and* the FIXCATs, with copy-ready lists and
downloadable SMP/E templates (`RECEIVE / APPLY CHECK` for IDs, `REPORT MISSINGFIX` for FIXCATs). They are templates:
review zone names and options first. Receive the vendors' latest HOLDDATA before running `REPORT MISSINGFIX`.

## Tabs

| Tab | Purpose |
|---|---|
| 1 z/OS Version | Filter the whole matrix (PTF filter: required / Check FIXCAT / none / not published). Download workbook. |
| 2 Check my products | Pick products + your VRM (or upload a CSV/XLSX with Vendor, Product, VRM). Verdict + worklist. |
| 3 Ask | Plain-English questions (works without AI; shows matching rows). |
| 4 Sources | Official vendor links. |

The Excel export has the same colours, a **PTF Worklist** sheet, and Sources / Notes sheets.

## Updating the data

**A. Through Excel** (good for many edits)

    python tools/import_xlsx.py my_corrected.xlsx --dry-run     (preview)
    python tools/import_xlsx.py my_corrected.xlsx               (apply to data/*.csv)

Rows match on Vendor + Product + VRM. Empty cells and placeholder PTF cells ("Verify", "Not stated") never overwrite data.

**B. Add a vendor's FIXCAT or a PTF you found** (good when a vendor publishes something new)
Add a line to `data/ptf_sources.csv` (vendor, product_contains, zos, ptf_text, source_url, verified_on), then

    python tools/apply_ptf_sources.py --dry-run
    python tools/apply_ptf_sources.py

It only fills cells that are still placeholders, so it is safe to run again. Start `ptf_text` with `Yes - ` (IDs known),
`Check FIXCAT - ` (give the FIXCAT name) or `Not found publicly - `.

Restart the app after changing data.

## Optional: written answers with Granite or Llama

    ollama pull granite3.3:8b          (or llama3.1:8b)
    set OLLAMA_MODEL=llama3.1:8b       (optional; default granite3.3:8b)
    set OLLAMA_HOST=http://localhost:11434

If Ollama is not running, Tab 3 simply shows the matching rows.

## Tests

    python tests/test_project.py

## Data notes

* z/OS 3.2 PTF IDs for Broadcom come from `tests/reference_zOS_3_2_filtered.xlsx` (29 products need PTFs).
* IBM / BMC FIXCAT names: IBM "Fix Category Values and Descriptions" and BMC "FIXCAT data" pages (checked 2026-11-02).
  Precisely Ironstream PTF: Precisely community Service Pack notice (April 2026). Sources are kept in the row comments.
* z/OS 3.1 PTF cells for Broadcom still say "see PTF list on Broadcom grid" (no IDs yet); z/OS 2.5 Broadcom is Unverified.
* IBM, Rocket, ASG and most Precisely/BMC *compatibility* statuses for z/OS 3.2 remain **Unverified**: this update adds
  PTF guidance, not new compatibility claims. IBM's per-product answer is in its Software Product Compatibility Reports.
* Always confirm on the live vendor page before production changes.
