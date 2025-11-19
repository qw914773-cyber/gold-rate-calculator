import streamlit as st
import requests
from datetime import datetime
from math import isfinite

GRAMS_PER_TROY_OUNCE = 31.1034768

st.set_page_config(page_title="Gold Rate Calculator — Live", layout="centered")

st.title("Gold Rate Calculator — Live")
st.write("Live XAU/USD → INR per 10g gold calculator (24K, 22K, 18K) using Yahoo Finance API — No 403 errors.")

# Sidebar settings
st.sidebar.header("Tax & Rounding Settings")
import_duty_pct = st.sidebar.number_input("Import Duty (%)", value=10.75, step=0.1)
gst_pct = st.sidebar.number_input("GST (%)", value=3.0, step=0.1)
round_to = st.sidebar.number_input("Round to (₹)", value=1.0, step=0.1)

fetch_btn = st.button("Fetch Live Rate")

def fetch_xau_yahoo():
    url = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=XAUUSD=X"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    price = data["quoteResponse"]["result"][0]["regularMarketPrice"]
    return float(price)

def fetch_usd_inr():
    url = "https://api.exchangerate.host/latest?base=USD&symbols=INR"
    resp = requests.get(url)
    resp.raise_for_status()
    return float(resp.json()["rates"]["INR"])

def round_value(x):
    if round_to <= 0:
        return x
    return round(round(x / round_to) * round_to, 2)

def calculate_rates(xau_usd, usd_inr):
    usd_per_gram = xau_usd / GRAMS_PER_TROY_OUNCE
    usd_per_10g = usd_per_gram * 10
    inr_per_10g = usd_per_10g * usd_inr

    rates = {
        "24K": inr_per_10g,
        "22K": inr_per_10g * (22 / 24),
        "18K": inr_per_10g * (18 / 24)
    }

    final_rates = {}

    for purity, base_value in rates.items():
        after_import = base_value * (1 + import_duty_pct / 100)
        after_gst = after_import * (1 + gst_pct / 100)

        final_rates[purity] = {
            "Base (INR)": round_value(base_value),
            "After Import Duty": round_value(after_import),
            "Final (After GST)": round_value(after_gst)
        }

    return final_rates

if fetch_btn:
    try:
        xau_usd = fetch_xau_yahoo()
        usd_inr = fetch_usd_inr()
        st.success("Live rates fetched successfully!")

        st.write(f"**XAU/USD:** {xau_usd}")
        st.write(f"**USD → INR:** {usd_inr}")

        results = calculate_rates(xau_usd, usd_inr)

        st.subheader("Final Gold Rates Per 10g")

        for purity, values in results.items():
            st.write(f"### {purity}")
            st.write(f"- Base Rate: ₹ {values['Base (INR)']:,}")
            st.write(f"- After Import Duty: ₹ {values['After Import Duty']:,}")
            st.write(f"- Final Rate (After GST): ₹ {values['Final (After GST)']:,}")
            st.write("---")

    except Exception as e:
        st.error(f"Error: {e}")
