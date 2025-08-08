import os
from pathlib import Path
from dotenv import load_dotenv
from model.ollama_model import get_llm
import logging
from typing import Dict
from model.prompt_builder import prompt_resume_section


load_dotenv(override=True)
LOG_PATH = os.getenv("LOG_PATH", "app.log")

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
    prompt = prompt_resume_section(section_name, section_text)
    response = llm.invoke(prompt)
    return response.content.strip()

def summarize_resume_sections(sections: Dict[str, str]) -> str:
    summarized_output = "\n\n **Summarized Resume Sections**\n\n"
    for section, content in sections.items():

        print(f"Section: {section}, length: {len(content)}")

        # # trim
        # if len(content) > 1000:
        #     print(f"Trimming '{section}' from {len(content)} to 1000 characters.")
        #     content = content[:1000]
        summary = summarize_section_with_llm(section, content)
        summarized_output += f"### {section.title()}\n{summary}\n\n"
    return summarized_output

