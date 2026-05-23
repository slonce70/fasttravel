"""Normalizer logic that we can unit-test without VCR cassettes.

Source-specific normalizer tests (ittour, tbo, farvater) belong in
their own files with recorded cassettes. Here we test the shared
contract: meal-plan canonicalization.
"""
from __future__ import annotations

import pytest

from src.normalizers.base import normalize_meal_plan


@pytest.mark.parametrize("raw,expected", [
    ("All Inclusive", "AI"),
    ("all inclusive", "AI"),
    ("AI", "AI"),
    ("Ultra All Inclusive", "UAI"),
    ("UAI", "UAI"),
    ("Half Board", "HB"),
    ("hb", "HB"),
    ("Bed and Breakfast", "BB"),
    ("Breakfast", "BB"),
    ("Full Board", "FB"),
    ("FB", "FB"),
    ("Room Only", "RO"),
    ("No Meal", "RO"),
    ("RO", "RO"),
])
def test_canonical_mapping(raw, expected):
    assert normalize_meal_plan(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "    "])
def test_empty_inputs_become_other(raw):
    assert normalize_meal_plan(raw) == "OTHER"


def test_unknown_vocabulary_becomes_other():
    """We refuse to silently force-map unknown strings. New vocabulary
    SHOULD reach the operator's eyes as 'OTHER' so they notice and add
    an alias."""
    assert normalize_meal_plan("Brunch+Dinner") == "OTHER"
