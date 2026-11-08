import logging
from pysnmp.hlapi import (
    getCmd, SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity,
)

logger = logging.getLogger(__name__)

# ---- OID map (generic + ZTE-ish) ----
OIDS = {
    "sysDescr": "1.3.6.1.2.1.1.1.0",
    "sysUpTime": "1.3.6.1.2.1.1.3.0",
    "cpu": "1.3.6.1.2.1.25.3.3.1.2.1",          # HOST-RESOURCES (may vary)
    "mem_used": "1.3.6.1.2.1.25.2.3.1.6.1",
    "mem_size": "1.3.6.1.2.1.25.2.3.1.5.1",
    "temperature": "1.3.6.1.2.1.99.1.1.1.4.1",   # ENTITY-SENSOR (may vary)
}


def snmp_get(ip, community, oid, port=161, version="2c"):
    """Return (value_str or None, error_str or None)."""
    try:
        mp_model = 1 if version == "2c" else 0  # 0=v1,1=v2c
        iterator = getCmd(
            SnmpEngine(),
            CommunityData(community, mpModel=mp_model),
            UdpTransportTarget((ip, port), timeout=3, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        if errorIndication:
            return None, str(errorIndication)
        if errorStatus:
            return None, f"{errorStatus.prettyPrint()} at {errorIndex}"
        for vb in varBinds:
            return str(vb[1]), None
        return None, "no varbinds"
    except Exception as e:
        logger.exception("snmp_get failed")
        return None, str(e)


def poll_olt(olt):
    """Poll an OLT row (SQLAlchemy OLT). Returns dict of metrics."""
    ip = olt.ip
    comm = olt.snmp_community
    port = olt.snmp_port or 161
    ver = olt.snmp_version or "2c"

    metrics = {"status": "offline", "cpu": None, "memory": None,
               "temperature": None, "uptime": None}

    # sysUpTime -> online check
    val, err = snmp_get(ip, comm, OIDS["sysUpTime"], port, ver)
    if err or val is None:
        return metrics
    metrics["status"] = "online"
    metrics["uptime"] = val

    # cpu
    v, _ = snmp_get(ip, comm, OIDS["cpu"], port, ver)
    if v is not None:
        try:
            metrics["cpu"] = float(v)
        except ValueError:
            pass

    # memory
    used, _ = snmp_get(ip, comm, OIDS["mem_used"], port, ver)
    size, _ = snmp_get(ip, comm, OIDS["mem_size"], port, ver)
    if used is not None and size not in (None, "0"):
        try:
            metrics["memory"] = round(float(used) / float(size) * 100, 1)
        except (ValueError, ZeroDivisionError):
            pass

    # temperature
    v, _ = snmp_get(ip, comm, OIDS["temperature"], port, ver)
    if v is not None:
        try:
            # ENTITY-SENSOR often returns millidegrees
            t = float(v)
            if t > 1000:
                t = t / 1000.0
            metrics["temperature"] = round(t, 1)
        except ValueError:
            pass

    return metrics


def list_interfaces(ip, community, port=161, version="2c"):
    """Return list of (ifIndex, ifDescr, ifOperStatus) via SNMP walk (best-effort)."""
    from pysnmp.hlapi import nextCmd
    result = []
    try:
        mp_model = 1 if version == "2c" else 0
        for (errInd, errStat, errIdx, varBinds) in nextCmd(
            SnmpEngine(),
            CommunityData(community, mpModel=mp_model),
            UdpTransportTarget((ip, port), timeout=3, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity("1.3.6.1.2.1.2.2.1.2")),  # ifDescr
            lexicographicMode=False,
        ):
            if errInd or errStat:
                break
            for vb in varBinds:
                idx = str(vb[0]).split(".")[-1]
                result.append((idx, str(vb[1])))
            if len(result) > 200:
                break
    except Exception:
        pass
    return result