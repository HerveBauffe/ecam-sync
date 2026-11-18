"""Accès à Google Calendar (compte de service, portée minimale).

Seuls les événements portant notre marqueur (extendedProperties.private.ecamSyncKey)
sont lus / modifiés / supprimés : un événement ajouté à la main dans le calendrier
n'est jamais touché.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
KEY_PROP = "ecamSyncKey"
RETRIES = 5


class CredentialsError(Exception):
    """Clé du compte de service absente ou illisible."""


class CalendarBackend(Protocol):
    """Ce dont sync.py a besoin (permet de tester avec un faux calendrier)."""

    def list_managed(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]: ...
    def insert(self, body: dict[str, Any]) -> None: ...
    def patch(self, event_id: str, body: dict[str, Any]) -> None: ...
    def delete(self, event_id: str) -> None: ...


class GoogleCalendar:
    def __init__(self, credentials_file: Path, calendar_id: str) -> None:
        try:
            credentials = service_account.Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
        except (OSError, ValueError) as exc:  # fichier absent / droits / JSON invalide
            raise CredentialsError(f"Clé Google illisible ({credentials_file}) : {type(exc).__name__}") from None
        self._events = build("calendar", "v3", credentials=credentials, cache_discovery=False).events()
        self._calendar_id = calendar_id

    def check_access(self) -> None:
        """Lève HttpError (404/403) si le calendrier n'est pas partagé avec le compte de service."""
        self._events.list(calendarId=self._calendar_id, maxResults=1).execute(num_retries=RETRIES)

    def list_managed(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        """Événements gérés qui chevauchent [time_min, time_max[ : même fenêtre que la source,
        sinon un événement hors fenêtre (ex. HORIZON_DAYS réduit) serait supprimé à tort."""
        managed: list[dict[str, Any]] = []
        page_token = None
        while True:
            response = self._events.list(
                calendarId=self._calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                showDeleted=False,
                maxResults=2500,
                pageToken=page_token,
                fields="nextPageToken,items(id,summary,description,location,extendedProperties)",
            ).execute(num_retries=RETRIES)
            for item in response.get("items", []):
                if KEY_PROP in item.get("extendedProperties", {}).get("private", {}):
                    managed.append(item)
            page_token = response.get("nextPageToken")
            if not page_token:
                return managed

    def insert(self, body: dict[str, Any]) -> None:
        self._events.insert(calendarId=self._calendar_id, body=body).execute(num_retries=RETRIES)

    def patch(self, event_id: str, body: dict[str, Any]) -> None:
        self._events.patch(calendarId=self._calendar_id, eventId=event_id, body=body).execute(num_retries=RETRIES)

    def delete(self, event_id: str) -> None:
        try:
            self._events.delete(calendarId=self._calendar_id, eventId=event_id).execute(num_retries=RETRIES)
        except HttpError as exc:
            if exc.resp.status not in (404, 410):  # déjà supprimé : pas un problème
                raise
