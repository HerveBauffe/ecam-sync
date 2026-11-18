"""Téléchargement et lecture de l'ICS source."""
from __future__ import annotations

import http.client
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import recurring_ical_events
from icalendar import Calendar

from .transform import course_names, transform_texts

log = logging.getLogger(__name__)


class SourceError(Exception):
    """Problème de téléchargement ou de lecture de l'ICS (message sans données sensibles)."""


@dataclass(frozen=True)
class CalEvent:
    title: str
    description: str
    location: str
    start: datetime
    end: datetime


def download_ics(url: str, timeout: float = 30.0, max_bytes: int = 5_000_000) -> bytes:
    """Télécharge l'ICS. L'URL contient un jeton : elle n'apparaît jamais dans les erreurs."""
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise SourceError("ICS_URL doit commencer par http:// ou https://")
    request = urllib.request.Request(url, headers={"User-Agent": "ecam-sync/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise SourceError(f"Le serveur du calendrier a répondu HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(f"Téléchargement impossible : {getattr(exc, 'reason', exc)}") from None
    except http.client.HTTPException as exc:  # connexion coupée en cours de lecture, réponse malformée...
        raise SourceError(f"Téléchargement interrompu ({type(exc).__name__})") from None
    if len(data) > max_bytes:
        raise SourceError("Fichier ICS anormalement gros, abandon")
    if not data.removeprefix(b"\xef\xbb\xbf").lstrip().startswith(b"BEGIN:VCALENDAR"):  # BOM UTF-8 toléré
        raise SourceError("La réponse n'est pas un fichier ICS valide")
    return data


def parse_events(data: bytes, tz: ZoneInfo, window_start: datetime, window_end: datetime) -> list[CalEvent]:
    """Lit l'ICS, déplie les récurrences (RRULE), ne garde que la fenêtre demandée
    et applique les règles de transformation. Résultat trié et déterministe."""
    # Une source partiellement illisible doit faire échouer la synchro (et non supprimer
    # des événements dans Google) : on convertit donc toute erreur de lecture en SourceError.
    try:
        calendar = Calendar.from_ical(data)
        occurrences = list(recurring_ical_events.of(calendar, components=["VEVENT"]).between(window_start, window_end))
        # noms de cours lus sur tout le fichier (examens passés compris), pas seulement la fenêtre
        names = course_names(str(c.get("SUMMARY", "")) for c in calendar.walk("VEVENT"))
        return _convert(occurrences, tz, names)
    except SourceError:
        raise
    except Exception as exc:  # noqa: BLE001 - dépend de la version d'icalendar
        raise SourceError(f"ICS illisible ({type(exc).__name__})") from None


def _convert(occurrences, tz: ZoneInfo, names: dict[str, str]) -> list[CalEvent]:
    events: list[CalEvent] = []
    for component in occurrences:
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start, end = component.start, component.end
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            log.warning("Événement sur la journée entière ignoré : %s", component.get("SUMMARY", "?"))
            continue
        if start.tzinfo is None:  # heure « flottante » : on suppose l'heure locale
            start, end = start.replace(tzinfo=tz), end.replace(tzinfo=tz)
        title, description = transform_texts(str(component.get("SUMMARY", "")), str(component.get("DESCRIPTION", "")), names)
        events.append(
            CalEvent(
                title=title,
                description=description,
                location=str(component.get("LOCATION", "")).strip(),
                start=start.astimezone(tz),
                end=end.astimezone(tz),
            )
        )
    events.sort(key=lambda e: (e.start, e.end, e.title, e.description, e.location))
    return events
