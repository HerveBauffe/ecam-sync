"""Cœur de la synchronisation : calcul du plan (créer / modifier / supprimer) puis exécution.

Identité d'un événement
-----------------------
On ne sait pas si les UID de la source sont stables d'un téléchargement à l'autre. On
identifie donc un événement par son *contenu essentiel* : début + fin + titre (+ un
numéro d'ordre quand plusieurs événements identiques existent, par ex. deux groupes
au même créneau). Conséquences :
  * description ou local modifiés  -> l'événement Google est MIS À JOUR sur place ;
  * horaire ou titre modifiés      -> ancien événement supprimé, nouveau créé.

Garde-fous
----------
  * source vide alors que le calendrier contient des événements -> on refuse ;
  * suppression de plus de MAX_DELETE_FRACTION des événements   -> on refuse
    (--force pour passer outre), pour éviter de vider le calendrier à cause
    d'une source momentanément incomplète.
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from googleapiclient.errors import HttpError

from .gcal import KEY_PROP, CalendarBackend
from .source import CalEvent

log = logging.getLogger(__name__)

MIN_DELETIONS_BEFORE_GUARD = 10  # en dessous, on supprime sans se poser de question
WRITE_PAUSE_SECONDS = 0.1  # évite de saturer le quota d'écriture de l'API


class SafetyError(Exception):
    """Une suppression massive ou une source vide a été bloquée."""


@dataclass
class Plan:
    to_create: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # (libellé, corps)
    to_update: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)  # (libellé, id Google, patch)
    to_delete: list[tuple[str, str]] = field(default_factory=list)  # (libellé, id Google)
    unchanged: int = 0


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    failed: int = 0
    dry_run: bool = False

    def summary(self) -> str:
        text = (
            f"{self.created} ajouté(s), {self.updated} modifié(s), "
            f"{self.deleted} supprimé(s), {self.unchanged} inchangé(s)"
        )
        if self.failed:
            text += f", {self.failed} ÉCHEC(S)"
        return ("[simulation] " if self.dry_run else "") + text


def make_keys(events: list[CalEvent]) -> list[tuple[str, CalEvent]]:
    """Clé stable par événement. Les doublons exacts reçoivent un numéro d'ordre."""
    seen: Counter[str] = Counter()
    keyed = []
    for event in sorted(events, key=lambda e: (e.start, e.end, e.title, e.description, e.location)):
        base = f"{event.start.isoformat()}|{event.end.isoformat()}|{event.title}"
        index = seen[base]
        seen[base] += 1
        keyed.append((hashlib.sha256(f"{base}|{index}".encode()).hexdigest()[:40], event))
    return keyed


def build_body(event: CalEvent, key: str, timezone: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "summary": event.title,
        "description": event.description,
        "start": {"dateTime": event.start.isoformat(), "timeZone": timezone},
        "end": {"dateTime": event.end.isoformat(), "timeZone": timezone},
        "reminders": {"useDefault": False},  # aucune notification
        "extendedProperties": {"private": {KEY_PROP: key}},
    }
    if event.location:
        body["location"] = event.location
    return body


def _label(event: CalEvent) -> str:
    return f"{event.start:%Y-%m-%d %H:%M} {event.title}"


def make_plan(desired: list[tuple[str, CalEvent]], existing: list[dict[str, Any]], timezone: str) -> Plan:
    plan = Plan()
    wanted = dict(desired)
    by_key: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for item in existing:
        key = item["extendedProperties"]["private"][KEY_PROP]
        if key in by_key:
            duplicates.append(item)  # doublon créé par accident : on garde le premier
        else:
            by_key[key] = item

    for key, event in desired:
        current = by_key.get(key)
        if current is None:
            plan.to_create.append((_label(event), build_body(event, key, timezone)))
            continue
        patch: dict[str, Any] = {}
        if (current.get("description") or "").strip() != event.description.strip():
            patch["description"] = event.description  # "" efface le champ côté Google
        if (current.get("location") or "").strip() != event.location:
            patch["location"] = event.location
        if patch:
            plan.to_update.append((_label(event), current["id"], patch))
        else:
            plan.unchanged += 1

    for key, item in by_key.items():
        if key not in wanted:
            plan.to_delete.append((item.get("summary", "?"), item["id"]))
    plan.to_delete.extend((item.get("summary", "?"), item["id"]) for item in duplicates)
    return plan


def check_safety(plan: Plan, existing_count: int, desired_count: int, max_fraction: float,
                 force: bool, allow_empty: bool) -> None:
    if desired_count == 0 and existing_count > 0 and not (force or allow_empty):
        raise SafetyError(
            "La source ne contient aucun événement à venir alors que le calendrier Google en contient "
            f"{existing_count} : synchronisation refusée (--allow-empty pour forcer)."
        )
    limit = max(MIN_DELETIONS_BEFORE_GUARD, int(existing_count * max_fraction))
    if len(plan.to_delete) > limit and not force:
        raise SafetyError(
            f"{len(plan.to_delete)} suppressions sur {existing_count} événements : au-delà du seuil "
            f"de sécurité ({limit}). Vérifier la source, puis relancer avec --force si c'est voulu."
        )


def apply_plan(plan: Plan, backend: CalendarBackend, pause: float = WRITE_PAUSE_SECONDS) -> SyncResult:
    result = SyncResult(unchanged=plan.unchanged)

    def attempt(action: str, label: str, call) -> bool:
        try:
            call()
        except HttpError as exc:
            log.error("Échec (%s) %s : HTTP %s", action, label, exc.resp.status)
            result.failed += 1
            return False
        time.sleep(pause)
        log.info("%s : %s", action, label)
        return True

    for label, event_id in plan.to_delete:
        result.deleted += attempt("suppression", label, lambda i=event_id: backend.delete(i))
    for label, event_id, patch in plan.to_update:
        result.updated += attempt("modification", label, lambda i=event_id, p=patch: backend.patch(i, p))
    for label, body in plan.to_create:
        result.created += attempt("ajout", label, lambda b=body: backend.insert(b))
    return result


def synchronize(events: list[CalEvent], backend: CalendarBackend, *, window_start, window_end, timezone: str,
                max_delete_fraction: float, dry_run: bool = False, force: bool = False,
                allow_empty: bool = False) -> SyncResult:
    desired = make_keys(events)
    existing = backend.list_managed(window_start, window_end)
    plan = make_plan(desired, existing, timezone)
    check_safety(plan, len(existing), len(desired), max_delete_fraction, force, allow_empty)
    log.info("Plan : %d à ajouter, %d à modifier, %d à supprimer, %d inchangés",
             len(plan.to_create), len(plan.to_update), len(plan.to_delete), plan.unchanged)
    if dry_run:
        for label, _ in plan.to_create:
            log.info("[simulation] ajout : %s", label)
        for label, _, _ in plan.to_update:
            log.info("[simulation] modification : %s", label)
        for label, _ in plan.to_delete:
            log.info("[simulation] suppression : %s", label)
        return SyncResult(len(plan.to_create), len(plan.to_update), len(plan.to_delete), plan.unchanged, 0, True)
    return apply_plan(plan, backend)
