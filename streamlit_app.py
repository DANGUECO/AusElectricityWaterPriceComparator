# streamlit_app.py
import time
import re
from typing import List, Dict

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

st.set_page_config(page_title="AU Water Price Comparator", page_icon="💧", layout="wide")

st.title("💧 Australian Water Price Comparator")
st.caption(
    "Prototype using your 2025–26 tariffs. Enter a postcode and annual usage (kL). "
    "Use ‘Refresh tariffs’ after you add more scrapers."
)

# ---- sidebar inputs
with st.sidebar:
    st.header("Inputs")
    postcode = st.text_input(
        "Postcode",
        value="3000",
        placeholder="e.g., 2000, 3000, 3152, 3337, 4165, 6000, 7000, 2600",
        help="Demo mapping is limited; extend POSTCODE_TO_PROVIDER in your module."
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

# ---- validation
if not re.fullmatch(r"\d{4}", (postcode or "").strip()):
    st.info("Enter a valid 4-digit Australian postcode to begin.")
    st.stop()

provider_keys: List[str] = POSTCODE_TO_PROVIDER.get(postcode.strip(), [])
if not provider_keys:
    st.warning("No mapping for this postcode. Extend POSTCODE_TO_PROVIDER in your module.")
    st.stop()

# ---- helper: build results for a given usage
def quote_for_usage(kL: float) -> pd.DataFrame:
    rows: List[Dict] = []
    for key in provider_keys:
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

        # match your CLI behaviour
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

# ---- current usage table
df = quote_for_usage(annual_kL)

left, right = st.columns([3, 2])
with left:
    st.subheader("Results")
    st.dataframe(
        df if show_notes else df.drop(columns=["Notes"]),
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Download results (CSV)",
        df.to_csv(index=False),
        file_name=f"water_quotes_{postcode}_{int(annual_kL)}kL.csv",
        mime="text/csv",
    )

with right:
    st.subheader("Cheapest at your usage")
    colname = f"Est. cost @ {annual_kL:.0f} kL"
    if df[colname].notna().any():
        cheapest = df.loc[df[colname].astype(float).idxmin()]
        st.metric(
            label=f"{cheapest['Provider']} ({cheapest['Region']})",
            value=f"${cheapest[colname]:,.2f}",
        )
    st.caption(f"🗓️ Last data refresh: {st.session_state.last_refreshed or 'not run this session'}")

# ---- optional: compare multiple usage points
if compare_usages:
    points = []
    for kL in compare_usages:
        d = quote_for_usage(float(kL))
        for _, r in d.iterrows():
            points.append({
                "Usage kL": float(kL),
                "Provider": r["Provider"],
                "Region": r["Region"],
                "Estimated cost": float(r[f"Est. cost @ {kL:.0f} kL"])
            })
    chart_df = pd.DataFrame(points)
    st.subheader("Cost vs usage (selected points)")
    chart = (
        alt.Chart(chart_df)
        .mark_line(point=True)
        .encode(
            x="Usage kL:Q",
            y="Estimated cost:Q",
            color="Provider:N",
            tooltip=["Provider", "Region", "Usage kL", "Estimated cost"]
        )
        .properties(height=340)
    )
    st.altair_chart(chart, use_container_width=True)

st.divider()
st.caption(
    "Estimates simplify some charges (e.g., trade waste, recycled water). "
    "Tariffs change each financial year; verify on provider sites."
)
