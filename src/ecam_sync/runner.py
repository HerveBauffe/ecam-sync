"""Orchestration d'une exécution : verrou, téléchargement, synchro, état publié vers HA."""
from __future__ import annotations

import fcntl
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError

from .config import Config
from .gcal import CredentialsError, GoogleCalendar
from .mqtt import StatusPublisher
from .source import SourceError, download_ics, parse_events
from .sync import SafetyError, synchronize

log = logging.getLogger(__name__)


class AlreadyRunning(Exception):
    pass


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Empêche deux synchros simultanées (bouton pressé pendant la synchro hebdomadaire...)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AlreadyRunning from None
        yield


def run_sync(cfg: Config, *, trigger: str, status: StatusPublisher, dry_run: bool = False,
             force: bool = False, allow_empty: bool = False) -> int:
    """Exécute une synchronisation complète. Retourne 0 si tout va bien, 1 sinon."""
    tz = ZoneInfo(cfg.timezone)
    publish = (lambda *a, **k: None) if dry_run else status.publish

    try:
        with exclusive_lock(cfg.state_dir / "sync.lock"):
            publish("running", trigger=trigger, message="Synchronisation en cours…")
            try:
                window_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
                window_end = window_start + timedelta(days=cfg.horizon_days)

                data = download_ics(cfg.ics_url)
                events = parse_events(data, tz, window_start, window_end)
                log.info("%d événement(s) à venir dans la source", len(events))

                backend = GoogleCalendar(cfg.google_credentials_file, cfg.calendar_id)
                result = synchronize(
                    events, backend, window_start=window_start, window_end=window_end, timezone=cfg.timezone,
                    max_delete_fraction=cfg.max_delete_fraction, dry_run=dry_run,
                    force=force, allow_empty=allow_empty,
                )
            except (SourceError, SafetyError, CredentialsError) as exc:
                return _fail(publish, trigger, tz, str(exc))
            except HttpError as exc:
                return _fail(publish, trigger, tz, f"Erreur Google Calendar (HTTP {exc.resp.status})")
            except GoogleAuthError as exc:  # clé révoquée ou supprimée côté Google
                return _fail(publish, trigger, tz, f"Authentification Google refusée ({type(exc).__name__})")
            except OSError as exc:  # réseau coupé / délai dépassé pendant les appels à Google
                return _fail(publish, trigger, tz, f"Erreur système ou réseau : {type(exc).__name__}: {exc.strerror or exc}")
            except Exception as exc:  # noqa: BLE001
                log.exception("Erreur inattendue")
                return _fail(publish, trigger, tz, f"Erreur inattendue : {type(exc).__name__}")

            log.info("Terminé : %s", result.summary())
            publish(
                "error" if result.failed else "ok", trigger=trigger, message=result.summary(),
                created=result.created, updated=result.updated, deleted=result.deleted,
                unchanged=result.unchanged, failed=result.failed,
                finished_at=datetime.now(tz).isoformat(timespec="seconds"),
            )
            return 1 if result.failed else 0
    except AlreadyRunning:
        log.warning("Une synchronisation est déjà en cours, demande ignorée")
        return 2
    except OSError as exc:  # dossier d'état absent ou non inscriptible : ne doit pas faire planter le démon
        return _fail(publish, trigger, tz, f"Verrou impossible dans {cfg.state_dir} : {exc.strerror or exc}")


def _fail(publish, trigger: str, tz: ZoneInfo, message: str) -> int:
    log.error(message)
    publish("error", trigger=trigger, message=message,
            finished_at=datetime.now(tz).isoformat(timespec="seconds"))
    return 1
