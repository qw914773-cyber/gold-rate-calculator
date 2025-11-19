# app.py (replace existing fetch logic with this file if you want a full working example)
import streamlit as st
import requests
from datetime import datetime, timedelta
from math import isfinite
import time

GRAMS_PER_TROY_OUNCE = 31.1034768

st.set_page_config(page_title="Gold Rate Calculator — Live", layout="centered")
st.title("Gold Rate Calculator — Live (Yahoo w/ caching, retry, fallback)")

# Sidebar: tax, rounding and advanced
st.sidebar.header("Settings")
import_duty_pct = st.sidebar.number_input("Import Duty (%)", value=10.75, step=0.1)
gst_pct = st.sidebar.number_input("GST (%)", value=3.0, step=0.1)
round_to = st.sidebar.number_input("Round to (₹)", value=1.0, step=0.1)
cache_ttl_seconds = st.sidebar.number_input("Cache TTL (sec)", value=120, min_value=10, step=10)
metals_api_key = st.sidebar.text_input("Metals-API key (optional fallback)")

# Button and cooldown display
fetch_btn = st.button("Fetch Live Rate")

if "last_fetch_time" not in st.session_state:
    st.session_state.last_fetch_time = None
if "cooldown_seconds" not in st.session_state:
    st.session_state.cooldown_seconds = 5  # UI-level quick protection

def can_fetch():
    """Return (allowed: bool, wait_seconds: int)."""
    if st.session_state.last_fetch_time is None:
        return True, 0
    elapsed = (datetime.utcnow() - st.session_state.last_fetch_time).total_seconds()
    if elapsed >= st.session_state.cooldown_seconds:
        return True, 0
    return False, int(st.session_state.cooldown_seconds - elapsed)

# Simple caching (in-memory)
if "cached_prices" not in st.session_state:
    st.session_state.cached_prices = {}

def cache_set(key, value):
    st.session_state.cached_prices[key] = {"value": value, "fetched_at": datetime.utcnow()}

def cache_get(key):
    rec = st.session_state.cached_prices.get(key)
    if not rec:
        return None
    age = (datetime.utcnow() - rec["fetched_at"]).total_seconds()
    if age > cache_ttl_seconds:
        # expired
        st.session_state.cached_prices.pop(key, None)
        return None
    return rec["value"]

# Helper for rounding
def round_value(x):
    if round_to <= 0:
        return round(x, 2)
    return round(round(x / round_to) * round_to, 2)

# Fetch with retries + backoff + 429 handling
def http_get_with_retries(url, params=None, headers=None, max_attempts=3):
    attempt = 0
    backoff = 1.0
    while attempt < max_attempts:
        attempt += 1
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 429:
                # Respect Retry-After header if present
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = int(retry_after)
                    except ValueError:
                        # Could be a date string; fallback to small wait
                        wait = backoff
                else:
                    wait = backoff
                # Inform the caller via exception, include wait seconds
                raise RuntimeError(f"429: Retry after {wait} seconds")
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            # Last attempt -> re-raise
            if attempt >= max_attempts:
                raise
            # Sleep then retry
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError("Failed after retries")

# Primary fetch: Yahoo (cached)
def fetch_xau_usd_cached():
    cached = cache_get("xau_usd")
    if cached is not None:
        return cached, "Yahoo (cached)"
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    params = {"symbols": "XAUUSD=X"}
    try:
        resp = http_get_with_retries(url, params=params, max_attempts=3)
        j = resp.json()
        price = j["quoteResponse"]["result"][0]["regularMarketPrice"]
        cache_set("xau_usd", float(price))
        return float(price), "Yahoo"
    except Exception as e:
        # Propagate message to caller
        raise

# USD→INR fetch (cached)
def fetch_usd_inr_cached():
    cached = cache_get("usd_inr")
    if cached is not None:
        return cached, "exchangerate.host (cached)"
    url = "https://api.exchangerate.host/latest"
    params = {"base": "USD", "symbols": "INR"}
    try:
        resp = http_get_with_retries(url, params=params, max_attempts=3)
        rate = resp.json()["rates"]["INR"]
        cache_set("usd_inr", float(rate))
        return float(rate), "exchangerate.host"
    except Exception as e:
        raise

# Optional fallback: Metals-API (if user provided key)
def fetch_xau_metalsapi(key):
    # metals-api.com example endpoint (user must provide key). Adjust path if provider differs.
    url = "https://metals-api.com/api/latest"
    params = {"access_key": key, "base": "USD", "symbols": "XAU"}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    j = resp.json()
    # Different APIs return different shapes — try to be flexible
    # metals-api returns rates like {"rates": {"XAU": 0.00056}} meaning XAU per USD — convert if necessary
    rates = j.get("rates")
    if rates and "XAU" in rates:
        # if rate is XAU per USD, then USD per XAU = 1/rate
        r = rates["XAU"]
        if r == 0:
            raise RuntimeError("Metals API returned XAU=0")
        usd_per_xau = 1.0 / float(r)
        cache_set("xau_usd", usd_per_xau)
        return usd_per_xau, "Metals-API"
    raise RuntimeError("Metals API response missing XAU")

# Conversion & display
def convert_and_display(xau_usd, usd_inr, source_xau, source_fx):
    usd_per_gram = xau_usd / GRAMS_PER_TROY_OUNCE
    usd_per_10g = usd_per_gram * 10
    inr_per_10g = usd_per_10g * usd_inr

    st.write(f"Source XAU: **{source_xau}** — XAU/USD: {xau_usd}")
    st.write(f"Source FX: **{source_fx}** — USD→INR: {usd_inr}")

    rates = {
        "24K": inr_per_10g,
        "22K": inr_per_10g * (22 / 24),
        "18K": inr_per_10g * (18 / 24),
    }

    st.subheader("Final rates per 10 g")
    for purity, base in rates.items():
        after_imp = base * (1 + import_duty_pct / 100)
        after_gst = after_imp * (1 + gst_pct / 100)
        st.write(f"**{purity}**")
        st.write(f"- Base: ₹ {round_value(base):,}")
        st.write(f"- After import duty: ₹ {round_value(after_imp):,}")
        st.write(f"- Final (after GST): ₹ {round_value(after_gst):,}")
        st.write("---")

# Main flow
allowed, wait = can_fetch()
if fetch_btn and not allowed:
    st.warning(f"Please wait {wait} second(s) before fetching again (UI cooldown).")
if fetch_btn and allowed:
    st.session_state.last_fetch_time = datetime.utcnow()
    # Try primary path (Yahoo + exchangerate.host)
    try:
        xau_usd, source_xau = fetch_xau_usd_cached()
        usd_inr, source_fx = fetch_usd_inr_cached()
        st.success("Fetched live rates.")
        convert_and_display(xau_usd, usd_inr, source_xau, source_fx)
    except Exception as e_primary:
        # If primary fails due to 429 or other, inform user and try optional fallback
        err_msg = str(e_primary)
        st.error(f"Primary source error: {err_msg}")
        # If it's a 429 with retry hint, show helpful message
        if "429" in err_msg:
            st.info("The remote service is throttling requests. Please wait a bit or increase Cache TTL in sidebar.")
            # If Retry-After present in exception message we already surfaced it earlier.
        # Try fallback (Metals-API) if key provided
        if metals_api_key:
            try:
                xau_usd, fx = fetch_xau_metalsapi(metals_api_key)
                usd_inr, source_fx = fetch_usd_inr_cached()
                st.success("Fetched using Metals-API fallback.")
                convert_and_display(xau_usd, usd_inr, fx, source_fx)
            except Exception as e_fallback:
                st.error(f"Fallback also failed: {e_fallback}")
                st.write("You can add a valid Metals-API key in the sidebar or increase cache TTL / cooldown to avoid 429s.")
        else:
            st.write("No fallback API key configured. Add a Metals-API key in the sidebar or increase Cache TTL to avoid rate-limits.")
