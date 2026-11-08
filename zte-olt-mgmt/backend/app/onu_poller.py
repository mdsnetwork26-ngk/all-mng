import logging
from app.olt_ssh import show_onu_state, show_onu_detail

logger = logging.getLogger(__name__)


def poll_onus_ssh(olt, pon="gpon-olt_1/1/1"):
    """Poll all ONUs on a PON port via SSH and return list of dicts with optical data."""
    onus, raw, err = show_onu_state(olt, pon)
    if err:
        logger.warning("show_onu_state failed for %s: %s", olt.name, err)
        return []
    results = []
    for o in onus:
        idx = o.get("index")
        if not idx:
            continue
        onu_id = f"gpon-onu_{pon.split('_')[-1]}:{idx}"
        detail, _, derr = show_onu_detail(olt, onu_id)
        results.append({
            "onu_index": idx,
            "onu_id": onu_id,
            "state": detail.get("state") or o.get("state"),
            "serial": detail.get("serial") or o.get("serial"),
            "rx_power": detail.get("rx_power"),
            "tx_power": detail.get("tx_power"),
            "name": detail.get("name"),
            "error": derr,
        })
    return results