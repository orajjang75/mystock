"""Hand-calculated examples. Defaults: round-trip fee 0.03% (0.015% per side), sell tax 0.18%."""

from decimal import Decimal

import pytest

from app.engine.params import RebuyParams
from app.services import quantities as q

DEFAULT = RebuyParams()
FREE = RebuyParams(round_trip_fee_rate=0, sell_tax_rate=0)


def test_fee_is_half_the_round_trip_rate_per_side() -> None:
    assert q.fee_rate_per_side(DEFAULT) == Decimal("0.00015")
    assert q.trade_fee(Decimal(100_000), 30, DEFAULT) == Decimal("450.0000")  # 3,000,000 x 0.015%


def test_sell_tax_is_charged_on_the_sale_value() -> None:
    assert q.sell_tax(Decimal(100_000), 30, DEFAULT) == Decimal("5400.0000")  # 3,000,000 x 0.18%


def test_net_proceeds_after_fee_and_tax() -> None:
    price, shares = Decimal(100_000), 30
    fee, tax = q.trade_fee(price, shares, DEFAULT), q.sell_tax(price, shares, DEFAULT)

    # 3,000,000 - 450 - 5,400
    assert q.net_sell_proceeds(price, shares, fee, tax) == Decimal("2994150")


def test_rebuying_lower_gains_a_share_after_costs() -> None:
    # 2,994,150 / (95,000 x 1.00015 = 95,014.25) = 31.51 -> 31 shares, +1
    proceeds = Decimal("2994150")

    shares = q.suggested_rebuy_quantity(proceeds, Decimal(95_000), DEFAULT)

    assert shares == 31
    assert q.quantity_increase(30, shares) == 1


def test_rebuying_at_the_target_price_gains_nothing_on_a_small_position() -> None:
    # target = 100,000 x (1 - 0.0021 - 0.01) = 98,790; 2,994,150 / 98,804.8185 = 30.30 -> 30
    shares = q.suggested_rebuy_quantity(Decimal("2994150"), Decimal("98790"), DEFAULT)

    assert shares == 30
    assert q.quantity_increase(30, shares) == 0  # 1% of 30 shares is 0.3 of a share


def test_rebuying_higher_loses_shares() -> None:
    shares = q.suggested_rebuy_quantity(Decimal("2994150"), Decimal(101_000), DEFAULT)

    assert shares == 29  # 2,994,150 / 101,015.15 = 29.64
    assert q.quantity_increase(30, shares) == -1


def test_a_whole_number_of_shares_is_not_lost_to_rounding() -> None:
    # exactly 40 shares: 3,000,000 / 75,000
    assert q.suggested_rebuy_quantity(Decimal(3_000_000), Decimal(75_000), FREE) == 40
    assert q.suggested_rebuy_quantity(Decimal(3_000_000), Decimal("75000.01"), FREE) == 39


def test_a_cost_of_one_won_decides_the_last_share() -> None:
    # With the 0.015% fee a share costs 75,011.25: 3,000,449 buys 39 shares, 3,000,450 buys 40
    assert q.suggested_rebuy_quantity(Decimal(3_000_449), Decimal(75_000), DEFAULT) == 39
    assert q.suggested_rebuy_quantity(Decimal(3_000_450), Decimal(75_000), DEFAULT) == 40


@pytest.mark.parametrize(
    ("held", "expected"),
    [(100, 33), (10, 3), (9, 3), (4, 1), (3, 1), (2, 1), (1, None), (0, None)],
)
def test_the_sell_suggestion_is_a_third_and_never_the_whole_position(
    held: int, expected: int | None
) -> None:
    assert q.suggested_sell_quantity(held, 1 / 3) == expected


def test_the_suggestion_follows_the_configured_fraction_but_stops_short_of_everything() -> None:
    assert q.suggested_sell_quantity(10, 0.5) == 5
    assert q.suggested_sell_quantity(10, 0.99) == 9
