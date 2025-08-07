import os
import pathlib
import logging
from dotenv import load_dotenv
from langchain_community.document_loaders import PDFPlumberLoader

load_dotenv(override=True)


RESUME_OUTPUT_PATH = os.getenv("RESUME_OUTPUT_PATH", "/app/data/resume_extractor")
JOB_DESCRIPTION_OUTPUT_DIR = os.getenv("JOB_DESCRIPTION_OUTPUT_DIR", "/app/data/job_description_extractor")

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

def pdf_parse(document_path: str, is_job_description=False) -> str:
    """Parses the PDF and saves as markdown-like plain text."""
    try:
        loader = PDFPlumberLoader(document_path)
        documents = loader.load()

        md_text = "\n".join(doc.page_content for doc in documents)

        if is_job_description:
            logging.info("Parsing job description PDF...")
            output_dir = JOB_DESCRIPTION_OUTPUT_DIR
        else:
            logging.info("Parsing resume PDF...")
            output_dir = RESUME_OUTPUT_PATH

        os.makedirs(output_dir, exist_ok=True)
        original_name = pathlib.Path(document_path).stem
        output_path = pathlib.Path(output_dir) / f"{original_name}.md"
        output_path.write_text(md_text, encoding='utf-8')
        logging.info(f"PDF parsed and saved to {output_path}")

        return md_text, str(output_path)
    except Exception as e:
        logging.error(f"Error parsing PDF: {e}")
        raise


def parse_document(document_path: str, is_job_description=False) -> str:
    extension = pathlib.Path(document_path).suffix.lower()
    if extension != ".pdf":
        logging.error(f"Unsupported file format: {extension}")
        raise ValueError(f"Unsupported file format: {extension}")

    return pdf_parse(document_path, is_job_description=is_job_description)

