import pytest

from services.normalize import normalize_amount, normalize_date


@pytest.mark.parametrize("text,expected", [
    ("12/03/2024", "2024-03-12"),
    ("2024-03-12", "2024-03-12"),
    ("12 March 2024", "2024-03-12"),
    ("March 12th, 2024", "2024-03-12"),
    ("12-Mar-2024", "2024-03-12"),
    ("25/12/24", "2024-12-25"),
    ("14th day of April 2022", "2022-04-14"),
    ("November 23,2021", "2021-11-23"),
    ("February 19, 2025 03:42 PST", "2025-02-19"),
    ("2/19/2025 3:42:45 AM", "2025-02-19"),
    ("02 Oct 2026 (2026-10-02)", "2026-10-02"),
    ("1st May, 2018", "2018-05-01"),
    ("not a date", None),
    ("", None),
])
def test_normalize_date_day_first(text, expected):
    assert normalize_date(text, "DMY") == expected


def test_normalize_date_month_first():
    assert normalize_date("03/12/2024", "MDY") == "2024-03-12"


def test_normalize_date_falls_back_when_day_over_12():
    assert normalize_date("03/25/2024", "DMY") == "2024-03-25"


@pytest.mark.parametrize("text,amount,currency", [
    ("PKR 1,500", "1500.00", "PKR"),
    ("Rs. 25,000.50", "25000.50", "PKR"),
    ("$ 99.9", "99.90", "USD"),
    ("1 234 567", "1234567.00", None),
    ("N/A", None, None),
])
def test_normalize_amount(text, amount, currency):
    assert normalize_amount(text) == (amount, currency)
