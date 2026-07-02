from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import Database, ORDER_STATUSES
from bot.formatters import customer_link, money, order_summary_line, order_text, product_line
from bot.keyboards import (
    admin_customer_actions,
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
    except TelegramBadRequest:
        return await message.answer(text, reply_markup=reply_markup)


async def send_orders_list(message: Message, orders: list[dict]) -> None:
    if not orders:
        await safe_edit_or_answer(message, "Заказов за этот период нет.")
        return
    text = "Заказы:\n\n" + "\n".join(order_summary_line(order) for order in orders[:20])
    await safe_edit_or_answer(message, text, reply_markup=admin_orders_list(orders[:20]))


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
async def admin_login_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminLogin.password)
    await message.answer("Введите пароль админки.")


@router.message(AdminLogin.password)
async def admin_login_password(message: Message, state: FSMContext, db: Database, config) -> None:
    if message.text.strip() != config.admin_password:
        await message.answer("Пароль неверный. Попробуйте /admin еще раз.")
        await state.clear()
        return
    await db.add_admin(message.from_user.id)
    await state.clear()
    await message.answer("Вы вошли в админку.", reply_markup=admin_menu())


@router.message(F.text == "Админ: товары")
async def products_admin(message: Message, db: Database) -> None:
    if not await require_admin(message, db):
        return
    await safe_delete(message)
    products = await db.products(active_only=False)
    await message.answer("Номенклатура:", reply_markup=admin_products(products))


@router.callback_query(F.data.startswith("admin_product:"))
async def product_admin_card(callback: CallbackQuery, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    product_id = int(callback.data.split(":")[1])
    product = await db.product(product_id)
    await safe_edit_or_answer(callback.message, product_line(product), reply_markup=admin_product_actions(product_id))
    await callback.answer()


@router.callback_query(F.data == "admin_add_product")
async def add_product_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminProduct.add_name)
    await callback.message.answer("Введите новую позицию в формате:\nНазвание; цена за кг; остаток кг\n\nНапример:\nФиники; 950; 10")
    await callback.answer()


@router.message(AdminProduct.add_name)
async def add_product_finish(message: Message, state: FSMContext, db: Database) -> None:
    parsed = parse_product_input(message.text)
    if not parsed:
        await message.answer("Не понял формат. Пример: Финики; 950; 10")
        return
    name, price, stock = parsed
    await db.add_product(name, price, stock)
    await state.clear()
    await message.answer("Позиция добавлена.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("admin_price:"))
async def edit_price_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    product_id = int(callback.data.split(":")[1])
    await state.update_data(product_id=product_id)
    await state.set_state(AdminProduct.edit_price)
    await callback.message.answer("Введите новую цену за кг числом. Например: 1200")
    await callback.answer()


@router.message(AdminProduct.edit_price)
async def edit_price_finish(message: Message, state: FSMContext, db: Database) -> None:
    try:
        price = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Введите число, например 1200.")
        return
    data = await state.get_data()
    await db.update_price(int(data["product_id"]), price)
    await state.clear()
    await message.answer("Цена обновлена.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("admin_stock:"))
async def add_stock_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    product_id = int(callback.data.split(":")[1])
    await state.update_data(product_id=product_id)
    await state.set_state(AdminProduct.add_stock_qty)
    await callback.message.answer("Введите приход на склад в кг. Например: 5 или 2.5")
    await callback.answer()


@router.message(AdminProduct.add_stock_qty)
async def add_stock_finish(message: Message, state: FSMContext, db: Database) -> None:
    try:
        qty = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Введите число, например 5.")
        return
    data = await state.get_data()
    await db.add_stock(int(data["product_id"]), qty)
    await state.clear()
    await message.answer("Остаток увеличен.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("admin_delete_product:"))
async def delete_product(callback: CallbackQuery, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    product_id = int(callback.data.split(":")[1])
    await db.delete_product(product_id)
    await callback.message.answer("Позиция скрыта из каталога.")
    await callback.answer()


@router.message(F.text == "Админ: заказы")
async def orders_admin(message: Message, db: Database) -> None:
    if not await require_admin(message, db):
        return
    await safe_delete(message)
    await message.answer("Какие заказы показать?", reply_markup=admin_orders_menu())


@router.callback_query(F.data.startswith("admin_orders:"))
async def orders_list(callback: CallbackQuery, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    period = callback.data.split(":")[1]
    orders = await db.orders(period=period)
    await send_orders_list(callback.message, orders)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_order_detail:"))
async def order_detail(callback: CallbackQuery, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[1])
    order = await db.order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    items = await db.order_items(order_id)
    await safe_edit_or_answer(callback.message, order_text(order, items, admin=True), reply_markup=admin_order_actions(order_id))
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
    await safe_edit_or_answer(callback.message, text)
    await callback.answer()


@router.message(AdminProduct.orders_by_product)
async def orders_by_product_finish(message: Message, state: FSMContext, db: Database) -> None:
    try:
        parts = message.text.strip().replace("#", "").split()
        product_id = int(parts[0])
        period = parts[1] if len(parts) > 1 else "all"
    except ValueError:
        await message.answer("Введите ID и период. Например: 3 week")
        return
    if period not in {"day", "week", "all"}:
        await message.answer("Период должен быть day, week или all. Например: 3 week")
        return
    orders = await db.orders(period=period, product_id=product_id)
    await state.clear()
    await safe_delete(message)
    if not orders:
        await message.answer("Заказов по этой позиции нет.", reply_markup=admin_menu())
    else:
        await message.answer(
            "Заказы по позиции:\n\n" + "\n".join(order_summary_line(order) for order in orders[:20]),
            reply_markup=admin_orders_list(orders[:20]),
        )


@router.callback_query(F.data.startswith("admin_set_status:"))
async def set_status(callback: CallbackQuery, db: Database) -> None:
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
    await safe_edit_or_answer(
        callback.message,
        f"Статус изменен на «{status}».\n\n" + order_text(order, items, admin=True),
        reply_markup=admin_order_actions(int(order_id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_delete_order:"))
async def delete_order(callback: CallbackQuery, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[1])
    await db.delete_order(order_id)
    await callback.message.answer(f"Заказ #{order_id} удален.")
    await callback.answer()


@router.message(F.text == "Админ: клиенты")
async def customers_admin(message: Message, db: Database) -> None:
    if not await require_admin(message, db):
        return
    customers = await db.customers()
    if not customers:
        await message.answer("Клиентов пока нет.")
        return
    for customer in customers:
        await message.answer(
            f"{customer_link(customer['telegram_id'], customer.get('username'))}\n"
            f"ФИО: {customer.get('full_name') or '-'}\n"
            f"Телефон: {customer.get('phone') or '-'}\n"
            f"Адрес: {customer.get('address') or '-'}\n"
            f"Telegram ID: <code>{customer['telegram_id']}</code>",
            reply_markup=admin_customer_actions(customer["telegram_id"]),
            disable_web_page_preview=True,
        )


@router.callback_query(F.data.startswith("admin_customer_orders:"))
async def customer_orders(callback: CallbackQuery, db: Database) -> None:
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    customer_id = int(callback.data.split(":")[1])
    orders = await db.orders(customer_id=customer_id)
    await send_orders_list(callback.message, orders)
    await callback.answer()


@router.message(F.text == "Админ: статистика")
async def stats_admin(message: Message, db: Database) -> None:
    if not await require_admin(message, db):
        return
    await message.answer("Выберите период статистики:", reply_markup=stats_menu())


@router.callback_query(F.data.startswith("admin_stats:"))
async def stats_callback(callback: CallbackQuery, db: Database) -> None:
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
    await callback.message.answer("\n".join(lines))
    await callback.answer()
