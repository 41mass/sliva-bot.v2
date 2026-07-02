from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import Database, ORDER_STATUSES
from bot.formatters import customer_text, money, order_summary_line, order_text, product_line
from bot.keyboards import (
    admin_customer_actions,
    admin_customers_list,
    admin_menu,
    admin_orders_list,
    admin_order_actions,
    admin_orders_menu,
    admin_product_actions,
    admin_products,
    stats_menu,
)
from bot.states import AdminLogin, AdminProduct


router = Router()


async def safe_delete(message: Message | None) -> None:
    if not message:
        return
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def safe_edit_or_answer(message: Message, text: str, reply_markup=None) -> Message:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return message
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).lower():
            return message
        return await message.answer(text, reply_markup=reply_markup)


async def delete_active_screen(bot: Bot, chat_id: int, state: FSMContext, keep_message_id: int | None = None) -> None:
    data = await state.get_data()
    screen_id = data.get("active_screen_message_id")
    if not screen_id or int(screen_id) == keep_message_id:
        return
    try:
        await bot.delete_message(chat_id, int(screen_id))
    except TelegramBadRequest:
        pass
    await state.update_data(active_screen_message_id=None)


async def remember_active_screen(state: FSMContext, message: Message) -> None:
    await state.update_data(active_screen_message_id=message.message_id)


async def show_active_screen(message: Message, state: FSMContext, text: str, reply_markup=None) -> Message:
    screen = await safe_edit_or_answer(message, text, reply_markup=reply_markup)
    await remember_active_screen(state, screen)
    return screen


async def send_orders_list(message: Message, orders: list[dict], state: FSMContext) -> None:
    if not orders:
        await show_active_screen(message, state, "Заказов за этот период нет.")
        return
    text = "Заказы:\n\n" + "\n".join(order_summary_line(order) for order in orders[:20])
    await show_active_screen(message, state, text, reply_markup=admin_orders_list(orders[:20]))


def parse_product_input(text: str) -> tuple[str, float, float] | None:
    parts = [part.strip() for part in text.split(";")]
    if len(parts) != 3:
        return None
    try:
        return parts[0], float(parts[1].replace(",", ".")), float(parts[2].replace(",", "."))
    except ValueError:
        return None


async def require_admin(message: Message, db: Database) -> bool:
    if await db.is_admin(message.from_user.id):
        return True
    await message.answer("Это админ-раздел. Введите /admin и пароль.")
    return False


@router.message(F.text == "/admin")
async def admin_login_start(message: Message, state: FSMContext, bot: Bot) -> None:
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    await state.set_state(AdminLogin.password)
    sent = await message.answer("Введите пароль админки.")
    await remember_active_screen(state, sent)


@router.message(AdminLogin.password)
async def admin_login_password(message: Message, state: FSMContext, db: Database, config, bot: Bot) -> None:
    await delete_active_screen(bot, message.chat.id, state)
    await safe_delete(message)
    if message.text.strip() != config.admin_password:
        await state.clear()
        sent = await message.answer("Пароль неверный. Попробуйте /admin еще раз.")
        await remember_active_screen(state, sent)
        return
    await db.add_admin(message.from_user.id)
    await state.clear()
    sent = await message.answer("Вы вошли в админку.", reply_markup=admin_menu())
    await remember_active_screen(state, sent)


@router.message(F.text == "Админ: товары")
async def products_admin(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    if not await require_admin(message, db):
        return
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    products = await db.products(active_only=False)
    sent = await message.answer("Номенклатура:", reply_markup=admin_products(products))
    await remember_active_screen(state, sent)


@router.callback_query(F.data.startswith("admin_product:"))
async def product_admin_card(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    product_id = int(callback.data.split(":")[1])
    product = await db.product(product_id)
    await show_active_screen(callback.message, state, product_line(product), reply_markup=admin_product_actions(product_id))
    await callback.answer()


@router.callback_query(F.data == "admin_add_product")
async def add_product_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminProduct.add_name)
    await show_active_screen(
        callback.message,
        state,
        "Введите новую позицию в формате:\nНазвание; цена за кг; остаток кг\n\nНапример:\nФиники; 950; 10",
    )
    await callback.answer()


@router.message(AdminProduct.add_name)
async def add_product_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    parsed = parse_product_input(message.text)
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    if not parsed:
        sent = await message.answer("Не понял формат. Пример: Финики; 950; 10")
        await remember_active_screen(state, sent)
        return
    name, price, stock = parsed
    await db.add_product(name, price, stock)
    await state.clear()
    sent = await message.answer("Позиция добавлена.", reply_markup=admin_menu())
    await remember_active_screen(state, sent)


@router.callback_query(F.data.startswith("admin_price:"))
async def edit_price_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    product_id = int(callback.data.split(":")[1])
    await state.update_data(product_id=product_id)
    await state.set_state(AdminProduct.edit_price)
    await show_active_screen(callback.message, state, "Введите новую цену за кг числом. Например: 1200")
    await callback.answer()


@router.message(AdminProduct.edit_price)
async def edit_price_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    try:
        price = float(message.text.replace(",", "."))
    except ValueError:
        sent = await message.answer("Введите число, например 1200.")
        await remember_active_screen(state, sent)
        return
    data = await state.get_data()
    await db.update_price(int(data["product_id"]), price)
    await state.clear()
    sent = await message.answer("Цена обновлена.", reply_markup=admin_menu())
    await remember_active_screen(state, sent)


@router.callback_query(F.data.startswith("admin_stock:"))
async def add_stock_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    product_id = int(callback.data.split(":")[1])
    await state.update_data(product_id=product_id)
    await state.set_state(AdminProduct.add_stock_qty)
    await show_active_screen(callback.message, state, "Введите приход на склад в кг. Например: 5 или 2.5")
    await callback.answer()


@router.message(AdminProduct.add_stock_qty)
async def add_stock_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    try:
        qty = float(message.text.replace(",", "."))
    except ValueError:
        sent = await message.answer("Введите число, например 5.")
        await remember_active_screen(state, sent)
        return
    data = await state.get_data()
    await db.add_stock(int(data["product_id"]), qty)
    await state.clear()
    sent = await message.answer("Остаток увеличен.", reply_markup=admin_menu())
    await remember_active_screen(state, sent)


@router.callback_query(F.data.startswith("admin_delete_product:"))
async def delete_product(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    product_id = int(callback.data.split(":")[1])
    await db.delete_product(product_id)
    await show_active_screen(callback.message, state, "Позиция скрыта из каталога.")
    await callback.answer()


@router.message(F.text == "Админ: заказы")
async def orders_admin(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    if not await require_admin(message, db):
        return
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    sent = await message.answer("Какие заказы показать?", reply_markup=admin_orders_menu())
    await remember_active_screen(state, sent)


@router.callback_query(F.data.startswith("admin_orders:"))
async def orders_list(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    period = callback.data.split(":")[1]
    orders = await db.orders(period=period)
    await send_orders_list(callback.message, orders, state)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_order_detail:"))
async def order_detail(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[1])
    order = await db.order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    items = await db.order_items(order_id)
    await show_active_screen(callback.message, state, order_text(order, items, admin=True), reply_markup=admin_order_actions(order_id))
    await callback.answer()


@router.callback_query(F.data == "admin_orders_by_product")
async def orders_by_product_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    products = await db.products(active_only=False)
    text = (
        "Введите ID позиции и период через пробел.\n"
        "Периоды: day, week, all\n"
        "Пример: 3 week\n\n"
        "Список:\n"
        + "\n".join(f"#{product['id']} {product['name']}" for product in products)
    )
    await state.set_state(AdminProduct.orders_by_product)
    await show_active_screen(callback.message, state, text)
    await callback.answer()


@router.message(AdminProduct.orders_by_product)
async def orders_by_product_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    try:
        parts = message.text.strip().replace("#", "").split()
        product_id = int(parts[0])
        period = parts[1] if len(parts) > 1 else "all"
    except ValueError:
        sent = await message.answer("Введите ID и период. Например: 3 week")
        await remember_active_screen(state, sent)
        return
    if period not in {"day", "week", "all"}:
        sent = await message.answer("Период должен быть day, week или all. Например: 3 week")
        await remember_active_screen(state, sent)
        return
    orders = await db.orders(period=period, product_id=product_id)
    await state.clear()
    if not orders:
        sent = await message.answer("Заказов по этой позиции нет.", reply_markup=admin_menu())
        await remember_active_screen(state, sent)
    else:
        sent = await message.answer(
            "Заказы по позиции:\n\n" + "\n".join(order_summary_line(order) for order in orders[:20]),
            reply_markup=admin_orders_list(orders[:20]),
        )
        await remember_active_screen(state, sent)


@router.callback_query(F.data.startswith("admin_set_status:"))
async def set_status(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, order_id, status = callback.data.split(":", 2)
    if status not in ORDER_STATUSES:
        await callback.answer("Неизвестный статус", show_alert=True)
        return
    await db.set_order_status(int(order_id), status)
    order = await db.order(int(order_id))
    items = await db.order_items(int(order_id))
    await show_active_screen(
        callback.message,
        state,
        f"Статус изменен на «{status}».\n\n" + order_text(order, items, admin=True),
        reply_markup=admin_order_actions(int(order_id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_delete_order:"))
async def delete_order(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[1])
    await db.delete_order(order_id)
    await show_active_screen(callback.message, state, f"Заказ #{order_id} удален.")
    await callback.answer()


@router.message(F.text == "Админ: клиенты")
async def customers_admin(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    if not await require_admin(message, db):
        return
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    customers = await db.customers()
    if not customers:
        sent = await message.answer("Клиентов пока нет.")
        await remember_active_screen(state, sent)
        return
    sent = await message.answer("Клиенты:", reply_markup=admin_customers_list(customers))
    await remember_active_screen(state, sent)


@router.callback_query(F.data.startswith("admin_customer_detail:"))
async def customer_detail(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    customer_id = int(callback.data.split(":")[1])
    customer = await db.fetch_one("SELECT * FROM customers WHERE telegram_id = ?", (customer_id,))
    if not customer:
        await callback.answer("Клиент не найден", show_alert=True)
        return
    await show_active_screen(
        callback.message,
        state,
        customer_text(customer),
        reply_markup=admin_customer_actions(customer["telegram_id"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_customer_orders:"))
async def customer_orders(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    customer_id = int(callback.data.split(":")[1])
    orders = await db.orders(customer_id=customer_id)
    await send_orders_list(callback.message, orders, state)
    await callback.answer()


@router.message(F.text == "Админ: статистика")
async def stats_admin(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    if not await require_admin(message, db):
        return
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    sent = await message.answer("Выберите период статистики:", reply_markup=stats_menu())
    await remember_active_screen(state, sent)


@router.callback_query(F.data.startswith("admin_stats:"))
async def stats_callback(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    period = callback.data.split(":")[1]
    stats = await db.stats(period)
    summary = stats["summary"]
    lines = [
        "Статистика продаж",
        f"Оплаченных/выданных заказов: {summary['orders_count']}",
        f"Выручка: {money(float(summary['revenue']))}",
        "",
        "Топ позиций:",
    ]
    if not stats["by_product"]:
        lines.append("Пока нет продаж.")
    for row in stats["by_product"]:
        lines.append(f"- {row['product_name']}: {row['qty']:g} кг, {money(float(row['amount']))}")
    await show_active_screen(callback.message, state, "\n".join(lines))
    await callback.answer()
