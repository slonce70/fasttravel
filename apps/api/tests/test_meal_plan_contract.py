from shared.meal_plans import CANONICAL_LABELS_UK, RAW_LABELS_UK, RAW_TO_CANONICAL
from shared.text_uk import format_meal_plan

from src.services import meal_normalizer


def test_meal_plan_codes_have_one_shared_source_for_api_and_copy() -> None:
    assert meal_normalizer.MEAL_CANONICAL == RAW_TO_CANONICAL
    assert meal_normalizer.labels() == CANONICAL_LABELS_UK


def test_all_inclusive_expands_for_category_filters_but_formats_raw_codes_precisely() -> None:
    assert meal_normalizer.raw_codes_for("all_inclusive") == ["AI", "UAI"]
    assert meal_normalizer.raw_codes_for("AI") == ["AI"]
    assert format_meal_plan("AI") == RAW_LABELS_UK["AI"]
    assert format_meal_plan("UAI") == RAW_LABELS_UK["UAI"]
