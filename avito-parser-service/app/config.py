import os


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001").rstrip("/")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "change_me_internal_token")
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "45"))
REQUEST_TIMEOUT_SEC = int(os.getenv("REQUEST_TIMEOUT_SEC", "35"))
PROXY_BLOCK_COOLDOWN_MINUTES = int(os.getenv("PROXY_BLOCK_COOLDOWN_MINUTES", "30"))
PARSER_MAX_WORKERS = int(os.getenv("PARSER_MAX_WORKERS", "6"))
