"""Unit tests for app/formatting.py -- especially the Indian (lakh/crore)
digit grouping, which has no stdlib equivalent and is easy to get subtly
wrong at the 5- and 7-digit boundaries."""
from app.formatting import fmt, money, money_grouped, pct


class TestFmt:
    def test_whole_number_renders_bare(self):
        assert fmt(5) == "5"
        assert fmt(0) == "0"

    def test_fractional_renders_two_decimals(self):
        assert fmt(5.5) == "5.50"
        assert fmt(2.299999999999997) == "2.30"  # matches live-app float noise, rounds cleanly for display


class TestMoney:
    def test_plain_two_decimal_no_grouping(self):
        assert money(1234567.5) == "₹1234567.50"

    def test_zero(self):
        assert money(0) == "₹0.00"


class TestMoneyGrouped:
    def test_below_1000_no_grouping_needed(self):
        assert money_grouped(500) == "₹500.00"

    def test_thousands_boundary(self):
        assert money_grouped(1000) == "₹1,000.00"

    def test_lakh_grouping_ten_thousands(self):
        # Indian grouping: last 3 digits, then groups of 2 -- NOT groups of 3.
        assert money_grouped(123456.78) == "₹1,23,456.78"

    def test_ten_lakh(self):
        assert money_grouped(1013274.24) == "₹10,13,274.24"

    def test_crore_grouping(self):
        assert money_grouped(12345678.9) == "₹1,23,45,678.90"

    def test_negative_amount(self):
        assert money_grouped(-1500) == "₹-1,500.00"

    def test_rounding_carry_at_two_decimals(self):
        # 4.999 -> whole=4 frac=99.9 rounds to 100 -> must carry to whole=5, not print ".100"
        result = money_grouped(4.999)
        assert result == "₹5.00"


class TestPct:
    def test_positive_gets_explicit_plus_sign(self):
        assert pct(5.5) == "+5.5%"

    def test_negative_keeps_native_minus(self):
        assert pct(-12.34) == "-12.3%"

    def test_none_renders_em_dash(self):
        assert pct(None) == "—"

    def test_zero_gets_plus_sign(self):
        assert pct(0) == "+0.0%"
