"""Run this with your real keys to check the Pexels/Pixabay adapters against the live APIs.
   PEXELS_API_KEY=... PIXABAY_API_KEY=... python scripts/check_providers.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import load_settings
from app.pipeline.footage import PexelsProvider, PixabayProvider, ProviderError

s = load_settings()
for prov in (PexelsProvider(s.pexels_api_key, s.http_timeout), PixabayProvider(s.pixabay_api_key, s.http_timeout)):
    try:
        res = prov.search("data center server room", "landscape", 5)
        print(f"{prov.name}: {len(res)} results")
        for c in res[:3]:
            print("  ", c.id, c.title[:50], f"{c.width}x{c.height}", f"{c.duration}s", c.licence, c.page_url)
    except ProviderError as e:
        print(f"{prov.name}: FAILED - {e}")
