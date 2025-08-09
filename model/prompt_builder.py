def prompt_resume(
    resume_text: str,
    job_description: str,
    has_internal_referral: bool = False
) -> str:
    """
    Build a strict prompt for evaluating a candidate against a job description.
    - Forces JSON-only output
    - Summary must cover skills, projects, and work experience
    - Applies a small score nudge (+2) if there's a verified internal referral
    """
    referral_note = (
        "\nReferral bonus rule: This candidate has a VERIFIED INTERNAL REFERRAL. "
        "but only if their skills/experience are relevant to the job.\n"
        if has_internal_referral else ""
    )

    system = (
        "You are a senior HR analyst. Critically evaluate the candidate's resume against the job description.\n"
        "Today's date is 2025-08-09.\n"
        "Use ONLY the content provided below. Do NOT guess or add facts not present in the text.\n"
        "Scoring: 0.0–10.0 (one decimal). Clamp to this range. "
        "Be consistent and justify via the comparison fields.\n"
        + referral_note +
        "\nFocus on:\n"
        "1) Academic qualifications\n"
        "2) Projects (quality, relevance, complexity)\n"
        "3) Work experience (roles, impact, relevance)\n"
        "4) Skills match to the job requirements\n\n"
        "Return ONLY valid JSON with this exact schema (no extra text):\n"
        "{\n"
        '  "score": 0.0,\n'
        '  "summary": "2–4 sentences covering skills, projects, and work experience that match the JD.",\n'
        '  "comparison": {\n'
        '    "academics": "short, factual comparison to JD (or N/A)",\n'
        '    "projects": "short, factual comparison to JD (or N/A)",\n'
        '    "experience": "short, factual comparison to JD (or N/A)",\n'
        '    "skills": "short, factual comparison to JD (or N/A)"\n'
        "  }\n"
        "}\n"
        "Notes:\n"
        "- Keep the summary specific and factual; avoid fluff.\n"
        "- If information is missing, use 'N/A' for that field rather than inventing details.\n"
        "- Output must be JSON only—no markdown, no prose outside the JSON."
    )

    user = (
        "Job Description:\n\n"
        f"{job_description}\n\n"
        "Candidate Resume (summary/extracted text):\n\n"
        f"{resume_text}\n"
    )

    return system + "\n\n" + user

def prompt_resume_summary(section_name: str, section_text: str) -> str:
    """
    Builds a prompt for the LLM to summarize a specific section of a candidate's resume.
    Output must be short, use bullet points, and focus on key, relevant details.
    """
    system = (
        "You are a helpful HR assistant. Your task is to summarize a specific section "
        "of a candidate's resume in a short, clear way.\n"
        "Today's date is 2025-08-09.\n"
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
    referrals_list: list[dict] | None = None,
    internal_referrers: list[dict] | None = None,
    cv_attached: bool = True
) -> str:
    """
    Build a prompt for the LLM to generate a concise, professional HTML email to the manager.
    LLM must return ONLY valid minimal HTML (no <html>/<head>).
    Includes internal referrer details: name, department, email, phone.
    """
    # External/general referrals (non-employee) as bullets
    refs_text = ""
    if referrals_list:
        lines = []
        for r in referrals_list:
            nm = (r.get("name") or "Unknown").strip()
            em = (r.get("email") or "N/A").strip()
            co = (r.get("internal_department") or "N/A").strip()
            lines.append(f"- {nm} ({em}) — {co}")
        refs_text = "\n".join(lines)

    # Internal referrers (employees) with department/email/phone
    internal_text = ""
    if internal_referrers:
        lines = []
        for d in internal_referrers:
            nm  = (d.get("name") or "N/A").strip()
            dep = (d.get("department") or "N/A").strip()
            em  = (d.get("email") or "N/A").strip()
            ph  = (d.get("phone") or "N/A").strip()
            lines.append(f"- {nm} — {dep} (email: {em}, phone: {ph})")
        internal_text = "Internal Referrals:\n" + "\n".join(lines)

    attachment_note = "Note: The candidate's CV is attached for your review." if cv_attached else ""

    system = (
        "You are an HR assistant responsible for drafting concise, fact-based professional emails. "
        "Use ONLY the information provided below (summary and referral blocks). Do NOT guess or add details. "
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

{internal_text if internal_text else "Internal Referrals: None"}

External/General Referrals:
{refs_text or "None"}

Additional:
{attachment_note or "No attachments mentioned."}

Email requirements:
1) Start with a greeting to {manager_name}.
2) Provide a concise resume summary that clearly highlights:
   - Key skills relevant to the role,
   - Relevant work experience and impact,
   - 1–3 notable projects aligned with the job description.
3) If internal referrals exist, include a clearly labeled section listing each employee with: name, department, email, phone.
4) If external referrals exist, include them as a short bullet list.
5) Close with a clear CTA:
   - Ask whether we should move ahead with the resume or reject it.
   - If moving ahead, ask for the manager's preferred time window to schedule the meeting.
6) Keep tone direct, courteous, professional.

Return ONLY the HTML snippet — no plain text before or after.
"""
    return system + "\n\n" + user


def _llm_rejection_email(cand_name: str | None) -> str:
    """Generate a polite rejection email body with the LLM; fallback to a template if it fails."""
    llm = get_llm(model_name="gpt-oss:20b", temperature=0.1)
    prompt = f"""
Write a short, warm, professional rejection email in HTML to a job applicant named "{cand_name or 'Candidate'}".
Constraints:
- 4–6 short sentences, friendly and respectful.
- Say: we can’t move forward with the resume now.
- Encourage them to stay connected and wish them the best for the future.
- No company name (generic).
- End with: "With regards,<br/>HR-Team".
Return only the email body (HTML).
"""
    try:
        resp = llm.invoke(prompt)
        html = (resp.content or "").strip()
        return _wrap_html(html)
    except Exception as e:
        logging.warning(f"[auto_reject] LLM failed, using fallback: {e}")
        return _wrap_html(f"""
<p>Hi {cand_name or 'there'},</p>
<p>Thank you for your interest and for taking the time to apply. After careful review, we won’t be moving forward with your resume at this time.</p>
<p>Please stay connected for future opportunities, and we wish you the very best in your career ahead.</p>
<p>With regards,<br/>HR-Team</p>
""")

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
