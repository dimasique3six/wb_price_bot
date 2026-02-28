"""
Модуль для работы с публичным API Wildberries.

Используем открытый эндпоинт карточек товаров — он не требует авторизации.
Цена возвращается в копейках, делим на 100.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# WB отдаёт данные через несколько CDN-хостов в зависимости от номера артикула
WB_CARD_URL = "https://card.wb.ru/cards/v1/detail"


class WildberriesAPI:
    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=15.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )

    async def get_product(self, article: int) -> dict | None:
        """
        Получает информацию о товаре по артикулу.
        Возвращает dict с ключами: name, price (руб.) или None при ошибке.
        """
        params = {
            "appType": 1,
            "curr": "rub",
            "dest": -1257786,  # Москва — самый популярный регион
            "nm": article,
        }

        try:
            resp = await self._client.get(WB_CARD_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Ошибка запроса к WB API для артикула {article}: {e}")
            return None

        products = data.get("data", {}).get("products", [])
        if not products:
            logger.warning(f"Товар {article} не найден в ответе WB API")
            return None

        product = products[0]
        name = product.get("name", f"Товар #{article}")

        # Цена может быть в salePriceU (со скидкой) или priceU (обычная)
        # salePriceU — цена с учётом всех скидок (та, что видна покупателю)
        price_raw = product.get("salePriceU") or product.get("priceU", 0)
        price = price_raw // 100  # копейки → рубли

        if price == 0:
            logger.warning(f"Нулевая цена для артикула {article}")
            return None

        return {"name": name, "price": price}

    async def close(self):
        await self._client.aclose()
