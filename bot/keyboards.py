from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db import ORDER_STATUSES


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Каталог"), KeyboardButton(text="Корзина")],
            [KeyboardButton(text="Мои заказы"), KeyboardButton(text="Мои данные")],
        ],
        resize_keyboard=True,
    )


def reuse_data_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оставить прошлые данные", callback_data="checkout_reuse_data")]
        ]
    )


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Админ: товары"), KeyboardButton(text="Админ: заказы")],
            [KeyboardButton(text="Админ: клиенты"), KeyboardButton(text="Админ: статистика")],
        ],
        resize_keyboard=True,
    )


def catalog(products: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.button(
            text=f"{product['name']} - {product['price_per_kg']:g} ₽/кг",
            callback_data=f"product:{product['id']}",
        )
    builder.adjust(1)
    return builder.as_markup()


def product_actions(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="+0.5 кг", callback_data=f"cart_add:{product_id}:0.5"),
                InlineKeyboardButton(text="+1 кг", callback_data=f"cart_add:{product_id}:1"),
                InlineKeyboardButton(text="+2 кг", callback_data=f"cart_add:{product_id}:2"),
            ],
            [InlineKeyboardButton(text="В каталог", callback_data="show_catalog")],
        ]
    )


def cart_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оформить заказ", callback_data="checkout")],
            [InlineKeyboardButton(text="Очистить корзину", callback_data="cart_clear")],
        ]
    )


def pay_order(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить заказ (тест)", callback_data=f"pay:{order_id}")],
            [InlineKeyboardButton(text="Мои заказы", callback_data="my_orders")],
        ]
    )


def user_orders_list(orders: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        label = f"#{order['id']} | {order['created_at'][:16]} | {order['status']}"
        builder.button(text=label, callback_data=f"user_order_detail:{order['id']}")
    builder.adjust(1)
    return builder.as_markup()


def admin_products(products: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        label = f"#{product['id']} {product['name']} ({product['stock_kg']:g} кг)"
        builder.button(text=label, callback_data=f"admin_product:{product['id']}")
    builder.button(text="Добавить позицию", callback_data="admin_add_product")
    builder.adjust(1)
    return builder.as_markup()


def admin_product_actions(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить цену", callback_data=f"admin_price:{product_id}")],
            [InlineKeyboardButton(text="Приход на склад", callback_data=f"admin_stock:{product_id}")],
            [InlineKeyboardButton(text="Удалить позицию", callback_data=f"admin_delete_product:{product_id}")],
        ]
    )


def admin_orders_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="За сегодня", callback_data="admin_orders:day")],
            [InlineKeyboardButton(text="За неделю", callback_data="admin_orders:week")],
            [InlineKeyboardButton(text="Все", callback_data="admin_orders:all")],
            [InlineKeyboardButton(text="По позиции", callback_data="admin_orders_by_product")],
        ]
    )


def admin_order_actions(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for status in ORDER_STATUSES:
        builder.button(text=f"Статус: {status}", callback_data=f"admin_set_status:{order_id}:{status}")
    builder.button(text="Удалить заказ", callback_data=f"admin_delete_order:{order_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_orders_list(orders: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        full_name = order.get("full_name") or "Без имени"
        label = f"#{order['id']} | {order['created_at'][:16]} | {full_name}"
        builder.button(text=label, callback_data=f"admin_order_detail:{order['id']}")
    builder.adjust(1)
    return builder.as_markup()


def admin_customer_actions(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="История заказов клиента", callback_data=f"admin_customer_orders:{telegram_id}")]
        ]
    )


def admin_customers_list(customers: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for customer in customers:
        full_name = customer.get("full_name") or "Без имени"
        username = f"@{customer['username']}" if customer.get("username") else f"ID {customer['telegram_id']}"
        builder.button(text=f"{full_name} | {username}", callback_data=f"admin_customer_detail:{customer['telegram_id']}")
    builder.adjust(1)
    return builder.as_markup()


def stats_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сегодня", callback_data="admin_stats:day")],
            [InlineKeyboardButton(text="Неделя", callback_data="admin_stats:week")],
            [InlineKeyboardButton(text="Все время", callback_data="admin_stats:all")],
        ]
    )
