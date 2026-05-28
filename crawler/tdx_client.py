"""TDX API client for Taiwan High-Speed Rail data.

Free API registration: https://tdx.transportdata.tw
Documentation:        https://tdx.transportdata.tw/api-service/swagger/basic/
"""

import os
import time
import requests

_TDX_AUTH_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
_TDX_BASE_URL = "https://tdx.transportdata.tw/api/basic/v2/Rail/THSR"

_PRICE_URL = "https://www.thsrc.com.tw/tw/TicketAndExpress/TicketPrice"


class TDXClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._token_expires_at: float = 0

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        resp = requests.post(
            _TDX_AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._token

    def _get(self, path: str, params: dict | None = None) -> list | dict:
        token = self._ensure_token()
        url = f"{_TDX_BASE_URL}/{path.lstrip('/')}"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"$format": "JSON", **(params or {})},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Public methods ─────────────────────────────────────────────────────────

    def get_stations(self) -> list[dict]:
        """Return station list from TDX."""
        return self._get("Station")

    def get_timetable(self, train_date: str) -> list[dict]:
        """
        Return full timetable for a specific date.
        train_date format: YYYY-MM-DD
        """
        return self._get(f"DailyTimetable/TrainDate/{train_date}")

    def get_general_timetable(self) -> list[dict]:
        """Return the general (non-date-specific) timetable."""
        return self._get("GeneralTimetable")

    def get_od_fares(self) -> list[dict]:
        """Return OD (origin-destination) fare matrix from TDX."""
        return self._get("ODFare")


def scrape_prices_from_website() -> list[dict]:
    """
    Scrape ticket prices from THSR's official price table page.
    Returns a list of dicts: {start_name, end_name, standard, business}
    """
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(_PRICE_URL, headers=headers, timeout=20)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")

    prices: list[dict] = []
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            # Rows usually look like: [start, end, standard, business]
            if len(cols) >= 3:
                try:
                    std = int(cols[2].replace(",", ""))
                    biz = int(cols[3].replace(",", "")) if len(cols) > 3 else int(std * 1.65)
                    prices.append({
                        "start_name": cols[0],
                        "end_name": cols[1],
                        "standard": std,
                        "business": biz,
                    })
                except (ValueError, IndexError):
                    continue
    return prices
