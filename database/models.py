from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    TIMESTAMP,
    Date,
    Numeric,
    Boolean,
    ForeignKey,
    Float,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import BOOLEAN, JSONB


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

    referrals = relationship(
        "Referral",
        back_populates="candidate",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    messages = relationship(
        "Message",
        back_populates="candidate",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events = relationship(
        "ConversationEvent",
        back_populates="candidate",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


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


class Message(Base):
    """
    Immutable log of inbound/outbound messages (email) related to a candidate.
    Stores thread/message IDs for Gmail, parsed intent and structured metadata.
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    gmail_message_id = Column(String, unique=True, nullable=False)
    gmail_thread_id = Column(String, index=True)

    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    manager_id = Column(String, ForeignKey("hiring_managers.id"), index=True)

    direction = Column(String, nullable=False)  # 'inbound' | 'outbound'
    sender_email = Column(String, nullable=False, index=True)
    subject = Column(String)
    body = Column(Text)
    received_at = Column(TIMESTAMP, server_default=func.now(), index=True)

    intent = Column(String, nullable=True, index=True)   # e.g. 'MEETING_SCHEDULED', 'REJECTION', 'SALARY_DISCUSSION'
    meta_json = Column(JSONB, nullable=True)             # {'date': '2025-08-12', 'time': '14:00', 'salary': 75000}

    # relationships
    candidate = relationship("Candidate", back_populates="messages")
    manager = relationship("HiringManager")


class ConversationEvent(Base):
    """
    Structured, searchable events extracted from messages:
      MEETING_SCHEDULED, SALARY_DISCUSSION, REJECTION, etc.
    Links back to the source message for auditability.
    """
    __tablename__ = "conversation_events"

    id = Column(Integer, primary_key=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    event_type = Column(String, nullable=False, index=True)
    event_data = Column(JSONB, nullable=True)            # {'date':..., 'time':..., 'salary':..., 'notes':...}
    source_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), index=True)

    # relationships
    candidate = relationship("Candidate", back_populates="events")
    source_message = relationship("Message")


class CandidateStatus(Base):
    __tablename__ = "candidate_status"

    id = Column(Integer, primary_key=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), unique=True, index=True)

    current_status = Column(String, index=True)  # 'Interview Scheduled', 'Offered', etc.
    final_meeting_time = Column(TIMESTAMP, nullable=True)  # Agreed slot start

    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), index=True)


class InterviewSlot(Base):
    __tablename__ = "interview_slots"

    id = Column(Integer, primary_key=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    proposed_by = Column(String, nullable=False)  # 'manager' | 'applicant'
    start_time = Column(TIMESTAMP, nullable=False)
    end_time = Column(TIMESTAMP, nullable=True)
    status = Column(String, nullable=False, default="proposed", index=True)
    source_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), index=True)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), index=True)

    candidate = relationship("Candidate")
    source_message = relationship("Message")