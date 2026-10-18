"""Backtests (PRD 10장 백테스트 계획).

The signal code is the app's own: the screener's gate and score (``services.screener``), the
alert signals (``engine.cycle_signals``) and the holding state machine (``services.holdings``)
are imported, never copied, so what is verified is what runs.

- ``signal_quality``: event study of the screener's candidates (vectorbt, or an equivalent pandas
  engine where vectorbt cannot be installed).
- ``cycle_simulator``: the sequential hold -> sell -> wait -> rebuy/expire simulation.
- ``sensitivity`` and ``walk_forward``: parameter heatmaps and out-of-sample checks.
- ``runner``: one ``BacktestConfig`` in, one result out; ``report``: the result as text.
"""
