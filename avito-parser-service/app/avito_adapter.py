from __future__ import annotations

import html as html_lib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

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


class AvitoAdapter:
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

    def parse_monitoring(self, monitoring: dict[str, Any]) -> list[dict[str, Any]]:
        url = monitoring["url"]
        proxy_url = monitoring.get("proxy_url")

        proxies = None
        if proxy_url:
            normalized_proxy = self._normalize_proxy_url(str(proxy_url))
            proxies = {"http": normalized_proxy, "https": normalized_proxy}

        try:
            response = requests.get(url, headers=HEADERS, timeout=25, proxies=proxies)
            response.raise_for_status()
        except requests.exceptions.ProxyError as exc:
            if not proxies:
                raise
            logger.warning(f"Proxy failed for url={url}: {exc}. Retrying without proxy.")
            response = requests.get(url, headers=HEADERS, timeout=25)
            response.raise_for_status()
        except requests.exceptions.InvalidSchema as exc:
            if not proxies or "SOCKS support" not in str(exc):
                raise
            logger.warning(f"SOCKS proxy is configured but dependencies are missing: {exc}. Retrying without proxy.")
            response = requests.get(url, headers=HEADERS, timeout=25)
            response.raise_for_status()

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
            ignore_reserv=True,
            ignore_promotion=False,
        )
        ads = AdsFilter(config=cfg, is_viewed_fn=None).apply(ads)

        result: list[dict[str, Any]] = []
        for ad in ads:
            ad_id = str(ad.id)
            ad_url = f"https://www.avito.ru{ad.urlPath}" if ad.urlPath else url
            price = ad.priceDetailed.value if ad.priceDetailed and ad.priceDetailed.value is not None else None

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
                    "published_at": self._to_utc(ad.sortTimeStamp),
                    "raw_json": ad.model_dump(mode="json"),
                }
            )
        return result
