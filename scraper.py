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


async def run_scraper(headless=True, save_fn=None, load_fn=None):
    log("=" * 50)
    log("Starting Satguru Tender Scraper")
    log("=" * 50)
    all_new = []

    _load = load_fn or load_existing
    _save = save_fn or save_results

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

    existing = _load()
    combined = dedup(existing + all_new)
    _save(combined)

    log(f"Done. {len(all_new)} new tenders found. {len(combined)} total in tracker.")
    return all_new


async def fetch_tender_page(url: str) -> str:
    """Log in to the portal, scrape tender details, return a clean standalone HTML page."""
    is_gt = "globaltenders.com" in url
    is_ti = "tendersinfo" in url
    creds = CREDS["globaltenders"] if is_gt else CREDS["tendersinfo"] if is_ti else None

    details = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            if creds:
                log(f"Logging in to {creds['name']} to fetch: {url}")
                await page.goto(creds["login_url"], timeout=30000)
                await page.wait_for_timeout(2000)
                if is_gt:
                    await page.fill('input[name="email"]', creds["email"])
                    await page.fill('input[name="password"]', creds["password"])
                    await page.click('input[type="submit"]')
                else:
                    await page.wait_for_selector('input[name="user_id"]', state="visible", timeout=15000)
                    await page.fill('input[name="user_id"]', creds["email"])
                    await page.fill('input[name="password"]', creds["password"])
                    await page.click('button:has-text("Sign In")')
                await page.wait_for_timeout(5000)
                log(f"After login, URL: {page.url}")

            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(4000)
            final_url = page.url
            log(f"Tender page final URL: {final_url}")

            # Check for login redirect (session didn't persist)
            if any(x in final_url.lower() for x in ["login", "sign-up", "sign_in", "signin"]) and final_url.rstrip("/") != url.rstrip("/"):
                details = {"error_type": "login_redirect", "pageUrl": url}
            else:
                page_text_start = await page.evaluate("() => document.body.innerText.slice(0, 300).toLowerCase()")
                if "page not found" in page_text_start or "not a functioning page" in page_text_start or "404" in page_text_start:
                    details = {"error_type": "expired", "pageUrl": url}
                else:
                    details = await page.evaluate("""
                    () => {
                        const get = sel => document.querySelector(sel)?.innerText?.trim() || '';
                        const pairs = {};
                        document.querySelectorAll('table tr').forEach(row => {
                            const cells = row.querySelectorAll('td');
                            if (cells.length >= 2) {
                                const k = cells[0].innerText.trim().replace(/:$/, '');
                                const v = cells[1].innerText.trim();
                                if (k && v && k.length < 60) pairs[k] = v;
                            }
                        });
                        return {
                            title: get('h1') || get('h2') || get('.tender-title') || get('[itemprop="name"]'),
                            body: document.body.innerText.slice(0, 10000),
                            pairs,
                            pageUrl: location.href,
                        };
                    }
                    """)
        except Exception as e:
            log(f"fetch_tender_page error: {e}")
            details = {"error_type": "exception", "error_msg": str(e)}
        finally:
            await browser.close()

    # ── Build output HTML ──────────────────────────────────────────────────
    error_type = details.get("error_type", "")
    page_url = details.get("pageUrl", url)

    if error_type == "expired":
        content_html = f"""
        <div class="warn-box">
          <strong>This tender is no longer available on the portal.</strong><br>
          The link may have expired or the tender was removed. This is common for older synced tenders.<br><br>
          <b>What to do:</b> Click <em>Sync Portals</em> on the main page to fetch fresh tenders with valid links.
        </div>
        <div class="source-box">Original URL: <a href="{url}" target="_blank">{url}</a></div>
        """
        title = "Tender Expired"
    elif error_type == "login_redirect":
        content_html = f"""
        <div class="error-box">
          Login did not persist when navigating to the tender page.<br>
          <a href="{url}" target="_blank">Try opening directly on the portal →</a>
        </div>"""
        title = "Login Error"
    elif error_type == "exception":
        content_html = f"""
        <div class="error-box">
          Error: {details.get('error_msg', 'Unknown error')}<br>
          <a href="{url}" target="_blank">Try opening directly →</a>
        </div>"""
        title = "Error"
    else:
        title = details.get("title", "") or "Tender Detail"
        pairs = details.get("pairs", {})
        body_text = details.get("body", "")

        pairs_rows = "".join(
            f'<tr><td class="lc">{k}</td><td>{v}</td></tr>'
            for k, v in pairs.items() if k and v
        )
        table_html = f'<table class="dt"><tbody>{pairs_rows}</tbody></table>' if pairs_rows else ""

        lines = [l.strip() for l in body_text.split("\n") if l.strip() and len(l.strip()) > 4]
        body_html = "".join(f"<p>{l}</p>" for l in lines[:150])

        content_html = f"""
        {table_html}
        <div class="full-text"><h3>Page Content</h3>{body_html}</div>
        <div class="source-box">Source: <a href="{page_url}" target="_blank">{page_url}</a></div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',sans-serif;background:#f0f2f5;color:#1a1a2e}}
  .topbar{{position:sticky;top:0;background:#1a1a2e;color:white;padding:12px 24px;
    display:flex;align-items:center;justify-content:space-between;z-index:100;
    box-shadow:0 2px 8px rgba(0,0,0,.3)}}
  .tl{{font-size:15px;font-weight:700}}.ts{{font-size:11px;opacity:.6;margin-top:2px}}
  .close-btn{{background:#e94560;border:none;color:white;padding:7px 16px;
    border-radius:7px;cursor:pointer;font-weight:700;font-size:13px}}
  .container{{max-width:960px;margin:24px auto;padding:0 20px 60px}}
  .card{{background:white;border-radius:12px;border:1px solid #e0e4ea;padding:24px;margin-bottom:20px}}
  .card h2{{font-size:18px;font-weight:700;color:#1a1a2e;margin-bottom:16px;line-height:1.4}}
  .dt{{width:100%;border-collapse:collapse;margin-bottom:20px}}
  .dt td{{padding:9px 12px;border-bottom:1px solid #f0f2f5;font-size:13px;vertical-align:top}}
  .lc{{font-weight:600;color:#6b7280;width:36%;background:#f8fafc}}
  .full-text h3{{font-size:12px;font-weight:700;color:#9ca3af;margin:16px 0 10px;text-transform:uppercase;letter-spacing:.5px}}
  .full-text p{{font-size:13px;color:#374151;line-height:1.6;margin-bottom:5px;padding:3px 0;border-bottom:1px solid #f9fafb}}
  .error-box{{background:#fee2e2;color:#991b1b;padding:20px;border-radius:10px;line-height:1.7}}
  .warn-box{{background:#fef3c7;color:#92400e;padding:20px;border-radius:10px;line-height:1.8}}
  .source-box{{margin-top:16px;padding:12px;background:#f0f4ff;border-radius:8px;font-size:12px;color:#555}}
</style>
</head>
<body>
<div class="topbar">
  <div><div class="tl">📋 Satguru — Tender Detail</div><div class="ts">Fetched via automated login · Read-only</div></div>
  <button class="close-btn" onclick="window.close()">✕ Close</button>
</div>
<div class="container">
  <div class="card">
    <h2>{title}</h2>
    {content_html}
  </div>
</div>
</body>
</html>"""


if __name__ == "__main__":
    asyncio.run(run_scraper(headless=False))
