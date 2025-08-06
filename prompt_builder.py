def prompt_resume(resume_text: str, job_description: str) -> str:
    """
    Builds a simplified, instruction-style prompt for scoring a candidate
    based on their resume and the given job description, focusing on academics,
    extracurriculars, certifications, and job relevance.
    """
    system = (
        "\n"
        "You are an expert HR/recruiting analyst. Compare the candidate's resume and the job description.\n"
        "Evaluate the candidate based on the following:\n"
        "\n"
        "1. Academic background\n"
        "2. Extracurricular activities\n"
        "3. Certifications\n"
        "4. Relevance of skills and experience to the job\n"
        "\n"
        "Return a concise summary with your evaluation and a score out of 10 with justification.\n"
    )

    user = (
        "Candidate Resume:\n\n"
        f"{resume_text}\n\n"
        "Job Description:\n\n"
        f"{job_description}\n\n"
    )

    return system + user
