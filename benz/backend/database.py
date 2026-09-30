import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


# Если Amvera передала DATABASE_URL (PostgreSQL) — используем его.
# Иначе — SQLite в папке /data (постоянное хранилище Amvera).
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # На случай старого формата postgres:// (SQLAlchemy хочет postgresql+psycopg://)
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    # Постоянное хранилище Amvera — папка /data.
    # Если её нет (локально) — используем текущую папку.
    data_dir = Path("/data")
    if not data_dir.exists() or not os.access(data_dir, os.W_OK):
        data_dir = Path("./data")
        data_dir.mkdir(exist_ok=True)

    db_path = data_dir / "fuel_map.db"
    DATABASE_URL = f"sqlite:///{db_path}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
