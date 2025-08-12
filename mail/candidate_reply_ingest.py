import logging
import re
import os
from datetime import datetime, timezone,  timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from database.db import SessionLocal
from database.models import (
    Candidate,
    HiringManager,
    Message,
    ConversationEvent,
    CandidateStatus,
    InterviewSlot,
)
from mail.mail_receiver import get_emails_from_sender, mark_read
from mail.mail_sender import send_email_html
from services.intent_parser_llm import parse_intent_llm
from services.google_calendar_service import create_event_with_meet
from services.google_calendar_service import create_event_with_meet

load_dotenv(override=True)
HR_EMAIL = os.getenv("SENDER_EMAIL")
NPT = ZoneInfo("Asia/Kathmandu")


#  Time helpers
def _ensure_aware(dt: datetime) -> datetime:
    """Ensure tz-aware in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_flexible(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO string to tz-aware UTC; naive treated as UTC."""
    if not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1]
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        return None
    return _ensure_aware(dt)


def _fmt_npt(dt: datetime) -> str:
    """Render datetime in Nepal time."""
    dt = _ensure_aware(dt)
    return dt.astimezone(NPT).strftime("%A, %d %B %Y at %I:%M %p NPT")


def _within_tolerance(a: datetime, b: datetime, minutes: int = 5) -> bool:
    a = _ensure_aware(a)
    b = _ensure_aware(b)
    return abs((a - b).total_seconds()) <= minutes * 60


#DB helpers
def _resolve_manager_for_candidate(session, candidate_id: int) -> Optional[HiringManager]:
    cand = session.query(Candidate).filter_by(id=candidate_id).first()
    if not cand or not cand.manager_id:
        return None
    return session.query(HiringManager).filter_by(id=cand.manager_id).first()


def _latest_open_manager_slots(session, candidate_id: int, limit: int = 10) -> List[InterviewSlot]:
    """
    Return manager-proposed slots still in 'proposed' status (i.e., not accepted/declined).
    Newest first.
    """
    return (
        session.query(InterviewSlot)
        .filter(
            InterviewSlot.candidate_id == candidate_id,
            InterviewSlot.proposed_by == "manager",
            InterviewSlot.status == "proposed",
        )
        .order_by(InterviewSlot.created_at.desc())
        .limit(limit)
        .all()
    )


def _find_matching_manager_slot(
    manager_slots: List[InterviewSlot],
    cand_start: datetime,
    cand_end: Optional[datetime],
    tolerance_minutes: int = 5,
) -> Optional[InterviewSlot]:
    """
    A 'match' means:
      - start times are within tolerance, and
      - if both ends present, ends are within tolerance as well
        (if manager slot has no end, ignore end comparison).
    """
    cand_start = _ensure_aware(cand_start)
    cand_end = _ensure_aware(cand_end) if cand_end else None

    for s in manager_slots:
        s_start = _ensure_aware(s.start_time)
        s_end = _ensure_aware(s.end_time) if s.end_time else None

        if _within_tolerance(s_start, cand_start, tolerance_minutes):
            if s_end and cand_end:
                if _within_tolerance(s_end, cand_end, tolerance_minutes):
                    return s
            else:
                return s
    return None


#  Email composers (NPT in emails)
def _email_manager_agreed(
    cand: Candidate,
    mgr: HiringManager,
    start_dt: datetime,
    end_dt: Optional[datetime],
    thread_id: Optional[str],
):
    when_npt = _fmt_npt(start_dt) + (f" — {_fmt_npt(end_dt)}" if end_dt else "")
    html_body = f"""
<div style="font-family:Arial,sans-serif;line-height:1.6;font-size:15px;color:#222;">
  <p>Hi <b>{mgr.name or 'there'}</b>,</p>
  <p><b>{cand.name}</b> has <b>agreed</b> to the interview time for <b>{cand.position or 'the role'}</b>.</p>
  <p><b>Confirmed time (Nepal time):</b><br/>{when_npt}</p>
  <p>We’ll mark this as confirmed.</p>
  <p>Best regards,<br/>HR Team</p>
</div>
""".strip()

    resp = send_email_html(
        to_email=mgr.email,
        subject=f"Interview confirmed – {cand.name}",
        html_body=html_body,
        thread_id=thread_id,
    )
    return resp.get("id") if isinstance(resp, dict) else None


def _email_manager_new_proposal(
    cand: Candidate,
    mgr: HiringManager,
    slots: List[dict],
    thread_id: Optional[str],
):
    if not slots:
        slot_html = "(no clear time detected)"
    else:
        parts = []
        for s in slots:
            st = _parse_iso_flexible(s.get("start"))
            en = _parse_iso_flexible(s.get("end")) if s.get("end") else None
            if st:
                if en:
                    parts.append(f"• {_fmt_npt(st)} — {_fmt_npt(en)}")
                else:
                    parts.append(f"• {_fmt_npt(st)}")
        slot_html = "<br/>".join(parts) if parts else "(no clear time detected)"

    html_body = f"""
<div style="font-family:Arial,sans-serif;line-height:1.6;font-size:15px;color:#222;">
  <p>Hi <b>{mgr.name or 'there'}</b>,</p>
  <p><b>{cand.name}</b> proposed a <b>different interview time</b> for <b>{cand.position or 'the role'}</b>:</p>
  <p>{slot_html}</p>
  <p>Please reply with your availability for one of these options.</p>
  <p>Best regards,<br/>HR Team</p>
</div>
""".strip()

    resp = send_email_html(
        to_email=mgr.email,
        subject=f"Candidate proposed new time – {cand.name}",
        html_body=html_body,
        thread_id=thread_id,
    )
    return resp.get("id") if isinstance(resp, dict) else None


# Core ingest
def ingest_candidate_replies(limit: int = 25, unread_only: bool = True) -> Dict:
    """
    Polls inbox for emails FROM each candidate email.
    Uses LLM to parse intent and times (default tz Asia/Kathmandu).
    - If candidate accepts a time that matches a manager slot -> mark accepted, update status.final_meeting_time, email manager (agreed) + create Google Meet link.
    - If candidate proposes different time(s) -> create InterviewSlot(proposed_by='applicant'), status='proposed', email manager (confirm?).
    """
    session = SessionLocal()
    try:
        candidates: List[Candidate] = session.query(Candidate).all()
        if not candidates:
            logging.info("[candidate_ingest] No candidates found.")
            return {"ok": True, "processed": 0, "skipped": 0, "errors": 0}

        processed = skipped = errors = 0

        for cand in candidates:
            if not cand.email:
                continue

            try:
                emails = get_emails_from_sender(
                    manager_email=cand.email,
                    limit=limit,
                    include_unread_only=unread_only,
                )
            except Exception as ex:
                logging.exception(f"[candidate_ingest] Failed to fetch emails for {cand.email}: {ex}")
                errors += 1
                continue

            mgr = _resolve_manager_for_candidate(session, cand.id)
            if not mgr:
                skipped += len(emails)
                continue

            open_mgr_slots = _latest_open_manager_slots(session, cand.id)

            for e in emails:
                try:
                    raw_from = (e.get("from") or "").strip()
                    em_match = re.search(r"<([^>]+)>", raw_from)
                    from_email = (em_match.group(1) if em_match else raw_from).lower()

                    msg = Message(
                        gmail_message_id=e["id"],
                        gmail_thread_id=e["threadId"],
                        candidate_id=cand.id,
                        manager_id=mgr.id,
                        direction="inbound",
                        sender_email=from_email,
                        subject=e.get("subject") or "",
                        body=e.get("body") or "",
                        received_at=datetime.now(timezone.utc),
                    )
                    session.add(msg)
                    session.flush()

                    intent, meta = parse_intent_llm(
                        e.get("body") or "",
                        subject=e.get("subject") or "",
                        default_tz="Asia/Kathmandu",
                    )
                    msg.intent = intent
                    msg.meta_json = meta or None
                    session.flush()

                    status = session.query(CandidateStatus).filter_by(candidate_id=cand.id).first()
                    if not status:
                        status = CandidateStatus(candidate_id=cand.id)
                        session.add(status)

                    accepted_slot: Optional[InterviewSlot] = None
                    created_applicant_slots: List[InterviewSlot] = []

                    candidate_slots: List[dict] = []
                    if meta:
                        if meta.get("meeting_iso"):
                            candidate_slots.append({"start": meta["meeting_iso"], "end": None})
                        if isinstance(meta.get("proposed_slots"), list):
                            for s in meta["proposed_slots"]:
                                if isinstance(s, dict) and s.get("start"):
                                    candidate_slots.append({"start": s["start"], "end": s.get("end")})

                    for s in candidate_slots:
                        st = _parse_iso_flexible(s.get("start"))
                        en = _parse_iso_flexible(s.get("end")) if s.get("end") else None
                        if not st:
                            continue
                        match = _find_matching_manager_slot(open_mgr_slots, st, en)
                        if match:
                            accepted_slot = match
                            if en and not match.end_time:
                                match.end_time = en
                            match.status = "accepted"
                            status.current_status = "Interview Confirmed"
                            status.final_meeting_time = match.start_time
                            break

                    if accepted_slot:
                        session.add(ConversationEvent(
                            candidate_id=cand.id,
                            event_type="CANDIDATE_ACCEPTED",
                            event_data={
                                "slot_id": accepted_slot.id,
                                "start": accepted_slot.start_time.isoformat(),
                                "end": accepted_slot.end_time.isoformat() if accepted_slot.end_time else None
                            },
                            source_message_id=msg.id,
                        ))
                        session.commit()

                        # === Create Google Calendar Event with Meet link ===
                        calendar_result = create_event_with_meet(
                            summary=f"Interview: {cand.name} – {cand.position}",
                            description="Interview between candidate and hiring manager",
                            start_dt=accepted_slot.start_time,
                            end_dt=accepted_slot.end_time or (accepted_slot.start_time + timedelta(hours=1)),
                            attendees=[cand.email, mgr.email, HR_EMAIL]
                        )

                        if calendar_result:
                            status.notes = f"Google Calendar Event ID: {calendar_result['event_id']}"
                            session.commit()

                            meet_link = calendar_result["hangoutLink"]
                            send_email_html(
                                to_email=cand.email,
                                subject=f"Interview scheduled – {cand.position}",
                                html_body=f"Your interview is confirmed.<br/>Meet link: <a href='{meet_link}'>{meet_link}</a>",
                            )
                            send_email_html(
                                to_email=mgr.email,
                                subject=f"Interview scheduled with {cand.name}",
                                html_body=f"The interview is confirmed.<br/>Meet link: <a href='{meet_link}'>{meet_link}</a>",
                            )

                        _email_manager_agreed(
                            cand,
                            mgr,
                            accepted_slot.start_time,
                            accepted_slot.end_time,
                            thread_id=msg.gmail_thread_id,
                        )

                    else:
                        for s in candidate_slots:
                            st = _parse_iso_flexible(s.get("start"))
                            en = _parse_iso_flexible(s.get("end")) if s.get("end") else None
                            if not st:
                                continue
                            new_slot = InterviewSlot(
                                candidate_id=cand.id,
                                proposed_by="applicant",
                                start_time=st,
                                end_time=en,
                                status="proposed",
                                source_message_id=msg.id,
                            )
                            session.add(new_slot)
                            session.flush()
                            created_applicant_slots.append(new_slot)

                        if created_applicant_slots:
                            status.current_status = "Awaiting Manager Confirmation"
                            session.add(ConversationEvent(
                                candidate_id=cand.id,
                                event_type="CANDIDATE_PROPOSED",
                                event_data={
                                    "proposed_slots": [
                                        {
                                            "start": s.start_time.isoformat(),
                                            "end": s.end_time.isoformat() if s.end_time else None
                                        }
                                        for s in created_applicant_slots
                                    ]
                                },
                                source_message_id=msg.id,
                            ))
                            session.commit()

                            email_slots = [
                                {"start": s.start_time.isoformat(), "end": s.end_time.isoformat() if s.end_time else None}
                                for s in created_applicant_slots
                            ]
                            _email_manager_new_proposal(
                                cand,
                                mgr,
                                email_slots,
                                thread_id=msg.gmail_thread_id,
                            )
                        else:
                            session.add(ConversationEvent(
                                candidate_id=cand.id,
                                event_type="CANDIDATE_REPLIED_NO_TIME",
                                event_data={"note": "LLM could not extract a time"},
                                source_message_id=msg.id,
                            ))
                            session.commit()

                            fallback_html = f"""
<div style="font-family:Arial,sans-serif;line-height:1.6;font-size:15px;color:#222;">
  <p>Hi <b>{mgr.name or 'there'}</b>,</p>
  <p><b>{cand.name}</b> replied regarding the interview for <b>{cand.position or 'the role'}</b>, but no clear time could be parsed.</p>
  <p><b>Candidate message:</b></p>
  <blockquote style="border-left:3px solid #ddd;padding-left:10px;color:#555;">{(e.get('body') or '').strip()[:1500]}</blockquote>
  <p>Could you please follow up as needed?</p>
  <p>Best regards,<br/>HR Team</p>
</div>
""".strip()
                            send_email_html(
                                to_email=mgr.email,
                                subject=f"Candidate replied (no clear time) – {cand.name}",
                                html_body=fallback_html,
                                thread_id=msg.gmail_thread_id,
                            )

                    if unread_only:
                        try:
                            mark_read(e["id"])
                        except Exception:
                            pass

                    processed += 1

                except Exception as ex:
                    logging.exception(f"[candidate_ingest] failed for email {e.get('id')}: {ex}")
                    errors += 1
                    if unread_only and e.get("id"):
                        try:
                            mark_read(e["id"])
                        except Exception:
                            pass

        return {"ok": True, "processed": processed, "skipped": skipped, "errors": errors}

    finally:
        session.close()
