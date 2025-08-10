# mail/mail_receiver.py
import base64, re
from typing import Dict, List
from mail.mail_sender import get_gmail_service

SENDER_FILTER = "srijanthapa70@gmail.com"

def _decode_body(msg) -> str:
    payload = msg.get("payload", {}) or {}
    parts = payload.get("parts") or []
    data = None
    for p in parts:
        if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
            data = p["body"]["data"]; break
    if not data:
        for p in parts:
            if p.get("mimeType") == "text/html" and p.get("body", {}).get("data"):
                data = p["body"]["data"]; break
    if not data:
        data = payload.get("body", {}).get("data")
    if not data:
        return ""
    text = base64.urlsafe_b64decode(data).decode(errors="ignore")
    return re.sub(r"<[^>]+>", " ", text).strip()

def get_emails_from_sender(limit: int = 10, include_unread_only: bool = True) -> List[Dict]:
    service = get_gmail_service()
    q = f'from:{SENDER_FILTER}'
    if include_unread_only:
        q += ' is:unread in:inbox'
    res = service.users().messages().list(userId="me", q=q, maxResults=limit).execute()
    msgs = res.get("messages", []) or []
    out: List[Dict] = []
    for m in msgs:
        full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        payload = full.get("payload", {}) or {}
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        out.append({
            "id": full.get("id"),
            "threadId": full.get("threadId"),
            "subject": headers.get("subject"),
            "from": headers.get("from"),
            "to": headers.get("to"),
            "date": headers.get("date"),
            "snippet": full.get("snippet"),
            "body": _decode_body(full),
        })
    return out

def mark_read(message_id: str) -> None:
    service = get_gmail_service()
    service.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()

def print_from_sender(limit: int = 10, include_unread_only: bool = True, mark_as_read: bool = False):
    emails = get_emails_from_sender(limit=limit, include_unread_only=include_unread_only)
    if not emails:
        print(f"No emails found from {SENDER_FILTER}" + (" (unread only)" if include_unread_only else ""))
        return
    for e in emails:
        print("=" * 70)
        print(f"From:    {e['from']}")
        print(f"To:      {e['to']}")
        print(f"Date:    {e['date']}")
        print(f"Subject: {e['subject']}")
        print(f"Snippet: {e['snippet']}")
        print(f"Body:\n{e['body']}")
        print("=" * 70)
        if mark_as_read:
            try:
                mark_read(e["id"])
                print(f"[INFO] Marked as read: {e['id']}")
            except Exception as ex:
                print(f"[WARN] Failed to mark as read: {e['id']} -> {ex}")

if __name__ == "__main__":
    print_from_sender(limit=5, include_unread_only=True, mark_as_read=False)
