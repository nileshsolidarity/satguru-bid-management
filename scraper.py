"""
Satguru Bid Management — Tender Scraper
Scrapes tenders from Global Tenders and Tenders Info using Playwright.
"""

import json
import os
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CREDS = {
    "globaltenders": {
        "name": "Global Tenders",
        "login_url": "https://www.globaltenders.com/tender-login/sign-up",
        "email": os.getenv("GT_EMAIL", "bid.marketing@satgurutravel.com"),
        "password": os.getenv("GT_PASSWORD", ""),
    },
    "tendersinfo": {
        "name": "Tenders Info",
        "login_url": "https://www.tendersinfo.com/login",
        "email": os.getenv("TI_EMAIL", "bid.marketing@satgurutravel.com"),
        "password": os.getenv("TI_PASSWORD", ""),
    },
}

# Keywords mapped to their GT sector/search URLs
GT_SEARCH_URLS = [
    "https://www.globaltenders.com/gt-search?tender_type=live&sector%5B0%5D=3205&notice_type=gpn%2Cpp%2Cspn%2Crei%2Cppn%2Cacn%2Crfc&omit_keyword=&keyword[]=travel+management",
    "https://www.globaltenders.com/gt-search?tender_type=live&sector%5B0%5D=3205&notice_type=gpn%2Cpp%2Cspn%2Crei%2Cppn%2Cacn%2Crfc&omit_keyword=&keyword[]=corporate+travel",
    "https://www.globaltenders.com/gt-search?tender_type=live&sector%5B0%5D=3205&notice_type=gpn%2Cpp%2Cspn%2Crei%2Cppn%2Cacn%2Crfc&omit_keyword=&keyword[]=travel+agency",
]

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tenders.json")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_existing():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            return json.load(f)
    return []


def save_results(tenders):
    with open(OUTPUT_FILE, "w") as f:
        json.dump(tenders, f, indent=2)
    log(f"Saved {len(tenders)} tenders to tenders.json")


def dedup(tenders):
    seen = set()
    result = []
    for t in tenders:
        key = t.get("title", "").strip().lower()[:80]
        if key and key not in seen:
            seen.add(key)
            result.append(t)
    return result


async def scrape_globaltenders(context):
    tenders = []
    creds = CREDS["globaltenders"]
    page = await context.new_page()

    try:
        log("Global Tenders: logging in...")
        await page.goto(creds["login_url"], timeout=30000)
        await page.wait_for_timeout(2000)
        await page.fill('input[name="email"]', creds["email"])
        await page.fill('input[name="password"]', creds["password"])
        await page.click('input[type="submit"]')
        await page.wait_for_timeout(4000)

        if "dashboard" not in page.url:
            log("Global Tenders: login may have failed, current URL: " + page.url)
        else:
            log("Global Tenders: logged in successfully")

        for url in GT_SEARCH_URLS:
            keyword = url.split("keyword[]=")[-1].replace("+", " ")
            log(f"Global Tenders: searching '{keyword}'...")
            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(4000)

            # Extract all tender cards using JS
            results = await page.evaluate("""
                () => {
                    const cards = document.querySelectorAll('.tender-wrap');
                    return Array.from(cards).map(card => {
                        const title = card.querySelector('[itemprop="name"]')?.innerText?.trim() || '';
                        const authorityEl = Array.from(card.querySelectorAll('div')).find(d => d.innerText.startsWith('Authority:'));
                        const authority = authorityEl ? authorityEl.innerText.replace('Authority:', '').trim() : '';
                        const country = card.querySelector('[itemprop="address"]')?.innerText?.trim() || '';
                        const dates = Array.from(card.querySelectorAll('[itemprop="startDate"], [itemprop="endDate"]')).map(d => d.innerText?.trim());
                        const postingDate = dates[0] || '';
                        const deadline = dates[1] || '';
                        const postingId = card.id?.replace('tender_', '') || '';
                        const detailLink = postingId ? `https://www.globaltenders.com/global-tender-details/${postingId}` : '';
                        return { title, authority, country, postingDate, deadline, detailLink };
                    }).filter(r => r.title.length > 5);
                }
            """)

            for r in results:
                tenders.append({
                    "title": r["title"],
                    "authority": r["authority"],
                    "country": r["country"],
                    "posting_date": r["postingDate"],
                    "deadline": r["deadline"],
                    "link": r["detailLink"],
                    "source": "Global Tenders",
                    "keyword": keyword,
                    "scraped_at": datetime.now().isoformat(),
                    "status": "New",
                })

            log(f"Global Tenders: got {len(results)} results for '{keyword}'")

    except PlaywrightTimeout as e:
        log(f"Global Tenders: timeout — {e}")
    except Exception as e:
        log(f"Global Tenders: error — {e}")
    finally:
        await page.close()

    log(f"Global Tenders: total {len(tenders)} tenders scraped")
    return tenders


async def scrape_tendersinfo(context):
    tenders = []
    creds = CREDS["tendersinfo"]
    page = await context.new_page()

    try:
        log("Tenders Info: logging in...")
        await page.goto(creds["login_url"], timeout=30000)
        await page.wait_for_selector('input[name="user_id"]', state="visible", timeout=15000)
        await page.fill('input[name="user_id"]', creds["email"])
        await page.fill('input[name="password"]', creds["password"])
        await page.click('button:has-text("Sign In")')
        await page.wait_for_timeout(5000)
        log(f"Tenders Info: logged in, URL: {page.url}")

        keywords = ["travel management", "corporate travel", "travel agency services", "airline ticketing"]
        for keyword in keywords:
            log(f"Tenders Info: searching '{keyword}'...")
            try:
                api_response = {}

                async def capture(response):
                    if "GetTendersList" in response.url:
                        try:
                            data = await response.json()
                            api_response['data'] = data
                        except Exception:
                            pass

                page.on("response", capture)
                search_url = f"https://www.tendersinfo.net/TenderAI/TenderAIList?searchtext={keyword.replace(' ', '+')}-tenders"
                await page.goto(search_url, timeout=30000)
                await page.wait_for_timeout(6000)
                page.remove_listener("response", capture)

                tender_list = api_response.get('data', {}).get('TenderList', [])
                log(f"Tenders Info: got {len(tender_list)} results for '{keyword}'")

                for t in tender_list:
                    tenders.append({
                        "title": (t.get("tendersbriefnew") or t.get("tendersbrief", "")).strip(),
                        "authority": t.get("companyname", "").title(),
                        "country": t.get("countryname", "").title(),
                        "posting_date": t.get("tenderdate", ""),
                        "deadline": t.get("closingdate", ""),
                        "ref_no": t.get("tenderrefno", ""),
                        "tid": t.get("tcno", ""),
                        "link": t.get("descriptionlink", ""),
                        "source": "Tenders Info",
                        "keyword": keyword,
                        "scraped_at": datetime.now().isoformat(),
                        "status": "New",
                    })

            except Exception as e:
                log(f"Tenders Info: error for '{keyword}': {e}")

    except PlaywrightTimeout as e:
        log(f"Tenders Info: timeout — {e}")
    except Exception as e:
        log(f"Tenders Info: error — {e}")
    finally:
        await page.close()

    log(f"Tenders Info: total {len(tenders)} tenders scraped")
    return tenders


async def run_scraper(headless=True):
    log("=" * 50)
    log("Starting Satguru Tender Scraper")
    log("=" * 50)
    all_new = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )

        gt = await scrape_globaltenders(context)
        all_new.extend(gt)

        ti = await scrape_tendersinfo(context)
        all_new.extend(ti)

        await browser.close()

    existing = load_existing()
    combined = dedup(existing + all_new)
    save_results(combined)

    log(f"Done. {len(all_new)} new tenders found. {len(combined)} total in tracker.")
    return all_new


if __name__ == "__main__":
    asyncio.run(run_scraper(headless=False))
