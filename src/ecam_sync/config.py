"""Configuration.

Les réglages sont lus dans un fichier CLE=valeur (par défaut /etc/ecam-sync/ecam-sync.env,
lisible uniquement par l'utilisateur du service). Une variable d'environnement de même
nom a priorité sur le fichier (pratique pour les tests).

Les secrets (URL du calendrier, mot de passe MQTT) sont exclus du repr() pour ne
jamais finir dans les logs par accident.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_CONFIG_PATH = "/etc/ecam-sync/ecam-sync.env"


KNOWN_KEYS = (
    "ICS_URL", "GOOGLE_CALENDAR_ID", "GOOGLE_CREDENTIALS_FILE", "STATE_DIR", "TIMEZONE", "HORIZON_DAYS",
    "MAX_DELETE_FRACTION", "MQTT_HOST", "MQTT_PORT", "MQTT_USER", "MQTT_PASSWORD", "MQTT_TLS", "MQTT_PREFIX",
)


class ConfigError(Exception):
    """Configuration absente ou invalide."""


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")  # -sig : tolère un BOM (fichier édité sous Windows)
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Lecture impossible de {path} : {exc}") from None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"{path}:{number}: ligne invalide (attendu CLE=valeur)")
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Config:
    ics_url: str = field(repr=False)
    calendar_id: str
    google_credentials_file: Path
    state_dir: Path
    timezone: str = "Europe/Brussels"
    horizon_days: int = 800
    max_delete_fraction: float = 0.5
    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_user: str | None = None
    mqtt_password: str | None = field(default=None, repr=False)
    mqtt_tls: bool = False
    mqtt_prefix: str = "ecam_sync"

    @property
    def command_topic(self) -> str:
        return f"{self.mqtt_prefix}/command"

    @property
    def status_topic(self) -> str:
        return f"{self.mqtt_prefix}/status"

    @property
    def availability_topic(self) -> str:
        return f"{self.mqtt_prefix}/availability"


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(path: str | None = None) -> Config:
    config_path = Path(path or os.environ.get("ECAM_SYNC_CONFIG", DEFAULT_CONFIG_PATH))
    values: dict[str, str] = {}
    if config_path.exists():
        values = parse_env_file(config_path)
    elif path:  # un chemin explicitement demandé doit exister
        raise ConfigError(f"Fichier de configuration introuvable : {config_path}")
    values.update({k: os.environ[k] for k in KNOWN_KEYS if k in os.environ})

    required = ["ICS_URL", "GOOGLE_CALENDAR_ID", "GOOGLE_CREDENTIALS_FILE"]
    missing = [k for k in required if not values.get(k)]
    if missing:
        raise ConfigError(f"Réglages manquants : {', '.join(missing)} (fichier : {config_path})")

    try:
        cfg = Config(
            ics_url=values["ICS_URL"],
            calendar_id=values["GOOGLE_CALENDAR_ID"],
            google_credentials_file=Path(values["GOOGLE_CREDENTIALS_FILE"]),
            state_dir=Path(values.get("STATE_DIR") or os.environ.get("STATE_DIRECTORY") or "/var/lib/ecam-sync"),
            timezone=values.get("TIMEZONE", "Europe/Brussels"),
            horizon_days=int(values.get("HORIZON_DAYS", "800")),
            max_delete_fraction=float(values.get("MAX_DELETE_FRACTION", "0.5")),
            mqtt_host=values.get("MQTT_HOST") or None,
            mqtt_port=int(values.get("MQTT_PORT", "1883")),
            mqtt_user=values.get("MQTT_USER") or None,
            mqtt_password=values.get("MQTT_PASSWORD") or None,
            mqtt_tls=_as_bool(values.get("MQTT_TLS", "false")),
            mqtt_prefix=values.get("MQTT_PREFIX", "ecam_sync"),
        )
    except ValueError as exc:
        raise ConfigError(f"Valeur numérique invalide dans la configuration : {exc}") from None
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    """Refuse dès le démarrage les valeurs qui feraient échouer (ou planter le démon) plus tard."""
    try:
        ZoneInfo(cfg.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"TIMEZONE inconnu : {cfg.timezone!r} (ex. Europe/Brussels)") from None
    if cfg.horizon_days <= 0:
        raise ConfigError("HORIZON_DAYS doit être strictement positif")
    if not 0 < cfg.max_delete_fraction <= 1:
        raise ConfigError("MAX_DELETE_FRACTION doit être compris entre 0 (exclu) et 1")
    if not 0 < cfg.mqtt_port < 65536:
        raise ConfigError("MQTT_PORT invalide")
