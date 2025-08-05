def prompt_resume(resume_text: str, job_description: str) -> str:
    """
    Builds an instruction-style prompt comparing a candidate resume to a job description,
    and extracting structured details.
    """
    system = (
        "<s>[INST] <<SYS>>\n"
        "You are an expert HR/recruiting analyst. Given a candidate's resume and a job description,\n"
        "you will:\n"
        "\n"
        "1. Extract the following structured fields:\n"
        "   - work_experience_summary (string)\n"
        "   - previous_organizations (list of company names)\n"
        "\n"
        "2. Summarize the candidate's key strengths and skills.\n"
        "3. Summarize the core requirements from the job description.\n"
        "4. Assess fit: list matches (what aligns), gaps (missing or weak areas), and potential risks.\n"
        "5. Provide a fit_score out of 10 with a short justification.\n"
        "\n"
        "Respond strictly in valid JSON format with the following keys:\n"
        "full_name, email, work_experience_summary, previous_organizations, strengths, requirements,\n"
        "matches, gaps, risks, fit_score, justification, interview_questions\n"
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
