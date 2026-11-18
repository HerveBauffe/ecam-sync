"""Lien avec Home Assistant via MQTT.

Topics (préfixe configurable, « ecam_sync » par défaut) :
  <préfixe>/command       Home Assistant y publie « sync » pour lancer une synchronisation
  <préfixe>/status        JSON retenu : {"status": "running|ok|error", "message": ..., compteurs...}
  <préfixe>/availability  « online » / « offline » (testament MQTT) pour le démon d'écoute

Une panne MQTT ne doit jamais faire échouer la synchronisation elle-même.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import threading
from datetime import datetime
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .config import Config

log = logging.getLogger(__name__)


def _new_client(cfg: Config, client_id: str) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    if cfg.mqtt_user:
        client.username_pw_set(cfg.mqtt_user, cfg.mqtt_password)
    if cfg.mqtt_tls:
        client.tls_set()
    return client


class StatusPublisher:
    """Publie l'état de la synchro. Sans `client`, ouvre une connexion éphémère à chaque envoi."""

    def __init__(self, cfg: Config, client: mqtt.Client | None = None) -> None:
        self._cfg = cfg
        self._client = client

    def publish(self, state: str, **fields: Any) -> None:
        if not self._cfg.mqtt_host:
            return
        payload = json.dumps({"status": state, **fields}, ensure_ascii=False)
        try:
            if self._client is not None:
                info = self._client.publish(self._cfg.status_topic, payload, qos=1, retain=True)
                if info.rc != mqtt.MQTT_ERR_SUCCESS:  # broker momentanément injoignable : état perdu
                    log.warning("État « %s » non publié : %s", state, mqtt.error_string(info.rc))
            else:
                self._publish_once(payload)
        except Exception as exc:  # noqa: BLE001 - jamais bloquant
            log.warning("Publication MQTT impossible : %s", exc)

    def _publish_once(self, payload: str, topic: str | None = None, retain: bool = True) -> None:
        """Connexion éphémère ; lève une exception si le message n'est pas confirmé par le broker."""
        client = _new_client(self._cfg, f"ecam-sync-oneshot-{os.getpid()}")
        client.connect(self._cfg.mqtt_host, self._cfg.mqtt_port, keepalive=30)
        client.loop_start()
        try:
            info = client.publish(topic or self._cfg.status_topic, payload, qos=1, retain=retain)
            info.wait_for_publish(timeout=10)
            if not info.is_published():
                raise TimeoutError("message MQTT non confirmé par le broker (10 s)")
        finally:
            client.loop_stop()
            client.disconnect()


def listen(cfg: Config, on_sync: Callable[[StatusPublisher], None]) -> None:
    """Démon : attend « sync » sur le topic de commande puis appelle on_sync.

    La synchronisation tourne dans le thread principal ; paho gère le réseau (et les
    reconnexions) dans son propre thread, donc une longue synchro ne coupe pas la connexion.
    """
    if not cfg.mqtt_host:
        raise SystemExit("MQTT_HOST n'est pas configuré : rien à écouter.")

    requested = threading.Event()
    stop = threading.Event()
    client = _new_client(cfg, "ecam-sync-listener")
    client.will_set(cfg.availability_topic, "offline", qos=1, retain=True)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Connexion MQTT refusée : %s", reason_code)
            return
        log.info("Connecté au broker MQTT, en attente de commandes sur %s", cfg.command_topic)
        client.subscribe(cfg.command_topic, qos=1)
        client.publish(cfg.availability_topic, "online", qos=1, retain=True)

    def on_disconnect(client, userdata, flags, reason_code, properties):
        log.warning("Déconnecté du broker MQTT (%s), reconnexion automatique", reason_code)

    def on_message(client, userdata, message):
        if message.retain:  # on ignore les commandes « retenues » : elles rejoueraient à chaque redémarrage
            return
        if message.payload.decode("utf-8", "ignore").strip().lower() == "sync":
            log.info("Commande de synchronisation reçue")
            requested.set()

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    client.connect_async(cfg.mqtt_host, cfg.mqtt_port, keepalive=30)
    client.loop_start()
    publisher = StatusPublisher(cfg, client)
    try:
        while not stop.is_set():
            if requested.wait(timeout=1.0):
                requested.clear()
                on_sync(publisher)
    finally:
        try:  # broker injoignable à l'arrêt : le testament MQTT publiera « offline » à notre place
            client.publish(cfg.availability_topic, "offline", qos=1, retain=True).wait_for_publish(timeout=5)
        except (RuntimeError, ValueError) as exc:
            log.warning("« offline » non publié : %s", exc)
        client.disconnect()
        client.loop_stop()
