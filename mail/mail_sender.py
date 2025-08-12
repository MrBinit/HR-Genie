# mail/mail_sender.py
import os, base64, mimetypes
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from email import encoders
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

load_dotenv(override=True)

SENDER_EMAIL       = os.getenv("SENDER_EMAIL")
SENDER_NAME        = os.getenv("SENDER_NAME", "HR Team")
CLIENT_SECRET_PATH = os.getenv("CLIENT_SECRET_PATH", "/app/mail/credits.json")
TOKEN_PATH         = os.getenv("TOKEN_PATH", "/app/mail/token.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

def get_gmail_service():
    creds = None
    if TOKEN_PATH and os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Start OAuth flow
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            try:
                # Try to open a local server on a random free port.
                # NOTE: This must run on the machine with a browser.
                creds = flow.run_local_server(port=0, open_browser=True)
            except Exception as e:
                # Fallback: manual copy/paste flow via console
                print("run_local_server failed:", e)
                auth_url, _ = flow.authorization_url(
                    prompt="consent",
                    access_type="offline",
                    include_granted_scopes="true"
                )
                print("\n1) Visit this URL in your browser and authorize:")
                print(auth_url)
                code = input("\n2) Paste the authorization code here: ").strip()
                flow.fetch_token(code=code)
                creds = flow.credentials

        # Save token
        if TOKEN_PATH:
            os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

def send_email_html(to_email: str, subject: str, html_body: str,
                    attachment_path: str | None = None,
                    thread_id: str | None = None):
    msg = MIMEMultipart()
    msg["From"] = formataddr((SENDER_NAME, SENDER_EMAIL))
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(html_body or "", "html"))

    if attachment_path and os.path.exists(attachment_path):
        ctype, encoding = mimetypes.guess_type(attachment_path)
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        with open(attachment_path, "rb") as f:
            data = f.read()
        part = MIMEBase(maintype, subtype)
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(attachment_path)}"')
        msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    service = build("gmail", "v1", credentials=get_gmail_service()._http.credentials)
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    resp = service.users().messages().send(userId="me", body=body).execute()
    print("Sent. Gmail message id:", resp.get("id"))
    return resp
