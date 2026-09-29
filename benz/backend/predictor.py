from datetime import datetime, timedelta
from statistics import mean, stdev
from math import radians, sin, cos, asin, sqrt
from sqlalchemy.orm import Session
from . import models
from .schemas import PredictionOut, TankerProbabilityOut

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def _intervals_hours(times):
    if len(times) < 2:
        return []
    times = sorted(times)
    return [(times[i+1] - times[i]).total_seconds() / 3600 for i in range(len(times) - 1)]

def predict_station(db: Session, station_id: int):
    station = db.query(models.Station).get(station_id)
    if not station:
        return None
    events = (
        db.query(models.FuelEvent)
        .filter(models.FuelEvent.station_id == station_id)
        .order_by(models.FuelEvent.created_at.asc())
        .all()
    )
    deliveries = [e.created_at for e in events if e.event_type == "delivery"]
    runouts = [e.created_at for e in events if e.event_type == "runout"]
    last_delivery = deliveries[-1] if deliveries else None
    d_intervals = _intervals_hours(deliveries)
    avg_interval = mean(d_intervals) if d_intervals else None
    life_hours = []
    for r in runouts:
        prev_delivery = max((d for d in deliveries if d < r), default=None)
        if prev_delivery:
            life_hours.append((r - prev_delivery).total_seconds() / 3600)
    avg_life = mean(life_hours) if life_hours else None
    next_delivery_eta = None
    if last_delivery and avg_interval:
        next_delivery_eta = last_delivery + timedelta(hours=avg_interval)
    predicted_runout = None
    if last_delivery and avg_life:
        predicted_runout = last_delivery + timedelta(hours=avg_life)
    confidence = 0.0
    if len(d_intervals) >= 2:
        cv = stdev(d_intervals) / avg_interval if avg_interval else 1
        confidence = max(0.0, min(1.0, 1 - cv / 2))
    elif len(d_intervals) == 1:
        confidence = 0.3
    return PredictionOut(
        station_id=station.id,
        station_name=station.name,
        last_delivery_at=last_delivery,
        avg_interval_hours=avg_interval,
        next_delivery_eta=next_delivery_eta,
        avg_runout_hours=avg_life,
        predicted_runout_eta=predicted_runout,
        confidence=round(confidence, 2),
    )

def tanker_probabilities(db: Session, lat: float, lon: float, radius_km: float = 15, top_n: int = 5):
    all_stations = db.query(models.Station).all()
    candidates = []
    now = datetime.utcnow()
    for s in all_stations:
        d = haversine_km(lat, lon, s.lat, s.lon)
        if d > radius_km:
            continue
        w_dist = 1 / (d + 0.5)
        last_report = (
            db.query(models.Report)
            .filter(models.Report.station_id == s.id)
            .order_by(models.Report.created_at.desc())
            .first()
        )
        w_status = 1.5 if last_report and last_report.status == "нет" else 0.5
        last_delivery = (
            db.query(models.FuelEvent)
            .filter(
                models.FuelEvent.station_id == s.id,
                models.FuelEvent.event_type == "delivery",
            )
            .order_by(models.FuelEvent.created_at.desc())
            .first()
        )
        if last_delivery:
            hours_since = (now - last_delivery.created_at).total_seconds() / 3600
            w_recency = min(hours_since / 24, 2.0)
        else:
            w_recency = 2.0
        score = w_dist * 2.0 + w_status * 1.0 + w_recency * 0.5
        candidates.append((s, d, score))
    if not candidates:
        return []
    total = sum(c[2] for c in candidates)
    result = [
        TankerProbabilityOut(
            station_id=s.id,
            station_name=s.name,
            lat=s.lat,
            lon=s.lon,
            distance_km=round(d, 2),
            probability=round(score / total * 100, 1),
        )
        for s, d, score in candidates
    ]
    result.sort(key=lambda x: x.probability, reverse=True)
    return result[:top_n]
