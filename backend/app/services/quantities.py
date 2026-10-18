"""Share counts and costs of the sell/rebuy cycle (PRD 5장 A-3, A-5, A-9).

Money is computed with Decimal so a quantity that lands exactly on a whole share is not lost to
float noise. The fee rate per side is half of the configured round-trip fee; the sell tax is
charged on sales only. Quantities are whole shares and always rounded down.
"""

from decimal import ROUND_DOWN, Decimal

from app.engine.params import RebuyParams

_MONEY = Decimal("0.0001")


def dec(value: float | Decimal | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def fee_rate_per_side(params: RebuyParams) -> Decimal:
    return dec(params.round_trip_fee_rate) / 2


def trade_fee(price: Decimal, quantity: int, params: RebuyParams) -> Decimal:
    """Brokerage fee of one buy or sell."""
    return (price * quantity * fee_rate_per_side(params)).quantize(_MONEY)


def sell_tax(price: Decimal, quantity: int, params: RebuyParams) -> Decimal:
    """매도 거래세 of a sale."""
    return (price * quantity * dec(params.sell_tax_rate)).quantize(_MONEY)


def suggested_sell_quantity(quantity: int, fraction: float) -> int | None:
    """A-3: a third of the position, at least one share, never the whole position.

    ``None`` when no partial sale is possible (fewer than two shares).
    """
    if quantity < 2:
        return None
    return min(max(1, int(quantity * fraction)), quantity - 1)


def net_sell_proceeds(price: Decimal, quantity: int, fee: Decimal, tax: Decimal) -> Decimal:
    """Cash received from a sale after fee and tax."""
    return price * quantity - fee - tax


def suggested_rebuy_quantity(
    net_proceeds: Decimal, rebuy_price: Decimal, params: RebuyParams
) -> int:
    """A-5: how many shares the sale proceeds buy back at ``rebuy_price``, fee included."""
    unit_cost = rebuy_price * (1 + fee_rate_per_side(params))
    return int((net_proceeds / unit_cost).to_integral_value(rounding=ROUND_DOWN))


def quantity_increase(sell_quantity: int, rebuy_quantity: int) -> int:
    """수량 증가분 = rebuy shares − sold shares."""
    return rebuy_quantity - sell_quantity
