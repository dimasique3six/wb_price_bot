"""
Wildberries Price Tracker Bot
Отслеживает изменения цен на товары WB и уведомляет об изменениях.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import BOT_TOKEN, CHECK_INTERVAL_MINUTES, PRICE_CHANGE_THRESHOLD
from database import Database
from wb_api import WildberriesAPI

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

db = Database()
wb = WildberriesAPI()


# ─── Команды бота ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Wildberries Price Tracker*\n\n"
        "Я отслеживаю изменения цен на товары WB и сразу уведомляю тебя.\n\n"
        "📌 *Команды:*\n"
        "/add `<артикул>` — добавить товар в отслеживание\n"
        "/remove `<артикул>` — удалить товар\n"
        "/list — список отслеживаемых товаров\n"
        "/check — проверить цены прямо сейчас\n"
        "/help — помощь\n\n"
        "💡 Пример: `/add 123456789`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❗ Укажи артикул товара.\nПример: `/add 123456789`",
            parse_mode="Markdown",
        )
        return

    article = context.args[0].strip()
    if not article.isdigit():
        await update.message.reply_text("❗ Артикул должен состоять только из цифр.")
        return

    user_id = update.effective_user.id
    msg = await update.message.reply_text("⏳ Получаю информацию о товаре...")

    product = await wb.get_product(int(article))
    if not product:
        await msg.edit_text(
            f"❌ Товар с артикулом `{article}` не найден на Wildberries.",
            parse_mode="Markdown",
        )
        return

    added = db.add_tracking(user_id, int(article), product["name"], product["price"])
    if added:
        await msg.edit_text(
            f"✅ Добавлен в отслеживание:\n\n"
            f"📦 *{product['name']}*\n"
            f"🏷 Артикул: `{article}`\n"
            f"💰 Текущая цена: *{product['price']:,} ₽*",
            parse_mode="Markdown",
        )
    else:
        await msg.edit_text(
            f"⚠️ Товар `{article}` уже отслеживается.",
            parse_mode="Markdown",
        )


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❗ Укажи артикул товара.\nПример: `/remove 123456789`",
            parse_mode="Markdown",
        )
        return

    article = context.args[0].strip()
    user_id = update.effective_user.id

    removed = db.remove_tracking(user_id, int(article))
    if removed:
        await update.message.reply_text(
            f"🗑 Товар `{article}` удалён из отслеживания.", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"⚠️ Товар `{article}` не найден в твоём списке.", parse_mode="Markdown"
        )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = db.get_user_trackings(user_id)

    if not items:
        await update.message.reply_text(
            "📋 Список пуст. Добавь товары командой `/add <артикул>`",
            parse_mode="Markdown",
        )
        return

    lines = ["📋 *Отслеживаемые товары:*\n"]
    for item in items:
        lines.append(
            f"• `{item['article']}` — {item['name']}\n"
            f"  💰 {item['last_price']:,} ₽  |  📅 {item['updated_at']}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = db.get_user_trackings(user_id)

    if not items:
        await update.message.reply_text(
            "📋 Список пуст. Добавь товары командой `/add <артикул>`",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text("⏳ Проверяю цены...")
    changes = await check_prices_for_user(user_id, items)

    if not changes:
        await msg.edit_text("✅ Изменений нет — все цены прежние.")
    else:
        lines = ["📊 *Обнаружены изменения цен:*\n"]
        for r in changes:
            arrow = "🔺" if r["change"] > 0 else "🔻"
            lines.append(
                f"{arrow} `{r['article']}` — {r['name']}\n"
                f"  {r['old_price']:,} ₽ → *{r['new_price']:,} ₽* ({r['change']:+.1f}%)"
            )
        await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ─── Логика проверки цен ─────────────────────────────────────────

async def check_prices_for_user(user_id: int, items: list) -> list:
    """Проверяет цены и возвращает список изменений."""
    changes = []
    for item in items:
        product = await wb.get_product(item["article"])
        if not product:
            logger.warning(f"Не удалось получить цену для артикула {item['article']}")
            continue

        new_price = product["price"]
        old_price = item["last_price"]

        if old_price == 0:
            db.update_price(user_id, item["article"], new_price)
            continue

        change_pct = (new_price - old_price) / old_price * 100

        # Обновляем цену в БД всегда
        db.update_price(user_id, item["article"], new_price)

        if abs(change_pct) >= PRICE_CHANGE_THRESHOLD:
            db.add_price_history(user_id, item["article"], old_price, new_price, change_pct)
            changes.append({
                "article": item["article"],
                "name": item["name"],
                "old_price": old_price,
                "new_price": new_price,
                "change": change_pct,
            })

    return changes


async def scheduled_check(application: Application):
    """Плановая проверка цен для всех пользователей."""
    logger.info("Плановая проверка цен...")
    all_users = db.get_all_users()

    for user_id in all_users:
        items = db.get_user_trackings(user_id)
        if not items:
            continue

        changes = await check_prices_for_user(user_id, items)
        for change in changes:
            arrow = "🔺 Цена выросла" if change["change"] > 0 else "🔻 Цена упала"
            pct = abs(change["change"])
            text = (
                f"{arrow} на *{pct:.1f}%*\n\n"
                f"📦 {change['name']}\n"
                f"🏷 Артикул: `{change['article']}`\n"
                f"💰 {change['old_price']:,} ₽ → *{change['new_price']:,} ₽*\n"
                f"🔗 https://www.wildberries.ru/catalog/{change['article']}/detail.aspx"
            )
            try:
                await application.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")


# ─── Запуск ──────────────────────────────────────────────────────

def main():
    db.init()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("check", cmd_check))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_check,
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        args=[app],
        next_run_time=datetime.now(),  # первая проверка сразу при старте
    )
    scheduler.start()

    logger.info(f"Бот запущен. Проверка цен каждые {CHECK_INTERVAL_MINUTES} минут.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
