import os
from pathlib import Path
from ollama_model import get_llm
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
from prompt_builder import prompt_resume


load_dotenv()

# resume_markdown = os.getenv("PDF_OUTPUT_PATH")
resume_markdown = "/home/binit/HR_system/resume_extractor/pdf_output_1.md"
job_description = "/home/binit/HR_system/job_description_extractor/job_output_1.md"
resume_text = Path(resume_markdown).read_text(encoding='utf-8')
job_description_text = Path(job_description).read_text(encoding='utf-8')



llm = get_llm(model_name="mistral:7b-instruct", temperature=0.0)


prompt = prompt_resume(resume_text, job_description_text)


response = llm.invoke(prompt)

print(response.content)



