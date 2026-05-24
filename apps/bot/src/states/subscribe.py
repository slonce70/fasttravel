"""FSM for the /subscribe wizard.

3 steps mirror the subset of the search wizard that matters for
matching: country → max budget → min stars. Meal plan and exact dates
are intentionally excluded — too many filters and alerts become quiet.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SubscribeState(StatesGroup):
    country = State()
    budget = State()
    stars = State()
