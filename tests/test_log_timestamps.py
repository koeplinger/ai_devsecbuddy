"""Both logs carry a local date/time + timezone stamp: the run-console log (each event gets a
``ts``) and the uvicorn server log (backend.log handlers get a tz-aware datefmt)."""
import json
import logging
import re
import tempfile

import pytest

from backend.service import LOG_TIMESTAMP_FORMAT, AssessmentService, log_timestamp

_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} (\S.*)$")   # "YYYY-MM-DD HH:MM:SS TZ"


def test_log_timestamp_has_date_time_and_timezone():
    m = _STAMP.match(log_timestamp())
    assert m, log_timestamp()
    assert m.group(1).strip()                    # a non-empty timezone token (e.g. EDT / UTC)


def test_run_log_events_are_timestamped():
    svc = AssessmentService(db_path=tempfile.mktemp(suffix=".db"), default_engine="mock")
    try:
        events = [json.loads(line) for line in svc.run_stream("tile-unguarded", "mock", None)]
    finally:
        svc.close()
    assert events and all("ts" in e for e in events)   # every run-log event is stamped
    assert _STAMP.match(events[0]["ts"])               # ...with the date/time + timezone


def test_install_timestamped_logging_adds_tz_stamp_to_uvicorn_log():
    pytest.importorskip("uvicorn")
    from backend.main import install_timestamped_logging

    added = []
    try:
        for name in ("uvicorn", "uvicorn.access"):
            lg = logging.getLogger(name)
            handler = logging.StreamHandler()
            lg.addHandler(handler)
            added.append((lg, handler))
        install_timestamped_logging()
        for lg, handler in added:
            assert handler.formatter is not None
            assert handler.formatter.datefmt == LOG_TIMESTAMP_FORMAT
            rec = logging.LogRecord(lg.name, logging.INFO, __file__, 1, "hello", (), None)
            asctime = handler.formatter.formatTime(rec, handler.formatter.datefmt)
            assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", asctime)
    finally:
        for lg, handler in added:
            lg.removeHandler(handler)
