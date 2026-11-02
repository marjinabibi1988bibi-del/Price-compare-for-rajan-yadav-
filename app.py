"""
Price Compare backend (BuyHatke-style).

Flow:
1. User pastes a product link.
2. We open that page and extract the product title (JSON-LD / og:title / <title> / URL slug).
3. We search that title on Google Shopping (India) via SerpAPI, which returns prices
   from many stores (Amazon, Flipkart, Croma, Reliance Digital, Tata CLiQ ...) in one call.
4. We return the results sorted by price, cheapest first.

Env vars:
  SERPAPI_KEY      (required)  https://serpapi.com  (free plan: 100 searches/month)
  SCRAPERAPI_KEY   (optional)  helps when Amazon/Flipkart block your server IP
"""
import json
import os
import re
import time
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")
CACHE_TTL = 30 * 60  # seconds
_cache = {}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


def cache_get(key):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    return None


def cache_set(key, value):
    _cache[key] = (time.time(), value)


def fetch_page(url):
    if SCRAPERAPI_KEY:
        return requests.get(
            "https://api.scraperapi.com/",
            params={"api_key": SCRAPERAPI_KEY, "url": url, "country_code": "in"},
            timeout=60,
        )
    return requests.get(url, headers=HEADERS, timeout=15)


def clean_title(t):
    t = re.sub(r"\s+", " ", t or "").strip()
    # remove store suffixes like ": Amazon.in: Electronics" or "- Buy ... Online"
    t = re.split(r"\s*[:|]\s*Amazon\.in|\s*\|\s*Flipkart|\s+-\s+Buy\b|\s+Online\b", t)[0]
    t = re.sub(r"^(Buy|Amazon\.in\s*:)\s+", "", t, flags=re.I)
    return t.strip(" -|:")[:140]


def title_from_url(url):
    segs = [s for s in urlparse(url).path.split("/") if s]
    best = max((s for s in segs if "-" in s), key=len, default=(segs[0] if segs else ""))
    best = unquote(best)
    best = re.sub(r"[-_+]+", " ", best)
    best = re.sub(r"\.(html?|php)$", "", best, flags=re.I)
    return " ".join(best.split()[:12])


def extract_from_jsonld(soup):
    """Return (name, price) from schema.org Product JSON-LD if present."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and "@graph" in it:
                items.extend(it["@graph"])
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                offers = it.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = None
                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice")
                try:
                    price = float(str(price).replace(",", "")) if price else None
                except ValueError:
                    price = None
                return it.get("name"), price
    return None, None


def extract_product(url):
    """Best-effort: get product title (+ price on the pasted page)."""
    title, price = None, None
    try:
        r = fetch_page(url)
        if r.ok:
            soup = BeautifulSoup(r.text, "html.parser")
            title, price = extract_from_jsonld(soup)
            if not title:
                el = soup.find(id="productTitle")  # Amazon
                if el:
                    title = el.get_text()
            if not title:
                og = soup.find("meta", property="og:title")
                if og and og.get("content"):
                    title = og["content"]
            if not title and soup.title:
                title = soup.title.get_text()
    except Exception:
        pass
    title = clean_title(title) if title else ""
    if len(title) < 4:
        title = title_from_url(url)
    return {"title": title, "price": price, "host": urlparse(url).hostname or ""}


def tokens(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def google_shopping(query):
    r = requests.get(
        "https://serpapi.com/search.json",
        params={
            "engine": "google_shopping",
            "q": query,
            "gl": "in",
            "hl": "en",
            "google_domain": "google.co.in",
            "api_key": SERPAPI_KEY,
        },
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for it in r.json().get("shopping_results", []):
        price = it.get("extracted_price")
        link = it.get("link") or it.get("product_link")
        if not price or not link:
            continue
        out.append(
            {
                "store": it.get("source", "Unknown"),
                "title": it.get("title", ""),
                "price": price,
                "price_text": it.get("price", f"₹{price:,.0f}"),
                "link": link,
                "image": it.get("thumbnail", ""),
                "rating": it.get("rating"),
            }
        )
    # keep results that look like the same product (token overlap), else keep all
    q = tokens(query)
    if q:
        close = [o for o in out if len(q & tokens(o["title"])) / len(q) >= 0.4]
        if close:
            out = close
    out.sort(key=lambda o: o["price"])
    return out


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/robots.txt")
def robots():
    return send_from_directory("static", "robots.txt")


@app.get("/api/compare")
def compare():
    url = (request.args.get("url") or "").strip()
    if not re.match(r"^https?://", url, re.I):
        return jsonify(error="Please paste a full link starting with http:// or https://"), 400
    if not SERPAPI_KEY:
        return jsonify(error="Server is missing SERPAPI_KEY."), 500

    cached = cache_get(url)
    if cached:
        return jsonify(cached)

    product = extract_product(url)
    try:
        results = google_shopping(product["title"])
    except Exception as e:
        return jsonify(error=f"Price search failed: {e}"), 502

    payload = {"product": product, "results": results}
    cache_set(url, payload)
    return jsonify(payload)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
