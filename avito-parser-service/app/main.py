from __future__ import annotations

import time
from typing import Any

from loguru import logger
import requests

from app.avito_adapter import AvitoAdapter
from app.config import BACKEND_URL, INTERNAL_API_TOKEN, POLL_INTERVAL_SEC, REQUEST_TIMEOUT_SEC


def backend_headers() -> dict[str, str]:
    return {
        "X-Internal-Token": INTERNAL_API_TOKEN,
        "Content-Type": "application/json",
    }


def get_active_monitorings() -> list[dict[str, Any]]:
    url = f"{BACKEND_URL}/api/v1/internal/monitorings/active"
    response = requests.get(url, headers=backend_headers(), timeout=REQUEST_TIMEOUT_SEC)
    response.raise_for_status()
    return response.json()


def push_scan_result(monitoring_id: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    url = f"{BACKEND_URL}/api/v1/internal/monitorings/{monitoring_id}/scan-result"
    payload = {"items": items}
    response = requests.post(url, headers=backend_headers(), json=payload, timeout=REQUEST_TIMEOUT_SEC)
    response.raise_for_status()
    return response.json()


def main() -> None:
    logger.info("Avito parser worker started")
    adapter = AvitoAdapter()

    while True:
        cycle_started = time.time()
        try:
            monitorings = get_active_monitorings()
        except Exception as exc:
            logger.error(f"Failed to fetch monitorings from backend: {exc}")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        logger.info(f"Scan cycle started, monitorings={len(monitorings)}")

        for mon in monitorings:
            mon_id = mon["monitoring_id"]
            mon_url = mon["url"]
            try:
                items = adapter.parse_monitoring(mon)
                result = push_scan_result(mon_id, items)
                logger.info(
                    "monitoring={} url={} parsed={} created={} updated={} price_changes={}",
                    mon_id,
                    mon_url,
                    len(items),
                    result.get("created_items", 0),
                    result.get("updated_items", 0),
                    result.get("price_changes", 0),
                )
            except Exception as exc:
                logger.warning(f"monitoring={mon_id} url={mon_url} failed: {exc}")

        elapsed = int(time.time() - cycle_started)
        sleep_for = max(POLL_INTERVAL_SEC - elapsed, 5)
        logger.info(f"Cycle finished in {elapsed}s, sleeping {sleep_for}s")
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
