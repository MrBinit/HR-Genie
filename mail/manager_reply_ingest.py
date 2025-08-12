# mail/manager_reply_ingest.py
import base64
import html
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

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
import os
from dotenv import load_dotenv

load_dotenv(override=True)
HR_EMAIL = os.getenv("SENDER_EMAIL")


# ---------- Helpers ----------
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

    # If HTML, strip tags (LLM can handle either, but we keep it clean)
    if "<html" in text.lower() or "<body" in text.lower():
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    return text.strip()


def _headers_dict(raw_msg: dict) -> Dict[str, str]:
    payload = raw_msg.get("payload", {}) or {}
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _compose_availability_followup(cand: Candidate, mgr: HiringManager) -> str:
    return f"""
<div style="font-family:Arial,sans-serif;line-height:1.5">
  <p>Hi {mgr.name or 'there'},</p>
  <p>Thanks for confirming you’d like to proceed with <b>{cand.name or 'the candidate'}</b>.</p>
  <p>Could you please share a few interview time options (date &amp; time, with timezone)?
     We’ll schedule right away.</p>
  <p>Regards,<br/>HR Team</p>
</div>
""".strip()


def _resolve_candidate_for_manager(session, manager_id: str) -> Optional[Candidate]:
    """
    Heuristic: most recent candidate under this manager in a stage where replies make sense.
    Improve later by tracking Gmail threadId on Candidate.
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


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _email_applicant_request_times(
    session,
    cand: Candidate,
    mgr: HiringManager,
    slots: List[dict],
    thread_id: Optional[str],
):
    """
    Sends an email to the applicant listing the proposed time(s),
    logs outbound Message + ConversationEvent, and updates CandidateStatus.
    """
    # Build HTML list of proposed times (UTC)
    items = []
    for s in slots:
        st = _parse_iso_flexible(s.get("start"))
        en = _parse_iso_flexible(s.get("end")) if s.get("end") else None
        if not st:
            continue
        items.append(f"• {_fmt_utc(st)}" + (f" — {_fmt_utc(en)}" if en else ""))

    choices_html = "<br/>".join(items) if items else "• (time to be confirmed)"
    html_body = f"""
<div style="font-family:Arial,sans-serif;line-height:1.5">
  <p>Hi {cand.name or 'there'},</p>
  <p>{mgr.name or 'The hiring manager'} has proposed interview time(s) for <b>{cand.position or 'the role'}</b>.</p>
  <p><b>Suggested times (UTC):</b><br/>{choices_html}</p>
  <p>Please reply and let us know which time works for you. If none fit, please propose another time that suits you.</p>
  <p>Best regards,<br/>HR Team</p>
</div>
""".strip()

    # Email the applicant (same thread if available)
    resp = send_email_html(
        to_email=cand.email,
        subject=f"Confirm interview time – {cand.position or 'Role'}",
        html_body=html_body,
        thread_id=thread_id,
    )
    out_id = resp.get("id") if isinstance(resp, dict) else None

    # Log outbound message (sender_email must NOT be NULL)
    out_msg = Message(
        gmail_message_id=out_id or f"local-{datetime.now().timestamp()}",
        gmail_thread_id=thread_id,
        candidate_id=cand.id,
        manager_id=mgr.id,
        direction="outbound",
        sender_email=HR_EMAIL,
        subject=f"Confirm interview time – {cand.position or 'Role'}",
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

    # Snapshot: waiting on the applicant (do NOT set final_meeting_time yet)
    status = session.query(CandidateStatus).filter_by(candidate_id=cand.id).first()
    if not status:
        status = CandidateStatus(candidate_id=cand.id)
        session.add(status)
    status.current_status = "Awaiting Candidate Confirmation"
    session.commit()


# ---------- Core ingest ----------
def ingest_manager_replies(limit: int = 25, unread_only: bool = True) -> Dict:
    """
    For each manager in DB:
      - fetch their unread emails,
      - save inbound message,
      - LLM-parse to intent/meta,
      - create ConversationEvent,
      - create InterviewSlot when time(s) present,
      - email applicant immediately to confirm/counter,
      - update CandidateStatus (cache),
      - mark as read.
    """
    session = SessionLocal()
    try:
        managers: List[HiringManager] = session.query(HiringManager).all()
        if not managers:
            logging.info("[ingest] No managers found in DB; nothing to ingest.")
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
                logging.exception(f"[ingest] Failed to fetch emails for manager {mgr.email}: {ex}")
                errors += 1
                continue

            for e in emails:
                try:
                    cand = _resolve_candidate_for_manager(session, mgr.id)
                    if not cand:
                        logging.info(f"[ingest] No candidate found for manager {mgr.id} ({mgr.email}); skipping this message.")
                        skipped += 1
                        if unread_only:
                            try:
                                mark_read(e["id"])
                            except Exception:
                                pass
                        continue

                    # Extract a plain email address (fallback to raw header)
                    raw_from = (e.get("from") or "").strip()
                    em_match = re.search(r"<([^>]+)>", raw_from)
                    from_email = (em_match.group(1) if em_match else raw_from).lower()

                    # Save inbound message
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
                    session.flush()  # msg.id

                    # Parse with LLM
                    intent, meta = parse_intent_llm(e.get("body") or "")
                    msg.intent = intent
                    msg.meta_json = meta or None
                    session.flush()

                    # Event
                    session.add(
                        ConversationEvent(
                            candidate_id=cand.id,
                            event_type=intent,
                            event_data=meta or {},
                            source_message_id=msg.id,
                        )
                    )

                    # Ensure CandidateStatus exists
                    status = session.query(CandidateStatus).filter_by(candidate_id=cand.id).first()
                    if not status:
                        status = CandidateStatus(candidate_id=cand.id)
                        session.add(status)

                    # Handle intents
                    if intent == "MEETING_SCHEDULED":
                        # Support single ISO or multiple proposed slots
                        slots_meta: List[dict] = []
                        if meta:
                            # Always include meeting_iso if given
                            if meta.get("meeting_iso"):
                                slots_meta.append({"start": meta["meeting_iso"], "end": None})

                            # Include all proposed_slots if given
                            if isinstance(meta.get("proposed_slots"), list):
                                for s in meta["proposed_slots"]:
                                    if isinstance(s, dict) and s.get("start"):
                                        slots_meta.append({"start": s["start"], "end": s.get("end")})


                        created_any = False
                        for s in slots_meta:
                            st = _parse_iso_flexible(s.get("start"))
                            en = _parse_iso_flexible(s.get("end")) if s.get("end") else None
                            if not st:
                                continue
                            if en and en <= st:
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
                            session.flush()
                            created_any = True

                        # We are now waiting on the applicant (do NOT set final_meeting_time yet)
                        status.current_status = "Awaiting Candidate Confirmation"
                        session.commit()

                        # Immediately email the applicant to confirm/counter, listing the times
                        if created_any:
                            _email_applicant_request_times(
                                session,
                                cand,
                                mgr,
                                slots_meta,
                                thread_id=msg.gmail_thread_id,
                            )

                        # Done with this email
                        if unread_only:
                            try:
                                mark_read(e["id"])
                            except Exception:
                                pass
                        processed += 1
                        continue  # skip other branches for this message

                    elif intent == "SALARY_DISCUSSION" and meta and meta.get("salary_amount"):
                        status.current_status = "Salary Discussed"
                        # Salary remains in ConversationEvent/Message meta; no cached salary field now.

                    elif intent == "REJECTION":
                        status.current_status = "Rejected by Manager"

                    elif intent == "PROCEED":
                        status.current_status = "Manager Approved"

                    session.commit()

                    # If PROCEED but no meeting time, auto-ask manager for availability
                    if intent == "PROCEED" and not (meta and (meta.get("meeting_iso") or meta.get("proposed_slots"))):
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

                    # Mark read after successful processing
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = ingest_manager_replies(limit=25, unread_only=True)
    logging.info(f"[ingest_manager_replies] {res}")
