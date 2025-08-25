# streamlit_app.py
# -----------------------------------------------------------------------------
# Water Tariff Explorer — Transparency & Ops Reliability (Streamlit)
#
# UX decisions:
# - Sidebar = global controls (view switcher, scheduler, maintainer tools).
# - Main area:
#     * Explorer view → Left: KPI glance • Middle: results • Right: inputs
#     * Ops views (Health / Incidents / Logs) → full-width heavy tables
#
# Positioning:
# - NOT a consumer "switching" tool. Most areas have a single supplier.
# - IS a transparency + operations dashboard:
#     * Explainable tariff estimates (line-item maths)
#     * Freshness/SLA monitoring, incidents, run logs
#     * Provisioning-style coverage via postcode→provider mapping
#
# Data policy:
# - Compliance-first: no live scraping here. Tariffs are static in code.
# - Ops state (scheduler, incidents, logs) persists in ops_state.json.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
from typing import List, Dict, Any, Optional

import pandas as pd
import altair as alt
import streamlit as st

# ---- Import backend helpers (your upgraded module)
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
    page_title="💧 Water Tariff Explorer — Transparency & Ops Reliability",
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
    return list(dict.fromkeys(pcs))  # de-dup, keep order


def _json_preview(obj: Any, max_chars: int = 140) -> str:
    """Short JSON string for table cells; full content is shown in expanders."""
    try:
        s = json.dumps(obj, ensure_ascii=False)
        return (s[: max_chars - 1] + "…") if len(s) > max_chars else s
    except Exception:
        return str(obj)


def _provider_to_postcodes() -> Dict[str, List[str]]:
    """
    Invert POSTCODE_TO_PROVIDER so we can show a 'Postcodes (mapped)' column
    in the Provider Health table. Each provider key → sorted unique postcodes.
    """
    mapping: Dict[str, List[str]] = {k: [] for k in PROVIDERS.keys()}
    for pc, providers in POSTCODE_TO_PROVIDER.items():
        for key in providers:
            mapping.setdefault(key, []).append(pc)
    for k in list(mapping.keys()):
        mapping[k] = sorted(set(mapping[k]))
    return mapping


def _health_rows() -> pd.DataFrame:
    """
    Build a provider health table from ops backend.
    Includes 'Postcodes (mapped)' to reflect provisioning-style coverage.
    """
    prov_to_pcs = _provider_to_postcodes()
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
            "Postcodes (mapped)": ", ".join(prov_to_pcs.get(key, [])) or "—",
            "Notes": " | ".join(ph.notes) if ph.notes else "",
        })
    return pd.DataFrame(rows)


def _cost_curve_for_postcode(postcode: str, kl_min: float, kl_max: float, kl_step: float = 10.0) -> Optional[pd.DataFrame]:
    """Compute cost curves for all providers mapped to a postcode (QA/planning view)."""
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


def _cost_matrix_for_postcodes(postcodes: List[str], kl_min: float, kl_max: float, kl_step: float = 10.0) -> pd.DataFrame:
    """Matrix of cheapest estimates across postcodes over a usage range.

    Returns long-form rows: Postcode • Usage • Estimated Bill • Provider • Region
    """
    xs: List[float] = []
    k = kl_min
    while k <= kl_max + 1e-9:
        xs.append(round(k, 3))
        k += kl_step

    rows: List[Dict[str, Any]] = []
    for pc in postcodes:
        for u in xs:
            best = cheapest_for_postcode(pc, u)
            if not best:
                continue
            rows.append({
                "Postcode": pc,
                "Usage (kL/yr)": u,
                "Estimated Bill ($/yr)": round(float(best["total"]), 2),
                "Provider": best["provider_name"],
                "Region": best["region"],
            })
    return pd.DataFrame(rows)


# =============================================================================
# Scheduled refresh: run if due (harmless if disabled)
# =============================================================================

# Ensure tiles/logs reflect any due run when the page loads.
maybe_run_scheduled_refresh()

# =============================================================================
# Sidebar — global view switcher + scheduler + maintainer tools
# =============================================================================

st.sidebar.title("Navigation & Ops")

# ---- View switcher (keeps heavy tables out of the narrow sidebar) ----------
view = st.sidebar.radio(
    "View",
    ["Explorer", "Ops — Health", "Ops — Incidents", "Ops — Logs"],
    help="Switch between user estimates and operations views.",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Automated health checks")

# ---- Scheduler state + toggle ------------------------------------------------
sch = get_scheduler_status()
colA, colB = st.sidebar.columns([1, 1])
with colA:
    enable_sched = st.toggle(
        "Enable scheduled validation",
        value=bool(sch.get("enabled")),
        help="If enabled, the app auto-runs validation on an interval.",
    )
with colB:
    interval_minutes = st.number_input(
        "Interval (min)",
        min_value=30,
        max_value=24 * 60 * 7,  # up to weekly
        value=int(sch.get("interval_minutes") or 1440),
        step=30,
        help="Example: daily = 1440.",
    )
if st.sidebar.button("Apply scheduler settings", use_container_width=True):
    set_scheduler_enabled(enable_sched, interval_minutes=interval_minutes)
    st.sidebar.success("Scheduler settings updated.")

st.sidebar.caption(
    f"Last run: {sch.get('last_run_at') or '—'}  •  Next due: {sch.get('next_run_due_at') or '—'}"
)

st.sidebar.markdown("---")
st.sidebar.subheader("Maintainer tools")

# ---- Manual validation run ---------------------------------------------------
if st.sidebar.button("🔁 Run validation now", use_container_width=True):
    res = refresh_all_providers()
    st.sidebar.success(f"{res['count']} providers checked • {res['errors']} errors • "
                       f"{res['warns']} warnings • {len(res['opened_incidents'])} incident(s).")

# ---- Manual provider check ---------------------------------------------------
prov_to_mark = st.sidebar.selectbox(
    "Manually mark provider as checked",
    options=["—"] + list(PROVIDERS.keys()),
    index=0,
)
success_mark = st.sidebar.checkbox("Mark success", value=True)
note_mark = st.sidebar.text_input("Note (optional)", value="")
if st.sidebar.button("✅ Apply manual check", disabled=(prov_to_mark == "—"), use_container_width=True):
    ph = mark_provider_checked(prov_to_mark, success=success_mark, note=note_mark or None)
    st.sidebar.success(f"{prov_to_mark} → {ph.status} (failures: {ph.failure_count}).")

# ---- Meta update (FY / last_data_updated) -----------------------------------
with st.sidebar.expander("Meta (FY / last updated)"):
    fy_in = st.text_input("Financial year (FY)", value=get_dashboard_status().get("meta", {}).get("fy", ""))
    lu_in = st.text_input("Last data updated (YYYY-MM-DD)", value=get_dashboard_status().get("meta", {}).get("last_updated", ""))
    if st.button("Save meta"):
        update_meta(fy=fy_in or None, last_updated=lu_in or None)
        st.success("Meta updated.")

# =============================================================================
# Header & KPI glance (top of every view)
# =============================================================================

st.title("💧 Water Tariff Explorer — Transparency & Ops Reliability")
st.caption("Informational tariff estimates with explainable maths, plus an operations view (freshness/SLA, incidents, run logs, coverage).")

dash = get_dashboard_status()
counts = dash["counts"]

# Small KPI glance (kept light; heavy tables live in Ops views)
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("OK", counts.get("OK", 0))
k2.metric("Stale", counts.get("STALE", 0))
k3.metric("Incomplete", counts.get("INCOMPLETE", 0))
k4.metric("Errors", counts.get("ERROR", 0))
k5.metric("Non-comm", counts.get("NON_COMMUNICATING", 0))
k6.metric("Pass rate", f"{dash['validation_pass_rate']}%")

st.caption(
    f"FY: **{dash['meta'].get('fy','')}** • Data last updated: **{dash['meta'].get('last_updated','')}** • "
    f"Last validation: **{(dash['last_run'] or {}).get('ts', '—')}**"
)
st.markdown("---")

# =============================================================================
# VIEW: Explorer (inputs on right, results in middle, glance on left)
# =============================================================================

if view == "Explorer":
    # ---- 3-column layout: Left = small info; Middle = results; Right = inputs
    left, middle, right = st.columns([1.1, 2.2, 1.1])

    # RIGHT: Inputs (as requested—keep visible while scrolling the middle)
    with right:
        st.subheader("Inputs")
        pcs_raw = st.text_input(
            "Postcodes (comma-separated)",
            value="3000, 2000, 3152",
            placeholder="e.g., 3000, 2000, 3152",
            help="We compute informational estimates for these postcodes.",
        )
        usage_kl = st.number_input(
            "Annual usage (kL)",
            min_value=0.0,
            max_value=1000.0,  # guard rails so charts never ‘overshoot’
            value=160.0,
            step=10.0,
            help="Typical VIC household ~160 kL/yr (≈440 L/day).",
        )

    # LEFT: Brief guidance (no heavy content)
    with left:
        st.subheader("About")
        st.markdown(
            "- Not a switching tool; transparency + ops dashboard.\n"
            "- Estimates include fixed + usage tiers.\n"
            "- Mapping is indicative; local rules may apply."
        )

    # MIDDLE: Results (cheapest table + explainability + optional curves)
    with middle:
        st.subheader("Estimates by postcode @ selected usage")
        st.caption(
            "If multiple providers are mapped, we show the lowest estimate. "
            "Expand a row for line-item maths and metadata."
        )

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
            # Explainability drawers
            for _, row in cheap_df.iterrows():
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
            st.info("Enter at least one valid postcode in the inputs on the right.")

        st.markdown("---")

        # =====================
        # Cost vs usage section
        # =====================
        st.subheader("Cost vs usage (QA & planning)")
        st.caption("Choose a mode. In compare mode, we plot the cheapest option per postcode and also show a usage × postcode table.")

        # ---- New: mode dropdown including side-by-side compare ---------------
        cc_mode = st.selectbox(
            "Mode",
            options=[
                "Single postcode — lines per provider",
                "Compare postcodes side-by-side — cheapest per postcode",
            ],
            index=0,
            help="Switch between a single-postcode provider breakdown and a side-by-side postcode comparison.",
        )

        cc_col1, cc_col2, cc_col3, cc_col4 = st.columns([1, 1, 1, 1])
        with cc_col2:
            cc_min = st.number_input("Usage min (kL)", min_value=0.0, max_value=900.0, value=0.0, step=10.0, key="curve_min")
        with cc_col3:
            cc_max = st.number_input("Usage max (kL)", min_value=10.0, max_value=1000.0, value=200.0, step=10.0, key="curve_max")
        with cc_col4:
            cc_step = st.number_input("Step (kL)", min_value=1.0, max_value=200.0, value=10.0, step=1.0, help="Granularity of the usage grid.")

        if cc_max <= cc_min:
            st.warning("Usage max must be greater than min.")
        else:
            if cc_mode.startswith("Single postcode"):
                with cc_col1:
                    cc_pc = st.selectbox("Pick a postcode", options=["—"] + postcodes, index=0, key="curve_pc")
                if cc_pc and cc_pc != "—":
                    curve_df = _cost_curve_for_postcode(cc_pc, cc_min, cc_max, kl_step=float(cc_step))
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
                                tooltip=["Provider", "Region", "Usage (kL/yr)", "Estimated Bill ($/yr)"]
                            )
                            .properties(height=360)
                        )
                        st.altair_chart(chart, use_container_width=True)
                else:
                    st.info("Choose a postcode to plot provider lines.")

            else:  # Compare postcodes side-by-side — cheapest per postcode
                if not postcodes:
                    st.info("Enter one or more postcodes in the inputs on the right.")
                else:
                    matrix_df = _cost_matrix_for_postcodes(postcodes, cc_min, cc_max, kl_step=float(cc_step))
                    if matrix_df.empty:
                        st.info("No mapped providers for the given postcodes.")
                    else:
                        # Line chart — one line per postcode (cheapest at each usage)
                        chart = (
                            alt.Chart(matrix_df)
                            .mark_line(point=True)
                            .encode(
                                x=alt.X("Usage (kL/yr):Q", scale=alt.Scale(domain=[cc_min, cc_max])),
                                y=alt.Y("Estimated Bill ($/yr):Q"),
                                color=alt.Color("Postcode:N"),
                                tooltip=["Postcode", "Provider", "Region", "Usage (kL/yr)", "Estimated Bill ($/yr)"]
                            )
                            .properties(height=360)
                        )
                        st.altair_chart(chart, use_container_width=True)

                        # Side-by-side table (usage × postcode)
                        st.markdown("**Side-by-side table (cheapest per postcode)**")
                        pivot = matrix_df.pivot(index="Usage (kL/yr)", columns="Postcode", values="Estimated Bill ($/yr)").sort_index()
                        st.dataframe(pivot, use_container_width=True)

                        # Optional: CSV download of the pivot
                        csv = pivot.to_csv(index=True).encode("utf-8")
                        st.download_button("⬇️ Download comparison (CSV)", data=csv, file_name="water_cost_comparison_usage_by_postcode.csv", mime="text/csv")

# =============================================================================
# VIEW: Ops — Health (freshness, failures, coverage)
# =============================================================================

elif view == "Ops — Health":
    st.subheader("Provider Health (freshness, failures, coverage)")
    st.caption(
        "Reflects validation status, last checked times, non-communicating escalations, "
        "and the postcodes currently mapped to each provider."
    )
    health_df = _health_rows()
    st.dataframe(health_df, use_container_width=True, hide_index=True)

# =============================================================================
# VIEW: Ops — Incidents (triage & root cause)
# =============================================================================

elif view == "Ops — Incidents":
    st.subheader("Incidents (triage & root cause)")
    st.caption("Items auto-open for repeated failures or validation errors. Acknowledge/resolve and add notes as needed.")

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

# =============================================================================
# VIEW: Ops — Logs (operational breadcrumb trail)
# =============================================================================

elif view == "Ops — Logs":
    st.subheader("Run logs (operational breadcrumb trail)")
    st.caption("Shows scheduler toggles, validation cycles, and incident openings/updates.")

    logs = get_run_logs(limit=200)
    if not logs:
        st.info("No logs yet. Trigger a validation run or enable the scheduler.")
    else:
        logs_df = pd.DataFrame([{
            "Time (UTC)": e["ts"],
            "Event": e["event"],
            "Details": _json_preview(e.get("details", {})),
        } for e in logs])
        st.dataframe(logs_df, use_container_width=True, hide_index=True)
        with st.expander("Show full JSON logs"):
            st.json(logs)

# =============================================================================
# Footer (shows on all views)
# =============================================================================

st.markdown("---")
with st.expander("Glossary: what each column means"):
    st.markdown("""
- **Postcode** — Australian postcode being quoted.  
- **Provider / Region** — Utility and service region applicable for that postcode.  
- **Est. Cost ($/yr)** — Estimated annual bill at the selected usage; includes fixed charges plus usage tiers.  
- **Explain** — Expand a row to see line-by-line maths, threshold, FY, and data freshness.  
- **Status** — Health flag:  
  - ✅ OK: Validated and recently checked  
  - 🟡 STALE: Last check beyond SLA window  
  - ⚪ INCOMPLETE: Placeholder/zero tariffs; needs curation  
  - 🔴 ERROR: Failed validation rules  
  - 🛑 NON_COMMUNICATING: Repeated failures reached threshold  
  - 🧩 UNKNOWN: Not checked yet  
- **Postcodes (mapped)** — Postcodes currently routed to that provider (provisioning-style coverage).
    """)

st.caption("Transparency-first, ops-reliable. Static tariffs (no scraping); bring your own sources and record checks in the UI.")
