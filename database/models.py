from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, func, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True)
    phone = Column(String)
    file_path = Column(String)
    summary = Column(Text, nullable=True)
    candidate_pitch = Column(Text, nullable=True)
    uploaded_at = Column(TIMESTAMP, server_default=func.now())
    position = Column(String, nullable=True)
    status = Column(String, default="Pending")
    manager_id = Column(String, ForeignKey("hiring_managers.id"), nullable=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)

    manager = relationship("HiringManager", back_populates="candidates")
    department = relationship("Department")
    referrals = relationship("Referral", back_populates="candidate", cascade="all, delete-orphan")

class Referral(Base):
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    company = Column(String, nullable=True)
    email = Column(String, nullable=False)
    verified = Column(Boolean, default=False)

    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    candidate = relationship("Candidate", back_populates="referrals")


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id = Column(Integer, primary_key=True, index=True)
    position = Column(String, nullable=False)
    description_text = Column(Text, nullable=True)
    file_path = Column(String, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    manager_id = Column(String, ForeignKey("hiring_managers.id"), nullable=False)
    manager = relationship("HiringManager", back_populates="job_descriptions")




class Department(Base):
    __tablename__ = "departments"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    managers = relationship("HiringManager", back_populates="department")


class HiringManager(Base):
    __tablename__ = "hiring_managers"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    phone = Column(String, nullable=True)

    department_id = Column(String, ForeignKey("departments.id"), nullable=False)
    department = relationship("Department", back_populates="managers")
    job_descriptions = relationship("JobDescription", back_populates="manager")
    candidates = relationship("Candidate", back_populates="manager")

