
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

def prompt_resume_section(section_name: str, section_text: str) -> str:
    """
    Builds a prompt for the LLM to summarize a specific section of a candidate's resume.
    Output must be short, use bullet points, and focus on key, relevant details.
    """
    system = (
        "You are a helpful HR assistant. Your task is to summarize a specific section "
        "of a candidate's resume in a short, clear way.\n"
        "Formatting rules:\n"
        "- Use concise bullet points (•) for each key detail.\n"
        "- Focus on concrete skills, achievements, and relevant facts.\n"
        "- Avoid unnecessary adjectives or filler language.\n"
        "- Return only the bullet points without extra commentary."
    )

    user = (
        f"Section name: {section_name}\n\n"
        f"Section text:\n{section_text}"
    )

    return system + "\n\n" + user


def prompt_manager_email(
    manager_name: str,
    cand_name: str,
    position: str,
    score: float,
    summary: str,
    referrals_list: list[dict] | None = None
) -> str:
    """
    Build a prompt for the LLM to generate a concise, professional HTML email to the manager.
    LLM must return ONLY valid minimal HTML (no <html>/<head>).
    """
    # Format referrals as bullet points
    refs_text = ""
    if referrals_list:
        lines = []
        for r in referrals_list:
            nm = (r.get("name") or "Unknown").strip()
            em = (r.get("email") or "N/A").strip()
            co = (r.get("company") or "N/A").strip()
            lines.append(f"- {nm} ({em}) — {co}")
        refs_text = "\n".join(lines)

    system = (
        "You are an HR assistant responsible for drafting concise, fact-based professional emails. "
        "Use ONLY the information provided in the candidate summary and referrals. "
        "Do NOT add or guess any missing details. "
        "Return ONLY valid minimal HTML (no <html> or <head> tags). "
        "Allowed tags: <div>, <p>, <ul>, <li>, <b>. "
        "No markdown. No extra commentary. Keep the email within 500 words."
    )

    user = f"""
Write an HTML email to the hiring manager about a candidate screening result.

Manager: {manager_name}
Candidate: {cand_name}
Role: {position}
Score: {score:.1f} / 10

Candidate Screening Summary (from evaluator):
---
{summary}
---

Referrals:
{refs_text or "None"}

The email must:
1. Start with a greeting to {manager_name}.
2. Give a concise but complete resume summary covering:
   - Key skills relevant to the role.
   - Relevant work experience and impact.
   - 1–3 most notable projects from the candidate that match the job description.
3. If referrals exist, list them clearly in a bullet list.
4. End with a call to action:
   - Ask if we should move ahead with the resume or reject it.
   - If moving ahead, request the manager's preferred time window for scheduling a meeting.

Return ONLY the HTML snippet — no plain text before or after.
"""
    return system + "\n\n" + user


def prompt_candidate_reply(text: str) -> str:
    return f"""
You are an assistant that analyzes a candidate's response about interview scheduling.

Candidate said:
\"\"\"{text}\"\"\"

Respond ONLY in JSON with:
- "intent": one of "accept", "reject", "propose_new_time"
- "proposed_time": optional, if intent is "propose_new_time"

Example:
{{"intent": "propose_new_time", "proposed_time": "2025-08-09T15:00:00+05:45"}}
"""
