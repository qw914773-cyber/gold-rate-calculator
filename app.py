# app.py
import streamlit as st
import requests, time
from datetime import datetime, timedelta
from math import isfinite

GRAMS_PER_TROY_OUNCE = 31.1034768

st.set_page_config(page_title="Gold Rate Calculator — Live (robust)", layout="centered")
st.title("Gold Rate Calculator — Live (robust)")

# Sidebar settings
st.sidebar.header("Settings & fallback")
import_duty_pct = st.sidebar.number_input("Import Duty (%)", value=10.75, step=0.1)
gst_pct = st.sidebar.number_input("GST (%)", value=3.0, step=0.1)
round_to = st.sidebar.number_input("Round to (₹)", value=1.0, step=0.1)
cache_ttl_seconds = st.sidebar.number_input("Cache TTL (sec)", value=120, min_value=10, step=10)
ui_cooldown = st.sidebar.number_input("UI cooldown (sec)", value=10, min_value=1, step=1)
metals_api_key = st.sidebar.text_input("Metals-API key (optional fallback)")

# Buttons
refresh = st.button("Refresh / Force fetch (respects cooldown)")

# session defaults
if "cache" not in st.session_state:
    st.session_state.cache = {}  # keys: xau_usd, usd_inr, fetched_at, source_xau, source_fx
if "last_user_fetch" not in st.session_state:
    st.session_state.last_user_fetch = None
if "last_retry_after" not in st.session_state:
    st.session_state.last_retry_after = None

# helpers
def cache_set(xau_usd=None, usd_inr=None, source_xau=None, source_fx=None):
    now = datetime.utcnow()
    st.session_state.cache.update({
        "xau_usd": xau_usd,
        "usd_inr": usd_inr,
        "fetched_at": now,
        "source_xau": source_xau,
        "source_fx": source_fx
    })

def cache_get():
    c = st.session_state.cache
    if not c or "fetched_at" not in c:
        return None
    age = (datetime.utcnow() - c["fetched_at"]).total_seconds()
    if age > cache_ttl_seconds:
        return None
    return c

def cache_age_seconds():
    c = st.session_state.cache
    if not c or "fetched_at" not in c:
        return None
    return (datetime.utcnow() - c["fetched_at"]).total_seconds()

def round_value(x):
    if round_to <= 0:
        return round(x, 2)
    return round(round(x / round_to) * round_to, 2)

# http helper with limited retries and 429 handling (does not block UI)
def http_get(url, params=None, headers=None, attempts=3):
    backoff = 1.0
    last_retry_after = None
    for attempt in range(1, attempts+1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=8)
            if resp.status_code == 429:
                # read Retry-After if present
                ra = resp.headers.get("Retry-After")
                try:
                    if ra is not None:
                        last_retry_after = int(float(ra))
                except Exception:
                    # ignore parse errors
                    last_retry_after = None
                raise requests.exceptions.HTTPError(f"429")
            resp.raise_for_status()
            return resp, None
        except requests.exceptions.HTTPError as he:
            if "429" in str(he):
                # bubble up a retry-after hint
                return None, last_retry_after or int(backoff)
            if attempt == attempts:
                raise
        except Exception:
            if attempt == attempts:
                raise
        time.sleep(backoff)
        backoff *= 2
    raise RuntimeError("Unreachable")

# Primary fetchers
def fetch_xau_yahoo():
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    params = {"symbols": "XAUUSD=X"}
    resp, retry_after = http_get(url, params=params, attempts=2)
    if resp is None:
        # return None and retry_after hint
        return None, None, retry_after
    j = resp.json()
    price = j["quoteResponse"]["result"][0]["regularMarketPrice"]
    return float(price), "Yahoo Finance", None

def fetch_usd_inr():
    url = "https://api.exchangerate.host/latest"
    params = {"base": "USD", "symbols": "INR"}
    resp, retry_after = http_get(url, params=params, attempts=2)
    if resp is None:
        return None, None, retry_after
    j = resp.json()
    rate = j["rates"]["INR"]
    return float(rate), "exchangerate.host", None

def fetch_metals_api(key):
    url = "https://metals-api.com/api/latest"
    params = {"access_key": key, "base": "USD", "symbols": "XAU"}
    resp, retry_after = http_get(url, params=params, attempts=2)
    if resp is None:
        return None, None, retry_after
    j = resp.json()
    rates = j.get("rates") or {}
    if "XAU" in rates:
        r = rates["XAU"]
        usd_per_xau = 1.0 / float(r) if float(r) != 0 else None
        return usd_per_xau, "Metals-API", None
    raise RuntimeError("Metals-API returned unexpected shape")

# Main logic: show cached always (if exists)
cached = cache_get()
if cached:
    age = cache_age_seconds()
    st.info(f"Showing cached price (age {int(age)}s). Increase Cache TTL in sidebar to keep it longer.")
    st.write(f"XAU source: **{cached.get('source_xau')}**  |  USD→INR source: **{cached.get('source_fx')}**")
    st.write(f"XAU (USD/oz): {cached.get('xau_usd')}")
    st.write(f"USD → INR: {cached.get('usd_inr')}")
    # show computed rates
    xau_usd = cached.get('xau_usd')
    usd_inr = cached.get('usd_inr')
    usd_per_gram = xau_usd / GRAMS_PER_TROY_OUNCE
    usd_per_10g = usd_per_gram * 10
    inr_per_10g = usd_per_10g * usd_inr
    def show_rates(inr_10g):
        st.subheader("Final Gold Rates per 10g")
        for purity, factor in [("24K", 1.0), ("22K", 22/24), ("18K", 18/24)]:
            base = inr_10g * factor
            after_imp = base * (1 + import_duty_pct/100)
            after_gst = after_imp * (1 + gst_pct/100)
            st.write(f"**{purity}** — Base: ₹ {round_value(base):,}  | After import: ₹ {round_value(after_imp):,}  | Final: ₹ {round_value(after_gst):,}")
    show_rates(inr_per_10g)
else:
    st.warning("No cached rate available yet. Press Refresh to fetch live rate (respecting cooldown).")

# Determine if user can fetch (UI cooldown)
if st.session_state.last_user_fetch is None:
    allowed = True
else:
    elapsed = (datetime.utcnow() - st.session_state.last_user_fetch).total_seconds()
    allowed = elapsed >= ui_cooldown
    if not allowed:
        st.write(f"UI cooldown active — wait {int(ui_cooldown - elapsed)}s before forcing another fetch.")

# If user pressed refresh and allowed, attempt fetch sequence
if refresh:
    if not allowed:
        st.warning("Please wait for cooldown before forcing another fetch.")
    else:
        st.session_state.last_user_fetch = datetime.utcnow()
        # attempt primary
        with st.spinner("Fetching XAU and FX (Yahoo + exchangerate.host)..."):
            try:
                xau_res = fetch_xau_yahoo()
                if xau_res[0] is None:
                    # got a retry-after
                    _, _, retry_after = xau_res
                    st.session_state.last_retry_after = retry_after
                    st.error(f"Primary source error: 429. Retry after {retry_after}s. Using cached if available.")
                else:
                    xau_usd, src_xau, _ = xau_res
                    fx_res = fetch_usd_inr()
                    if fx_res[0] is None:
                        _, _, retry_after = fx_res
                        st.session_state.last_retry_after = retry_after
                        st.error(f"Primary FX source error: 429. Retry after {retry_after}s. Using cached if available.")
                    else:
                        usd_inr, src_fx, _ = fx_res
                        # success — cache and show
                        cache_set(xau_usd=xau_usd, usd_inr=usd_inr, source_xau=src_xau, source_fx=src_fx)
                        st.success("Fetched live prices and updated cache.")
                        st.experimental_rerun()
            except Exception as e:
                st.error(f"Primary fetch failed: {e}")
                # try fallback if key present
                if metals_api_key:
                    with st.spinner("Trying Metals-API fallback..."):
                        try:
                            met = fetch_metals_api(metals_api_key)
                            if met[0] is None:
                                _, _, retry_after = met
                                st.error(f"Fallback 429. Retry after {retry_after}s")
                            else:
                                xau_usd, src = met[0], met[1]
                                fx_res = fetch_usd_inr()
                                if fx_res[0] is None:
                                    st.error("FX fetch failed when fallback used.")
                                else:
                                    usd_inr, src_fx, _ = fx_res
                                    cache_set(xau_usd=xau_usd, usd_inr=usd_inr, source_xau=src, source_fx=src_fx)
                                    st.success("Fallback succeeded and cache updated.")
                                    st.experimental_rerun()
                        except Exception as ef:
                            st.error(f"Fallback attempt failed: {ef}")
                else:
                    st.info("No Metals-API key configured. Add one in the sidebar to enable a paid fallback.")

# show helpful tips
st.markdown("---")
st.subheader("Why you're seeing 429 / how to stop it")
st.write(
    "- 429 = remote service (Yahoo) is rate-limiting the IP used by Streamlit Cloud.\n"
    "- Increase **Cache TTL** (sidebar) to 60–300s to avoid frequent hits.\n"
    "- Don't press Refresh repeatedly — use the cache and the cooldown.\n"
    "- For production, use a paid provider (Metals-API / GoldAPI) behind an API key or a backend with pooled requests."
)
