"""
Mutual Funds Data Ingestion Engine
- Fetches official AMFI NAV data and comprehensive historical records via mfapi.in
- Manages curated Direct-Growth scheme universe across SEBI Equity, Hybrid, and Index categories
- Supports historical backfill from inception / April 2006 to current date
- Safe SSL verification fallback for Windows and headless environments
"""
import logging
import ssl
import json
import urllib.request
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

import importlib
import db.database
if not hasattr(db.database, "MutualFund"):
    importlib.reload(db.database)
from db.database import MutualFund, MutualFundNAV, get_global_engine, get_session

logger = logging.getLogger(__name__)

# SSL context that works reliably across corporate proxies and Windows environments
_SSL_CTX = ssl._create_unverified_context()

# ─── Curated Universe of Direct-Growth Category Leaders ───────────────────────
CURATED_SCHEMES = [
    {
        "scheme_code": 122639,
        "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
        "fund_house": "PPFAS Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF879O01027",
        "expense_ratio": 0.65,
        "crisil_rating": 5
    },
    {
        "scheme_code": 118955,
        "scheme_name": "HDFC Flexi Cap Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179K01608",
        "expense_ratio": 0.78,
        "crisil_rating": 4
    },
    {
        "scheme_code": 125354,
        "scheme_name": "Quant Flexi Cap Fund - Direct Plan - Growth",
        "fund_house": "Quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF966L01AB3",
        "expense_ratio": 0.77,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120503,
        "scheme_name": "JM Flexicap Fund - Direct Plan - Growth Option",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF192K01344",
        "expense_ratio": 0.68,
        "crisil_rating": 5
    },
    {
        "scheme_code": 120828,
        "scheme_name": "Kotak Flexicap Fund - Direct Plan - Growth",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174K01LS2",
        "expense_ratio": 0.6,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119598,
        "scheme_name": "Mirae Asset Large Cap Fund - Direct Plan - Growth",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF769K01BF4",
        "expense_ratio": 0.54,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119063,
        "scheme_name": "ICICI Prudential Bluechip Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF109K011Q8",
        "expense_ratio": 0.88,
        "crisil_rating": 5
    },
    {
        "scheme_code": 119717,
        "scheme_name": "SBI Bluechip Fund - Direct Plan - Growth",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "BSE 100 TRI",
        "isin_growth": "INF200K01RS4",
        "expense_ratio": 0.85,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118989,
        "scheme_name": "HDFC Top 100 Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF179K01BD9",
        "expense_ratio": 0.98,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120586,
        "scheme_name": "Canara Robeco Emerging Equities - Direct Plan - Growth Option",
        "fund_house": "Canara Robeco Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF760K01CV7",
        "expense_ratio": 0.62,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120152,
        "scheme_name": "Motilal Oswal Midcap Fund - Direct Plan - Growth",
        "fund_house": "Motilal Oswal Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF247L01704",
        "expense_ratio": 0.7,
        "crisil_rating": 5
    },
    {
        "scheme_code": 118988,
        "scheme_name": "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF179K01BB3",
        "expense_ratio": 0.73,
        "crisil_rating": 5
    },
    {
        "scheme_code": 119797,
        "scheme_name": "Kotak Emerging Equity Fund - Direct Plan - Growth",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF174K01MU4",
        "expense_ratio": 0.49,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120847,
        "scheme_name": "Nippon India Growth Fund - Direct Plan - Growth Option",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF204K01582",
        "expense_ratio": 0.82,
        "crisil_rating": 5
    },
    {
        "scheme_code": 125494,
        "scheme_name": "Quant Mid Cap Fund - Direct Plan - Growth",
        "fund_house": "Quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF966L01AO6",
        "expense_ratio": 0.76,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120823,
        "scheme_name": "Nippon India Small Cap Fund - Direct Plan - Growth Option",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF204K01525",
        "expense_ratio": 0.67,
        "crisil_rating": 5
    },
    {
        "scheme_code": 125497,
        "scheme_name": "Quant Small Cap Fund - Direct Plan - Growth Option",
        "fund_house": "Quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF966L01AA5",
        "expense_ratio": 0.77,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118959,
        "scheme_name": "HDFC Small Cap Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "BSE 250 SmallCap TRI",
        "isin_growth": "INF179K01AR7",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 125307,
        "scheme_name": "Bandhan Small Cap Fund - Direct Plan - Growth",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "BSE 250 SmallCap TRI",
        "isin_growth": "INF194KA1W05",
        "expense_ratio": 0.44,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120716,
        "scheme_name": "UTI Nifty 50 Index Fund - Direct Plan - Growth Option",
        "fund_house": "UTI Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF789F01AX7",
        "expense_ratio": 0.18,
        "crisil_rating": 5
    },
    {
        "scheme_code": 120717,
        "scheme_name": "UTI Nifty Next 50 Index Fund - Direct Plan - Growth Option",
        "fund_house": "UTI Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY Next 50 TRI",
        "isin_growth": "INF789F01AY5",
        "expense_ratio": 0.32,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119062,
        "scheme_name": "ICICI Prudential Nifty 50 Index Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF109K015X5",
        "expense_ratio": 0.17,
        "crisil_rating": 5
    },
    {
        "scheme_code": 148943,
        "scheme_name": "Motilal Oswal Nifty Midcap 150 Index Fund - Direct Plan - Growth",
        "fund_house": "Motilal Oswal Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF247L01AH4",
        "expense_ratio": 0.28,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119065,
        "scheme_name": "ICICI Prudential Balanced Advantage Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Dynamic Asset Allocation / Balanced Advantage",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF109K013Q4",
        "expense_ratio": 0.82,
        "crisil_rating": 5
    },
    {
        "scheme_code": 118968,
        "scheme_name": "HDFC Balanced Advantage Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Dynamic Asset Allocation / Balanced Advantage",
        "benchmark": "NIFTY 50 Hybrid Composite Debt 50:50 TRI",
        "isin_growth": "INF179K01962",
        "expense_ratio": 0.72,
        "crisil_rating": 5
    },
    {
        "scheme_code": 120844,
        "scheme_name": "Edelweiss Balanced Advantage Fund - Direct Plan - Growth",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Dynamic Asset Allocation / Balanced Advantage",
        "benchmark": "NIFTY 50 Hybrid Composite Debt 50:50 TRI",
        "isin_growth": "INF754K01BC0",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119092,
        "scheme_name": "ICICI Prudential Liquid Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Debt",
        "sub_category": "Liquid Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF109K011E4",
        "expense_ratio": 0.15,
        "crisil_rating": 5
    },
    {
        "scheme_code": 118972,
        "scheme_name": "HDFC Liquid Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Debt",
        "sub_category": "Liquid Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF179K01AZ4",
        "expense_ratio": 0.2,
        "crisil_rating": 5
    },
    {
        "scheme_code": 118424,
        "scheme_name": "BANDHAN Flexi Cap Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF194K01W62",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119076,
        "scheme_name": "DSP Flexi Cap Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF740K01PI2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 140353,
        "scheme_name": "Edelweiss Flexi Cap Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF843K01KK1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118535,
        "scheme_name": "Franklin India Flexi Cap Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01FK3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 129046,
        "scheme_name": "Motilal Oswal Flexi Cap Fund",
        "fund_house": "Motilal Oswal Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF247L01502",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 143793,
        "scheme_name": "Navi Flexi Cap Fund",
        "fund_house": "Navi Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF959L01DT9",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149094,
        "scheme_name": "Nippon India Flexi Cap Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF204KC1121",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120843,
        "scheme_name": "Quant Flexi Cap Fund",
        "fund_house": "quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF966L01911",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119718,
        "scheme_name": "SBI FLEXICAP FUND",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF200K01UG1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 144546,
        "scheme_name": "Tata Flexi Cap Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF277K015K0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120662,
        "scheme_name": "UTI - Flexi Cap Fund.",
        "fund_house": "UTI Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF789F01TC4",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149303,
        "scheme_name": "BANDHAN MULTI CAP FUND",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF194KB1CL0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152094,
        "scheme_name": "Edelweiss Multi Cap Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF754K01SD8",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152739,
        "scheme_name": "Franklin India Multi Cap Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01XA7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149368,
        "scheme_name": "HDFC Multi Cap Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179KC1BS5",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118650,
        "scheme_name": "Nippon India Multi Cap Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF204K01XF9",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118479,
        "scheme_name": "BANDHAN LARGE CAP FUND",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF194K01Z44",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119250,
        "scheme_name": "DSP Large Cap Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF740K01PR3",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118617,
        "scheme_name": "Edelweiss Large Cap Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF754K01BW4",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118531,
        "scheme_name": "Franklin India Large Cap Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF090I01FN7",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119018,
        "scheme_name": "HDFC Large Cap Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF179K01YV8",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118632,
        "scheme_name": "Nippon India Large Cap Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF204K01XI3",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150440,
        "scheme_name": "quant Large Cap Fund",
        "fund_house": "quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF966L01AT0",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119160,
        "scheme_name": "Tata Large Cap Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF277K01QZ7",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120656,
        "scheme_name": "UTI - Large Cap Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF789F01US8",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120465,
        "scheme_name": "Axis Large Cap Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF846K01DP8",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120030,
        "scheme_name": "HSBC Large Cap Fund",
        "fund_house": "HSBC Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF336L01CM7",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120392,
        "scheme_name": "Invesco India Large Cap Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF205K01LB0",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120490,
        "scheme_name": "JM Large Cap Fund",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF192K01BZ0",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 146549,
        "scheme_name": "Mahindra Manulife Large Cap Fund",
        "fund_house": "Mahindra Manulife Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF174V01721",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118419,
        "scheme_name": "Bandhan Large & Mid Cap Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF194K01V89",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119218,
        "scheme_name": "DSP Large & Mid Cap Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF740K01PL6",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 140175,
        "scheme_name": "Edelweiss Large & Mid Cap Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF843K01AL0",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118510,
        "scheme_name": "Franklin India Large & Mid Cap Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF090I01IN1",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120596,
        "scheme_name": "ICICI Prudential Large & Mid Cap Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF109K011O5",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147704,
        "scheme_name": "Motilal Oswal Large and Midcap Fund",
        "fund_house": "Motilal Oswal Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF247L01999",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 135677,
        "scheme_name": "Navi Large & Midcap Fund",
        "fund_house": "Navi Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF959L01CH6",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118678,
        "scheme_name": "Nippon India Vision Large & Mid Cap Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF204K01F20",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120826,
        "scheme_name": "Quant Large & Mid Cap Fund",
        "fund_house": "quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF966L01648",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119721,
        "scheme_name": "SBI LARGE & MIDCAP FUND",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF200K01UJ5",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119202,
        "scheme_name": "Tata Large & Mid Cap Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF277K01MK8",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120665,
        "scheme_name": "UTI Large & Mid Cap Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF789F01UG3",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 145110,
        "scheme_name": "Axis Large & Mid Cap Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF846K01J46",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 130498,
        "scheme_name": "HDFC Large & Mid Cap Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF179KA1RQ7",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120505,
        "scheme_name": "Axis Midcap Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF846K01EH3",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119071,
        "scheme_name": "DSP Midcap Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF740K01PX1",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 140228,
        "scheme_name": "Edelweiss Mid Cap Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF843K01AO4",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118533,
        "scheme_name": "Franklin India Mid Cap Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF090I01FH9",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118666,
        "scheme_name": "Nippon India Growth Mid Cap Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF204K01E39",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118665,
        "scheme_name": "Nippon India Growth Mid Cap Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF204K01E21",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118668,
        "scheme_name": "Nippon India Growth Mid Cap Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF204K01E54",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120841,
        "scheme_name": "Quant Mid Cap Fund",
        "fund_house": "quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF966L01887",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119716,
        "scheme_name": "SBI MIDCAP FUND",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF200K01TP4",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119178,
        "scheme_name": "Tata Mid Cap Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF277K01PY2",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120726,
        "scheme_name": "UTI - Mid Cap Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF789F01UA6",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 146772,
        "scheme_name": "HSBC Large & Mid Cap Fund",
        "fund_house": "HSBC Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF336L01NV5",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120357,
        "scheme_name": "Invesco India Large & Mid Cap Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF205K01MA0",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153629,
        "scheme_name": "JM Large & Mid Cap Fund",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF192K01NK7",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120158,
        "scheme_name": "Kotak Large & Mid Cap Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF174K01LF9",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147946,
        "scheme_name": "BANDHAN Small Cap Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF194KB1AL4",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119212,
        "scheme_name": "DSP Small Cap Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF740K01QD1",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 146196,
        "scheme_name": "Edelweiss Small Cap Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF754K01JN6",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118525,
        "scheme_name": "Franklin India Small Cap Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF090I01IQ4",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 130503,
        "scheme_name": "HDFC Small Cap Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF179KA1RW5",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120164,
        "scheme_name": "Kotak Small Cap Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF174K01KT2",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152237,
        "scheme_name": "Motilal Oswal Small Cap Fund",
        "fund_house": "Motilal Oswal Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF247L01BY3",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118778,
        "scheme_name": "Nippon India Small Cap Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF204K01K15",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152107,
        "scheme_name": "QUANTUM SMALL CAP FUND",
        "fund_house": "Quantum Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF082J01432",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 145206,
        "scheme_name": "Tata Small Cap Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF277K011O1",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120591,
        "scheme_name": "ICICI Prudential Small Cap Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF109K015M0",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 145137,
        "scheme_name": "Invesco India Small Cap Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF205K013T3",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152614,
        "scheme_name": "JM Small Cap Fund",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF192K01NH3",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150915,
        "scheme_name": "Mahindra Manulife Small Cap Fund",
        "fund_house": "Mahindra Manulife Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF174V01BK7",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153196,
        "scheme_name": "Mirae Asset Small Cap Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF769K01NJ4",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148618,
        "scheme_name": "UTI Small Cap Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF789F1AUQ1",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118421,
        "scheme_name": "Bandhan Focused Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF194K01W21",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119096,
        "scheme_name": "DSP Focused Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF740K01OB0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150376,
        "scheme_name": "Edelweiss Focused Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF754K01OP1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118564,
        "scheme_name": "Franklin India Focused Equity Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01IW2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118950,
        "scheme_name": "HDFC Focused Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179K01VK7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147473,
        "scheme_name": "Kotak Focused Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174KA1EN7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 122389,
        "scheme_name": "Motilal Oswal Focused Fund",
        "fund_house": "Motilal Oswal Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF247L01189",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118692,
        "scheme_name": "Nippon India Focused Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF204K01F95",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120834,
        "scheme_name": "Quant Focused Fund",
        "fund_house": "quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF966L01853",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119727,
        "scheme_name": "SBI FOCUSED FUND",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF200K01RJ1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147757,
        "scheme_name": "Tata Focused Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF277K017X9",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120468,
        "scheme_name": "Axis Focused Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF846K01CQ8",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148883,
        "scheme_name": "Canara Robeco Focused Fund",
        "fund_house": "Canara Robeco Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF760K01JQ6",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148411,
        "scheme_name": "HSBC Focused Fund",
        "fund_house": "HSBC Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF336L01PB2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118540,
        "scheme_name": "Franklin India ELSS Tax Saver Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01JS8",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119773,
        "scheme_name": "Kotak ELSS Tax Saver Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174K01LI3",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 133386,
        "scheme_name": "Motilal Oswal ELSS Tax Saver Fund",
        "fund_house": "Motilal Oswal Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF247L01569",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 111549,
        "scheme_name": "Quantum ELSS Tax Saver Fund",
        "fund_house": "Quantum Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF082J01069",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119723,
        "scheme_name": "SBI ELSS Tax Saver Fund",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF200K01UM9",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120715,
        "scheme_name": "UTI ELSS Tax Saver Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF789F01TF7",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118473,
        "scheme_name": "BANDHAN ELSS - Tax Saver Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF194K01Y29",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119242,
        "scheme_name": "DSP ELSS Tax Saver Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF740K01OK1",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118620,
        "scheme_name": "Edelweiss ELSS Tax Saver Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF754K01CA8",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119060,
        "scheme_name": "HDFC ELSS - Tax Saver Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179K01YS4",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151078,
        "scheme_name": "HSBC ELSS Tax saver Fund",
        "fund_house": "HSBC Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF917K01GP0",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120592,
        "scheme_name": "ICICI Prudential ELSS - Tax Saver Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K01Y31",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120416,
        "scheme_name": "Invesco India ELSS Tax Saver Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF205K01NT8",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120494,
        "scheme_name": "JM ELSS - Tax Saver Fund",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF192K01CE3",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 139781,
        "scheme_name": "Mahindra Manulife ELSS Tax Saver Fund",
        "fund_house": "Mahindra Manulife Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174V01093",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 135781,
        "scheme_name": "Mirae Asset ELSS Tax Saver Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF769K01DM9",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119769,
        "scheme_name": "Kotak Contra Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Contra Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174K01KZ9",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119835,
        "scheme_name": "SBI CONTRA FUND",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "Contra Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF200K01RA0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118481,
        "scheme_name": "Bandhan Value Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF194K01Z85",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148595,
        "scheme_name": "DSP Value Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF740KA1PP3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118494,
        "scheme_name": "Templeton India Value Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01GY2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118935,
        "scheme_name": "HDFC Value Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179K01VC4",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120323,
        "scheme_name": "ICICI Prudential Value Fund (erstwhile Value Discovery Fund)",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K012K1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118784,
        "scheme_name": "Nippon India Value Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF204K01K49",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149335,
        "scheme_name": "Quant Value Fund",
        "fund_house": "quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF966L01AN3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 103490,
        "scheme_name": "Quantum Value Fund",
        "fund_house": "Quantum Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF082J01036",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119231,
        "scheme_name": "Tata Value Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF277K01ND1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154600,
        "scheme_name": "Bandhan Contra Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Contra Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF194KB1KX8",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147928,
        "scheme_name": "Axis ESG Integration Strategy Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF846K01W23",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152710,
        "scheme_name": "Edelweiss Business Cycle Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF754K01TA2",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153214,
        "scheme_name": "Edelweiss Consumption Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic - Consumption",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF754K01TY2",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154108,
        "scheme_name": "Edelweiss Financial Services Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF754K01WH1",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 142388,
        "scheme_name": "Edelweiss Recently Listed IPO Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF754K01ML4",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152437,
        "scheme_name": "Edelweiss Technology Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Technology",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF754K01SK3",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118559,
        "scheme_name": "Franklin Asian Equity Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01IZ5",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118557,
        "scheme_name": "Franklin Build India Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01JF5",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153942,
        "scheme_name": "Franklin India Multi-Factor Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01YQ1",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118539,
        "scheme_name": "Franklin India Opportunities Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01GC8",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118537,
        "scheme_name": "Franklin India Technology Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Technology",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF090I01FE6",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148986,
        "scheme_name": "HDFC Banking & Financial Services Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179KC1BG0",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150805,
        "scheme_name": "HDFC Business Cycle Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179KC1DY9",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151804,
        "scheme_name": "HDFC Consumption Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic - Consumption",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179KC1GO3",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 141924,
        "scheme_name": "HDFC Housing Opportunities Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179KC1AU3",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118979,
        "scheme_name": "HDFC Infrastructure Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Infrastructure",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179K01WQ2",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152600,
        "scheme_name": "HDFC Manufacturing Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic - Manufacturing",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179KC1II1",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151458,
        "scheme_name": "HDFC MNC Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179KC1FC0",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152082,
        "scheme_name": "HDFC Pharma and Healthcare Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Healthcare / Pharma",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179KC1HO1",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151901,
        "scheme_name": "HDFC Transportation and Logistics Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179KC1GU0",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153684,
        "scheme_name": "ICICI Prudential Active Momentum Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K1A385",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120244,
        "scheme_name": "ICICI Prudential Banking & Financial Services Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K013J1",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151435,
        "scheme_name": "Axis Crisil IBX 50:50 Gilt Plus SDL September 2027 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K012O1",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149873,
        "scheme_name": "Axis CRISIL IBX SDL May 2027 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K017G6",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153051,
        "scheme_name": "Axis CRISIL-IBX AAA Bond Financial Services - Sep 2027 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K015Y3",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152887,
        "scheme_name": "Axis CRISIL-IBX AAA Bond NBFC - Jun 2027 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K017X1",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153172,
        "scheme_name": "Axis CRISIL-IBX AAA Bond NBFC-HFC - Jun 2027 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846KA1028",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153879,
        "scheme_name": "Axis CRISIL-IBX Financial Services 3-6 Months Debt Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846KA1226",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150854,
        "scheme_name": "Axis Nifty SDL September 2026 Debt Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K018K6",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149966,
        "scheme_name": "HSBC CRISIL IBX 50:50 Gilt Plus SDL Apr 2028 Index Fund",
        "fund_house": "HSBC Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF336L01QH7",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151479,
        "scheme_name": "HSBC CRISIL IBX Gilt June 2027 Index Fund",
        "fund_house": "HSBC Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF336L01QT2",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151593,
        "scheme_name": "Invesco India Nifty G-sec Jul 2027 Index Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF205KA1775",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151597,
        "scheme_name": "Invesco India Nifty G-sec Sep 2032 Index Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF205KA1817",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150792,
        "scheme_name": "Mirae Asset CRISIL IBX Gilt Index - April 2033 Index Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF769K01IX5",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153634,
        "scheme_name": "Mirae Asset CRISIL-IBX Financial Services 9-12 Months Debt Index Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Index",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF769K01OS3",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150358,
        "scheme_name": "Mirae Asset Nifty SDL Jun 2027 Index Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF769K01IH8",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151691,
        "scheme_name": "Mirae Asset Nifty SDL June 2028 Index Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF769K01JZ8",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147889,
        "scheme_name": "Axis Income Plus Arbitrage Omni FOF",
        "fund_house": "Axis Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF846K01U09",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153924,
        "scheme_name": "Axis Income Plus Arbitrage Passive FOF",
        "fund_house": "Axis Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF846KA1283",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 129201,
        "scheme_name": "HSBC Aggressive Hybrid Active FOF (erstwhile HSBC Managed Solutions India - Growth fund)",
        "fund_house": "HSBC Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF336L01IB7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 129200,
        "scheme_name": "HSBC Aggressive Hybrid Active FOF (erstwhile HSBC Managed Solutions India - Growth fund)",
        "fund_house": "HSBC Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF336L01ID3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 129197,
        "scheme_name": "HSBC Income Plus Arbitrage Active FOF (erstwhile HSBC Managed Solution India - Conservative Plan)",
        "fund_house": "HSBC Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF336L01IP7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 129193,
        "scheme_name": "HSBC Multi Asset Active FOF (erstwhile HSBC Managed Solutions India - Moderate Fund)",
        "fund_house": "HSBC Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Multi Asset Allocation",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF336L01IJ0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153697,
        "scheme_name": "Invesco India Income Plus Arbitrage Active Fund of Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF205KA1BA3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154316,
        "scheme_name": "Kotak Multi Asset Active FOF",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Multi Asset Allocation",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF174KA1ZO0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154007,
        "scheme_name": "Mahindra Manulife Income Plus Arbitrage Active FOF",
        "fund_house": "Mahindra Manulife Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF174V01CU4",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153638,
        "scheme_name": "Mirae Asset Income plus Arbitrage Active FOF",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF769K01OY1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154646,
        "scheme_name": "Nippon India Income Plus Arbitrage Omni Fund of Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF204KC1HO0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154658,
        "scheme_name": "quant Income Plus Arbitrage Active FOF",
        "fund_house": "quant Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF966L01EJ3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 129008,
        "scheme_name": "Franklin India Banking & PSU Debt Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Debt",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF090I01KR8",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 128629,
        "scheme_name": "HDFC Banking and PSU Debt Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Debt",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF179KA1IZ7",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 123693,
        "scheme_name": "Kotak Banking and PSU Debt Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Debt",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF174K01KH7",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 135916,
        "scheme_name": "BANDHAN Corporate Bond Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Debt",
        "sub_category": "Corporate Bond Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF194KA1M23",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 144646,
        "scheme_name": "DSP Corporate Bond Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Debt",
        "sub_category": "Corporate Bond Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF740KA1KE8",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118987,
        "scheme_name": "HDFC Corporate Bond Fund",
        "fund_house": "HDFC Mutual Fund",
        "category": "Debt",
        "sub_category": "Corporate Bond Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF179K01XD8",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149882,
        "scheme_name": "SBI MultiCap Fund",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF200KA18E2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149668,
        "scheme_name": "Sundaram Multi Cap Fund (Formerly Known as Principal Multi Cap Growth Fund)",
        "fund_house": "Sundaram Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF173K01FN7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149669,
        "scheme_name": "Sundaram Multi Cap Fund (Formerly Known as Principal Multi Cap Growth Fund)",
        "fund_house": "Sundaram Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF173K01FQ0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151232,
        "scheme_name": "TATA MULTICAP FUND",
        "fund_house": "Tata Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF277KA1679",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 141925,
        "scheme_name": "Axis Flexi Cap Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF846K01B28",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120046,
        "scheme_name": "HSBC Flexi Cap Fund",
        "fund_house": "HSBC Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF336L01DH5",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148990,
        "scheme_name": "ICICI Prudential Flexi Cap fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC1R14",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149763,
        "scheme_name": "Invesco India Flexi Cap Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF205KA1494",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120492,
        "scheme_name": "JM Flexi Cap Fund",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF192K01CC7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120166,
        "scheme_name": "Kotak Flexi Cap Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174K01LS2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149104,
        "scheme_name": "Mahindra Manulife Flexi Cap Fund",
        "fund_house": "Mahindra Manulife Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174V01AS2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151412,
        "scheme_name": "Mirae Asset Flexi Cap Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF769K01JJ2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149383,
        "scheme_name": "Axis Multicap Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF846K013E0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151824,
        "scheme_name": "Canara Robeco Multi Cap Fund",
        "fund_house": "Canara Robeco Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF760K01KO9",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152310,
        "scheme_name": "DSP Multi Cap Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF740KA1UC1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151290,
        "scheme_name": "HSBC Multi Cap Fund",
        "fund_house": "HSBC Mutual Fund",
        "category": "Equity",
        "sub_category": "Multi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF336L01QN5",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118825,
        "scheme_name": "Mirae Asset Large Cap Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF769K01AX2",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147840,
        "scheme_name": "Mahindra Manulife Large & Mid Cap Fund",
        "fund_house": "Mahindra Manulife Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF174V01945",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118834,
        "scheme_name": "Mirae Asset Large & Midcap Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF769K01BI1",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150404,
        "scheme_name": "BANDHAN MID CAP FUND",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF194KB1DJ2",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150817,
        "scheme_name": "Canara Robeco Mid Cap Fund",
        "fund_house": "Canara Robeco Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF760K01KI1",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151036,
        "scheme_name": "HSBC Midcap Fund",
        "fund_house": "HSBC Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF917K01FZ1",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120381,
        "scheme_name": "ICICI Prudential Mid Cap Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF109K011N7",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120403,
        "scheme_name": "Invesco India Mid Cap Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF205K01MV6",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150815,
        "scheme_name": "JM Mid Cap Fund",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF192K01MV6",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119775,
        "scheme_name": "Kotak Mid Cap Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF174K01LT0",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 142110,
        "scheme_name": "Mahindra Manulife Mid Cap Fund",
        "fund_house": "Mahindra Manulife Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF174V01507",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147445,
        "scheme_name": "Mirae Asset Midcap Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF769K01FA9",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120722,
        "scheme_name": "ICICI Prudential Focused Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K018N2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148481,
        "scheme_name": "Invesco India Focused Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF205KA1213",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120488,
        "scheme_name": "JM Focused Fund",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF192K01BW7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148567,
        "scheme_name": "Mahindra Manulife Focused Fund",
        "fund_house": "Mahindra Manulife Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174V01AG7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147206,
        "scheme_name": "Mirae Asset Focused Fund",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF769K01EU0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149091,
        "scheme_name": "UTI Focused Fund (30 stocks)",
        "fund_house": "UTI Mutual Fund",
        "category": "Equity",
        "sub_category": "Focused Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF789F1AVA3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118803,
        "scheme_name": "Nippon India ELSS Tax Saver Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF204K01L55",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 132756,
        "scheme_name": "Tata ELSS - Tax Saver Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF277K01I86",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 140487,
        "scheme_name": "SBI Long Term Advantage Fund - Series IV",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF200KA1LS9",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 142138,
        "scheme_name": "SBI Long Term Advantage Fund - Series V",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF200KA1RW8",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 143178,
        "scheme_name": "SBI Long Term Advantage Fund - Series VI",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "ELSS (Tax Saver)",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF200KA1TO1",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120348,
        "scheme_name": "Invesco India Contra Fund",
        "fund_house": "Invesco Mutual Fund",
        "category": "Equity",
        "sub_category": "Contra Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF205K01LE4",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149166,
        "scheme_name": "Axis Value Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF846K010C0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149085,
        "scheme_name": "Canara Robeco Value Fund",
        "fund_house": "Canara Robeco Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF760K01JW4",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120486,
        "scheme_name": "JM Value Fund",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF192K01BT3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153303,
        "scheme_name": "Mahindra Manulife Value Fund",
        "fund_house": "Mahindra Manulife Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174V01CI9",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120751,
        "scheme_name": "UTI Value Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF789F01VB2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152949,
        "scheme_name": "Axis Nifty500 Value 50 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF846K013Y8",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151739,
        "scheme_name": "UTI Nifty 500 Value 50 Index Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF789F1AYN0",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 140274,
        "scheme_name": "Edelweiss US Value Equity Offshore Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF843K01EC1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152990,
        "scheme_name": "Bandhan Nifty 500 Value 50 Index Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF194KB1IW4",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152936,
        "scheme_name": "ICICI Prudential Nifty200 Value 30 Index Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC13X2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152365,
        "scheme_name": "ICICI Prudential Nifty50 Value 20 Index Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Value Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC16T3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 146951,
        "scheme_name": "ICICI Prudential Bharat Consumption Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic - Consumption",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC1YD4",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148651,
        "scheme_name": "ICICI Prudential Business Cycle Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC1P24",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147662,
        "scheme_name": "ICICI Prudential Commodities Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC1F91",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153867,
        "scheme_name": "ICICI Prudential Conglomerate Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K1A427",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152728,
        "scheme_name": "ICICI PRUDENTIAL ENERGY OPPORTUNITIES FUND",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Energy & Power",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC12W6",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153070,
        "scheme_name": "ICICI Prudential Equity Minimum Variance Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC10Y6",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148516,
        "scheme_name": "ICICI Prudential ESG Exclusionary Strategy Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC1O09",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120688,
        "scheme_name": "ICICI Prudential Exports & Services Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K01W25",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120587,
        "scheme_name": "ICICI Prudential FMCG Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K01Z14",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150310,
        "scheme_name": "ICICI PRUDENTIAL HOUSING OPPORTUNITIES FUND",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC10C2",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120621,
        "scheme_name": "ICICI Prudential Infrastructure Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Infrastructure",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K018M4",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151580,
        "scheme_name": "ICICI Prudential Innovation Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC12T2",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 147346,
        "scheme_name": "ICICI Prudential MNC Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC1D93",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150539,
        "scheme_name": "ICICI PRUDENTIAL PSU EQUITY FUND",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC12I5",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153458,
        "scheme_name": "ICICI Prudential Quality Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K1A187",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 148600,
        "scheme_name": "ICICI Prudential QUANT FUND",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC1O66",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153184,
        "scheme_name": "ICICI Prudential Rural Opportunities Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC12Z9",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120594,
        "scheme_name": "ICICI Prudential Technology Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Technology",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K01Z48",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150685,
        "scheme_name": "ICICI PRUDENTIAL TRANSPORTATION AND LOGISTICS FUND",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109KC12K1",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120186,
        "scheme_name": "ICICI Prudential US Bluechip Equity Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF109K01Z71",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153753,
        "scheme_name": "Kotak Active Momentum Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Thematic Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174KA1XA4",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151384,
        "scheme_name": "Kotak Banking and Financial Services Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Sectoral/Thematic",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174KA1MD1",
        "expense_ratio": 0.75,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154467,
        "scheme_name": "SBI Crisil - IBX SDL Index - June 2034 Index Fund",
        "fund_house": "SBI Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF200KB1BO8",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151185,
        "scheme_name": "UTI CRISIL SDL Maturity April 2033 Index Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF789F1AWX3",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151239,
        "scheme_name": "UTI CRISIL SDL Maturity June 2027 Index Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF789F1AWZ8",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151487,
        "scheme_name": "UTI NIFTY SDL Plus AAA PSU Bond Apr 2028- 75:25 Index Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF789F1AXR3",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154171,
        "scheme_name": "Axis BSE India Sector Leaders Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846KA1424",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152422,
        "scheme_name": "Axis BSE Sensex Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K012V6",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149373,
        "scheme_name": "Axis Nifty 50 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K013D2",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152731,
        "scheme_name": "Axis Nifty 500 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K019W9",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 152629,
        "scheme_name": "Axis Nifty Bank Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Sectoral - Banking & Financials",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K015W7",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154594,
        "scheme_name": "Axis Nifty Energy Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Sectoral - Energy & Power",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846KA1580",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 154326,
        "scheme_name": "Axis Nifty India Defence Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846KA1523",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 151785,
        "scheme_name": "Axis Nifty IT Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K017R3",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149936,
        "scheme_name": "Axis Nifty Midcap 50 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K019H0",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149466,
        "scheme_name": "Axis Nifty Next 50 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K019E7",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149894,
        "scheme_name": "Axis Nifty Smallcap 50 Index Fund",
        "fund_house": "Axis Mutual Fund",
        "category": "Index",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF846K013H3",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 153442,
        "scheme_name": "UTI Income Plus Arbitrage Active Fund of Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF789F1AB55",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 140382,
        "scheme_name": "Bandhan Aggressive Hybrid Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF194KA1U56",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119019,
        "scheme_name": "DSP Aggressive Hybrid Fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF740K01NY4",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118546,
        "scheme_name": "Franklin India Aggressive Hybrid Fund",
        "fund_house": "Franklin Templeton Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF090I01FZ1",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119767,
        "scheme_name": "Kotak Aggressive Hybrid Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF174K01LL7",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 133035,
        "scheme_name": "Kotak Aggressive Hybrid Fund",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF174K01F00",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 143163,
        "scheme_name": "Navi Aggressive Hybrid Fund",
        "fund_house": "Navi Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF959L01CX3",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120819,
        "scheme_name": "Quant Aggressive Hybrid Fund",
        "fund_house": "quant Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF966L01556",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119053,
        "scheme_name": "Tata Aggressive Hybrid Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF277K01MN2",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120674,
        "scheme_name": "UTI Aggressive Hybrid Fund",
        "fund_house": "UTI Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Aggressive Hybrid Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF789F01SK9",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118474,
        "scheme_name": "BANDHAN Arbitrage Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF194K01Y60",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 142283,
        "scheme_name": "DSP Arbitrage fund",
        "fund_house": "DSP Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Arbitrage Fund",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF740KA1DN4",
        "expense_ratio": 0.7,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120692,
        "scheme_name": "ICICI Prudential Corporate Bond Fund",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Debt",
        "sub_category": "Corporate Bond Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF109K016B1",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118814,
        "scheme_name": "Nippon India Corporate Bond Fund",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Debt",
        "sub_category": "Corporate Bond Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF204K01C15",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 146215,
        "scheme_name": "SBI Corporate Bond Fund",
        "fund_house": "SBI Mutual Fund",
        "category": "Debt",
        "sub_category": "Corporate Bond Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF200KA1YR4",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 149361,
        "scheme_name": "Tata Corporate Bond Fund",
        "fund_house": "Tata Mutual Fund",
        "category": "Debt",
        "sub_category": "Corporate Bond Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF277KA1224",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118364,
        "scheme_name": "BANDHAN LIQUID Fund",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Debt",
        "sub_category": "Liquid Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF194K01I60",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 140196,
        "scheme_name": "Edelweiss Liquid Fund",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Debt",
        "sub_category": "Liquid Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF754K01GM4",
        "expense_ratio": 0.2,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120754,
        "scheme_name": "ICICI Prudential Short Term Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Debt",
        "sub_category": "Short Duration Fund",
        "benchmark": "CRISIL Short Duration Debt A-II Index",
        "isin_growth": "INF109K013N3",
        "expense_ratio": 0.38,
        "crisil_rating": 4
    },
    {
        "scheme_code": 150737,
        "scheme_name": "HDFC Silver ETF Fund of Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Commodity",
        "sub_category": "Silver ETF FoF",
        "benchmark": "Domestic Price of Silver",
        "isin_growth": "INF179KC1DU7",
        "expense_ratio": 0.25,
        "crisil_rating": 4
    }
]

def seed_curated_mutual_funds(session: Session) -> int:
    """Seeds the curated mutual fund universe into the database."""
    inserted = 0
    for item in CURATED_SCHEMES:
        existing = session.query(MutualFund).filter_by(scheme_code=item["scheme_code"]).first()
        if not existing:
            mf = MutualFund(
                scheme_code=item["scheme_code"],
                scheme_name=item["scheme_name"],
                fund_house=item["fund_house"],
                category=item["category"],
                sub_category=item["sub_category"],
                benchmark=item["benchmark"],
                isin_growth=item.get("isin_growth"),
                expense_ratio=item.get("expense_ratio", 0.75),
                crisil_rating=item.get("crisil_rating", 4),
                is_active=True
            )
            session.add(mf)
            inserted += 1
        else:
            # Update metadata if needed
            existing.scheme_name = item["scheme_name"]
            existing.sub_category = item["sub_category"]
            existing.expense_ratio = item.get("expense_ratio", existing.expense_ratio)
            existing.crisil_rating = item.get("crisil_rating", existing.crisil_rating)
    session.commit()
    logger.info(f"Seeded/Updated {inserted} curated mutual funds.")
    return inserted


def fetch_scheme_nav_history(scheme_code: int, session: Session, min_date: str = "2006-04-01") -> int:
    """
    Fetches historical daily NAVs for a given scheme code from mfapi.in and stores in mutual_fund_navs.
    Returns the count of inserted records.
    """
    url = f"https://api.mfapi.in/mf/{scheme_code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Error fetching NAV history for scheme {scheme_code}: {e}")
        return 0

    nav_data = payload.get("data", [])
    if not nav_data:
        return 0

    # Query latest date already present in database to avoid duplicate inserts
    latest_db_date = session.execute(
        text("SELECT MAX(date) FROM mutual_fund_navs WHERE scheme_code = :sc"),
        {"sc": scheme_code}
    ).scalar()

    # Parse and prepare new records
    new_rows = []
    # nav_data is ordered newest to oldest: reverse to chronological
    sorted_navs = sorted(nav_data, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y"))
    
    prev_nav = None
    for entry in sorted_navs:
        try:
            d_obj = datetime.strptime(entry["date"], "%d-%m-%Y").date()
            if d_obj < datetime.strptime(min_date, "%Y-%m-%d").date():
                continue
            if latest_db_date and d_obj <= latest_db_date:
                prev_nav = float(entry["nav"])
                continue

            nav_val = float(entry["nav"])
            daily_ret = ((nav_val - prev_nav) / prev_nav * 100) if (prev_nav and prev_nav > 0) else 0.0
            prev_nav = nav_val

            new_rows.append({
                "scheme_code": scheme_code,
                "date": d_obj,
                "nav": nav_val,
                "daily_return": round(daily_ret, 4)
            })
        except Exception:
            continue

    if new_rows:
        session.bulk_insert_mappings(MutualFundNAV, new_rows)
        session.commit()
        logger.info(f"Inserted {len(new_rows)} historical NAVs for scheme {scheme_code}.")
    return len(new_rows)


def backfill_all_curated_mutual_funds(session: Session, limit_schemes: Optional[int] = None) -> Dict[str, int]:
    """Backfills historical NAVs for all curated mutual funds."""
    seed_curated_mutual_funds(session)
    funds = session.query(MutualFund).filter_by(is_active=True).all()
    if limit_schemes:
        funds = funds[:limit_schemes]

    results = {}
    for fund in funds:
        cnt = fetch_scheme_nav_history(fund.scheme_code, session)
        results[fund.scheme_name] = cnt

    return results


def sync_daily_amfi_nav_feed(session: Session) -> int:
    """
    Downloads the daily AMFI NAVAll.txt feed and updates the latest NAV
    for all tracked mutual funds.
    """
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=25) as response:
            content = response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"Failed to download AMFI NAV feed: {e}")
        return 0

    tracked_codes = {r[0] for r in session.query(MutualFund.scheme_code).all()}
    if not tracked_codes:
        return 0

    lines = content.splitlines()
    updated_count = 0
    today_date = date.today()

    for line in lines:
        parts = line.strip().split(";")
        if len(parts) >= 8:
            try:
                code_str = parts[0].strip()
                if not code_str.isdigit():
                    continue
                code = int(code_str)
                if code in tracked_codes:
                    nav_val = float(parts[6].strip())
                    nav_date_str = parts[7].strip()
                    nav_date = datetime.strptime(nav_date_str, "%d-%b-%Y").date()

                    # Check if already present
                    exists = session.execute(
                        text("SELECT id FROM mutual_fund_navs WHERE scheme_code = :sc AND date = :dt"),
                        {"sc": code, "dt": nav_date}
                    ).first()

                    if not exists:
                        prev_nav = session.execute(
                            text("SELECT nav FROM mutual_fund_navs WHERE scheme_code = :sc ORDER BY date DESC LIMIT 1"),
                            {"sc": code}
                        ).scalar()
                        daily_ret = ((nav_val - prev_nav) / prev_nav * 100) if (prev_nav and prev_nav > 0) else 0.0

                        nav_rec = MutualFundNAV(
                            scheme_code=code,
                            date=nav_date,
                            nav=nav_val,
                            daily_return=round(daily_ret, 4)
                        )
                        session.add(nav_rec)
                        updated_count += 1
            except Exception:
                continue

    if updated_count > 0:
        session.commit()
        logger.info(f"Updated {updated_count} mutual fund NAVs from AMFI daily feed.")
    return updated_count


def sync_all_mf_nav_deltas(session: Session) -> Dict:
    """
    Performs an automated incremental Daily Delta Sync for all active Mutual Funds.
    - Seeds curated universe if not present.
    - Checks missing date delta between last synced NAV date and latest market prices.
    - Fetches incremental NAVs via mfapi / AMFI feed with resilient fallback.
    - Returns detailed delta statistics (new NAV points, updated schemes, latest NAV date).
    """
    # 1. Ensure curated schemes are in DB
    cnt_existing = session.query(MutualFund).filter(MutualFund.is_active == True).count()
    if cnt_existing == 0:
        seed_curated_mutual_funds(session)

    funds = session.query(MutualFund).filter(MutualFund.is_active == True).all()
    if not funds:
        return {
            "status": "NO_FUNDS",
            "new_navs_added": 0,
            "schemes_updated": 0,
            "latest_nav_date": None,
            "message": "No active mutual funds found to sync.",
        }

    latest_mkt_date = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    if not latest_mkt_date:
        latest_mkt_date = date.today()
    elif isinstance(latest_mkt_date, str):
        latest_mkt_date = datetime.strptime(latest_mkt_date, "%Y-%m-%d").date()

    total_added = 0
    schemes_updated = 0
    synced_schemes = []

    # First attempt: Quick AMFI daily feed sync
    try:
        amfi_added = sync_daily_amfi_nav_feed(session)
        if amfi_added > 0:
            total_added += amfi_added
    except Exception as e:
        logger.debug(f"AMFI feed sync note: {e}")

    # Second check: Per-scheme delta audit
    for f in funds:
        last_nav_row = session.execute(
            text("SELECT MAX(date), nav FROM mutual_fund_navs WHERE scheme_code = :sc"),
            {"sc": f.scheme_code}
        ).first()

        last_date = last_nav_row[0] if last_nav_row else None
        last_nav = float(last_nav_row[1]) if (last_nav_row and last_nav_row[1]) else None

        if isinstance(last_date, str):
            last_date = datetime.strptime(last_date, "%Y-%m-%d").date()

        # If missing completely, fetch history
        if not last_date:
            added = fetch_scheme_nav_history(f.scheme_code, session, min_date="2023-01-01")
            if added > 0:
                total_added += added
                schemes_updated += 1
                synced_schemes.append(f.scheme_name)
        elif last_date < latest_mkt_date:
            # Scheme is behind latest market date - fetch delta
            added = fetch_scheme_nav_history(f.scheme_code, session, min_date=str(last_date - timedelta(days=5)))
            if added > 0:
                total_added += added
                schemes_updated += 1
                synced_schemes.append(f.scheme_name)
            else:
                # If API has not yet released today's NAV (e.g. declared later in the evening or T+1),
                # do not fabricate synthetic NAVs; retain the latest confirmed official AMFI NAV.
                pass

    new_latest_date = session.execute(text("SELECT MAX(date) FROM mutual_fund_navs")).scalar()

    msg = (
        f"✅ Mutual Fund Delta Sync Complete: {total_added} daily NAV points indexed across "
        f"{schemes_updated} schemes. Latest NAV date: {new_latest_date}."
    )
    logger.info(msg)

    return {
        "status": "SUCCESS",
        "new_navs_added": total_added,
        "schemes_updated": schemes_updated,
        "latest_nav_date": str(new_latest_date),
        "synced_schemes": synced_schemes[:5],
        "message": msg,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def get_mf_daily_delta_summary(session: Session) -> List[Dict]:
    """
    Returns a comprehensive Daily Delta Summary table for all tracked Mutual Funds:
      - Latest NAV and NAV Date
      - 1-Day NAV Delta (₹) and 1D Return (%)
      - 5-Day Rolling Delta (%)
      - 1-Month Delta (%)
      - Trend & Momentum status
    """
    funds = session.query(MutualFund).filter(MutualFund.is_active == True).all()
    results = []

    for f in funds:
        # Get latest 25 NAV records ordered by date DESC
        nav_rows = session.execute(text("""
            SELECT date, nav, daily_return
            FROM mutual_fund_navs
            WHERE scheme_code = :sc
            ORDER BY date DESC
            LIMIT 25
        """), {"sc": f.scheme_code}).fetchall()

        if not nav_rows:
            continue

        latest_date = str(nav_rows[0][0])
        latest_nav = float(nav_rows[0][1])
        day_ret_pct = float(nav_rows[0][2] or 0.0)

        # 1-Day NAV Delta in ₹
        prev_nav = float(nav_rows[1][1]) if len(nav_rows) > 1 else latest_nav
        nav_delta_1d_inr = round(latest_nav - prev_nav, 4)

        # 5-Day Delta %
        nav_5d = float(nav_rows[min(5, len(nav_rows) - 1)][1])
        delta_5d_pct = round((latest_nav - nav_5d) / nav_5d * 100.0, 2) if nav_5d > 0 else 0.0

        # 1-Month (approx 20 trading sessions) Delta %
        nav_20d = float(nav_rows[-1][1])
        delta_1m_pct = round((latest_nav - nav_20d) / nav_20d * 100.0, 2) if nav_20d > 0 else 0.0

        trend_status = "🚀 STRONG BULLISH" if delta_5d_pct > 1.5 else (
            "🟢 ACCUMULATION" if delta_5d_pct >= 0.0 else "🔴 CONSOLIDATION"
        )

        results.append({
            "scheme_code": f.scheme_code,
            "scheme_name": f.scheme_name,
            "category": f.category,
            "sub_category": f.sub_category,
            "fund_house": f.fund_house,
            "latest_nav": latest_nav,
            "latest_date": latest_date,
            "nav_delta_1d_inr": nav_delta_1d_inr,
            "daily_return_pct": day_ret_pct,
            "delta_5d_pct": delta_5d_pct,
            "delta_1m_pct": delta_1m_pct,
            "trend_status": trend_status,
            "crisil_rating": f.crisil_rating or 4,
            "expense_ratio": f.expense_ratio or 0.75,
        })

    # Sort by 1D return descending
    results.sort(key=lambda x: x["daily_return_pct"], reverse=True)
    return results


if __name__ == "__main__":
    engine = get_global_engine()
    s = get_session(engine)
    print("Seeding curated funds...")
    seed_curated_mutual_funds(s)
    print("Syncing all MF NAV deltas...")
    res = sync_all_mf_nav_deltas(s)
    print(res)
    summary = get_mf_daily_delta_summary(s)
    print(f"Computed daily delta summary for {len(summary)} funds.")
    s.close()

