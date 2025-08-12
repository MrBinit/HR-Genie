import datetime
import logging
import os
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

# Paths inside Docker
TOKEN_PATH = "/app/mail/token.json"
CREDENTIALS_PATH = "/app/mail/credits.json"

# Scopes for Calendar + Gmail
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify"
]


def get_calendar_service():
    """Authenticate and return Google Calendar API service."""
    creds = None

    # Load token if available
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If not valid, refresh or create
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=False)
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def create_event_with_meet(
    summary: str,
    description: str,
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
    attendees: list,
    timezone: str = "Asia/Kathmandu",
    calendar_id: str = "primary"
):
    """
    Create a Google Calendar event with Meet link.
    Always returns a dict with keys: success, event_id, htmlLink, hangoutLink, error.
    """
    try:
        service = get_calendar_service()

        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
            "attendees": [{"email": email} for email in attendees],
            "conferenceData": {
                "createRequest": {
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    "requestId": f"meet-{int(datetime.datetime.now().timestamp())}"
                }
            }
        }

        event = service.events().insert(
            calendarId=calendar_id,
            body=event,
            conferenceDataVersion=1
        ).execute()

        logging.info(f"Event created: {event.get('htmlLink')}")

        return {
            "success": True,
            "event_id": event.get("id"),
            "htmlLink": event.get("htmlLink"),
            "hangoutLink": event.get("hangoutLink"),
            "error": None
        }

    except HttpError as error:
        logging.exception("Google API returned an error")
        return {
            "success": False,
            "event_id": None,
            "htmlLink": None,
            "hangoutLink": None,
            "error": str(error)
        }

    except Exception as e:
        logging.exception("Failed to create Google Calendar event")
        return {
            "success": False,
            "event_id": None,
            "htmlLink": None,
            "hangoutLink": None,
            "error": str(e)
        }
