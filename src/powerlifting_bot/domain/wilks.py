from decimal import Decimal

FORMULA_VERSION = "wilks_original"
# Original Wilks, not Wilks 2020. British Powerlifting model evaluation:
# https://www.britishpowerlifting.org/documents/962_models_evaluation-i-2020.pdf
COEFFICIENTS = {
    "male": (
        "-216.0475144",
        "16.2606339",
        "-0.002388645",
        "-0.00113732",
        "0.00000701863",
        "-0.00000001291",
    ),
    "female": (
        "594.31747775582",
        "-27.23842536447",
        "0.82112226871",
        "-0.00930733913",
        "0.00004731582",
        "-0.00000009054",
    ),
}


def parse_weight(text: str, minimum=Decimal("0.01"), maximum=Decimal(1000)) -> Decimal:
    try:
        weight = Decimal(text.strip().replace(",", "."))
        if not weight.is_finite() or not minimum <= weight <= maximum:
            raise ValueError
        if weight != weight.quantize(Decimal("0.01")):
            raise ValueError
        return weight
    except (ArithmeticError, ValueError):
        raise ValueError(
            f"Введите число от {minimum} до {maximum} кг, до 2 знаков после запятой."
        ) from None


def wilks(sex: str, bodyweight: Decimal, lifted: Decimal) -> Decimal:
    if sex not in COEFFICIENTS:
        raise ValueError("Неизвестный пол для расчёта.")
    # Explicit supported range for this application; no hidden clamping.
    maximum = Decimal(200) if sex == "male" else Decimal(150)
    if not bodyweight.is_finite() or not Decimal(40) <= bodyweight <= maximum:
        raise ValueError(f"Для Wilks в этой версии масса должна быть от 40 до {maximum} кг.")
    if not lifted.is_finite() or not Decimal(0) < lifted <= Decimal(1000):
        raise ValueError("Вес штанги должен быть больше 0 и не больше 1000 кг.")
    denominator = Decimal(0)
    for coefficient in reversed(COEFFICIENTS[sex]):
        denominator = denominator * bodyweight + Decimal(coefficient)
    return Decimal(500) * lifted / denominator
