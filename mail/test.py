# simulate_manager_replies.py
from datetime import datetime
from database.db import SessionLocal
from database.models import (
    Message, ConversationEvent, CandidateStatus,
    Candidate, HiringManager, Department
)
from services.intent_parser_llm import parse_intent_llm

# Fake test emails (simulate Gmail fetcher output)
fake_emails = [
    {
        'id': 'fake_msg_1',
        'threadId': 'thread_123',
        'candidate_id': 2,
        'manager_id': 'mgr_1',
        'from': 'manager@example.com',
        'subject': 'Interview Scheduling',
        'body': "Let's schedule the interview on 15 August 2025 at 2:30 PM."
    },
    {
        'id': 'fake_msg_2',
        'threadId': 'thread_124',
        'candidate_id': 2,
        'manager_id': 'mgr_1',
        'from': 'manager@example.com',
        'subject': 'Salary Offer',
        'body': "We can offer NPR 150,000 monthly for this position."
    },
    {
        'id': 'fake_msg_3',
        'threadId': 'thread_125',
        'candidate_id': 3,
        'manager_id': 'mgr_2',
        'from': 'manager2@example.com',
        'subject': 'Rejection',
        'body': "We cannot move forward with this candidate."
    }
]

def ensure_related_records(session, candidate_id, manager_id, manager_email):
    """Ensure department, manager, and candidate exist before inserting messages."""

    # Ensure Department
    dept_id = "dept_1"
    dept = session.query(Department).filter_by(id=dept_id).first()
    if not dept:
        dept = Department(id=dept_id, name="Default Department")
        session.add(dept)
        session.commit()

    # Ensure Manager
    mgr = session.query(HiringManager).filter_by(id=manager_id).first()
    if not mgr:
        mgr = HiringManager(
            id=manager_id,
            name=f"Manager {manager_id}",
            email=manager_email,
            phone="0000000000",
            department_id=dept_id
        )
        session.add(mgr)
        session.commit()

    # Ensure Candidate
    cand = session.query(Candidate).filter_by(id=candidate_id).first()
    if not cand:
        cand = Candidate(
            id=candidate_id,
            name=f"Candidate {candidate_id}",
            email=f"candidate{candidate_id}@example.com",
            phone="1111111111",
            position="Test Position",
            manager_id=manager_id,
            department_id=dept_id
        )
        session.add(cand)
        session.commit()

def simulate_ingest():
    session = SessionLocal()

    for email in fake_emails:
        # Make sure foreign key records exist
        ensure_related_records(session, email['candidate_id'], email['manager_id'], email['from'])

        # Save raw message
        msg = Message(
            gmail_message_id=email['id'],
            gmail_thread_id=email['threadId'],
            candidate_id=email['candidate_id'],
            manager_id=email['manager_id'],
            direction="inbound",
            sender_email=email['from'],
            subject=email.get('subject', ''),
            body=email['body'],
            received_at=datetime.utcnow()
        )
        session.add(msg)
        session.flush()

        # Parse with LLM
        intent, meta = parse_intent_llm(email['body'])

        # Save conversation event
        event = ConversationEvent(
            candidate_id=email['candidate_id'],
            event_type=intent,
            event_data=meta,
            source_message_id=msg.id
        )
        session.add(event)

        # Update candidate status
        status = session.query(CandidateStatus).filter_by(candidate_id=email['candidate_id']).first()
        if not status:
            status = CandidateStatus(candidate_id=email['candidate_id'])
            session.add(status)

        if intent == "MEETING_SCHEDULED" and meta.get('meeting_iso'):
            status.current_status = "Interview Scheduled"
            status.last_meeting_time = datetime.fromisoformat(meta['meeting_iso'])

        elif intent == "SALARY_DISCUSSION" and meta.get('salary_amount'):
            status.current_status = "Salary Discussed"
            status.last_salary_offer = meta['salary_amount']

        elif intent == "REJECTION":
            status.current_status = "Rejected"

        session.commit()

    print(f"✅ Simulated ingest of {len(fake_emails)} manager replies.")

if __name__ == "__main__":
    simulate_ingest()
