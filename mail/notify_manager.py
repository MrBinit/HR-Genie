# mail/notify_manager.py
from __future__ import annotations

import os
import logging
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import desc

from database.db import SessionLocal
from database.models import (
    Candidate,
    HiringManager,
    Referral,
    Employee,
    Message,          
)

from mail.mail_sender import send_email_html
from model.ollama_model import get_llm
from model.prompt_builder import prompt_manager_email


# Threshold (can be overridden by function arg)
THRESHOLD = float(os.getenv("THRESHOLD", "6.0"))


def _fallback_html(
    cand: Candidate,
    mgr_name: str,
    referrals: list[Referral],
    internal_referrers: list[dict[str, Any]],
) -> str:
    """Build a safe HTML body if the LLM fails."""
    # External/general referrals list
    ref_html = ""
    if referrals:
        ref_html = (
            "<p><b>Referral(s):</b></p><ul>"
            + "".join(
                f"<li>{r.name} ({r.email}) — {r.internal_department or 'N/A'}</li>"
                for r in referrals
            )
            + "</ul>"
        )

    # Internal referral block with full details
    internal_html = ""
    if internal_referrers:
        internal_html = (
            "<p><b>Internal Referral(s):</b></p><ul>"
            + "".join(
                f"<li><b>{r.get('name','N/A')}</b> — {r.get('department','N/A')} "
                f"(email: {r.get('email','N/A')}, phone: {r.get('phone','N/A')})</li>"
                for r in internal_referrers
            )
            + "</ul>"
        )

    score_s = f"{cand.cv_score:.1f}" if cand.cv_score is not None else "N/A"
    return f"""
    <div style="font-family:Arial, sans-serif; line-height:1.5;">
      <p>Hi {mgr_name},</p>
      <p><b>{cand.name or 'Candidate'}</b> has been evaluated for the <b>{cand.position or 'N/A'}</b> role.</p>
      <p><b>Score:</b> {score_s}/10</p>
      <p><b>Summary:</b><br>{cand.candidate_pitch or cand.summary or 'No summary available.'}</p>
      {internal_html}
      {ref_html}
      <hr style="border:none;border-top:1px solid #ddd;margin:16px 0;" />
      <p>Please reply with one of the following (plain text is fine):</p>
      <ul>
        <li><b>YES</b> / <b>PROCEED</b></li>
        <li><b>NO</b> / <b>REJECT</b></li>
        <li><b>SCHEDULE</b> &lt;preferred time window&gt;</li>
      </ul>
      <p>Thanks,<br/>HR Automation</p>
    </div>
    """


def _build_internal_referrers(db: Session, candidate_id: int, referrals: list[Referral]) -> list[dict]:
    """Gather full employee info for internal referrals."""
    internal_referrers: list[dict] = []
    for r in referrals:
        if getattr(r, "is_internal", False) and r.referrer_employee_id:
            emp = db.query(Employee).filter(Employee.id == r.referrer_employee_id).first()
            if emp:
                dept_name = emp.department.name if getattr(emp, "department", None) else None
                internal_referrers.append(
                    {
                        "name": emp.name,
                        "email": emp.email,
                        "phone": emp.phone,
                        "department": dept_name or "N/A",
                    }
                )
    return internal_referrers


def notify_manager_if_pass(
    candidate_id: int,
    threshold: Optional[float] = None,
    force_send: bool = False,
) -> Dict[str, Any]:
    """
    Notify the hiring manager for a candidate if their score >= threshold and status is 'Received'.
    - If 'force_send' is True, bypass the score/status check.
    - Logs the outbound email in 'messages'.
    - Saves the HTML body to candidate.manager_email_body.
    - Sets candidate.status = 'Forwarded to Manager'.

    Returns a dict with details of the operation.
    """
    if threshold is None:
        threshold = THRESHOLD

    db: Session = SessionLocal()
    try:
        cand = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not cand:
            return {"ok": False, "reason": f"Candidate {candidate_id} not found"}

        if not cand.manager_id:
            return {"ok": False, "reason": "candidate.manager_id missing"}

        mgr = db.query(HiringManager).filter(HiringManager.id == cand.manager_id).first()
        if not mgr or not mgr.email:
            return {"ok": False, "reason": "manager not found or missing email"}

        # Score & status gate unless forced
        if not force_send:
            if cand.cv_score is None:
                return {"ok": False, "reason": "cv_score is None (evaluate first)"}
            if cand.status != "Received":
                return {
                    "ok": True,
                    "notified": False,
                    "reason": f"Candidate status is '{cand.status}', not 'Received'",
                    "score": cand.cv_score,
                }
            if cand.cv_score < float(threshold):
                return {
                    "ok": True,
                    "notified": False,
                    "reason": f"Score {cand.cv_score} < threshold {threshold}",
                    "score": cand.cv_score,
                }

        # Collect referrals for context
        referrals = db.query(Referral).filter(Referral.candidate_id == candidate_id).all()
        internal_referrers = _build_internal_referrers(db, candidate_id, referrals)

        # Build HTML (LLM first, fallback if needed)
        llm = get_llm(model_name="gpt-oss:20b", temperature=0.0)
        prompt = prompt_manager_email(
            manager_name=mgr.name or "Manager",
            cand_name=cand.name or "Candidate",
            position=cand.position or "N/A",
            score=float(cand.cv_score) if cand.cv_score is not None else 0.0,
            summary=cand.summary or cand.candidate_pitch or "",
            referrals_list=[
                {
                    "name": r.name,
                    "email": r.email,
                    "company": getattr(r, "internal_department", None) or "N/A",
                }
                for r in referrals
            ],
            internal_referrers=internal_referrers,
        )

        try:
            resp = llm.invoke(prompt)
            html_body = (getattr(resp, "content", None) or "").strip()
            # very basic validation
            if "<" not in html_body or ">" not in html_body:
                raise ValueError("LLM returned non-HTML content")
        except Exception as e:
            logging.warning(f"LLM email generation failed, using fallback. Reason: {e}")
            html_body = _fallback_html(cand, mgr.name or "Manager", referrals, internal_referrers)

        # Subject with CID:<id> to allow downstream threading/parsing
        score_str = f"{cand.cv_score:.1f}" if cand.cv_score is not None else "N/A"
        subject = f"[Candidate Review] {cand.name or 'Candidate'} — {cand.position or ''} (Score: {score_str}/10) CID:{cand.id}"

        # Attach resume if present
        resume_path = cand.file_path if cand.file_path and os.path.exists(cand.file_path) else None
        if resume_path is None:
            logging.info(f"[notify] resume missing or unreadable for candidate {cand.id}: {cand.file_path}")

        # Send email
        send_resp = send_email_html(
            to_email=mgr.email,
            subject=subject,
            html_body=html_body,
            attachment_path=resume_path,
        )
        gmail_msg_id = (send_resp or {}).get("id")
        gmail_thread_id = (send_resp or {}).get("threadId")

        # Persist outbound message
        out_msg = Message(
            gmail_message_id=gmail_msg_id or f"local-{cand.id}",
            gmail_thread_id=gmail_thread_id,
            candidate_id=cand.id,
            manager_id=mgr.id,
            direction="outbound",
            sender_email=os.getenv("SENDER_EMAIL", ""),  # your sender mailbox
            subject=subject,
            body=html_body,
            intent=None,
            meta_json=None,
        )
        db.add(out_msg)

        # Update candidate snapshot
        cand.status = "Forwarded to Manager"
        cand.manager_email_body = html_body

        db.commit()

        logging.info(f"[notify] sent to {mgr.email} for candidate {candidate_id} (gmail_id={gmail_msg_id})")
        return {
            "ok": True,
            "notified": True,
            "manager_email": mgr.email,
            "candidate_id": cand.id,
            "score": cand.cv_score,
            "referrals": [r.email for r in referrals],
            "internal_referrers": internal_referrers,
            "attached_resume": bool(resume_path),
            "email_body": html_body,
            "gmail_message_id": gmail_msg_id,
            "gmail_thread_id": gmail_thread_id,
        }

    except Exception as e:
        logging.exception("Failed to notify manager")
        return {"ok": False, "reason": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # quick manual test (adjust id)
    cid = int(os.getenv("TEST_CANDIDATE_ID", "1"))
    res = notify_manager_if_pass(candidate_id=cid, threshold=THRESHOLD, force_send=False)
    print(res)
