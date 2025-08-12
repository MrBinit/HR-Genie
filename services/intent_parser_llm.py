# services/intent_parser_llm.py
# Context-aware LLM intent extraction for manager replies.
# Uses recent thread messages to improve accuracy (meeting vs proceed vs salary).

from __future__ import annotations
import json
import re
import logging
from typing import Tuple, Dict, Any, List, Optional

from model.ollama_model import get_llm

# Allowed intents
ALLOWED_INTENTS = {
    "MEETING_SCHEDULED",  # concrete date/time present
    "PROCEED",            # manager approves but no concrete date/time
    "REJECTION",
    "SALARY_DISCUSSION",
    "OTHER",
}

def _coerce_json(s: str) -> dict:
    """Strip fences and parse JSON safely."""
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?", "", s, flags=re.I).strip()
    s = re.sub(r"```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        return {}

def _summarize_thread_for_prompt(thread_messages: Optional[List[Dict[str, Any]]], limit: int = 6) -> str:
    """
    thread_messages item schema (recommended):
      {
        "direction": "inbound" | "outbound",
        "sender": "email-or-name",
        "subject": "str (optional)",
        "body": "str",
        "ts": "ISO time (optional)"
      }
    """
    if not thread_messages:
        return "No prior context available."

    # Keep only last N messages
    msgs = thread_messages[-limit:]
    lines = []
    for m in msgs:
        role = "Manager" if m.get("direction") == "inbound" else "HR System"
        subj = m.get("subject") or ""
        ts = m.get("ts") or ""
        body = (m.get("body") or "").strip()
        # truncate long bodies for token safety
        if len(body) > 1500:
            body = body[:1500] + " ..."
        lines.append(f"[{role}] {ts} {('SUBJ: ' + subj) if subj else ''}\n{body}\n")
    return "\n---\n".join(lines)

def parse_intent_llm(
    current_message_text: str,
    *,
    subject: Optional[str] = None,
    thread_context: Optional[List[Dict[str, Any]]] = None,
    default_tz: str = "Asia/Kathmandu"
) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (intent, meta) extracted by an LLM with conversation context.

    - intent ∈ {"MEETING_SCHEDULED","PROCEED","REJECTION","SALARY_DISCUSSION","OTHER"}
    - meta keys (only include if present):
        meeting_iso: ISO 8601 datetime for the interview (assume default_tz if not given)
        salary_amount: integer
        currency: "USD"|"NPR"|... or 3-letter code if known
        notes: short free-text
    """
    llm = get_llm(model_name="gpt-oss:20b", temperature=0.0)

    context_block = _summarize_thread_for_prompt(thread_context)
    subject_line = subject or ""

    # System prompt that forces a clean JSON schema and context-aware rules
    prompt = f"""
You are an information extraction service for recruiting workflows.
You will receive:
  - The subject of the current email
  - The current incoming email body
  - A short transcript of the conversation thread (most recent messages last)

Your task:
  1) Decide the single best intent among:
     - MEETING_SCHEDULED: A concrete interview date/time is stated.
     - PROCEED: Manager approves moving forward, but no concrete date/time.
     - REJECTION: Manager declines to move forward.
     - SALARY_DISCUSSION: A salary figure or compensation range is being discussed.
     - OTHER: Anything else.
  2) Extract structured fields when possible.

Rules:
  - If a concrete date AND time are present for an interview, choose MEETING_SCHEDULED.
  - If the manager says "yes/approved" but no concrete date/time, choose PROCEED (do NOT invent a date/time).
  - If both a meeting time AND salary are present, prefer MEETING_SCHEDULED and also include salary fields in meta if clearly given.
  - If timezone is not stated, assume {default_tz} and produce an ISO 8601 datetime (YYYY-MM-DDTHH:MM) without seconds.
  - Keep "notes" very short.
  - Output ONLY valid JSON (no prose, no markdown).

Output schema (JSON only):
{{
  "intent": "MEETING_SCHEDULED|PROCEED|REJECTION|SALARY_DISCUSSION|OTHER",
  "meeting_iso": "<ISO 8601 like 2025-08-15T14:30 or null>",
  "salary_amount": <integer or null>,
  "currency": "<3-5 letter code or null>",
  "notes": "<short string>"
}}

SUBJECT:
{subject_line}

THREAD CONTEXT (oldest to newest):
{context_block}

CURRENT INCOMING EMAIL BODY:
{current_message_text}
"""

    try:
        resp = llm.invoke(prompt)
        data = _coerce_json(resp.content)
        intent = str(data.get("intent") or "OTHER").strip().upper()
        if intent not in ALLOWED_INTENTS:
            intent = "OTHER"

        meta: Dict[str, Any] = {}

        # only include fields that exist and are non-empty
        meeting_iso = data.get("meeting_iso")
        if isinstance(meeting_iso, str) and meeting_iso.strip():
            # normalize a bit (drop seconds if present)
            meeting_iso = meeting_iso.strip()
            meeting_iso = re.sub(r":\d{2}(?:(?:\+\d{2}:\d{2})|Z)?$", "", meeting_iso) if len(meeting_iso) > 16 else meeting_iso
            meta["meeting_iso"] = meeting_iso

        salary_amount = data.get("salary_amount")
        try:
            if salary_amount is not None:
                meta["salary_amount"] = int(salary_amount)
        except Exception:
            pass

        currency = data.get("currency")
        if isinstance(currency, str) and currency.strip():
            meta["currency"] = currency.strip().upper()

        notes = data.get("notes")
        if isinstance(notes, str) and notes.strip():
            meta["notes"] = notes.strip()

        # Decision guardrails: if the LLM said MEETING_SCHEDULED but gave no meeting_iso, downgrade to PROCEED.
        if intent == "MEETING_SCHEDULED" and "meeting_iso" not in meta:
            intent = "PROCEED"

        return intent, meta

    except Exception as e:
        logging.warning(f"[intent_parser_llm] LLM failed, defaulting to OTHER: {e}")
        return "OTHER", {}
