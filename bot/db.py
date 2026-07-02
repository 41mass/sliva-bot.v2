from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import aiosqlite


INITIAL_PRODUCTS = [
    ("Яблоки сушеные сладкие", 850, 5),
    ("Яблоки сушеные кислые", 790, 5),
    ("Персики сушеные", 1250, 4),
    ("Апельсины сушеные", 1100, 4),
    ("Клубника сушеная", 2200, 2),
    ("Черешня сушеная", 2400, 2),
    ("Манго сушеное", 1800, 3),
]

ORDER_STATUSES = ("создан", "оплачен", "выдан", "отменен", "возврат")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def connect(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    price_per_kg REAL NOT NULL,
                    stock_kg REAL NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS customers (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    phone TEXT,
                    address TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS admins (
                    telegram_id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS carts (
                    telegram_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    qty_kg REAL NOT NULL,
                    PRIMARY KEY (telegram_id, product_id),
                    FOREIGN KEY (product_id) REFERENCES products(id)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'создан',
                    total_amount REAL NOT NULL,
                    phone TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    address TEXT NOT NULL,
                    delivery_datetime TEXT NOT NULL,
                    comment TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    paid_at TEXT,
                    issued_at TEXT,
                    FOREIGN KEY (customer_id) REFERENCES customers(telegram_id)
                );

                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    product_name TEXT NOT NULL,
                    price_per_kg REAL NOT NULL,
                    qty_kg REAL NOT NULL,
                    line_total REAL NOT NULL,
                    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                    FOREIGN KEY (product_id) REFERENCES products(id)
                );
                """
            )
            existing = await self.scalar(db, "SELECT COUNT(*) FROM products")
            if existing == 0:
                await db.executemany(
                    "INSERT INTO products(name, price_per_kg, stock_kg) VALUES (?, ?, ?)",
                    INITIAL_PRODUCTS,
                )
            await db.commit()

    @staticmethod
    async def scalar(db: aiosqlite.Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        return row[0] if row else None

    async def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = await self.fetch_all(query, params)
        return rows[0] if rows else None

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(query, params)
            await db.commit()
            return int(cursor.lastrowid or 0)

    async def is_admin(self, telegram_id: int) -> bool:
        row = await self.fetch_one("SELECT telegram_id FROM admins WHERE telegram_id = ?", (telegram_id,))
        return row is not None

    async def add_admin(self, telegram_id: int) -> None:
        await self.execute("INSERT OR IGNORE INTO admins(telegram_id) VALUES (?)", (telegram_id,))

    async def upsert_customer(
        self,
        telegram_id: int,
        username: str | None,
        full_name: str | None = None,
        phone: str | None = None,
        address: str | None = None,
    ) -> None:
        old = await self.fetch_one("SELECT * FROM customers WHERE telegram_id = ?", (telegram_id,))
        if old:
            await self.execute(
                """
                UPDATE customers
                SET username = ?, full_name = COALESCE(?, full_name),
                    phone = COALESCE(?, phone), address = COALESCE(?, address),
                    updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
                """,
                (username, full_name, phone, address, telegram_id),
            )
        else:
            await self.execute(
                """
                INSERT INTO customers(telegram_id, username, full_name, phone, address)
                VALUES (?, ?, ?, ?, ?)
                """,
                (telegram_id, username, full_name, phone, address),
            )

    async def products(self, active_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE is_active = 1" if active_only else ""
        return await self.fetch_all(f"SELECT * FROM products {where} ORDER BY name")

    async def product(self, product_id: int) -> dict[str, Any] | None:
        return await self.fetch_one("SELECT * FROM products WHERE id = ?", (product_id,))

    async def add_product(self, name: str, price: float, stock: float) -> None:
        await self.execute(
            "INSERT INTO products(name, price_per_kg, stock_kg) VALUES (?, ?, ?)",
            (name, price, stock),
        )

    async def update_price(self, product_id: int, price: float) -> None:
        await self.execute("UPDATE products SET price_per_kg = ? WHERE id = ?", (price, product_id))

    async def add_stock(self, product_id: int, qty: float) -> None:
        await self.execute("UPDATE products SET stock_kg = stock_kg + ? WHERE id = ?", (qty, product_id))

    async def delete_product(self, product_id: int) -> None:
        await self.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))

    async def add_to_cart(self, telegram_id: int, product_id: int, qty: float) -> tuple[bool, str]:
        product = await self.product(product_id)
        if not product or not product["is_active"]:
            return False, "Такой позиции уже нет в каталоге."
        current_qty = await self.fetch_one(
            "SELECT qty_kg FROM carts WHERE telegram_id = ? AND product_id = ?",
            (telegram_id, product_id),
        )
        new_qty = qty + (float(current_qty["qty_kg"]) if current_qty else 0)
        if new_qty > float(product["stock_kg"]):
            return False, f"На складе только {product['stock_kg']:g} кг. В корзину столько добавить нельзя."
        await self.execute(
            """
            INSERT INTO carts(telegram_id, product_id, qty_kg)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id, product_id) DO UPDATE SET qty_kg = excluded.qty_kg
            """,
            (telegram_id, product_id, new_qty),
        )
        return True, "Добавил в корзину."

    async def cart(self, telegram_id: int) -> list[dict[str, Any]]:
        return await self.fetch_all(
            """
            SELECT c.product_id, c.qty_kg, p.name, p.price_per_kg, p.stock_kg,
                   c.qty_kg * p.price_per_kg AS line_total
            FROM carts c
            JOIN products p ON p.id = c.product_id
            WHERE c.telegram_id = ?
            ORDER BY p.name
            """,
            (telegram_id,),
        )

    async def clear_cart(self, telegram_id: int) -> None:
        await self.execute("DELETE FROM carts WHERE telegram_id = ?", (telegram_id,))

    async def create_order(
        self,
        telegram_id: int,
        phone: str,
        full_name: str,
        address: str,
        delivery_datetime: str,
        comment: str,
    ) -> tuple[bool, str, int | None]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN")
            cursor = await db.execute(
                """
                SELECT c.product_id, c.qty_kg, p.name, p.price_per_kg, p.stock_kg, p.is_active
                FROM carts c
                JOIN products p ON p.id = c.product_id
                WHERE c.telegram_id = ?
                """,
                (telegram_id,),
            )
            items = await cursor.fetchall()
            if not items:
                await db.rollback()
                return False, "Корзина пустая.", None
            for item in items:
                if not item["is_active"] or item["qty_kg"] > item["stock_kg"]:
                    await db.rollback()
                    return False, f"По позиции «{item['name']}» сейчас доступно {item['stock_kg']:g} кг.", None
            total = sum(float(item["qty_kg"]) * float(item["price_per_kg"]) for item in items)
            cursor = await db.execute(
                """
                INSERT INTO orders(customer_id, total_amount, phone, full_name, address, delivery_datetime, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (telegram_id, total, phone, full_name, address, delivery_datetime, comment),
            )
            order_id = int(cursor.lastrowid)
            await db.executemany(
                """
                INSERT INTO order_items(order_id, product_id, product_name, price_per_kg, qty_kg, line_total)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        order_id,
                        item["product_id"],
                        item["name"],
                        item["price_per_kg"],
                        item["qty_kg"],
                        float(item["qty_kg"]) * float(item["price_per_kg"]),
                    )
                    for item in items
                ],
            )
            await db.execute("DELETE FROM carts WHERE telegram_id = ?", (telegram_id,))
            await db.commit()
            return True, "Заказ создан.", order_id

    async def mark_paid_and_write_off_stock(self, order_id: int, customer_id: int) -> tuple[bool, str]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            order_cursor = await db.execute(
                "SELECT * FROM orders WHERE id = ? AND customer_id = ?",
                (order_id, customer_id),
            )
            order = await order_cursor.fetchone()
            if not order:
                await db.rollback()
                return False, "Заказ не найден."
            if order["status"] != "создан":
                await db.rollback()
                return False, f"У заказа уже статус «{order['status']}»."

            items_cursor = await db.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,))
            items = await items_cursor.fetchall()
            for item in items:
                product_cursor = await db.execute("SELECT stock_kg FROM products WHERE id = ?", (item["product_id"],))
                product = await product_cursor.fetchone()
                if not product or float(product["stock_kg"]) < float(item["qty_kg"]):
                    available = float(product["stock_kg"]) if product else 0
                    await db.rollback()
                    return False, f"Пока вы оформляли заказ, «{item['product_name']}» осталось {available:g} кг."

            for item in items:
                await db.execute(
                    "UPDATE products SET stock_kg = stock_kg - ? WHERE id = ?",
                    (item["qty_kg"], item["product_id"]),
                )
            await db.execute(
                "UPDATE orders SET status = 'оплачен', paid_at = CURRENT_TIMESTAMP WHERE id = ?",
                (order_id,),
            )
            await db.commit()
            return True, "Оплата принята, товар списан со склада."

    async def set_order_status(self, order_id: int, status: str) -> None:
        issued_sql = ", issued_at = CURRENT_TIMESTAMP" if status == "выдан" else ""
        await self.execute(f"UPDATE orders SET status = ? {issued_sql} WHERE id = ?", (status, order_id))

    async def delete_order(self, order_id: int) -> None:
        await self.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    async def order(self, order_id: int) -> dict[str, Any] | None:
        return await self.fetch_one(
            """
            SELECT o.*, c.username
            FROM orders o
            LEFT JOIN customers c ON c.telegram_id = o.customer_id
            WHERE o.id = ?
            """,
            (order_id,),
        )

    async def order_items(self, order_id: int) -> list[dict[str, Any]]:
        return await self.fetch_all("SELECT * FROM order_items WHERE order_id = ?", (order_id,))

    def _period_start(self, period: str) -> str:
        now = datetime.now()
        if period == "day":
            return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(" ")
        if period == "week":
            return (now - timedelta(days=7)).isoformat(" ")
        return "1970-01-01 00:00:00"

    async def orders(self, period: str = "all", product_id: int | None = None, customer_id: int | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [self._period_start(period)]
        joins = ""
        where = ["o.created_at >= ?"]
        if product_id is not None:
            joins = "JOIN order_items oi ON oi.order_id = o.id"
            where.append("oi.product_id = ?")
            params.append(product_id)
        if customer_id is not None:
            where.append("o.customer_id = ?")
            params.append(customer_id)
        return await self.fetch_all(
            f"""
            SELECT DISTINCT o.*, c.username
            FROM orders o
            LEFT JOIN customers c ON c.telegram_id = o.customer_id
            {joins}
            WHERE {' AND '.join(where)}
            ORDER BY o.id DESC
            LIMIT 50
            """,
            tuple(params),
        )

    async def customers(self) -> list[dict[str, Any]]:
        return await self.fetch_all("SELECT * FROM customers ORDER BY updated_at DESC LIMIT 50")

    async def stats(self, period: str = "all") -> dict[str, Any]:
        since = self._period_start(period)
        summary = await self.fetch_one(
            """
            SELECT COUNT(*) AS orders_count,
                   COALESCE(SUM(total_amount), 0) AS revenue
            FROM orders
            WHERE created_at >= ? AND status IN ('оплачен', 'выдан')
            """,
            (since,),
        )
        by_product = await self.fetch_all(
            """
            SELECT oi.product_name, SUM(oi.qty_kg) AS qty, SUM(oi.line_total) AS amount
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.created_at >= ? AND o.status IN ('оплачен', 'выдан')
            GROUP BY oi.product_name
            ORDER BY amount DESC
            LIMIT 10
            """,
            (since,),
        )
        return {"summary": summary, "by_product": by_product}
