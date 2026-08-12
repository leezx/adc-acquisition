from adc_acquisition.checkpoint import CheckpointStore


def test_load_returns_default_when_missing(tmp_path):
    store = CheckpointStore("pubmed", tmp_path)
    checkpoint = store.load()
    assert checkpoint["job"] == "pubmed"
    assert checkpoint["records"] == {}
    assert checkpoint["last_success_max_date"] is None


def test_save_then_load_round_trips(tmp_path):
    store = CheckpointStore("pubmed", tmp_path)
    checkpoint = store.load()
    store.set_record_state(checkpoint, "123", "hash-abc", 1, "2020-01-01T00:00:00+00:00")
    checkpoint["last_success_max_date"] = "2020-01-01"
    store.save(checkpoint)

    reloaded = CheckpointStore("pubmed", tmp_path).load()
    assert reloaded["records"]["123"]["content_hash"] == "hash-abc"
    assert reloaded["records"]["123"]["version"] == 1
    assert reloaded["last_success_max_date"] == "2020-01-01"


def test_get_record_state_missing_returns_none(tmp_path):
    store = CheckpointStore("pubmed", tmp_path)
    checkpoint = store.load()
    assert store.get_record_state(checkpoint, "does-not-exist") is None


def test_set_record_state_overwrites_prior_version(tmp_path):
    store = CheckpointStore("pubmed", tmp_path)
    checkpoint = store.load()
    store.set_record_state(checkpoint, "123", "hash-v1", 1, "t1")
    store.set_record_state(checkpoint, "123", "hash-v2", 2, "t2")
    state = store.get_record_state(checkpoint, "123")
    assert state["version"] == 2
    assert state["content_hash"] == "hash-v2"


def test_set_record_state_stores_extra_metadata(tmp_path):
    store = CheckpointStore("ema", tmp_path)
    checkpoint = store.load()
    store.set_record_state(checkpoint, "doc-1", "hash-1", 1, "t1", extra={"last_updated_seen": "2020-01-01", "url_seen": "http://x"})
    state = store.get_record_state(checkpoint, "doc-1")
    assert state["last_updated_seen"] == "2020-01-01"
    assert state["url_seen"] == "http://x"
    assert state["content_hash"] == "hash-1"


def test_namespaces_isolate_state_for_the_same_id(tmp_path):
    """A metadata record and a derived artifact (e.g. its full text) sharing
    the same underlying id must not collide with each other's state."""
    store = CheckpointStore("europe_pmc", tmp_path)
    checkpoint = store.load()
    store.set_record_state(checkpoint, "same-id", "metadata-hash", 1, "t1", namespace="records")
    store.set_record_state(checkpoint, "same-id", "fulltext-hash", 1, "t1", namespace="fulltext_records")

    assert store.get_record_state(checkpoint, "same-id", namespace="records")["content_hash"] == "metadata-hash"
    assert store.get_record_state(checkpoint, "same-id", namespace="fulltext_records")["content_hash"] == "fulltext-hash"
    assert store.get_record_state(checkpoint, "same-id", namespace="records")["version"] == 1
