def prompt_resume(resume_text: str, job_description: str) -> str:
    """
    Builds an instruction-style prompt comparing a candidate resume to a job description.
    """
    system = (
        "<s>[INST] <<SYS>>\n"
        "You are an expert HR/recruiting analyst. Given a candidate's resume and a job description,\n"
        "you will:\n"
        "1. Summarize the candidate's key strengths and skills.\n"
        "2. Summarize the core requirements from the job description.\n"
        "3. Assess fit: list matches (what aligns), gaps (missing or weak areas), and potential risks.\n"
        "4. Give a fit score out of 10 with a short justification.\n"
        "5. Suggest three tailored interview questions to probe the gaps or clarify fit.\n"
        "Present the answer in clearly labeled sections with bullet points.\n"
        "<</SYS>>\n\n"
    )

    user = (
        "Candidate Resume:\n\n"
        f"{resume_text}\n\n"
        "Job Description:\n\n"
        f"{job_description}\n\n"
        "[/INST]"
    )
    return system + user
