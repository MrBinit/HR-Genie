from sqlalchemy import Column, Integer, String, Float, Text, TIMESTAMP, func
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True)
    phone = Column(String)
    file_path = Column(String)
    score = Column(Float, nullable=True)
    summary = Column(Text, nullable=True)
    uploaded_at = Column(TIMESTAMP, server_default=func.now())
    status = Column(String, default="Pending")
