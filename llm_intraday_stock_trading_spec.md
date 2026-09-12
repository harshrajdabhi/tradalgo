# LLM Trading System Specification — Indian Intraday Equity

## Objective
Design an AI-assisted intraday trading system for liquid NSE stocks, primarily Nifty 50 constituents. Prioritize capital preservation, high-quality setups, and positive expected R after costs rather than trade frequency or prediction accuracy.

## Capital & Risk
- Initial trading capital: ₹20,000.
- Maximum risk per trade: 3% of trading capital (₹600 initially).
- Maximum 2 trades per day; only take the second if an independent valid setup appears.
- Never force a trade to meet the daily limit.
- Use up to 5× broker-supported intraday leverage only for position sizing; leverage must never increase rupee risk.
- Position size = min(risk-based quantity, leverage-based maximum quantity).
- Include ₹50 fixed cost per completed trade when calculating net/expected R.

## Nightly Stock Selection
Run after market close across the Nifty 50 universe and select six stocks for the next session. Rank using:
1. Momentum and trend strength.
2. Relative strength/weakness versus Nifty and sector.
3. ATR and realized-volatility percentile.
4. Relative volume and volume expansion.
5. Breakout/consolidation structure.
6. Distance to key levels: previous-day high/low, swing high/low, daily/weekly support/resistance.
7. Relevant news/events and sentiment.

Favor stocks with sufficient expected intraday movement and clean structure. Reject candidates where a realistic 2R target is blocked by nearby support/resistance.

## Intraday Engine
Poll 5-minute or 15-minute data through the broker SDK; use 5-minute signals with 15-minute context where appropriate. Detect independent strategies:
- Opening Range Breakout (ORB).
- VWAP continuation/reclaim/rejection.
- Previous-day high/low breakout or rejection.
- Momentum pullback after strong expansion.
- Consolidation/range breakout.
- Gap continuation or gap-fade setups.

Classify the market/stock regime (trend, range, high volatility) and enable only compatible strategies.

## Trade Validation
Before entry, calculate entry, structural/ATR stop-loss, 2R/3R targets, room to the next major level, expected move, position quantity, leverage requirement, and estimated ₹50 cost. Execute only when sufficient room exists and expected value after costs is positive.

## Position Management
At 2R, square off 60% of the position. Manage the remaining 40% as a runner using a predefined trailing/protection rule and exit all remaining quantity by 3:00 PM. Never average down or widen the original stop.

## ML Evolution
Start with deterministic rules and log every signal, feature, decision, execution, MFE/MAE, slippage, and outcome in R. Later train a ranking/meta-model to estimate P(reaching 2R before SL) and expected R. Optimize for out-of-sample expected R after costs, not classification accuracy.

## Safety
Backtest and paper trade before live deployment. Implement daily loss limits, kill switches, API/error handling, duplicate-order protection, and complete audit logs.
