"""
water_price_app_extended.py
Compliance-first data + helpers (no live scraping).

New in this version:
- Freshness monitor with SLA and per-provider health.
- Explainability: line-item bill breakdown + metadata.
- Scheduled refresh scaffold (toggle, interval, due, manual heartbeat).
- Run logs (start/end, counts, warnings/errors), capped for size.
- Anomaly detection (schema/logic/drift/placeholder providers).
- Incident workflow (open/ack/resolve, auto-escalation).
- Non-communicating endpoint handling via failure counters.
- Lightweight JSON persistence so state survives app reloads.

Notes:
- No network calls here (keeps "compliance-first"). You can optionally
  record source URLs and last-checked timestamps via the API below.
- The Streamlit app should call `maybe_run_scheduled_refresh()` on load,
  show `get_dashboard_status()`, and surface incidents / logs.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Dict, List, Tuple, Optional, Any
import copy
import json
import os
from datetime import datetime, timezone, timedelta

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


# ------- Ops data classes -------

@dataclass
class ValidationIssue:
    provider_key: str
    code: str                  # e.g., "PLACEHOLDER", "NEGATIVE_RATE", "MONOTONICITY", "DRIFT"
    message: str
    severity: str              # "INFO" | "WARN" | "ERROR"
    context: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ProviderHealth:
    provider_key: str
    last_checked: Optional[str] = None   # ISO
    last_success: Optional[str] = None   # ISO
    failure_count: int = 0
    status: str = "UNKNOWN"              # "OK"|"STALE"|"INCOMPLETE"|"ERROR"|"NON_COMMUNICATING"|"UNKNOWN"
    notes: List[str] = field(default_factory=list)

@dataclass
class Incident:
    id: int
    provider_key: str
    code: str
    status: str                 # "open"|"acknowledged"|"resolved"
    summary: str
    details: Dict[str, Any]
    opened_at: str              # ISO
    updated_at: str             # ISO

@dataclass
class RunLogEntry:
    ts: str                     # ISO
    event: str                  # "refresh_start"|"refresh_end"|"scheduler_on"|"scheduler_off"|"incident_open"|"incident_update"
    details: Dict[str, Any]


# =========================
# Config / constants
# =========================

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

# SLA: if a provider hasn't been checked in this many days => STALE
FRESHNESS_SLA_DAYS = int(os.environ.get("WATER_APP_SLA_DAYS", "30"))

# How many consecutive failures before we escalate to "NON_COMMUNICATING"
NONCOMMUNICATION_THRESHOLD = int(os.environ.get("WATER_APP_NONCOMM_THRESHOLD", "3"))

# Where we persist ops state (json, simple and portable)
STATE_PATH = os.environ.get("WATER_APP_STATE", "ops_state.json")

# Snapshot comparison usage (for drift alerts)
DRIFT_BENCHMARK_KL = 160.0
DRIFT_ALERT_PCT = float(os.environ.get("WATER_APP_DRIFT_ALERT_PCT", "15.0"))  # % change

# Metadata (financial year / last data update)
META: Dict[str, str] = {
    "fy": "2025-26",
    "last_updated": "2025-08-14",
}

# --------------------------
# Static dataset of tariffs
# --------------------------
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

# Postcode → provider mapping (demo coverage; extend as needed)
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


# =========================
# Ops state storage (JSON)
# =========================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {
            "scheduler": {
                "enabled": False,
                "interval_minutes": 1440,
                "last_run_at": None,
                "next_run_due_at": None,
                "history": [],  # toggles
            },
            "providers": {},   # provider_key -> ProviderHealth as dict
            "incidents": [],   # list[Incident as dict]
            "runs": [],        # list[RunLogEntry as dict]
            "snapshots": {},   # fy -> provider_key -> snapshot dict
            "meta": dict(META)
        }
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            # Corrupt file? start fresh but keep a backup
            os.rename(STATE_PATH, STATE_PATH + ".bak")
            return _load_state()

def _save_state(state: Dict[str, Any]) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)

def _ensure_health(state: Dict[str, Any], provider_key: str) -> ProviderHealth:
    ph_dict = state["providers"].get(provider_key)
    if ph_dict is None:
        ph = ProviderHealth(provider_key=provider_key)
        state["providers"][provider_key] = asdict(ph)
        return ph
    # Convert to dataclass-like for use
    return ProviderHealth(**ph_dict)

def _put_health(state: Dict[str, Any], ph: ProviderHealth) -> None:
    state["providers"][ph.provider_key] = asdict(ph)

def _append_run(state: Dict[str, Any], event: str, details: Dict[str, Any]) -> None:
    entry = RunLogEntry(ts=_now_iso(), event=event, details=details)
    state["runs"].append(asdict(entry))
    # keep last 500
    if len(state["runs"]) > 500:
        state["runs"] = state["runs"][-500:]

def _next_due(dt_last: Optional[str], minutes: int) -> Optional[str]:
    if not minutes:
        return None
    base = datetime.fromisoformat(dt_last) if dt_last else datetime.now(timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat()

# =========================
# Helpers (unchanged API)
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
        thresh = threshold_kL if threshold_kL is not None else provider_threshold_keyless(tariff)  # see helper below
        base = min(annual_kL, thresh)
        excess = max(annual_kL - thresh, 0.0)
        usage_total = base * first_rate + excess * second_rate
    return network_total + usage_total

def provider_threshold_keyless(tariff: Tariff) -> float:
    """If you don't have the provider key handy, still apply default threshold."""
    return BLOCK_THRESHOLD_KL

def get_meta() -> Dict[str, str]:
    return dict(META)

def copy_providers() -> Dict[str, Tariff]:
    """Deep-copy of PROVIDERS for safe editing in the UI session."""
    return copy.deepcopy(PROVIDERS)

def copy_thresholds() -> Dict[str, float]:
    return dict(PROVIDER_THRESHOLDS)

# -------------------------
# Export helper (unchanged)
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


# =========================
# New: Explainability
# =========================

def explain_bill_breakdown(provider_key: str, annual_kL: float, thresholds: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Return a transparent breakdown for stakeholder trust."""
    t = PROVIDERS[provider_key]
    thresh = (thresholds or PROVIDER_THRESHOLDS).get(provider_key, BLOCK_THRESHOLD_KL)
    first_rate, second_rate = t.usage_charges

    items = []
    items.append({"label": "Fixed: water + sewerage", "amount": round(t.network_charge + t.sewerage_charge, 2)})

    if second_rate is None:
        items.append({"label": f"Usage @ {first_rate:.4f} $/kL × {annual_kL:.1f} kL", "amount": round(annual_kL * first_rate, 2)})
    else:
        base = min(annual_kL, thresh)
        excess = max(annual_kL - thresh, 0.0)
        items.append({"label": f"Usage tier 1 @ {first_rate:.4f} $/kL × {base:.1f} kL (≤ {thresh:.1f} kL)", "amount": round(base * first_rate, 2)})
        items.append({"label": f"Usage tier 2 @ {second_rate:.4f} $/kL × {excess:.1f} kL (> {thresh:.1f} kL)", "amount": round(excess * second_rate, 2)})

    total = sum(x["amount"] for x in items)
    effective = total / max(annual_kL, 1e-9)
    meta = get_meta()
    return {
        "provider_key": provider_key,
        "provider_name": t.name,
        "region": t.region,
        "fy": meta.get("fy"),
        "last_data_updated": meta.get("last_updated"),
        "notes": t.notes,
        "threshold_kL": thresh,
        "items": items,
        "total": round(total, 2),
        "effective_$_per_kL": round(effective, 4),
    }


# =========================
# New: Validation & anomalies
# =========================

def _is_placeholder(t: Tariff) -> bool:
    u1 = t.usage_charges[0] if t.usage_charges else 0.0
    u2 = t.usage_charges[1] if t.usage_charges else None
    return (t.network_charge == 0.0 and t.sewerage_charge == 0.0 and (u1 == 0.0) and (u2 in (None, 0.0)))

def validate_provider(provider_key: str, t: Tariff) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    if _is_placeholder(t):
        issues.append(ValidationIssue(provider_key, "PLACEHOLDER", "Provider has placeholder (zero) tariffs.", "ERROR"))
        return issues

    # Non-negative checks
    if t.network_charge < 0 or t.sewerage_charge < 0:
        issues.append(ValidationIssue(provider_key, "NEGATIVE_FIXED", "Fixed charges should not be negative.", "ERROR",
                                      {"network_charge": t.network_charge, "sewerage_charge": t.sewerage_charge}))
    u1, u2 = t.usage_charges
    if u1 < 0 or (u2 is not None and u2 < 0):
        issues.append(ValidationIssue(provider_key, "NEGATIVE_RATE", "Usage rates should not be negative.", "ERROR",
                                      {"usage_charges": t.usage_charges}))

    # Monotonicity (usually tier2 >= tier1). If not, warn.
    if u2 is not None and u2 < u1:
        issues.append(ValidationIssue(provider_key, "MONOTONICITY", "Tier-2 rate is lower than Tier-1 (unusual).", "WARN",
                                      {"tier1": u1, "tier2": u2}))

    # Sanity: very large rates
    if u1 > 20 or (u2 is not None and u2 > 25):
        issues.append(ValidationIssue(provider_key, "OUTLIER_RATE", "Usage rate looks extremely high.", "WARN",
                                      {"usage_charges": t.usage_charges}))

    return issues

def _snapshot_for_drift(t: Tariff) -> Dict[str, float]:
    """Minimal snapshot for drift comparison."""
    u1, u2 = t.usage_charges
    return {
        "network_charge": float(t.network_charge),
        "sewerage_charge": float(t.sewerage_charge),
        "u1": float(u1),
        "u2": float(u2) if u2 is not None else None,
        "est160": float(calculate_bill(t, DRIFT_BENCHMARK_KL)),
    }

def _compare_drift(prev: Dict[str, Any], cur: Dict[str, Any]) -> Optional[ValidationIssue]:
    if not prev:
        return None
    try:
        est_prev, est_cur = prev.get("est160"), cur.get("est160")
        if est_prev and est_prev > 0:
            pct = (est_cur - est_prev) / est_prev * 100.0
            if abs(pct) >= DRIFT_ALERT_PCT:
                return ValidationIssue(
                    provider_key="",
                    code="DRIFT",
                    message=f"Estimated annual bill changed by {pct:.1f}% at {DRIFT_BENCHMARK_KL} kL.",
                    severity="WARN",
                    context={"prev": est_prev, "cur": est_cur, "pct": pct}
                )
    except Exception:
        return None
    return None


# =========================
# New: Refresh / health / incidents
# =========================

def refresh_all_providers(only: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    'Refresh' without hitting the web:
    - Validates all providers
    - Updates ProviderHealth timestamps and failure counters
    - Detects drift vs previous snapshots (per FY)
    - Opens incidents for ERRORs and repeated failures
    - Updates 'last_run' and schedules next according to scheduler settings
    """
    state = _load_state()
    _append_run(state, "refresh_start", {"only": only or "ALL"})

    fy = state.get("meta", {}).get("fy", META.get("fy", ""))
    snapshots = state.setdefault("snapshots", {})
    fy_snap = snapshots.setdefault(fy, {})

    total = 0
    errors = 0
    warns = 0
    opened_incidents: List[int] = []

    for key, t in PROVIDERS.items():
        if only and key not in only:
            continue

        total += 1
        ph = _ensure_health(state, key)
        ph.last_checked = _now_iso()

        issues = validate_provider(key, t)
        # attach drift warning if any
        cur_snap = _snapshot_for_drift(t)
        prev_snap = fy_snap.get(key)
        drift_issue = _compare_drift(prev_snap, cur_snap)
        if drift_issue:
            drift_issue.provider_key = key
            issues.append(drift_issue)

        # classify outcomes
        has_error = any(i.severity == "ERROR" for i in issues)
        has_warn = any(i.severity == "WARN" for i in issues)

        if _is_placeholder(t):
            ph.status = "INCOMPLETE"
            ph.failure_count += 1
            ph.notes = ["Placeholder tariffs; needs curation."]
            errors += 1
        elif has_error:
            ph.status = "ERROR"
            ph.failure_count += 1
            errors += 1
        else:
            ph.status = "OK"
            ph.last_success = ph.last_checked
            if has_warn:
                warns += 1
            # reset failure counter on success
            ph.failure_count = 0
            ph.notes = []

        # Non-communicating escalation
        if ph.failure_count >= NONCOMMUNICATION_THRESHOLD:
            ph.status = "NON_COMMUNICATING"
            opened_incidents.append(_open_or_update_incident(state, key, "NON_COMMUNICATING",
                                   f"{key} failed {ph.failure_count} consecutive checks.",
                                   {"failure_count": ph.failure_count}))

        # Open incidents for ERROR issues
        for i in issues:
            if i.severity == "ERROR":
                opened_incidents.append(_open_or_update_incident(state, key, i.code, i.message, i.context))

        _put_health(state, ph)

        # Save current snapshot for drift comparison next time
        fy_snap[key] = cur_snap

    # Apply freshness SLA (STALE)
    _apply_freshness_sla(state)

    # Update scheduler last/next run
    sch = state["scheduler"]
    sch["last_run_at"] = _now_iso()
    sch["next_run_due_at"] = _next_due(sch["last_run_at"], int(sch.get("interval_minutes") or 0))

    _append_run(state, "refresh_end", {
        "count": total, "errors": errors, "warns": warns, "incidents_opened": len([x for x in opened_incidents if x is not None])
    })
    _save_state(state)

    return {"count": total, "errors": errors, "warns": warns, "opened_incidents": [x for x in opened_incidents if x is not None]}


def _apply_freshness_sla(state: Dict[str, Any]) -> None:
    """Mark providers as STALE if last_checked older than SLA days (unless already worse)."""
    now = datetime.now(timezone.utc)
    for key in PROVIDERS.keys():
        ph = _ensure_health(state, key)
        if ph.last_checked:
            age_days = (now - datetime.fromisoformat(ph.last_checked)).days
            if age_days > FRESHNESS_SLA_DAYS and ph.status in ("OK", "UNKNOWN"):
                ph.status = "STALE"
                ph.notes = [f"Stale: last check {age_days} days ago (> {FRESHNESS_SLA_DAYS} SLA)."]
                _put_health(state, ph)
        else:
            # Never checked => stale-ish but keep UNKNOWN; first refresh will set it
            pass


# ----- Incidents -----

def _new_incident_id(state: Dict[str, Any]) -> int:
    existing = [inc["id"] for inc in state.get("incidents", [])]
    return (max(existing) + 1) if existing else 1

def _find_open_incident(state: Dict[str, Any], provider_key: str, code: str) -> Optional[Dict[str, Any]]:
    for inc in state.get("incidents", []):
        if inc["provider_key"] == provider_key and inc["code"] == code and inc["status"] in ("open", "acknowledged"):
            return inc
    return None

def _open_or_update_incident(state: Dict[str, Any], provider_key: str, code: str, summary: str, details: Dict[str, Any]) -> int:
    inc = _find_open_incident(state, provider_key, code)
    now = _now_iso()
    if inc:
        inc["details"] = {**inc.get("details", {}), **details}
        inc["updated_at"] = now
        _append_run(state, "incident_update", {"id": inc["id"], "provider_key": provider_key, "code": code})
        return inc["id"]
    # open new
    iid = _new_incident_id(state)
    new_inc = Incident(
        id=iid,
        provider_key=provider_key,
        code=code,
        status="open",
        summary=summary,
        details=details,
        opened_at=now,
        updated_at=now
    )
    state["incidents"].append(asdict(new_inc))
    _append_run(state, "incident_open", {"id": iid, "provider_key": provider_key, "code": code})
    return iid

def list_incidents(status: Optional[str] = None) -> List[Dict[str, Any]]:
    state = _load_state()
    incs = state.get("incidents", [])
    if status:
        incs = [i for i in incs if i["status"] == status]
    return incs

def update_incident(iid: int, status: str, note: Optional[str] = None) -> bool:
    state = _load_state()
    for inc in state.get("incidents", []):
        if inc["id"] == iid:
            inc["status"] = status
            inc["updated_at"] = _now_iso()
            if note:
                inc["details"] = {**inc.get("details", {}), "note": note}
            _save_state(state)
            return True
    return False


# =========================
# New: Scheduler scaffold
# =========================

def set_scheduler_enabled(enabled: bool, interval_minutes: Optional[int] = None) -> Dict[str, Any]:
    """Toggle manual scheduler flag, record history, and compute next due."""
    state = _load_state()
    sch = state["scheduler"]
    sch["enabled"] = enabled
    if interval_minutes is not None:
        sch["interval_minutes"] = int(interval_minutes)
    event = "scheduler_on" if enabled else "scheduler_off"
    sch["history"].append({"ts": _now_iso(), "enabled": enabled, "interval": sch.get("interval_minutes")})
    sch["next_run_due_at"] = _next_due(sch.get("last_run_at"), int(sch.get("interval_minutes") or 0)) if enabled else None
    _append_run(state, event, {"interval_minutes": sch.get("interval_minutes")})
    _save_state(state)
    return sch

def get_scheduler_status() -> Dict[str, Any]:
    state = _load_state()
    return state["scheduler"]

def maybe_run_scheduled_refresh() -> Optional[Dict[str, Any]]:
    """Idempotent: if scheduler is enabled and due, run refresh now."""
    state = _load_state()
    sch = state["scheduler"]
    if not sch.get("enabled"):
        return None
    due = sch.get("next_run_due_at")
    if not due:
        return None
    if datetime.now(timezone.utc) >= datetime.fromisoformat(due):
        result = refresh_all_providers()
        # state will be saved inside refresh; recompute next due
        state = _load_state()
        sch = state["scheduler"]
        sch["next_run_due_at"] = _next_due(sch.get("last_run_at"), int(sch.get("interval_minutes") or 0))
        _save_state(state)
        return result
    return None


# =========================
# New: Dashboard status
# =========================

def get_dashboard_status() -> Dict[str, Any]:
    """Aggregate counts for quick tiles in the UI."""
    state = _load_state()
    counts = {"OK": 0, "STALE": 0, "INCOMPLETE": 0, "ERROR": 0, "NON_COMMUNICATING": 0, "UNKNOWN": 0}
    for key in PROVIDERS.keys():
        ph = _ensure_health(state, key)
        counts[ph.status] = counts.get(ph.status, 0) + 1
    # validation pass rate proxy: OK / all that aren't placeholders
    total = len(PROVIDERS)
    ok = counts["OK"]
    run = state["runs"][-1] if state["runs"] else None
    return {
        "counts": counts,
        "total_providers": total,
        "validation_pass_rate": round(ok / max(total, 1) * 100.0, 1),
        "last_run": run,
        "scheduler": state["scheduler"],
        "meta": state.get("meta", META),
    }

def get_run_logs(limit: int = 50) -> List[Dict[str, Any]]:
    state = _load_state()
    return list(reversed(state.get("runs", [])[-limit:]))

def get_provider_health(provider_key: str) -> ProviderHealth:
    state = _load_state()
    return _ensure_health(state, provider_key)


# =========================
# Optional: manual metadata tweaks
# =========================

def mark_provider_checked(provider_key: str, success: bool = True, note: Optional[str] = None) -> ProviderHealth:
    """Let maintainer mark a provider as freshly checked (e.g., after manual review)."""
    state = _load_state()
    ph = _ensure_health(state, provider_key)
    ph.last_checked = _now_iso()
    if success:
        ph.last_success = ph.last_checked
        ph.status = "OK"
        ph.failure_count = 0
    else:
        ph.failure_count += 1
        if ph.failure_count >= NONCOMMUNICATION_THRESHOLD:
            ph.status = "NON_COMMUNICATING"
    if note:
        ph.notes.append(note)
    _put_health(state, ph)
    _save_state(state)
    return ph

def update_meta(fy: Optional[str] = None, last_updated: Optional[str] = None) -> Dict[str, Any]:
    state = _load_state()
    m = state.get("meta", {})
    if fy:
        m["fy"] = fy
    if last_updated:
        m["last_updated"] = last_updated
    state["meta"] = m
    _save_state(state)
    # also update module-level META so explainers match
    META.update(m)
    return m


# =========================
# Utility: pick cheapest per postcode
# (You likely already have this logic in the app UI.)
# =========================

def cheapest_for_postcode(postcode: str, annual_kL: float) -> Optional[Dict[str, Any]]:
    provs = POSTCODE_TO_PROVIDER.get(postcode, [])
    if not provs:
        return None
    best = None
    for key in provs:
        t = PROVIDERS[key]
        cost = calculate_bill(t, annual_kL, provider_threshold(key))
        if (best is None) or (cost < best["total"]):
            best = {
                "provider_key": key,
                "provider_name": t.name,
                "region": t.region,
                "total": round(cost, 2),
                "explain": explain_bill_breakdown(key, annual_kL),
            }
    return best
