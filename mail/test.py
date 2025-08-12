import datetime
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Paths to your files inside Docker
TOKEN_PATH = "/app/mail/token.json"
CREDENTIALS_PATH = "/app/mail/credits.json"

# Scopes: Gmail read/write + Google Calendar full access
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify"
]

def main():
    """Authenticate and create a Google Calendar meeting."""
    creds = None

    # Load token if it exists
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If no valid token, go through OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            # Use console flow (works in Docker, no GUI needed)
            creds = flow.run_local_server(port=0, open_browser=False)        # Save token
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    try:
        service = build("calendar", "v3", credentials=creds)

        # Meeting details
        start_time = datetime.datetime(2025, 8, 16, 15, 0)  # 3:00 PM
        end_time = datetime.datetime(2025, 8, 16, 16, 0)    # 4:00 PM
        timezone = "Asia/Kathmandu"

        event = {
            "summary": "HR System Interview Meeting",
            "description": "Interview meeting with B. Sapkota",
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": timezone,
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": timezone,
            },
            "attendees": [
                {"email": "b.sapkota.747@westcliff.edu"},
                {"email": "sapkotabinit2002@gmail.com"},
            ],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 30},
                    {"method": "popup", "minutes": 10},
                ],
            },
            "conferenceData": {
                "createRequest": {
                    "requestId": "hr-meeting-001",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        }

        event = service.events().insert(
            calendarId="primary",
            body=event,
            conferenceDataVersion=1
        ).execute()

        print(f"✅ Meeting created: {event.get('htmlLink')}")
        print(f"📅 Google Meet link: {event.get('hangoutLink')}")

    except HttpError as error:
        print(f"❌ An error occurred: {error}")

if __name__ == "__main__":
    main()
