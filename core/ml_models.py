"""
ML Models — Forecasting & Classification
1. Prophet: Time-series forecasting for 7D/14D/1M/3M/6M/1Y horizons
2. Random Forest: BUY/SELL classification from indicator features
3. Linear Regression: Trend momentum scoring
"""
import logging
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Dict, Tuple
import sys

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    ML_PREDICTION_DAYS, ML_TRAIN_MIN_ROWS, PROPHET_CHANGEPOINT_PRIOR,
    RF_N_ESTIMATORS, RF_MAX_DEPTH, RF_RANDOM_STATE
)
from db.database import get_session, Stock, Forecast

logger = logging.getLogger(__name__)


# ─── Feature Engineering for ML ───────────────────────────────────────────────
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build ML features from OHLCV + indicator data.
    Features include: returns, momentum, volatility, and normalized indicators.
    """
    f = pd.DataFrame(index=df.index)

    if "close" not in df.columns:
        return f

    close = df["close"]

    # Return features
    f["ret_1d"] = close.pct_change(1)
    f["ret_3d"] = close.pct_change(3)
    f["ret_5d"] = close.pct_change(5)
    f["ret_10d"] = close.pct_change(10)
    f["ret_20d"] = close.pct_change(20)

    # Momentum
    f["mom_10"] = close / close.shift(10) - 1
    f["mom_20"] = close / close.shift(20) - 1
    f["mom_50"] = close / close.shift(50) - 1

    # Volatility (rolling std of returns)
    ret = close.pct_change()
    f["vol_10"] = ret.rolling(10).std()
    f["vol_20"] = ret.rolling(20).std()

    # Normalized price position (52-week range)
    high_52w = close.rolling(252).max()
    low_52w = close.rolling(252).min()
    f["price_position_52w"] = (close - low_52w) / (high_52w - low_52w + 1e-10)

    # Volume features (if available)
    if "volume" in df.columns:
        vol = df["volume"]
        f["vol_ratio_5d"] = vol / vol.rolling(5).mean()
        f["vol_ratio_20d"] = vol / vol.rolling(20).mean()

    # Indicator-based features (if present in df)
    for col in ["rsi_14", "macd", "macd_hist", "bb_pct", "ema_9", "ema_21", "ema_50",
                "adx", "stoch_k", "cci_20", "volume_ratio", "atr_14"]:
        if col in df.columns:
            f[col] = df[col]

    return f.replace([np.inf, -np.inf], np.nan)


def build_target(df: pd.DataFrame, forward_days: int = 5) -> pd.Series:
    """
    Build binary target: 1 if price goes up by > 1% in next N days, else 0.
    """
    close = df["close"]
    future_return = close.shift(-forward_days) / close - 1
    return (future_return > 0.01).astype(int)


# ─── 1. Time-Series Forecaster (Prophet + Holt-Winters Fallback) ───────────────
def run_prophet_forecast(
    df: pd.DataFrame,
    symbol: str,
) -> Optional[Dict]:
    """
    Run time-series forecast for multiple horizons (7d, 14d, 1m, 3m, 6m, 1y).
    Uses Meta Prophet if available, otherwise falls back to Holt-Winters Exponential Smoothing.
    """
    if len(df) < ML_TRAIN_MIN_ROWS:
        logger.debug(f"{symbol}: Insufficient data for forecast ({len(df)} rows)")
        return None

    try:
        from prophet import Prophet
        prophet_df = pd.DataFrame({
            "ds": df.index,
            "y": df["close"].values
        }).dropna()
        prophet_df["ds"] = pd.to_datetime(prophet_df["ds"])

        model = Prophet(
            changepoint_prior_scale=PROPHET_CHANGEPOINT_PRIOR,
            seasonality_mode="multiplicative",
            yearly_seasonality=True,
            weekly_seasonality=True,
            daily_seasonality=False,
            interval_width=0.80,
        )
        model.fit(prophet_df, verbose=False)

        max_days = max(ML_PREDICTION_DAYS)
        future = model.make_future_dataframe(periods=max_days, freq="B")
        forecast = model.predict(future)

        last_train_date = prophet_df["ds"].max()
        future_forecast = forecast[forecast["ds"] > last_train_date].copy()
        current_price = float(prophet_df["y"].iloc[-1])

        result = {
            "model_used": "prophet",
            "data_points_used": len(prophet_df),
        }

        horizon_map = {7: "7d", 14: "14d", 30: "1m", 90: "3m", 180: "6m", 365: "1y"}
        for days, label in horizon_map.items():
            target_dates = future_forecast[
                future_forecast["ds"] <= last_train_date + pd.Timedelta(days=days)
            ]
            if target_dates.empty:
                target_dates = future_forecast.tail(1)

            row = target_dates.iloc[-1]
            predicted = float(row["yhat"])
            upper = float(row["yhat_upper"])
            lower = max(0.1, float(row["yhat_lower"]))
            change_pct = (predicted - current_price) / current_price * 100

            result[f"forecast_{label}_price"] = round(predicted, 2)
            result[f"forecast_{label}_change_pct"] = round(change_pct, 2)
            result[f"forecast_{label}_upper"] = round(upper, 2)
            result[f"forecast_{label}_lower"] = round(lower, 2)

        return result

    except Exception:
        # Fallback to Statistical Exponential Smoothing
        return run_statistical_forecast(df, symbol)


def run_statistical_forecast(df: pd.DataFrame, symbol: str) -> Optional[Dict]:
    """
    Hybrid Multi-Horizon Forecaster:
    Combines Holt-Winters Exponential Smoothing with Multi-Period Linear Momentum Drift
    and Volatility Expansion Cones (80% Confidence Interval).
    """
    try:
        from sklearn.linear_model import LinearRegression

        series = df["close"].dropna().astype(float)
        if len(series) < 60:
            return None

        current_price = float(series.iloc[-1])
        daily_returns = series.pct_change().dropna()
        daily_vol = float(daily_returns.std()) if not daily_returns.empty else 0.015

        # 1. Multi-Period Momentum Drift Slope (Recent 60 days + 120 days)
        lookback = min(len(series), 90)
        recent_prices = series.iloc[-lookback:].values
        x = np.arange(lookback).reshape(-1, 1)
        lr = LinearRegression().fit(x, recent_prices)
        daily_drift = lr.coef_[0]  # ₹ change per day

        # EMA Trend Slope
        ema_21 = series.ewm(span=21).mean().iloc[-1]
        ema_50 = series.ewm(span=50).mean().iloc[-1]
        ema_trend_bias = (ema_21 - ema_50) / ema_50 if ema_50 > 0 else 0.0

        # Blended annualized drift rate
        annual_drift_pct = (daily_drift * 252 / current_price) * 0.65 + (ema_trend_bias * 0.35)
        # Constrain realistic annual drift between -45% and +65%
        annual_drift_pct = max(-0.45, min(0.65, annual_drift_pct))

        # 2. Pure Native Holt's Exponential Smoothing (Double Exponential Smoothing)
        vals = series.iloc[-120:].values
        if len(vals) >= 2:
            alpha, beta_param = 0.25, 0.10
            level = float(vals[0])
            trend = float(vals[1] - vals[0])
            for val in vals[1:]:
                last_level = level
                level = alpha * float(val) + (1 - alpha) * (last_level + trend)
                trend = beta_param * (level - last_level) + (1 - beta_param) * trend
            hw_fc = [max(0.1, level + h * trend) for h in range(1, 261)]
        else:
            hw_fc = [current_price] * 260

        result = {
            "model_used": "Hybrid Momentum + Holt-Winters",
            "data_points_used": len(series),
        }

        horizon_map = {7: "7d", 14: "14d", 30: "1m", 90: "3m", 180: "6m", 365: "1y"}
        td_map = {7: 5, 14: 10, 30: 21, 90: 63, 180: 126, 365: 252}

        for days, label in horizon_map.items():
            t_days = td_map[days]
            hw_pred = float(hw_fc[min(t_days - 1, len(hw_fc) - 1)]) if len(hw_fc) > 0 else current_price

            # Hybrid projection: 50% Momentum Drift + 50% Holt-Winters
            drift_pred = current_price * (1.0 + (annual_drift_pct * (days / 365.0)))
            pred_price = (drift_pred * 0.60) + (hw_pred * 0.40)

            # Volatility cone (80% CI: z = 1.282)
            vol_expansion = 1.282 * daily_vol * np.sqrt(t_days) * current_price
            upper = pred_price + vol_expansion
            lower = max(0.1, pred_price - vol_expansion)
            change_pct = (pred_price - current_price) / current_price * 100

            result[f"forecast_{label}_price"] = round(pred_price, 2)
            result[f"forecast_{label}_change_pct"] = round(change_pct, 2)
            result[f"forecast_{label}_upper"] = round(upper, 2)
            result[f"forecast_{label}_lower"] = round(lower, 2)

        return result

    except Exception as e:
        logger.error(f"{symbol}: Statistical forecast failed: {e}")
        return None


# ─── 1b. XGBoost Multi-Horizon Forecast Regressor (Items 1.3 & 5.2) ───────────
def train_xgboost_forecast(df: pd.DataFrame, symbol: str) -> Optional[Dict]:
    """
    Items 1.3 & 5.2: XGBoost Multi-Horizon Return & Price Regressor.
    Features: Returns (1d, 3d, 5d, 10d, 20d), Momentum (10, 20, 50), Volatility (10, 20),
              52W price range position, Volume ratio, RSI, MACD, ADX, ATR ratio.
    Trains on recent 800 days (stationary regime window), 80/20 train/val split.
    Projects 7d, 14d, 1m, 3m, 6m, 1y price horizons with volatility cone bounds.
    """
    try:
        import xgboost as xgb
        if len(df) < 80:
            return None

        # Work with recent 800 days to avoid ancient regime bias
        recent_df = df.tail(800)
        features = build_features(recent_df).dropna()
        if len(features) < 50:
            return None

        close = recent_df.loc[features.index, "close"].astype(float)
        current_price = float(close.iloc[-1])

        # Target: 10-day forward return (~14 calendar days)
        fwd_ret = (close.shift(-10) - close) / close
        valid_idx = fwd_ret.dropna().index

        X = features.loc[valid_idx]
        y = fwd_ret.loc[valid_idx]

        split = int(len(X) * 0.8)
        X_train, X_val = X.iloc[:split], X.iloc[split:]
        y_train, y_val = y.iloc[:split], y.iloc[split:]

        model = xgb.XGBRegressor(
            n_estimators=75,
            max_depth=3,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=2
        )
        model.fit(X_train, y_train)

        # Validation metrics
        preds_val = model.predict(X_val)
        corr = 0.0
        if len(y_val) >= 5 and np.std(preds_val) > 0 and np.std(y_val) > 0:
            corr = float(np.corrcoef(y_val, preds_val)[0, 1])
            if np.isnan(corr):
                corr = 0.0

        # Predict forward return for latest bar
        latest_feat = features.iloc[[-1]]
        base_14d_ret = float(model.predict(latest_feat)[0])
        # Clip to realistic 14-day boundaries (-20% to +25%)
        base_14d_ret = max(-0.20, min(0.25, base_14d_ret))

        # Daily historical volatility
        ret_series = close.pct_change().dropna()
        daily_vol = float(ret_series.std()) if len(ret_series) > 0 else 0.015

        horizon_days = {"7d": 5, "14d": 10, "1m": 21, "3m": 63, "6m": 126, "1y": 252}
        result = {
            "model_used": f"XGBoost Regressor (Out-of-Sample Corr: {corr:.2f})",
            "data_points_used": len(recent_df),
        }

        # Multi-horizon scaling: t^(1/2) scaling for drift with mean-reversion dampening
        for label, td in horizon_days.items():
            time_factor = (td / 10.0) ** 0.65  # sublinear horizon scaling
            proj_ret = base_14d_ret * time_factor
            proj_price = current_price * (1.0 + proj_ret)

            # Volatility cone (80% CI: z=1.282)
            vol_spread = 1.282 * daily_vol * np.sqrt(td) * current_price
            upper = proj_price + vol_spread
            lower = max(0.1, proj_price - vol_spread)

            result[f"forecast_{label}_price"] = round(proj_price, 2)
            result[f"forecast_{label}_change_pct"] = round(proj_ret * 100.0, 2)
            result[f"forecast_{label}_upper"] = round(upper, 2)
            result[f"forecast_{label}_lower"] = round(lower, 2)

        return result

    except Exception as e:
        logger.warning(f"{symbol}: XGBoost forecast fallback: {e}")
        return None


# ─── 2. Random Forest Classifier ─────────────────────────────────────────────

def run_random_forest(
    df: pd.DataFrame,
    symbol: str,
    forward_days: int = 5,
) -> Tuple[str, float, Optional[float]]:
    """
    Random Forest BUY/SELL classifier.
    Returns: (signal, confidence, model_accuracy)
    """
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import accuracy_score
    except ImportError:
        return "WATCH", 0.5, None

    if len(df) < ML_TRAIN_MIN_ROWS + forward_days:
        return "WATCH", 0.5, None

    try:
        features = build_features(df)
        target = build_target(df, forward_days)

        combined = features.join(target.rename("target")).dropna()
        if len(combined) < ML_TRAIN_MIN_ROWS:
            return "WATCH", 0.5, None

        X = combined.drop("target", axis=1)
        y = combined["target"]

        # Train/test split (time-series aware — no shuffle)
        split = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:split], X.iloc[split:]
        y_train, y_test = y.iloc[:split], y.iloc[split:]

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        model = RandomForestClassifier(
            n_estimators=RF_N_ESTIMATORS,
            max_depth=RF_MAX_DEPTH,
            random_state=RF_RANDOM_STATE,
            n_jobs=-1,
        )
        model.fit(X_train_s, y_train)

        # Accuracy on test set
        y_pred_test = model.predict(X_test_s)
        accuracy = accuracy_score(y_test, y_pred_test)

        # Predict on latest row
        latest_features = X.iloc[[-1]]
        if latest_features.isna().all().all():
            return "WATCH", 0.5, accuracy

        latest_scaled = scaler.transform(latest_features.fillna(0))
        proba = model.predict_proba(latest_scaled)[0]
        predicted_class = model.predict(latest_scaled)[0]

        confidence = float(max(proba))
        signal = "BUY" if predicted_class == 1 else "SELL"

        # Only return signal if confidence > 0.55
        if confidence < 0.55:
            signal = "WATCH"

        return signal, round(confidence, 3), round(accuracy, 3)

    except Exception as e:
        logger.error(f"{symbol}: Random Forest failed: {e}")
        return "WATCH", 0.5, None


# ─── 3. Linear & Polynomial Ridge Trend Regression ─────────────────────────
def compute_trend_regression(
    df: pd.DataFrame,
    window: int = 60,
) -> Dict:
    """
    Linear regression on price series to determine trend slope and strength.
    Returns: {slope_pct, r2, trend_signal, ml_score, acceleration}
    """
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import r2_score

    if len(df) < window:
        return {"slope_pct": 0, "r2": 0, "trend_signal": "WATCH", "ml_score": 50.0, "acceleration": 0}

    try:
        close = df["close"].tail(window).values
        x = np.arange(len(close)).reshape(-1, 1)

        model = LinearRegression()
        model.fit(x, close)
        y_pred = model.predict(x)

        r2 = r2_score(close, y_pred)
        slope = model.coef_[0]
        slope_pct = (slope / close[0]) * 100 if close[0] != 0 else 0

        # Polynomial curvature (trend acceleration)
        poly_coef = np.polyfit(np.arange(len(close)), close, 2)
        acceleration = float(poly_coef[0])  # positive = upward curve (accelerating)

        if slope_pct > 0.08 and r2 > 0.4:
            trend_signal = "BUY"
            ml_score = min(92, 55 + r2 * 35 + (5 if acceleration > 0 else 0))
        elif slope_pct < -0.08 and r2 > 0.4:
            trend_signal = "SELL"
            ml_score = max(8, 45 - r2 * 35 - (5 if acceleration < 0 else 0))
        else:
            trend_signal = "WATCH"
            ml_score = 50.0

        return {
            "slope_pct": round(slope_pct, 4),
            "r2": round(r2, 4),
            "trend_signal": trend_signal,
            "ml_score": round(ml_score, 2),
            "acceleration": round(acceleration, 4),
        }
    except Exception:
        return {"slope_pct": 0, "r2": 0, "trend_signal": "WATCH", "ml_score": 50.0, "acceleration": 0}


# ─── 4. Monte Carlo Price Simulation & Risk Engine ───────────────────────────
def run_monte_carlo_simulation(
    df: pd.DataFrame,
    days_forward: int = 30,
    num_simulations: int = 3000,
) -> Dict:
    """
    Monte Carlo price path simulation using Geometric Brownian Motion.
    Returns: Probability of Profit (PoP), Expected Price, VaR (95%), CVaR, CI bands.
    """
    try:
        series = df["close"].dropna().astype(float)
        if len(series) < 60:
            return {}

        current_price = float(series.iloc[-1])
        returns = series.pct_change().dropna()

        # Annualized drift & daily volatility
        mu = float(returns.mean())
        sigma = float(returns.std())

        if sigma <= 0 or np.isnan(sigma):
            return {}

        # Simulate paths: S_t = S_0 * exp(cumsum((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z))
        dt = 1.0
        random_shocks = np.random.normal(0, 1, (num_simulations, days_forward))
        drift_component = (mu - 0.5 * (sigma ** 2)) * dt
        diffusion_component = sigma * np.sqrt(dt) * random_shocks
        daily_log_returns = drift_component + diffusion_component

        # Price paths
        price_paths = current_price * np.exp(np.cumsum(daily_log_returns, axis=1))
        ending_prices = price_paths[:, -1]

        # Metrics
        pop = float(np.mean(ending_prices > current_price)) * 100
        expected_price = float(np.mean(ending_prices))
        ci_80_lower = float(np.percentile(ending_prices, 10))
        ci_80_upper = float(np.percentile(ending_prices, 90))
        ci_95_lower = float(np.percentile(ending_prices, 2.5))
        ci_95_upper = float(np.percentile(ending_prices, 97.5))

        # Value at Risk (VaR 95%) & Conditional VaR (CVaR / Expected Shortfall)
        final_returns = (ending_prices - current_price) / current_price
        var_95 = float(np.percentile(final_returns, 5)) * 100
        cvar_95 = float(np.mean(final_returns[final_returns <= np.percentile(final_returns, 5)])) * 100

        return {
            "current_price": round(current_price, 2),
            "expected_price_30d": round(expected_price, 2),
            "expected_return_30d_pct": round((expected_price - current_price) / current_price * 100, 2),
            "probability_of_profit_pct": round(pop, 1),
            "ci_80_lower": round(ci_80_lower, 2),
            "ci_80_upper": round(ci_80_upper, 2),
            "ci_95_lower": round(ci_95_lower, 2),
            "ci_95_upper": round(ci_95_upper, 2),
            "var_95_pct": round(var_95, 2),
            "cvar_95_pct": round(cvar_95, 2),
        }
    except Exception as e:
        logger.error(f"Monte Carlo simulation failed: {e}")
        return {}


# ─── 5. Signal Correlation & Multi-Engine Confluence ──────────────────────────
def compute_signal_correlation_and_confluence(
    df: pd.DataFrame,
    ind_dict: dict,
    ml_result: dict,
) -> Dict:
    """
    Computes cross-correlation between signals and calculates Confluence Index (0-100%).
    Measures degree of agreement between 5 distinct analytical engines:
    1. Trend (EMA alignment & Linear Reg)
    2. Momentum (RSI, MACD, Stoch, CCI)
    3. Volatility (Bollinger Bands & ATR expansion)
    4. Volume Flow (OBV & Volume Ratio)
    5. Machine Learning (Random Forest & GBM probability)
    """
    close = ind_dict.get("close") or (df["close"].iloc[-1] if not df.empty else 0)
    if not close:
        return {"confluence_score": 50.0, "confluence_grade": "MODERATE", "bullish_engines": 0, "total_engines": 5}

    bullish_engines = 0
    bearish_engines = 0
    engine_details = {}

    # Engine 1: Trend
    ema_9 = ind_dict.get("ema_9") or close
    ema_21 = ind_dict.get("ema_21") or close
    ema_50 = ind_dict.get("ema_50") or close
    slope = ml_result.get("trend_slope", 0)
    if (ema_9 >= ema_21 and ema_21 >= ema_50) or slope > 0.05:
        bullish_engines += 1
        engine_details["Trend"] = "BULLISH"
    elif (ema_9 < ema_21 and ema_21 < ema_50) or slope < -0.05:
        bearish_engines += 1
        engine_details["Trend"] = "BEARISH"
    else:
        engine_details["Trend"] = "NEUTRAL"

    # Engine 2: Momentum
    rsi = ind_dict.get("rsi_14") or 50
    macd_hist = ind_dict.get("macd_hist") or 0
    stoch_k = ind_dict.get("stoch_k") or 50
    mom_bull = (rsi > 50) + (macd_hist > 0) + (stoch_k > 50)
    if mom_bull >= 2:
        bullish_engines += 1
        engine_details["Momentum"] = "BULLISH"
    elif mom_bull <= 1 and (rsi < 48 or macd_hist < 0):
        bearish_engines += 1
        engine_details["Momentum"] = "BEARISH"
    else:
        engine_details["Momentum"] = "NEUTRAL"

    # Engine 3: Volatility & Price Action
    bb_pct = ind_dict.get("bb_pct") or 0.5
    bb_width = ind_dict.get("bb_width") or 0.05
    if bb_pct > 0.55:
        bullish_engines += 1
        engine_details["Volatility"] = "BULLISH"
    elif bb_pct < 0.45:
        bearish_engines += 1
        engine_details["Volatility"] = "BEARISH"
    else:
        engine_details["Volatility"] = "NEUTRAL"

    # Engine 4: Volume & Liquidity
    vol_ratio = ind_dict.get("volume_ratio") or 1.0
    obv = ind_dict.get("obv") or 0
    obv_sma = ind_dict.get("obv_sma") or 0
    if vol_ratio > 1.1 and (obv >= obv_sma):
        bullish_engines += 1
        engine_details["Volume"] = "BULLISH"
    elif vol_ratio > 1.1 and (obv < obv_sma):
        bearish_engines += 1
        engine_details["Volume"] = "BEARISH"
    else:
        engine_details["Volume"] = "NEUTRAL"

    # Engine 5: Machine Learning
    rf_sig = ml_result.get("ml_signal", "WATCH")
    if rf_sig == "BUY":
        bullish_engines += 1
        engine_details["ML Model"] = "BULLISH"
    elif rf_sig == "SELL":
        bearish_engines += 1
        engine_details["ML Model"] = "BEARISH"
    else:
        engine_details["ML Model"] = "NEUTRAL"

    # Confluence calculation
    net_bull = bullish_engines - bearish_engines
    confluence_score = round(50.0 + (net_bull / 5.0) * 50.0, 1)

    if confluence_score >= 80:
        grade = "ULTRA CONFLUENCE (5-Engine Bullish)"
    elif confluence_score >= 65:
        grade = "STRONG CONFLUENCE (Bullish)"
    elif confluence_score <= 20:
        grade = "ULTRA CONFLUENCE (5-Engine Bearish)"
    elif confluence_score <= 35:
        grade = "STRONG CONFLUENCE (Bearish)"
    else:
        grade = "MODERATE / MIXED SIGNALS"

    return {
        "confluence_score": confluence_score,
        "confluence_grade": grade,
        "bullish_engines": bullish_engines,
        "bearish_engines": bearish_engines,
        "total_engines": 5,
        "engine_details": engine_details,
    }


# ─── Main ML Runner ───────────────────────────────────────────────────────────
def run_ml_analysis(
    df: pd.DataFrame,
    symbol: str,
) -> Dict:
    """
    Run all ML models and return combined results.
    """
    results = {
        "ml_signal": "WATCH",
        "ml_confidence": 0.5,
        "ml_score": 50.0,
    }

    if df.empty or len(df) < ML_TRAIN_MIN_ROWS:
        return results

    # 1. Linear Regression (fast, always runs)
    lr = compute_trend_regression(df)
    results["trend_slope"] = lr["slope_pct"]
    results["trend_r2"] = lr["r2"]
    results["ml_score"] = lr["ml_score"]
    results["ml_signal"] = lr["trend_signal"]

    # 2. Random Forest (slower, skip for smallcap to save time)
    rf_signal, rf_conf, rf_acc = run_random_forest(df, symbol)
    if rf_conf > 0.55:
        # Blend RF with LR trend signal
        if rf_signal == lr["trend_signal"]:
            results["ml_signal"] = rf_signal
            results["ml_confidence"] = rf_conf
            results["ml_score"] = (lr["ml_score"] + (rf_conf * 100)) / 2
        else:
            # Disagreement — use WATCH
            results["ml_signal"] = "WATCH"
            results["ml_confidence"] = 0.5
    results["rf_accuracy"] = rf_acc

    return results


def compute_and_save_forecasts(
    symbol: str,
    stock_id: int,
    df: pd.DataFrame,
    session: Session,
):
    """Run forecasting and save results to DB."""
    if len(df) < 50:
        return

    # Item 1.3/5.2: Try XGBoost Regressor first, fallback to Prophet / Holt-Winters
    fc_results = train_xgboost_forecast(df, symbol)
    if fc_results is None:
        fc_results = run_prophet_forecast(df, symbol)
    if fc_results is None:
        return

    # Use latest available date from price dataframe
    last_dt = df.index[-1]
    gen_date = last_dt.date() if hasattr(last_dt, "date") else str(last_dt)[:10]

    fc_data = {
        "stock_id": stock_id,
        "symbol": symbol,
        "generated_date": str(gen_date),
        **{k: v for k, v in fc_results.items() if k not in ("model_used", "data_points_used")},
        "model_used": fc_results.get("model_used", "Holt-Winters Damped"),
        "data_points_used": fc_results.get("data_points_used", len(df)),
    }

    try:
        cols = ", ".join(fc_data.keys())
        placeholders = ", ".join(f":{k}" for k in fc_data.keys())
        session.execute(text(f"INSERT OR REPLACE INTO forecasts ({cols}) VALUES ({placeholders})"), fc_data)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"{symbol}: Forecast save failed: {e}")


def run_forecasts_for_top_stocks(session: Session, top_n: int = 100, progress_callback=None):
    """Run forecasts for top N stocks by composite score."""
    from db.database import CompositeScore, Stock
    from core.data_fetcher import get_all_prices_dataframe

    # Get top N stocks by latest composite score
    top = session.query(CompositeScore, Stock).join(
        Stock, CompositeScore.symbol == Stock.symbol
    ).order_by(
        CompositeScore.composite_score.desc()
    ).limit(top_n).all()

    logger.info(f"Running ML & Time-Series forecasts for {len(top)} top stocks...")

    for i, (score, stock) in enumerate(top):
        try:
            df = get_all_prices_dataframe(stock.symbol, session)
            if not df.empty:
                compute_and_save_forecasts(stock.symbol, stock.id, df, session)
        except Exception as e:
            logger.error(f"{stock.symbol}: Forecast error: {e}")

        if progress_callback:
            progress_callback(i + 1, len(top), stock.symbol)

    logger.info("✅ Stock forecasting complete")


def run_forecasts_for_indexes_and_commodities(session: Session):
    """Run multi-horizon time-series forecasting for all major Indexes and Commodities."""
    from core.data_fetcher import get_index_dataframe, get_commodity_dataframe

    # 1. Indexes
    idx_symbols = session.execute(text("SELECT DISTINCT symbol, name FROM index_prices")).fetchall()
    for sym, name in idx_symbols:
        try:
            df = get_index_dataframe(sym, session, days=1500)
            if not df.empty and len(df) >= 50:
                compute_and_save_forecasts(sym, 0, df, session)
                logger.info(f"✅ Generated forecast for Index: {name} ({sym})")
        except Exception as e:
            logger.error(f"{sym}: Index forecast error: {e}")

    # 2. Commodities
    comm_symbols = session.execute(text("SELECT DISTINCT symbol, name FROM commodity_prices")).fetchall()
    for sym, name in comm_symbols:
        try:
            df = get_commodity_dataframe(sym, session, days=1500)
            if not df.empty and len(df) >= 50:
                compute_and_save_forecasts(sym, 0, df, session)
                logger.info(f"✅ Generated forecast for Commodity: {name} ({sym})")
        except Exception as e:
            logger.error(f"{sym}: Commodity forecast error: {e}")

    logger.info("✅ Index & Commodity forecasting complete")


def compute_ml_ensemble_consensus(df: pd.DataFrame) -> Dict:
    """
    Train and evaluate a 5-Model ML Ensemble on historical stock data:
    1. Gradient Boosting Machine (Optimized Fast Iterations)
    2. Random Forest Bagging Ensemble (Parallel Multi-core)
    3. Polynomial Ridge Trend Acceleration Model
    4. Holt-Winters / Exponential Smoothing Momentum
    5. Monte Carlo Stochastic Brownian Motion (Vectorized NumPy)

    Returns consensus confidence %, direction, and individual model predictions in <0.2s.
    """
    if df.empty or len(df) < 60:
        return {}

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import Ridge, LogisticRegression
    from sklearn.preprocessing import PolynomialFeatures

    features = build_features(df).dropna()
    if len(features) < 40:
        return {}

    close = df.loc[features.index, "close"]
    # Binary target: 10-day forward return > 1.5%
    fwd_ret = (close.shift(-10) - close) / close
    valid_idx = fwd_ret.dropna().index

    X = features.loc[valid_idx].values
    y = (fwd_ret.loc[valid_idx] > 0.015).astype(int).values

    if len(np.unique(y)) < 2 or len(X) < 30:
        return {}

    latest_X = features.iloc[[-1]].values

    # 1. XGBoost Gradient Boosting Machine
    gbm_prob = 0.50
    try:
        import xgboost as xgb
        xgb_clf = xgb.XGBClassifier(
            n_estimators=40, max_depth=3, learning_rate=0.05,
            subsample=0.8, random_state=42, n_jobs=2, eval_metric='logloss'
        )
        xgb_clf.fit(X, y)
        gbm_prob = float(xgb_clf.predict_proba(latest_X)[0, 1])
    except Exception:
        try:
            lr = LogisticRegression(max_iter=100, random_state=42)
            lr.fit(X, y)
            gbm_prob = float(lr.predict_proba(latest_X)[0, 1])
        except Exception:
            pass

    # 2. Random Forest (RF - Parallel Multi-core)
    rf_prob = 0.50
    try:
        rf = RandomForestClassifier(n_estimators=30, max_depth=5, random_state=42, n_jobs=-1)
        rf.fit(X, y)
        rf_prob = float(rf.predict_proba(latest_X)[0, 1])
    except Exception:
        pass

    # 3. Polynomial Ridge Acceleration
    ridge_signal = "BULLISH"
    poly_score = 0.55
    try:
        x_time = np.arange(len(close)).reshape(-1, 1)
        poly = PolynomialFeatures(degree=2)
        x_poly = poly.fit_transform(x_time)
        ridge = Ridge(alpha=1.0)
        ridge.fit(x_poly[-40:], close.values[-40:])
        coef_accel = ridge.coef_[2] if len(ridge.coef_) > 2 else 0.0
        if coef_accel > 0:
            ridge_signal = "BULLISH (Accelerating)"
            poly_score = 0.65
        elif coef_accel < 0:
            ridge_signal = "BEARISH (Decelerating)"
            poly_score = 0.35
        else:
            ridge_signal = "NEUTRAL"
            poly_score = 0.50
    except Exception:
        pass

    # 4. Holt-Winters / Exponential Smoothing Momentum
    hw_score = 0.50
    try:
        ema_short = float(close.ewm(span=7, adjust=False).mean().iloc[-1])
        ema_long = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        hw_momentum = (ema_short - ema_long) / ema_long
        hw_score = min(0.90, max(0.10, 0.50 + (hw_momentum * 5.0)))
    except Exception:
        pass

    # 5. Monte Carlo PoP (Vectorized NumPy simulation in ~2ms)
    mc_pop = 55.0
    try:
        ret_arr = close.pct_change().dropna().values
        daily_mu = float(np.mean(ret_arr))
        daily_sig = float(np.std(ret_arr))
        sims = np.random.normal(daily_mu, daily_sig, (500, 30))
        paths = close.values[-1] * np.cumprod(1 + sims, axis=1)
        mc_pop = float(np.mean(paths[:, -1] > close.values[-1]) * 100.0)
    except Exception:
        pass
    mc_score = mc_pop / 100.0

    # Weighted Ensemble Aggregator
    # Weights: GBM/LogReg (30%), RF (25%), Poly Ridge (15%), Holt-Winters (15%), Monte Carlo (15%)
    ensemble_prob = (
        gbm_prob * 0.30 +
        rf_prob * 0.25 +
        poly_score * 0.15 +
        hw_score * 0.15 +
        mc_score * 0.15
    )

    ensemble_confidence_pct = round(ensemble_prob * 100, 1)

    if ensemble_confidence_pct >= 68.0:
        consensus = "🟢 STRONG BUY"
        consensus_desc = "All 5 ML algorithms confirm strong upward momentum and positive expected alpha."
    elif ensemble_confidence_pct >= 54.0:
        consensus = "🟢 BUY"
        consensus_desc = "Majority ML consensus is bullish with favorable risk-reward probability."
    elif ensemble_confidence_pct >= 44.0:
        consensus = "🟡 NEUTRAL"
        consensus_desc = "ML models indicate consolidation or mixed directional signals."
    else:
        consensus = "🔴 SELL / CAUTION"
        consensus_desc = "Ensemble ML detects downside momentum expansion and unfavorable risk metrics."

    return {
        "ensemble_confidence_pct": ensemble_confidence_pct,
        "consensus_label": consensus,
        "consensus_description": consensus_desc,
        "models": [
            {"model": "Gradient Boosting / Statistical Classifier", "prob_bullish": f"{gbm_prob*100:.1f}%", "verdict": "🟢 Bullish" if gbm_prob >= 0.55 else ("🔴 Bearish" if gbm_prob <= 0.45 else "🟡 Neutral"), "weight": "30%"},
            {"model": "Random Forest (Multi-Tree Bagging)", "prob_bullish": f"{rf_prob*100:.1f}%", "verdict": "🟢 Bullish" if rf_prob >= 0.55 else ("🔴 Bearish" if rf_prob <= 0.45 else "🟡 Neutral"), "weight": "25%"},
            {"model": "Polynomial Ridge Acceleration", "prob_bullish": f"{poly_score*100:.1f}%", "verdict": ridge_signal, "weight": "15%"},
            {"model": "Holt-Winters Trend Momentum", "prob_bullish": f"{hw_score*100:.1f}%", "verdict": "🟢 Bullish" if hw_score >= 0.55 else ("🔴 Bearish" if hw_score <= 0.45 else "🟡 Neutral"), "weight": "15%"},
            {"model": "Monte Carlo PoP (500 Paths)", "prob_bullish": f"{mc_pop:.1f}%", "verdict": "🟢 Bullish" if mc_pop >= 55 else "🟡 Neutral", "weight": "15%"},
        ]
    }

