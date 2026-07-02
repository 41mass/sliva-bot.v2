from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import Database
from bot.formatters import cart_text, order_text, product_line, user_order_summary_line
from bot.keyboards import cart_actions, catalog, main_menu, pay_order, product_actions, reuse_data_keyboard, user_orders_list
from bot.states import Checkout


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


async def delete_checkout_prompt(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_id = data.get("prompt_message_id")
    if not prompt_id:
        return
    try:
        await bot.delete_message(chat_id, int(prompt_id))
    except TelegramBadRequest:
        pass


async def send_checkout_prompt(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup=None,
) -> None:
    sent = await message.answer(text, reply_markup=reply_markup)
    await state.update_data(prompt_message_id=sent.message_id)


async def show_catalog(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    products = await db.products()
    await delete_active_screen(bot, message.chat.id, state)
    if not products:
        sent = await message.answer("Каталог пока пуст.", reply_markup=main_menu())
        await remember_active_screen(state, sent)
        return
    sent = await message.answer("Выберите позицию:", reply_markup=catalog(products))
    await remember_active_screen(state, sent)


@router.message(F.text == "/start")
async def start(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    await db.upsert_customer(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    sent = await message.answer(
        "Здравствуйте! Это магазин сухофруктов «Слива».\n\n"
        "Здесь можно выбрать товары, оформить доставку и посмотреть свои заказы.",
        reply_markup=main_menu(),
    )
    await remember_active_screen(state, sent)


@router.message(F.text == "Каталог")
async def catalog_message(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    await safe_delete(message)
    await show_catalog(message, db, state, bot)


@router.callback_query(F.data == "show_catalog")
async def catalog_callback(callback: CallbackQuery, db: Database, state: FSMContext, bot: Bot) -> None:
    products = await db.products()
    await delete_active_screen(bot, callback.message.chat.id, state, keep_message_id=callback.message.message_id)
    if not products:
        screen = await safe_edit_or_answer(callback.message, "Каталог пока пуст.")
    else:
        screen = await safe_edit_or_answer(callback.message, "Выберите позицию:", reply_markup=catalog(products))
    await remember_active_screen(state, screen)
    await callback.answer()


@router.callback_query(F.data.startswith("product:"))
async def product_card(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    product_id = int(callback.data.split(":")[1])
    product = await db.product(product_id)
    if not product or not product["is_active"]:
        await callback.answer("Позиция недоступна.", show_alert=True)
        return
    screen = await safe_edit_or_answer(callback.message, product_line(product), reply_markup=product_actions(product_id))
    await remember_active_screen(state, screen)
    await callback.answer()


@router.callback_query(F.data.startswith("cart_add:"))
async def add_to_cart(callback: CallbackQuery, db: Database) -> None:
    _, product_id, qty = callback.data.split(":")
    ok, text = await db.add_to_cart(callback.from_user.id, int(product_id), float(qty))
    await callback.answer(text, show_alert=not ok)


@router.message(F.text == "Корзина")
async def cart_message(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    items = await db.cart(message.from_user.id)
    markup = cart_actions() if items else None
    sent = await message.answer(cart_text(items), reply_markup=markup)
    await remember_active_screen(state, sent)


@router.callback_query(F.data == "cart_clear")
async def clear_cart(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    await db.clear_cart(callback.from_user.id)
    screen = await safe_edit_or_answer(callback.message, "Корзина очищена.")
    await remember_active_screen(state, screen)
    await callback.answer()


@router.callback_query(F.data == "checkout")
async def checkout_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    items = await db.cart(callback.from_user.id)
    if not items:
        await callback.answer("Корзина пустая.", show_alert=True)
        return
    customer = await db.fetch_one("SELECT * FROM customers WHERE telegram_id = ?", (callback.from_user.id,))
    has_saved_data = bool(customer and customer.get("phone") and customer.get("full_name") and customer.get("address"))
    await safe_delete(callback.message)
    await state.update_data(active_screen_message_id=None)
    await state.set_state(Checkout.phone)
    if has_saved_data:
        await state.update_data(
            saved_phone=customer["phone"],
            saved_full_name=customer["full_name"],
            saved_address=customer["address"],
        )
        text = (
            "Можно оставить прошлые данные:\n"
            f"ФИО: {customer['full_name']}\n"
            f"Телефон: {customer['phone']}\n"
            f"Адрес: {customer['address']}\n\n"
            "Нажмите «Оставить прошлые данные» или введите новый телефон."
        )
        await send_checkout_prompt(callback.message, state, text, reply_markup=reuse_data_keyboard())
    else:
        await send_checkout_prompt(callback.message, state, "Введите телефон для связи.")
    await callback.answer()


@router.callback_query(Checkout.phone, F.data == "checkout_reuse_data")
async def checkout_reuse_data(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if not data.get("saved_phone"):
        await callback.answer("Сохраненных данных пока нет.", show_alert=True)
        return
    await state.update_data(
        phone=data["saved_phone"],
        full_name=data["saved_full_name"],
        address=data["saved_address"],
    )
    await state.set_state(Checkout.delivery_datetime)
    await safe_edit_or_answer(
        callback.message,
        "Хорошо, оставил прошлые ФИО, телефон и адрес.\nВведите дату и время доставки. Например: 05.07 после 18:00",
    )
    await state.update_data(prompt_message_id=callback.message.message_id)
    await callback.answer()


@router.message(Checkout.phone)
async def checkout_phone(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_checkout_prompt(bot, message.chat.id, state)
    data = await state.get_data()
    if message.text.strip() == "Оставить прошлые данные" and data.get("saved_phone"):
        await state.update_data(
            phone=data["saved_phone"],
            full_name=data["saved_full_name"],
            address=data["saved_address"],
        )
        await state.set_state(Checkout.delivery_datetime)
        await safe_delete(message)
        await send_checkout_prompt(
            message,
            state,
            "Хорошо, оставил прошлые ФИО, телефон и адрес.\nВведите дату и время доставки. Например: 05.07 после 18:00",
        )
        return
    await state.update_data(phone=message.text.strip())
    await state.set_state(Checkout.full_name)
    await safe_delete(message)
    await send_checkout_prompt(message, state, "Введите ФИО получателя.")


@router.message(Checkout.full_name)
async def checkout_full_name(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_checkout_prompt(bot, message.chat.id, state)
    await state.update_data(full_name=message.text.strip())
    await state.set_state(Checkout.address)
    await safe_delete(message)
    await send_checkout_prompt(message, state, "Введите адрес доставки.")


@router.message(Checkout.address)
async def checkout_address(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_checkout_prompt(bot, message.chat.id, state)
    await state.update_data(address=message.text.strip())
    await state.set_state(Checkout.delivery_datetime)
    await safe_delete(message)
    await send_checkout_prompt(message, state, "Введите дату и время доставки. Например: 05.07 после 18:00")


@router.message(Checkout.delivery_datetime)
async def checkout_delivery(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_checkout_prompt(bot, message.chat.id, state)
    await state.update_data(delivery_datetime=message.text.strip())
    await state.set_state(Checkout.comment)
    await safe_delete(message)
    await send_checkout_prompt(message, state, "Комментарий к заказу. Если комментария нет, напишите «нет».")


@router.message(Checkout.comment)
async def checkout_finish(message: Message, state: FSMContext, db: Database, bot: Bot, config: Config) -> None:
    await delete_checkout_prompt(bot, message.chat.id, state)
    data = await state.get_data()
    comment = "" if message.text.strip().lower() in {"нет", "-", "no"} else message.text.strip()
    await safe_delete(message)
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
        sent = await message.answer(text, reply_markup=main_menu())
        await remember_active_screen(state, sent)
        return
    order = await db.order(order_id)
    items = await db.order_items(order_id)
    sent = await message.answer(
        order_text(order, items) + "\n\nНажмите кнопку оплаты. Сейчас это тестовая кнопка-заглушка.",
        reply_markup=pay_order(order_id),
    )
    await remember_active_screen(state, sent)
    if config.admin_notify_id:
        await bot.send_message(
            config.admin_notify_id,
            "Новый заказ ожидает оплаты:\n\n" + order_text(order, items, admin=True),
        )


@router.callback_query(F.data.startswith("pay:"))
async def pay(callback: CallbackQuery, db: Database, bot: Bot, config: Config, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[1])
    ok, text = await db.mark_paid_and_write_off_stock(order_id, callback.from_user.id)
    order = await db.order(order_id)
    if not ok:
        screen = await safe_edit_or_answer(callback.message, text + "\nМожно изменить заказ или написать магазину.")
        await remember_active_screen(state, screen)
        await callback.answer("Оплата не прошла", show_alert=True)
        return
    items = await db.order_items(order_id)
    screen = await safe_edit_or_answer(callback.message, text + "\n\n" + order_text(order, items))
    await remember_active_screen(state, screen)
    if config.admin_notify_id:
        await bot.send_message(
            config.admin_notify_id,
            "Заказ оплачен, склад списан:\n\n" + order_text(order, items, admin=True),
        )
    await callback.answer("Оплачено")


@router.message(F.text == "Мои заказы")
@router.callback_query(F.data == "my_orders")
async def my_orders(event: Message | CallbackQuery, db: Database, state: FSMContext, bot: Bot) -> None:
    user_id = event.from_user.id
    orders = await db.orders(customer_id=user_id)
    target = event.message if isinstance(event, CallbackQuery) else event
    await delete_active_screen(bot, target.chat.id, state, keep_message_id=target.message_id if isinstance(event, CallbackQuery) else None)
    if isinstance(event, Message):
        await safe_delete(event)
    if not orders:
        sent = await target.answer("У вас пока нет заказов.")
        await remember_active_screen(state, sent)
    else:
        text = "Ваши заказы:\n\n" + "\n".join(user_order_summary_line(order) for order in orders[:10])
        sent = await target.answer(text, reply_markup=user_orders_list(orders[:10]))
        await remember_active_screen(state, sent)
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data.startswith("user_order_detail:"))
async def user_order_detail(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    order_id = int(callback.data.split(":")[1])
    order = await db.order(order_id)
    if not order or int(order["customer_id"]) != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    items = await db.order_items(order_id)
    screen = await safe_edit_or_answer(callback.message, order_text(order, items))
    await remember_active_screen(state, screen)
    await callback.answer()


@router.message(F.text == "Мои данные")
async def my_data(message: Message, db: Database, state: FSMContext, bot: Bot) -> None:
    await safe_delete(message)
    await delete_active_screen(bot, message.chat.id, state)
    customer = await db.fetch_one("SELECT * FROM customers WHERE telegram_id = ?", (message.from_user.id,))
    if not customer:
        sent = await message.answer("Данных пока нет. Они сохранятся после первого заказа.")
        await remember_active_screen(state, sent)
        return
    sent = await message.answer(
        "Ваши сохраненные данные:\n"
        f"ФИО: {customer.get('full_name') or '-'}\n"
        f"Телефон: {customer.get('phone') or '-'}\n"
        f"Адрес: {customer.get('address') or '-'}\n\n"
        "При новом заказе можно ввести другие данные, бот обновит карточку."
    )
    await remember_active_screen(state, sent)
