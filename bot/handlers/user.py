from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import Database
from bot.formatters import cart_text, order_text, product_line
from bot.keyboards import cart_actions, catalog, main_menu, pay_order, product_actions
from bot.states import Checkout


router = Router()


async def show_catalog(message: Message, db: Database) -> None:
    products = await db.products()
    if not products:
        await message.answer("Каталог пока пуст.", reply_markup=main_menu())
        return
    await message.answer("Выберите позицию:", reply_markup=catalog(products))


@router.message(F.text == "/start")
async def start(message: Message, db: Database) -> None:
    await db.upsert_customer(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    await message.answer(
        "Здравствуйте! Это магазин сухофруктов «Слива».\n\n"
        "Здесь можно выбрать товары, оформить доставку и посмотреть свои заказы.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "Каталог")
async def catalog_message(message: Message, db: Database) -> None:
    await show_catalog(message, db)


@router.callback_query(F.data == "show_catalog")
async def catalog_callback(callback: CallbackQuery, db: Database) -> None:
    await callback.message.delete()
    await show_catalog(callback.message, db)
    await callback.answer()


@router.callback_query(F.data.startswith("product:"))
async def product_card(callback: CallbackQuery, db: Database) -> None:
    product_id = int(callback.data.split(":")[1])
    product = await db.product(product_id)
    if not product or not product["is_active"]:
        await callback.answer("Позиция недоступна.", show_alert=True)
        return
    await callback.message.answer(product_line(product), reply_markup=product_actions(product_id))
    await callback.answer()


@router.callback_query(F.data.startswith("cart_add:"))
async def add_to_cart(callback: CallbackQuery, db: Database) -> None:
    _, product_id, qty = callback.data.split(":")
    ok, text = await db.add_to_cart(callback.from_user.id, int(product_id), float(qty))
    await callback.answer(text, show_alert=not ok)


@router.message(F.text == "Корзина")
async def cart_message(message: Message, db: Database) -> None:
    items = await db.cart(message.from_user.id)
    markup = cart_actions() if items else None
    await message.answer(cart_text(items), reply_markup=markup)


@router.callback_query(F.data == "cart_clear")
async def clear_cart(callback: CallbackQuery, db: Database) -> None:
    await db.clear_cart(callback.from_user.id)
    await callback.message.answer("Корзина очищена.")
    await callback.answer()


@router.callback_query(F.data == "checkout")
async def checkout_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    items = await db.cart(callback.from_user.id)
    if not items:
        await callback.answer("Корзина пустая.", show_alert=True)
        return
    customer = await db.fetch_one("SELECT * FROM customers WHERE telegram_id = ?", (callback.from_user.id,))
    await state.set_state(Checkout.phone)
    hint = f"\nВаш прошлый номер: {customer['phone']}" if customer and customer.get("phone") else ""
    await callback.message.answer("Введите телефон для связи." + hint)
    await callback.answer()


@router.message(Checkout.phone)
async def checkout_phone(message: Message, state: FSMContext) -> None:
    await state.update_data(phone=message.text.strip())
    await state.set_state(Checkout.full_name)
    await message.answer("Введите ФИО получателя.")


@router.message(Checkout.full_name)
async def checkout_full_name(message: Message, state: FSMContext) -> None:
    await state.update_data(full_name=message.text.strip())
    await state.set_state(Checkout.address)
    await message.answer("Введите адрес доставки.")


@router.message(Checkout.address)
async def checkout_address(message: Message, state: FSMContext) -> None:
    await state.update_data(address=message.text.strip())
    await state.set_state(Checkout.delivery_datetime)
    await message.answer("Введите дату и время доставки. Например: 05.07 после 18:00")


@router.message(Checkout.delivery_datetime)
async def checkout_delivery(message: Message, state: FSMContext) -> None:
    await state.update_data(delivery_datetime=message.text.strip())
    await state.set_state(Checkout.comment)
    await message.answer("Комментарий к заказу. Если комментария нет, напишите «нет».")


@router.message(Checkout.comment)
async def checkout_finish(message: Message, state: FSMContext, db: Database, bot: Bot, config: Config) -> None:
    data = await state.get_data()
    comment = "" if message.text.strip().lower() in {"нет", "-", "no"} else message.text.strip()
    await db.upsert_customer(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=data["full_name"],
        phone=data["phone"],
        address=data["address"],
    )
    ok, text, order_id = await db.create_order(
        telegram_id=message.from_user.id,
        phone=data["phone"],
        full_name=data["full_name"],
        address=data["address"],
        delivery_datetime=data["delivery_datetime"],
        comment=comment,
    )
    await state.clear()
    if not ok or order_id is None:
        await message.answer(text)
        return
    order = await db.order(order_id)
    items = await db.order_items(order_id)
    await message.answer(
        order_text(order, items) + "\n\nНажмите кнопку оплаты. Сейчас это тестовая кнопка-заглушка.",
        reply_markup=pay_order(order_id),
    )
    if config.admin_notify_id:
        await bot.send_message(
            config.admin_notify_id,
            "Новый заказ ожидает оплаты:\n\n" + order_text(order, items, admin=True),
        )


@router.callback_query(F.data.startswith("pay:"))
async def pay(callback: CallbackQuery, db: Database, bot: Bot, config: Config) -> None:
    order_id = int(callback.data.split(":")[1])
    ok, text = await db.mark_paid_and_write_off_stock(order_id, callback.from_user.id)
    order = await db.order(order_id)
    if not ok:
        await callback.message.answer(text + "\nМожно изменить заказ или написать магазину.")
        await callback.answer("Оплата не прошла", show_alert=True)
        return
    items = await db.order_items(order_id)
    await callback.message.answer(text + "\n\n" + order_text(order, items))
    if config.admin_notify_id:
        await bot.send_message(
            config.admin_notify_id,
            "Заказ оплачен, склад списан:\n\n" + order_text(order, items, admin=True),
        )
    await callback.answer("Оплачено")


@router.message(F.text == "Мои заказы")
@router.callback_query(F.data == "my_orders")
async def my_orders(event: Message | CallbackQuery, db: Database) -> None:
    user_id = event.from_user.id
    orders = await db.orders(customer_id=user_id)
    target = event.message if isinstance(event, CallbackQuery) else event
    if not orders:
        await target.answer("У вас пока нет заказов.")
    else:
        for order in orders[:10]:
            items = await db.order_items(order["id"])
            await target.answer(order_text(order, items))
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(F.text == "Мои данные")
async def my_data(message: Message, db: Database) -> None:
    customer = await db.fetch_one("SELECT * FROM customers WHERE telegram_id = ?", (message.from_user.id,))
    if not customer:
        await message.answer("Данных пока нет. Они сохранятся после первого заказа.")
        return
    await message.answer(
        "Ваши сохраненные данные:\n"
        f"ФИО: {customer.get('full_name') or '-'}\n"
        f"Телефон: {customer.get('phone') or '-'}\n"
        f"Адрес: {customer.get('address') or '-'}\n\n"
        "При новом заказе можно ввести другие данные, бот обновит карточку."
    )
