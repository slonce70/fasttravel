"""FSM states for the /search wizard.

7 steps, one per filter facet. Picking a country puts the user into
`choosing_nights`; pressing «◀ Назад» moves back; «❌ Скасувати» clears
state and returns to the main menu.

The values themselves are stored in the FSM context via
`state.update_data(...)` — never on the State object itself. State just
tags where the user is in the flow so message handlers know which
callback prefix to expect.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SearchState(StatesGroup):
    choosing_hotel_query = State()
    choosing_country = State()
    choosing_nights = State()
    choosing_when = State()
    choosing_budget = State()
    choosing_meal = State()
    choosing_stars = State()
    viewing_results = State()
