import streamlit as st
import requests

st.set_page_config(page_title="Live Gold Rate Calculator (India)", page_icon="🏅", layout="centered")

def fetch_live_data():
    try:
        xau_data = requests.get("https://api.metals.live/v1/spot").json()[0]
        xau_usd = xau_data.get("gold", 0)
        usd_inr = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=INR").json()["rates"]["INR"]
        return xau_usd, usd_inr
    except Exception:
        st.warning("⚠️ Could not fetch live data. Please enter values manually.")
        return None, None

def gold_rate_from_xauusd(xau_usd, usd_inr, duty_gst_rate):
    usd_per_gram = xau_usd / 31.1035
    inr_per_gram_24k = usd_per_gram * usd_inr
    inr_per_gram_22k = inr_per_gram_24k * 0.9167
    retail_22k = inr_per_gram_22k * (1 + duty_gst_rate / 100)

    return {
        "24K per gram (₹)": round(inr_per_gram_24k, 2),
        "24K per 10g (₹)": round(inr_per_gram_24k * 10, 2),
        "22K per gram (₹)": round(retail_22k, 2),
        "22K per 10g (₹)": round(retail_22k * 10, 2),
    }

st.title("🏅 Live Gold Rate Calculator (India)")

if st.button("Fetch Live Prices"):
    xau_usd, usd_inr = fetch_live_data()
    if xau_usd and usd_inr:
        st.success(f"Live XAU/USD: {xau_usd} | USD/INR: {usd_inr}")
else:
    xau_usd = st.number_input("Enter XAU/USD (Gold price per ounce in USD):", value=4013.0)
    usd_inr = st.number_input("Enter USD/INR exchange rate:", value=88.3)

duty_gst_rate = st.number_input("Enter import duty + GST rate (%) (default 18):", value=18.0)

if st.button("Calculate Gold Rate"):
    rates = gold_rate_from_xauusd(xau_usd, usd_inr, duty_gst_rate)
    st.subheader("Results:")
    st.write(f"**24K per gram:** ₹{rates['24K per gram (₹)']}")
    st.write(f"**24K per 10g:** ₹{rates['24K per 10g (₹)']}")
    st.write(f"**22K per gram (with duty + GST):** ₹{rates['22K per gram (₹)']}")
    st.write(f"**22K per 10g (with duty + GST):** ₹{rates['22K per 10g (₹)']}")

st.caption("💡 Data source: metals.live (XAU/USD) and exchangerate.host (USD/INR). Prices are indicative — retail rates vary by city.")
