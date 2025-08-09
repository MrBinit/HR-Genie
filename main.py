from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
import shutil
import os
import pathlib
import logging
from dotenv import load_dotenv
from services.parse import parse_document
from fastapi.responses import JSONResponse
from services.extract_contact_info import extract_contact_info_from_resume
from database.db import SessionLocal
from database.models import Candidate, Referral, JobDescription, HiringManager, Employee, Department
from sqlalchemy.exc import IntegrityError
from services.chunker import smart_resume_chunker
from services.summarize_resume import summarize_resume_sections
from services.analyze_resume import evaluate_candidate
from decimal import Decimal, InvalidOperation
import json
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session
from mail.notify_manager import notify_manager_if_pass
from mail.mail_sender import send_email_html


# from mail.notify_manager import notify_manager_if_pass

# Load environment variables
load_dotenv(override=True)

JOB_DESCRIPTION_DIR = pathlib.Path(os.getenv("JOB_DESCRIPTION_DIR", "/app/data/job_description"))
RESUME_INPUT_PATH = pathlib.Path(os.getenv("RESUME_INPUT_PATH", "/app/data/resume"))
JOB_DESCRIPTION_OUTPUT_DIR = pathlib.Path(os.getenv("JOB_DESCRIPTION_OUTPUT_DIR", "/app/data/job_description_extractor"))
JOB_DESCRIPTION_DIR.mkdir(parents=True, exist_ok=True)
RESUME_INPUT_PATH.mkdir(parents=True, exist_ok=True)
RESUME_OUTPUT_PATH = pathlib.Path(os.getenv("RESUME_OUTPUT_PATH", "/app/data/resume_extractor"))
THRESHOLD = float(os.getenv("THRESHOLD", "6.0"))
# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
app = FastAPI()

@app.post("/upload/resume")
async def upload_resume(file: UploadFile = File(...),
                        position: str = Form(...),
                        department_name: str = Form(...)):
    try:
        # Save uploaded resume
        file_path = RESUME_INPUT_PATH / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logging.info(f"Resume saved to: {file_path}")

        resume_text, parsed_md_path = parse_document(str(file_path), is_job_description=False)
        parsed_md_path = pathlib.Path(parsed_md_path)
        logging.info(f"Parsed Markdown Path: {parsed_md_path}")

        extracted_info = {}
        summarize_resume = None
        # evaluation_summary = None
        parsed_preview = ""

        if parsed_md_path.exists():
            parsed_preview = resume_text[:500] + "..."
            extracted_info = extract_contact_info_from_resume(parsed_md_path)
            chunked_resume = smart_resume_chunker(resume_text)
            summarize_resume = summarize_resume_sections(chunked_resume)
        else:
            logging.warning(f"Markdown file not found at: {parsed_md_path}")

        # Save to database
        db = SessionLocal()

        department_name = department_name.strip().lower()

        # get the department from the database
        department = db.query(Department).filter(Department.name == department_name).first()
        if not department:
            db.close()
            return JSONResponse(status_code=404, content={"error": "Department not found."})

        # get the manager id
        manager = db.query(HiringManager).filter(HiringManager.department_id == department.id).first()
        if not manager:
            db.close()
            return JSONResponse(status_code=400, content={"error": f"No hiring manager assigned to department '{department_name}'."})

        job_description = db.query(JobDescription).filter(
            JobDescription.position == position.strip().lower()
        ).first()

        if not job_description:
            db.close()
            return JSONResponse(status_code=404, content={
                "error": f"No job description found for position '{position}' in department '{department_name}'."
            })

        try:
            new_candidate = Candidate(
                name=extracted_info.get("name"),
                email=extracted_info.get("email"),
                phone=extracted_info.get("phone"),
                position=position.strip().lower(),
                file_path=str(file_path),
                candidate_pitch=None,
                summary=summarize_resume,
                status="Received",
                department_id=department.id,
                manager_id=manager.id,
                job_description_id=job_description.id

            )
            db.add(new_candidate)
            db.commit()
            db.refresh(new_candidate)

            for ref in extracted_info.get("referrals", []):
                if ref["name"] and ref["email"]:
                    referral = Referral(
                        name=ref["name"],
                        internal_department=ref.get("internal_department", ""),
                        email=ref["email"],
                        candidate_id=new_candidate.id
                    )
                    db.add(referral)
            db.commit()

            # evaluate the candidate using LLM
            logging.info(f"Evaluating candidate with ID: {new_candidate.id}")

            raw_summary = evaluate_candidate(candidate_id=new_candidate.id)
            logging.info(f"Evaluation summary: {raw_summary}")

            try:
                result = json.loads(raw_summary)
                score = result.get("score")
                summary = result.get("summary")
            except Exception as e:
                logging.error(f"Failed to parse evaluation response: {e}")
                score = None
                summary = None

            candidate_to_update = db.merge(new_candidate)
            candidate_to_update.cv_score = score
            candidate_to_update.candidate_pitch = summary
            db.commit()

            notify_result = {"ok": True, "notified": False}
            if candidate_to_update.status == "Received" and (score is not None) and (score >= THRESHOLD):
                notify_result = notify_manager_if_pass(candidate_id=candidate_to_update.id)
                if notify_result.get("ok") and notify_result.get("notified") and notify_result.get("email_body"):
                    candidate_to_update.manager_email_body = notify_result["email_body"]  # <-- FIXED
                    db.commit()

        except IntegrityError:
            db.rollback()
            logging.warning("Candidate with this email already exists.")
        finally:
            db.close()


        return {
            "message": "Resume uploaded and processed successfully",
            "filename": file.filename,
            "parsed_preview": parsed_preview,
            "extracted_info": extracted_info,
            "score": score,
            "summary": summary,
            "notify": notify_result
        }

    except Exception as e:
        logging.error(f"Error uploading resume: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/upload/job-description")
async def upload_job_description(
    position: str = Form(...),
    description_text: str = Form(None),
    manager_email: str = Form(...),
    file: UploadFile = File(None)
):
    try:
        # Reject if both or neither are provided
        if (file and description_text) or (not file and not description_text):
            return JSONResponse(
                status_code=400,
                content={"error": "Provide either a job description file OR text — not both."}
            )

        db = SessionLocal()
        manager = db.query(HiringManager).filter(HiringManager.email == manager_email.strip().lower()).first()
        if not manager:
            return JSONResponse(status_code=404, content={"error": "Manager not found."})

        file_path_str = None
        parsed_text = None
        position_lower = position.strip().lower()

        # Handle file upload
        if file:
            file_path = JOB_DESCRIPTION_DIR / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            file_path_str = str(file_path)
            logging.info(f"Job description file saved to: {file_path_str}")

            parsed_text = str(parse_document(str(file_path), is_job_description=True))

        # Handle plain text input and save as Markdown
        elif description_text:
            md_filename = f"{position_lower.replace(' ', '_')}.md"
            file_path = JOB_DESCRIPTION_OUTPUT_DIR / md_filename
            file_path.write_text(description_text, encoding="utf-8")

            file_path_str = str(file_path)
            parsed_text = description_text
            logging.info(f"Job description text saved as markdown to: {file_path_str}")

        # Save to DB
        db = SessionLocal()
        try:
            jd = JobDescription(
                position=position_lower,
                description_text=parsed_text,
                file_path=file_path_str,
                manager_id=manager.id
            )
            db.add(jd)
            db.commit()
            db.refresh(jd)
        except IntegrityError:
            db.rollback()
            logging.error("Failed to insert job description due to integrity error.")
            return JSONResponse(status_code=400, content={"error": "Duplicate or invalid data."})
        except Exception as e:
            db.rollback()
            logging.error(f"Database error: {e}")
            return JSONResponse(status_code=500, content={"error": str(e)})
        finally:
            db.close()

        return {
            "message": "Job description uploaded and saved successfully",
            "position": position_lower,
            "manager": manager.name,
            "department": manager.department.name,
            "file_path": file_path_str,
            "parsed_preview": parsed_text[:500] + "..." if parsed_text else "Empty"
        }

    except Exception as e:
        logging.error(f"Error uploading job description: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/create-department")
def create_department(name: str = Form(...)):
    db = SessionLocal()
    try:
        name = name.strip().lower()

        existing = db.query(Department).filter(Department.name == name).first()
        if existing:
            return {"message": "Department already exists", "id": existing.id}

        # Generate new department ID
        last_dept = db.query(Department).order_by(Department.id.desc()).first()
        if last_dept:
            last_num = int(last_dept.id.replace("dept", ""))
            new_num = last_num + 1
        else:
            new_num = 1
        dept_id = f"dept{new_num:03d}"

        new_department = Department(id=dept_id, name=name)
        db.add(new_department)
        db.commit()
        db.refresh(new_department)

        return {
            "message": "Department created successfully",
            "id": new_department.id,
            "name": new_department.name
        }

    except Exception as e:
        db.rollback()
        logging.error(f"Error creating department: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        db.close()


@app.post("/register-manager")
def register_hiring_manager(
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(None),
    department_name: str = Form(...)
):
    db = SessionLocal()
    try:
        department_name = department_name.strip().lower()
        email = email.strip().lower()
        department = db.query(Department).filter(Department.name == department_name).first()
        if not department:
            return JSONResponse(status_code=404, content={"error": "Department not found. Please create it first."})

        # Generate unique hiring manager ID
        last_manager = db.query(HiringManager).order_by(HiringManager.id.desc()).first()
        if last_manager:
            last_num = int(last_manager.id.replace("bn", ""))
            new_num = last_num + 1
        else:
            new_num = 1
        new_id = f"bn{new_num:03d}"

        # Create new manager
        new_manager = HiringManager(
            id=new_id,
            name=name.strip(),
            email=email,
            phone=phone.strip() if phone else None,
            department_id=department.id
        )
        db.add(new_manager)
        db.commit()
        db.refresh(new_manager)

        return {
            "message": "Hiring Manager registered successfully",
            "manager_id": new_manager.id,
            "name": new_manager.name,
            "email": new_manager.email,
            "phone": new_manager.phone,
            "department": department.name
        }

    except IntegrityError:
        db.rollback()
        logging.error("Hiring Manager with this email already exists.")
        return JSONResponse(status_code=400, content={"error": "Hiring Manager with this email already exists."})
    except Exception as e:
        db.rollback()
        logging.error(f"Error registering hiring manager: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        db.close()



@app.post("/register-employee")
def register_employee(
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(None),
    position: str = Form(None),
    joining_date: str = Form(None),
    salary: str = Form(None),
    department_name: str = Form(None)
):
    db = SessionLocal()
    try:
        email = email.strip().lower()
        dept = None

        if department_name:
            department_name = department_name.strip().lower()
            dept = db.query(Department).filter(Department.name == department_name).first()
            if not dept:
                return JSONResponse(status_code=404, content={"error": "Department not found. Create it first."})

        # Generate employee id like "emp001"
        last_emp = db.query(Employee).order_by(Employee.id.desc()).first()
        if last_emp:
            try:
                last_num = int(last_emp.id.replace("emp", ""))
            except ValueError:
                last_num = 0
            new_num = last_num + 1
        else:
            new_num = 1
        emp_id = f"emp{new_num:03d}"

        # Parse date and salary
        dt = None
        if joining_date:
            try:
                dt = datetime.strptime(joining_date, "%Y-%m-%d").date()
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "joining_date must be YYYY-MM-DD"})

        sal = None
        if salary:
            try:
                sal = Decimal(salary)
            except InvalidOperation:
                return JSONResponse(status_code=400, content={"error": "salary must be a numeric string"})

        emp = Employee(
            id=emp_id,
            name=name.strip(),
            email=email,
            phone=phone.strip() if phone else None,
            position=position.strip() if position else None,
            joining_date=dt,
            salary=sal,
            department_id=dept.id if dept else None
        )
        db.add(emp)
        db.commit()
        db.refresh(emp)

        return {
            "message": "Employee registered successfully",
            "employee": {
                "id": emp.id, "name": emp.name, "email": emp.email, "phone": emp.phone,
                "position": emp.position,
                "joining_date": emp.joining_date.isoformat() if emp.joining_date else None,
                "salary": str(emp.salary) if emp.salary is not None else None,
                "department": dept.name if dept else None
            }
        }

    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=400, content={"error": "Employee with this email already exists."})
    except Exception as e:
        db.rollback()
        logging.exception("Error registering employee")
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        db.close()


@app.post("/referrals/internal")
def create_internal_referral_by_employee_email(
    employee_email: str = Form(...),
    candidate_email: str = Form(...),
    position: str = Form(...)
):
    db = SessionLocal()
    try:
        emp_email = employee_email.strip().lower()
        cand_email = candidate_email.strip().lower()
        pos = position.strip().lower()

        emp = (
            db.query(Employee)
              .options(joinedload(Employee.department))
              .filter(func.lower(Employee.email) == emp_email)
              .first()
        )
        if not emp:
            return JSONResponse(status_code=404, content={"error": f"Employee '{emp_email}' not found."})

        cand = (
            db.query(Candidate)
              .options(joinedload(Candidate.manager))
              .filter(
                  func.lower(Candidate.email) == cand_email,
                  func.lower(Candidate.position) == pos
              )
              .first()
        )
        if not cand:
            return JSONResponse(
                status_code=404,
                content={"error": f"Candidate not found for email '{cand_email}' and position '{pos}'."}
            )

        exists = (
            db.query(Referral)
              .filter(
                  Referral.candidate_id == cand.id,
                  func.lower(Referral.email) == func.lower(emp.email),
                  Referral.is_internal.is_(True)
              )
              .first()
        )
        if exists:
            return JSONResponse(
                status_code=400,
                content={"error": "This employee has already referred this candidate internally."}
            )

        dept_name = emp.department.name if getattr(emp, "department", None) else "Internal"

        already_internal = (
            db.query(Referral)
              .filter(Referral.candidate_id == cand.id, Referral.is_internal.is_(True))
              .count() > 0
        )

        ref = Referral(
            name=emp.name,
            email=emp.email,
            internal_department=dept_name,
            is_internal=True,
            candidate_id=cand.id,
            referrer_employee_id=emp.id
        )
        db.add(ref)

        # +1 only on the first internal referral and only if there is a score
        if not already_internal and cand.cv_score is not None:
            cand.cv_score = min(float(cand.cv_score) + 1.0, 10.0)  # optional cap

        cand.is_internal = True

        # Commit before notifying (notify uses a new Session)
        db.commit()
        db.refresh(ref)
        db.refresh(cand)

        notify_result = None

        # If newly eligible and still "Received", send the initial email
        if (not already_internal
            and cand.cv_score is not None
            and cand.status == "Received"
            and cand.cv_score >= THRESHOLD):
            notify_result = notify_manager_if_pass(candidate_id=cand.id)
            if notify_result.get("ok") and notify_result.get("notified") and notify_result.get("email_body"):
                cand.manager_email_body = notify_result["email_body"]
                db.commit()
                db.refresh(cand)  

        # If already forwarded earlier → send a follow-up about the internal referrer
        if cand.status == "Forwarded to Manager":
            if cand.manager and cand.manager.email:
                followup_subject = f"[Follow-up] Internal referral for {cand.name or 'Candidate'}"
                followup_html = f"""
                <p>Hi {cand.manager.name if cand.manager else 'Manager'},</p>
                <p>The candidate <b>{cand.name}</b> ({cand.position}) you received earlier now has an internal referral:</p>
                <ul>
                    <li><b>Name:</b> {emp.name}</li>
                    <li><b>Email:</b> {emp.email}</li>
                    <li><b>Department:</b> {dept_name}</li>
                </ul>
                <p>Regards,<br/>HR Automation</p>
                """
                send_email_html(
                    to_email=cand.manager.email,
                    subject=followup_subject,
                    html_body=followup_html
                )

        return {
            "message": "Internal referral recorded.",
            "candidate": {
                "id": cand.id,
                "name": cand.name,
                "cv_score": cand.cv_score,
                "status": cand.status
            },
            "referral": {
                "id": ref.id,
                "candidate_id": ref.candidate_id,
                "referral_type": "internal",
                "internal_department": ref.internal_department
            },
            "notify_result": notify_result
        }

    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=400, content={"error": "Duplicate or invalid data."})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        db.close()