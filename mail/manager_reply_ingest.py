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
)
from mail.mail_sender import get_gmail_service, send_email_html
from services.intent_parser_llm import parse_intent_llm


# ---------- Helpers to decode Gmail bodies ----------
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
        # very light tag strip; your LLM is robust anyway
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    return text.strip()


def _headers_dict(raw_msg: dict) -> Dict[str, str]:
    payload = raw_msg.get("payload", {}) or {}
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


# ---------- Compose auto-reply when time is missing ----------
def _compose_availability_followup(cand: Candidate, mgr: HiringManager) -> str:
    return f"""
<div style="font-family:Arial,sans-serif;line-height:1.5">
  <p>Hi {mgr.name or 'there'},</p>
  <p>Great—thanks for confirming you’d like to proceed with <b>{cand.name or 'the candidate'}</b>.</p>
  <p>Could you please share a few time options for the interview (date &amp; time, with timezone)?
     We’ll schedule right away.</p>
  <p>With regards,<br/>HR-Team</p>
</div>
""".strip()


# ---------- Candidate resolution heuristics ----------
def _resolve_candidate_for_manager(session, manager_id: str) -> Optional[Candidate]:
    """
    Heuristic: pick the most recent candidate under this manager who is in a
    stage that makes sense for replies (Forwarded to Manager first, else Received).
    You can improve this by storing Gmail threadId on the candidate when you first email.
    """
    cand = (
        session.query(Candidate)
        .filter(Candidate.manager_id == manager_id)
        .filter(Candidate.status.in_(["Forwarded to Manager", "Received"]))
        .order_by(Candidate.uploaded_at.desc())
        .first()
    )
    return cand


# ---------- Core ingest ----------
def ingest_manager_replies(limit: int = 25, unread_only: bool = True) -> Dict:
    """
    Fetch unread Gmail messages, filter to known managers, save inbound,
    parse with LLM, create conversation events & update candidate_status.
    If intent == PROCEED without time -> auto-reply asking for availability.
    """
    session = SessionLocal()
    svc = get_gmail_service()

    try:
        # Build list of manager emails from DB
        managers: List[HiringManager] = session.query(HiringManager).all()
        mgr_by_email = {m.email.strip().lower(): m for m in managers if m.email}
        if not mgr_by_email:
            logging.info("[ingest] No managers found in DB; nothing to ingest.")
            return {"ok": True, "processed": 0, "skipped": 0, "errors": 0}

        # Build Gmail query
        # We could OR all manager emails in the query, but for simplicity,
        # fetch unread inbox and filter in code. Adjust if your inbox is huge.
        q = "in:inbox"
        if unread_only:
            q += " is:unread"
        q += " newer_than:60d"  # safety window; adjust as needed

        res = svc.users().messages().list(userId="me", q=q, maxResults=limit).execute()
        msg_refs = res.get("messages", []) or []

        processed = skipped = errors = 0

        for ref in msg_refs:
            try:
                full = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
                headers = _headers_dict(full)
                from_raw = headers.get("from", "")  # e.g., "Name <email@domain>"
                m = re.search(r"<([^>]+)>", from_raw)
                from_email = (m.group(1) if m else from_raw).strip().lower()

                if from_email not in mgr_by_email:
                    skipped += 1
                    continue

                mgr = mgr_by_email[from_email]
                body = _decode_gmail_body(full)
                subject = headers.get("subject") or ""
                thread_id = full.get("threadId")
                gmail_id = full.get("id")

                # Resolve candidate for this manager
                cand = _resolve_candidate_for_manager(session, mgr.id)
                if not cand:
                    logging.info(f"[ingest] No candidate found for manager {mgr.id} ({from_email}); skipping this message.")
                    skipped += 1
                    # Still mark as read to avoid infinite loop
                    if unread_only:
                        svc.users().messages().modify(
                            userId="me", id=gmail_id, body={"removeLabelIds": ["UNREAD"]}
                        ).execute()
                    continue

                # Save inbound message
                msg = Message(
                    gmail_message_id=gmail_id,
                    gmail_thread_id=thread_id,
                    candidate_id=cand.id,
                    manager_id=mgr.id,
                    direction="inbound",
                    sender_email=from_email,
                    subject=subject,
                    body=body,
                    received_at=datetime.now(timezone.utc),
                )
                session.add(msg)
                session.flush()  # get msg.id

                # Parse with LLM
                intent, meta = parse_intent_llm(body)

                # Update message with parsed intent/meta
                msg.intent = intent
                msg.meta_json = meta or None
                session.flush()

                # Save conversation event
                session.add(ConversationEvent(
                    candidate_id=cand.id,
                    event_type=intent,
                    event_data=meta or {},
                    source_message_id=msg.id
                ))

                # Update candidate_status based on intent
                status = session.query(CandidateStatus).filter_by(candidate_id=cand.id).first()
                if not status:
                    status = CandidateStatus(candidate_id=cand.id)
                    session.add(status)

                if intent == "MEETING_SCHEDULED" and meta.get("meeting_iso"):
                    status.current_status = "Interview Scheduled"
                    try:
                        # allow both "2025-08-15T14:30" and "2025-08-15T14:30:00"
                        status.last_meeting_time = datetime.fromisoformat(meta["meeting_iso"])
                    except Exception:
                        pass  # keep it None if parse fails

                elif intent == "SALARY_DISCUSSION" and meta.get("salary_amount"):
                    status.current_status = "Salary Discussed"
                    status.last_salary_offer = meta["salary_amount"]

                elif intent == "REJECTION":
                    status.current_status = "Rejected by Manager"

                elif intent == "PROCEED":
                    # Tentative: set to "Manager Approved" unless we ask for availability below
                    status.current_status = "Manager Approved"

                session.commit()

                # If manager said proceed but didn't give a time: auto-reply asking for availability
                if intent == "PROCEED" and not (meta.get("meeting_iso")):
                    html = _compose_availability_followup(cand, mgr)
                    resp = send_email_html(
                        to_email=mgr.email,
                        subject=f"Re: {subject or 'Interview Scheduling'}",
                        html_body=html,
                        thread_id=thread_id
                    )

                    # Store outbound message
                    out_id = resp.get("id")
                    out_msg = Message(
                        gmail_message_id=out_id,
                        gmail_thread_id=thread_id,
                        candidate_id=cand.id,
                        manager_id=mgr.id,
                        direction="outbound",
                        sender_email=None,
                        subject=f"Re: {subject or 'Interview Scheduling'}",
                        body=html,
                        received_at=datetime.now(timezone.utc),
                        intent="ASKED_FOR_AVAILABILITY",
                        meta_json={"reason": "PROCEED_without_time"}
                    )
                    session.add(out_msg)
                    session.flush()
                    session.add(ConversationEvent(
                        candidate_id=cand.id,
                        event_type="ASKED_FOR_AVAILABILITY",
                        event_data={"reason": "PROCEED_without_time"},
                        source_message_id=out_msg.id
                    ))
                    # Update status for this branch
                    status.current_status = "Awaiting Manager Availability"
                    session.commit()

                # Mark inbound as read
                if unread_only:
                    svc.users().messages().modify(
                        userId="me", id=gmail_id, body={"removeLabelIds": ["UNREAD"]}
                    ).execute()

                processed += 1

            except Exception as ex:
                logging.exception(f"[ingest] failed on message {ref.get('id')}: {ex}")
                errors += 1
                # best effort: mark as read to avoid poison-pill loop (optional)
                try:
                    if unread_only and ref.get("id"):
                        svc.users().messages().modify(
                            userId="me", id=ref["id"], body={"removeLabelIds": ["UNREAD"]}
                        ).execute()
                except Exception:
                    pass

        return {"ok": True, "processed": processed, "skipped": skipped, "errors": errors}

    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = ingest_manager_replies(limit=25, unread_only=True)
    logging.info(f"[ingest_manager_replies] {res}")
