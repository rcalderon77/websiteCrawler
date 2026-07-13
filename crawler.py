import pandas as pd
import re
import os
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright, TimeoutError

# --- CONFIGURATION ---
EXCEL_FILE = "EXCEL PATH"
START_URL = "WEBSITE"  # The root URL where the crawl begins

ENCODING_MAP = {
    "{tm}": "™",
    "{c}": "©",
    "{r}": "®",
    "&amp;": "&",
}

def normalize_text(text):
    if not isinstance(text, str):
        return str(text)
    for key, value in ENCODING_MAP.items():
        text = re.sub(re.escape(key), value, text, flags=re.IGNORECASE)
    return " ".join(text.split())

def scroll_page(page):
    """Scrolls to trigger lazy-loaded content."""
    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
    page.wait_for_timeout(1000)
    page.evaluate("window.scrollTo(0, 0);")

def expand_dropdowns(page):
    """Attempts to click open common dropdown menus."""
    expandables = page.locator('button[aria-expanded="false"], div[aria-expanded="false"]')
    for i in range(expandables.count()):
        try:
            expandables.nth(i).click(force=True, timeout=1000)
            page.wait_for_timeout(300)
        except Exception:
            continue

def get_same_domain_links(page, base_domain):
    """Extracts all links on the page and filters for the same domain."""
    # Run Javascript to grab all href attributes quickly
    hrefs = page.evaluate("Array.from(document.querySelectorAll('a[href]')).map(a => a.href)")
    
    valid_links = set()
    for href in hrefs:
        # Ignore anchor links, emails, and phone numbers
        if href.startswith(('mailto:', 'tel:', 'javascript:')) or '#' in href:
            continue
            
        parsed_href = urlparse(href)
        # Ensure it belongs to our target website domain
        if parsed_href.netloc == base_domain or parsed_href.netloc == "":
            clean_url = href.split('?')[0] # Strip URL parameters to avoid duplicate pages
            valid_links.add(clean_url)
            
    return valid_links

def main():
    if not os.path.exists("screenshots"):
        os.makedirs("screenshots")

    # 1. Load targets into a list of dictionaries to track what has been found
    df = pd.read_excel(EXCEL_FILE)
    targets = []
    for _, row in df.iterrows():
        targets.append({
            'id': row['ID'],
            'label': row['Label'],
            'search_text': normalize_text(row['English Text']),
            'found': False
        })

    # 2. Setup Crawler State
    base_domain = urlparse(START_URL).netloc
    queue = [START_URL]
    visited = set([START_URL])
    
    with sync_playwright() as p:
        print("Launching browser...")
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        # 3. Main Crawler Loop
        while queue:
            # Check if we've already found everything
            unfound_targets = [t for t in targets if not t['found']]
            if not unfound_targets:
                print("\n🎉 All strings found! Stopping crawl.")
                break
                
            current_url = queue.pop(0)
            print(f"\n[{len(queue)} pages in queue] Crawling: {current_url}")
            
            try:
                page.goto(current_url, wait_until="domcontentloaded", timeout=15000)
            except TimeoutError:
                print("  -> Page load timeout. Skipping.")
                continue
            except Exception as e:
                print(f"  -> Error loading page: {e}")
                continue
            
            # Prepare page for reading
            scroll_page(page)
            expand_dropdowns(page)
            
            # 4. Search the page for all remaining unfound strings
            for target in unfound_targets:
                # Use exact=False to find text embedded within larger paragraphs
                element = page.get_by_text(target['search_text'], exact=False).first
                
                if element.count() > 0 and element.is_visible():
                    print(f"  ✅ FOUND Target [{target['id']}]: '{target['search_text']}'")
                    
                    try:
                        element.scroll_into_view_if_needed()
                        # Draw a red box around the text so you know exactly what matched
                        element.evaluate("el => el.style.border = '3px solid red'")
                        
                        safe_label = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(target['label']))
                        filename = f"screenshots/{target['id']}_{safe_label}.png"
                        
                        # Screenshot the whole page to give context of where the element is
                        page.screenshot(path=filename)
                        
                        target['found'] = True
                    except Exception as e:
                        print(f"  -> Error capturing screenshot for [{target['id']}]: {e}")

            # 5. Harvest new links to keep crawling
            new_links = get_same_domain_links(page, base_domain)
            for link in new_links:
                if link not in visited:
                    visited.add(link)
                    queue.append(link)
                    
        browser.close()
        
        # Final Report
        print("\n--- CRAWL COMPLETE ---")
        missed = [t for t in targets if not t['found']]
        if missed:
            print(f"Could not find {len(missed)} items:")
            for m in missed:
                print(f"  - [{m['id']}] {m['search_text']}")

if __name__ == "__main__":
    main()
