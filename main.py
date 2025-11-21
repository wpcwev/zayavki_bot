import os
import asyncio
import json
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

# ==========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("TGTOKEN")
TARGET_CHAT_ID = -1002909872942 # id чата для публикации заявок

COUNTER_FILE = "counter.json"
TEMPLATES_FILE = "templates.json"

PUBLISH_CB = "publish_request"
CANCEL_CB = "cancel_request"
SAVE_TEMPLATE_CB = "save_template"
NO_TEMPLATE_CB = "no_template"
TEMPLATE_SELECT_PREFIX = "tpl:"
DELETE_TEMPLATE_PREFIX = "dtpl:"

# ==========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================

def load_json(path: str, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: str, data):
    p = Path(path)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_next_request_id() -> int:
    data = load_json(COUNTER_FILE, {"last_id": 0})
    last_id = int(data.get("last_id", 0)) + 1
    data["last_id"] = last_id
    save_json(COUNTER_FILE, data)
    return last_id


def get_user_templates(user_id: int):
    data = load_json(TEMPLATES_FILE, {})
    return data.get(str(user_id), [])


def save_user_templates(user_id: int, templates):
    data = load_json(TEMPLATES_FILE, {})
    data[str(user_id)] = templates
    save_json(TEMPLATES_FILE, data)


def format_amount_with_ruble(raw: str) -> str:
    """
    Берём то, что ввёл пользователь (возможно в несколько строк),
    и добавляем к каждой непустой строке знак ₽.
    """
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(f"{line} ₽" for line in lines)


# ==========================
# СОСТОЯНИЯ FSM
# ==========================

class RequestStates(StatesGroup):
    direction = State()
    amount = State()
    rate = State()
    bank = State()
    bank_custom = State()
    traffic = State()
    traffic_custom = State()
    exchange = State()
    conditions = State()
    conditions_custom = State()
    contact = State()
    confirm = State()
    template_name = State()


# ==========================
# КЛАВИАТУРЫ
# ==========================

def direction_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Принять RUB"),
                KeyboardButton(text="Отправить RUB"),
            ],
            [KeyboardButton(text="Использовать шаблон")],
            [KeyboardButton(text="Управлять шаблонами")],  # <--- ДОБАВИЛИ СТРОКУ
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )



def bank_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Любой банк (СБП)")],
            [KeyboardButton(text="Только Сбербанк")],
            [KeyboardButton(text="Только Т-Банк")],
            [KeyboardButton(text="✍️ Написать свои условия по банкам")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def traffic_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Личная карта")],
            [KeyboardButton(text="БТ (белый треугольник)")],
            [KeyboardButton(text="Процессинг")],
            [KeyboardButton(text="Свой обменник")],
            [KeyboardButton(text="Товарка")],
            [KeyboardButton(text="Обмен юаней")],
            [KeyboardButton(text="✍️ Другое (написать источник)")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def exchange_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Bybit"), KeyboardButton(text="HTX")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def conditions_receive_kb() -> ReplyKeyboardMarkup:
    # для направления "Принять RUB"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Чек PDF")],
            [KeyboardButton(text="Чек на почту")],
            [KeyboardButton(text="Одним платежом")],
            [KeyboardButton(text="Могу принять частями")],
            [KeyboardButton(text="✍️ Написать свои условия")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def conditions_send_kb() -> ReplyKeyboardMarkup:
    # для направления "Отправить RUB"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Одним платежом")],
            [KeyboardButton(text="Могу отправить частями")],
            [KeyboardButton(text="✍️ Написать свои условия")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
def back_to_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="В главное меню")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )



def new_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Создать новую заявку")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Использовать текущий контакт")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def preview_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать",
                    callback_data=PUBLISH_CB,
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=CANCEL_CB,
                )
            ],
        ]
    )


def after_publish_template_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💾 Сохранить как шаблон",
                    callback_data=SAVE_TEMPLATE_CB,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не сохранять",
                    callback_data=NO_TEMPLATE_CB,
                )
            ],
        ]
    )


# ==========================
# ХЭНДЛЕРЫ
# ==========================

async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я бот для создания заявок на обмен в чат "
        "<a href='https://t.me/+MLjt_rkqxpIwMjJi'>Заявки P2P</a>.\n\n"
        "Заявку в каком направлении вы хотите создать?",
        reply_markup=direction_kb(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    await state.set_state(RequestStates.direction)


async def new_request(message: types.Message, state: FSMContext):
    await cmd_start(message, state)


# ---------- Направление / шаблоны ----------

async def use_template(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    templates = get_user_templates(user_id)
    if not templates:
        await message.answer(
            "У тебя пока нет шаблонов.\n"
            "Создай заявку до конца, после публикации я предложу сохранить её как шаблон.",
            reply_markup=back_to_main_kb(),  # <-- ДОБАВИЛИ КНОПКУ
        )
        return
    ...


    buttons = []
    for idx, tpl in enumerate(templates):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=tpl.get("name", f"Шаблон {idx+1}"),
                    callback_data=f"{TEMPLATE_SELECT_PREFIX}{idx}",
                )
            ]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    # сообщение с шаблонами (inline-кнопки)
    await message.answer(
        "Выбери шаблон, который хочешь использовать:",
        reply_markup=kb,
    )

    # отдельным сообщением даём кнопку "В главное меню"
    await message.answer(
        "Если передумал, нажми «В главное меню».",
        reply_markup=back_to_main_kb(),
    )
async def manage_templates(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    templates = get_user_templates(user_id)

    if not templates:
        await message.answer(
            "У тебя пока нет шаблонов.",
            reply_markup=direction_kb(),
        )
        return

    buttons = []
    for idx, tpl in enumerate(templates):
        name = tpl.get("name", f"Шаблон {idx+1}")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 {name}",
                    callback_data=f"{DELETE_TEMPLATE_PREFIX}{idx}",
                )
            ]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "Выбери шаблон, который хочешь удалить:",
        reply_markup=kb,
    )

    # ДОБАВЛЯЕМ ЭТО ↓↓↓
    await message.answer(
        "Если передумал — нажми «В главное меню»",
        reply_markup=back_to_main_kb(),
    )


async def template_selected(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    if not data.startswith(TEMPLATE_SELECT_PREFIX):
        return

    user_id = callback.from_user.id
    templates = get_user_templates(user_id)

    try:
        idx = int(data.split(":", 1)[1])
    except Exception:
        await callback.answer("Ошибка шаблона", show_alert=True)
        return

    if idx < 0 or idx >= len(templates):
        await callback.answer("Шаблон не найден", show_alert=True)
        return

    tpl = templates[idx]

    await state.update_data(
        direction=tpl.get("direction"),
        bank=tpl.get("bank"),
        traffic=tpl.get("traffic"),
        exchange=tpl.get("exchange"),
        conditions=tpl.get("conditions"),
    )

    await callback.answer(f"Шаблон «{tpl.get('name', f'Шаблон {idx+1}')}» выбран.")
    await callback.message.answer(
        "Использую выбранный шаблон.\n\n"
        f"🔁 Направление: {tpl.get('direction')}\n"
        f"🏦 Банк: {tpl.get('bank')}\n"
        f"📥 Источник трафика: {tpl.get('traffic')}\n"
        f"📈 Биржа: {tpl.get('exchange')}\n"
        f"📄 Условия: {tpl.get('conditions')}\n\n"
        "Теперь введи суммы заявки одним сообщением.\n"
        "Можно несколько сумм, каждую с новой строки.\n"
        "Например: 100000\n20000-50000",
        reply_markup=ReplyKeyboardRemove(),
    )

    await state.set_state(RequestStates.amount)

async def delete_template_callback(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    if not data.startswith(DELETE_TEMPLATE_PREFIX):
        return

    user_id = callback.from_user.id
    templates = get_user_templates(user_id)

    try:
        idx = int(data.split(":", 1)[1])
    except Exception:
        await callback.answer("Ошибка удаления шаблона", show_alert=True)
        return

    if idx < 0 or idx >= len(templates):
        await callback.answer("Шаблон не найден", show_alert=True)
        return

    removed = templates.pop(idx)
    save_user_templates(user_id, templates)

    await callback.answer(f"Шаблон «{removed.get('name', 'без названия')}» удалён ✅", show_alert=True)

    # Перерисуем список оставшихся шаблонов
    if not templates:
        await callback.message.edit_text("Все шаблоны удалены.")
        return

    buttons = []
    for i, tpl in enumerate(templates):
        name = tpl.get("name", f"Шаблон {i+1}")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 {name}",
                    callback_data=f"{DELETE_TEMPLATE_PREFIX}{i}",
                )
            ]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        "Выбери шаблон, который хочешь удалить:",
        reply_markup=kb,
    )

async def back_to_main(message: types.Message, state: FSMContext):
    # просто перезапускаем сценарий
    await cmd_start(message, state)


async def direction_chosen(message: types.Message, state: FSMContext):
    if message.text not in ["Принять RUB", "Отправить RUB"]:
        await message.answer(
            "Пожалуйста, выберите направление с кнопок ниже.",
            reply_markup=direction_kb(),
        )
        return

    await state.update_data(direction=message.text)
    await message.answer(
        "Введите суммы заявки одним сообщением.\n\n"
        "Можно несколько сумм, каждую с новой строки.\n"
        "Важно: каждая строка должна начинаться с цифры.\n\n"
        "Примеры:\n"
        "<code>150000</code>\n"
        "<code>100000-300000</code>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(RequestStates.amount)


# ---------- Суммы (много строк в одном сообщении) ----------

async def amount_chosen(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer(
            "Пожалуйста, введите хотя бы одну сумму.\n\n"
            "Можно несколько сумм, каждую с новой строки.",
        )
        return

    # проверяем, что каждая непустая строка начинается с цифры
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if not line[0].isdigit():
            await message.answer(
                "Каждая строка с суммой должна начинаться с цифры.\n\n"
                "Примеры допустимого ввода:\n"
                "<code>150000</code>\n"
                "<code>100000-300000</code>\n\n"
                "Можно несколько строк подряд.",
                parse_mode=ParseMode.HTML,
            )
            return

    await state.update_data(amount=text)
    await message.answer(
        "Теперь введите курс обмена.\n\n"
        "Например: <code>83,15</code> .",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(RequestStates.rate)


# ---------- Остальной сценарий ----------

async def rate_chosen(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("Пожалуйста, введите курс обмена.")
        return

    await state.update_data(rate=text)

    data = await state.get_data()
    # Если заявка создана из шаблона и у нас уже есть
    # bank, traffic, exchange, conditions — сразу к контакту
    if data.get("bank") and data.get("traffic") and data.get("exchange") and data.get("conditions"):
        await ask_contact(message, state)
        return

    await message.answer(
        "Выберите банк:",
        reply_markup=bank_kb(),
    )
    await state.set_state(RequestStates.bank)


async def bank_chosen(message: types.Message, state: FSMContext):
    text = message.text.strip()

    if text == "✍️ Написать свои условия по банкам":
        await message.answer(
            "Напишите свои условия по банкам (например, «только Сбер/Т-Банк, без других»).",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(RequestStates.bank_custom)
        return

    if text not in [
        "Любой банк (СБП)",
        "Только Сбербанк",
        "Только Т-Банк",
    ]:
        await message.answer(
            "Пожалуйста, выберите вариант с кнопок.",
            reply_markup=bank_kb(),
        )
        return

    await state.update_data(bank=text)
    await message.answer(
        "Выберите источник трафика:",
        reply_markup=traffic_kb(),
    )
    await state.set_state(RequestStates.traffic)


async def bank_custom_entered(message: types.Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(bank=text)

    await message.answer(
        "Выберите источник трафика:",
        reply_markup=traffic_kb(),
    )
    await state.set_state(RequestStates.traffic)


async def traffic_chosen(message: types.Message, state: FSMContext):
    text = message.text.strip()

    if text == "✍️ Другое (написать источник)":
        await message.answer(
            "Напишите источник трафика (например, «свои клиенты», «за рекламу» и т.п.).",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(RequestStates.traffic_custom)
        return

    valid = [
        "Личная карта",
        "БТ (белый треугольник)",
        "Процессинг",
        "Свой обменник",
        "Товарка",
        "Обмен юаней",
    ]
    if text not in valid:
        await message.answer(
            "Пожалуйста, выберите источник трафика с кнопок.",
            reply_markup=traffic_kb(),
        )
        return

    await state.update_data(traffic=text)
    await message.answer(
        "Выберите биржу, на которой размещена заявка:",
        reply_markup=exchange_kb(),
    )
    await state.set_state(RequestStates.exchange)


async def traffic_custom_entered(message: types.Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(traffic=text)

    await message.answer(
        "Выберите биржу, на которой размещена заявка:",
        reply_markup=exchange_kb(),
    )
    await state.set_state(RequestStates.exchange)


async def exchange_chosen(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text not in ["Bybit", "HTX"]:
        await message.answer(
            "Пожалуйста, выберите биржу с кнопок.",
            reply_markup=exchange_kb(),
        )
        return

    await state.update_data(exchange=text)
    data = await state.get_data()
    direction = data.get("direction")

    if direction == "Принять RUB":
        kb = conditions_receive_kb()
    else:
        kb = conditions_send_kb()

    await message.answer(
        "Выберите дополнительные условия:",
        reply_markup=kb,
    )
    await state.set_state(RequestStates.conditions)


async def conditions_chosen(message: types.Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    direction = data.get("direction")

    if text == "✍️ Написать свои условия":
        await message.answer(
            "Напишите свои условия по сделке (или «без доп. условий»).",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(RequestStates.conditions_custom)
        return

    if direction == "Принять RUB":
        valid = [
            "Чек PDF",
            "Чек на почту",
            "Одним платежом",
            "Могу принять частями",
        ]
    else:
        valid = [
            "Одним платежом",
            "Могу отправить частями",
        ]

    if text not in valid:
        if direction == "Принять RUB":
            kb = conditions_receive_kb()
        else:
            kb = conditions_send_kb()

        await message.answer(
            "Пожалуйста, выберите вариант с кнопок.",
            reply_markup=kb,
        )
        return

    await state.update_data(conditions=text)
    await ask_contact(message, state)


async def conditions_custom_entered(message: types.Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(conditions=text)
    await ask_contact(message, state)


async def ask_contact(message: types.Message, state: FSMContext):
    username = message.from_user.username

    if username:
        suggested = f"@{username}"
        await state.update_data(suggested_contact=suggested)

        await message.answer(
            f"Укажи контакт для связи по заявке.\n\n"
            f"Могу использовать твой текущий контакт: <b>{suggested}</b>\n\n"
            f"– Нажми «Использовать текущий контакт»\n"
            f"– Или введи другой контакт, начинающийся с <code>@</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=contact_kb(),
        )
    else:
        await message.answer(
            "Укажи контакт для связи по заявке.\n\n"
            "Введи ник, начинающийся с символа <code>@</code> (например, <code>@username</code>).",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )

    await state.set_state(RequestStates.contact)


async def contact_chosen(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = message.text.strip()
    suggested = data.get("suggested_contact")

    if text == "Использовать текущий контакт" and suggested:
        contact = suggested
    else:
        if not text.startswith("@"):
            await message.answer(
                "Пожалуйста, укажи контакт, начинающийся с символа @.\n"
                "Например: <code>@username</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        contact = text

    await state.update_data(contact=contact)

    # формируем черновик заявки + номер
    data = await state.get_data()

    direction = data.get("direction")
    raw_amount = data.get("amount")
    rate = data.get("rate")
    bank = data.get("bank")
    traffic = data.get("traffic")
    exchange = data.get("exchange")
    conditions = data.get("conditions")
    contact = data.get("contact")

    if direction == "Принять RUB":
        direction_label = "Приму RUB"
    else:
        direction_label = "Отправлю RUB"

    request_id = get_next_request_id()
    await state.update_data(request_id=request_id)

    user_mention = message.from_user.mention_html()
    amount_formatted = format_amount_with_ruble(raw_amount or "")

    text_out = (
        f"📩 <b>Заявка №{request_id}</b>\n\n"
        f"👤 От: {user_mention}\n\n"
        f"🔁 Направление: <b>{direction_label}</b>\n"
        f"💰 Сумма:\n<b>{amount_formatted}</b>\n\n"
        f"💱 Курс: <b>{rate}</b>\n"
        f"🏦 Банк: <b>{bank}</b>\n"
        f"📥 Источник трафика: <b>{traffic}</b>\n"
        f"📈 Биржа: <b>{exchange}</b>\n"
        f"📄 Условия: <b>{conditions}</b>\n"
        f"📲 Контакт для связи: <b>{contact}</b>\n"
    )

    await state.update_data(preview_text=text_out)

    # автопроверка перед публикацией
    await message.answer(
        "Проверь заявку перед публикацией:\n\n"
        f"{text_out}\n"
        "Если всё верно — нажми «Опубликовать». Если нет — «Отменить» и создай заново.",
        parse_mode=ParseMode.HTML,
        reply_markup=preview_kb(),
    )

    await state.set_state(RequestStates.confirm)


# ---------- Callback: публикация / отмена ----------

async def callback_publish(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    text_out = data.get("preview_text")
    request_id = data.get("request_id")

    if not text_out:
        await callback.answer("Нет заявки для публикации", show_alert=True)
        return

    if TARGET_CHAT_ID == 0:
        await callback.message.answer(
            "⚠️ TARGET_CHAT_ID не задан. Заявка не может быть отправлена в чат.\n\n"
            "Сейчас я просто покажу, как она выглядит:",
            parse_mode=ParseMode.HTML,
        )
        await callback.message.answer(text_out, parse_mode=ParseMode.HTML)
    else:
        try:
            await bot.send_message(
                chat_id=TARGET_CHAT_ID,
                text=text_out,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await callback.message.answer(
                "⚠️ Не удалось отправить заявку в целевой чат. "
                "Проверь, что бот добавлен в этот чат и имеет право писать сообщения.",
            )
            await callback.message.answer(text_out, parse_mode=ParseMode.HTML)

    await callback.answer("Заявка опубликована!")

    await callback.message.answer(
        f"✅ Заявка №{request_id} отправлена в чат!",
        reply_markup=new_request_kb(),
    )

    # предложение сохранить шаблон
    await callback.message.answer(
        "Хочешь сохранить эту заявку как шаблон для быстрых заявок в будущем?",
        reply_markup=after_publish_template_kb(),
    )
    # состояние пока не чистим — данные нужны для шаблона


async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Заявка отменена")
    await callback.message.answer(
        "Заявка отменена. Чтобы создать новую — нажми «Создать новую заявку» или отправь /start.",
        reply_markup=new_request_kb(),
    )


# ---------- Callback: шаблоны после публикации ----------

async def callback_save_template(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "Введи название шаблона (например, «Bybit Т-Банк личка»):",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(RequestStates.template_name)


async def callback_no_template(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Ок, без шаблона.")
    await state.clear()
    await callback.message.answer(
        "Ок, шаблон не сохранён.",
        reply_markup=new_request_kb(),
    )


async def template_name_entered(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Название шаблона не может быть пустым. Введи что-нибудь осмысленное.")
        return

    data = await state.get_data()
    user_id = message.from_user.id

    template = {
        "name": name,
        "direction": data.get("direction"),
        "bank": data.get("bank"),
        "traffic": data.get("traffic"),
        "exchange": data.get("exchange"),
        "conditions": data.get("conditions"),
    }

    templates = get_user_templates(user_id)
    templates.append(template)
    save_user_templates(user_id, templates)

    await message.answer(
        f"Шаблон «{name}» сохранён ✅\n\n"
        "В следующий раз можешь нажать «Использовать шаблон» при создании заявки.",
        reply_markup=new_request_kb(),
    )
    await state.clear()


# ---------- Системные команды ----------

async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Ок, заявка отменена. Чтобы создать новую — отправь /start.",
        reply_markup=ReplyKeyboardRemove(),
    )


# ==========================
# MAIN
# ==========================

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Команды (только в личке)
    dp.message.register(cmd_start, CommandStart(), F.chat.type == ChatType.PRIVATE)
    dp.message.register(
        cmd_cancel,
        Command(commands=["cancel", "отмена"]),
        F.chat.type == ChatType.PRIVATE,
    )

    # Кнопка "Создать новую заявку"
    dp.message.register(
        new_request,
        F.text == "Создать новую заявку",
        F.chat.type == ChatType.PRIVATE,
    )
    dp.message.register(
        back_to_main,
        F.text == "В главное меню",
        F.chat.type == ChatType.PRIVATE,
    )


    # Direction / шаблоны
    dp.message.register(
        use_template,
        RequestStates.direction,
        F.text == "Использовать шаблон",
        F.chat.type == ChatType.PRIVATE,
    )
    dp.callback_query.register(
        template_selected,
        F.data.startswith(TEMPLATE_SELECT_PREFIX),
    )
    # Управление шаблонами (из главного меню)
    dp.message.register(
        manage_templates,
        RequestStates.direction,
        F.text == "Управлять шаблонами",
        F.chat.type == ChatType.PRIVATE,
    )


    # FSM-цепочка (приватный чат)
    dp.message.register(direction_chosen, RequestStates.direction, F.chat.type == ChatType.PRIVATE)
    dp.message.register(amount_chosen, RequestStates.amount, F.chat.type == ChatType.PRIVATE)
    dp.message.register(rate_chosen, RequestStates.rate, F.chat.type == ChatType.PRIVATE)
    dp.message.register(bank_chosen, RequestStates.bank, F.chat.type == ChatType.PRIVATE)
    dp.message.register(bank_custom_entered, RequestStates.bank_custom, F.chat.type == ChatType.PRIVATE)
    dp.message.register(traffic_chosen, RequestStates.traffic, F.chat.type == ChatType.PRIVATE)
    dp.message.register(traffic_custom_entered, RequestStates.traffic_custom, F.chat.type == ChatType.PRIVATE)
    dp.message.register(exchange_chosen, RequestStates.exchange, F.chat.type == ChatType.PRIVATE)
    dp.message.register(conditions_chosen, RequestStates.conditions, F.chat.type == ChatType.PRIVATE)
    dp.message.register(conditions_custom_entered, RequestStates.conditions_custom, F.chat.type == ChatType.PRIVATE)
    dp.message.register(contact_chosen, RequestStates.contact, F.chat.type == ChatType.PRIVATE)
    dp.message.register(template_name_entered, RequestStates.template_name, F.chat.type == ChatType.PRIVATE)

    # Callback-и
    dp.callback_query.register(callback_publish, F.data == PUBLISH_CB)
    dp.callback_query.register(callback_cancel, F.data == CANCEL_CB)
    dp.callback_query.register(callback_save_template, F.data == SAVE_TEMPLATE_CB)
    dp.callback_query.register(callback_no_template, F.data == NO_TEMPLATE_CB)

    dp.callback_query.register(
        delete_template_callback,
        F.data.startswith(DELETE_TEMPLATE_PREFIX),
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
