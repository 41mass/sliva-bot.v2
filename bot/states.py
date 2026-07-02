from aiogram.fsm.state import State, StatesGroup


class AdminLogin(StatesGroup):
    password = State()


class Checkout(StatesGroup):
    phone = State()
    full_name = State()
    address = State()
    delivery_datetime = State()
    comment = State()


class AdminProduct(StatesGroup):
    add_name = State()
    add_price = State()
    add_stock = State()
    edit_price = State()
    add_stock_qty = State()
    orders_by_product = State()
