# app.py
import streamlit as st
import requests
from datetime import datetime
from math import isfinite

GRAMS_PER_TROY_OUNCE = 31.1034768

st.set_page_config(page_title="Gold Rate Calculator — Live", layout="centered")

st.title("Gold Rate Calculator — Live (server side)")
st.write("Fetches XAU (USD/oz) and converts to INR per 10g. Tries Investing.com API first, falls back to Yahoo Finance.")

# Controls
col1, col2 = st.columns([1, 1])
with col1:
    fetch_now = st.button("Fetch now")
with col2:
    clear_cache = st.button("Clear cache")

# User inputs for taxes and rounding (change them to match MCX)
st.sidebar.header("Tax & rounding settings")
import_duty_pct = st.sidebar.number_input("Import duty (%)", value=10.0, min_value=0.0, step=0.1)
gst_pct = st.sidebar.number_input("GST (%)", value=3.0, min_value=0.0, step=0.1)
round_to = st.sidebar.number_input("Round to (₹)", value=0.1, step=0.1)

# simple server-side cache using st.session_state
if "cached" not in st.session_state:
    st.session_state.cached = {}

def clear_cache_fn():
    st.session_state.cached = {}
    st.success("Cache cleared.")

if clear_cache:
    clear_cache_fn()

def fetch_investing_xau():
    """Try Investing.com hidden-ish API endpoint for XAU/USD; may return 403."""
    url = "https://api.investing.com/api/financialdata/v1/indices/XAU_USD/historical/chart"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://in.investing.com",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # try a few common shapes for the price
        # 1) direct last field
        if isinstance(data, dict):
            if "last" in data:
                return float(data["last"]), "Investing.com API"
            # maybe series of points
            if "series" in data and isinstance(data["series"], list) and len(data["series"])>0:
                # take last point value if available
                last_point = data["series"][-1]
                if isinstance(last_point, dict) and "value" in last_point:
                    return float(last_point["value"]), "Investing.com API"
            # other possibilities: data.get("data")[...]
            if "data" in data and isinstance(data["data"], list) and len(data["data"])>0:
                # pick last element if it's a number or dict
                last = data["data"][-1]
                if isinstance(last, (int, float)):
                    return float(last), "Investing.com API"
                if isinstance(last, dict) and "close" in last:
                    return float(last["close"]), "Investing.com API"
        # fallback: try to parse 'price' key
        if isinstance(data, dict) and "price" in data:
            return float(data["price"]), "Investing.com API"
    except requests.exceptions.HTTPError as e:
        # will be caught by caller
        raise
    except Exception:
        pass
    raise RuntimeError("Investing.com endpoint didn't return price in expected format.")

def fetch_yahoo_xau():
    """Fallback: Yahoo Finance quote endpoint for XAUUSD=X"""
    url = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=XAUUSD=X"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        j = resp.json()
        q = j.get("quoteResponse", {}).get("result", [])
        if q and isinstance(q, list):
            price = q[0].get("regularMarketPrice") or q[0].get("bid") or q[0].get("ask")
            if price is not None:
                return float(price), "Yahoo Finance"
    except Exception:
        pass
    raise RuntimeError("Yahoo Finance fallback failed.")

def fetch_usd_inr():
    """Get USD to INR rate using exchangerate.host (free)"""
    url = "https://api.exchangerate.host/latest"
    params = {"base": "USD", "symbols": "INR"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        j = resp.json()
        rate = j.get("rates", {}).get("INR")
        if rate:
            return float(rate)
    except Exception:
        pass
    # last ditch: approximate using a fixed value (only if absolutely necessary).
    raise RuntimeError("Failed to fetch USD→INR from exchangerate.host. Check network.")

def convert_and_display(xau_usd, usd_inr):
    # xau_usd is USD per troy ounce
    usd_per_gram = xau_usd / GRAMS_PER_TROY_OUNCE
    usd_per_10g = usd_per_gram * 10
    inr_per_10g = usd_per_10g * usd_inr

    rates = {}
    rates["24K (pure) per 10g"] = inr_per_10g
    rates["22K per 10g (22/24)"] = inr_per_10g * (22/24)
    rates["18K per 10g (18/24)"] = inr_per_10g * (18/24)

    taxed = {}
    for k, v in rates.items():
        after_import = v * (1 + import_duty_pct/100.0)
        after_gst = after_import * (1 + gst_pct/100.0)
        taxed[k] = {"pre_tax": v, "after_import": after_import, "after_gst": after_gst}

    # rounding helper
    def r(x):
        if not isfinite(x):
            return x
        if round_to <= 0:
            return x
        return round(round(x/round_to)*round_to, 2)

    st.subheader("Computed rates (per 10 g)")
    for k, v in taxed.items():
        st.write(f"**{k}**")
        st.write(f"- Pre-tax : ₹ {r(v['pre_tax']):,}")
        st.write(f"- After import duty ({import_duty_pct}%) : ₹ {r(v['after_import']):,}")
        st.write(f"- After GST ({gst_pct}%) : ₹ {r(v['after_gst']):,}")
        st.write("")

def main():
    show_section = st.empty()
    if not fetch_now and st.session_state.cached.get("last_fetched") is None:
        st.info("Press *Fetch now* to retrieve live XAU/USD and compute rates.")
        return

    # if cached and not forcing fetch, use cache
    if not fetch_now and st.session_state.cached.get("last_fetched"):
        cached = st.session_state.cached
        st.success("Used cached rates (press Fetch now to refresh).")
        st.write(f"Source: **{cached.get('source')}**")
        st.write(f"XAU (USD/oz): {cached.get('xau_usd')}")
        st.write(f"USD→INR: {cached.get('usd_inr')}")
        st.write(f"Last update: {cached.get('last_fetched')}")
        convert_and_display(cached.get('xau_usd'), cached.get('usd_inr'))
        return

    # Fresh fetch
    error_msgs = []
    xau_usd = None
    source = None
    try:
        try:
            xau_usd, source = fetch_investing_xau()
        except requests.exceptions.HTTPError as he:
            # likely 403
            error_msgs.append(f"Investing.com HTTP error: {he}")
            raise
        except Exception as e:
            error_msgs.append(f"Investing.com fetch failed: {e}")

        if xau_usd is None:
            # try fallback
            try:
                xau_usd, source = fetch_yahoo_xau()
            except Exception as e:
                error_msgs.append(f"Yahoo fallback failed: {e}")
                raise RuntimeError("All price fetch attempts failed.")

        usd_inr = fetch_usd_inr()

        # cache it
        st.session_state.cached = {
            "xau_usd": xau_usd,
            "usd_inr": usd_inr,
            "source": source,
            "last_fetched": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        }

        st.success("Fetched live prices.")
        st.write(f"Source: **{source}**")
        st.write(f"XAU (USD per troy oz): {xau_usd}")
        st.write(f"USD → INR : {usd_inr}")
        st.write(f"Last update: {st.session_state.cached['last_fetched']}")

        convert_and_display(xau_usd, usd_inr)

    except requests.exceptions.HTTPError as he:
        st.error(f"HTTP error while fetching Investing.com: {he}")
        st.error("Investing.com likely returned 403 Forbidden. Try the fallback data source or use a different method (Selenium / proxy / official API key).")
        if error_msgs:
            st.write("Details:")
            for e in error_msgs:
                st.write("-", e)
    except Exception as e:
        st.error(f"Error: {e}")
        if error_msgs:
            st.write("Details:")
            for em in error_msgs:
                st.write("-", em)

if __name__ == "__main__":
    main()
