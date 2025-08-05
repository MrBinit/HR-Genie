from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

DB_USER = os.getenv("POSTGRES_USER", "hr_user")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "hr_password")
DB_NAME = os.getenv("POSTGRES_DB", "hr_db")
DB_HOST = os.getenv("POSTGRES_HOST", "hr_postgres")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

