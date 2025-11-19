from flask import Flask, jsonify, render_template, request
import requests, re
from functools import lru_cache
import time

app = Flask(__name__)
HEADERS = {"User-Agent":"goldcalc/1.0"}

XAU_URL = "https://in.investing.com/currencies/xau-usd"
USD_URL = "https://in.investing.com/currencies/usd-inr"

def extract_price(html: str):
    m = re.search(r'data-last=["\']?([0-9,]+\.\d+)["\']?', html)
    if m:
        return float(m.group(1).replace(",",""))
    m = re.search(r'id=["\']last_last["\'][^>]*>([0-9,]+\.\d+)<', html)
    if m:
        return float(m.group(1).replace(",",""))
    m = re.search(r'([0-9]{1,3}(?:,[0-9]{3})*\.\d{1,6})', html)
    if m:
        return float(m.group(1).replace(",",""))
    return None

@lru_cache(maxsize=64)
def cached_fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text

@app.route("/api/rate")
def api_rate():
    # query params to override defaults
    import_duty = float(request.args.get("import_duty", 6.0))
    gst = float(request.args.get("gst", 3.0))
    mcx_adjust = float(request.args.get("mcx_adjust", 0.0))

    # fetch (cached)
    xau_html = cached_fetch(XAU_URL)
    usd_html = cached_fetch(USD_URL)

    xau = extract_price(xau_html)
    usd = extract_price(usd_html)
    if xau is None or usd is None:
        return jsonify({"error":"failed to parse source pages"}), 500

    ounce_to_gram = 31.1034768
    price_per_gram_usd = xau / ounce_to_gram
    price_per_gram_inr = price_per_gram_usd * usd
    per_10g = price_per_gram_inr * 10.0

    customs = per_10g * (import_duty/100.0)
    assessable = per_10g + customs
    gst_amount = assessable * (gst/100.0)
    final_imported_24 = per_10g + customs + gst_amount

    def round2(x): return round(x,2)
    result = {
        "source": {"xau_usd": xau, "usd_inr": usd},
        "raw": {
            "24k_per_10g": round2(per_10g),
            "22k_per_10g": round2(per_10g * 22/24),
            "18k_per_10g": round2(per_10g * 18/24),
        },
        "imported": {
            "24k_per_10g": round2(final_imported_24),
            "22k_per_10g": round2(final_imported_24 * 22/24),
            "18k_per_10g": round2(final_imported_24 * 18/24)
        },
        "mcx_adjust": mcx_adjust,
        "mcx": {
            "24k": round2(final_imported_24 + mcx_adjust),
            "22k": round2(final_imported_24 * 22/24 + mcx_adjust),
            "18k": round2(final_imported_24 * 18/24 + mcx_adjust)
        },
        "meta": {"import_duty_pct": import_duty, "gst_pct": gst, "timestamp": int(time.time())}
    }
    return jsonify(result)

@app.route("/")
def index():
    return render_template("index.html")
