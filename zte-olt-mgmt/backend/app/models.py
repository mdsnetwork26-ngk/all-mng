from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class OLT(Base):
    __tablename__ = "olts"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    ip = Column(String(64), nullable=False)
    snmp_community = Column(String(64), default="public")
    snmp_version = Column(String(8), default="2c")
    snmp_port = Column(Integer, default=161)
    ssh_user = Column(String(64), default="")
    ssh_password = Column(String(128), default="")
    ssh_port = Column(Integer, default=22)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    metrics = relationship("OLTMetric", back_populates="olt", cascade="all, delete-orphan")
    onus = relationship("ONU", back_populates="olt", cascade="all, delete-orphan")


class OLTMetric(Base):
    __tablename__ = "olt_metrics"
    id = Column(Integer, primary_key=True)
    olt_id = Column(Integer, ForeignKey("olts.id"))
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    cpu = Column(Float)
    memory = Column(Float)
    temperature = Column(Float)
    uptime = Column(String(64))
    status = Column(String(16))  # online/offline
    olt = relationship("OLT", back_populates="metrics")


class ONU(Base):
    __tablename__ = "onus"
    id = Column(Integer, primary_key=True)
    olt_id = Column(Integer, ForeignKey("olts.id"))
    pon_port = Column(String(32))   # e.g. gpon-olt_1/1/1
    onu_index = Column(String(16))  # e.g. 1
    name = Column(String(128))
    serial = Column(String(64))
    status = Column(String(16))     # online/offline
    rx_power = Column(Float)
    tx_power = Column(Float)
    last_seen = Column(DateTime, default=datetime.utcnow)
    olt = relationship("OLT", back_populates="onus")


class Alarm(Base):
    __tablename__ = "alarms"
    id = Column(Integer, primary_key=True)
    olt_id = Column(Integer, ForeignKey("olts.id"))
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    severity = Column(String(16))  # critical/major/minor/info
    message = Column(Text)
    resolved = Column(Boolean, default=False)


class ONUMetric(Base):
    __tablename__ = "onu_metrics"
    id = Column(Integer, primary_key=True)
    olt_id = Column(Integer, ForeignKey("olts.id"))
    onu_index = Column(String(16), index=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    rx_power = Column(Float)
    tx_power = Column(Float)
    status = Column(String(16))