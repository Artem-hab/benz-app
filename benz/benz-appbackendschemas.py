from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ReportCreate(BaseModel):
    station_id: Optional[int] = None
    status: str = Field(..., pattern="^(есть|нет|ограничение|очередь|бензовоз)$")
    fuel_type: Optional[str] = None
    comment: Optional[str] = None
    lat: float
    lon: float
    device_id: str

class ReportOut(ReportCreate):
    id: int
    created_at: datetime
    class Config: from_attributes = True

class StationOut(BaseModel):
    id: int
    name: str
    brand: Optional[str]
    lat: float
    lon: float
    last_status: Optional[str] = None
    last_report_at: Optional[datetime] = None
    reports_count: int = 0
    class Config: from_attributes = True

class EventOut(BaseModel):
    id: int
    station_id: int
    event_type: str
    created_at: datetime
    class Config: from_attributes = True

class PredictionOut(BaseModel):
    station_id: int
    station_name: str
    last_delivery_at: Optional[datetime]
    avg_interval_hours: Optional[float]
    next_delivery_eta: Optional[datetime]
    avg_runout_hours: Optional[float]
    predicted_runout_eta: Optional[datetime]
    confidence: float

class TankerProbabilityOut(BaseModel):
    station_id: int
    station_name: str
    lat: float
    lon: float
    distance_km: float
    probability: float