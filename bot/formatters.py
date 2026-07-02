from __future__ import annotations

from html import escape
from typing import Any


def money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def customer_link(telegram_id: int, username: str | None = None) -> str:
    if username:
        return f"@{escape(username)}"
    return f'<a href="tg://user?id={telegram_id}">ID {telegram_id}</a>'


def product_line(product: dict[str, Any]) -> str:
    return (
        f"#{product['id']} {escape(product['name'])}\n"
        f"Цена: {money(float(product['price_per_kg']))}/кг\n"
        f"На складе: {float(product['stock_kg']):g} кг"
    )


def cart_text(items: list[dict[str, Any]]) -> str:
    if not items:
        return "Корзина пустая."
    lines = ["Ваша корзина:"]
    total = 0.0
    for item in items:
        total += float(item["line_total"])
        lines.append(
            f"- {escape(item['name'])}: {float(item['qty_kg']):g} кг x "
            f"{money(float(item['price_per_kg']))} = {money(float(item['line_total']))}"
        )
    lines.append(f"\nИтого: {money(total)}")
    return "\n".join(lines)


def order_text(order: dict[str, Any], items: list[dict[str, Any]], admin: bool = False) -> str:
    lines = [
        f"Заказ #{order['id']}",
        f"Статус: {escape(order['status'])}",
        f"Сумма: {money(float(order['total_amount']))}",
        "",
        "Состав:",
    ]
    for item in items:
        lines.append(
            f"- {escape(item['product_name'])}: {float(item['qty_kg']):g} кг = {money(float(item['line_total']))}"
        )
    lines.extend(
        [
            "",
            f"ФИО: {escape(order['full_name'])}",
            f"Телефон: {escape(order['phone'])}",
            f"Адрес: {escape(order['address'])}",
            f"Доставка: {escape(order['delivery_datetime'])}",
            f"Комментарий: {escape(order['comment'] or '-')}",
            f"Создан: {escape(order['created_at'])}",
        ]
    )
    if admin:
        lines.append(f"Покупатель: {customer_link(int(order['customer_id']), order.get('username'))}")
    return "\n".join(lines)
