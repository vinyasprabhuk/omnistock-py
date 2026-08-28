"""Unit tests for app/services/normalize_unit.py. Unit FAMILIES are never
cross-converted -- only weight-unit spellings collapse into KG."""
from app.services.normalize_unit import normalize_unit


def test_weight_units_convert_to_kg():
    result = normalize_unit(500, "GM")
    assert result == {"qty": 0.5, "unit": "KG", "ambiguous": False}


def test_kg_stays_kg_no_rescale():
    result = normalize_unit(2, "KG")
    assert result == {"qty": 2, "unit": "KG", "ambiguous": False}


def test_litre_family_never_converts_to_kg():
    result = normalize_unit(2, "LITRE")
    assert result["unit"] == "LITRE"
    assert result["qty"] == 2  # unchanged -- no cross-family conversion


def test_pack_and_pcs_families_stay_separate():
    assert normalize_unit(1, "PACK")["unit"] == "PACK"
    assert normalize_unit(1, "PCS")["unit"] == "PCS"


def test_unit_spelling_variants_collapse_to_canonical():
    assert normalize_unit(1, "PIECE")["unit"] == "PCS"
    assert normalize_unit(1, "PIECES")["unit"] == "PCS"
    assert normalize_unit(1, "LIT")["unit"] == "LITRE"
    assert normalize_unit(1, "BOTTLE")["unit"] == "BOTTLES"


def test_missing_unit_is_ambiguous():
    result = normalize_unit(5, None)
    assert result == {"qty": 5, "unit": "", "ambiguous": True}


def test_blank_unit_is_ambiguous():
    result = normalize_unit(5, "   ")
    assert result["ambiguous"] is True


def test_unrecognized_unit_passed_through_not_guessed():
    result = normalize_unit(5, "CRATE")
    assert result == {"qty": 5, "unit": "CRATE", "ambiguous": True}


def test_unit_matching_is_case_insensitive():
    assert normalize_unit(1, "kg")["unit"] == "KG"
    assert normalize_unit(1, "Litre")["unit"] == "LITRE"
