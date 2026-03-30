import os


BACKEND_URL = os.getenv("BACKEND_URL", "http://miniapp-backend:8000").rstrip("/")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "change_me_internal_token")
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "45"))
REQUEST_TIMEOUT_SEC = int(os.getenv("REQUEST_TIMEOUT_SEC", "35"))
