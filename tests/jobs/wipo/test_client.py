import responses

from adc_acquisition.http_utils import RateLimiter, RetryingClient
from jobs.wipo.client import OPS_AUTH_URL, OPS_SEARCH_URL, OPSClient, OPSThrottleError

BIBLIO_URL = "https://ops.epo.org/3.2/rest-services/published-data/publication/docdb/WO.2026163182.A1/biblio"


def _client(search_rate=1000, biblio_rate=1000):
    return OPSClient(
        search_client=RetryingClient(RateLimiter(search_rate)),
        biblio_client=RetryingClient(RateLimiter(biblio_rate)),
        consumer_key="key",
        consumer_secret="secret",
    )


def _mock_token(expires_in=1199):
    responses.add(responses.POST, OPS_AUTH_URL, json={"access_token": "tok-123", "expires_in": expires_in})


@responses.activate
def test_search_fetches_token_then_calls_search_with_bearer():
    _mock_token()
    responses.add(responses.GET, OPS_SEARCH_URL, body="<xml/>")

    result = _client().search("pn=WO", 1, 100)

    assert result == b"<xml/>"
    auth_call, search_call = responses.calls
    assert auth_call.request.headers["Authorization"].startswith("Basic ")
    assert search_call.request.headers["Authorization"] == "Bearer tok-123"
    assert search_call.request.params["Range"] == "1-100"


@responses.activate
def test_token_reused_across_calls_until_near_expiry():
    _mock_token(expires_in=1199)
    responses.add(responses.GET, OPS_SEARCH_URL, body="<xml/>")

    client = _client()
    client.search("pn=WO", 1, 100)
    client.search("pn=WO", 101, 200)

    auth_calls = [c for c in responses.calls if c.request.url == OPS_AUTH_URL]
    assert len(auth_calls) == 1


@responses.activate
def test_401_triggers_one_token_refresh_and_retry():
    _mock_token()
    responses.add(responses.GET, OPS_SEARCH_URL, status=401)
    responses.add(responses.GET, OPS_SEARCH_URL, body="<xml/>")

    result = _client().search("pn=WO", 1, 100)
    assert result == b"<xml/>"


@responses.activate
def test_biblio_404_returns_none_not_an_error():
    _mock_token()
    responses.add(responses.GET, BIBLIO_URL, status=404, body='<fault><code>SERVER.EntityNotFound</code></fault>')

    assert _client().fetch_biblio("WO.2026163182.A1") is None


@responses.activate
def test_biblio_success_returns_raw_bytes():
    _mock_token()
    responses.add(responses.GET, BIBLIO_URL, body=b"<xml>biblio</xml>")

    assert _client().fetch_biblio("WO.2026163182.A1") == b"<xml>biblio</xml>"


@responses.activate
def test_search_zero_results_returns_parseable_stub_not_an_error():
    """Live-verified (Job 15): OPS returns HTTP 404/SERVER.EntityNotFound
    for a query with genuinely zero hits, not an empty 200 -- must not
    crash the caller's discovery loop."""
    from adc_acquisition.ops_parser import parse_search_response

    _mock_token()
    responses.add(
        responses.GET, OPS_SEARCH_URL, status=404,
        body='<fault xmlns="http://ops.epo.org"><code>SERVER.EntityNotFound</code><message>No results found</message></fault>',
    )

    result = _client().search('pn=WO and (ti="Enhertu" or ab="Enhertu")', 1, 100)
    hits, total = parse_search_response(result)
    assert hits == []
    assert total == 0


@responses.activate
def test_search_throttle_403_retries_then_succeeds(monkeypatch):
    import adc_acquisition.ops_client as client_module
    monkeypatch.setattr(client_module.time, "sleep", lambda _s: None)

    _mock_token()
    responses.add(
        responses.GET, OPS_SEARCH_URL, status=403,
        headers={"x-rejection-reason": "ThrottlingControlQuota"},
    )
    responses.add(responses.GET, OPS_SEARCH_URL, body="<xml/>")

    result = _client().search("pn=WO", 1, 100)
    assert result == b"<xml/>"


@responses.activate
def test_search_throttle_403_gives_up_after_max_attempts(monkeypatch):
    import adc_acquisition.ops_client as client_module
    monkeypatch.setattr(client_module.time, "sleep", lambda _s: None)

    _mock_token()
    responses.add(
        responses.GET, OPS_SEARCH_URL, status=403,
        headers={"x-rejection-reason": "ThrottlingControlQuota"},
    )

    try:
        _client().search("pn=WO", 1, 100)
        raised = False
    except OPSThrottleError:
        raised = True
    assert raised


@responses.activate
def test_non_throttle_403_raises_immediately():
    _mock_token()
    responses.add(responses.GET, OPS_SEARCH_URL, status=403, body='<fault><code>CLIENT.Other</code></fault>')

    try:
        _client().search("pn=WO", 1, 100)
        raised = False
    except Exception:
        raised = True
    assert raised
