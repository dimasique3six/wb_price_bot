"""
Клиент для получения цен с Wildberries.
Поддерживает x-pow (Proof of Work) защиту WB.
"""

import asyncio
import hashlib
import logging
import struct
import time
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

WB_CARD_URL = (
    "https://card.wb.ru/cards/v2/detail"
    "?appType=1&curr=rub&dest=-1257786&spp=30&nm={article_id}"
)
WB_CARD_URL_V1 = (
    "https://card.wb.ru/cards/v1/detail"
    "?appType=1&curr=rub&dest=-1257786&spp=30&nm={article_id}"
)

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Origin": "https://www.wildberries.ru",
    "Referer": "https://www.wildberries.ru/",
}


# --- Proof of Work -----------------------------------------------------------

def _solve_pow(challenge_str: str) -> Optional[str]:
    """
    Решает x-pow challenge от WB.
    challenge_str вида: "6,8,1,<prefix>,<uuid1>,<uuid2>,<ts>,1,<sig>,<extra>"

    Алгоритм: ищем nonce такой, что
      SHA256(prefix_bytes + nonce_le64) имеет >= difficulty ведущих нулевых бит.
    Возвращает строку для заголовка x-pow или None при неудаче.
    """
    try:
        parts = challenge_str.strip().split(",")
        # parts[0] = version
        # parts[1] = difficulty (число нулевых бит)
        # parts[2] = algo (1 = SHA256)
        # parts[3] = prefix hex
        # parts[4] = uuid1
        # parts[5] = uuid2
        # parts[6] = timestamp
        # parts[7] = flag
        # parts[8] = signature base64
        # parts[9] = extra hex

        difficulty   = int(parts[1])
        prefix_hex   = parts[3]
        uuid1        = parts[4]
        uuid2        = parts[5]
        timestamp    = parts[6]
        flag         = parts[7]
        signature    = parts[8]
        extra_hex    = parts[9] if len(parts) > 9 else ""

        # WB иногда даёт нечётный hex — дополняем до чётной длины
        if len(prefix_hex) % 2:
            prefix_hex = "0" + prefix_hex
        prefix_bytes = bytes.fromhex(prefix_hex) if prefix_hex else b""
        full_bytes   = difficulty // 8
        rem_bits     = difficulty % 8

        logger.debug(f"Solving PoW: difficulty={difficulty}, prefix={prefix_hex[:16]}...")
        start = time.time()

        for nonce in range(10_000_000):
            nonce_bytes = struct.pack("<Q", nonce)
            digest      = hashlib.sha256(prefix_bytes + nonce_bytes).digest()

            # Проверяем ведущие нули
            if digest[:full_bytes] != b"\x00" * full_bytes:
                continue
            if rem_bits and (digest[full_bytes] >> (8 - rem_bits)) != 0:
                continue

            elapsed   = time.time() - start
            nonce_hex = nonce_bytes.hex()
            solution  = (
                f"6,{difficulty},1,{prefix_hex},{uuid1},{uuid2},"
                f"{timestamp},{flag},{signature},{extra_hex},{nonce_hex}"
            )
            logger.info(f"PoW solved: nonce={nonce}, time={elapsed:.2f}s")
            return solution

        logger.warning("PoW: exceeded max attempts")
        return None

    except Exception as e:
        logger.error(f"PoW solve error: {e}")
        return None


async def _solve_pow_async(challenge_str: str) -> Optional[str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _solve_pow, challenge_str)


# --- API Client --------------------------------------------------------------

class WildberriesAPI:
    def __init__(self, proxy: Optional[str] = None):
        self.proxy    = proxy
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = None
            if self.proxy and self.proxy.startswith("socks"):
                try:
                    from aiohttp_socks import ProxyConnector
                    connector = ProxyConnector.from_url(self.proxy)
                except ImportError:
                    logger.error("Установите: pip install aiohttp-socks")
            self._session = aiohttp.ClientSession(
                headers=BASE_HEADERS,
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=60),
            )
        return self._session

    async def get_product(self, article_id: int) -> Optional[dict]:
        """Возвращает {"name": str, "price": float} или None."""
        for url_tpl in (WB_CARD_URL, WB_CARD_URL_V1):
            result = await self._fetch_with_pow(url_tpl.format(article_id=article_id))
            if result:
                return result
            await asyncio.sleep(0.3)
        return None

    async def _fetch_with_pow(self, url: str) -> Optional[dict]:
        session  = await self._get_session()
        proxy    = self.proxy if self.proxy and not self.proxy.startswith("socks") else None
        extra_h  = {}

        for attempt in range(3):
            try:
                async with session.get(url, proxy=proxy, ssl=False, headers=extra_h) as resp:
                    pow_hdr = resp.headers.get("x-pow", "")

                    if resp.status == 404 and "status=invalid" in pow_hdr and "challenge=" in pow_hdr:
                        logger.info(f"x-pow challenge received (attempt {attempt+1}), solving...")
                        challenge = pow_hdr.split("challenge=")[1]
                        solution  = await _solve_pow_async(challenge)
                        if solution:
                            extra_h = {"x-pow": solution}
                            continue
                        return None

                    if resp.status != 200:
                        logger.warning(f"HTTP {resp.status} for {url}")
                        return None

                    data     = await resp.json(content_type=None)
                    products = (data.get("data", {}) or {}).get("products", [])
                    if not products:
                        return None

                    return self._parse_product(products[0])

            except asyncio.TimeoutError:
                logger.warning(f"Timeout: {url}")
            except Exception as e:
                logger.error(f"Fetch error {url}: {e}")
                break

        return None

    def _parse_product(self, p: dict) -> Optional[dict]:
        price_raw = None
        for size in p.get("sizes", []):
            total = size.get("price", {}).get("total")
            if total:
                price_raw = total
                break

        if price_raw is None:
            price_raw = p.get("salePriceU") or p.get("priceU")

        if not price_raw:
            return None

        name      = p.get("name") or p.get("supplierArticle") or str(p.get("id", ""))
        brand     = p.get("brand", "")
        full_name = f"{brand} {name}".strip() if brand else name

        return {"name": full_name, "price": price_raw / 100}

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
