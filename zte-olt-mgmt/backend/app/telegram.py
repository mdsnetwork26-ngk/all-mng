import os
import logging
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def is_configured():
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_message(text: str, parse_mode: str = "HTML"):
    if not is_configured():
        logger.debug("Telegram not configured; skip")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        with httpx.Client(timeout=10) as c:
            r = c.post(url, json=payload)
            if r.status_code != 200:
                logger.warning("Telegram send failed: %s %s", r.status_code, r.text)
                return False
            return True
    except Exception as e:
        logger.warning("Telegram error: %s", e)
        return False


def notify_alarm(severity, message):
    icon = "🔴" if severity == "critical" else "🟡" if severity == "major" else "🔵"
    return send_message(f"{icon} <b>{severity.upper()}</b>\n{message}")


def notify_onu_result(olt_name, onu_id, rx_power, tx_power=None, status=None, note=None):
    # threshold
    if rx_power is None:
        status_txt = "⚠️ Rx tidak terbaca"
    elif rx_power < -28:
        status_txt = "🔴 LEMAH (perlu perbaikan)"
    elif rx_power > -8:
        status_txt = "🟠 TERLALU KUAT"
    else:
        status_txt = "🟢 BAGUS"
    lines = [
        f"📡 <b>Hasil Redaman ONU</b>",
        f"OLT: {olt_name}",
        f"ONU: {onu_id}",
        f"Rx: {rx_power if rx_power is not None else '-'} dBm  {status_txt}",
    ]
    if tx_power is not None:
        lines.append(f"Tx: {tx_power} dBm")
    if status:
        lines.append(f"State: {status}")
    if note:
        lines.append(f"Catatan: {note}")
    return send_message("\n".join(lines))