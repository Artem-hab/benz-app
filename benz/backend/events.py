from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from . import models

def get_last_status(db: Session, station_id: int):
    last = (
        db.query(models.Report)
        .filter(
            models.Report.station_id == station_id,
            models.Report.status.in_(["есть", "нет", "ограничение"]),
        )
        .order_by(models.Report.created_at.desc())
        .first()
    )
    return last.status if last else None

def detect_event(db: Session, station_id: int, new_status: str):
    prev = get_last_status(db, station_id)
    event_type = None
    if prev == "нет" and new_status == "есть":
        event_type = "delivery"
    elif prev in ("есть", "ограничение") and new_status == "нет":
        event_type = "runout"
    if not event_type:
        return None
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    dup = (
        db.query(models.FuelEvent)
        .filter(
            models.FuelEvent.station_id == station_id,
            models.FuelEvent.event_type == event_type,
            models.FuelEvent.created_at >= cutoff,
        )
        .first()
    )
    if dup:
        return None
    event = models.FuelEvent(
        station_id=station_id,
        event_type=event_type,
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
