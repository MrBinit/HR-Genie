# mail/manager_reply_ingest.py
import base64
import html
import logging
import re
import os
from datetime import datetime, timezone
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
from mail.mail_sender import send_email_html
from mail.mail_receiver import get_emails_from_sender, mark_read
from services.intent_parser_llm import parse_intent_llm
from services.google_calendar_service import create_event_with_meet
load_dotenv(override=True)


HR_EMAIL = os.getenv("SENDER_EMAIL")
if not HR_EMAIL:
    logging.warning("SENDER_EMAIL not set; outbound Message.sender_email will use None.")

# Nepal Time
NPT = ZoneInfo("Asia/Kathmandu")

# quick confirm detector (manager replies like "yes, I agree", "works for me", etc.)
_QUICK_CONFIRM = re.compile(
    r"\b(i\s*agree|agree|works\s*for\s*me|sounds\s*good|ok(?:ay)?|confirmed|let'?s\s+go\s+with\s+that)\b",
    re.IGNORECASE,
)


def _fmt_local(dt: datetime) -> str:
    """
    Render a datetime in Nepal time. If naive, treat as UTC first, then convert.
    Example: Tuesday, 16 August 2025 at 03:00 PM NPT
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NPT).strftime("%A, %d %B %Y at %I:%M %p NPT")


# Gmail helpers
def _decode_gmail_body(raw_msg: dict) -> str:
    """Prefer text/plain; fallback to text/html; fallback to top-level body."""
    payload = raw_msg.get("payload", {}) or {}
    parts = payload.get("parts") or []

    def _find_part(mtype: str) -> Optional[str]:
        for p in parts:
            if p.get("mimeType") == mtype and p.get("body", {}).get("data"):
                return p["body"]["data"]
        return None

    data = _find_part("text/plain") or _find_part("text/html") or payload.get("body", {}).get("data")
    if not data:
        return ""

    try:
        text = base64.urlsafe_b64decode(data).decode(errors="ignore")
    except Exception:
        return ""

    # If HTML, strip tags
    if "<html" in text.lower() or "<body" in text.lower():
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    return text.strip()


def _headers_dict(raw_msg: dict) -> Dict[str, str]:
    payload = raw_msg.get("payload", {}) or {}
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


# Copy / templates
def _compose_availability_followup(cand: Candidate, mgr: HiringManager) -> str:
    return f"""
<div style="font-family:Arial,sans-serif;line-height:1.5">
  <p>Hi {mgr.name or 'there'},</p>
  <p>Thanks for confirming you’d like to proceed with <b>{cand.name or 'the candidate'}</b>.</p>
  <p>Could you please share a few interview time options <b>(Nepal time)</b>?
     We’ll schedule right away.</p>
  <p>Regards,<br/>HR Team</p>
</div>
""".strip()


# DB helpers
def _resolve_candidate_for_manager(session, manager_id: str) -> Optional[Candidate]:
    """
    Heuristic: pick the most recent candidate under this manager in a sensible stage.
    """
    return (
        session.query(Candidate)
        .filter(Candidate.manager_id == manager_id)
        .filter(Candidate.status.in_(["Forwarded to Manager", "Received"]))
        .order_by(Candidate.uploaded_at.desc())
        .first()
    )


def _parse_iso_flexible(value: Optional[str]) -> Optional[datetime]:
    """
    Accepts 'YYYY-MM-DDTHH:MM' / 'YYYY-MM-DDTHH:MM:SS' / supports trailing 'Z'.
    Returns timezone-aware UTC datetime (naive treated as UTC).
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


def _ensure_aware(dt: datetime) -> datetime:
    """Ensure tz-aware in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _within_tolerance(a: datetime, b: datetime, minutes: int = 5) -> bool:
    a = _ensure_aware(a)
    b = _ensure_aware(b)
    return abs((a - b).total_seconds()) <= minutes * 60


def _latest_open_applicant_slots(session, candidate_id: int, limit: int = 10) -> List[InterviewSlot]:
    """
    Return applicant-proposed slots still in 'proposed' status (i.e., not accepted/declined).
    Newest first.
    """
    return (
        session.query(InterviewSlot)
        .filter(
            InterviewSlot.candidate_id == candidate_id,
            InterviewSlot.proposed_by == "applicant",
            InterviewSlot.status == "proposed",
        )
        .order_by(InterviewSlot.created_at.desc())
        .limit(limit)
        .all()
    )


# Email to applicant (times rendered in NPT)
def _email_applicant_request_times(
    session,
    cand: Candidate,
    mgr: HiringManager,
    slots: List[dict],
    thread_id: Optional[str],
):
    """
    Sends a NPT-friendly email to the applicant listing proposed time(s),
    logs outbound Message + ConversationEvent, and updates CandidateStatus.
    """
    items = []
    for s in slots:
        st = _parse_iso_flexible(s.get("start"))
        en = _parse_iso_flexible(s.get("end")) if s.get("end") else None
        if not st:
            continue
        if en and en <= st:
            continue
        if en:
            items.append(f"• {_fmt_local(st)} — {_fmt_local(en)}")
        else:
            items.append(f"• {_fmt_local(st)}")

    choices_html = "<br/>".join(items) if items else "• (time to be confirmed)"

    html_body = f"""
<div style="font-family: Arial, sans-serif; line-height: 1.6; font-size: 15px; color: #333;">
  <p>Hi <b>{cand.name or 'there'}</b>,</p>
  <p><b>{'The hiring manager'}</b> has suggested the following time(s) for your interview for the <b>{cand.position or 'role'}</b> (Nepal time):</p>
  <p style="margin-left: 10px;">{choices_html}</p>
  <p>Please reply to let us know which option works best for you. If none of these fit, you can suggest another time that’s convenient for you.</p>
  <p>Best regards,<br/>HR Team</p>
</div>
""".strip()

    # Email the applicant (same thread if available)
    resp = send_email_html(
        to_email=cand.email,
        subject=f"Please confirm your interview time – {cand.position or 'Role'}",
        html_body=html_body,
        thread_id=thread_id,
    )
    out_id = resp.get("id") if isinstance(resp, dict) else None

    # Log outbound message (sender_email should be set if HR_EMAIL is available)
    out_msg = Message(
        gmail_message_id=out_id or f"local-{datetime.now().timestamp()}",
        gmail_thread_id=thread_id,
        candidate_id=cand.id,
        manager_id=mgr.id,
        direction="outbound",
        sender_email=HR_EMAIL,
        subject=f"Please confirm your interview time – {cand.position or 'Role'}",
        body=html_body,
        received_at=datetime.now(timezone.utc),
        intent="REQUEST_TIME_CONFIRMATION",
        meta_json={"interview_slots": slots},
    )
    session.add(out_msg)
    session.flush()

    session.add(
        ConversationEvent(
            candidate_id=cand.id,
            event_type="REQUEST_TIME_CONFIRMATION",
            event_data={"interview_slots": slots},
            source_message_id=out_msg.id,
        )
    )

    status = session.query(CandidateStatus).filter_by(candidate_id=cand.id).first()
    if not status:
        status = CandidateStatus(candidate_id=cand.id)
        session.add(status)
    status.current_status = "Awaiting Candidate Confirmation"
    session.commit()


def _email_manager_confirmed(
    cand: Candidate,
    mgr: HiringManager,
    start_dt: datetime,
    end_dt: Optional[datetime],
    thread_id: Optional[str],
):
    when_npt = _fmt_local(start_dt) + (f" — {_fmt_local(end_dt)}" if end_dt else "")
    html_body = f"""
<div style="font-family:Arial,sans-serif;line-height:1.6;font-size:15px;color:#222;">
  <p>Hi <b>{mgr.name or 'there'}</b>,</p>
  <p>Interview with <b>{cand.name}</b> for <b>{cand.position or 'the role'}</b> is <b>confirmed</b>.</p>
  <p><b>Final time (Nepal time):</b><br/>{when_npt}</p>
  <p>Best regards,<br/>HR Team</p>
</div>
""".strip()
    send_email_html(
        to_email=mgr.email,
        subject=f"Interview confirmed – {cand.name}",
        html_body=html_body,
        thread_id=thread_id,
    )


def _email_applicant_confirmed(
    cand: Candidate,
    start_dt: datetime,
    end_dt: Optional[datetime],
    thread_id: Optional[str],
):
    when_npt = _fmt_local(start_dt) + (f" — {_fmt_local(end_dt)}" if end_dt else "")
    html_body = f"""
<div style="font-family:Arial,sans-serif;line-height:1.6;font-size:15px;color:#222;">
  <p>Hi <b>{cand.name}</b>,</p>
  <p>The hiring manager has <b>confirmed</b> your interview for <b>{cand.position or 'the role'}</b>.</p>
  <p><b>Final time (Nepal time):</b><br/>{when_npt}</p>
  <p>You’ll receive a calendar invite shortly.</p>
  <p>Best regards,<br/>HR Team</p>
</div>
""".strip()
    send_email_html(
        to_email=cand.email,
        subject=f"Your interview is confirmed – {cand.position or 'the role'}",
        html_body=html_body,
        thread_id=thread_id,
    )


def ingest_manager_replies(limit: int = 25, unread_only: bool = True) -> Dict:
    """
    For each manager in DB:
      - fetch their unread emails,
      - save inbound message,
      - LLM-parse to intent/meta (default tz Asia/Kathmandu),
      - create ConversationEvent,
      - create InterviewSlot when time(s) present,
      - email applicant immediately to confirm/counter (NPT rendering),
      - update CandidateStatus (cache),
      - mark as read.
    """
    session = SessionLocal()
    try:
        managers: List[HiringManager] = session.query(HiringManager).all()
        if not managers:
            logging.info("[ingest] No managers found.")
            return {"ok": True, "processed": 0, "skipped": 0, "errors": 0}

        processed = skipped = errors = 0

        for mgr in managers:
            if not mgr.email:
                continue

            try:
                emails = get_emails_from_sender(
                    manager_email=mgr.email,
                    limit=limit,
                    include_unread_only=unread_only,
                )
            except Exception as ex:
                logging.exception(f"[ingest] Fetch failed for {mgr.email}: {ex}")
                errors += 1
                continue

            for e in emails:
                try:
                    cand = _resolve_candidate_for_manager(session, mgr.id)
                    if not cand:
                        skipped += 1
                        if unread_only:
                            try:
                                mark_read(e["id"])
                            except Exception:
                                pass
                        continue

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

                    session.add(
                        ConversationEvent(
                            candidate_id=cand.id,
                            event_type=intent,
                            event_data=meta or {},
                            source_message_id=msg.id,
                        )
                    )

                    status = session.query(CandidateStatus).filter_by(candidate_id=cand.id).first()
                    if not status:
                        status = CandidateStatus(candidate_id=cand.id)
                        session.add(status)

                    # === Manager agrees to applicant's proposed time ===
                    is_quick_agree = bool(_QUICK_CONFIRM.search(e.get("body") or ""))
                    is_llm_confirm = str(intent or "").upper() in {
                        "CONFIRM", "CONFIRMED", "AGREE", "AGREED", "ACCEPT", "ACCEPTED"
                    }

                    if is_quick_agree or is_llm_confirm:
                        applicant_slots = _latest_open_applicant_slots(session, cand.id, limit=5)

                        target_start = _parse_iso_flexible((meta or {}).get("meeting_iso")) if meta else None
                        target_end = None
                        if not target_start and isinstance((meta or {}).get("proposed_slots"), list):
                            for s in meta["proposed_slots"]:
                                if s.get("start"):
                                    target_start = _parse_iso_flexible(s["start"])
                                    target_end = _parse_iso_flexible(s.get("end")) if s.get("end") else None
                                    break

                        match_slot = None
                        if target_start:
                            for s in applicant_slots:
                                if _within_tolerance(s.start_time, target_start, minutes=5):
                                    match_slot = s
                                    if target_end and not s.end_time:
                                        s.end_time = target_end
                                    break

                        if not match_slot and applicant_slots:
                            match_slot = applicant_slots[0]

                        if match_slot:
                            match_slot.status = "accepted"
                            status.current_status = "Interview Confirmed"
                            status.final_meeting_time = _ensure_aware(match_slot.start_time)

                            session.add(
                                ConversationEvent(
                                    candidate_id=cand.id,
                                    event_type="MANAGER_ACCEPTED",
                                    event_data={
                                        "slot_id": match_slot.id,
                                        "start": match_slot.start_time.isoformat(),
                                        "end": match_slot.end_time.isoformat() if match_slot.end_time else None,
                                    },
                                    source_message_id=msg.id,
                                )
                            )
                            session.commit()

                            # === Create Google Calendar Event + Meet Link ===
                            from google_calendar_service import create_event_with_meet
                            from datetime import timedelta

                            calendar_result = create_event_with_meet(
                                summary=f"Interview: {cand.name} – {cand.position}",
                                description="Interview between candidate and hiring manager",
                                start_dt=match_slot.start_time,
                                end_dt=match_slot.end_time or (match_slot.start_time + timedelta(hours=1)),
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

                            _email_manager_confirmed(cand, mgr, match_slot.start_time, match_slot.end_time, thread_id=msg.gmail_thread_id)
                            _email_applicant_confirmed(cand, match_slot.start_time, match_slot.end_time, thread_id=msg.gmail_thread_id)

                            if unread_only:
                                try:
                                    mark_read(e["id"])
                                except Exception:
                                    pass

                            processed += 1
                            continue  # done with this email

                    # === Handle MEETING_SCHEDULED intent ===
                    if intent == "MEETING_SCHEDULED":
                        slots_meta: List[dict] = []
                        if meta:
                            if meta.get("meeting_iso"):
                                slots_meta.append({"start": meta["meeting_iso"], "end": None})
                            if isinstance(meta.get("proposed_slots"), list):
                                for s in meta["proposed_slots"]:
                                    if isinstance(s, dict) and s.get("start"):
                                        slots_meta.append({"start": s["start"], "end": s.get("end")})

                        created_any = False
                        for s in slots_meta:
                            st = _parse_iso_flexible(s.get("start"))
                            en = _parse_iso_flexible(s.get("end")) if s.get("end") else None
                            if not st or (en and en <= st):
                                continue
                            session.add(
                                InterviewSlot(
                                    candidate_id=cand.id,
                                    proposed_by="manager",
                                    start_time=st,
                                    end_time=en,
                                    status="proposed",
                                    source_message_id=msg.id,
                                )
                            )
                            created_any = True

                        status.current_status = "Awaiting Candidate Confirmation"
                        session.commit()

                        if created_any:
                            _email_applicant_request_times(
                                session,
                                cand,
                                mgr,
                                slots_meta,
                                thread_id=msg.gmail_thread_id,
                            )

                        if unread_only:
                            try:
                                mark_read(e["id"])
                            except Exception:
                                pass
                        processed += 1
                        continue

                    elif intent == "SALARY_DISCUSSION" and meta and meta.get("salary_amount"):
                        status.current_status = "Salary Discussed"

                    elif intent == "REJECTION":
                        status.current_status = "Rejected by Manager"

                    elif intent == "PROCEED":
                        status.current_status = "Manager Approved"

                        # Ask manager for times if none provided
                        if not (meta and (meta.get("meeting_iso") or meta.get("proposed_slots"))):
                            html_body = _compose_availability_followup(cand, mgr)
                            try:
                                resp = send_email_html(
                                    to_email=mgr.email,
                                    subject=f"Re: {e.get('subject') or 'Interview Scheduling'}",
                                    html_body=html_body,
                                    thread_id=e.get("threadId"),
                                )
                                out_id = resp.get("id") if isinstance(resp, dict) else None
                            except Exception as send_ex:
                                logging.exception(f"[ingest] Failed to send availability follow-up to {mgr.email}: {send_ex}")
                                out_id = None

                            out_msg = Message(
                                gmail_message_id=out_id or f"local-{datetime.now().timestamp()}",
                                gmail_thread_id=e.get("threadId"),
                                candidate_id=cand.id,
                                manager_id=mgr.id,
                                direction="outbound",
                                sender_email=HR_EMAIL,
                                subject=f"Re: {e.get('subject') or 'Interview Scheduling'}",
                                body=html_body,
                                received_at=datetime.now(timezone.utc),
                                intent="ASKED_FOR_AVAILABILITY",
                                meta_json={"reason": "PROCEED_without_time"},
                            )
                            session.add(out_msg)
                            session.flush()
                            session.add(
                                ConversationEvent(
                                    candidate_id=cand.id,
                                    event_type="ASKED_FOR_AVAILABILITY",
                                    event_data={"reason": "PROCEED_without_time"},
                                    source_message_id=out_msg.id,
                                )
                            )
                            status.current_status = "Awaiting Manager Availability"
                            session.commit()

                    if unread_only:
                        try:
                            mark_read(e["id"])
                        except Exception:
                            pass

                    processed += 1

                except Exception as ex:
                    logging.exception(f"[ingest] failed for email {e.get('id')}: {ex}")
                    errors += 1
                    if unread_only and e.get("id"):
                        try:
                            mark_read(e["id"])
                        except Exception:
                            pass

        return {"ok": True, "processed": processed, "skipped": skipped, "errors": errors}
    finally:
        session.close()
