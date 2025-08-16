# streamlit_app.py
# -----------------------------------------------------------------------------
# Australian Water Price Comparator — Ops-Aware UI
#
# What this app does:
# - Lets users compare water bills by postcode & usage (your original goal)
# - Adds operations features for the Bluecurrent-style role:
#   * Freshness & health tiles, SLA awareness
#   * Scheduled refresh scaffold (toggle + interval)
#   * Run logs (start/end, counts, incidents)
#   * Incident list with acknowledge/resolve workflow
#   * Explainability drawers (line-item math + metadata)
#   * Provider health table incl. non-communicating detection
#   * Optional cost curves for a chosen postcode
#
# Notes:
# - No live scraping here (compliance-first). All ops signals come from
#   validation + manual checks + your refresh workflow in the backend.
# - State (scheduler, health, incidents, logs) persists in ops_state.json.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
from typing import List, Dict, Any, Optional

import pandas as pd
import altair as alt
import streamlit as st

# ---- Import your ops-aware backend helpers
from water_price_app_extended import (
    # Domain data / calculators
    Tariff,
    PROVIDERS,
    POSTCODE_TO_PROVIDER,
    provider_threshold,
    calculate_bill,
    explain_bill_breakdown,
    # Ops features
    refresh_all_providers,
    get_dashboard_status,
    get_run_logs,
    list_incidents,
    update_incident,
    get_provider_health,
    set_scheduler_enabled,
    get_scheduler_status,
    maybe_run_scheduled_refresh,
    mark_provider_checked,
    update_meta,
    # Convenience
    cheapest_for_postcode,
)

# =============================================================================
# Page config & constants
# =============================================================================

st.set_page_config(
    page_title="💧 AU Water Price Comparator (Ops-Aware)",
    page_icon="💧",
    layout="wide",
)

STATUS_EMOJI = {
    "OK": "✅",
    "STALE": "🟡",
    "INCOMPLETE": "⚪",
    "ERROR": "🔴",
    "NON_COMMUNICATING": "🛑",
    "UNKNOWN": "🧩",
}

# =============================================================================
# Utility functions (UI helpers)
# =============================================================================

def _parse_postcodes(raw: str) -> List[str]:
    """Parse a comma-separated string into unique, trimmed postcodes."""
    pcs = [p.strip() for p in raw.split(",") if p.strip()]
    # Keep strings (leading zeros possible in some contexts)
    return list(dict.fromkeys(pcs))  # de-dup, keep order

def _json_preview(obj: Any, max_chars: int = 140) -> str:
    """Short JSON string for table cells; full content is shown in expanders."""
    try:
        s = json.dumps(obj, ensure_ascii=False)
        return (s[: max_chars - 1] + "…") if len(s) > max_chars else s
    except Exception:
        return str(obj)

def _health_rows() -> pd.DataFrame:
    """Build a provider health table from ops backend."""
    rows = []
    for key in PROVIDERS.keys():
        ph = get_provider_health(key)
        rows.append({
            "Provider Key": key,
            "Name": PROVIDERS[key].name,
            "Region": PROVIDERS[key].region,
            "Status": f"{STATUS_EMOJI.get(ph.status, '❔')} {ph.status}",
            "Last Checked (UTC)": ph.last_checked,
            "Last Success (UTC)": ph.last_success,
            "Failure Count": ph.failure_count,
            "Notes": " | ".join(ph.notes) if ph.notes else "",
        })
    return pd.DataFrame(rows)

def _cost_curve_for_postcode(postcode: str, kl_min: float, kl_max: float, kl_step: float = 10.0) -> Optional[pd.DataFrame]:
    """Compute cost curves for all providers mapped to a postcode."""
    provs = POSTCODE_TO_PROVIDER.get(postcode, [])
    if not provs:
        return None
    xs = []
    k = kl_min
    while k <= kl_max + 1e-9:
        xs.append(round(k, 3))
        k += kl_step
    rows = []
    for key in provs:
        t = PROVIDERS[key]
        for k in xs:
            rows.append({
                "Postcode": postcode,
                "Usage (kL/yr)": k,
                "Provider Key": key,
                "Provider": t.name,
                "Region": t.region,
                "Estimated Bill ($/yr)": round(calculate_bill(t, k, provider_threshold(key)), 2),
            })
    return pd.DataFrame(rows)

# =============================================================================
# Scheduled refresh: run if due (harmless if disabled)
# =============================================================================

# Call this early so tiles/logs reflect the latest state if the scheduler is on.
maybe_run_scheduled_refresh()

# =============================================================================
# Sidebar — primary controls + scheduler + maintainer actions
# =============================================================================

with st.sidebar:
    st.header("Inputs")

    # --- User input: postcodes and usage -------------------------------------
    pcs_raw = st.text_input(
        "Postcodes (comma-separated)",
        value="3000, 2000, 3152",
        placeholder="e.g., 3000, 2000, 3152",
        help="We’ll compute the cheapest provider per postcode at the usage below.",
    )
    usage_kl = st.number_input(
        "Annual usage (kL)",
        min_value=0.0,
        max_value=1000.0,  # guard rails so charts never ‘overshoot’
        value=160.0,
        step=10.0,
        help="Typical VIC household ~160 kL/yr (≈440 L/day).",
    )

    st.markdown("---")
    st.subheader("Scheduler")

    # --- Scheduler state + toggle --------------------------------------------
    sch = get_scheduler_status()
    colA, colB = st.columns([1, 1])
    with colA:
        enable_sched = st.toggle(
            "Enable scheduled refresh",
            value=bool(sch.get("enabled")),
            help="If enabled, the app will auto-run validation/refresh roughly on schedule.",
        )
    with colB:
        interval_minutes = st.number_input(
            "Interval (minutes)",
            min_value=30,
            max_value=24 * 60 * 7,  # up to weekly
            value=int(sch.get("interval_minutes") or 1440),
            step=30,
            help="Choose a sensible cadence (e.g., daily = 1440).",
        )
    if st.button("Apply scheduler settings", use_container_width=True):
        set_scheduler_enabled(enable_sched, interval_minutes=interval_minutes)
        st.success("Scheduler settings updated.")

    st.caption(
        f"Last run: {sch.get('last_run_at') or '—'}  •  Next due: {sch.get('next_run_due_at') or '—'}"
    )

    st.markdown("---")
    st.subheader("Maintainer actions")

    # --- Manual refresh now ---------------------------------------------------
    if st.button("🔁 Refresh now (validate all providers)", use_container_width=True):
        res = refresh_all_providers()
        st.success(f"Refresh complete — {res['count']} providers checked, "
                   f"{res['errors']} errors, {res['warns']} warnings, "
                   f"{len(res['opened_incidents'])} incident(s) opened/updated.")

    # --- Mark provider checked (manual acknowledgement) ----------------------
    prov_to_mark = st.selectbox(
        "Mark provider as checked (manual)",
        options=["—"] + list(PROVIDERS.keys()),
        index=0,
        help="Use this after verifying a tariff against its source (e.g., PDF/website).",
    )
    success_mark = st.checkbox("Mark success", value=True)
    note_mark = st.text_input("Note (optional)", value="")
    if st.button("✅ Apply check", disabled=(prov_to_mark == "—"), use_container_width=True):
        ph = mark_provider_checked(prov_to_mark, success=success_mark, note=note_mark or None)
        st.success(f"{prov_to_mark} → {ph.status} (failures: {ph.failure_count}).")

    # --- Meta update (FY / last_data_updated) --------------------------------
    with st.expander("Meta: Financial year / last data updated"):
        fy_in = st.text_input("Financial year (FY)", value=get_dashboard_status().get("meta", {}).get("fy", ""))
        lu_in = st.text_input("Last data updated (YYYY-MM-DD)", value=get_dashboard_status().get("meta", {}).get("last_updated", ""))
        if st.button("Save meta"):
            update_meta(fy=fy_in or None, last_updated=lu_in or None)
            st.success("Meta updated.")

# =============================================================================
# Header + quick guidance
# =============================================================================

st.title("💧 Australian Water Price Comparator — with Ops Dashboard")
st.caption("Compare bills across providers by postcode, **and** keep the data pipeline healthy (freshness, incidents, logs).")

# =============================================================================
# KPI tiles (freshness/health overview)
# =============================================================================

# -- Get status for tiles & quick pass rate -----------------------------------
dash = get_dashboard_status()
counts = dash["counts"]
total = dash["total_providers"]

kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)
kpi1.metric("Providers OK", counts.get("OK", 0))
kpi2.metric("Stale", counts.get("STALE", 0))
kpi3.metric("Incomplete", counts.get("INCOMPLETE", 0))
kpi4.metric("Errors", counts.get("ERROR", 0))
kpi5.metric("Non-communicating", counts.get("NON_COMMUNICATING", 0))
kpi6.metric("Validation pass rate", f"{dash['validation_pass_rate']}%")

st.caption(
    f"FY: **{dash['meta'].get('fy','')}** • Data last updated: **{dash['meta'].get('last_updated','')}** • "
    f"Last run: **{(dash['last_run'] or {}).get('ts', '—')}**"
)

st.markdown("---")

# =============================================================================
# Cheapest-by-postcode table with explainability drawers
# =============================================================================

st.subheader("Cheapest option by postcode @ selected usage")
st.caption("Transparent, line-item math builds stakeholder trust — expand a row to see the calculation.")

postcodes = _parse_postcodes(pcs_raw)

cheap_rows: List[Dict[str, Any]] = []
for pc in postcodes:
    best = cheapest_for_postcode(pc, usage_kl)
    if not best:
        cheap_rows.append({"Postcode": pc, "Provider": "—", "Region": "—", "Est. Cost ($/yr)": "N/A", "Explain": "No providers mapped"})
        continue
    cheap_rows.append({
        "Postcode": pc,
        "Provider": best["provider_name"],
        "Region": best["region"],
        "Est. Cost ($/yr)": best["total"],
        "Explain": _json_preview(best["explain"]),
        "_explain_full": best["explain"],
        "_provider_key": best["provider_key"],
    })

cheap_df = pd.DataFrame(cheap_rows)
if not cheap_df.empty:
    st.dataframe(
        cheap_df[["Postcode", "Provider", "Region", "Est. Cost ($/yr)", "Explain"]],
        use_container_width=True,
        hide_index=True,
    )
    # Expanders: one per result (explainability)
    for i, row in cheap_df.iterrows():
        with st.expander(f"🔍 Explain calculation for {row['Postcode']} → {row['Provider']}"):
            detail = row.get("_explain_full") or {}
            st.write(f"**Provider:** {detail.get('provider_name')}  •  **Region:** {detail.get('region')}")
            st.write(f"**FY:** {detail.get('fy')}  •  **Last data updated:** {detail.get('last_data_updated')}  •  **Threshold:** {detail.get('threshold_kL')} kL")
            st.write("**Notes:**", detail.get("notes") or "—")
            st.markdown("**Line-items**")
            items = detail.get("items", [])
            items_df = pd.DataFrame(items)
            if not items_df.empty:
                st.dataframe(items_df, use_container_width=True, hide_index=True)
            st.write(f"**Total:** ${detail.get('total')}  •  **Effective:** ${detail.get('effective_$_per_kL')}/kL")
else:
    st.info("Enter at least one valid postcode above.")

st.markdown("---")

# =============================================================================
# Optional: Cost curves for a selected postcode (multi-provider comparison)
# =============================================================================

st.subheader("Cost curves (optional): compare all providers for one postcode")
st.caption("Use this to see where cross-overs happen as usage changes. Guard rails prevent the ‘lines extending off the graph’ issue.")

cc_col1, cc_col2, cc_col3 = st.columns([1, 1, 1])
with cc_col1:
    cc_pc = st.selectbox("Pick a postcode", options=["—"] + postcodes, index=0)
with cc_col2:
    cc_min = st.number_input("Usage min (kL)", min_value=0.0, max_value=900.0, value=0.0, step=10.0)
with cc_col3:
    cc_max = st.number_input("Usage max (kL)", min_value=10.0, max_value=1000.0, value=200.0, step=10.0)

# Clamp to ensure min < max and safe domain
if cc_max <= cc_min:
    st.warning("Usage max must be greater than min.")
else:
    if cc_pc and cc_pc != "—":
        curve_df = _cost_curve_for_postcode(cc_pc, cc_min, cc_max, kl_step=10.0)
        if curve_df is None or curve_df.empty:
            st.info("No providers mapped for that postcode.")
        else:
            chart = (
                alt.Chart(curve_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("Usage (kL/yr):Q", scale=alt.Scale(domain=[cc_min, cc_max])),
                    y=alt.Y("Estimated Bill ($/yr):Q"),
                    color=alt.Color("Provider:N"),
                    tooltip=["Provider", "Region", "Usage (kL/yr)", "Estimated Bill ($/yr)"],
                )
                .properties(height=360)
            )
            st.altair_chart(chart, use_container_width=True)

st.markdown("---")

# =============================================================================
# Provider health table (freshness, failures, non-communicating)
# =============================================================================

st.subheader("Provider health")
st.caption("Reflects validation status, last checked times, and non-communicating escalations.")

health_df = _health_rows()
st.dataframe(health_df, use_container_width=True, hide_index=True)

st.markdown("---")

# =============================================================================
# Incidents (triage & root cause workflow)
# =============================================================================

st.subheader("Incidents")
st.caption("Open/ack/resolve items. Incidents auto-open for repeated failures (non-communicating) and validation errors.")

incs = list_incidents()
if not incs:
    st.success("No incidents 🎉")
else:
    incs_df = pd.DataFrame([{
        "ID": i["id"],
        "Provider Key": i["provider_key"],
        "Code": i["code"],
        "Status": i["status"],
        "Summary": i["summary"],
        "Opened": i["opened_at"],
        "Updated": i["updated_at"],
        "Details": _json_preview(i.get("details", {})),
    } for i in incs])
    st.dataframe(incs_df, use_container_width=True, hide_index=True)

    # Action controls per incident (ack/resolve)
    for i in incs:
        with st.expander(f"⚠️ Incident {i['id']} • {i['provider_key']} • {i['code']} • {i['status']}"):
            st.write("**Summary:**", i["summary"])
            st.write("**Details (raw):**")
            st.json(i.get("details", {}))
            ack_col, res_col = st.columns([1, 1])
            with ack_col:
                if st.button("Acknowledge", key=f"ack_{i['id']}"):
                    ok = update_incident(i["id"], "acknowledged", note="Acknowledged via UI")
                    st.success("Acknowledged." if ok else "Failed to update.")
            with res_col:
                if st.button("Resolve", key=f"res_{i['id']}"):
                    ok = update_incident(i["id"], "resolved", note="Resolved via UI")
                    st.success("Resolved." if ok else "Failed to update.")

st.markdown("---")

# =============================================================================
# Run logs (recent activity)
# =============================================================================

st.subheader("Run logs")
st.caption("Operational breadcrumb trail — scheduler toggles, refresh cycles, incidents.")

logs = get_run_logs(limit=100)
if not logs:
    st.info("No logs yet. Trigger a refresh or toggle the scheduler.")
else:
    # Table view (compact)
    logs_df = pd.DataFrame([{
        "Time (UTC)": e["ts"],
        "Event": e["event"],
        "Details": _json_preview(e.get("details", {})),
    } for e in logs])
    st.dataframe(logs_df, use_container_width=True, hide_index=True)

    # Full JSON view in an expander
    with st.expander("Show full JSON logs"):
        st.json(logs)

st.markdown("---")

# =============================================================================
# Column glossary (stakeholder-friendly)
# =============================================================================

with st.expander("Glossary: what each column means"):
    st.markdown("""
- **Postcode** — Australian postcode being quoted.  
- **Provider / Region** — Utility and service region applicable for that postcode.  
- **Est. Cost ($/yr)** — Estimated annual bill at the selected usage. Includes fixed charges plus usage tiers.  
- **Explain** — Short JSON; expand a row to see the line-by-line calculation, threshold, FY, and data freshness.  
- **Status** — Health flag for each provider:  
  - ✅ OK: Validated and recently checked  
  - 🟡 STALE: Last check beyond SLA window  
  - ⚪ INCOMPLETE: Placeholder/zero tariffs; needs curation  
  - 🔴 ERROR: Failed validation rules  
  - 🛑 NON_COMMUNICATING: Repeated failures reached threshold  
  - 🧩 UNKNOWN: Not checked yet  
    """)

# =============================================================================
# Footer
# =============================================================================

st.caption("Built for transparency + reliability. No live scraping here; bring-your-own sources and record checks in the UI.")
