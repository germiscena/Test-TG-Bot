from aiogram.fsm.state import State, StatesGroup


class ReportStates(StatesGroup):
    idle = State()
    clarifying_item = State()  # Выбор одного из кандидатов при неоднозначности
    reviewing_draft = State()  # Просмотр итогового списка перед подтверждением
    editing_volume = State()   # Ввод нового числа для конкретной позиции
    deleting_item = State()    # Выбор позиции для удаления
