# /app/mail/auto_reject.py
from datetime import datetime, timedelta
import logging
from sqlalchemy.orm import Session

from database.db import SessionLocal
from database.models import Candidate, Referral
from mail.mail_sender import send_email_html
from model.ollama_model import get_llm
from model.prompt_builder import _llm_rejection_email

def _wrap_html(text: str) -> str:
    # If LLM returns plain HTML, keep it; otherwise wrap as simple HTML
    if "<" in (text or "") and ">" in (text or ""):
        return text
    safe = (text or "").replace("\n", "<br/>")
    return f"<div style='font-family:Arial,sans-serif;line-height:1.5'>{safe}</div>"


def auto_reject_candidates(grace_days: int = 7, threshold: float = 6.0) -> dict:
    """
    Reject candidates who are still 'Received' after `grace_days`,
    have NO internal referral, and whose cv_score < threshold.
    Sends a polite LLM-written rejection email to the candidate.
    """
    db: Session = SessionLocal()
    checked = rejected = emailed = 0
    try:
        cutoff = datetime.utcnow() - timedelta(days=grace_days)

        cands = (
            db.query(Candidate)
              .filter(Candidate.status == "Received")
              .filter(Candidate.uploaded_at <= cutoff)
              .all()
        )
        logging.info(f"[auto_reject] candidates to check: {len(cands)} cutoff={cutoff.isoformat()}Z")

        for cand in cands:
            checked += 1

            # any internal referral?
            has_internal = (
                db.query(Referral)
                  .filter(Referral.candidate_id == cand.id, Referral.is_internal.is_(True))
                  .count() > 0
            )
            score_ok = (cand.cv_score is not None and float(cand.cv_score) < float(threshold))
            email_ok = bool(cand.email)

            logging.info(
                f"[auto_reject] cand_id={cand.id} status={cand.status} "
                f"score={cand.cv_score} has_internal={has_internal} email={cand.email}"
            )

            if not email_ok:
                logging.info(f"[auto_reject] skip {cand.id}: no email")
                continue
            if has_internal:
                logging.info(f"[auto_reject] skip {cand.id}: has internal referral")
                continue
            if not score_ok:
                logging.info(f"[auto_reject] skip {cand.id}: score missing or >= threshold")
                continue

            # Send rejection email
            html_body = _llm_rejection_email(cand.name)
            try:
                send_email_html(
                    to_email=cand.email,
                    subject="Application Update",
                    html_body=html_body
                )
                logging.info(f"[auto_reject] sent rejection to cand_id={cand.id} -> {cand.email}")
                emailed += 1
            except Exception as e:
                logging.warning(f"[auto_reject] Gmail send failed for cand_id={cand.id}: {e}")

            # Flip status so we don't send again
            cand.status = "Rejected"
            rejected += 1

        db.commit()
        logging.info(f"[auto_reject] done: checked={checked}, rejected={rejected}, emailed={emailed}")
        return {"ok": True, "checked": checked, "rejected": rejected, "emailed": emailed}
    except Exception as e:
        db.rollback()
        logging.exception("auto_reject_candidates failed")
        return {"ok": False, "reason": str(e)}
    finally:
        db.close()
