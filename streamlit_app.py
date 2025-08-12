# streamlit_app.py
import re
import time
from typing import List, Dict, Optional

import pandas as pd
import streamlit as st
import altair as alt

st.set_page_config(page_title="💧 AU Water Price Comparator", page_icon="💧", layout="wide")

# ---- Safe import of your data module; show errors in the UI instead of a blank page
try:
    from water_price_app_extended import (
        Tariff,
        PROVIDERS,
        PROVIDER_THRESHOLDS,
        BLOCK_THRESHOLD_KL,
        POSTCODE_TO_PROVIDER,
        calculate_bill,
        copy_providers,
        copy_thresholds,
        get_meta,
        export_python,
    )
except Exception as e:
    st.title("💧 Australian Water Price Comparator")
    st.error(
        "Failed to import `water_price_app_extended`.\n\n"
        "Common causes:\n"
        "• The file name is wrong or not saved\n"
        "• A syntax/indentation error in that file\n"
        "• Python version mismatch\n"
    )
    st.exception(e)
    st.stop()

st.title("💧 Australian Water Price Comparator")
st.caption(
    "No scraping. Built-in data from code.\n"
    "Maintainer Mode is **live**: changes update calculations immediately. "
    "Use Export only if you want to save edits back to code."
)

# =========================
# Session bootstrap
# =========================
if "providers" not in st.session_state:
    st.session_state.providers: Dict[str, Tariff] = copy_providers()
if "thresholds" not in st.session_state:
    st.session_state.thresholds: Dict[str, float] = copy_thresholds()
if "meta" not in st.session_state:
    st.session_state.meta = get_meta()
if "last_action" not in st.session_state:
    st.session_state.last_action = None

def current_providers() -> Dict[str, Tariff]:
    return st.session_state.providers

def current_thresholds() -> Dict[str, float]:
    return st.session_state.thresholds

# =========================
# Sidebar inputs (minimal)
# =========================
with st.sidebar:
    st.header("Inputs")

    pcs_raw = st.text_input(
        "Postcodes (comma-separated)",
        value="3000, 2000, 3152",
        placeholder="e.g., 3000, 2000, 3152",
        help="Enter 4-digit postcodes separated by commas (max ~8)."
    )

    annual_kL = st.number_input(
        "Annual water use (kL)",
        min_value=0.0, value=160.0, step=10.0,
        help="Used for the tables, summary and chart."
    )

    st.divider()
    if st.button("Reset to built-in defaults"):
        st.session_state.providers = copy_providers()
        st.session_state.thresholds = copy_thresholds()
        st.session_state.meta = get_meta()
        st.session_state.last_action = f"Reset at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        st.success("Reset to built-in data (no scraping).")

    with st.expander("How updates work"):
        st.markdown(
            """
**Live updates.**  
Edits in Maintainer Mode immediately change the data and recalculations.  
Click **Export** only if you want a Python snippet to paste back into `water_price_app_extended.py` to save permanently.
"""
        )

# =========================
# Maintainer Mode (LIVE updates)
# =========================
st.markdown("### 🛠️ Maintainer Mode (live session edits)")
with st.expander("Open maintainer console"):
    provs = current_providers()
    thrs = current_thresholds()
    keys = sorted(provs.keys())
    default_idx = keys.index("YVW") if "YVW" in keys else 0
    sel_key = st.selectbox("Select provider key", options=keys, index=default_idx)

    def _provider_health_msg(k: str, t: Optional[Tariff]) -> Optional[str]:
        if t is None:
            return f"Key **{k}** has no data in `PROVIDERS`."
        msgs = []
        if t.network_charge == 0.0 and t.sewerage_charge == 0.0 and (t.usage_charges[0] == 0.0):
            msgs.append("All values are 0.0 — this looks like a **placeholder** provider.")
        if t.usage_charges[0] <= 0:
            msgs.append("Usage tier 1 is ≤ 0. Enter a positive rate for meaningful estimates.")
        if (t.usage_charges[1] is not None) and (t.usage_charges[1] <= 0):
            msgs.append("Usage tier 2 is ≤ 0. Enter a positive rate or turn off Two-step.")
        return "\n".join(msgs) if msgs else None

    if sel_key:
        t = provs.get(sel_key)
        if t is None:
            st.error(
                f"Provider key `{sel_key}` exists in the dropdown but not in `PROVIDERS`.\n\n"
                "Fix: add a Tariff for this key in `water_price_app_extended.py`, or choose another key."
            )
        else:
            health = _provider_health_msg(sel_key, t)
            if health:
                st.warning(f"**{sel_key} • {t.name}**\n\n{health}")

            # Widgets (we'll write changes back to session_state on every rerun = live)
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Provider name", value=t.name, key=f"name_{sel_key}")
                region = st.text_input("Region", value=t.region, key=f"region_{sel_key}")
                network = st.number_input(
                    "Annual water/network charge (AUD)",
                    min_value=0.0, value=float(t.network_charge), step=1.0, key=f"net_{sel_key}"
                )
                sewer = st.number_input(
                    "Annual sewerage charge (AUD)",
                    min_value=0.0, value=float(t.sewerage_charge), step=1.0, key=f"sew_{sel_key}"
                )
            with col2:
                has_two = st.checkbox(
                    "Two-step tariff", value=(t.usage_charges[1] is not None), key=f"two_{sel_key}",
                    help="If on, set the higher tier rate and (optionally) a threshold override."
                )
                usage1 = st.number_input(
                    "Usage tier 1 ($/kL)", min_value=0.0, value=float(t.usage_charges[0]),
                    step=0.01, format="%.4f", key=f"u1_{sel_key}"
                )
                usage2_val_default = float(t.usage_charges[1] or 0.0)
                usage2_val = st.number_input(
                    "Usage tier 2 ($/kL)", min_value=0.0, value=usage2_val_default,
                    step=0.01, format="%.4f", key=f"u2_{sel_key}", disabled=not has_two
                )
                use_thr_override = st.checkbox(
                    "Override block threshold for this provider?",
                    value=(sel_key in thrs), key=f"thrflag_{sel_key}",
                    help=f"Default is {BLOCK_THRESHOLD_KL:.0f} kL unless overridden."
                )
                thr_default = thrs.get(sel_key, BLOCK_THRESHOLD_KL)
                thr_val = st.number_input(
                    "Provider-specific threshold (kL)",
                    min_value=1.0, value=float(thr_default), step=1.0,
                    disabled=not use_thr_override, key=f"thr_{sel_key}"
                )
            notes = st.text_area("Notes", value=t.notes, height=80, key=f"notes_{sel_key}")

            # ---- LIVE UPDATE: write back to session_state every rerun
            new_tariff = Tariff(
                network_charge=float(network),
                sewerage_charge=float(sewer),
                usage_charges=(float(usage1), None if not has_two else float(usage2_val)),
                name=name, region=region, notes=notes
            )
            provs[sel_key] = new_tariff
            if use_thr_override:
                thrs[sel_key] = float(thr_val)
            else:
                thrs.pop(sel_key, None)
            # Touch metadata so footer shows today's date for live edits
            st.session_state.meta["last_updated"] = time.strftime("%Y-%m-%d")

            # Export remains optional for persistence
            if st.button("🧾 Export updated data as Python", key=f"export_{sel_key}"):
                snippet = export_python(provs, thrs, BLOCK_THRESHOLD_KL, st.session_state.meta)
                st.session_state["export_snippet"] = snippet
                st.info("Scroll just below to copy the snippet.")

    if "export_snippet" in st.session_state:
        st.markdown("#### Copy/paste this into `water_price_app_extended.py` (replace the dicts)")
        st.code(st.session_state["export_snippet"], language="python")

# =========================
# Helpers
# =========================
def parse_postcodes(s: str, limit: int = 8) -> List[str]:
    """Split by commas/spaces, keep valid 4-digit postcodes, de-dupe preserving order."""
    if not s:
        return []
    seen = set()
    out: List[str] = []
    for tok in re.split(r"[,\s]+", s.strip()):
        if re.fullmatch(r"\d{4}", tok) and tok not in seen:
            seen.add(tok)
            out.append(tok)
        if len(out) >= limit:
            break
    return out

def provider_keys_for(pc: str) -> List[str]:
    return POSTCODE_TO_PROVIDER.get(pc.strip(), [])

def threshold_for(key: str) -> float:
    return current_thresholds().get(key, BLOCK_THRESHOLD_KL)

def quote_for_usage(postcode: str, kL: float) -> pd.DataFrame:
    rows: List[Dict] = []
    keys = provider_keys_for(postcode)
    if not keys:
        return pd.DataFrame(rows)

    provs = current_providers()
    for key in keys:
        t: Optional[Tariff] = provs.get(key)
        if not t:
            rows.append({
                "Provider": key, "Region": "—",
                "Fixed charges (annual)": None,
                "Usage rate(s) ($/kL)": "—",
                "Tariff type": "—",
                "Block threshold": "—",
                f"Est. cost @ {kL:.0f} kL": None,
                "Notes": "Provider data missing."
            })
            continue

        thr = threshold_for(key) if t.usage_charges[1] is not None else None
        total = calculate_bill(t, kL, threshold_kL=thr)
        fixed = t.network_charge + t.sewerage_charge

        if t.usage_charges[1] is None:
            usage_str = f"{t.usage_charges[0]:.4f}"
            tier_desc = "Flat rate"
            block_text = "—"
        else:
            # ✅ fixed: single colon in the f-string
            usage_str = f"{t.usage_charges[0]:.4f} / {t.usage_charges[1]:.4f}"
            tier_desc = "Two-step"
            block_text = f"{threshold_for(key):.0f} kL"

        rows.append({
            "Provider": t.name,
            "Region": t.region,
            "Fixed charges (annual)": round(fixed, 2),
            "Usage rate(s) ($/kL)": usage_str,
            "Tariff type": tier_desc,
            "Block threshold": block_text,
            f"Est. cost @ {kL:.0f} kL": round(total, 2),
            "Notes": t.notes or "",
        })
    return pd.DataFrame(rows)

def cheapest_row(df: pd.DataFrame, kL: float) -> Optional[pd.Series]:
    col = f"Est. cost @ {kL:.0f} kL"
    if df.empty or col not in df.columns or not df[col].notna().any():
        return None
    return df.loc[df[col].astype(float).idxmin()]

def tariff_summary_box(postcode: str) -> str:
    keys = provider_keys_for(postcode)
    if not keys:
        return "_No providers mapped in this demo._"
    lines = []
    provs = current_providers()
    for key in keys:
        t: Optional[Tariff] = provs.get(key)
        if not t:
            lines.append(f"- **{key}**: _no data_")
            continue
        fixed = t.network_charge + t.sewerage_charge
        if t.usage_charges[1] is None:
            usage_str = f"${t.usage_charges[0]:.4f}/kL (flat)"
        else:
            thr = threshold_for(key)
            usage_str = f"${t.usage_charges[0]:.4f}/kL up to ~{thr:.0f} kL, then ${t.usage_charges[1]:.4f}/kL"
        lines.append(
            f"- **{t.name}** ({t.region}): fixed **${fixed:,.2f}/yr**, usage **{usage_str}**."
        )
    return "\n".join(lines)

# =========================
# Build results for ALL postcodes
# =========================
postcodes = parse_postcodes(pcs_raw)
if not postcodes:
    st.info("Enter at least one valid 4-digit postcode.")
    st.stop()

if len(postcodes) > 8:
    st.warning("Showing the first 8 postcodes to keep things readable.")
postcodes = postcodes[:8]

dfs_by_pc: Dict[str, pd.DataFrame] = {}
cheapest_by_pc: Dict[str, Optional[pd.Series]] = {}
all_rows: List[pd.DataFrame] = []

for pc in postcodes:
    df = quote_for_usage(pc, annual_kL)
    dfs_by_pc[pc] = df
    cheapest_by_pc[pc] = cheapest_row(df, annual_kL)
    if not df.empty:
        tmp = df.copy()
        tmp.insert(0, "Postcode", pc)
        all_rows.append(tmp)

# =========================
# Summary: cheapest per postcode
# =========================
st.markdown("### 📋 Cheapest option by postcode (at your selected usage)")
summary_rows = []
for pc in postcodes:
    ch = cheapest_by_pc[pc]
    if ch is not None:
        summary_rows.append({
            "Postcode": pc,
            "Cheapest provider": f"{ch['Provider']} ({ch['Region']})",
            f"Cheapest cost @ {annual_kL:.0f} kL": float(ch[f"Est. cost @ {annual_kL:.0f} kL"])
        })
    else:
        summary_rows.append({
            "Postcode": pc,
            "Cheapest provider": "—",
            f"Cheapest cost @ {annual_kL:.0f} kL": None
        })

sum_df = pd.DataFrame(summary_rows)
st.dataframe(sum_df, use_container_width=True, hide_index=True)

# =========================
# Line chart: cheapest cost vs usage (by postcode)
# =========================
st.markdown("### 📈 Cheapest estimated cost vs usage (by postcode)")

def usage_points_around(k: float) -> List[int]:
    base = int(round(k))
    # sample a few points around the selected usage; clamp at 0
    pts = sorted({max(0, base + d) for d in (-60, -30, 0, 30, 60)})
    return pts or [base]

u_points = usage_points_around(annual_kL)

rows_points: List[Dict] = []
for pc in postcodes:
    for k in u_points:
        d = quote_for_usage(pc, float(k))
        r = cheapest_row(d, float(k))
        if r is not None:
            rows_points.append({
                "Postcode": pc,
                "Usage kL": float(k),
                "Cheapest estimated cost": float(r[f"Est. cost @ {float(k):.0f} kL"]),
                "Provider (cheapest)": r["Provider"],
            })

points_df = pd.DataFrame(rows_points)

if points_df.empty:
    st.info("No data to chart yet. Enter postcodes with mapped providers.")
else:
    chart = (
        alt.Chart(points_df)
        .mark_line(point=True, clip=True)
        .encode(
            x=alt.X("Usage kL:Q", title="Usage (kL)"),
            y=alt.Y("Cheapest estimated cost:Q", title="Estimated cost (AUD)", scale=alt.Scale(domainMin=0)),
            color=alt.Color("Postcode:N", legend=alt.Legend(title="Postcode")),
            tooltip=["Postcode", "Usage kL", "Cheapest estimated cost", "Provider (cheapest)"],
        )
        .properties(height=380)
    )
    st.altair_chart(chart, use_container_width=True)

# =========================
# Tabs: full breakdown per postcode
# =========================
st.markdown("### 📦 Full breakdown per postcode")
tabs = st.tabs([f"{pc}" for pc in postcodes])
for tab, pc in zip(tabs, postcodes):
    with tab:
        st.subheader(f"Postcode {pc}")
        df = dfs_by_pc[pc]
        if df.empty:
            st.info("No results to show. Add a provider mapping for this postcode.")
        else:
            show_notes = st.checkbox("Show Notes", value=True, key=f"notes_{pc}")
            show_df = df if show_notes else df.drop(columns=["Notes"])
            st.dataframe(show_df, use_container_width=True, hide_index=True)
            ch = cheapest_by_pc[pc]
            if ch is not None:
                st.metric(
                    label=f"Cheapest @ {annual_kL:.0f} kL",
                    value=f"${float(ch[f'Est. cost @ {annual_kL:.0f} kL']):,.2f}",
                    delta=f"{ch['Provider']} ({ch['Region']})"
                )

# =========================
# Tariff details (simple)
# =========================
st.markdown("### 🧾 Tariff details (as modeled)")
for pc in postcodes:
    with st.expander(f"{pc}: tariff details", expanded=False):
        st.markdown(tariff_summary_box(pc))

st.divider()

# =========================
# Footer metadata
# =========================
meta = st.session_state.meta
st.caption(
    "Estimates simplify some charges (e.g., trade waste, recycled water). "
    "Tariffs change each financial year; verify on provider sites."
)
st.caption(
    f"📦 Data FY: {meta.get('fy','n/a')} • 🗓️ Last data update: {meta.get('last_updated','n/a')} • "
    f"🧰 Live edits this session: yes"
)
