import json
import os

import yaml

from scripts.export_openapi import schema


def test_openapi_yaml_matches_the_running_service():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "openapi.yaml")
    committed = yaml.safe_load(open(path))
    assert json.loads(json.dumps(committed)) == json.loads(json.dumps(schema())), "run: python scripts/export_openapi.py"
    assert committed["openapi"].startswith("3.1")
    assert all(p.startswith("/api/v1/") or p in ("/health", "/ready") for p in committed["paths"])
