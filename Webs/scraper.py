from loguru import logger
from curl_cffi import requests
from cloudscraper import create_scraper
from asyncio import to_thread
from json import JSONDecodeError
from curl_cffi.requests.exceptions import HTTPError, ConnectionError, Timeout
from asyncio.exceptions import CancelledError
from typing import Optional, Any


tor_proxies = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050",
}


class Scraper:
    __slots__ = ("scraper", "session", "headers", "tor")

    def __init__(self, headers: Optional[dict] = None, tor: bool = False):
        self.scraper = create_scraper(browser="chrome")
        
        self.session = requests.Session(impersonate="chrome124")
        
        self.headers = headers or {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124"}
        
        self.tor = tor

    def _internal_request(
        self, method: str, url: str, use_cs: bool, rjson: bool = False, **kwargs
    ) -> Optional[Any]:
        """Sync request handler with proper resource cleanup."""
       
        headers = self.headers.copy()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        
        kwargs["headers"] = headers

        if self.tor:
            kwargs["proxies"] = tor_proxies

        try:
            ex = self.scraper if use_cs else self.session
            response = ex.request(method, url, **kwargs)
            response.raise_for_status()
            
            return response.json() if rjson else response.text
                    
        except (JSONDecodeError, HTTPError, ConnectionError, Timeout) as e:
            logger.error(f"{type(e).__name__}: {e} → {url}")
            
        except Exception as e:
            logger.exception(f"Unexpected Scraper Error at {url}: {e}")
            
        return None

    async def _make_request(
        self, method: str, url: str, rjson: bool = False, cs: bool = False, **kwargs
    ) -> Optional[Any]:
        kwargs.setdefault("timeout", 80)

        try:
            return await to_thread(
                self._internal_request, method, url, cs, rjson, **kwargs
            )
        except CancelledError:
            logger.warning(f"Request cancelled: {url}")
            raise
        
        except Exception as e:
            logger.error(f"Thread error for {url}: {e}")
            return None

    async def get(self, url: str, rjson: bool = False, cs: bool = False, **kwargs):
        return await self._make_request("GET", url, rjson, cs, **kwargs)

    async def post(self, url: str, rjson: bool = False, cs: bool = False, **kwargs):
        return await self._make_request("POST", url, rjson, cs, **kwargs)

    def close(self) -> None:
        """Clean up sessions when done (recommended for long-running scripts)."""
        self.session.close()
        self.scraper.close()
