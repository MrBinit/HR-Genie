from fastapi import FastAPI, UploadFile, File, Form
import shutil
import os
import pathlib
import logging
from dotenv import load_dotenv
from parse import parse_document 

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

# Initialize app
app = FastAPI()


@app.post("/upload/")
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form(...)
):
    """
    Uploads a file and parses it based on the type selected.
    file_type must be either: 'resume' or 'job_description'
    """

    # Choose directory based on type
    if file_type == "resume":
        upload_dir = RESUME_INPUT_PATH
        is_description = False
    elif file_type == "job_description":
        upload_dir = JOB_DESCRIPTION_DIR
        is_description = True
    else:
        return {"error": "Invalid file_type. Must be 'resume' or 'job_description'"}

    # Save the uploaded file with original filename
    file_path = upload_dir / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    logging.info(f"File saved to: {file_path}")

    # Parse the file
    try:
        parsed_text = parse_document(str(file_path), is_job_description=is_description)
        return {
            "message": "File uploaded and parsed successfully",
            "filename": file.filename,
            "file_type": file_type,
            "parsed_preview": parsed_text[:500] + "..." if parsed_text else "Empty"
        }
    except Exception as e:
        logging.error(f" Failed to parse file: {e}")
        return {"error": str(e)}
