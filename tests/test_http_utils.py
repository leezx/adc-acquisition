import requests

from adc_acquisition import http_utils
from adc_acquisition.http_utils import RateLimiter, RetryConfig, RetryingClient


class FakeResponse:
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses_or_exceptions):
        self._queue = list(responses_or_exceptions)
        self.calls = 0

    def request(self, method, url, timeout=None, **kwargs):
        self.calls += 1
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _no_sleep(monkeypatch):
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: None)


def test_succeeds_first_try(monkeypatch):
    _no_sleep(monkeypatch)
    session = FakeSession([FakeResponse(200)])
    client = RetryingClient(RateLimiter(1000), session=session)
    response = client.get("http://example.test")
    assert response.status_code == 200
    assert session.calls == 1


def test_retries_on_retriable_status_then_succeeds(monkeypatch):
    _no_sleep(monkeypatch)
    session = FakeSession([FakeResponse(503), FakeResponse(200)])
    client = RetryingClient(RateLimiter(1000), retry_config=RetryConfig(max_attempts=3, base_delay_seconds=0.01), session=session)
    response = client.get("http://example.test")
    assert response.status_code == 200
    assert session.calls == 2


def test_gives_up_after_max_attempts_on_retriable_status(monkeypatch):
    _no_sleep(monkeypatch)
    session = FakeSession([FakeResponse(500), FakeResponse(500), FakeResponse(500)])
    client = RetryingClient(RateLimiter(1000), retry_config=RetryConfig(max_attempts=3, base_delay_seconds=0.01), session=session)
    response = client.get("http://example.test")
    assert response.status_code == 500
    assert session.calls == 3


def test_retries_on_network_exception_then_raises_after_max_attempts(monkeypatch):
    _no_sleep(monkeypatch)
    session = FakeSession([requests.ConnectionError("boom"), requests.ConnectionError("boom")])
    client = RetryingClient(RateLimiter(1000), retry_config=RetryConfig(max_attempts=2, base_delay_seconds=0.01), session=session)
    try:
        client.get("http://example.test")
        assert False, "expected RequestException to propagate"
    except requests.ConnectionError:
        pass
    assert session.calls == 2


def test_non_retriable_status_returned_immediately(monkeypatch):
    _no_sleep(monkeypatch)
    session = FakeSession([FakeResponse(404)])
    client = RetryingClient(RateLimiter(1000), session=session)
    response = client.get("http://example.test")
    assert response.status_code == 404
    assert session.calls == 1


def test_respects_retry_after_header(monkeypatch):
    _no_sleep(monkeypatch)
    sleeps = []
    monkeypatch.setattr(http_utils.time, "sleep", lambda seconds: sleeps.append(seconds))
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "2"}), FakeResponse(200)])
    client = RetryingClient(RateLimiter(1000), retry_config=RetryConfig(max_attempts=3, base_delay_seconds=0.01), session=session)
    client.get("http://example.test")
    assert 2.0 in sleeps


def test_rate_limiter_sleeps_between_calls(monkeypatch):
    calls = {"monotonic": [0.0, 0.0], "sleep_seconds": None}

    def fake_monotonic():
        return calls["monotonic"].pop(0) if calls["monotonic"] else 0.0

    monkeypatch.setattr(http_utils.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(http_utils.time, "sleep", lambda s: calls.__setitem__("sleep_seconds", s))

    limiter = RateLimiter(2.0)  # min interval 0.5s
    limiter.wait()
    limiter.wait()
    assert calls["sleep_seconds"] == 0.5
