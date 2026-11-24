import asyncio
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

from database import (
    add_booking,
    delete_booking,
    get_all_bookings,
    get_booked_times,
    get_booking_by_id,
    get_unreminded_bookings,
    get_user_bookings,
    init_db,
    mark_as_reminded,
)

load_dotenv(override=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 943077302

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

SERVICES = {
    "s1": "Мужская стрижка — 1 500 ₽",
    "s2": "Стрижка + Борода — 2 200 ₽",
    "s3": "Моделирование бороды — 1 000 ₽",
    "s4": "Королевское бритьё — 1 300 ₽",
}

MASTERS = {
    "m1": "Артём (Топ-барбер)",
    "m2": "Максим (Барбер)",
    "m3": "Денис (Старший барбер)",
}

TIME_SLOTS = ["10:00", "11:30", "13:00", "14:30", "16:00", "17:30", "19:00", "20:30"]
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


class BookingState(StatesGroup):
    choosing_service = State()
    choosing_master = State()
    choosing_date = State()
    choosing_time = State()
    entering_name = State()
    entering_phone = State()


# --- КЛАВИАТУРЫ ---

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✂️ Записаться онлайн")],
        [KeyboardButton(text="📅 Мои записи")],
        [KeyboardButton(text="💈 Услуги и цены"), KeyboardButton(text="📍 Адрес и контакты")],
    ],
    resize_keyboard=True,
)

cancel_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True,
)

phone_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Отправить мой номер", request_contact=True)],
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
)


def build_services_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=title, callback_data=f"srv:{code}")]
        for code, title in SERVICES.items()
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отменить запись", callback_data="abort")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_masters_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"💈 {name}", callback_data=f"mst:{code}")]
        for code, name in MASTERS.items()
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отменить запись", callback_data="abort")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_dates_kb() -> InlineKeyboardMarkup:
    buttons = []
    today = datetime.now()
    for i in range(5):
        day = today + timedelta(days=i)
        iso_date = day.strftime("%Y-%m-%d")
        weekday = WEEKDAYS_RU[day.weekday()]
        label = f"Сегодня, {day.strftime('%d.%m')}" if i == 0 else f"{day.strftime('%d.%m')} ({weekday})"
        buttons.append([InlineKeyboardButton(text=f"📆 {label}", callback_data=f"dt:{iso_date}")])
    buttons.append([InlineKeyboardButton(text="❌ Отменить запись", callback_data="abort")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_times_kb(free_slots: list[str]) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for slot in free_slots:
        row.append(InlineKeyboardButton(text=f"🕒 {slot}", callback_data=f"tm:{slot}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Выбрать другую дату", callback_data="back_to_dates")])
    rows.append([InlineKeyboardButton(text="❌ Отменить запись", callback_data="abort")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_date_ru(iso_date: str) -> str:
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return f"{dt.strftime('%d.%m.%Y')} ({WEEKDAYS_RU[dt.weekday()]})"


# --- ОСНОВНЫЕ КОМАНДЫ И РАЗДЕЛЫ ---

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "💈 <b>Добро пожаловать в барбершоп CUT & CRAFT!</b>\n\n"
        "Здесь вы можете за 30 секунд выбрать услугу, удобного мастера и свободное окно без звонков администратору.\n\n"
        "Выберите нужное действие в меню ниже 👇",
        reply_markup=main_menu,
        parse_mode="HTML",
    )


@dp.message(F.text == "❌ Отмена")
async def cancel_text(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Оформление записи отменено. Возвращаю главное меню 👇", reply_markup=main_menu)


@dp.callback_query(F.data == "abort")
async def cancel_inline(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Оформление записи отменено.")
    await callback.message.answer("Выберите действие в меню:", reply_markup=main_menu)
    await callback.answer()


@dp.message(F.text == "💈 Услуги и цены")
async def show_prices(message: Message):
    text = (
        "💈 <b>Прайс-лист CUT & CRAFT:</b>\n\n"
        "• <b>Мужская стрижка</b> — 1 500 ₽ <i>(60 мин)</i>\n"
        "• <b>Стрижка + Борода</b> — 2 200 ₽ <i>(90 мин)</i>\n"
        "• <b>Моделирование бороды</b> — 1 000 ₽ <i>(45 мин)</i>\n"
        "• <b>Королевское бритьё</b> — 1 300 ₽ <i>(45 мин)</i>\n\n"
        "В стоимость входит мытьё головы, укладка премиальной косметикой и напиток на выбор."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✂️ Записаться сейчас", callback_data="start_booking")]]
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.message(F.text == "📍 Адрес и контакты")
async def show_contacts(message: Message):
    await message.answer(
        "📍 <b>Где мы находимся:</b>\n\n"
        "• Адрес: ул. Центральная, 24 (вход со стороны сквера)\n"
        "• График работы: ежедневно с 10:00 до 21:00\n"
        "• Телефон администратора: +7 (999) 123-45-67\n\n"
        "Бесплатная парковка для гостей прямо перед входом.",
        parse_mode="HTML",
    )


# --- СЦЕНАРИЙ ОНЛАЙН-ЗАПИСИ ---

@dp.message(F.text == "✂️ Записаться онлайн")
async def start_booking_msg(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BookingState.choosing_service)
    await message.answer(
        "<b>Шаг 1 из 6.</b> Выберите услугу:",
        reply_markup=build_services_kb(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "start_booking")
async def start_booking_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(BookingState.choosing_service)
    await callback.message.answer(
        "<b>Шаг 1 из 6.</b> Выберите услугу:",
        reply_markup=build_services_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(BookingState.choosing_service, F.data.startswith("srv:"))
async def process_service(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":")[1]
    service_name = SERVICES[code]
    await state.update_data(service=service_name)
    await state.set_state(BookingState.choosing_master)

    await callback.message.edit_text(
        f"✅ Услуга: <b>{service_name}</b>\n\n"
        "<b>Шаг 2 из 6.</b> Выберите мастера:",
        reply_markup=build_masters_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(BookingState.choosing_master, F.data.startswith("mst:"))
async def process_master(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":")[1]
    master_name = MASTERS[code]
    await state.update_data(master=master_name)
    await state.set_state(BookingState.choosing_date)

    data = await state.get_data()
    await callback.message.edit_text(
        f"✅ Услуга: <b>{data['service']}</b>\n"
        f"✅ Мастер: <b>{master_name}</b>\n\n"
        "<b>Шаг 3 из 6.</b> Выберите удобную дату:",
        reply_markup=build_dates_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(BookingState.choosing_time, F.data == "back_to_dates")
async def back_to_dates(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingState.choosing_date)
    data = await state.get_data()
    await callback.message.edit_text(
        f"✅ Услуга: <b>{data['service']}</b>\n"
        f"✅ Мастер: <b>{data['master']}</b>\n\n"
        "<b>Шаг 3 из 6.</b> Выберите другую дату:",
        reply_markup=build_dates_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(BookingState.choosing_date, F.data.startswith("dt:"))
async def process_date(callback: CallbackQuery, state: FSMContext):
    iso_date = callback.data.split(":")[1]
    data = await state.get_data()
    master_name = data["master"]

    booked = await get_booked_times(master_name, iso_date)
    free_slots = [t for t in TIME_SLOTS if t not in booked]

    if not free_slots:
        await callback.answer("На эту дату у мастера нет свободных окон. Выберите другой день.", show_alert=True)
        return

    await state.update_data(booking_date=iso_date)
    await state.set_state(BookingState.choosing_time)

    await callback.message.edit_text(
        f"✅ Услуга: <b>{data['service']}</b>\n"
        f"✅ Мастер: <b>{master_name}</b>\n"
        f"✅ Дата: <b>{format_date_ru(iso_date)}</b>\n\n"
        "<b>Шаг 4 из 6.</b> Выберите свободное время:",
        reply_markup=build_times_kb(free_slots),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(BookingState.choosing_time, F.data.startswith("tm:"))
async def process_time(callback: CallbackQuery, state: FSMContext):
    chosen_time = callback.data.split(":", 1)[1]
    await state.update_data(booking_time=chosen_time)
    await state.set_state(BookingState.entering_name)

    data = await state.get_data()
    await callback.message.edit_text(
        f"✅ Услуга: <b>{data['service']}</b>\n"
        f"✅ Мастер: <b>{data['master']}</b>\n"
        f"✅ Дата и время: <b>{format_date_ru(data['booking_date'])} в {chosen_time}</b>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "<b>Шаг 5 из 6.</b> Введите ваше имя:",
        reply_markup=cancel_menu,
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(BookingState.entering_name)
async def process_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Пожалуйста, введите имя текстом.")
        return

    await state.update_data(client_name=message.text.strip())
    await state.set_state(BookingState.entering_phone)
    await message.answer(
        "<b>Шаг 6 из 6.</b> Нажмите кнопку <b>«📱 Отправить мой номер»</b> ниже или введите телефон вручную:",
        reply_markup=phone_menu,
        parse_mode="HTML",
    )


@dp.message(BookingState.entering_phone)
async def process_phone(message: Message, state: FSMContext):
    if message.contact:
        phone = message.contact.phone_number
    elif message.text:
        phone = message.text.strip()
    else:
        await message.answer("Отправьте контакт кнопкой или напишите номер телефона текстом.")
        return

    data = await state.get_data()
    username = f"@{message.from_user.username}" if message.from_user.username else "Скрыт"

    success = await add_booking(
        user_id=message.from_user.id,
        username=username,
        client_name=data["client_name"],
        phone=phone,
        service=data["service"],
        master=data["master"],
        booking_date=data["booking_date"],
        booking_time=data["booking_time"],
    )

    if not success:
        await state.set_state(BookingState.choosing_time)
        booked = await get_booked_times(data["master"], data["booking_date"])
        free_slots = [t for t in TIME_SLOTS if t not in booked]
        await message.answer(
            "⚠️ Пока вы вводили данные, это время успел забронировать другой клиент.\n"
            "Выберите другое свободное окошко:",
            reply_markup=build_times_kb(free_slots),
        )
        return

    pretty_date = format_date_ru(data["booking_date"])

    demo_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Тест: как придёт напоминание", callback_data="demo_rem")]
        ]
    )

    await message.answer(
        "🎉 <b>Вы успешно записаны в CUT & CRAFT!</b>\n\n"
        f"👤 <b>Имя:</b> {data['client_name']}\n"
        f"📞 <b>Телефон:</b> {phone}\n"
        f"✂️ <b>Услуга:</b> {data['service']}\n"
        f"💈 <b>Мастер:</b> {data['master']}\n"
        f"📆 <b>Дата и время:</b> {pretty_date} в {data['booking_time']}\n\n"
        "За 2 часа до визита я автоматически пришлю напоминание. "
        "Можете проверить эту функцию прямо сейчас по кнопке ниже 👇",
        reply_markup=demo_kb,
        parse_mode="HTML",
    )
    await message.answer("Главное меню снова доступно:", reply_markup=main_menu)

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "🔔 <b>Новая запись в барбершоп!</b>\n\n"
            f"👤 <b>Клиент:</b> {data['client_name']} ({username})\n"
            f"📞 <b>Телефон:</b> {phone}\n"
            f"✂️ <b>Услуга:</b> {data['service']}\n"
            f"💈 <b>Мастер:</b> {data['master']}\n"
            f"📆 <b>Когда:</b> {pretty_date} в {data['booking_time']}"
        ),
        parse_mode="HTML",
    )

    await state.clear()


@dp.callback_query(F.data == "demo_rem")
async def demo_reminder(callback: CallbackQuery):
    await callback.answer("Демо-напоминание придёт через 3 секунды!")
    await asyncio.sleep(3)

    records = await get_user_bookings(callback.from_user.id)
    if records:
        _, service, master, bk_date, bk_time = records[-1]
        details = f"✂️ <b>Услуга:</b> {service}\n💈 <b>Мастер:</b> {master}\n🕒 <b>Время:</b> {format_date_ru(bk_date)} в {bk_time}"
    else:
        details = "✂️ <b>Услуга:</b> Мужская стрижка\n💈 <b>Мастер:</b> Артём (Топ-барбер)\n🕒 <b>Время:</b> Сегодня в 16:00"

    await callback.message.answer(
        "⏰ <b>Напоминание о записи в CUT & CRAFT!</b>\n\n"
        "Ждём вас на стрижку уже через 2 часа:\n"
        f"{details}\n"
        "📍 Адрес: ул. Центральная, 24\n\n"
        "<i>(Это демонстрация автоматического уведомления для портфолио)</i>",
        parse_mode="HTML",
    )


# --- ЛИЧНЫЙ КАБИНЕТ И ОТМЕНА ЗАПИСЕЙ ---

@dp.message(F.text == "📅 Мои записи")
async def my_bookings(message: Message):
    records = await get_user_bookings(message.from_user.id)
    if not records:
        await message.answer(
            "У вас пока нет активных записей.\nНажмите <b>«✂️ Записаться онлайн»</b>, чтобы выбрать удобное время!",
            parse_mode="HTML",
        )
        return

    lines = ["📅 <b>Ваши активные записи:</b>\n"]
    buttons = []
    for bk_id, service, master, bk_date, bk_time in records:
        pretty_date = format_date_ru(bk_date)
        lines.append(f"• <b>{pretty_date} в {bk_time}</b> — {service} ({master})")
        buttons.append(
            [InlineKeyboardButton(text=f"❌ Отменить: {bk_date} в {bk_time}", callback_data=f"del_bk:{bk_id}")]
        )

    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("del_bk:"))
async def cancel_user_booking(callback: CallbackQuery):
    bk_id = int(callback.data.split(":")[1])
    await delete_booking(bk_id)
    await callback.message.edit_text(
        "✅ <b>Запись отменена.</b>\nВремя снова открыто для бронирования в общем расписании.",
        parse_mode="HTML",
    )
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"⚠️ Клиент @{callback.from_user.username or callback.from_user.id} отменил запись #{bk_id}.",
    )
    await callback.answer("Запись отменена")


# --- АДМИН-ПАНЕЛЬ ---

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    records = await get_all_bookings()
    if not records:
        await message.answer("📋 В базе пока нет активных записей.")
        return

    lines = ["📋 <b>Все активные записи:</b>\n"]
    buttons = []
    for bk_id, name, phone, username, service, master, bk_date, bk_time in records:
        pretty_date = format_date_ru(bk_date)
        lines.append(
            f"<b>#{bk_id}</b> | {pretty_date} в <b>{bk_time}</b>\n"
            f"👤 {name} ({username}) — {phone}\n"
            f"✂️ {service} | 💈 {master}\n"
        )
        buttons.append(
            [InlineKeyboardButton(text=f"❌ Удалить #{bk_id} ({name}, {bk_time})", callback_data=f"adm_del:{bk_id}")]
        )

    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("adm_del:"))
async def admin_delete_booking(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    bk_id = int(callback.data.split(":")[1])
    booking = await get_booking_by_id(bk_id)

    if not booking:
        await callback.answer("Эта запись уже была удалена.", show_alert=True)
        return

    user_id, client_name, service, master, bk_date, bk_time = booking
    await delete_booking(bk_id)

    try:
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"⚠️ <b>Здравствуйте, {client_name}!</b>\n\n"
                f"Администратор барбершопа CUT & CRAFT отменил вашу запись:\n"
                f"✂️ {service} ({master})\n"
                f"📆 {format_date_ru(bk_date)} в {bk_time}\n\n"
                "Вы можете выбрать другое удобное время в меню <b>«✂️ Записаться онлайн»</b>."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.message.edit_text(
        f"✅ Запись <b>#{bk_id}</b> ({client_name}, {bk_date} в {bk_time}) удалена.\n"
        "Клиент получил уведомление, а окошко снова свободно.",
        parse_mode="HTML",
    )
    await callback.answer("Запись удалена")


# --- ФОНОВЫЙ ПОМОЩНИК НАПОМИНАНИЙ ---

async def reminder_worker():
    while True:
        records = await get_unreminded_bookings()
        now = datetime.now()

        for bk_id, user_id, client_name, service, master, bk_date, bk_time in records:
            visit_dt = datetime.strptime(f"{bk_date} {bk_time}", "%Y-%m-%d %H:%M")
            time_left = visit_dt - now

            if timedelta(0) < time_left <= timedelta(hours=2):
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"⏰ <b>Напоминание о записи, {client_name}!</b>\n\n"
                            "Ждём вас в барбершопе <b>CUT & CRAFT</b> уже через 2 часа:\n"
                            f"✂️ <b>Услуга:</b> {service}\n"
                            f"💈 <b>Мастер:</b> {master}\n"
                            f"🕒 <b>Время:</b> {format_date_ru(bk_date)} в {bk_time}\n"
                            "📍 Адрес: ул. Центральная, 24"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                await mark_as_reminded(bk_id)

            elif time_left <= timedelta(0):
                await mark_as_reminded(bk_id)

        await asyncio.sleep(60)


# --- ЗАПУСК БОТА ---

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(reminder_worker())
    print("Бот онлайн-записи CUT & CRAFT запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())