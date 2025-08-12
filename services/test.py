# test_intent_parser_llm.py

from services.intent_parser_llm import parse_intent_llm

# Example thread context (oldest to newest)
thread_context = [
    {
        "direction": "outbound",
        "sender": "HR System",
        "subject": "Interview Scheduling for Data Scientist",
        "body": "Dear Manager,\nPlease let us know a suitable time and date for the interview.",
        "ts": "2025-08-10T09:00"
    }
]

# Test inputs — try each one
test_cases = [
    "Let's schedule the interview on 15 August 2025 at 2:30 PM.",
    "Yes, let's proceed with the interview.",
    "We cannot move forward with this candidate.",
    "We can offer NPR 150,000 monthly for this position.",
    "Let's do the interview on 20th August at 3 PM, and salary will be NPR 180,000."
]

for idx, text in enumerate(test_cases, start=1):
    intent, meta = parse_intent_llm(
        current_message_text=text,
        subject="Re: Interview Scheduling",
        thread_context=thread_context
    )
    print(f"--- Test Case {idx} ---")
    print(f"Email Body: {text}")
    print(f"Detected Intent: {intent}")
    print(f"Meta: {meta}")
    print()
