# Price Compare (BuyHatke-style)

Paste any product link, get prices from many Indian shopping sites, cheapest first.

## How it works
1. Backend opens your pasted link and extracts the product title.
2. It searches that title on Google Shopping (India) through SerpAPI, which returns
   prices from Amazon, Flipkart, Croma, Reliance Digital, Tata CLiQ and others.
3. Results are filtered for the same product and sorted by price.

## Run locally
```bash
pip install -r requirements.txt
export SERPAPI_KEY=your_key_here        # Windows: set SERPAPI_KEY=your_key_here
python app.py
```
Open http://localhost:5000

Get a SerpAPI key at https://serpapi.com (free plan: 100 searches/month).
Results are cached for 30 minutes so repeat links don't use credits.

## Deploy (Render, free tier)
`render.yaml` is included, so setup is mostly automatic.
1. Push this folder to a GitHub repo (`.gitignore` is included).
2. On render.com: New > Blueprint > connect the repo. Render reads `render.yaml`.
3. When asked, paste your `SERPAPI_KEY` value.
4. Deploy. You get a public https://....onrender.com link.

Custom domain: Render dashboard > your service > Settings > Custom Domains.

## Optional
- `SCRAPERAPI_KEY`: if Amazon/Flipkart block your server when reading the pasted link,
  add a ScraperAPI key. Without it the app falls back to the product name in the URL.

## Known limits
- Free API plans have monthly search limits.
- Matching is by product name, so similar variants (colour, storage) can appear. Check before buying.
- Scraping store sites directly can break their terms of service. This design uses a search API instead.
- To earn money, convert result links to affiliate links (Amazon Associates, EarnKaro, Cuelinks).
