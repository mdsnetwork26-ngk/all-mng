import re
import logging
from app.crypto import decrypt
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException

logger = logging.getLogger(__name__)


def _conn(olt):
    return {
        "device_type": "zte_zxros",
        "host": olt.ip,
        "username": olt.ssh_user or "admin",
        "password": decrypt(olt.ssh_password or ""),
        "port": olt.ssh_port or 22,
        "timeout": 30,
        "session_timeout": 60,
    }


def test_connection(olt):
    try:
        with ConnectHandler(**_conn(olt)) as conn:
            out = conn.send_command("show version", read_timeout=20)
            return True, (out or "")[:500]
    except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def show_onu_state(olt, pon_port):
    """Return (list of dict {index, serial, state, ...}, raw_text, error)."""
    cmd = f"show gpon onu state {pon_port}"
    try:
        with ConnectHandler(**_conn(olt)) as conn:
            raw = conn.send_command(cmd, read_timeout=30)
    except Exception as e:
        return [], "", str(e)
    onus = _parse_onu_state(raw)
    return onus, raw, None


def _parse_onu_state(raw):
    """
    Best-effort parser for 'show gpon onu state'.
    Typical ZTE output columns: OnuIndex  OnuType  SN  State  ...
    We extract lines containing an ONU index pattern like '1/1/1:1' or ':1'.
    """
    result = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # match lines with an ONU id token and a state word
        m = re.search(r"(\d+)\s+(\S+)\s+(\S+)\s+(online|offline|los|dyinggasp|unknown|o\d+)", line, re.I)
        if m:
            result.append({
                "index": m.group(1),
                "type": m.group(2),
                "serial": m.group(3),
                "state": m.group(4).lower(),
            })
            continue
        # alternative: lines like "gpon-onu_1/1/1:1  online"
        m2 = re.search(r"gpon-onu_[\d/]+:(\d+)\s+(\S+)", line, re.I)
        if m2:
            result.append({"index": m2.group(1), "state": m2.group(2).lower()})
    return result


def show_onu_detail(olt, onu_id):
    """onu_id like 'gpon-onu_1/1/1:1' or '1/1/1:1'."""
    cmd = f"show gpon onu detail-info {onu_id}"
    try:
        with ConnectHandler(**_conn(olt)) as conn:
            raw = conn.send_command(cmd, read_timeout=30)
    except Exception as e:
        return {}, raw if False else "", str(e)
    detail = _parse_onu_detail(raw)
    return detail, raw, None


def _parse_onu_detail(raw):
    detail = {}
    # Rx/Tx power
    m = re.search(r"Rx\s*power\s*[:=]\s*(-?[\d.]+)\s*dBm", raw, re.I)
    if m:
        detail["rx_power"] = float(m.group(1))
    m = re.search(r"Tx\s*power\s*[:=]\s*(-?[\d.]+)\s*dBm", raw, re.I)
    if m:
        detail["tx_power"] = float(m.group(1))
    m = re.search(r"(?:ONU\s*)?name\s*[:=]\s*(.+)", raw, re.I)
    if m:
        detail["name"] = m.group(1).strip()
    m = re.search(r"Serial\s*(?:number)?\s*[:=]\s*(\S+)", raw, re.I)
    if m:
        detail["serial"] = m.group(1).strip()
    m = re.search(r"State\s*[:=]\s*(\S+)", raw, re.I)
    if m:
        detail["state"] = m.group(1).lower()
    return detail


def register_onu(olt, pon_port, onu_index, onu_type, serial, name=None,
                 tcont_profile="UP-100M", vlan=100, gemport=1):
    """
    Register a new ONU and configure a basic internet service.
    Returns (success_bool, raw_output, error).
    """
    cmds = []
    cmds.append("configure terminal")
    cmds.append(f"interface {pon_port}")
    cmds.append(f"onu {onu_index} type {onu_type} sn {serial}")
    cmds.append("exit")
    cmds.append(f"interface gpon-onu_{pon_port.split('_')[-1]}:{onu_index}")
    if name:
        cmds.append(f"name {name}")
    cmds.append(f"tcont 1 name internet profile {tcont_profile}")
    cmds.append(f"gemport {gemport} name internet tcont 1")
    cmds.append(f"service-port 1 vport 1 user-vlan {vlan} vlan {vlan}")
    cmds.append("exit")
    cmds.append("exit")
    try:
        with ConnectHandler(**_conn(olt)) as conn:
            conn.enable()
            out = conn.send_config_set(cmds, read_timeout=40)
            # save
            try:
                conn.send_command("write", read_timeout=30)
            except Exception:
                pass
            return True, out, None
    except Exception as e:
        return False, "", str(e)


def delete_onu(olt, pon_port, onu_index):
    cmds = ["configure terminal", f"interface {pon_port}",
            f"no onu {onu_index}", "exit", "exit"]
    try:
        with ConnectHandler(**_conn(olt)) as conn:
            conn.enable()
            out = conn.send_config_set(cmds, read_timeout=40)
            try:
                conn.send_command("write", read_timeout=30)
            except Exception:
                pass
            return True, out, None
    except Exception as e:
        return False, "", str(e)


def rename_onu(olt, onu_id, new_name):
    cmds = ["configure terminal", f"interface {onu_id}",
            f"name {new_name}", "exit", "exit"]
    try:
        with ConnectHandler(**_conn(olt)) as conn:
            conn.enable()
            out = conn.send_config_set(cmds, read_timeout=30)
            try:
                conn.send_command("write", read_timeout=30)
            except Exception:
                pass
            return True, out, None
    except Exception as e:
        return False, "", str(e)