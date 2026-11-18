from ecam_sync.config import Config
from ecam_sync.runner import run_sync


class Recorder:
    def __init__(self):
        self.calls = []

    def publish(self, state, **fields):
        self.calls.append((state, fields))


def test_unwritable_state_dir_reports_error_instead_of_crashing(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    cfg = Config(ics_url="https://example.test/x.ics", calendar_id="cal",
                 google_credentials_file=tmp_path / "key.json", state_dir=blocker / "sub")
    status = Recorder()
    assert run_sync(cfg, trigger="test", status=status) == 1
    assert status.calls[-1][0] == "error"
