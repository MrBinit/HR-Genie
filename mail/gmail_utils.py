# mail/gmail_utils.py
import base64, html, re
from typing import Dict, List, Optional
from email.utils import parsedate_to_datetime
from mail.mail_sender import get_gmail_service

def decode_body(full_msg: dict) -> str:
    payload = full_msg.get("payload", {}) or {}
    parts = payload.get("parts") or []
    def _pick(mt: str) -> Optional[str]:
        for p in parts:
            if p.get("mimeType") == mt and p.get("body", {}).get("data"):
                return p["body"]["data"]
        return None
    data = _pick("text/plain") or _pick("text/html") or payload.get("body", {}).get("data")
    if not data:
        return ""
    try:
        text = base64.urlsafe_b64decode(data).decode(errors="ignore")
    except Exception:
        return ""
    if "<" in text and ">" in text:  # light HTML strip
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    return text.strip()

def headers_dict(full_msg: dict) -> Dict[str, str]:
    payload = full_msg.get("payload", {}) or {}
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

def parse_gmail_date(date_str: Optional[str]):
    if not date_str: return None
    try: return parsedate_to_datetime(date_str)
    except Exception: return None

def fetch_messages_by_query(q: str, limit: int = 10) -> List[dict]:
    svc = get_gmail_service()
    res = svc.users().messages().list(userId="me", q=q, maxResults=limit).execute()
    ids = res.get("messages", []) or []
    return [svc.users().messages().get(userId="me", id=m["id"], format="full").execute() for m in ids]

def fetch_from_to(sender: str, to: Optional[str], unread_only=True, limit=10) -> List[dict]:
    q = f"from:{sender}"
    if to: q += f" to:{to}"
    if unread_only: q += " is:unread in:inbox"
    return fetch_messages_by_query(q, limit=limit)

def mark_read(gmail_id: str):
    svc = get_gmail_service()
    svc.users().messages().modify(userId="me", id=gmail_id, body={"removeLabelIds": ["UNREAD"]}).execute()
