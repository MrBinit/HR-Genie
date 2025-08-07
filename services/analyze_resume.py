import sys
import os
from dotenv import load_dotenv
# Setup paths and environment
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(BASE_DIR)
load_dotenv()

from langchain_core.prompts import ChatPromptTemplate
from model.ollama_model import get_llm
from model.prompt_builder import prompt_resume


# SQLAlchemy
from sqlalchemy.orm import Session
from database.db import SessionLocal
from database.models import Candidate

def retrieve_candidate_and_jd(candidate_id: int):
    db: Session = SessionLocal()
    try:
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            print(f"Candidate with ID {candidate_id} not found.")
            return None, None

        job_description = candidate.job_description
        if not job_description:
            print(f"Job description not linked.")
            return None, None

        return candidate.summary, job_description.description_text
    finally:
        db.close()

def evaluate_candidate(candidate_id: int):
    resume_text, job_description_text = retrieve_candidate_and_jd(candidate_id)

    if not resume_text or not job_description_text:
        print("Missing resume or job description text.")
        return

    # Load the LLM
    llm = get_llm(model_name="gpt-oss:20b", temperature=0.0)

    # Build the prompt
    prompt = prompt_resume(resume_text, job_description_text)
    response = llm.invoke(prompt)
    return response.content.strip()

print(evaluate_candidate(1))