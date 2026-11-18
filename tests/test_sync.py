from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ecam_sync.gcal import KEY_PROP
from ecam_sync.source import CalEvent
from ecam_sync.sync import SafetyError, make_keys, synchronize

TZ = ZoneInfo("Europe/Brussels")
WINDOW = datetime(2026, 10, 14, tzinfo=TZ)
WINDOW_END = datetime(2028, 12, 31, tzinfo=TZ)


class FakeCalendar:
    """Calendrier Google en mémoire."""

    def __init__(self):
        self.items, self.counter, self.manual = {}, 0, []

    def list_managed(self, time_min, time_max):
        return [dict(v) for v in self.items.values()]

    def insert(self, body):
        self.counter += 1
        self.items[f"id{self.counter}"] = {"id": f"id{self.counter}", **body}

    def patch(self, event_id, body):
        for k, v in body.items():
            if v is None:
                self.items[event_id].pop(k, None)
            else:
                self.items[event_id][k] = v

    def delete(self, event_id):
        del self.items[event_id]


def ev(day=20, hour=9, title="Cours", desc="Groupe:A", loc="2F10"):
    return CalEvent(title, desc, loc, datetime(2026, 10, day, hour, tzinfo=TZ), datetime(2026, 10, day, hour + 2, tzinfo=TZ))


def run(events, cal, **kw):
    return synchronize(events, cal, window_start=WINDOW, window_end=WINDOW_END, timezone="Europe/Brussels",
                       max_delete_fraction=0.5, **kw)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("ecam_sync.sync.WRITE_PAUSE_SECONDS", 0)
    monkeypatch.setattr("ecam_sync.sync.apply_plan.__defaults__", (0,))


def test_first_run_creates_everything_then_second_run_is_noop():
    cal, events = FakeCalendar(), [ev(20), ev(21), ev(22)]
    assert run(events, cal).created == 3
    again = run(events, cal)
    assert (again.created, again.updated, again.deleted, again.unchanged) == (0, 0, 0, 3)


def test_created_events_have_no_reminders_and_marker():
    cal = FakeCalendar()
    run([ev()], cal)
    body = next(iter(cal.items.values()))
    assert body["reminders"] == {"useDefault": False}
    assert KEY_PROP in body["extendedProperties"]["private"]
    assert body["start"]["timeZone"] == "Europe/Brussels"


def test_location_and_description_changes_update_in_place():
    cal = FakeCalendar()
    run([ev(loc="")], cal)
    event_id = next(iter(cal.items))
    result = run([ev(loc="2F12", desc="Groupe:A\nEns:XYZ")], cal)
    assert (result.created, result.updated, result.deleted) == (0, 1, 0)
    assert list(cal.items) == [event_id]  # même événement Google
    assert cal.items[event_id]["location"] == "2F12"


def test_location_removed_is_cleared():
    cal = FakeCalendar()
    run([ev(loc="2F12")], cal)
    result = run([ev(loc="")], cal)
    assert result.updated == 1
    assert not next(iter(cal.items.values())).get("location")  # "" efface le champ côté Google
    assert run([ev(loc="")], cal).unchanged == 1


def test_time_change_is_delete_plus_create():
    cal = FakeCalendar()
    run([ev(hour=9), ev(21)], cal)
    result = run([ev(hour=10), ev(21)], cal)
    assert (result.created, result.deleted, result.unchanged) == (1, 1, 1)


def test_event_removed_from_source_is_deleted():
    cal = FakeCalendar()
    run([ev(20), ev(21)], cal)
    assert run([ev(20)], cal).deleted == 1 and len(cal.items) == 1


def test_identical_slots_with_different_groups_are_both_kept():
    cal = FakeCalendar()
    events = [ev(desc="Groupe:A"), ev(desc="Groupe:B")]
    assert run(events, cal).created == 2
    assert run(events, cal).unchanged == 2


def test_unmanaged_events_are_never_touched():
    class Cal(FakeCalendar):
        def list_managed(self, time_min, time_max):  # le vrai backend filtre sur le marqueur
            return [dict(v) for v in self.items.values() if KEY_PROP in v.get("extendedProperties", {}).get("private", {})]

    cal = Cal()
    cal.items["manual"] = {"id": "manual", "summary": "Dentiste"}
    run([ev()], cal)
    run([], cal, allow_empty=True)
    assert "manual" in cal.items


def test_duplicate_google_events_are_cleaned():
    cal = FakeCalendar()
    run([ev()], cal)
    cal.items["dup"] = {**next(iter(cal.items.values())), "id": "dup"}
    assert run([ev()], cal).deleted == 1 and len(cal.items) == 1


def test_empty_source_is_refused():
    cal = FakeCalendar()
    run([ev(20), ev(21)], cal)
    with pytest.raises(SafetyError):
        run([], cal)
    assert len(cal.items) == 2


def test_mass_deletion_is_refused_unless_forced():
    cal = FakeCalendar()
    many = [ev(day=1 + i % 28, hour=7 + i // 28, title=f"C{i}") for i in range(40)]
    run(many, cal)
    with pytest.raises(SafetyError):
        run(many[:5], cal)
    assert run(many[:5], cal, force=True).deleted == 35


def test_dry_run_changes_nothing():
    cal = FakeCalendar()
    result = run([ev(20), ev(21)], cal, dry_run=True)
    assert result.created == 2 and result.dry_run and not cal.items


def test_keys_are_deterministic_and_order_independent():
    a, b = ev(desc="A"), ev(desc="B")
    assert make_keys([a, b]) == make_keys([b, a])


def test_sync_only_lists_google_events_inside_the_window():
    seen = {}

    class Cal(FakeCalendar):
        def list_managed(self, time_min, time_max):
            seen.update(time_min=time_min, time_max=time_max)
            return super().list_managed(time_min, time_max)

    run([ev()], Cal())
    assert seen == {"time_min": WINDOW, "time_max": WINDOW_END}
