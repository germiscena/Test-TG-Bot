from aiogram.fsm.state import State, StatesGroup


class ReportStates(StatesGroup):
    idle = State()
    clarifying_item = State()
    reviewing_draft = State()
    editing_volume = State()
    adding_item = State()
    deleting_item = State()
