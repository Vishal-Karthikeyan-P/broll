"""Write openapi.yaml from the running app's schema. Run: python scripts/export_openapi.py"""
import os
import sys

os.environ["BROLL_NO_AUTOSTART"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile

import yaml

from app.config import load_settings
from app.main import create_app


def schema():
    return create_app(load_settings(data_dir=tempfile.mkdtemp())).openapi()


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "openapi.yaml")
    with open(out, "w") as f:
        yaml.safe_dump(schema(), f, sort_keys=False)
    print("wrote", out)
