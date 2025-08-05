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
from models import Candidate
from sqlalchemy.exc import IntegrityError


# Load environment variables
load_dotenv(override=True)

JOB_DESCRIPTION_DIR = pathlib.Path(os.getenv("JOB_DESCRIPTION_DIR", "/app/job_description"))
RESUME_INPUT_PATH = pathlib.Path(os.getenv("PDF_INPUT_PATH", "/app/resume"))
JOB_DESCRIPTION_DIR.mkdir(parents=True, exist_ok=True)
RESUME_INPUT_PATH.mkdir(parents=True, exist_ok=True)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
app = FastAPI()

@app.post("/upload/")
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form(...)
):
    """
    Uploads a file and parses it based on the type selected.
    file_type must be either: 'resume' or 'jd'
    """
    try:
        if file_type == "resume":
            upload_dir = RESUME_INPUT_PATH
            is_job_description = False
        elif file_type == "jd":
            upload_dir = JOB_DESCRIPTION_DIR
            is_job_description = True
        else:
            return {"error": "Invalid file_type. Must be 'resume' or 'jd'"}

        # Save the uploaded file with original filename
        file_path = upload_dir / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logging.info(f"File saved to: {file_path}")

        local_base_path = "/home/binit/HR_system"
        relative_path = file_path.relative_to("/app")
        full_local_path = pathlib.Path(local_base_path) / relative_path



        # Parse the file
        parsed_text = parse_document(str(file_path), is_job_description=is_job_description)

        # Extract contact info if it's a resume
        extracted_info = {}
        if not is_job_description:
            parsed_md_path = pathlib.Path("/app/resume_extractor") / (file_path.stem + ".md")
            if parsed_md_path.exists():
                extracted_info = extract_contact_info_from_resume(parsed_md_path)
                db = SessionLocal()
                try:
                    new_candidate = Candidate(
                        name=extracted_info.get("name"),
                        email=extracted_info.get("email"),
                        phone=extracted_info.get("phone"),
                        file_path=str(full_local_path),
                        score=None,
                        summary=None,
                        status = "Received"
                    )
                    db.add(new_candidate)
                    db.commit()
                    db.refresh(new_candidate)
                    logging.info("Candidate saved to database.")
                except IntegrityError:
                    db.rollback()
                    logging.warning("Candidate with this email already exists.")
                except Exception as e:
                    db.rollback()
                    logging.error(f"Failed to insert candidate: {e}")
                finally:
                    db.close()
            else:
                logging.warning("Parsed markdown file not found for contact extraction.")


        return {
            "message": "File uploaded and parsed successfully",
            "filename": file.filename,
            "file_type": file_type,
            "parsed_preview": parsed_text[:500] + "..." if parsed_text else "Empty",
            "extracted_info": extracted_info
        }

    except Exception as e:
        logging.error(f"Error in upload endpoint: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
