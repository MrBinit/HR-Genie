import os, base64, mimetypes
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email import encoders

from dotenv import load_dotenv

load_dotenv(override=True)


SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_NAME  = os.getenv("SENDER_NAME", "HR Team")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")
CLIENT_SECRET_PATH = os.getenv("CLIENT_SECRET_PATH")
TOKEN_PATH = os.getenv("TOKEN_PATH")
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def send_email_html(to_email: str, subject: str, html_body: str, attachment_path: str = None):
    """Send an HTML email via Gmail API with optional file attachment."""
    msg = MIMEMultipart()
    msg["From"] = formataddr((SENDER_NAME, SENDER_EMAIL))
    msg["To"] = to_email
    msg["Subject"] = subject

    # HTML body
    msg.attach(MIMEText(html_body, "html"))

    # Add attachment
    if attachment_path and os.path.exists(attachment_path):
        content_type, encoding = mimetypes.guess_type(attachment_path)
        if content_type is None or encoding is not None:
            content_type = "application/octet-stream"
        main_type, sub_type = content_type.split("/", 1)

        with open(attachment_path, "rb") as f:
            file_data = f.read()

        part = MIMEBase(main_type, sub_type)
        part.set_payload(file_data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(attachment_path)}"')
        msg.attach(part)

    # Encode and send
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    service = get_gmail_service()
    try:
        resp = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        print("Sent. Gmail message id:", resp.get("id"))
    except HttpError as e:
        print("Gmail send failed:", e)