# mail/applicant_time_request.py
import os
from datetime import datetime, timezone
from typing import Optional

from database.db import SessionLocal
from database.models import (
    Candidate,
    HiringManager,
    Message,
    ConversationEvent,
    CandidateStatus,
    InterviewSlot,
)
from mail.mail_sender import send_email_html

from dotenv import load_dotenv

load_dotenv(override=True)

SENDER_EMAIL  =  os.getenv("SENDER_EMAIL")


def _parse_iso_flexible(value: str) -> Optional[datetime]:
    """
    Accepts 'YYYY-MM-DDTHH:MM', 'YYYY-MM-DDTHH:MM:SS', or with trailing 'Z'.
    Treats naive as UTC and returns tz-aware UTC datetime.
    """
    if not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1]
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compose_applicant_time_confirmation(applicant_name: str, proposed_time_display: str, position: str, manager_name: str) -> str:
    """
    Build HTML email asking the applicant to confirm or suggest a time.
    """
    return f"""
<div style="font-family:Arial,sans-serif;line-height:1.5">
  <p>Hi {applicant_name},</p>
  <p>We are pleased to inform you that {manager_name} has proposed an interview time for the <b>{position}</b> position.</p>
  <p><b>Proposed Time:</b> {proposed_time_display}</p>
  <p>Please confirm if you are available at this time by replying to this email.</p>
  <p>If you are unavailable, kindly suggest an alternative time slot that works best for you.</p>
  <p>We look forward to your confirmation.</p>
  <p>Best regards,<br/>HR Team</p>
</div>
""".strip()


def send_time_confirmation_to_applicant(
    candidate_id: int,
    proposed_time_iso: str,
    thread_id: Optional[str] = None,
    proposed_end_time_iso: Optional[str] = None,
):
    """
    Fetch candidate + manager, create an InterviewSlot(proposed_by='manager'),
    email the applicant, log Message + ConversationEvent, and set CandidateStatus.current_status.

    Args:
        candidate_id: Candidate.id
        proposed_time_iso: ISO string e.g. '2025-08-15T14:00' or '2025-08-15T14:00:00Z'
        thread_id: (optional) Gmail thread to reply within
        proposed_end_time_iso: (optional) ISO end; if provided, stored on InterviewSlot.end_time
    """
    db = SessionLocal()
    try:
        cand = db.query(Candidate).filter_by(id=candidate_id).first()
        if not cand:
            return {"ok": False, "reason": f"Candidate with id={candidate_id} not found."}

        mgr = db.query(HiringManager).filter_by(id=cand.manager_id).first()
        if not mgr:
            return {"ok": False, "reason": f"No manager linked to candidate id={candidate_id}."}

        # Parse times to UTC (for DB) and keep a nice display string for email
        start_dt = _parse_iso_flexible(proposed_time_iso)
        end_dt = _parse_iso_flexible(proposed_end_time_iso) if proposed_end_time_iso else None

        if end_dt and start_dt and end_dt <= start_dt:
            return {"ok": False, "reason": "proposed_end_time must be after proposed_time"}

        # Create InterviewSlot (history-first)
        slot = InterviewSlot(
            candidate_id=cand.id,
            proposed_by="manager",
            start_time=start_dt if start_dt else None,  # can be None if parsing failed
            end_time=end_dt,
            status="proposed",
            source_message_id=None,  # this is an outbound initiation; you can link later when reply arrives
        )
        db.add(slot)
        db.flush()  # get slot.id

        # Email body (use the raw proposed_time string as display; optionally format from start_dt)
        display_time = proposed_time_iso if proposed_time_iso else "TBD"
        if start_dt:
            # Optional: show in ISO UTC to be explicit
            display_time = start_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        html_body = compose_applicant_time_confirmation(
            applicant_name=cand.name or "Candidate",
            proposed_time_display=display_time if not end_dt else f"{display_time} — {end_dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            position=cand.position or "the role",
            manager_name=mgr.name or "the hiring manager",
        )

        # Send email
        resp = send_email_html(
            to_email=cand.email,
            subject=f"Interview Time Confirmation – {cand.position or 'Role'}",
            html_body=html_body,
            thread_id=thread_id,
        )
        out_gmail_id = resp.get("id") if isinstance(resp, dict) else None

        # Log outbound message
        msg = Message(
            gmail_message_id=out_gmail_id or f"local-{datetime.now().timestamp()}",
            gmail_thread_id=thread_id,
            candidate_id=cand.id,
            manager_id=mgr.id,
            direction="outbound",
            sender_email=SENDER_EMAIL,
            subject=f"Interview Time Confirmation – {cand.position or 'Role'}",
            body=html_body,
            received_at=datetime.now(timezone.utc),
            intent="REQUEST_TIME_CONFIRMATION",
            meta_json={
                "proposed_time_iso": proposed_time_iso,
                **({"proposed_end_time_iso": proposed_end_time_iso} if proposed_end_time_iso else {}),
                "interview_slot_id": slot.id,
            },
        )
        db.add(msg)
        db.flush()

        # Conversation event
        db.add(
            ConversationEvent(
                candidate_id=cand.id,
                event_type="REQUEST_TIME_CONFIRMATION",
                event_data={
                    "proposed_time_iso": proposed_time_iso,
                    **({"proposed_end_time_iso": proposed_end_time_iso} if proposed_end_time_iso else {}),
                    "interview_slot_id": slot.id,
                },
                source_message_id=msg.id,
            )
        )

        # Update candidate status (cache)
        status = db.query(CandidateStatus).filter_by(candidate_id=cand.id).first()
        if not status:
            status = CandidateStatus(candidate_id=cand.id)
            db.add(status)
        status.current_status = "Awaiting Candidate Confirmation"
        # Do NOT set final_meeting_time here; only set it on acceptance.

        db.commit()
        return {"ok": True, "message_id": msg.id, "interview_slot_id": slot.id}

    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()
