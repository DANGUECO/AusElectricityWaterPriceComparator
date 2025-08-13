"""
water_price_app_extended.py
Compliance-first data + helpers (no live scraping).

How to update data:
- Run the app and use 'Maintainer Mode' to tweak tariffs for this session.
- Click 'Export updated data as Python' to get a snippet.
- Paste that snippet back into this file (overwriting PROVIDERS/PROVIDER_THRESHOLDS/META).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import copy

# =========================
# Core types
# =========================

@dataclass
class Tariff:
    """Represents the tariff structure for a water utility.

    network_charge: annual fixed water charge (AUD)
    sewerage_charge: annual fixed sewerage charge (AUD)
    usage_charges: (first_rate, second_rate|None) in AUD/kL
    name: human-readable provider name
    region: zone/area name
    notes: free-text assumptions/limitations
    """
    network_charge: float
    sewerage_charge: float
    usage_charges: Tuple[float, Optional[float]]
    name: str
    region: str
    notes: str = ""


# Default annualised block threshold (many VIC suppliers: 440 L/day)
BLOCK_THRESHOLD_KL = 160.066

# Provider-specific annualised thresholds (kL) for first block.
PROVIDER_THRESHOLDS: Dict[str, float] = {
    "ICON": 200.0,             # Icon Water: 50,000 L/quarter ≈ 200 kL/yr
    "URBAN_UTILITIES": 300.0,  # Urban Utilities: ~822 L/day ≈ 300 kL/yr
    "SAWATER": 140.0,          # SA Water Tier 1 upper bound ≈ 140 kL/yr
    "WACORP": 150.0,           # WA Water Corp: Tier 1 up to 150 kL/yr
    # Others fall back to BLOCK_THRESHOLD_KL
}

# Static dataset of tariffs for major Australian water utilities.
# All amounts are AUD per year (fixed) or AUD/kL (usage).
PROVIDERS: Dict[str, Tariff] = {
    # New South Wales – Sydney Water
    "SYDNEY": Tariff(
        network_charge=16.90 * 4 + 22.23 * 4,  # water service + stormwater (house)
        sewerage_charge=155.89 * 4,
        usage_charges=(2.67, None),
        name="Sydney Water",
        region="standard",
        notes="Stormwater assumes single dwelling. Usage may change if storage <60%."
    ),

    # Victoria – Yarra Valley Water
    "YVW": Tariff(
        network_charge=312.98,
        sewerage_charge=607.57,
        usage_charges=(3.1702, None),
        name="Yarra Valley Water",
        region="standard",
        notes="Single usage rate; excludes trade waste/recycled water specifics."
    ),

    # Victoria – Greater Western Water (central)
    "GWW_CENTRAL": Tariff(
        network_charge=224.26,
        sewerage_charge=298.00,
        usage_charges=(3.6413, 4.1629),
        name="Greater Western Water",
        region="central",
        notes="Two-step tariff; first block ~440 L/day (~160 kL/yr)."
    ),

    # Victoria – Greater Western Water (western)
    "GWW_WESTERN": Tariff(
        network_charge=224.23,
        sewerage_charge=525.83,
        usage_charges=(2.6453, 3.4059),
        name="Greater Western Water",
        region="western",
        notes="Two-step tariff; first block ~440 L/day (~160 kL/yr)."
    ),

    # Victoria – South East Water
    "SEW": Tariff(
        network_charge=87.90,   # annual water service (21.97/quarter)
        sewerage_charge=401.65,
        usage_charges=(3.0084, 3.8383),
        name="South East Water",
        region="standard",
        notes="Two-step water tariff; some combined charges slightly higher."
    ),

    # Tasmania – TasWater (full service)
    "TASWATER": Tariff(
        network_charge=407.33,  # connected/meter size may vary in practice
        sewerage_charge=469.01,
        usage_charges=(1.2612, None),
        name="TasWater",
        region="state-wide",
        notes="Usage for drinking-quality water."
    ),

    # Western Australia – Water Corporation (Perth metro)
    "WACORP": Tariff(
        network_charge=296.89,
        sewerage_charge=0.0,  # property-value-based in reality; omitted here
        usage_charges=(2.052, 2.734),  # >500 kL third tier (5.115) omitted
        name="Water Corporation WA",
        region="Perth metropolitan",
        notes="Tiered usage: 0–150 kL $2.052/kL; 151–500 $2.734/kL; >500 $5.115 (not modelled)."
    ),

    # Australian Capital Territory – Icon Water
    "ICON": Tariff(
        network_charge=243.47,
        sewerage_charge=617.21,
        usage_charges=(2.78, 5.58),
        name="Icon Water",
        region="ACT",
        notes="Block threshold 50,000 L/quarter (~200 kL/yr)."
    ),

    # South East Queensland – Redland City Council
    "REDLAND": Tariff(
        network_charge=0.0,
        sewerage_charge=0.0,
        usage_charges=(4.337, None),
        name="Redland City Council",
        region="Redlands/Straddie",
        notes="Combined water price (bulk + local); fixed charges embedded."
    ),

    # South East Queensland – Urban Utilities (Brisbane/Ipswich region)
    "URBAN_UTILITIES": Tariff(
        network_charge=0.694 * 365,     # daily water fixed
        sewerage_charge=1.961 * 365,    # daily sewer fixed
        usage_charges=(0.981 + 3.517, 2.038 + 3.517),  # ≈ (4.498, 5.555)
        name="Urban Utilities",
        region="Brisbane/Ipswich region",
        notes="Tiered usage plus state bulk water included. Tier 1 up to ~822 L/day (~300 kL/yr)."
    ),

    # South Australia – SA Water (Metropolitan)
    "SAWATER": Tariff(
        network_charge=329.20,
        sewerage_charge=376.00,          # minimum sewerage (varies by property value in practice)
        usage_charges=(2.357, 3.365),    # Tier 3 (~3.646) not modelled
        name="SA Water",
        region="Metropolitan Adelaide",
        notes="Residential tiers: ~0–140 kL $2.357; ~140–520 $3.365; >520 $3.646 (omitted). Sewerage simplified."
    ),

    # Northern Territory – Power and Water Corporation
    "POWER_WATER_NT": Tariff(
        network_charge=0.9457 * 365,   # ≤25 mm meter daily fixed
        sewerage_charge=953.89,
        usage_charges=(2.2647, None),  # flat usage
        name="Power and Water Corporation (NT)",
        region="Darwin urban",
        notes="Assumes ≤25 mm meter for fixed water. Flat domestic water $/kL."
    ),

    # --- Placeholders to expand coverage (fill real tariffs later) ---
    "UNITYWATER": Tariff(
        0.0, 0.0, (0.0, None), "Unitywater", "Sunshine Coast/Moreton Bay",
        "TODO: add 2025–26 Unitywater tariffs."
    ),
    "GOLD_COAST_WATER": Tariff(
        0.0, 0.0, (0.0, None), "Gold Coast Water", "City of Gold Coast",
        "TODO: add 2025–26 Gold Coast tariffs."
    ),
    "LOGAN_WATER": Tariff(
        0.0, 0.0, (0.0, None), "Logan Water", "Logan City",
        "TODO: add 2025–26 Logan tariffs."
    ),
    "HUNTER": Tariff(
        0.0, 0.0, (0.0, None), "Hunter Water", "Newcastle/Lake Macquarie",
        "TODO: add 2025–26 Hunter Water tariffs."
    ),
    "CENTRAL_COAST": Tariff(
        0.0, 0.0, (0.0, None), "Central Coast Council", "Gosford/Wyong",
        "TODO: add 2025–26 Central Coast tariffs."
    ),
    "BARWON": Tariff(
        0.0, 0.0, (0.0, None), "Barwon Water", "Geelong",
        "TODO: add 2025–26 Barwon tariffs."
    ),
    "CENTRAL_HIGHLANDS": Tariff(
        0.0, 0.0, (0.0, None), "Central Highlands Water", "Ballarat",
        "TODO: add 2025–26 Central Highlands tariffs."
    ),
    "COLIBAN": Tariff(
        0.0, 0.0, (0.0, None), "Coliban Water", "Bendigo",
        "TODO: add 2025–26 Coliban tariffs."
    ),
    "GOULBURN_VALLEY": Tariff(
        0.0, 0.0, (0.0, None), "Goulburn Valley Water", "Shepparton",
        "TODO: add 2025–26 Goulburn Valley tariffs."
    ),
    "NORTH_EAST": Tariff(
        0.0, 0.0, (0.0, None), "North East Water", "Wodonga",
        "TODO: add 2025–26 North East tariffs."
    ),
    "LOWER_MURRAY": Tariff(
        0.0, 0.0, (0.0, None), "Lower Murray Water", "Mildura",
        "TODO: add 2025–26 Lower Murray tariffs."
    ),
    "AQWEST": Tariff(
        0.0, 0.0, (0.0, None), "Aqwest", "Bunbury",
        "TODO: add 2025–26 Aqwest tariffs."
    ),
    "BUSSELTON_WATER": Tariff(
        0.0, 0.0, (0.0, None), "Busselton Water", "Busselton",
        "TODO: add 2025–26 Busselton tariffs."
    ),
}

# Postcode → provider mapping (non-comprehensive demo coverage).
POSTCODE_TO_PROVIDER: Dict[str, List[str]] = {
    # NSW – Sydney Water
    "2000": ["SYDNEY"], "2006": ["SYDNEY"], "2010": ["SYDNEY"], "2020": ["SYDNEY"],
    # VIC – GWW / YVW / SEW
    "3000": ["GWW_CENTRAL"], "3004": ["GWW_CENTRAL", "YVW"], "3108": ["YVW"], "3155": ["YVW"],
    "3152": ["SEW"], "3199": ["SEW"], "3337": ["GWW_WESTERN"],
    # TAS – Hobart
    "7000": ["TASWATER"],
    # WA – Perth
    "6000": ["WACORP"], "6150": ["WACORP"],
    # ACT – Canberra
    "2600": ["ICON"],
    # QLD – Redland
    "4165": ["REDLAND"], "4183": ["REDLAND"],
    # QLD – Brisbane
    "4000": ["URBAN_UTILITIES"],
    # SA – Adelaide
    "5000": ["SAWATER"],
    # NT – Darwin
    "0800": ["POWER_WATER_NT"],
    # Extra demo coverage
    "4551": ["UNITYWATER"], "4500": ["UNITYWATER"], "4217": ["GOLD_COAST_WATER"], "4114": ["LOGAN_WATER"],
    "2300": ["HUNTER"], "2260": ["CENTRAL_COAST"], "3220": ["BARWON"], "3350": ["CENTRAL_HIGHLANDS"],
    "3550": ["COLIBAN"], "3630": ["GOULBURN_VALLEY"], "3690": ["NORTH_EAST"], "3500": ["LOWER_MURRAY"],
    "6230": ["AQWEST"], "6280": ["BUSSELTON_WATER"],
}

# Lightweight metadata
META: Dict[str, str] = {
    "fy": "2025-26",
    "last_updated": "2025-08-12",
}

# =========================
# Helpers
# =========================

def provider_threshold(key: str) -> float:
    """Return the annualised block threshold (kL) for a provider key."""
    return PROVIDER_THRESHOLDS.get(key, BLOCK_THRESHOLD_KL)

def calculate_bill(tariff: Tariff, annual_kL: float, threshold_kL: Optional[float] = None) -> float:
    """Estimate annual water charges for a provider at a given usage (kL)."""
    network_total = tariff.network_charge + tariff.sewerage_charge
    first_rate, second_rate = tariff.usage_charges
    if second_rate is None:
        usage_total = annual_kL * first_rate
    else:
        thresh = threshold_kL if threshold_kL is not None else BLOCK_THRESHOLD_KL
        base = min(annual_kL, thresh)
        excess = max(annual_kL - thresh, 0.0)
        usage_total = base * first_rate + excess * second_rate
    return network_total + usage_total

def get_meta() -> Dict[str, str]:
    return dict(META)

def copy_providers() -> Dict[str, Tariff]:
    """Deep-copy of PROVIDERS for safe editing in the UI session."""
    return copy.deepcopy(PROVIDERS)

def copy_thresholds() -> Dict[str, float]:
    return dict(PROVIDER_THRESHOLDS)

# -------------------------
# Export helper (for Maintainer Mode)
# -------------------------

def _py_str(s: str) -> str:
    return repr(s)

def export_python(
    providers: Dict[str, Tariff],
    thresholds: Dict[str, float],
    block_threshold: float = BLOCK_THRESHOLD_KL,
    meta: Optional[Dict[str, str]] = None,
) -> str:
    """Return a Python snippet to paste back into this file to persist changes."""
    lines = []
    lines.append("# === BEGIN AUTO-EXPORTED DATA ===")
    lines.append(f"BLOCK_THRESHOLD_KL = {block_threshold:.6f}")
    lines.append("")
    # thresholds
    lines.append("PROVIDER_THRESHOLDS = {")
    for k in sorted(thresholds.keys()):
        lines.append(f'    "{k}": {float(thresholds[k]):.6f},')
    lines.append("}")
    lines.append("")
    # providers
    lines.append("PROVIDERS = {")
    for k in sorted(providers.keys()):
        t = providers[k]
        u1 = float(t.usage_charges[0]) if t.usage_charges else 0.0
        u2 = t.usage_charges[1] if t.usage_charges else None
        u2_str = "None" if u2 is None else f"{float(u2):.6f}"
        lines.append(f'    "{k}": Tariff(')
        lines.append(f"        network_charge={float(t.network_charge):.6f},")
        lines.append(f"        sewerage_charge={float(t.sewerage_charge):.6f},")
        lines.append(f"        usage_charges=({u1:.6f}, {u2_str}),")
        lines.append(f"        name={_py_str(t.name)},")
        lines.append(f"        region={_py_str(t.region)},")
        lines.append(f"        notes={_py_str(t.notes)},")
        lines.append("    ),")
    lines.append("}")
    lines.append("")
    # meta
    m = dict(META)
    if meta:
        m.update(meta)
    fy = _py_str(m.get("fy", ""))
    lu = _py_str(m.get("last_updated", ""))
    lines.append(f"META = {{'fy': {fy}, 'last_updated': {lu}}}")
    lines.append("# === END AUTO-EXPORTED DATA ===")
    return "\n".join(lines)
