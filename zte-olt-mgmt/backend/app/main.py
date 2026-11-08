import os
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, OLT, OLTMetric, ONU, Alarm, ONUMetric
from app.olt_snmp import poll_olt
from app.onu_poller import poll_onus_ssh
from app.olt_ssh import (test_connection, show_onu_state, show_onu_detail,
                         register_onu, delete_onu, rename_onu)
from app.crypto import encrypt, decrypt
from app.telegram import notify_alarm, notify_onu_result, is_configured
from apscheduler.schedulers.background import BackgroundScheduler

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./olt.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(bind=engine)

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))
ONU_POLL_INTERVAL = int(os.getenv("ONU_POLL_INTERVAL", "300"))  # 0 = disabled

templates = Jinja2Templates(directory="app/templates")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _alarm_exists(db, olt_id, message):
    return db.query(Alarm).filter(
        Alarm.olt_id == olt_id, Alarm.message == message, Alarm.resolved == False).first() is not None


def poll_all_olts():
    db = SessionLocal()
    try:
        for olt in db.query(OLT).filter(OLT.enabled == True).all():
            m = poll_olt(olt)
            metric = OLTMetric(
                olt_id=olt.id,
                cpu=m.get("cpu"),
                memory=m.get("memory"),
                temperature=m.get("temperature"),
                uptime=m.get("uptime"),
                status=m.get("status", "offline"),
            )
            db.add(metric)

            # alarm on offline
            if m.get("status") != "online":
                msg = f"OLT {olt.name} ({olt.ip}) offline / tidak merespon SNMP"
                if not _alarm_exists(db, olt.id, msg):
                    db.add(Alarm(olt_id=olt.id, severity="critical", message=msg))
                    db.commit()
                    notify_alarm("critical", msg)
            else:
                # auto-resolve offline alarms
                db.query(Alarm).filter(Alarm.olt_id == olt.id, Alarm.message.like("OLT%offline%"),
                                           Alarm.resolved == False).update({"resolved": True})
                db.commit()

            # alarm on high temp
            t = m.get("temperature")
            if t is not None and t > 60:
                msg = f"OLT {olt.name} suhu tinggi: {t}°C"
                if not _alarm_exists(db, olt.id, msg):
                    db.add(Alarm(olt_id=olt.id, severity="major", message=msg))
                    db.commit()
                    notify_alarm("major", msg)
            db.commit()
    except Exception as e:
        print("poll error:", e)
    finally:
        db.close()


def record_onu_metric(db, olt_id, onu_index, rx, tx, status):
    m = ONUMetric(olt_id=olt_id, onu_index=onu_index, rx_power=rx,
                  tx_power=tx, status=status)
    db.add(m)
    db.commit()


def poll_all_onus():
    if ONU_POLL_INTERVAL <= 0:
        return
    db = SessionLocal()
    try:
        for olt in db.query(OLT).filter(OLT.enabled == True).all():
            try:
                results = poll_onus_ssh(olt)
            except Exception as e:
                print("onu poll error:", e)
                continue
            for r in results:
                record_onu_metric(db, olt.id, r["onu_index"], r["rx_power"],
                                  r["tx_power"], r["state"])
                # alarm + notify on weak optical
                rx = r["rx_power"]
                if rx is not None and (rx < -28 or rx > -8):
                    msg = f"ONU {r['onu_id']} redaman {'lemah' if rx < -28 else 'terlalu kuat'}: {rx} dBm (OLT {olt.name})"
                    if not _alarm_exists(db, olt.id, msg):
                        db.add(Alarm(olt_id=olt.id, severity="major", message=msg))
                        db.commit()
                        notify_alarm("major", msg)
                        notify_onu_result(olt.name, r["onu_id"], rx, r["tx_power"], r["state"])
    except Exception as e:
        print("poll_all_onus error:", e)
    finally:
        db.close()


scheduler = BackgroundScheduler()
scheduler.add_job(poll_all_olts, "interval", seconds=POLL_INTERVAL)
if ONU_POLL_INTERVAL > 0:
    scheduler.add_job(poll_all_onus, "interval", seconds=ONU_POLL_INTERVAL)
scheduler.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # seed: poll once at startup
    poll_all_olts()
    yield
    scheduler.shutdown()


app = FastAPI(title="ZTE OLT Management", lifespan=lifespan)
import os as _os
if _os.path.isdir("app/static"):
    app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    db = SessionLocal()
    olts = db.query(OLT).all()
    latest = {}
    for o in olts:
        m = db.query(OLTMetric).filter(OLTMetric.olt_id == o.id).order_by(OLTMetric.id.desc()).first()
        latest[o.id] = m
    alarms = db.query(Alarm).filter(Alarm.resolved == False).order_by(Alarm.id.desc()).limit(20).all()
    db.close()
    return templates.TemplateResponse("index.html", {
        "request": request, "olts": olts, "latest": latest, "alarms": alarms,
    })


@app.get("/olts", response_class=HTMLResponse)
def olts_page(request: Request):
    db = SessionLocal()
    olts = db.query(OLT).all()
    db.close()
    return templates.TemplateResponse("olts.html", {"request": request, "olts": olts})


@app.post("/olts/add")
def add_olt(name: str = Form(...), ip: str = Form(...),
            community: str = Form("public"), ssh_user: str = Form(""),
            ssh_password: str = Form("")):
    db = SessionLocal()
    olt = OLT(name=name, ip=ip, snmp_community=community,
              ssh_user=ssh_user, ssh_password=encrypt(ssh_password))
    db.add(olt)
    db.commit()
    db.close()
    return RedirectResponse("/olts", status_code=303)


@app.post("/olts/{olt_id}/delete")
def delete_olt(olt_id: int):
    db = SessionLocal()
    olt = db.query(OLT).get(olt_id)
    if olt:
        db.delete(olt)
        db.commit()
    db.close()
    return RedirectResponse("/olts", status_code=303)


@app.get("/olts/{olt_id}", response_class=HTMLResponse)
def olt_detail(request: Request, olt_id: int):
    db = SessionLocal()
    olt = db.query(OLT).get(olt_id)
    if not olt:
        raise HTTPException(404, "OLT not found")
    metrics = db.query(OLTMetric).filter(OLTMetric.olt_id == olt_id).order_by(OLTMetric.id.desc()).limit(50).all()
    db.close()
    return templates.TemplateResponse("olt_detail.html", {
        "request": request, "olt": olt, "metrics": metrics,
    })


@app.get("/api/metrics/{olt_id}")
def api_metrics(olt_id: int):
    db = SessionLocal()
    rows = db.query(OLTMetric).filter(OLTMetric.olt_id == olt_id).order_by(OLTMetric.id.desc()).limit(60).all()
    db.close()
    return [{"ts": r.ts.isoformat(), "cpu": r.cpu, "memory": r.memory,
             "temperature": r.temperature, "status": r.status} for r in rows]


@app.get("/olts/{olt_id}/onus", response_class=HTMLResponse)
def onus_page(request: Request, olt_id: int, pon: str = "gpon-olt_1/1/1"):
    db = SessionLocal()
    olt = db.query(OLT).get(olt_id)
    db.close()
    if not olt:
        raise HTTPException(404, "OLT not found")
    onus, raw, err = show_onu_state(olt, pon)
    return templates.TemplateResponse("onus.html", {
        "request": request, "olt": olt, "pon": pon, "onus": onus,
        "raw": raw, "err": err,
    })


@app.get("/olts/{olt_id}/onus/{onu_index}/detail", response_class=HTMLResponse)
def onu_detail(request: Request, olt_id: int, onu_index: str, pon: str = "gpon-olt_1/1/1"):
    db = SessionLocal()
    olt = db.query(OLT).get(olt_id)
    db.close()
    if not olt:
        raise HTTPException(404, "OLT not found")
    onu_id = f"gpon-onu_{pon.split('_')[-1]}:{onu_index}"
    detail, raw, err = show_onu_detail(olt, onu_id)
    return templates.TemplateResponse("onu_detail.html", {
        "request": request, "olt": olt, "onu_id": onu_id, "detail": detail,
        "raw": raw, "err": err,
    })


@app.post("/olts/{olt_id}/onus/register")
def onu_register(olt_id: int, pon: str = Form(...), onu_index: str = Form(...),
                 onu_type: str = Form(...), serial: str = Form(...),
                 name: str = Form(""), vlan: int = Form(100),
                 tcont_profile: str = Form("UP-100M")):
    db = SessionLocal()
    olt = db.query(OLT).get(olt_id)
    db.close()
    if not olt:
        raise HTTPException(404, "OLT not found")
    ok, out, err = register_onu(olt, pon, onu_index, onu_type, serial, name or None, tcont_profile, vlan)
    if not ok:
        raise HTTPException(500, f"Registrasi gagal: {err}")
    # notify technician with optical result
    try:
        onu_id = f"gpon-onu_{pon.split('_')[-1]}:{onu_index}"
        detail, _, _ = show_onu_detail(olt, onu_id)
        record_onu_metric(SessionLocal(), olt.id, onu_index, detail.get("rx_power"),
                          detail.get("tx_power"), detail.get("state"))
        notify_onu_result(olt.name, onu_id, detail.get("rx_power"), detail.get("tx_power"),
                          detail.get("state"), note=name or "")
    except Exception as e:
        print("notify error:", e)
    return RedirectResponse(f"/olts/{olt_id}/onus?pon={pon}", status_code=303)


@app.post("/olts/{olt_id}/onus/{onu_index}/delete")
def onu_delete(olt_id: int, onu_index: str, pon: str = Form(...)):
    db = SessionLocal()
    olt = db.query(OLT).get(olt_id)
    db.close()
    if not olt:
        raise HTTPException(404, "OLT not found")
    ok, out, err = delete_onu(olt, pon, onu_index)
    if not ok:
        raise HTTPException(500, f"Hapus gagal: {err}")
    return RedirectResponse(f"/olts/{olt_id}/onus?pon={pon}", status_code=303)


@app.post("/olts/{olt_id}/onus/{onu_index}/rename")
def onu_rename(olt_id: int, onu_index: str, pon: str = Form(...), new_name: str = Form(...)):
    db = SessionLocal()
    olt = db.query(OLT).get(olt_id)
    db.close()
    if not olt:
        raise HTTPException(404, "OLT not found")
    onu_id = f"gpon-onu_{pon.split('_')[-1]}:{onu_index}"
    ok, out, err = rename_onu(olt, onu_id, new_name)
    if not ok:
        raise HTTPException(500, f"Rename gagal: {err}")
    return RedirectResponse(f"/olts/{olt_id}/onus?pon={pon}", status_code=303)


@app.get("/api/ssh/test/{olt_id}")
def api_ssh_test(olt_id: int):
    db = SessionLocal()
    olt = db.query(OLT).get(olt_id)
    db.close()
    if not olt:
        raise HTTPException(404, "OLT not found")
    ok, msg = test_connection(olt)
    return {"ok": ok, "message": msg}


@app.get("/api/onu-metrics/{olt_id}/{onu_index}")
def api_onu_metrics(olt_id: int, onu_index: str, limit: int = 100):
    db = SessionLocal()
    rows = (db.query(ONUMetric).filter(ONUMetric.olt_id == olt_id,
                                       ONUMetric.onu_index == onu_index)
            .order_by(ONUMetric.id.desc()).limit(limit).all())
    db.close()
    return [{"ts": r.ts.isoformat(), "rx": r.rx_power, "tx": r.tx_power,
             "status": r.status} for r in reversed(rows)]


@app.post("/api/onu-poll/{olt_id}")
def api_onu_poll(olt_id: int, pon: str = "gpon-olt_1/1/1"):
    db = SessionLocal()
    olt = db.query(OLT).get(olt_id)
    db.close()
    if not olt:
        raise HTTPException(404, "OLT not found")
    try:
        results = poll_onus_ssh(olt, pon)
    except Exception as e:
        raise HTTPException(500, str(e))
    for r in results:
        record_onu_metric(SessionLocal(), olt.id, r["onu_index"], r["rx_power"],
                          r["tx_power"], r["state"])
    return {"count": len(results), "results": results}


@app.post("/alarms/{alarm_id}/resolve")
def resolve_alarm(alarm_id: int):
    db = SessionLocal()
    a = db.query(Alarm).get(alarm_id)
    if a:
        a.resolved = True
        db.commit()
    db.close()
    return RedirectResponse("/", status_code=303)