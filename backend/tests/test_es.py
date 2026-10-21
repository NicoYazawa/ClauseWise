"""Unit tests for the es layer: client factory / IK plugin probe / index management."""
from __future__ import annotations

from app.es import client as es_client
from app.es import indices
from tests import helpers


class TestEsClient:
    def test_get_client_ok(self, monkeypatch):
        created = {}

        class _FakeElasticsearch:
            def __init__(self, url, basic_auth=None, request_timeout=None):
                created.update(url=url, basic_auth=basic_auth, request_timeout=request_timeout)

            def ping(self):
                return True

        monkeypatch.setattr(es_client, "Elasticsearch", _FakeElasticsearch)
        monkeypatch.setattr(es_client.settings, "es_url", "http://es:9200")
        monkeypatch.setattr(es_client.settings, "es_username", "")
        es = es_client.get_es_client()
        assert isinstance(es, _FakeElasticsearch)
        assert created["url"] == "http://es:9200"
        assert created["basic_auth"] is None
        assert created["request_timeout"] == 10
        assert es_client.get_es_client() is es  # lru_cache hit

    def test_get_client_with_basic_auth(self, monkeypatch):
        seen = {}

        class _FakeElasticsearch:
            def __init__(self, url, basic_auth=None, request_timeout=None):
                seen["auth"] = basic_auth

            def ping(self):
                return True

        monkeypatch.setattr(es_client, "Elasticsearch", _FakeElasticsearch)
        monkeypatch.setattr(es_client.settings, "es_username", "elastic")
        monkeypatch.setattr(es_client.settings, "es_password", "pw")
        es_client.get_es_client()
        assert seen["auth"] == ("elastic", "pw")

    def test_get_client_ping_false(self, monkeypatch):
        class _FakeElasticsearch:
            def __init__(self, *a, **kw):
                pass

            def ping(self):
                return False

        monkeypatch.setattr(es_client, "Elasticsearch", _FakeElasticsearch)
        assert es_client.get_es_client() is None

    def test_get_client_exception(self, monkeypatch):
        class _FakeElasticsearch:
            def __init__(self, *a, **kw):
                raise OSError("no route")

        monkeypatch.setattr(es_client, "Elasticsearch", _FakeElasticsearch)
        assert es_client.get_es_client() is None

    def test_has_ik_plugin_no_es(self, monkeypatch):
        monkeypatch.setattr(es_client, "get_es_client", lambda: None)
        assert indices.has_ik_plugin() is False

    def test_has_ik_plugin_ok(self, monkeypatch):
        monkeypatch.setattr(es_client, "get_es_client", lambda: helpers.FakeES(ik_available=True))
        assert indices.has_ik_plugin() is True

    def test_has_ik_plugin_missing(self, monkeypatch):
        monkeypatch.setattr(es_client, "get_es_client", lambda: helpers.FakeES(ik_available=False))
        assert indices.has_ik_plugin() is False


class TestIndices:
    def test_index_constants(self):
        assert indices.INDEX_LEGAL == "legal_knowledge"
        assert indices.INDEX_TEMPLATE == "template_clause"
        assert indices.INDEX_CONTRACT == "contract_index"
        assert indices.INDEX_REPORT == "report_index"
        assert set(indices.VECTOR_INDICES) == {"legal_knowledge", "template_clause", "report_index"}

    def test_analyzer_settings_with_ik(self, monkeypatch):
        monkeypatch.setattr(indices, "has_ik_plugin", lambda: True)
        s = indices._analyzer_settings()
        assert s["analysis"]["analyzer"]["cn_index"]["tokenizer"] == "ik_max_word"
        assert indices._text_props()["analyzer"] == "cn_index"
        assert indices._text_props()["search_analyzer"] == "cn_search"

    def test_analyzer_settings_without_ik(self, monkeypatch):
        monkeypatch.setattr(indices, "has_ik_plugin", lambda: False)
        assert indices._analyzer_settings() == {}
        assert indices._text_props()["analyzer"] == "standard"

    def test_vector_mapping_dims(self, monkeypatch):
        monkeypatch.setattr(indices, "has_ik_plugin", lambda: False)
        monkeypatch.setattr(indices.settings, "embedding_dim", 768)
        m = indices._vector_mapping()
        assert m["properties"]["content_vector"]["dims"] == 768
        assert m["properties"]["content_vector"]["similarity"] == "cosine"

    def test_contract_mapping(self, monkeypatch):
        monkeypatch.setattr(indices, "has_ik_plugin", lambda: False)
        m = indices._contract_mapping()
        assert m["properties"]["contract_id"]["type"] == "long"
        assert "content_vector" not in m["properties"]

    def test_ensure_indices_no_es(self, monkeypatch):
        monkeypatch.setattr(indices, "get_es_client", lambda: None)
        assert indices.ensure_indices() is False

    def test_ensure_indices_creates_all(self, monkeypatch):
        monkeypatch.setattr(indices, "has_ik_plugin", lambda: False)
        es = helpers.FakeES(existing_indices=set())
        monkeypatch.setattr(indices, "get_es_client", lambda: es)
        assert indices.ensure_indices() is True
        created = {c["index"] for c in es.created}
        assert created == set(indices.VECTOR_INDICES) | {indices.INDEX_CONTRACT}
        assert es.created[0]["settings"]["number_of_shards"] == 1

    def test_ensure_indices_skips_existing(self, monkeypatch):
        monkeypatch.setattr(indices, "has_ik_plugin", lambda: True)
        es = helpers.FakeES(existing_indices=set(indices.VECTOR_INDICES) | {indices.INDEX_CONTRACT})
        monkeypatch.setattr(indices, "get_es_client", lambda: es)
        assert indices.ensure_indices() is True
        assert es.created == []

    def test_ensure_indices_with_ik_settings(self, monkeypatch):
        monkeypatch.setattr(indices, "has_ik_plugin", lambda: True)
        es = helpers.FakeES()
        monkeypatch.setattr(indices, "get_es_client", lambda: es)
        indices.ensure_indices()
        assert "analysis" in es.created[0]["settings"]

    def test_delete_indices(self, monkeypatch):
        es = helpers.FakeES(existing_indices=set(indices.VECTOR_INDICES) | {indices.INDEX_CONTRACT})
        monkeypatch.setattr(indices, "get_es_client", lambda: es)
        indices.delete_indices()
        assert len(es.deleted) == 4

    def test_delete_indices_no_es(self, monkeypatch):
        monkeypatch.setattr(indices, "get_es_client", lambda: None)
        indices.delete_indices()  # does not raise
