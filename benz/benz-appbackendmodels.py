from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class Station(Base):
    __tablename__ = "stations"
    id = Column(Integer, primary_key=True)
    osm_id = Column(String, unique=True, index=True)
    name = Column(String)
    brand = Column(String, nullable=True)
    lat = Column(Float, index=True)
    lon = Column(Float, index=True)
    reports = relationship("Report", back_populates="station")
    events = relationship("FuelEvent", back_populates="station")

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), index=True)
    status = Column(String)
    fuel_type = Column(String, nullable=True)
    comment = Column(Text, nullable=True)
    lat = Column(Float)
    lon = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    device_id = Column(String, index=True)
    station = relationship("Station", back_populates="reports")

class FuelEvent(Base):
    __tablename__ = "fuel_events"
    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), index=True)
    event_type = Column(String, index=True)
    fuel_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    station = relationship("Station", back_populates="events")

class TankerSighting(Base):
    __tablename__ = "tanker_sightings"
    id = Column(Integer, primary_key=True)
    lat = Column(Float, index=True)
    lon = Column(Float, index=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    device_id = Column(String, index=True)

Index("ix_events_station_time", FuelEvent.station_id, FuelEvent.created_at)