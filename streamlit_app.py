# streamlit_app.py
import time
import re
from typing import List, Dict, Optional

import pandas as pd
import streamlit as st
import altair as alt

from water_price_app_extended import (
    Tariff,
    PROVIDERS,
    POSTCODE_TO_PROVIDER,
    calculate_bill,
    refresh_provider_data,
)

st.set_page_config(page_title="💧 AU Water Price Comparator", page_icon="💧", layout="wide")

st.title("💧 Australian Water Price Comparator")
st.caption(
    "Prototype using your 2025–26 tariffs. Enter one or two postcodes and an annual usage (kL). "
    "‘Refresh tariffs’ calls your scraping stubs when you add them."
)

# =========================
# Sidebar controls
# =========================
with st.sidebar:
    st.header("Inputs")

    postcode_a = st.text_input(
        "Postcode A",
        value="3000",
        placeholder="e.g., 2000, 3000, 3152, 3337, 4165, 6000, 7000, 2600",
    )

    compare_two = st.checkbox("Compare with a second postcode", value=True)

    postcode_b: Optional[str] = None
    if compare_two:
        postcode_b = st.text_input(
            "Postcode B",
            value="2000",
            placeholder="Second postcode (optional)",
        )

    annual_kL = st.number_input("Annual water use (kL)", min_value=0.0, value=160.0, step=10.0)

    compare_usages = st.multiselect(
        "Compare multiple usages (optional)",
        options=[120, 160, 200, 240, 300],
        default=[160, 200]
    )

    show_notes = st.checkbox("Show provider notes/assumptions", value=True)

    st.divider()
    if "last_refreshed" not in st.session_state:
        st.session_state.last_refreshed = None

    if st.button("🔄 Refresh tariffs (run scrapers)"):
        with st.spinner("Refreshing tariffs..."):
            try:
                refresh_provider_data()
                st.session_state.last_refreshed = time.strftime("%Y-%m-%d %H:%M:%S")
                st.success("Tariffs refreshed (where scrapers exist).")
            except Exception as e:
                st.error(f"Refresh failed: {e}")

# =========================
# Validation helpers
# =========================
def valid_pc(pc: Optional[str]) -> bool:
    return bool(pc) and bool(re.fullmatch(r"\d{4}", pc.strip()))

def provider_keys_for(pc: str) -> List[str]:
    return POSTCODE_TO_PROVIDER.get(pc.strip(), [])

# Require at least Postcode A to be valid
if not valid_pc(postcode_a):
    st.info("Enter a valid 4-digit **Postcode A** to begin.")
    st.stop()

if compare_two and postcode_b and not valid_pc(postcode_b):
    st.warning("Postcode B isn’t a valid 4-digit number. I’ll show Postcode A only.")

# =========================
# Core quoting function
# =========================
def quote_for_usage(postcode: str, kL: float) -> pd.DataFrame:
    rows: List[Dict] = []
    keys = provider_keys_for(postcode)
    if not keys:
        return pd.DataFrame(rows)

    for key in keys:
        tariff: Tariff = PROVIDERS.get(key)
        if not tariff:
            rows.append({
                "Provider": key, "Region": "—",
                "Fixed charges (annual)": None,
                "Usage rate(s) ($/kL)": "—",
                f"Est. cost @ {kL:.0f} kL": None,
                "Notes": "Provider data missing in PROVIDERS."
            })
            continue

        # Match your CLI behaviour: ICON has a ~200 kL/year block threshold
        threshold = 200.0 if key == "ICON" else None
        total = calculate_bill(tariff, kL, threshold_kL=threshold)

        fixed = tariff.network_charge + tariff.sewerage_charge
        if tariff.usage_charges[1] is None:
            usage_str = f"{tariff.usage_charges[0]:.4f}"
        else:
            usage_str = f"{tariff.usage_charges[0]:.4f} / {tariff.usage_charges[1]:.4f}"

        rows.append({
            "Provider": tariff.name,
            "Region": tariff.region,
            "Fixed charges (annual)": round(fixed, 2),
            "Usage rate(s) ($/kL)": usage_str,
            f"Est. cost @ {kL:.0f} kL": round(total, 2),
            "Notes": tariff.notes or "",
        })
    return pd.DataFrame(rows)

def cheapest_row(df: pd.DataFrame, kL: float) -> Optional[pd.Series]:
    col = f"Est. cost @ {kL:.0f} kL"
    if df.empty or col not in df.columns or not df[col].notna().any():
        return None
    return df.loc[df[col].astype(float).idxmin()]

# =========================
# Build results for A (+ B)
# =========================
df_a = quote_for_usage(postcode_a, annual_kL)
df_b = quote_for_usage(postcode_b, annual_kL) if (compare_two and valid_pc(postcode_b or "")) else pd.DataFrame()

# Empty mapping messages
if df_a.empty:
    st.warning(
        f"No providers mapped for **{postcode_a}** in this demo. "
        f"Extend POSTCODE_TO_PROVIDER in your module."
    )
if compare_two and valid_pc(postcode_b or "") and df_b.empty:
    st.warning(
        f"No providers mapped for **{postcode_b}** in this demo. "
        f"Extend POSTCODE_TO_PROVIDER in your module."
    )

# =========================
# Layout: two columns of results
# =========================
col_a, col_b = st.columns(2)

with col_a:
    st.subheader(f"Postcode A: {postcode_a}")
    if df_a.empty:
        st.info("No results to show.")
    else:
        st.dataframe(df_a if show_notes else df_a.drop(columns=["Notes"]), use_container_width=True, hide_index=True)
        st.download_button(
            f"Download A ({postcode_a}) CSV",
            df_a.to_csv(index=False),
            file_name=f"water_quotes_{postcode_a}_{int(annual_kL)}kL.csv",
            mime="text/csv",
        )
        cheap_a = cheapest_row(df_a, annual_kL)
        if cheap_a is not None:
            st.metric(
                label=f"Cheapest @ {annual_kL:.0f} kL",
                value=f"${cheap_a[f'Est. cost @ {annual_kL:.0f} kL']:,.2f}",
                delta=f"{cheap_a['Provider']} ({cheap_a['Region']})"
            )

with col_b:
    st.subheader(f"Postcode B: {postcode_b or '—'}")
    if df_b.empty:
        st.info("No results to show." if compare_two else "Add a second postcode to compare.")
    else:
        st.dataframe(df_b if show_notes else df_b.drop(columns=["Notes"]), use_container_width=True, hide_index=True)
        st.download_button(
            f"Download B ({postcode_b}) CSV",
            df_b.to_csv(index=False),
            file_name=f"water_quotes_{postcode_b}_{int(annual_kL)}kL.csv",
            mime="text/csv",
        )
        cheap_b = cheapest_row(df_b, annual_kL)
        if cheap_b is not None:
            st.metric(
                label=f"Cheapest @ {annual_kL:.0f} kL",
                value=f"${cheap_b[f'Est. cost @ {annual_kL:.0f} kL']:,.2f}",
                delta=f"{cheap_b['Provider']} ({cheap_b['Region']})"
            )

# =========================
# Head-to-head cheapest comparison
# =========================
st.markdown("### 🥊 Head-to-head (cheapest option at your usage)")
summary_rows = []
cheap_a = cheapest_row(df_a, annual_kL) if not df_a.empty else None
cheap_b = cheapest_row(df_b, annual_kL) if not df_b.empty else None

if cheap_a is not None:
    summary_rows.append({
        "Postcode": postcode_a,
        "Cheapest provider": f"{cheap_a['Provider']} ({cheap_a['Region']})",
        f"Cheapest cost @ {annual_kL:.0f} kL": float(cheap_a[f"Est. cost @ {annual_kL:.0f} kL"])
    })
if cheap_b is not None:
    summary_rows.append({
        "Postcode": postcode_b,
        "Cheapest provider": f"{cheap_b['Provider']} ({cheap_b['Region']})",
        f"Cheapest cost @ {annual_kL:.0f} kL": float(cheap_b[f"Est. cost @ {annual_kL:.0f} kL"])
    })

if summary_rows:
    sum_df = pd.DataFrame(summary_rows)
    st.dataframe(sum_df, use_container_width=True, hide_index=True)

    # Show difference if both exist
    if len(summary_rows) == 2:
        a_cost = summary_rows[0][f"Cheapest cost @ {annual_kL:.0f} kL"]
        b_cost = summary_rows[1][f"Cheapest cost @ {annual_kL:.0f} kL"]
        diff = abs(a_cost - b_cost)
        cheaper_pc = postcode_a if a_cost < b_cost else postcode_b
        st.success(f"At {annual_kL:.0f} kL, **{cheaper_pc}** is cheaper by **${diff:,.2f}** (comparing the cheapest options).")

# =========================
# Cheapest vs usage chart (A vs B)
# =========================
if compare_usages:
    chart_points: List[Dict] = []

    if not df_a.empty:
        for k in compare_usages:
            d = quote_for_usage(postcode_a, float(k))
            r = cheapest_row(d, float(k))
            if r is not None:
                chart_points.append({
                    "Postcode": postcode_a,
                    "Usage kL": float(k),
                    "Cheapest estimated cost": float(r[f"Est. cost @ {float(k):.0f} kL"])
                })

    if compare_two and valid_pc(postcode_b or "") and not df_b.empty:
        for k in compare_usages:
            d = quote_for_usage(postcode_b, float(k))
            r = cheapest_row(d, float(k))
            if r is not None:
                chart_points.append({
                    "Postcode": postcode_b,
                    "Usage kL": float(k),
                    "Cheapest estimated cost": float(r[f"Est. cost @ {float(k):.0f} kL"])
                })

    if chart_points:
        st.subheader("Cheapest cost vs usage (by postcode)")
        chart_df = pd.DataFrame(chart_points)
        chart = (
            alt.Chart(chart_df)
            .mark_line(point=True)
            .encode(
                x="Usage kL:Q",
                y="Cheapest estimated cost:Q",
                color="Postcode:N",
                tooltip=["Postcode", "Usage kL", "Cheapest estimated cost"]
            )
            .properties(height=360)
        )
        st.altair_chart(chart, use_container_width=True)

st.divider()
st.caption(
    "Estimates simplify some charges (e.g., trade waste, recycled water). "
    "Tariffs change each financial year; verify on provider sites. "
    f"🗓️ Last data refresh: {st.session_state.last_refreshed or 'not run this session'}"
)
