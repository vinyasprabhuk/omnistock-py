"""Unit tests for the Dice-coefficient item matcher -- ported from the
`string-similarity` npm package's exact algorithm. These pin down the exact
math, independent of any database state."""
import pytest

from app.services.match_item import compare_two_strings, normalize


def test_normalize_trims_uppercases_collapses_whitespace():
    assert normalize("  sun   flower   oil  ") == "SUN FLOWER OIL"


class TestCompareTwoStrings:
    def test_identical_strings_score_1(self):
        assert compare_two_strings("SALT", "SALT") == 1.0

    def test_both_empty_scores_1(self):
        assert compare_two_strings("", "") == 1.0

    def test_single_char_strings_score_0(self):
        # len < 2 on either side -> 0 (identical-strings check only short-circuits
        # when the strings are EQUAL, which "A" vs "B" isn't)
        assert compare_two_strings("A", "B") == 0.0

    def test_single_char_identical_strings_still_score_1(self):
        # The identical-strings fast path runs before the length check, so
        # two equal single-char strings score 1, not 0.
        assert compare_two_strings("A", "A") == 1.0

    def test_completely_different_scores_low(self):
        assert compare_two_strings("SALT", "PEPPER") < 0.2

    def test_whitespace_is_stripped_before_bigram_comparison(self):
        # "RED CHILLI" and "REDCHILLI" must compare as if spaces never existed --
        # this is the double-normalization quirk noted in match_item.py.
        assert compare_two_strings("RED CHILLI", "REDCHILLI") == 1.0

    def test_known_dice_coefficient_value(self):
        # "NIGHT" vs "NACHT": bigrams NI,IG,GH,HT vs NA,AC,CH,HT -> 1 shared / 8 total = 0.25
        score = compare_two_strings("NIGHT", "NACHT")
        assert score == pytest.approx(0.25)

    def test_partial_overlap_scores_between_0_and_1(self):
        score = compare_two_strings("SUNFLOWER OIL", "SUNFLOWER")
        assert 0 < score < 1


class TestMatchItemThresholds:
    """The confidence-band logic itself (>=90 AUTO, >=70 REVIEW, else MANUAL)
    is exercised via match_item(), which needs a DB -- see test_calculations.py
    for a DB-backed integration test. Pure threshold-boundary logic is
    re-verified here directly against the same constants."""

    def test_threshold_constants(self):
        from app.services.match_item import AUTO_THRESHOLD, REVIEW_THRESHOLD
        assert AUTO_THRESHOLD == 90
        assert REVIEW_THRESHOLD == 70
