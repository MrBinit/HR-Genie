import os
from pathlib import Path
from dotenv import load_dotenv
from model.ollama_model import get_llm
import logging
from typing import Dict



load_dotenv(override=True)
LOG_PATH = os.getenv("LOG_PATH", "app.log")
RESUME_PARSE_PATH = os.getenv("RESUME_PARSE_PATH")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)

llm = get_llm()

def summarize_section_with_llm(section_name: str, section_text: str) -> str:
    prompt = f"""
You are a helpful HR assistant. Summarize the following {section_name} section of a candidate's resume in short.
Highlight key points in bullet points.

{section_text}
"""
    response = llm.invoke(prompt)
    return response.content.strip()

def summarize_resume_sections(sections: Dict[str, str]) -> str:
    summarized_output = "\n\n **Summarized Resume Sections**\n\n"
    for section, content in sections.items():
        summary = summarize_section_with_llm(section, content)
        summarized_output += f"### {section.title()}\n{summary}\n\n"
    return summarized_output

if __name__ == "__main__":
    resume_file = Path(RESUME_PARSE_PATH)
    try:
        summary = summarize_resume_sections(resume_file)
        if summary:
            print(summary)

            out_path = resume_file.parent / "resume_summary.md"
            out_path.write_text(summary, encoding='utf-8')
            logging.info("Summary saved to: %s", out_path)

    except Exception as e:
        logging.error("Failed to summarize: %s", str(e))
        raise
