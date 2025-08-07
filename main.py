from fastapi import FastAPI, UploadFile, File, Form
import shutil
import os
import pathlib
import logging
from dotenv import load_dotenv
from services.parse import parse_document
from fastapi.responses import JSONResponse
from services.extract_contact_info import extract_contact_info_from_resume
from database.db import SessionLocal
from database.models import Candidate, Referral, JobDescription
from sqlalchemy.exc import IntegrityError
from services.chunker import smart_resume_chunker
from services.summarize_resume import summarize_resume_sections
from datetime import datetime



# Load environment variables
load_dotenv(override=True)

JOB_DESCRIPTION_DIR = pathlib.Path(os.getenv("JOB_DESCRIPTION_DIR", "/app/data/job_description"))
RESUME_INPUT_PATH = pathlib.Path(os.getenv("RESUME_INPUT_PATH", "/app/data/resume"))
JOB_DESCRIPTION_OUTPUT_DIR = pathlib.Path(os.getenv("JOB_DESCRIPTION_OUTPUT_DIR", "/app/data/job_description_extractor"))
JOB_DESCRIPTION_DIR.mkdir(parents=True, exist_ok=True)
RESUME_INPUT_PATH.mkdir(parents=True, exist_ok=True)
RESUME_OUTPUT_PATH = pathlib.Path(os.getenv("RESUME_OUTPUT_PATH", "/app/data/resume_extractor"))
# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
app = FastAPI()

@app.post("/upload/resume")
async def upload_resume(file: UploadFile = File(...), position: str = Form(...)):
    try:
        # Save uploaded resume
        file_path = RESUME_INPUT_PATH / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logging.info(f"Resume saved to: {file_path}")

        # resume_text, parsed_md_path = parse_document(str(file_path), is_job_description=False)
        # logging.info(f"Parsed Markdown Path: {parsed_md_path}")

        # extracted_info = {}
        # summarize_resume = None
        # parsed_preview = ""

        # if parsed_md_path.exists():
        #     resume_text = parsed_md_path.read_text(encoding='utf-8')
        #     parsed_preview = resume_text[:500] + "..."
        #     extracted_info = extract_contact_info_from_resume(parsed_md_path)
        #     chunked_resume = smart_resume_chunker(resume_text)
        #     summarize_resume = summarize_resume_sections(chunked_resume)
        #     # summarize_resume = f"Dummy summary of"

        # else:
        #     logging.warning(f"Markdown file not found at: {parsed_md_path}")


        resume_text, parsed_md_path = parse_document(str(file_path), is_job_description=False)
        parsed_md_path = pathlib.Path(parsed_md_path)
        logging.info(f"Parsed Markdown Path: {parsed_md_path}")

        extracted_info = {}
        summarize_resume = None
        parsed_preview = ""

        if parsed_md_path.exists():
            parsed_preview = resume_text[:500] + "..."
            extracted_info = extract_contact_info_from_resume(parsed_md_path)
            chunked_resume = smart_resume_chunker(resume_text)
            summarize_resume = summarize_resume_sections(chunked_resume)
        else:
            logging.warning(f"Markdown file not found at: {parsed_md_path}")

        # Save to database
        db = SessionLocal()
        try:
            new_candidate = Candidate(
                name=extracted_info.get("name"),
                email=extracted_info.get("email"),
                phone=extracted_info.get("phone"),
                position=position.strip().lower(),
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
            "parsed_preview": parsed_preview,
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

        # Handle file upload
        if file:
            file_path = JOB_DESCRIPTION_DIR / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            file_path_str = str(file_path)
            logging.info(f"Job description file saved to: {file_path_str}")

            parsed_text = str(parse_document(str(file_path), is_job_description=True))

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
