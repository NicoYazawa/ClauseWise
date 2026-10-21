from pathlib import Path

import yaml


def test_data_services_are_authenticated_and_bound_to_loopback():
    config = yaml.safe_load((Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8"))
    services = config["services"]
    for name in ("mysql", "redis", "es", "api"):
        assert all(port.startswith("127.0.0.1:") for port in services[name]["ports"])
    es_env = services["es"]["environment"]
    assert "xpack.security.enabled=true" in es_env
    assert any(entry.startswith("ELASTIC_PASSWORD=${ES_PASSWORD:?") for entry in es_env)
    redis = services["redis"]
    assert "REDIS_PASSWORD" in str(redis["environment"])
    assert "--requirepass" in str(redis["command"])
    backend = config["x-backend-env"]
    assert backend["ES_USERNAME"] == "elastic"
    assert backend["ES_PASSWORD"].startswith("${ES_PASSWORD:?")
    assert backend["REDIS_PASSWORD"].startswith("${REDIS_PASSWORD:?")
