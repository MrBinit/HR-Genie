import os
import pathlib
import logging
import pymupdf4llm
from dotenv import load_dotenv

load_dotenv(override=True)

RESUME_INPUT_PATH = os.getenv("PDF_INPUT_PATH")
RESUME_OUTPUT_PATH = os.getenv("PDF_OUTPUT_PATH")
JOB_DESCRIPTION_INPUT_PATH = os.getenv("JOB_DESCRIPTION_DIR")
JOB_DESCRIPTION_OUTPUT_DIR = os.getenv("JOB_DESCRIPTION_OUTPUT_DIR")
LOG_PATH = os.getenv("LOG_PATH", "app.log")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)

def get_next_filename(dir_path, base_name):
    """Find next available file name like base_name_1.md, base_name_2.md, etc."""
    dir_path = pathlib.Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    existing_files = list(dir_path.glob(f"{base_name}_*.md"))
    max_index = 0

    for file in existing_files:
        try:
            number = int(file.stem.split('_')[-1])
            max_index = max(max_index, number)
        except ValueError:
            continue

    return dir_path / f"{base_name}_{max_index + 1}.md"


def pdf_parse(document_path: str, is_job_description=False) -> str:
    """Parses the PDF and saves as markdown to the appropriate folder."""
    try:
        md_text = pymupdf4llm.to_markdown(document_path, ignore_images=True)

        if is_job_description:
            logging.info("Parsing job description PDF...")
            output_dir = JOB_DESCRIPTION_OUTPUT_DIR
            base_name = "job_output"
        else:
            logging.info("Parsing resume PDF...")
            output_dir = RESUME_OUTPUT_PATH
            base_name = "resume_output"

        output_path = get_next_filename(output_dir, base_name)
        output_path.write_bytes(md_text.encode())
        logging.info(f"PDF parsed and saved to {output_path}")
        return md_text
    except Exception as e:
        logging.error(f"Error parsing PDF: {e}")
        raise


def parse_document(document_path: str, is_job_description=False) -> str:
    """Parse the document (resume or job description)."""
    extension = pathlib.Path(document_path).suffix.lower()
    if extension != ".pdf":
        logging.error(f"Unsupported file format: {extension}")
        raise ValueError(f"Unsupported file format: {extension}")

    return pdf_parse(document_path, is_job_description=is_job_description)


if __name__ == "__main__":
    is_description = True

    # Select input path based on type
    if is_description:
        if not JOB_DESCRIPTION_INPUT_PATH:
            logging.error("JOB_DESCRIPTION_INPUT_PATH is not set in environment.")
            raise RuntimeError("Missing JOB_DESCRIPTION_INPUT_PATH in .env")
        input_path = JOB_DESCRIPTION_INPUT_PATH
    else:
        if not RESUME_INPUT_PATH:
            logging.error("PDF_INPUT_PATH (resume) is not set in environment.")
            raise RuntimeError("Missing PDF_INPUT_PATH in .env")
        input_path = RESUME_INPUT_PATH

    try:
        text = parse_document(input_path, is_job_description=is_description)
        print(text)
    except Exception as e:
        logging.error("Failed to process document: %s", e)
        raise
