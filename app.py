# streamlit_app.py
# Streamlit Gold Rate Calculator — server-side fetch from Investing.com
# Run locally: streamlit run streamlit_app.py

import streamlit as st
import requests
import re
import time
from datetime import datetime
from typing import Optional

st.set_page_config(page_title="Gold Rate Calculator (INR)", layout="centered")

HEADERS = {
    "User-Agent": "goldcalc/1.0 (+https://example.com)"
}
DEFAULT_XAU = "https://in.investing.com/currencies/xau-usd"
DEFAULT_USD = "https://in.investing.com/currencies/usd-inr"
OUNCE_TO_GRAM = 31.1034768

st.title("Gold Rate Calculator — Live (server-side)")

st.markdown(
    "This app scrapes **Investing.com** server-side and converts XAU/USD → INR → per 10g, "
    "applies import duty + GST and shows 24K, 22K and 18K rates. Use the controls below to adjust taxes or MCX rounding."
)

with st.sidebar:
    st.header("Settings")
    xau_url = st.text_input("XAU/USD URL", DEFAULT_XAU)
    usd_url = st.text_input("USD/INR URL", DEFAULT_USD)
    import_duty = st.number_input("Import duty (%)", value=6.0, step=0.1, format="%.2f")
    gst_pct = st.number_input("GST / IGST (%)", value=3.0, step=0.1, format="%.2f")
    mcx_adjust = st.number_input("MCX adjustment (₹ per 10g)", value=0.0, step=0.1, format="%.2f")
    cache_seconds = st.number_input("Cache duration (s)", value=30, min_value=5, step=5)
    auto_refresh = st.checkbox("Auto-refresh", value=False)
    refresh_interval = st.number_input("Auto-refresh interval (s)", value=15, min_value=5, step=1)

st.write("**Manual controls:**")
col1, col2 = st.columns([1,1])
with col1:
    if st.button("Fetch now"):
        st.session_state["_force_fetch"] = True
with col2:
    if st.button("Clear cache"):
        st.session_state["_clear_cache"] = True

# --- Helpers ---

def extract_price(html: str) -> Optional[float]:
    """Heuristic HTML extraction for Investing.com price"""
    if not html:
        return None
    # 1) data-last="1234.56"
    m = re.search(r'data-last=["\']?([0-9,]+\.\d+)["\']?', html)
    if m:
        return float(m.group(1).replace(",", ""))
    # 2) id="last_last">1234.56<
    m = re.search(r'id=["\']last_last["\'][^>]*>([0-9,]+\.\d+)<', html)
    if m:
        return float(m.group(1).replace(",", ""))
    # 3) 'instrument-price-last' vicinity
    idx = html.find("instrument-price-last")
    if idx != -1:
        snippet = html[idx: idx + 400]
        m = re.search(r'([0-9]{1,3}(?:,[0-9]{3})*\.\d+)', snippet)
        if m:
            return float(m.group(1).replace(",", ""))
    # 4) fallback: first numeric token like 1,234.56
    m = re.search(r'([0-9]{1,3}(?:,[0-9]{3})*\.\d{1,6})', html)
    if m:
        return float(m.group(1).replace(",", ""))
    return None

@st.cache_data(ttl=30)
def fetch_page(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text

def compute_rates(xau_usd: float, usd_inr: float, import_duty_pct: float, gst_pct: float, mcx_adj: float):
    price_per_gram_usd = xau_usd / OUNCE_TO_GRAM
    price_per_gram_inr = price_per_gram_usd * usd_inr
    per_10g = price_per_gram_inr * 10.0

    customs = per_10g * (import_duty_pct / 100.0)
    assessable = per_10g + customs
    gst_amount = assessable * (gst_pct / 100.0)
    imported_24 = per_10g + customs + gst_amount

    raw24 = per_10g
    raw22 = raw24 * (22.0 / 24.0)
    raw18 = raw24 * (18.0 / 24.0)

    imported22 = imported_24 * (22.0 / 24.0)
    imported18 = imported_24 * (18.0 / 24.0)

    mcx24 = imported_24 + mcx_adj
    mcx22 = imported22 + mcx_adj
    mcx18 = imported18 + mcx_adj

    return {
        "source": {"xau_usd": xau_usd, "usd_inr": usd_inr},
        "raw": {"24k": raw24, "22k": raw22, "18k": raw18},
        "imported": {"24k": imported_24, "22k": imported22, "18k": imported18},
        "mcx": {"24k": mcx24, "22k": mcx22, "18k": mcx18},
    }

# --- Fetching logic with cache/clear support ---
force = st.session_state.get("_force_fetch", False)
clear_cache = st.session_state.pop("_clear_cache", False) if st.session_state.get("_clear_cache") else False
if clear_cache:
    # clear cache by calling st.cache_data.clear()
    try:
        st.cache_data.clear()
        st.success("Cache cleared.")
    except Exception:
        st.warning("Cache clear attempted; if you see stale data, refresh the page.")

# Adjust fetch ttl based on user input (re-decorated cache isn't dynamic; we will re-call fetch_page with a custom wrapper)
# To honor user cache_seconds we will bypass cache if force or if cache_seconds small.
def safe_fetch(url: str, bypass: bool = False):
    # if bypass, call requests directly
    if bypass:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.text
    # else use cached function (ttl defined by decorator default)
    return fetch_page(url)

# Determine when to bypass cache:
bypass_cache = force or cache_seconds <= 0 or st.session_state.get("_force_fetch", False)
# reset force flag
if "_force_fetch" in st.session_state:
    st.session_state["_force_fetch"] = False

# perform fetch
status = st.empty()
try:
    status.info("Fetching prices from Investing.com ...")
    xau_html = safe_fetch(xau_url, bypass=bypass_cache)
    usd_html = safe_fetch(usd_url, bypass=bypass_cache)
    xau = extract_price(xau_html)
    usd = extract_price(usd_html)
    if xau is None or usd is None:
        raise ValueError("Failed to parse source pages. Investing.com markup may have changed or site blocked requests.")
    rates = compute_rates(xau, usd, import_duty, gst_pct, mcx_adjust)
    status.success(f"Fetched at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
except Exception as e:
    status.error(f"Error: {e}")
    st.stop()

# --- Display results ---
st.subheader("Source prices")
st.write(f"XAU/USD (USD/oz): **{rates['source']['xau_usd']:.6f}**")
st.write(f"USD/INR         : **{rates['source']['usd_inr']:.6f}**")

st.subheader("Raw (no tax) per 10g")
st.table({
    "Purity": ["24K", "22K", "18K"],
    "Price (₹ / 10g)": [
        f"{rates['raw']['24k']:.2f}",
        f"{rates['raw']['22k']:.2f}",
        f"{rates['raw']['18k']:.2f}",
    ]
})

st.subheader("After Import Duty + GST (per 10g)")
st.table({
    "Purity": ["24K", "22K", "18K"],
    "Price (₹ / 10g)": [
        f"{rates['imported']['24k']:.2f}",
        f"{rates['imported']['22k']:.2f}",
        f"{rates['imported']['18k']:.2f}",
    ]
})

st.subheader("MCX-adjusted (manual adjust applied)")
st.table({
    "Purity": ["24K", "22K", "18K"],
    "Price (₹ / 10g)": [
        f"{rates['mcx']['24k']:.2f}",
        f"{rates['mcx']['22k']:.2f}",
        f"{rates['mcx']['18k']:.2f}",
    ]
})

st.markdown("---")
st.markdown(
    "Notes:\n"
    "- 1 troy ounce = 31.1034768 g. Purity scaling: 22K = 22/24 of 24K; 18K = 18/24 of 24K.\n"
    "- GST is applied on (price + customs) as used in the calculation.\n"
    "- If the app fails to parse prices, Investing.com may have changed page markup or may be blocking requests. "
    "Try increasing cache time, or use a different source/proxy."
)

if auto_refresh:
    st.experimental_rerun()
