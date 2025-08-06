import re
from pathlib import Path

EMAIL_REGEX = r'[\w\.-]+@[\w\.-]+\.\w+'
PHONE_REGEX = r'(\+?977[-\s]?)?(9\d{8})'
TITLE_KEYWORDS = [
    "engineer", "developer", "manager", "consultant", "analyst", "candidate",
    "coordinator", "professor", "lecturer", "researcher", "founder", "director",
    "intern", "lead", "specialist", "architect", "technician", "executive",
    "officer", "trainer", "supervisor", "scientist", "president", "head"
]

def extract_email(text: str) -> str:
    match = re.search(EMAIL_REGEX, text)
    return match.group(0) if match else None

def extract_phone(text: str) -> str:
    match = re.search(PHONE_REGEX, text)
    if match:
        return (match.group(1) or '') + match.group(2)
    return None

def extract_name(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    skip_keywords = ["/", "http", "https", ".com"]

    for line in lines[:2]:
        if any(k in line for k in skip_keywords):
            continue
        words = line.split()
        capitalized = [w for w in words if w[0].isupper()]
        if len(capitalized) >= 2:
            return line
    return None

def looks_like_name(line: str) -> bool:
    if extract_email(line) or extract_phone(line):
        return False
    if any(char.isdigit() for char in line):
        return False
    words = line.strip().split()
    return sum(1 for w in words if w and w[0].isupper()) >= 2

def looks_like_title_or_company(line: str) -> bool:
    if any(keyword in line.lower() for keyword in TITLE_KEYWORDS):
        return True
    if len(line.split()) >= 2 and not extract_email(line) and not extract_phone(line):
        return True
    return False

def extract_referrals(text: str) -> list:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    recent_lines = lines[-15:] 
    start_index = None

    # Detect heading
    for idx, line in enumerate(recent_lines):
        if re.search(r'\b(references|referees|reference)\b', line, re.IGNORECASE):
            start_index = idx + 1
            break
    if start_index is None:
        return []

    block = recent_lines[start_index:]
    referrals = []
    current = {}

    for line in block:
        if not line:
            continue

        email = extract_email(line)
        phone = extract_phone(line)

        if email:
            current["email"] = email
        if phone:
            current["phone"] = phone

        if "name" not in current and looks_like_name(line):
            current["name"] = line
        elif "company" not in current and looks_like_title_or_company(line):
            current["company"] = line

        # If we have name and email, store referral and reset
        if "name" in current and "email" in current:
            referrals.append(current)
            current = {}

    # Catch any remaining referral
    if current and "name" in current and "email" in current:
        referrals.append(current)

    return referrals

def extract_contact_info_from_resume(resume_path: Path) -> dict:
    text = resume_path.read_text(encoding='utf-8', errors='ignore')

    return {
        "name": extract_name(text),
        "email": extract_email(text),
        "phone": extract_phone(text),
        "referrals": extract_referrals(text)
    }
