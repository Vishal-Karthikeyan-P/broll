"""All settings come from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from functools import lru_cache


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return default if v is None or v == "" else v


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    v = _env(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in (_env(name, default) or "").split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    # paths
    data_dir: str = "./data"
    work_dir: str = ""      # derived: data_dir/work
    cache_dir: str = ""     # derived: data_dir/cache
    db_path: str = ""       # derived: data_dir/jobs.sqlite3
    # public URL used to build download links for local storage
    public_base_url: str = "http://localhost:8000"
    # storage
    storage_backend: str = "local"  # local | s3
    s3_endpoint: str = ""
    s3_public_endpoint: str = ""
    s3_bucket: str = "broll"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    # providers (all swappable by config)
    stt_provider: str = "mock"          # mock | faster_whisper
    whisper_model: str = "base"
    tts_provider: str = "espeak"        # espeak | mock
    planner_provider: str = "heuristic"  # heuristic | openai_compat
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    footage_providers: tuple = ("mock",)  # ordered: pexels,pixabay,mock
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    # limits
    max_audio_seconds: int = 600
    max_download_mb: int = 200
    max_workers: int = 2
    http_timeout: float = 20.0
    min_scene_seconds: float = 2.0
    max_scene_seconds: float = 8.0
    min_relevance: float = 1.8
    portrait_mode: str = "blur_fit"     # blur_fit | center_crop
    # security / demo protection
    api_token: str = ""
    rate_limit_per_minute: int = 60
    allow_private_urls: bool = False
    callback_secret: str = "change-me"
    # cost model (estimates, not billing)
    cost_per_llm_call_usd: float = 0.0
    cost_per_tts_char_usd: float = 0.0
    compute_cost_per_hour_usd: float = 0.10

    def derived(self) -> "Settings":
        return replace(
            self,
            work_dir=self.work_dir or os.path.join(self.data_dir, "work"),
            cache_dir=self.cache_dir or os.path.join(self.data_dir, "cache"),
            db_path=self.db_path or os.path.join(self.data_dir, "jobs.sqlite3"),
        )


def load_settings(**overrides) -> Settings:
    s = Settings(
        log_level=_env("LOG_LEVEL", "INFO"),
        data_dir=_env("DATA_DIR", "./data"),
        work_dir=_env("WORK_DIR", ""),
        cache_dir=_env("CACHE_DIR", ""),
        db_path=_env("DB_PATH", ""),
        public_base_url=_env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        storage_backend=_env("STORAGE_BACKEND", "local"),
        s3_endpoint=_env("S3_ENDPOINT", ""),
        s3_public_endpoint=_env("S3_PUBLIC_ENDPOINT", "") or _env("S3_ENDPOINT", ""),
        s3_bucket=_env("S3_BUCKET", "broll"),
        s3_access_key=_env("S3_ACCESS_KEY", ""),
        s3_secret_key=_env("S3_SECRET_KEY", ""),
        s3_region=_env("S3_REGION", "us-east-1"),
        stt_provider=_env("STT_PROVIDER", "mock"),
        whisper_model=_env("WHISPER_MODEL", "base"),
        tts_provider=_env("TTS_PROVIDER", "espeak"),
        planner_provider=_env("PLANNER_PROVIDER", "heuristic"),
        llm_base_url=_env("LLM_BASE_URL", ""),
        llm_api_key=_env("LLM_API_KEY", ""),
        llm_model=_env("LLM_MODEL", ""),
        footage_providers=tuple(_list("FOOTAGE_PROVIDERS", "mock")),
        pexels_api_key=_env("PEXELS_API_KEY", ""),
        pixabay_api_key=_env("PIXABAY_API_KEY", ""),
        max_audio_seconds=_int("MAX_AUDIO_SECONDS", 600),
        max_download_mb=_int("MAX_DOWNLOAD_MB", 200),
        max_workers=_int("MAX_WORKERS", 2),
        http_timeout=_float("HTTP_TIMEOUT", 20.0),
        min_scene_seconds=_float("MIN_SCENE_SECONDS", 2.0),
        max_scene_seconds=_float("MAX_SCENE_SECONDS", 8.0),
        min_relevance=_float("MIN_RELEVANCE", 1.8),
        portrait_mode=_env("PORTRAIT_MODE", "blur_fit"),
        api_token=_env("API_TOKEN", ""),
        rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 60),
        allow_private_urls=_bool("ALLOW_PRIVATE_URLS", False),
        callback_secret=_env("CALLBACK_SECRET", "change-me"),
        cost_per_llm_call_usd=_float("COST_PER_LLM_CALL_USD", 0.0),
        cost_per_tts_char_usd=_float("COST_PER_TTS_CHAR_USD", 0.0),
        compute_cost_per_hour_usd=_float("COMPUTE_COST_PER_HOUR_USD", 0.10),
    )
    valid = {f.name for f in fields(Settings)}
    bad = set(overrides) - valid
    if bad:
        raise ValueError(f"unknown settings: {bad}")
    return replace(s, **overrides).derived()


@lru_cache
def get_settings() -> Settings:
    return load_settings()
