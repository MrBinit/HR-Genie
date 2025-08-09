from sqlalchemy import (
    Column, Integer, String, Text, TIMESTAMP, Date, Numeric,
    Boolean, ForeignKey, Float, UniqueConstraint, func
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import BOOLEAN
from sqlalchemy import text


Base = declarative_base()

class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True)
    phone = Column(String)
    file_path = Column(String)
    uploaded_at = Column(TIMESTAMP, server_default=func.now())
    position = Column(String, nullable=True)
    status = Column(String, default="Pending")
    cv_score = Column(Float, nullable=True)
    manager_id = Column(String, ForeignKey("hiring_managers.id"), nullable=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    job_description_id = Column(Integer, ForeignKey("job_descriptions.id"))

    is_internal = Column(BOOLEAN, nullable=False, server_default=text('false'))
    summary = Column(Text, nullable=True)
    candidate_pitch = Column(Text, nullable=True)
    manager_email_body = Column(Text, nullable=True) 


    job_description = relationship("JobDescription", back_populates="candidates")
    manager = relationship("HiringManager", back_populates="candidates")
    department = relationship("Department")

    referrals = relationship("Referral", back_populates="candidate", cascade="all, delete-orphan")

class Referral(Base):
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    internal_department = Column(String, nullable=True)
    email = Column(String, nullable=False)
    verified = Column(Boolean, nullable=True)
    is_internal = Column(BOOLEAN, nullable=False, server_default=text('false'))


    referrer_employee_id = Column(String, ForeignKey("employees.id"), nullable=True)
    referrer = relationship("Employee")
    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    candidate = relationship("Candidate", back_populates="referrals")

    # same employee can refer multiple candidates
    __table_args__ = (
    UniqueConstraint("candidate_id", "email", name="uq_referral_candidate_email"),
    )

class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id = Column(Integer, primary_key=True, index=True)
    position = Column(String, nullable=False)
    file_path = Column(String, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    manager_id = Column(String, ForeignKey("hiring_managers.id"), nullable=False)
    description_text = Column(Text, nullable=True)

    manager = relationship("HiringManager", back_populates="job_descriptions")
    candidates = relationship("Candidate", back_populates="job_description")


class Department(Base):
    __tablename__ = "departments"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    managers = relationship("HiringManager", back_populates="department")
    employees = relationship("Employee", back_populates="department")



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


class Employee(Base):
    __tablename__ = "employees"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=True)
    position = Column(String, nullable=True)
    joining_date = Column(Date, nullable=True)
    salary = Column(Numeric(12, 2), nullable=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    department = relationship("Department", back_populates="employees")