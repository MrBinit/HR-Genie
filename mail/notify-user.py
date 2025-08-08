# notify_manager.py
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import logging

from sqlalchemy.orm import Session
from sqlalchemy import desc
from database.db import SessionLocal
from database.models import Candidate, HiringManager, Referral
from mail_sender import send_email_html
from model.ollama_model import get_llm
from model.prompt_builder import prompt_manager_email

THRESHOLD = 6.0

def _fallback_html(cand: Candidate, mgr_name: str, referrals: list[Referral]) -> str:
    ref_html = ""
    if referrals:
        ref_html = "<p><b>Referral(s):</b></p><ul>" + "".join(
            f"<li>{r.name} ({r.email}) — {r.company or 'N/A'}</li>" for r in referrals
        ) + "</ul>"

    return f"""
    <div style="font-family:Arial, sans-serif; line-height:1.5;">
      <p>Hi {mgr_name},</p>
      <p><b>{cand.name or 'Candidate'}</b> has been evaluated for the <b>{cand.position or 'N/A'}</b> role.</p>
      <p><b>Score:</b> {f'{cand.cv_score:.1f}' if cand.cv_score is not None else 'N/A'}/10</p>
      <p><b>Summary:</b><br>{cand.candidate_pitch or 'No summary available.'}</p>
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


def _pick_latest_candidate(db: Session, threshold: float) -> Candidate | None:
    """Optionally used if you want auto-pick mode; not used in main path here."""
    return (
        db.query(Candidate)
          .filter(Candidate.cv_score != None)
          .filter(Candidate.cv_score > threshold)
          .filter(Candidate.status != "Forwarded to Manager")
          .order_by(desc(Candidate.uploaded_at))
          .first()
    )


def notify_manager_if_pass(candidate_id: int, threshold: float = THRESHOLD) -> dict:
    """
    If candidate.cv_score > threshold, generate the manager email with LLM (HTML) and send via Gmail.
    Also includes referrals in the email. Sets status to 'Forwarded to Manager' on success.
    """
    db: Session = SessionLocal()
    try:
        cand = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not cand:
            return {"ok": False, "reason": f"Candidate {candidate_id} not found"}

        if cand.cv_score is None:
            return {"ok": False, "reason": "cv_score is None (evaluate first)"}

        if cand.cv_score <= threshold:
            logging.info(f"Candidate {candidate_id} score {cand.cv_score} ≤ {threshold}; not notifying.")
            return {"ok": True, "notified": False, "score": cand.cv_score}

        if not cand.manager_id:
            return {"ok": False, "reason": "candidate.manager_id missing"}

        mgr = db.query(HiringManager).filter(HiringManager.id == cand.manager_id).first()
        if not mgr or not mgr.email:
            return {"ok": False, "reason": "manager not found or missing email"}

        referrals = db.query(Referral).filter(Referral.candidate_id == candidate_id).all()

        llm = get_llm(model_name="gpt-oss:20b", temperature=0.0)
        prompt = prompt_manager_email(
            manager_name=mgr.name or "Manager",
            cand_name=cand.name or "Candidate",
            position=cand.position or "N/A",
            score=float(cand.cv_score),
            summary=cand.summary or "",
            referrals_list=[{"name": r.name, "email": r.email, "company": r.company} for r in referrals]
        )
        try:
            resp = llm.invoke(prompt)
            html_body = (resp.content or "").strip()
            if "<" not in html_body or ">" not in html_body:
                raise ValueError("LLM returned non-HTML content")
        except Exception as e:
            logging.warning(f"LLM email generation failed, using fallback. Reason: {e}")
            html_body = _fallback_html(cand, mgr.name or "Manager", referrals)

        subject = f"[Candidate Review] {cand.name or 'Candidate'} — {cand.position or ''} (Score: {cand.cv_score:.1f}/10)"

        resume_path = cand.file_path if cand.file_path and os.path.exists(cand.file_path) else None
        if not resume_path:
            logging.warning(f"Resume file not found or unreadable for candidate {cand.id}: {cand.file_path}")

        send_email_html(to_email=mgr.email,
                        subject=subject,
                        html_body=html_body,
                        attachment_path=resume_path)

        cand.status = "Forwarded to Manager"
        db.commit()

        logging.info(f"Notified manager {mgr.email} for candidate {candidate_id}")
        return {
            "ok": True,
            "notified": True,
            "manager_email": mgr.email,
            "candidate_id": cand.id,
            "score": cand.cv_score,
            "referrals": [r.email for r in referrals],
        }

    except Exception as e:
        logging.exception("Failed to notify manager")
        return {"ok": False, "reason": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = notify_manager_if_pass(candidate_id=1, threshold=THRESHOLD)
    print(res)
