"""portwatch.cli through main(argv), with the catalogue and the Process API replaced."""
import logging
import types
from datetime import datetime

import dotenv
import pytest

from conftest import TINY_BBOX, UTC, FakeWorld, every_12_days
from portwatch import cli
from portwatch import copernicus as cop

REF_DATES = every_12_days(datetime(2026, 1, 1, 0, 34, 38, tzinfo=UTC), 6)
TARGETS = [datetime(2026, 4, 1, 0, 34, 38, tzinfo=UTC), datetime(2026, 4, 13, 0, 34, 38, tzinfo=UTC)]
TARGET0_ID = "S1A_IW_GRDH_1SDV_20260401T003438_107"

PORTS_YAML = """tiny:
  bbox: [-97.0, 27.80, -96.99, 27.81]
  notes: test
  reference: {from: "2026-01-01T00:00:00Z", to: "2026-03-15T00:00:00Z"}
"""


class Resp:
    def __init__(self, payload, ok=True, status=200):
        self.payload, self.ok, self.status_code, self.text = payload, ok, status, str(payload)

    def json(self):
        return self.payload


@pytest.fixture
def fake_run(monkeypatch, tmp_path):
    """cli.main(["run", ...]) against a FakeWorld; returns (world, argv)."""
    w = FakeWorld({107: (REF_DATES, TARGETS)})
    (tmp_path / "ports.yaml").write_text(PORTS_YAML)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)          # never read a .env in tests
    monkeypatch.setattr(cop.TokenSource, "from_env", classmethod(lambda cls: types.SimpleNamespace(get=lambda: "tok")))
    monkeypatch.setattr(cop, "search_s1", lambda bbox, since, **kw: w.search(bbox, since))
    monkeypatch.setattr(cop, "fetch_s1_raw", lambda scene, bbox, get_token: w.fetch(scene, bbox))
    argv = ["--ports-file", str(tmp_path / "ports.yaml"), "run", "--port", "tiny", "--days", "3650",
            "--data-dir", str(tmp_path / "data")]
    return w, argv


def run_log(tmp_path):
    path = tmp_path / "data" / "run.log"
    return path.read_text() if path.exists() else ""


def test_i3_unknown_port_exits_2_and_lists_the_ports(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["search", "--port", "nowhere"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "nowhere" in err
    for name in ("corpus_christi", "houston_ship_channel", "loop"):
        assert name in err


def test_i3_unknown_port_on_run_also_exits_2(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--port", "nowhere", "--days", "3"])
    assert e.value.code == 2 and "corpus_christi" in capsys.readouterr().err


def test_i3_catalogue_response_without_value_names_the_problem(monkeypatch, capsys):
    monkeypatch.setattr(cop, "search_s1", lambda bbox, since, **kw: cop.search(
        "SENTINEL-1", "IW_GRDH_1SDV", bbox, since, get=lambda *a, **k: Resp({"unexpected": 1})))
    with pytest.raises(SystemExit) as e:
        cli.main(["search", "--port", "loop", "--days", "5"])
    assert e.value.code not in (0, None)
    message = str(e.value.code) + capsys.readouterr().err
    assert message.strip() != "value" and "value" in message and "atalogue" in message


def test_i3_programming_errors_propagate_with_a_traceback(monkeypatch):
    def broken(bbox, since, **kw):
        raise KeyError("value")
    monkeypatch.setattr(cop, "search_s1", broken)
    with pytest.raises(KeyError):
        cli.main(["search", "--port", "loop", "--days", "5"])


def test_i3_copernicus_error_in_a_run_puts_the_traceback_in_run_log(fake_run, tmp_path):
    w, argv = fake_run

    def boom(scene, bbox):
        raise cop.CopernicusError("Process API request failed: HTTP 500")
    w.fetch = boom
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code not in (0, None)
    text = run_log(tmp_path)
    assert "Traceback" in text and "HTTP 500" in text


def test_i4_run_log_has_the_pass_summary_and_the_image_id(fake_run, tmp_path, capsys):
    w, argv = fake_run
    before = list(logging.getLogger("portwatch").handlers)
    cli.main(argv)
    text = run_log(tmp_path)
    assert "ship-like target(s)" in text
    assert f"20260401T003438Z {TARGET0_ID}" in text
    assert "ship-like target(s)" in capsys.readouterr().out         # and on stdout
    assert logging.getLogger("portwatch").handlers == before        # the run's handlers are removed again
