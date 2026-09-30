from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta
from pathlib import Path
import httpx
import json

from . import models, schemas, events, predictor
from .database import engine, get_db
from .predictor import haversine_km

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="BENZ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.post("/api/import-stations")
async def import_stations(lat: float, lon: float, radius_km: float = 30, db: Session = Depends(get_db)):
    data_file = Path(__file__).parent / "stations_raw.geojson"
    if not data_file.exists():
        raise HTTPException(500, "Файл stations_raw.geojson не найден")

    with open(data_file, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    features = geojson.get("features", [])
    added = 0
    skipped = 0

    for feat in features:
        props = feat.get("properties", {}) or {}
        geom = feat.get("geometry", {}) or {}

        if props.get("amenity") != "fuel":
            continue

        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        s_lon, s_lat = coords[0], coords[1]

        d = haversine_km(lat, lon, s_lat, s_lon)
        if d > radius_km:
            skipped += 1
            continue

        osm_id = feat.get("id") or props.get("@id") or f"feat_{s_lat:.4f}_{s_lon:.4f}"
        osm_id = str(osm_id).replace("/", "_")

        if db.query(models.Station).filter_by(osm_id=osm_id).first():
            skipped += 1
            continue

        name = props.get("name") or props.get("operator") or "АЗС"
        brand = props.get("brand") or props.get("operator") or props.get("name")

        db.add(models.Station(
            osm_id=osm_id,
            name=name,
            brand=brand,
            lat=s_lat,
            lon=s_lon,
        ))
        added += 1

    db.commit()
    return {"added": added, "skipped": skipped, "total_features": len(features), "source": "stations_raw.geojson"}


@app.get("/api/stations", response_model=list[schemas.StationOut])
def get_stations(lat: float, lon: float, radius_km: float = 30, fresh_minutes: int = 180, db: Session = Depends(get_db)):
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, abs(lat) / 90 + 0.5))
    stations = db.query(models.Station).filter(
        models.Station.lat.between(lat - dlat, lat + dlat),
        models.Station.lon.between(lon - dlon, lon + dlon),
    ).all()
    cutoff = datetime.utcnow() - timedelta(minutes=fresh_minutes)
    out = []
    for s in stations:
        last = (
            db.query(models.Report)
            .filter(models.Report.station_id == s.id, models.Report.created_at >= cutoff)
            .order_by(desc(models.Report.created_at))
            .first()
        )
        cnt = (
            db.query(func.count(models.Report.id))
            .filter(models.Report.station_id == s.id, models.Report.created_at >= cutoff)
            .scalar()
        )
        out.append(schemas.StationOut(
            id=s.id, name=s.name, brand=s.brand, lat=s.lat, lon=s.lon,
            last_status=last.status if last else None,
            last_report_at=last.created_at if last else None,
            reports_count=cnt,
        ))
    return out


@app.post("/api/reports", response_model=schemas.ReportOut)
def create_report(payload: schemas.ReportCreate, db: Session = Depends(get_db)):
    recent = (
        db.query(models.Report)
        .filter(
            models.Report.device_id == payload.device_id,
            models.Report.created_at >= datetime.utcnow() - timedelta(minutes=5),
        ).first()
    )
    if recent:
        raise HTTPException(429, "Слишком часто, подождите 5 минут")
    report = models.Report(**payload.model_dump())
    db.add(report)
    db.commit()
    db.refresh(report)
    if payload.station_id and payload.status in ("есть", "нет"):
        events.detect_event(db, payload.station_id, payload.status)
    if payload.status == "бензовоз":
        db.add(models.TankerSighting(
            lat=payload.lat, lon=payload.lon,
            comment=payload.comment, device_id=payload.device_id,
        ))
        db.commit()
    return report


@app.get("/api/stations/{station_id}/events", response_model=list[schemas.EventOut])
def station_events(station_id: int, limit: int = 100, db: Session = Depends(get_db)):
    return (
        db.query(models.FuelEvent)
        .filter(models.FuelEvent.station_id == station_id)
        .order_by(models.FuelEvent.created_at.desc())
        .limit(limit).all()
    )


@app.get("/api/stations/{station_id}/prediction", response_model=schemas.PredictionOut)
def station_prediction(station_id: int, db: Session = Depends(get_db)):
    p = predictor.predict_station(db, station_id)
    if not p:
        raise HTTPException(404, "АЗС не найдена")
    return p


@app.get("/api/predictions", response_model=list[schemas.PredictionOut])
def predictions(lat: float, lon: float, radius_km: float = 30, limit: int = 30, db: Session = Depends(get_db)):
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, abs(lat) / 90 + 0.5))
    stations = db.query(models.Station).filter(
        models.Station.lat.between(lat - dlat, lat + dlat),
        models.Station.lon.between(lon - dlon, lon + dlon),
    ).limit(limit).all()
    return [p for s in stations if (p := predictor.predict_station(db, s.id))]


@app.get("/api/tanker/{sighting_id}/probabilities", response_model=list[schemas.TankerProbabilityOut])
def tanker_probs(sighting_id: int, radius_km: float = 15, db: Session = Depends(get_db)):
    t = db.query(models.TankerSighting).get(sighting_id)
    if not t:
        raise HTTPException(404, "Бензовоз не найден")
    return predictor.tanker_probabilities(db, t.lat, t.lon, radius_km)


@app.get("/api/tankers")
def fresh_tankers(lat: float, lon: float, radius_km: float = 50, minutes: int = 60, db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, abs(lat) / 90 + 0.5))
    return (
        db.query(models.TankerSighting)
        .filter(
            models.TankerSighting.created_at >= cutoff,
            models.TankerSighting.lat.between(lat - dlat, lat + dlat),
            models.TankerSighting.lon.between(lon - dlon, lon + dlon),
        )
        .order_by(desc(models.TankerSighting.created_at))
        .all()
    )


@app.post("/api/admin/clear-stations")
def clear_stations(secret: str = "", db: Session = Depends(get_db)):
    if secret != "benz2026clean":
        raise HTTPException(403, "Неверный secret")
    deleted = db.query(models.Station).delete()
    db.query(models.FuelEvent).delete()
    db.query(models.Report).delete()
    db.query(models.TankerSighting).delete()
    db.commit()
    return {"deleted_stations": deleted, "message": "База очищена"}

@app.get("/api/admin/debug-geojson")
def debug_geojson():
    from pathlib import Path
    data_file = Path(__file__).parent / "stations_raw.geojson"
    result = {
        "path": str(data_file),
        "exists": data_file.exists(),
    }
    if data_file.exists():
        result["size_bytes"] = data_file.stat().st_size
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                content = f.read()
            result["first_200_chars"] = content[:200]
            parsed = json.loads(content)
            result["top_level_keys"] = list(parsed.keys()) if isinstance(parsed, dict) else f"not a dict: {type(parsed).__name__}"
            if isinstance(parsed, dict):
                result["has_features_key"] = "features" in parsed
                result["features_count"] = len(parsed.get("features", []))
                result["type"] = parsed.get("type")
        except Exception as e:
            result["parse_error"] = str(e)
    backend_dir = Path(__file__).parent
    result["files_in_backend"] = [f.name for f in backend_dir.iterdir()]
    return result


@app.get("/health")
def health():
    return {"ok": True}
@app.get("/health")
def health():
    return {"ok": True}


frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="static")

