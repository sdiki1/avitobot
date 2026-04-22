import os
import re


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001").rstrip("/")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "change_me_internal_token")
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "45"))
REQUEST_TIMEOUT_SEC = int(os.getenv("REQUEST_TIMEOUT_SEC", "35"))

_db_proxy_cooldown_seconds_env = os.getenv("DB_PROXY_BLOCK_COOLDOWN_SECONDS")
_proxy_block_cooldown_seconds_env = os.getenv("PROXY_BLOCK_COOLDOWN_SECONDS")
_proxy_block_cooldown_minutes_env = os.getenv("PROXY_BLOCK_COOLDOWN_MINUTES")
if _db_proxy_cooldown_seconds_env is not None:
    DB_PROXY_BLOCK_COOLDOWN_SECONDS = max(1, int(_db_proxy_cooldown_seconds_env))
elif _proxy_block_cooldown_seconds_env is not None:
    DB_PROXY_BLOCK_COOLDOWN_SECONDS = max(1, int(_proxy_block_cooldown_seconds_env))
elif _proxy_block_cooldown_minutes_env is not None:
    DB_PROXY_BLOCK_COOLDOWN_SECONDS = max(1, int(_proxy_block_cooldown_minutes_env) * 60)
else:
    DB_PROXY_BLOCK_COOLDOWN_SECONDS = 1800

ENV_PROXY_BLOCK_COOLDOWN_SECONDS = max(1, int(os.getenv("ENV_PROXY_BLOCK_COOLDOWN_SECONDS", "2")))
PARSER_MAX_WORKERS = int(os.getenv("PARSER_MAX_WORKERS", "6"))


def _parse_proxy_list(raw_value: str | None) -> list[str]:
    proxies: list[str] = []
    for candidate in re.split(r"[,\n;]", raw_value or ""):
        cleaned = candidate.strip()
        if cleaned and cleaned not in proxies:
            proxies.append(cleaned)
    return proxies


PARSER_PROXY_LIST = _parse_proxy_list(os.getenv("PARSER_PROXY_LIST"))
