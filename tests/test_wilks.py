from decimal import Decimal as D

import pytest

from powerlifting_bot.domain.wilks import parse_weight, wilks


@pytest.mark.parametrize(
    "sex,body,lift,expected",
    [
        ("male", "100", "100", "60.86"),
        ("female", "60", "100", "111.49"),
    ],
)
def test_reference_scores(sex, body, lift, expected):
    assert wilks(sex, D(body), D(lift)).quantize(D(".01")) == D(expected)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0", "1.001", "1001", "abc"])
def test_invalid_weights(value):
    with pytest.raises(ValueError):
        parse_weight(value)


def test_decimal_comma():
    assert parse_weight(" 85,50 ") == D("85.50")


def test_formula_range():
    with pytest.raises(ValueError):
        wilks("female", D(151), D(100))
    with pytest.raises(ValueError):
        wilks("male", D(39), D(100))


def test_total_wilks_uses_sum_and_accepts_total_over_1000():
    from powerlifting_bot.domain.wilks import wilks_total

    score = wilks_total("male", D(100), D(400), D(300), D(400))
    assert score.quantize(D(".01")) == D("669.45")
    assert abs(score - wilks("male", D(100), D(100)) * 11) < D("0.00000001")
