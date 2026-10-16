"""Friendly diagnostic labels; unknown protocol values remain visible."""

from .models import FieldDescriptor
import re

NAMES = {
    "mission_phase": "Robot status",
    "mission_error": "Status - Error",
    "not_ready_code": "Status - Readiness",
    "mission_initiator": "Status - Started by",
    "dock_state": "Dock status",
    "dock_pad_dry_state": "Pad dry status",
    "dock_pad_wash_state": "Pad wash status",
    "tank_present": "Robot water tank",
    "stats_mission_count": "Missions total",
    "stats_mission_success_count": "Missions successful",
    "stats_mission_failure_count": "Missions failed",
}
PHASES = {
    "run": "Cleaning",
    "charge": "Charging",
    "stop": "Stopped",
    "stuck": "Stuck",
    "evac": "Emptying bin",
    "padWash": "Washing pads",
    "padDry": "Drying pads",
    "refill": "Refilling tank",
    "pause": "Paused",
    "hmPostMsn": "Returning after mission",
    "hmMidMsn": "Returning to recharge",
    "hmUsrDock": "Returning to dock",
    "hmUsrChrg": "Returning to charge",
    "chargingError": "Charging error",
    "mapUpd": "Updating map",
    "chargingerror": "Charging error",
    "chgerr": "Charging error",
    "mapupd": "Updating map",
    "new": "New mission",
    "resume": "Resuming",
    "recharge": "Recharging",
    "completed": "Mission completed",
    "cancelled": "Canceled",
    "stale": "Not responding",
    "binFull": "Bin full",
    "disc": "Discovering",
    "error": "Error",
    "explore": "Exploring",
    "kidnap": "Picked up",
    "oClean": "Spot cleaning",
    "plan": "Planning",
    "polygon": "Cleaning area",
    "reloc": "Relocating",
    "room": "Cleaning room",
    "tankEmpty": "Tank empty",
    "travel": "Travelling",
    "traversal": "Traversing",
    "zone": "Cleaning zone",
    "idle": "Idle",
}
PADS = {
    "padPlate": "Pad plate fitted",
    "NoPad": "No pad",
    "noPad": "No pad",
    "dispDry": "Disposable dry pad",
    "dispWet": "Disposable wet pad",
    "reusableDry": "Reusable dry pad",
    "reusableWet": "Reusable wet pad",
    "invalid": "Invalid pad",
    "reusablewet": "Reusable wet pad",
}
DOCK = {
    300: "Dock state unknown",
    301: "Dock ready",
    302: "Emptying bin",
    303: "Emptying complete",
    304: "Stopping evacuation",
    305: "Dock updating",
    350: "Dust bag missing",
    351: "Dock clogged",
    352: "Dock sealing issue",
    353: "Dust bag full",
    354: "Dock motor failure",
    360: "Dock communication failure",
    361: "Dock evacuation report communication failure",
    362: "Dock lifetime data report communication failure",
    363: "Dock evacuation and lifetime report communication failure",
    364: "Evacuation dock detected but not communicating",
    365: "Too-frequent evacuations",
    399: "Undefined evacuation error",
}
REFILL = {
    400: "Refill state unknown",
    401: "Refill OK",
    402: "Refill started",
    403: "Refilling tank",
    404: "Refill complete",
    405: "Refill complete - insufficient water",
    406: "Dock updating",
    449: "Invalid dock state for refill",
    450: "Refill tank missing",
    451: "Refill tank low",
    452: "Refill tank level sensor issue",
    453: "Refill alignment failure",
    454: "Refill clogged",
    455: "Refill pump failure",
    456: "Incorrect robot tank",
    457: "Refill communication failure",
    458: "Cannot extend refill snorkel",
    459: "Cannot retract refill snorkel",
    460: "Dock tank level not decreasing",
    461: "Robot tank level not increasing",
    462: "Refill hardware issue",
    463: "Dock tank level decreasing unexpectedly",
    464: "Detergent tank missing or empty",
}
WASH = {
    600: "Pad wash state unknown",
    601: "Pad wash OK",
    602: "Washing pads",
    603: "Pad wash complete",
    604: "Wetting pads",
    605: "Pad wetting complete",
    606: "Dock updating",
    607: "Flushing wash tray",
    608: "Wash tray flush complete",
    650: "Clean-water tank missing",
    651: "Clean-water tank low",
    653: "Dirty-water tank missing",
    654: "Dirty-water tank full",
    668: "No pad attached",
    669: "Pad actuator stalled",
    670: "Cleaning tray out of position",
    671: "Clean-water tank empty or missing",
    672: "Dirty-water tank full or missing",
    649: "Invalid dock state for pad wash",
    652: "Clean-water level sensor issue",
    660: "Pad wash communication failure",
    661: "Dirty-water tank level not decreasing",
    662: "Dirty-water tank level not increasing",
    663: "Clean-water tank level decreasing unexpectedly",
    664: "Dirty-water tank level decreasing unexpectedly",
    665: "Pad wash hardware issue",
}
COMMON_DOCK_ERRORS = {
    500: "Reserved dock error",
    501: "Dock beacon path blocked",
    502: "Dock COC communication failure",
    503: "Dock Bluetooth communication failure",
    504: "Dock home switch failure",
    505: "Dock primary internal communication failure",
    506: "Dock secondary internal communication failure",
    507: "Dock Bluetooth pairing failure",
    508: "Dock primary processor update failure",
    509: "Dock secondary processor update failure",
    510: "Dock updating",
    511: "Dirty-water tank level sensor issue",
    512: "Dirty-water evacuation clogged",
    513: "Dirty-water pump failure",
    515: "Dirty-water control valve failure",
    516: "Wash-tray agitator motor stalled",
    517: "Wash tray overflowing",
    518: "Wash-tray agitator missing",
    519: "Robot not on dock contacts",
    520: "Dock infrared communication failure",
}
DRY = {
    700: "Pad dry state unknown",
    701: "Pad dry OK",
    702: "Drying pads",
    703: "Pad drying complete",
    704: "Drying interrupted by robot",
    705: "Drying interrupted by mission",
    706: "Drying interrupted by user",
    707: "Dock updating",
    753: "Pad not washed",
    756: "No pad attached",
    757: "Dock communication failure",
    749: "Invalid pad dry state",
    750: "Pad drying motor stalled",
    751: "Pad drying motor failed to start",
    752: "Pad drying actuator stalled",
    754: "Pad drying motor FET fault",
    755: "Pad drying hardware issue",
}
INITIATORS = {
    "matter": "Matter",
    "cloud": "Cloud",
    "manual": "Robot",
    "rmtApp": "iRobot app",
    "localApp": "Local app",
    "schedule": "Schedule",
    "none": "None",
    "demand": "Demand clean",
    "dockBtn": "Dock button",
    "alexa": "Alexa",
    "siri": "Siri",
    "google": "Google",
    "ifttt": "IFTTT",
    "iftttc": "IFTTT",
    "homey": "Homey",
    "openHAB": "openHAB",
    "yonomi": "Yonomi",
    "bosch": "Bosch",
    "swisscom": "Swisscom",
    "alismart": "AliSmart",
    "team": "Teamed robot",
    "rmtAuto": "iRobot automation",
    "loclAuto": "Local automation",
    "simAuto": "Simulated automation",
    "wifi": "Wi-Fi",
    "shell": "Shell",
    "internal": "Robot (internal)",
    "unknown": "Unknown",
}
READINESS = {
    0: "Ready",
    201: "Cannot start - stairs or drop-off detected",
    202: "Cannot start - robot suspended",
    207: "Cannot start - bin missing",
    210: "Cannot start - robot in keep-out zone",
    215: "Cannot start - battery low",
    216: "Cannot start - bin full or air duct clogged",
    218: "Cannot start - robot updating",
    222: "Cannot start - navigation module issue",
    224: "Cannot start - map issue",
    228: "Cannot start - required update",
    231: "Cannot start - clean-water tank low",
    234: "Cannot mop - mop missing",
    237: "Cannot start - battery not detected",
    238: "Cannot start - battery not detected",
    239: "Cannot start - saving map",
    251: "Cannot start - camera issue",
    266: "Cannot start - subscription issue",
    268: "Cannot start - saving map",
    283: "Cannot start - laser sensor issue",
    284: "Cannot start - incompatible map",
    285: "Cannot start - draining robot water tank",
    286: "Robot must be on the floor and ready",
    287: "Cannot vacuum - remove pad plate",
    290: "Cannot mop - attach pad plate",
}
ROBOT_ERRORS = {
    1: "Robot moved or on uneven surface",
    2: "Main brush stuck",
    4: "Left wheel stuck",
    5: "Right wheel stuck",
    6: "Cliff sensors need cleaning",
    7: "Left wheel sensor issue",
    9: "Bumper stuck",
    10: "Right wheel sensor issue",
    12: "Cliff sensor stall",
    14: "Bin missing",
    16: "Robot moved or on uneven surface",
    18: "Cannot reach dock",
    19: "Cannot leave dock - obstacle",
    22: "Robot stuck",
    24: "Navigation issue",
    26: "Vacuum motor stalled",
    29: "Robot updating",
    30: "Vacuum motor issue",
    32: "Cannot reach requested map areas",
    33: "Robot trapped",
    35: "Mop missing",
    36: "Bin full or air duct clogged",
    42: "Cannot reach room",
    44: "Robot water-bin pump may be blocked",
    46: "Battery too low to clean",
    47: "Required update",
    48: "Room entrance blocked",
    66: "Memory storage issue",
    68: "Obstacle camera issue",
    69: "Cannot find way home",
    101: "Charging - battery not detected",
    102: "Unable to charge",
    103: "Unable to charge",
    104: "Charging contacts need cleaning",
    105: "Charging contacts need cleaning",
    106: "Battery needs to cool before charging",
    107: "Battery needs to cool before charging",
    109: "Unable to charge",
    110: "Charging - battery replacement needed",
    111: "Unable to charge",
    114: "Charging issue",
    115: "Charging - battery replacement needed",
    117: "Unable to charge",
    119: "Charging contacts need cleaning",
    120: "Unable to charge",
    121: "Charging contacts need cleaning",
    1000: "Left side brush stuck",
    1001: "Right side brush stuck",
    1008: "Mop lift motor stalled",
    1010: "Cannot reach dock",
    1025: "Laser sensor issue",
    1026: "Mop tangled or stuck",
    1027: "Clean-water tank missing or low",
    1028: "Dirty-water tank or wash basin clogged",
    1029: "Incompatible map",
    1030: "Robot stuck in no-mop zone",
    1034: "Pad plate detached",
}
DOCK_STATES = {**DOCK, **REFILL, **WASH, **DRY}
DOCK_ERRORS = {
    code: label
    for group, first_error in ((DOCK, 350), (REFILL, 449), (WASH, 649), (DRY, 749))
    for code, label in group.items()
    if code >= first_error
}
DOCK_ERROR_LABELS = {0: "OK", **DOCK_ERRORS, **COMMON_DOCK_ERRORS}
ERRORS = {**ROBOT_ERRORS, **READINESS, **DOCK_ERROR_LABELS}
LABELS: dict[str, dict[str, str] | dict[int, str]] = {
    "mission_phase": PHASES,
    "detected_pad": PADS,
    "dock_state": DOCK_STATES,
    "dock_pad_wash_state": WASH,
    "dock_pad_dry_state": DRY,
    "suction_level": {2: "Light", 3: "Normal", 4: "Deep"},
    "mission_error": ERRORS,
    "dock_error": DOCK_ERROR_LABELS,
    "not_ready_code": READINESS,
    "mission_initiator": INITIATORS,
}
ICONS = {
    "robot_mqtt_connection": "mdi:lan-connect",
    "last_data_received": "mdi:clock-check-outline",
    "mission_phase": "mdi:robot-vacuum",
    "mission_error": "mdi:alert-circle-outline",
    "dock_error": "mdi:alert-circle-outline",
    "not_ready_code": "mdi:check-circle-outline",
    "mission_initiator": "mdi:account",
    "dock_state": "mdi:dock-window",
    "dock_pad_wash_state": "mdi:water-sync",
    "dock_pad_dry_state": "mdi:weather-sunny",
    "detected_pad": "mdi:square-outline",
    "suction_level": "mdi:fan",
    "tank_present": "mdi:water",
    "bin_present": "mdi:delete-outline",
    "firmware_version": "mdi:chip",
    "stats_mission_count": "mdi:counter",
    "stats_mission_success_count": "mdi:check-decagram-outline",
    "stats_mission_failure_count": "mdi:close-circle-outline",
    "stats_mission_canceled_count": "mdi:hand-back-right-outline",
    "system_powered_hours": "mdi:timer-outline",
    "runtime_hours_raw": "mdi:timer-outline",
    "runtime_minutes_raw": "mdi:timer-outline",
    "navigation_reset_count": "mdi:restart",
}


def display_value(key: str, raw: str | int | None) -> str | int | None:
    if raw is None or key not in LABELS:
        return raw
    if type(raw) is int:
        if key == "mission_error" and raw not in ERRORS:
            return f"Error {raw}"
        if key == "dock_error" and raw not in LABELS[key]:
            return f"Dock error {raw}"
        if key == "not_ready_code" and raw not in READINESS:
            return f"Readiness code {raw} (meaning unverified)"
    return next(
        (label for value, label in LABELS[key].items() if value == raw), f"Unrecognized ({raw})"
    )


def diagnostic(key: str) -> bool:
    return key in LABELS or key in ("bin_present", "tank_present", "dock_known")


def state_key(raw: str | int) -> str:
    """Stable state tokens allow frontend translations without localized state."""
    if isinstance(raw, int):
        return f"code_{raw}"
    return re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_") or "unknown"


SCREENSHOT_DIAGNOSTICS = {
    "mission_phase",
    "bin_present",
    "detected_pad",
    "dock_error",
    "dock_state",
    "firmware_version",
    "stats_mission_canceled_count",
    "stats_mission_failure_count",
    "stats_mission_success_count",
    "stats_mission_count",
    "dock_pad_dry_state",
    "dock_pad_wash_state",
    "tank_present",
    "mission_error",
    "not_ready_code",
    "mission_initiator",
    "robot_mqtt_connection",
    "last_data_received",
    "localized_map",
}

MAIN_SENSORS = {"battery", "mission_area", "mission_started"}
TRANSLATED_FIELDS = (
    SCREENSHOT_DIAGNOSTICS
    | MAIN_SENSORS
    | {
        "cleaning_mode",
        "child_lock",
        "carpet_boost",
        "two_pass",
        "pad_dry_allowed",
        "pad_wash_allowed",
        "auto_evac_frequency",
        "pad_dry_duration",
        "pad_wash_area_interval",
        "pad_wash_frequency",
        "pad_wash_time_interval",
        "suction_level",
    }
)


def expose_field(field: FieldDescriptor) -> bool:
    is_diagnostic = diagnostic(field["key"]) or field.get("entity_category") == "diagnostic"
    if is_diagnostic:
        return field["key"] in SCREENSHOT_DIAGNOSTICS
    if field.get("entity_category") == "config":
        return True
    return field["key"] in MAIN_SENSORS


def retired_unique_ids(entry_unique_id: str, fields: list[FieldDescriptor]) -> set[str]:
    keys = {"reporting", "connection_health", "locate"}
    keys.update(field["key"] for field in fields if not expose_field(field))
    return {entry_unique_id + "_" + key for key in keys}
