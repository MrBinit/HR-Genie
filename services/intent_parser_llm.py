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
    - Now supports multiple slots via meta["proposed_slots"].
    - Resolves relative dates to actual ISO times using default_tz.
    """
    llm = get_llm(model_name="gpt-oss:20b", temperature=0.0)

    context_block = _summarize_thread_for_prompt(thread_context)
    subject_line = subject or ""

    prompt = f"""
You are an information extraction service for recruiting workflows.
You will receive:
  - Subject of the current email
  - Current incoming email body
  - A transcript of the conversation thread

Your task:
1) Choose the single best intent among:
   - MEETING_SCHEDULED: A concrete interview date/time is stated.
   - PROCEED: Manager approves but no date/time.
   - REJECTION
   - SALARY_DISCUSSION
   - OTHER
2) Extract:
   - meeting_iso: single ISO datetime (YYYY-MM-DDTHH:MM+05:45) if only one slot given.
   - proposed_slots: list of {{"start": "...", "end": "..."}} in ISO +05:45 if multiple slots given.
   - salary_amount
   - currency
   - notes
3) If manager uses relative expressions (e.g., "tomorrow at 2pm", "Friday next week"), resolve them to actual datetimes assuming today = NOW in {default_tz}.
4) Times must always include the +05:45 offset.

Output JSON only:
{{
  "intent": "MEETING_SCHEDULED|PROCEED|REJECTION|SALARY_DISCUSSION|OTHER",
  "meeting_iso": "<string or null>",
  "proposed_slots": [{{"start": "<string>", "end": "<string or null>"}}],
  "salary_amount": <integer or null>,
  "currency": "<3-letter code or null>",
  "notes": "<short string>"
}}

SUBJECT:
{subject_line}

THREAD CONTEXT:
{context_block}

CURRENT MESSAGE:
{current_message_text}
"""

    try:
        resp = llm.invoke(prompt)
        data = _coerce_json(resp.content)

        intent = str(data.get("intent") or "OTHER").strip().upper()
        if intent not in ALLOWED_INTENTS:
            intent = "OTHER"

        meta: Dict[str, Any] = {}
        # Meeting ISO
        if isinstance(data.get("meeting_iso"), str) and data["meeting_iso"].strip():
            meta["meeting_iso"] = data["meeting_iso"].strip()

        # Proposed slots
        if isinstance(data.get("proposed_slots"), list):
            clean_slots = []
            for slot in data["proposed_slots"]:
                if not isinstance(slot, dict):
                    continue
                start = slot.get("start")
                end = slot.get("end")
                if isinstance(start, str) and start.strip():
                    clean_slots.append({
                        "start": start.strip(),
                        "end": end.strip() if isinstance(end, str) and end.strip() else None
                    })
            if clean_slots:
                meta["proposed_slots"] = clean_slots

        # Salary
        if data.get("salary_amount") is not None:
            try:
                meta["salary_amount"] = int(data["salary_amount"])
            except Exception:
                pass

        # Currency
        if isinstance(data.get("currency"), str) and data["currency"].strip():
            meta["currency"] = data["currency"].strip().upper()

        # Notes
        if isinstance(data.get("notes"), str) and data["notes"].strip():
            meta["notes"] = data["notes"].strip()

        # Guardrail: If intent is MEETING_SCHEDULED but no meeting_iso or slots, downgrade
        if intent == "MEETING_SCHEDULED" and not (meta.get("meeting_iso") or meta.get("proposed_slots")):
            intent = "PROCEED"

        return intent, meta

    except Exception as e:
        logging.warning(f"[intent_parser_llm] LLM failed: {e}")
        return "OTHER", {}