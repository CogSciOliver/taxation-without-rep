import requests
from bs4 import BeautifulSoup

IRS_UPDATES_SOURCES = [
    "https://www.irs.gov/newsroom/irs-releases-tax-inflation-adjustments-for-tax-year-2026-including-amendments-from-the-one-big-beautiful-bill",
    "https://www.irs.gov/newsroom/irs-sets-2026-business-standard-mileage-rate-at-725-cents-per-mile-up-25-cents",
    "https://www.irs.gov/charities-non-profits/annual-exempt-organization-return-who-must-file",
]

def fetch_tax_updates(timeout=7):
    updates = []
    headers = {"User-Agent": "TaxPLPrototype/2.0"}
    for url in IRS_UPDATES_SOURCES:
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            h1 = soup.find("h1")
            title = h1.get_text(strip=True) if h1 else url

            time_el = soup.find("time")
            date = time_el.get_text(strip=True) if time_el else ""

            p = soup.find("p")
            snippet = ""
            if p:
                txt = p.get_text(" ", strip=True)
                snippet = (txt[:240] + "…") if len(txt) > 240 else txt

            updates.append({"title": title, "date": date, "url": url, "snippet": snippet})
        except Exception:
            updates.append({"title": "IRS update (fetch failed)", "date": "", "url": url, "snippet": "Open the link directly."})
    return updates
