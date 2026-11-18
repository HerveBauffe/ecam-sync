"""Ligne de commande : ecam-sync sync | listen | check."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import ConfigError, load_config
from .mqtt import StatusPublisher, listen
from .runner import run_sync
from .source import download_ics, parse_events


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ecam-sync", description=__doc__)
    parser.add_argument("--config", help="fichier de configuration (défaut : /etc/ecam-sync/ecam-sync.env)")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="lance une synchronisation maintenant")
    sync.add_argument("--dry-run", action="store_true", help="affiche ce qui serait fait, sans rien modifier")
    sync.add_argument("--force", action="store_true", help="ignore le garde-fou contre les suppressions massives")
    sync.add_argument("--allow-empty", action="store_true", help="accepte une source sans événement à venir")
    sync.add_argument("--trigger", default="manual", help="origine de l'exécution (timer, button, manual)")

    sub.add_parser("listen", help="démon : écoute les commandes MQTT de Home Assistant")
    sub.add_parser("check", help="vérifie la configuration (ICS, Google, MQTT) sans rien modifier")
    return parser


def _check(cfg) -> int:
    from .gcal import GoogleCalendar

    ok = True
    try:
        tz = ZoneInfo(cfg.timezone)
        # même fenêtre que la synchro (l'ancien « now.replace(year=+3) » plantait un 29 février)
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        events = parse_events(download_ics(cfg.ics_url), tz, start, start + timedelta(days=cfg.horizon_days))
        print(f"OK   ICS : téléchargé, {len(events)} événement(s) à venir")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"FAIL ICS : {exc}")
    try:
        GoogleCalendar(cfg.google_credentials_file, cfg.calendar_id).check_access()
        print("OK   Google Calendar : calendrier accessible en écriture")
    except Exception as exc:  # noqa: BLE001
        ok = False
        status = getattr(getattr(exc, "resp", None), "status", None)
        print(f"FAIL Google Calendar : {f'HTTP {status}' if status else exc}")
    if cfg.mqtt_host:
        try:
            # topic dédié et non retenu : le test ne perturbe pas le capteur de Home Assistant
            StatusPublisher(cfg)._publish_once("check", topic=f"{cfg.mqtt_prefix}/check", retain=False)  # noqa: SLF001
            print("OK   MQTT : connexion et publication réussies")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"FAIL MQTT : {exc}")
    else:
        print("--   MQTT : non configuré")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration : {exc}", file=sys.stderr)
        return 2

    if args.command == "check":
        return _check(cfg)
    if args.command == "sync":
        return run_sync(cfg, trigger=args.trigger, status=StatusPublisher(cfg), dry_run=args.dry_run,
                        force=args.force, allow_empty=args.allow_empty)
    # listen
    listen(cfg, lambda publisher: run_sync(cfg, trigger="button", status=publisher))
    return 0


if __name__ == "__main__":
    sys.exit(main())
