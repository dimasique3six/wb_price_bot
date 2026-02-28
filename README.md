# Wildberries Price Tracker Bot

Telegram-бот для отслеживания изменений цен на Wildberries.

## Структура проекта

```
wb_price_bot/
├── bot.py               # основной файл бота
├── wb_api.py            # клиент WB API
├── database.py          # SQLite хранилище
├── requirements.txt
├── .env.example         # шаблон конфига
├── wb_price_bot.service # systemd unit
└── README.md
```

## Быстрый старт

### 1. Установка на VPS

```bash
# Клонируем / копируем файлы
mkdir -p /opt/wb_price_bot
cd /opt/wb_price_bot

# Виртуальное окружение
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Конфигурация

```bash
cp .env.example .env
nano .env
```

Обязательно укажите:
- `BOT_TOKEN` — токен от @BotFather
- `PROXY_URL` — если VPS в Европе (см. ниже)

### 3. Тестовый запуск

```bash
source venv/bin/activate
python bot.py
```

### 4. Запуск как systemd-служба

```bash
# Отредактируйте User= в wb_price_bot.service
nano wb_price_bot.service

sudo cp wb_price_bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wb_price_bot
sudo systemctl start wb_price_bot

# Проверить статус
sudo systemctl status wb_price_bot

# Логи
sudo journalctl -u wb_price_bot -f
```

---

## ⚠️ Важно: Европейский VPS

Wildberries может блокировать запросы с нероссийских IP.
Проверьте доступность без прокси:

```bash
curl "https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm=12345678"
```

Если получаете пустой ответ или ошибку — нужен российский прокси.

### Варианты прокси

**HTTP-прокси:**
```
PROXY_URL=http://login:password@ip:port
```

**SOCKS5-прокси:**
```
PROXY_URL=socks5://login:password@ip:port
```

Где купить:
- [proxys.io](https://proxys.io) — российские прокси
- [proxy6.net](https://proxy6.net) — российские
- [proxyline.net](https://proxyline.net)

---

## Команды бота

| Команда | Описание |
|---------|----------|
| /start | Приветствие и список команд |
| /add | Добавить артикул для отслеживания |
| /list | Список отслеживаемых артикулов |
| /remove | Удалить артикул |
| /check | Проверить цены прямо сейчас |
| /threshold | Изменить порог уведомлений (по умолчанию 1%) |
| /help | Помощь |

---

## Как работает

1. Бот опрашивает `card.wb.ru` — публичный API WB (без авторизации)
2. Сравнивает текущую цену с сохранённой
3. Если изменение ≥ порога — отправляет уведомление в Telegram
4. История цен сохраняется в SQLite (`prices.db`)

---

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|-------------|---------|
| `BOT_TOKEN` | — | Токен Telegram-бота (обязательно) |
| `PROXY_URL` | пусто | Прокси для запросов к WB |
| `CHECK_INTERVAL` | 30 | Интервал проверки в минутах |
| `PRICE_THRESHOLD` | 1.0 | Мин. изменение цены для уведомления, % |
| `MAX_ARTICLES` | 50 | Лимит артикулов на пользователя |
