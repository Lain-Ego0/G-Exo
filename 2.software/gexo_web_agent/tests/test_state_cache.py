"""StateCache thread-safety and staleness tests."""
from __future__ import annotations

import threading
import time

from gexo_web_agent.schemas import Mode, StateData
from gexo_web_agent.state_cache import StateCache


def test_empty_cache_is_stale():
    c = StateCache(stale_timeout_s=1.0)
    assert c.get() is None
    assert c.is_stale()
    assert not c.has_state()
    assert c.age_s() is None


def test_update_then_fresh():
    c = StateCache(stale_timeout_s=1.0)
    c.update(StateData(mode=Mode.ASSIST, assist_ratio=0.6))
    assert not c.is_stale()
    st = c.get()
    assert st is not None and st.assist_ratio == 0.6
    assert c.last_update_ms() is not None


def test_becomes_stale_after_timeout():
    c = StateCache(stale_timeout_s=0.05)
    c.update(StateData())
    assert not c.is_stale()
    time.sleep(0.12)
    assert c.is_stale()
    # state itself is still readable (UI shows it greyed out)
    assert c.get() is not None


def test_snapshot_replaced_atomically():
    c = StateCache(stale_timeout_s=5.0)
    a = StateData(assist_ratio=0.3)
    b = StateData(assist_ratio=1.0)
    c.update(a)
    c.update(b)
    assert c.get() is b


def test_concurrent_read_write_hammer():
    c = StateCache(stale_timeout_s=5.0)
    stop = threading.Event()
    errors: list[Exception] = []

    def writer():
        i = 0
        while not stop.is_set():
            c.update(StateData(assist_ratio=0.3 + (i % 8) * 0.1))
            i += 1

    def reader():
        while not stop.is_set():
            st = c.get()
            if st is not None:
                try:
                    # a torn snapshot would blow up validation invariants
                    assert 0.29 <= st.assist_ratio <= 1.01
                except AssertionError as e:  # pragma: no cover
                    errors.append(e)
                    stop.set()

    threads = [threading.Thread(target=writer), *(threading.Thread(target=reader) for _ in range(3))]
    for t in threads:
        t.start()
    time.sleep(0.3)
    stop.set()
    for t in threads:
        t.join(timeout=2.0)
    assert not errors
