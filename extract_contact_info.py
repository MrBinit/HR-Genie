import re
from pathlib import Path

def extract_email(text: str) -> str:
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    return match.group(0) if match else None

def extract_phone(text: str) -> str:
    match = re.search(r'(\+?\d[\d\s\-\(\)]{8,}\d)', text)
    return match.group(0) if match else None

def extract_name(text: str) -> str:
    # Heuristic: first line with at least 2 capitalized words
    lines = text.splitlines()
    for line in lines[:10]:
        words = line.strip().split()
        if len(words) >= 2 and all(w[0].isupper() for w in words[:2]):
            return line.strip()
    return None

def extract_contact_info_from_resume(resume_path: Path) -> dict:
    text = resume_path.read_text(encoding='utf-8')

    return {
        "name": extract_name(text),
        "email": extract_email(text),
        "phone": extract_phone(text)
    }

if __name__ == "__main__":
    resume_file = Path("/home/binit/HR_system/resume_extractor/resume_output_1.md")
    if resume_file.exists():
        info = extract_contact_info_from_resume(resume_file)
        print("Extracted Contact Info:\n")
        for key, value in info.items():
            print(f"{key.title()}: {value}")
    else:
        print("Resume file not found.")
