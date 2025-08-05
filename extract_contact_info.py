import re
from pathlib import Path

def extract_email(text: str) -> str:
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    return match.group(0) if match else None

def extract_phone(text: str) -> str:
    match = re.search(r'(\+?977[-\s]?)?(9\d{9})', text)
    if match:
        return f"{match.group(1) or ''}{match.group(2)}"
    return None

def extract_name(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    skip_keywords = ["/", "http", "https", ".com"]

    for line in lines[:2]:  # Only look at the first 2 lines
        if any(k in line for k in skip_keywords):
            continue
        words = line.split()
        capitalized = [w for w in words if w[0].isupper()]
        if len(capitalized) >= 2:
            return line

    return None



def extract_contact_info_from_resume(resume_path: Path) -> dict:
    text = resume_path.read_text(encoding='utf-8', errors='ignore')

    return {
        "name": extract_name(text),
        "email": extract_email(text),
        "phone": extract_phone(text)
    }

# if __name__ == "__main__":
#     resume_file = Path("/app/resume_extractor/Binit_Sapkota_resume.md")
#     if resume_file.exists():
#         info = extract_contact_info_from_resume(resume_file)
#         print("Extracted Contact Info:\n")
#         for key, value in info.items():
#             print(f"{key.title()}: {value}")
#     else:
#         print("Resume file not found.")
