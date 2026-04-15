from __future__ import annotations

import html as html_lib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from loguru import logger
from pydantic import ValidationError
import requests

# Используем модели и фильтры из parser_avito
PARSER_ROOT = Path(__file__).resolve().parents[2] / "parser_avito"
if str(PARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PARSER_ROOT))

from common_data import HEADERS  # type: ignore  # noqa: E402
from dto import AvitoConfig  # type: ignore  # noqa: E402
from filters.ads_filter import AdsFilter  # type: ignore  # noqa: E402
from models import ItemsResponse, Item  # type: ignore  # noqa: E402
from app.config import BACKEND_URL, INTERNAL_API_TOKEN, PROXY_BLOCK_COOLDOWN_SECONDS, REQUEST_TIMEOUT_SEC


class AvitoAdapter:
    def __init__(self) -> None:
        self._proxy_cooldown_until: dict[str, datetime] = {}

    @staticmethod
    def _normalize_proxy_url(proxy_url: str) -> str:
        raw = proxy_url.strip()
        if not raw:
            return raw

        if "://" in raw:
            return raw

        # Common proxy format from providers: host:port:username:password
        parts = raw.split(":")
        if len(parts) >= 4 and parts[1].isdigit():
            host = parts[0]
            port = parts[1]
            username = parts[2]
            password = ":".join(parts[3:])
            return f"http://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"

        # host:port without auth
        if len(parts) == 2 and parts[1].isdigit():
            return f"http://{raw}"

        # user:pass@host:port without explicit scheme
        if "@" in raw:
            return f"http://{raw}"

        return raw

    @staticmethod
    def _normalize_avito_url(url: str) -> str:
        raw = url.strip()
        if not raw:
            return raw

        try:
            parsed = urlsplit(raw)
        except Exception:
            return raw

        netloc = parsed.netloc or ""
        lower_netloc = netloc.lower()
        if lower_netloc == "m.avito.ru":
            replaced_netloc = "www.avito.ru"
        elif lower_netloc.startswith("m.avito.ru:"):
            replaced_netloc = "www.avito.ru" + netloc[len("m.avito.ru") :]
        else:
            return raw

        return urlunsplit((parsed.scheme, replaced_netloc, parsed.path, parsed.query, parsed.fragment))

    @staticmethod
    def _ensure_s104_query_param(url: str) -> str:
        raw = (url or "").strip()
        if not raw:
            return raw

        try:
            parsed = urlsplit(raw)
        except Exception:
            return raw

        query = parsed.query or ""
        if re.search(r"(^|&)s=", query):
            return raw

        new_query = f"{query}&s=104" if query else "s=104"
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))

    @staticmethod
    def find_json_on_page(html_code: str) -> dict[str, Any]:
        """Логика взята из parser_avito/parser_cls.py::find_json_on_page."""
        soup = BeautifulSoup(html_code, "html.parser")
        try:
            for script in soup.select("script"):
                if (
                    script.get("type") == "mime/invalid"
                    and script.get("data-mfe-state") == "true"
                    and "sandbox" not in script.text
                ):
                    data = json.loads(html_lib.unescape(script.text))
                    if data.get("i18n", {}).get("hasMessages", {}):
                        return data.get("state", {}).get("data", {})
        except Exception:
            return {}
        return {}

    @staticmethod
    def _to_utc(ms_timestamp: int | None) -> datetime | None:
        if not ms_timestamp:
            return None
        return datetime.fromtimestamp(ms_timestamp / 1000, tz=timezone.utc)

    @staticmethod
    def _backend_headers() -> dict[str, str]:
        return {
            "X-Internal-Token": INTERNAL_API_TOKEN,
            "Content-Type": "application/json",
        }

    def _is_proxy_cooling_down(self, proxy_url: str) -> bool:
        until = self._proxy_cooldown_until.get(proxy_url)
        if not until:
            return False
        now = datetime.now(timezone.utc)
        if now >= until:
            self._proxy_cooldown_until.pop(proxy_url, None)
            return False
        return True

    def _set_local_proxy_cooldown(self, proxy_url: str) -> None:
        cooldown_seconds = max(1, int(PROXY_BLOCK_COOLDOWN_SECONDS))
        self._proxy_cooldown_until[proxy_url] = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)

    def _report_blocked_proxy(self, proxy_url: str, status_code: int, source_url: str) -> None:
        payload = {
            "proxy_url": proxy_url,
            "status_code": status_code,
            "source_url": source_url,
        }
        endpoint = f"{BACKEND_URL}/api/v1/internal/proxies/blocked"
        try:
            response = requests.post(
                endpoint,
                headers=self._backend_headers(),
                json=payload,
                timeout=max(3, min(REQUEST_TIMEOUT_SEC, 10)),
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning(f"Failed to report blocked proxy={proxy_url}: {exc}")

    def _proxy_candidates(self, monitoring: dict[str, Any]) -> list[str]:
        raw_pool = monitoring.get("proxy_pool")
        candidates: list[str] = []

        if isinstance(raw_pool, list):
            for raw in raw_pool:
                if not isinstance(raw, str):
                    continue
                normalized = self._normalize_proxy_url(raw)
                if normalized and normalized not in candidates and not self._is_proxy_cooling_down(normalized):
                    candidates.append(normalized)

        raw_single = monitoring.get("proxy_url")
        if isinstance(raw_single, str):
            normalized_single = self._normalize_proxy_url(raw_single)
            if (
                normalized_single
                and normalized_single not in candidates
                and not self._is_proxy_cooling_down(normalized_single)
            ):
                candidates.insert(0, normalized_single)

        return candidates

    def _request_with_failover(self, url: str, monitoring: dict[str, Any]) -> requests.Response:
        candidates = self._proxy_candidates(monitoring)
        last_exc: Exception | None = None

        for idx, proxy in enumerate(candidates, start=1):
            proxy_label = f"{idx}/{len(candidates)}"
            proxies = {"http": proxy, "https": proxy}
            try:
                response = requests.get(url, headers=HEADERS, timeout=25, proxies=proxies)
                response.raise_for_status()
                if idx > 1:
                    logger.info(f"Recovered with fallback proxy {proxy_label} for url={url}")
                return response
            except requests.exceptions.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                last_exc = exc
                if status_code in {403, 429}:
                    self._set_local_proxy_cooldown(proxy)
                    self._report_blocked_proxy(proxy, status_code, url)
                    logger.warning(
                        f"Proxy {proxy_label} blocked for url={url}: status={status_code}. Switching to next proxy."
                    )
                    continue
                raise
            except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exc = exc
                logger.warning(f"Proxy {proxy_label} failed for url={url}: {exc}. Switching to next proxy.")
                continue
            except requests.exceptions.InvalidSchema as exc:
                last_exc = exc
                if "SOCKS support" in str(exc):
                    logger.warning(f"Proxy {proxy_label} has unsupported SOCKS schema: {exc}. Switching to next proxy.")
                    continue
                raise

        if not candidates:
            response = requests.get(url, headers=HEADERS, timeout=25)
            response.raise_for_status()
            return response

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"All proxies exhausted for url={url}")

    def parse_monitoring(self, monitoring: dict[str, Any]) -> list[dict[str, Any]]:
        url = self._normalize_avito_url(monitoring["url"])
        response = self._request_with_failover(url, monitoring)

        data = self.find_json_on_page(response.text)
        catalog = data.get("catalog") or {}

        try:
            parsed = ItemsResponse(**catalog)
        except ValidationError:
            return []

        ads: list[Item] = [ad for ad in parsed.items if ad.id]

        cfg = AvitoConfig(
            urls=[url],
            count=1,
            keys_word_white_list=monitoring.get("keywords_white") or [],
            keys_word_black_list=monitoring.get("keywords_black") or [],
            min_price=monitoring.get("min_price") if monitoring.get("min_price") is not None else 0,
            max_price=monitoring.get("max_price") if monitoring.get("max_price") is not None else 999_999_999,
            geo=monitoring.get("geo") or None,
            # Disable max-age filtering so we can detect price changes on old listings.
            max_age=0,
            ignore_reserv=True,
            ignore_promotion=False,
        )
        ads = AdsFilter(config=cfg, is_viewed_fn=None).apply(ads)

        result: list[dict[str, Any]] = []
        for ad in ads:
            ad_id = str(ad.id)
            ad_url_raw = f"https://www.avito.ru{ad.urlPath}" if ad.urlPath else url
            ad_url = self._ensure_s104_query_param(ad_url_raw)
            price = ad.priceDetailed.value if ad.priceDetailed and ad.priceDetailed.value is not None else None
            published_at = self._to_utc(ad.sortTimeStamp)

            location = None
            if ad.geo and ad.geo.formattedAddress:
                location = ad.geo.formattedAddress
            elif ad.addressDetailed and ad.addressDetailed.locationName:
                location = ad.addressDetailed.locationName

            result.append(
                {
                    "avito_ad_id": ad_id,
                    "title": ad.title or "Без названия",
                    "url": ad_url,
                    "price_rub": price,
                    "location": location,
                    "published_at": published_at.isoformat() if published_at else None,
                    "raw_json": ad.model_dump(mode="json"),
                }
            )
        return result
