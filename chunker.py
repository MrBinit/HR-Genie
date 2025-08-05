import re
from pathlib import Path
from typing import Dict

SECTION_PATTERNS = {
    "experience": [
        r"professional experience", r"work experience", r"experience",
        r"employment history", r"career summary"
    ],
    "skills": [
        r"skills", r"technical skills", r"core competencies", r"technologies"
    ],
    "education": [
        r"education", r"academic background", r"qualifications"
    ],
    "projects": [
        r"projects", r"key projects", r"notable work", r"case studies"
    ]
}


def smart_resume_chunker(resume_text: str) -> Dict[str, str]:
    """
    Extracts chunks of the resume based on common section headers using flexible pattern matching.

    Returns:
        Dict mapping section name (e.g., 'experience') to its content.
    """
    section_matches = []

    # Find all matching section headers
    for label, patterns in SECTION_PATTERNS.items():
        for pattern in patterns:
            # Match only clean header lines
            match = re.search(rf"(?i)^\s*({pattern})\s*$", resume_text, re.MULTILINE)
            if match:
                section_matches.append((label, match.start()))

    # Sort by order of appearance
    section_matches = sorted(section_matches, key=lambda x: x[1])

    # Extract content for each section
    extracted_sections = {}
    for i in range(len(section_matches)):
        label, start_idx = section_matches[i]
        end_idx = section_matches[i + 1][1] if i + 1 < len(section_matches) else len(resume_text)
        content = resume_text[start_idx:end_idx].strip()
        extracted_sections[label] = content

    return extracted_sections


def main():
    # Load resume file
    resume_path = Path("/home/binit/HR_system/resume_extractor/resume_output_1.md")
    if not resume_path.exists():
        print("Resume file not found.")
        return

    resume_text = resume_path.read_text(encoding='utf-8')
    sections = smart_resume_chunker(resume_text)

    print("Extracted Resume Sections:\n")
    for section, content in sections.items():
        print(f"--- {section.upper()} ---\n{content[:500]}...\n")


if __name__ == "__main__":
    main()
