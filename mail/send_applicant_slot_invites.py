# mail/send_applicant_slot_invites.py

from datetime import datetime, timezone
from typing import List, Optional
from database.db import SessionLocal
from database.models import (
    Candidate,
    HiringManager,
    InterviewSlot,
    Message,
    ConversationEvent,
    CandidateStatus,
)
from mail.mail_sender import send_email_html


def _parse_iso_flexible(value: Optional[str]) -> Optional[datetime]:
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


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _compose_html(cand: Candidate, mgr: HiringManager, slot_rows: List[InterviewSlot]) -> str:
    items = []
    for row in slot_rows:
        if not row.start_time:
            continue
        items.append(
            f"• {_fmt_utc(row.start_time)}" + (f" — {_fmt_utc(row.end_time)}" if row.end_time else "")
        )
    choices_html = "<br/>".join(items) if items else "• (time to be confirmed)"
    return f"""
<div style="font-family:Arial,sans-serif;line-height:1.5">
  <p>Hi {cand.name or 'there'},</p>
  <p>{mgr.name or 'The hiring manager'} has proposed interview time(s) for <b>{cand.position or 'the role'}</b>.</p>
  <p><b>Suggested times (UTC):</b><br/>{choices_html}</p>
  <p>Please reply and let us know which time works for you. If none fit, please propose another time that suits you.</p>
  <p>Best regards,<br/>HR Team</p>
</div>
""".strip()


def already_invited_after(session, candidate_id: int, since_dt: datetime) -> bool:
    """
    Returns True if we have already sent a REQUEST_TIME_CONFIRMATION after `since_dt`
    for this candidate — used to avoid duplicate emails.
    """
    ev = (
        session.query(ConversationEvent)
        .filter(ConversationEvent.candidate_id == candidate_id)
        .filter(ConversationEvent.event_type == "REQUEST_TIME_CONFIRMATION")
        .filter(ConversationEvent.created_at >= since_dt)
        .order_by(ConversationEvent.created_at.desc())
        .first()
    )
    return ev is not None


def send_invite_for_candidate(candidate_id: int, thread_id: Optional[str] = None) -> dict:
    """
    Sends one email to the applicant listing all current manager-proposed InterviewSlots (status='proposed').
    Creates Message + ConversationEvent and updates CandidateStatus.
    Avoids duplicates if an invite was already sent after the latest proposed slot was created.

    Args:
        candidate_id: Candidate.id
        thread_id: optional Gmail thread to keep continuity (pass from a related message if you have it)

    Returns:
        dict: {"ok": True, "message_id": int, "slot_ids": [..]} on success
    """
    db = SessionLocal()
    try:
        cand = db.query(Candidate).filter_by(id=candidate_id).first()
        if not cand:
            return {"ok": False, "reason": f"Candidate {candidate_id} not found"}
        mgr = db.query(HiringManager).filter_by(id=cand.manager_id).first()
        if not mgr:
            return {"ok": False, "reason": f"No manager linked to candidate {candidate_id}"}

        # Gather manager-proposed slots that are still pending
        slots = (
            db.query(InterviewSlot)
            .filter(InterviewSlot.candidate_id == cand.id)
            .filter(InterviewSlot.proposed_by == "manager")
            .filter(InterviewSlot.status == "proposed")
            .order_by(InterviewSlot.created_at.asc())
            .all()
        )
        if not slots:
            return {"ok": False, "reason": "No manager-proposed slots found (status='proposed')"}

        latest_slot_time = max(s.created_at for s in slots if s.created_at) or datetime.now(timezone.utc)

        # Avoid duplicate invites: if we've already invited the applicant AFTER latest proposed slot, skip
        if already_invited_after(db, cand.id, latest_slot_time):
            return {"ok": False, "reason": "Invite already sent after the latest proposed slot."}

        html_body = _compose_html(cand, mgr, slots)

        # Send email
        resp = send_email_html(
            to_email=cand.email,
            subject=f"Confirm interview time – {cand.position or 'Role'}",
            html_body=html_body,
            thread_id=thread_id,
        )
        out_id = resp.get("id") if isinstance(resp, dict) else None

        # Log outbound message (IMPORTANT: sender_email must not be NULL)
        out_msg = Message(
            gmail_message_id=out_id or f"local-{datetime.now().timestamp()}",
            gmail_thread_id=thread_id,
            candidate_id=cand.id,
            manager_id=mgr.id,
            direction="outbound",
            sender_email=HR_EMAIL,  # <- fixes NOT NULL constraint
            subject=f"Confirm interview time – {cand.position or 'Role'}",
            body=html_body,
            received_at=datetime.now(timezone.utc),
            intent="REQUEST_TIME_CONFIRMATION",
            meta_json={"interview_slot_ids": [s.id for s in slots]},
        )
        db.add(out_msg)
        db.flush()

        # Event
        db.add(
            ConversationEvent(
                candidate_id=cand.id,
                event_type="REQUEST_TIME_CONFIRMATION",
                event_data={"interview_slot_ids": [s.id for s in slots]},
                source_message_id=out_msg.id,
            )
        )

        # Snapshot (cache)
        status = db.query(CandidateStatus).filter_by(candidate_id=cand.id).first()
        if not status:
            status = CandidateStatus(candidate_id=cand.id)
            db.add(status)
        status.current_status = "Awaiting Candidate Confirmation"
        db.commit()

        return {"ok": True, "message_id": out_msg.id, "slot_ids": [s.id for s in slots]}

    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def send_invites_for_all_candidates() -> dict:
    """
    Batch mode:
    For every candidate with at least one manager-proposed slot (status='proposed'),
    send a single invite (if not already sent after the latest proposal).
    """
    db = SessionLocal()
    try:
        cand_ids = [
            cid for (cid,) in db.query(InterviewSlot.candidate_id)
            .filter(InterviewSlot.proposed_by == "manager")
            .filter(InterviewSlot.status == "proposed")
            .distinct()
            .all()
        ]
        sent, skipped, errors = 0, 0, 0
        for cid in cand_ids:
            res = send_invite_for_candidate(cid)
            if res.get("ok"):
                sent += 1
            else:
                reason = res.get("reason") or res.get("error") or ""
                if reason:
                    skipped += 1
                else:
                    errors += 1
        return {"ok": True, "sent": sent, "skipped": skipped, "errors": errors}
    finally:
        db.close()

