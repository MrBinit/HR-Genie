# def prompt_resume(resume_text: str, job_description: str) -> str:
#     """
#     Builds an instruction-style prompt for evaluating a candidate's resume
#     against a job description. The evaluation is based on academic background,
#     project work, relevant work experience, and skills.
#     """

#     system = (
#         "You are a senior HR analyst. Your task is to evaluate the following resume "
#         "against the provided job description. Investigate the resume carefully and critically.\n\n"
#         "Focus your analysis on the following criteria:\n"
#         "1. Academic qualifications and performance\n"
#         "2. Projects (quality, relevance, complexity)\n"
#         "3. Work experience (roles, impact, relevance)\n"
#         "4. Skills and how well they match the job requirements\n\n"
#         "Provide a short and precise evaluation summary in 3–4 sentences.\n"
#         "End your response with a final score out of 10, based strictly on the criteria above.\n"
#         "Avoid unnecessary repetition or generic statements.\n"
#     )

#     user = (
#         "Candidate Resume:\n\n"
#         f"{resume_text}\n\n"
#         "Job Description:\n\n"
#         f"{job_description}\n\n"
#     )

#     return system + user


def prompt_resume(resume_text: str, job_description: str) -> str:
    """
    Builds a prompt to evaluate a candidate's resume against a job description.
    The model must return a structured JSON object with score, summary, and comparison.
    """

    system = (
        "You are a senior HR analyst. Your task is to critically evaluate the candidate's resume "
        "against the job description based on the following four criteria:\n"
        "1. Academic qualifications\n"
        "2. Projects (quality, relevance, complexity)\n"
        "3. Work experience (roles, impact, relevance)\n"
        "4. Skills and how well they match the job requirements\n\n"
        "Respond ONLY in JSON format with the following structure:\n\n"
        "{\n"
        "  \"score\": float (from 0 to 10),\n"
        "  \"summary\": \"Short 2–4 sentence evaluation summary.\",\n"
        "  \"comparison\": {\n"
        "    \"academics\": \"Short comment comparing academics to the JD\",\n"
        "    \"projects\": \"Comment on project relevance\",\n"
        "    \"experience\": \"Comment on work experience\",\n"
        "    \"skills\": \"Comment on skills matching\"\n"
        "  }\n"
        "}\n\n"
        "Do not include any text before or after the JSON."
    )

    user = (
        "Candidate Resume:\n\n"
        f"{resume_text}\n\n"
        "Job Description:\n\n"
        f"{job_description}\n\n"
    )

    return system + "\n\n" + user