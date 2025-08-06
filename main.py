from fastapi import FastAPI, UploadFile, File, Form
import shutil
import os
import pathlib
import logging
from dotenv import load_dotenv
from parse import parse_document
from fastapi.responses import JSONResponse
from extract_contact_info import extract_contact_info_from_resume
from db import SessionLocal
from models import Candidate, Referral, JobDescription
from sqlalchemy.exc import IntegrityError
from chunker import smart_resume_chunker
from summarize_resume import summarize_resume_sections
from datetime import datetime



# Load environment variables
load_dotenv(override=True)

JOB_DESCRIPTION_DIR = pathlib.Path(os.getenv("JOB_DESCRIPTION_DIR", "/app/job_description"))
RESUME_INPUT_PATH = pathlib.Path(os.getenv("PDF_INPUT_PATH", "/app/resume"))
JOB_DESCRIPTION_OUTPUT_DIR = pathlib.Path(os.getenv("JOB_DESCRIPTION_OUTPUT_DIR", "/app/job_description_extractor"))
JOB_DESCRIPTION_DIR.mkdir(parents=True, exist_ok=True)
RESUME_INPUT_PATH.mkdir(parents=True, exist_ok=True)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
app = FastAPI()

@app.post("/upload/resume")
async def upload_resume(file: UploadFile = File(...)):
    try:
        upload_dir = RESUME_INPUT_PATH
        file_path = upload_dir / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logging.info(f"Resume saved to: {file_path}")
        parsed_text = parse_document(str(file_path), is_job_description=False)

        parsed_md_path = pathlib.Path("/app/resume_extractor") / (file_path.stem + ".md")
        extracted_info = {}
        summarize_resume = None

        if parsed_md_path.exists():
            extracted_info = extract_contact_info_from_resume(parsed_md_path)
            resume_text = parsed_md_path.read_text(encoding='utf-8')
            chunked_resume = smart_resume_chunker(resume_text)
            summarize_resume = summarize_resume_sections(chunked_resume)

        db = SessionLocal()
        try:
            new_candidate = Candidate(
                name=extracted_info.get("name"),
                email=extracted_info.get("email"),
                phone=extracted_info.get("phone"),
                file_path=str(file_path),
                candidate_pitch=None,
                summary=summarize_resume,
                status="Received"
            )
            db.add(new_candidate)
            db.commit()
            db.refresh(new_candidate)

            for ref in extracted_info.get("referrals", []):
                if ref["name"] and ref["email"]:
                    referral = Referral(
                        name=ref["name"],
                        company=ref.get("company", ""),
                        email=ref["email"],
                        candidate_id=new_candidate.id
                    )
                    db.add(referral)
            db.commit()
        except IntegrityError:
            db.rollback()
            logging.warning("Candidate with this email already exists.")
        finally:
            db.close()

        return {
            "message": "Resume uploaded and processed successfully",
            "filename": file.filename,
            "parsed_preview": parsed_text[:500] + "...",
            "extracted_info": extracted_info
        }

    except Exception as e:
        logging.error(f"Error uploading resume: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/upload/job-description")
async def upload_job_description(
    position: str = Form(...),
    description_text: str = Form(None),
    file: UploadFile = File(None)
):
    try:
        # Reject if both or neither are provided
        if (file and description_text) or (not file and not description_text):
            return JSONResponse(
                status_code=400,
                content={"error": "Provide either a job description file OR text — not both."}
            )

        file_path_str = None
        parsed_text = None

        # Normalize position to lowercase
        position_lower = position.strip().lower()

        # Option 1: Handle file upload
        if file:
            file_path = JOB_DESCRIPTION_DIR / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            file_path_str = str(file_path)
            logging.info(f"Job description file saved to: {file_path_str}")

            parsed_text = parse_document(str(file_path), is_job_description=True)

        # Handle plain text input and save as Markdown
        elif description_text:
            md_filename = f"{position_lower.replace(' ', '_')}.md"
            file_path = JOB_DESCRIPTION_OUTPUT_DIR / md_filename
            file_path.write_text(description_text, encoding="utf-8")

            file_path_str = str(file_path)
            parsed_text = description_text
            logging.info(f"Job description text saved as markdown to: {file_path_str}")

        # Save to DB
        db = SessionLocal()
        try:
            jd = JobDescription(
                position=position_lower,
                description_text=parsed_text,
                file_path=file_path_str
            )
            db.add(jd)
            db.commit()
            db.refresh(jd)
        except IntegrityError:
            db.rollback()
            logging.error("Failed to insert job description due to integrity error.")
            return JSONResponse(status_code=400, content={"error": "Duplicate or invalid data."})
        except Exception as e:
            db.rollback()
            logging.error(f"Database error: {e}")
            return JSONResponse(status_code=500, content={"error": str(e)})
        finally:
            db.close()

        return {
            "message": "Job description uploaded and saved successfully",
            "position": position_lower,
            "file_path": file_path_str,
            "parsed_preview": parsed_text[:500] + "..." if parsed_text else "Empty"
        }

    except Exception as e:
        logging.error(f"Error uploading job description: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
