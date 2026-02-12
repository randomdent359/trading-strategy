"""Test slippage and fee calculations."""

from decimal import Decimal

import pytest

from trading_core.config.schema import PaperConfig
from trading_core.paper.sizing import apply_slippage, calculate_fees, calculate_pnl


class TestSlippageCalculations:
    """Test slippage application for various scenarios."""

    def test_long_entry_slippage(self):
        """LONG entry: pay more due to slippage."""
        price = Decimal("100.00")
        slippage_pct = 0.001  # 0.1%
        result = apply_slippage(price, "LONG", slippage_pct, is_entry=True)
        assert result == Decimal("100.10")  # 100 * 1.001

    def test_short_entry_slippage(self):
        """SHORT entry: receive less due to slippage."""
        price = Decimal("100.00")
        slippage_pct = 0.001  # 0.1%
        result = apply_slippage(price, "SHORT", slippage_pct, is_entry=True)
        assert result == Decimal("99.90")  # 100 * 0.999

    def test_long_exit_slippage(self):
        """LONG exit: receive less due to slippage."""
        price = Decimal("100.00")
        slippage_pct = 0.001  # 0.1%
        result = apply_slippage(price, "LONG", slippage_pct, is_entry=False)
        assert result == Decimal("99.90")  # 100 * 0.999

    def test_short_exit_slippage(self):
        """SHORT exit: pay more due to slippage."""
        price = Decimal("100.00")
        slippage_pct = 0.001  # 0.1%
        result = apply_slippage(price, "SHORT", slippage_pct, is_entry=False)
        assert result == Decimal("100.10")  # 100 * 1.001

    def test_zero_slippage(self):
        """Zero slippage should not change the price."""
        price = Decimal("100.00")
        slippage_pct = 0.0
        for direction in ["LONG", "SHORT"]:
            for is_entry in [True, False]:
                result = apply_slippage(price, direction, slippage_pct, is_entry)
                assert result == price

    def test_high_slippage(self):
        """Test with high slippage (1%)."""
        price = Decimal("1000.00")
        slippage_pct = 0.01  # 1%

        # LONG entry: pay 1% more
        result = apply_slippage(price, "LONG", slippage_pct, is_entry=True)
        assert result == Decimal("1010.00")

        # SHORT exit: pay 1% more
        result = apply_slippage(price, "SHORT", slippage_pct, is_entry=False)
        assert result == Decimal("1010.00")


class TestFeeCalculations:
    """Test fee calculations for round-trip trades."""

    def test_basic_fee_calculation(self):
        """Test fee calculation for a simple trade."""
        entry_price = Decimal("100.00")
        exit_price = Decimal("110.00")
        quantity = Decimal("10")
        fee_pct = 0.001  # 0.1%

        # Entry notional: 100 * 10 = 1000, fee = 1
        # Exit notional: 110 * 10 = 1100, fee = 1.1
        # Total fees = 2.1
        fees = calculate_fees(entry_price, exit_price, quantity, fee_pct)
        assert fees == Decimal("2.1")

    def test_zero_fees(self):
        """Zero fee percentage should result in zero fees."""
        entry_price = Decimal("100.00")
        exit_price = Decimal("110.00")
        quantity = Decimal("10")
        fee_pct = 0.0

        fees = calculate_fees(entry_price, exit_price, quantity, fee_pct)
        assert fees == Decimal("0")

    def test_high_fee_scenario(self):
        """Test with high fees (0.5%)."""
        entry_price = Decimal("1000.00")
        exit_price = Decimal("1050.00")
        quantity = Decimal("5")
        fee_pct = 0.005  # 0.5%

        # Entry notional: 1000 * 5 = 5000, fee = 25
        # Exit notional: 1050 * 5 = 5250, fee = 26.25
        # Total fees = 51.25
        fees = calculate_fees(entry_price, exit_price, quantity, fee_pct)
        assert fees == Decimal("51.25")

    def test_loss_trade_fees(self):
        """Fees are still charged on losing trades."""
        entry_price = Decimal("100.00")
        exit_price = Decimal("90.00")  # Loss
        quantity = Decimal("10")
        fee_pct = 0.002  # 0.2%

        # Entry notional: 100 * 10 = 1000, fee = 2
        # Exit notional: 90 * 10 = 900, fee = 1.8
        # Total fees = 3.8
        fees = calculate_fees(entry_price, exit_price, quantity, fee_pct)
        assert fees == Decimal("3.8")


class TestIntegratedPnL:
    """Test P&L calculations with slippage and fees."""

    def test_profitable_long_with_slippage_and_fees(self):
        """Test a profitable LONG trade with slippage and fees."""
        # Market prices
        market_entry = Decimal("100.00")
        market_exit = Decimal("110.00")
        quantity = Decimal("10")
        slippage_pct = 0.001  # 0.1%
        fee_pct = 0.002  # 0.2%

        # Apply slippage
        actual_entry = apply_slippage(market_entry, "LONG", slippage_pct, is_entry=True)
        actual_exit = apply_slippage(market_exit, "LONG", slippage_pct, is_entry=False)

        assert actual_entry == Decimal("100.10")  # Pay more on entry
        assert actual_exit == Decimal("109.89")   # Receive less on exit

        # Calculate gross P&L
        gross_pnl = calculate_pnl("LONG", actual_entry, actual_exit, quantity)
        expected_gross = (Decimal("109.89") - Decimal("100.10")) * Decimal("10")
        assert gross_pnl == expected_gross  # 9.79 * 10 = 97.9

        # Calculate fees
        fees = calculate_fees(actual_entry, actual_exit, quantity, fee_pct)
        # Entry: 100.10 * 10 * 0.002 = 2.002
        # Exit: 109.89 * 10 * 0.002 = 2.1978
        # Total: 4.1998
        assert abs(fees - Decimal("4.1998")) < Decimal("0.0001")

        # Net P&L
        net_pnl = gross_pnl - fees
        assert net_pnl < gross_pnl  # Fees reduce profit
        assert net_pnl > Decimal("0")  # Still profitable

    def test_losing_short_with_slippage_and_fees(self):
        """Test a losing SHORT trade with slippage and fees."""
        # Market prices
        market_entry = Decimal("100.00")
        market_exit = Decimal("105.00")  # Price went up, loss for SHORT
        quantity = Decimal("5")
        slippage_pct = 0.0005  # 0.05%
        fee_pct = 0.001  # 0.1%

        # Apply slippage
        actual_entry = apply_slippage(market_entry, "SHORT", slippage_pct, is_entry=True)
        actual_exit = apply_slippage(market_exit, "SHORT", slippage_pct, is_entry=False)

        assert actual_entry == Decimal("99.95")   # Receive less on entry
        assert actual_exit == Decimal("105.0525") # Pay more on exit

        # Calculate gross P&L
        gross_pnl = calculate_pnl("SHORT", actual_entry, actual_exit, quantity)
        # SHORT P&L: (entry - exit) * quantity
        expected_gross = (Decimal("99.95") - Decimal("105.0525")) * Decimal("5")
        assert gross_pnl == expected_gross  # Negative

        # Calculate fees
        fees = calculate_fees(actual_entry, actual_exit, quantity, fee_pct)

        # Net P&L (more negative due to fees)
        net_pnl = gross_pnl - fees
        assert net_pnl < gross_pnl  # Fees make the loss worse
        assert net_pnl < Decimal("0")  # Definitely a loss

    def test_breakeven_becomes_loss_with_costs(self):
        """Test a breakeven trade that becomes a loss after slippage and fees."""
        # Market prices - would be breakeven without costs
        market_entry = Decimal("100.00")
        market_exit = Decimal("100.00")
        quantity = Decimal("20")
        slippage_pct = 0.0005  # 0.05%
        fee_pct = 0.001  # 0.1%

        # Apply slippage for LONG
        actual_entry = apply_slippage(market_entry, "LONG", slippage_pct, is_entry=True)
        actual_exit = apply_slippage(market_exit, "LONG", slippage_pct, is_entry=False)

        assert actual_entry > market_entry  # Paid more
        assert actual_exit < market_exit    # Received less

        # Calculate gross P&L (already negative due to slippage)
        gross_pnl = calculate_pnl("LONG", actual_entry, actual_exit, quantity)
        assert gross_pnl < Decimal("0")

        # Calculate fees
        fees = calculate_fees(actual_entry, actual_exit, quantity, fee_pct)
        assert fees > Decimal("0")

        # Net P&L (loss due to slippage + fees)
        net_pnl = gross_pnl - fees
        assert net_pnl < Decimal("0")

        # Total cost should be roughly slippage + fees
        total_cost = abs(net_pnl)
        slippage_cost = quantity * market_entry * Decimal(str(slippage_pct)) * 2  # Entry + exit
        fee_cost = fees
        assert abs(total_cost - (slippage_cost + fee_cost)) < Decimal("0.01")