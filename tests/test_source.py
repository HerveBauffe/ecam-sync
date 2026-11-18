from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ecam_sync.source import SourceError, download_ics, parse_events

TZ = ZoneInfo("Europe/Brussels")
SAMPLE = (Path(__file__).parent / "data" / "sample.ics").read_bytes()


def events(start="2026-10-14", end="2028-01-01"):
    return parse_events(SAMPLE, TZ, datetime.fromisoformat(start).replace(tzinfo=TZ),
                        datetime.fromisoformat(end).replace(tzinfo=TZ))


def test_past_events_are_excluded():
    assert all(e.start.year >= 2026 for e in events())
    assert len(events("2025-01-01", "2025-02-01")) == 1
    assert "Thermo" not in {e.title for e in events()}  # l'examen passé n'est pas repris...


def test_generic_titles_get_course_name_from_exams_of_the_whole_file():
    titles = {e.title for e in events()}  # ...mais il fournit le nom du cours
    assert "Thermo – théorie" in titles
    assert "ZZ9C – exercices" in titles  # aucun examen pour ce code : le code sert de préfixe


def test_recurrence_is_expanded_and_follows_dst():
    weekly = [e for e in events() if e.title == "Signals and systems"]
    assert [e.start.strftime("%Y-%m-%d %H:%M") for e in weekly] == [
        "2026-11-04 08:30", "2026-11-11 08:30", "2026-11-18 08:30"]


def test_partial_window_only_keeps_future_occurrences():
    weekly = [e for e in events("2026-11-10") if e.title == "Signals and systems"]
    assert len(weekly) == 2


def test_cancelled_and_all_day_are_skipped():
    titles = [e.title for e in events()]
    assert "Cours annulé" not in titles and "Congé" not in titles


def test_transformation_applied_and_location_optional():
    by_desc = {e.description: e for e in events() if e.title == "Projet atelier"}
    assert by_desc["Groupe:G2-s4\nEns:CCC"].location == ""
    assert by_desc["Groupe:G2-s5\nEns:DDD"].location == "2F12"


def test_result_is_sorted():
    result = events()
    assert result == sorted(result, key=lambda e: (e.start, e.end, e.title, e.description, e.location))


def test_garbage_is_rejected():
    with pytest.raises(SourceError):
        parse_events(b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:garbage\nEND:VEVENT\nEND:VCALENDAR\n", TZ,
                     datetime(2026, 1, 1, tzinfo=TZ), datetime(2027, 1, 1, tzinfo=TZ))


def test_download_refuses_non_http_scheme_without_leaking_url():
    with pytest.raises(SourceError) as exc:
        download_ics("file:///etc/passwd")
    assert "passwd" not in str(exc.value)


def test_utf8_bom_is_accepted(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return b"\xef\xbb\xbf" + SAMPLE

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response())
    data = download_ics("https://example.test/cal.ics")
    assert parse_events(data, TZ, datetime(2026, 10, 14, tzinfo=TZ), datetime(2028, 1, 1, tzinfo=TZ))


def test_interrupted_download_is_a_source_error(monkeypatch):
    import http.client

    def boom(*a, **k):
        raise http.client.IncompleteRead(b"BEGIN")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(SourceError) as exc:
        download_ics("https://example.test/secret-token")
    assert "secret" not in str(exc.value)
