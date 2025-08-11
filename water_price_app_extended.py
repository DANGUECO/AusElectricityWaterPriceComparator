"""
water_price_app_extended.py
==========================

This module implements a national water‑price comparison tool.  It is
similar to the Victorian‑only prototype (``water_price_app.py``) but
extends coverage to include other Australian jurisdictions where price
data is publicly available.  The script maintains a local dataset of
tariffs and a sample mapping of postcodes to providers.  It also
includes stubs for web scraping functions that can be used to
refresh the tariff data from provider websites.

**Important:**  Water tariffs change every financial year and not all
utilities publish their prices in easily parseable formats.  This
dataset was assembled from the 2025–26 pricing schedules for
several major suppliers【966970947902062†L241-L409】【451232434067261†L145-L172】.  For providers
whose sites could not be scraped, we either used publicly available
approximations (e.g. Redland City Council’s combined water charge) or
left placeholders.  Use the scraping stubs or manual updates to keep
the data current.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import re
import requests
from bs4 import BeautifulSoup


@dataclass
class Tariff:
    """Represents the tariff structure for a water utility.

    Parameters
    ----------
    network_charge : float
        Annual fixed charge for water supply (per property).  For
        utilities that bill quarterly, the annual value is obtained by
        multiplying the quarterly charge by four.
    sewerage_charge : float
        Annual fixed charge for wastewater services.  When utilities
        embed all fixed charges in a single volumetric rate (e.g.
        Redland City Council), this value is set to zero.
    usage_charges : Tuple[float, Optional[float]]
        One or two usage rates expressed in dollars per kilolitre.  A
        two‑element tuple indicates a block tariff where the second
        element is the rate applied to consumption above the block
        threshold (see ``BLOCK_THRESHOLD_KL``).  If the second element
        is ``None``, the provider uses a flat rate for all usage.
    name : str
        Human‑readable name of the provider.
    region : str
        Region or zone within the provider’s service area (e.g.
        ``central`` or ``western`` for Greater Western Water).  For
        providers with a single zone this can be ``standard``.
    notes : str
        Optional notes to display when presenting results.  Use this to
        highlight assumptions (e.g. that sewerage charges have been
        simplified).
    """

    network_charge: float
    sewerage_charge: float
    usage_charges: Tuple[float, Optional[float]]
    name: str
    region: str
    notes: str = ""


# Approximate block threshold in kilolitres per year.  Many Victorian
# suppliers use 440 L/day ≈ 160.066 kL/year as the first block limit.
# Icon Water uses 50 000 L/quarter ≈ 200 kL/year.  In this simple
# implementation we default to the Victorian threshold but allow
# provider‑specific overrides when computing bills.
BLOCK_THRESHOLD_KL = 160.066


# Static dataset of tariffs for major Australian water utilities.
# All amounts are expressed in Australian dollars.
PROVIDERS: Dict[str, Tariff] = {
    # New South Wales – Sydney Water
    # Charges per quarter are multiplied by four to obtain annual
    # figures.  The water service charge is $16.90/quarter, wastewater
    # service charge $155.89/quarter and stormwater charge (house) is
    # $22.23/quarter【966970947902062†L389-L409】.  Combined annual fixed charge ≈
    # 16.90 + 155.89 + 22.23 = 195.02 per quarter -> 780.08 per year.
    "SYDNEY": Tariff(
        network_charge=16.90 * 4 + 22.23 * 4,  # water + stormwater
        sewerage_charge=155.89 * 4,
        usage_charges=(2.67, None),
        name="Sydney Water",
        region="standard",
        notes="Stormwater charge assumes a single‑dwelling house; usage rate increases to $3.61/kL if dam levels fall below 60 %【966970947902062†L241-L382】.",
    ),

    # Victoria – Yarra Valley Water
    "YVW": Tariff(
        network_charge=312.98,
        sewerage_charge=607.57,
        usage_charges=(3.1702, None),
        name="Yarra Valley Water",
        region="standard",
        notes="Single usage rate; sewerage disposal and recycled water charges not included【451232434067261†L145-L172】."
    ),

    # Victoria – Greater Western Water (central region)
    "GWW_CENTRAL": Tariff(
        network_charge=224.26,
        sewerage_charge=298.00,
        usage_charges=(3.6413, 4.1629),
        name="Greater Western Water",
        region="central",
        notes="Two‑step tariff: 440 L/day threshold【758277050889561†L180-L205】."
    ),

    # Victoria – Greater Western Water (western region)
    "GWW_WESTERN": Tariff(
        network_charge=224.23,
        sewerage_charge=525.83,
        usage_charges=(2.6453, 3.4059),
        name="Greater Western Water",
        region="western",
        notes="Two‑step tariff: 440 L/day threshold; higher sewerage fee due to infrastructure costs【758277050889561†L241-L263】."
    ),

    # Victoria – South East Water
    "SEW": Tariff(
        network_charge=87.90,  # annual water service (21.97 per quarter)
        sewerage_charge=401.65,
        usage_charges=(3.0084, 3.8383),
        name="South East Water",
        region="standard",
        notes="Two‑step water‑only tariff; combined water and sewerage usage rates are slightly higher【156717191123297†L610-L671】."
    ),

    # Tasmania – TasWater (full service)
    "TASWATER": Tariff(
        network_charge=407.33,  # water fixed charge for unconnected property; typical connected charge depends on meter size
        sewerage_charge=469.01,
        usage_charges=(1.2612, None),
        name="TasWater",
        region="state‑wide",
        notes="Usage rate is for drinking‑quality water; limited‑quality water is cheaper【624024359122133†L258-L277】."
    ),

    # Western Australia – Water Corporation (Perth metropolitan)
    "WACORP": Tariff(
        network_charge=296.89,
        sewerage_charge=0.0,  # Sewerage charges depend on property value and are not included
        usage_charges=(2.052, 2.734),  # second step applies from 150 kL to 500 kL; high third step omitted
        name="Water Corporation WA",
        region="Perth metropolitan",
        notes="Tiered usage: 0–150 kL $2.052/kL, 151–500 kL $2.734/kL, over 500 kL $5.115/kL【442652027044042†L432-L438】; sewerage charges vary by property value.",
    ),

    # Australian Capital Territory – Icon Water
    "ICON": Tariff(
        network_charge=243.47,
        sewerage_charge=617.21,
        usage_charges=(2.78, 5.58),
        name="Icon Water",
        region="ACT",
        notes="Block threshold is 50 000 L/quarter (~200 kL/year); second rate applies above this【431346559018546†L770-L799】."
    ),

    # South East Queensland – Redland City Council
    "REDLAND": Tariff(
        network_charge=0.0,
        sewerage_charge=0.0,
        usage_charges=(4.337, None),
        name="Redland City Council",
        region="Redlands/Straddie",
        notes="Combined water charge (bulk + local) for 2025–26【987362501762421†L374-L381】; network charges are embedded in volumetric price."
    ),

    # Placeholder for other utilities (unpopulated); these can be filled
    # via scraping functions or manual updates.
    # "SAWATER": Tariff(...),
    # "HUNTER": Tariff(...),
    # "URBAN_UTILITIES": Tariff(...),
    # "UNITYWATER": Tariff(...),
}


# Sample postcode mapping for demonstration purposes.  Each entry maps
# a postcode to one or more provider keys in the ``PROVIDERS`` dict.  In
# reality every suburb or town has a single water supplier, but a few
# postcodes straddle boundaries.  This mapping includes examples from
# multiple states and is **not comprehensive**.
POSTCODE_TO_PROVIDER: Dict[str, List[str]] = {
    # New South Wales – Sydney Water (central Sydney)
    "2000": ["SYDNEY"],  # Sydney CBD
    "2006": ["SYDNEY"],  # Camperdown/Newtown (University of Sydney)
    "2020": ["SYDNEY"],  # Mascot

    # Victoria – Greater Western Water (central) and Yarra Valley Water
    "3000": ["GWW_CENTRAL"],
    "3004": ["GWW_CENTRAL", "YVW"],  # boundary example
    "3108": ["YVW"],
    "3155": ["YVW"],
    "3152": ["SEW"],  # Wantirna South
    "3199": ["SEW"],  # Frankston
    "3337": ["GWW_WESTERN"],  # Melton

    # Tasmania – Hobart
    "7000": ["TASWATER"],  # Hobart

    # Western Australia – Perth
    "6000": ["WACORP"],  # Perth CBD
    "6150": ["WACORP"],  # Murdoch

    # Australian Capital Territory – Canberra
    "2600": ["ICON"],  # Canberra/Deakin

    # Queensland – Redland City Council (only some suburbs; demonstration)
    "4165": ["REDLAND"],  # Redland Bay
    "4183": ["REDLAND"],  # North Stradbroke Island
}


def calculate_bill(tariff: Tariff, annual_kL: float, threshold_kL: Optional[float] = None) -> float:
    """Calculate the estimated annual water bill for a given provider.

    Parameters
    ----------
    tariff : Tariff
        Tariff record for the provider.
    annual_kL : float
        Customer’s estimated annual water consumption in kilolitres.
    threshold_kL : Optional[float]
        Optional override for the block threshold.  If ``None``,
        ``BLOCK_THRESHOLD_KL`` (≈160 kL) is used.  Some providers (e.g.
        Icon Water) have different thresholds.

    Returns
    -------
    float
        Estimated total annual charge.
    """
    network_total = tariff.network_charge + tariff.sewerage_charge
    first_rate, second_rate = tariff.usage_charges

    # If provider uses single rate (no second rate), apply it to all
    # consumption.  Otherwise split consumption at the threshold.
    if second_rate is None:
        usage_total = annual_kL * first_rate
    else:
        # Determine block threshold; allow provider‑specific values
        thresh = threshold_kL if threshold_kL is not None else BLOCK_THRESHOLD_KL
        base = min(annual_kL, thresh)
        excess = max(annual_kL - thresh, 0.0)
        usage_total = base * first_rate + excess * second_rate
    return network_total + usage_total


def scrape_yvw() -> Tariff:
    """Example scraping function for Yarra Valley Water.

    Returns a Tariff instance with up‑to‑date values by parsing the
    Yarra Valley Water fees and charges page.  This stub is intended as
    an example and may need adjustment if the web page structure
    changes.  It raises requests.HTTPError if the page cannot be
    retrieved.
    """
    url = "https://www.yvw.com.au/help-advice/financial-help/understand-my-bill/fees-and-charges"
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    # Find the fixed charges
    water_charge = None
    sewer_charge = None
    usage_rate = None
    # Use regular expressions to extract numbers from the text.  The
    # patterns here are illustrative; verify them against the actual page.
    m = re.search(r"water supply system charge.*\$([0-9]+\.?[0-9]*)", text, re.IGNORECASE)
    if m:
        water_charge = float(m.group(1))
    m = re.search(r"sewerage system charge.*\$([0-9]+\.?[0-9]*)", text, re.IGNORECASE)
    if m:
        sewer_charge = float(m.group(1))
    m = re.search(r"water usage charge.*\$([0-9]+\.?[0-9]*)", text, re.IGNORECASE)
    if m:
        usage_rate = float(m.group(1))
    if water_charge and sewer_charge and usage_rate:
        return Tariff(
            network_charge=water_charge,
            sewerage_charge=sewer_charge,
            usage_charges=(usage_rate, None),
            name="Yarra Valley Water",
            region="standard",
            notes="Scraped from website"
        )
    raise ValueError("Could not extract all YVW tariff components")


def refresh_provider_data() -> None:
    """Placeholder function to refresh tariff data via scraping.

    This function demonstrates how you might update the `PROVIDERS`
    dictionary with freshly scraped values.  Only a few providers
    currently have implemented scrapers.  If scraping fails, the
    original values remain in place.
    """
    try:
        new_yvw = scrape_yvw()
        PROVIDERS["YVW"] = new_yvw
        print("Yarra Valley Water tariffs updated from website.")
    except Exception as exc:
        print(f"Warning: could not refresh YVW data: {exc}")

    # Additional scrapers (e.g. for Sydney Water, SEW) would be
    # implemented similarly and called here.


def main() -> None:
    """Command‑line interface for the water price comparison tool."""
    print("Water price comparison tool (national prototype)")
    print("This tool uses hard‑coded tariffs from 2025–26 schedules.")
    print("Enter your postcode and annual water consumption to estimate your bill.\n")

    postcode = input("Enter your postcode: ").strip()
    if postcode not in POSTCODE_TO_PROVIDER:
        print("Sorry, no data for your postcode.  Please extend the mapping in the script.")
        return
    try:
        annual_kL = float(input("Enter your annual water use in kilolitres (kL): "))
    except ValueError:
        print("Invalid consumption.  Please enter a numeric value.")
        return

    provider_keys = POSTCODE_TO_PROVIDER[postcode]
    print()
    for key in provider_keys:
        tariff = PROVIDERS.get(key)
        if not tariff:
            print(f"Provider {key} data not available.")
            continue

        # Use provider‑specific threshold if necessary (Icon Water)
        threshold = None
        if key == "ICON":
            threshold = 200.0  # 50 000 L per quarter ≈ 200 kL per year

        total = calculate_bill(tariff, annual_kL, threshold_kL=threshold)
        print(f"{tariff.name} ({tariff.region} region):")
        print(f"  Fixed charges: ${tariff.network_charge + tariff.sewerage_charge:,.2f} per year")
        if tariff.usage_charges[1] is None:
            print(f"  Usage rate: ${tariff.usage_charges[0]:.4f}/kL")
        else:
            print(f"  Usage rates: ${tariff.usage_charges[0]:.4f}/kL (first block), ${tariff.usage_charges[1]:.4f}/kL (second block)")
        print(f"  Estimated annual cost for {annual_kL:.1f} kL: ${total:,.2f}")
        if tariff.notes:
            print(f"  Notes: {tariff.notes}")
        print()


if __name__ == "__main__":
    main()