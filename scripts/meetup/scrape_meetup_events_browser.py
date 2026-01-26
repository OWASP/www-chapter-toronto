#!/usr/bin/env python3
"""
Meetup Event Scraper with Browser Automation for OWASP Toronto Chapter

Uses Playwright to handle infinite scroll pagination and capture screenshots.
Scrapes ALL past events from Meetup.com and generates markdown files.

Usage:
    uv run scrape_meetup_events_browser.py

Requirements:
    - request.txt file in repository root with exported browser headers
    - Python 3.8+
    - Dependencies from pyproject.toml
    - Playwright browsers installed (run: playwright install)
"""

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import html2text
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from playwright.async_api import async_playwright, Page, Browser


def parse_cookies_from_request_file(filepath: str = '../../request.txt') -> Dict[str, str]:
    """
    Parse cookies from exported request file

    Args:
        filepath: Path to request.txt file

    Returns:
        Dictionary of cookie key-value pairs
    """
    script_dir = Path(__file__).parent
    request_file = script_dir / filepath

    if not request_file.exists():
        # Try absolute path from repo root
        request_file = Path('/Users/ads/git/www-chapter-toronto/request.txt')
        if not request_file.exists():
            raise FileNotFoundError(
                f"request.txt not found. Tried: {script_dir / filepath} and {request_file}. "
                "Please export your browser request headers to request.txt in repo root."
            )

    print(f"Reading cookies from: {request_file}")

    cookies = {}

    with open(request_file, 'r') as f:
        lines = f.readlines()

    # Simple approach: find the line that says 'cookie' and grab the next line
    for i, line in enumerate(lines):
        if line.strip().lower() == 'cookie' and i + 1 < len(lines):
            cookie_value = lines[i + 1].strip()
            if cookie_value and '=' in cookie_value:
                cookie_pairs = cookie_value.split('; ')
                for pair in cookie_pairs:
                    if '=' in pair:
                        key, value = pair.split('=', 1)
                        cookies[key.strip()] = value.strip()
                break

    print(f"Parsed {len(cookies)} cookies")
    return cookies


async def load_page_with_cookies(page: Page, url: str, cookies: Dict[str, str]) -> None:
    """
    Load a page with authentication cookies

    Args:
        page: Playwright page object
        url: URL to load
        cookies: Dictionary of cookies to set
    """
    # Convert cookies to Playwright format
    if cookies:
        cookie_list = []
        for name, value in cookies.items():
            cookie_list.append({
                'name': name,
                'value': value,
                'domain': '.meetup.com',
                'path': '/'
            })
        await page.context.add_cookies(cookie_list)

    # Load page with longer timeout
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        # Wait a bit more for dynamic content
        await asyncio.sleep(3)
    except Exception as e:
        print(f"Warning: Page load issue: {e}")
        print("Continuing anyway...")


async def click_load_more_buttons(page: Page) -> bool:
    """Try to find and click any 'load more' or 'show more' buttons"""
    try:
        # Try various common selectors for load more buttons
        selectors = [
            'button:has-text("Show more")',
            'button:has-text("Load more")',
            'button:has-text("See more")',
            '[data-testid="load-more"]',
            'a:has-text("Show more events")'
        ]

        for selector in selectors:
            try:
                button = page.locator(selector).first
                if await button.is_visible(timeout=1000):
                    await button.click()
                    print(f"  → Clicked '{selector}' button")
                    await asyncio.sleep(3)
                    return True
            except:
                continue

        return False
    except:
        return False


async def scroll_to_load_all_events(page: Page, max_scrolls: int = 300) -> None:
    """
    Scroll down the page to trigger infinite scroll and load ALL past events.
    Keep scrolling until no more events load. Be VERY patient.

    Args:
        page: Playwright page object
        max_scrolls: Maximum number of scroll attempts (safety limit)
    """
    print("Scrolling to load ALL events (this may take 10-20 minutes)...")

    previous_event_count = 0
    no_change_count = 0
    scroll_count = 0

    while scroll_count < max_scrolls:
        scroll_count += 1

        # Try clicking load more button first
        clicked = await click_load_more_buttons(page)
        if clicked:
            await asyncio.sleep(5)  # Wait for content to load after click

        # Scroll to bottom in multiple steps
        await page.evaluate('window.scrollBy(0, window.innerHeight * 0.8)')
        await asyncio.sleep(1)
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')

        # Wait MUCH longer for content to load (Meetup's infinite scroll is slow)
        await asyncio.sleep(5)

        # Count current events in multiple ways
        current_html = await page.content()
        event_count = current_html.count('Event:')
        past_count = current_html.count('"status":"PAST"')

        if scroll_count % 3 == 0:  # Report every 3 scrolls
            print(f"  Scroll {scroll_count}: Found ~{event_count} event refs, {past_count} PAST events")

        # Check if we loaded new events
        if event_count == previous_event_count:
            no_change_count += 1
            # Be EXTREMELY patient - wait for 20 consecutive no-change attempts
            # User reported seeing events back to 2022, so keep trying!
            if no_change_count >= 20:
                print(f"  No new events loaded after {no_change_count} attempts. Done scrolling.")
                break
        else:
            no_change_count = 0
            print(f"  → Loaded more events! Total now: ~{event_count}")

        previous_event_count = event_count

        # Additional wait for network to settle
        await asyncio.sleep(3)

    print(f"Finished scrolling after {scroll_count} attempts.")
    print(f"Total event references: ~{previous_event_count}")


def extract_event_urls_from_html_links(html: str) -> List[str]:
    """
    Extract event URLs from HTML anchor tags (for older events)

    Args:
        html: HTML content of page

    Returns:
        List of unique event URLs
    """
    soup = BeautifulSoup(html, 'lxml')
    event_urls = set()

    # Find all links to owasp-toronto events
    pattern = re.compile(r'/owasp-toronto/events/\d+')

    for link in soup.find_all('a', href=pattern):
        href = link.get('href')
        if href:
            # Normalize URL
            if href.startswith('/'):
                full_url = f"https://www.meetup.com{href}"
            else:
                full_url = href

            # Remove query parameters
            full_url = full_url.split('?')[0]

            event_urls.add(full_url)

    return sorted(list(event_urls))


def extract_events_from_html(html: str) -> List[Dict]:
    """
    Extract event data from Next.js __APOLLO_STATE__ AND HTML links

    Args:
        html: HTML content of page

    Returns:
        List of event dictionaries (URLs for older events that need individual fetching)
    """
    events = []
    event_urls_found = set()

    # Method 1: Extract from __APOLLO_STATE__ (recent events with full data)
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', html, re.DOTALL)

    if match:
        try:
            next_data = json.loads(match.group(1))
            apollo_state = next_data.get('props', {}).get('pageProps', {}).get('__APOLLO_STATE__', {})

            # Find all Event objects
            event_keys = [k for k in apollo_state.keys() if k.startswith('Event:')]

            for event_key in event_keys:
                event_data = apollo_state[event_key]

                # Only include PAST events
                if event_data.get('status') == 'PAST':
                    try:
                        # Extract venue information
                        venue_ref = event_data.get('venue', {})
                        if isinstance(venue_ref, dict):
                            venue_ref = venue_ref.get('__ref')
                        venue_data = apollo_state.get(venue_ref, {}) if venue_ref else {}

                        # Build event dictionary
                        event = {
                            'event_id': event_data.get('id'),
                            'title': event_data.get('title'),
                            'url': event_data.get('eventUrl'),
                            'description': event_data.get('description'),
                            'date_time': event_data.get('dateTime'),
                            'end_time': event_data.get('endTime'),
                            'going_count': event_data.get('going', {}).get('totalCount', 0) if event_data.get('going') else 0,
                            'event_type': event_data.get('eventType'),
                            'venue_name': venue_data.get('name') if venue_data else None,
                            'venue_address': venue_data.get('address') if venue_data else None,
                            'venue_city': venue_data.get('city') if venue_data else None,
                            'is_online': event_data.get('isOnline', False),
                            'created_time': event_data.get('createdTime')
                        }

                        # Extract featured photo if available
                        photo_ref = event_data.get('featuredEventPhoto', {})
                        if isinstance(photo_ref, dict):
                            photo_ref = photo_ref.get('__ref')
                        if photo_ref:
                            photo_data = apollo_state.get(photo_ref, {})
                            base_url = photo_data.get('baseUrl') if photo_data else None
                            photo_id = photo_data.get('id') if photo_data else None
                            if base_url and photo_id:
                                # Construct full photo URL
                                event['featured_photo_url'] = f"{base_url}{photo_id}/highres_{photo_id}.jpeg"

                        events.append(event)
                        event_urls_found.add(event['url'])
                    except Exception as e:
                        print(f"Warning: Error processing event {event_key}: {e}")

            print(f"Extracted {len(events)} recent events from Apollo state")

        except Exception as e:
            print(f"Error extracting from Apollo state: {e}")

    # Method 2: Extract event URLs from HTML links (older events)
    html_event_urls = extract_event_urls_from_html_links(html)
    print(f"Found {len(html_event_urls)} event URLs in HTML links")

    # Add older events as stub entries (need to fetch individually)
    for url in html_event_urls:
        if url not in event_urls_found:
            # Extract event ID from URL
            match = re.search(r'/events/(\d+)', url)
            if match:
                events.append({
                    'event_id': match.group(1),
                    'url': url,
                    'needs_fetch': True  # Flag that we need to visit this page
                })

    print(f"Total events to process: {len(events)}")
    return events


async def capture_event_screenshot(page: Page, event_url: str, save_path: str, retries: int = 2) -> bool:
    """
    Navigate to event page and capture full-page screenshot

    Args:
        page: Playwright page object
        event_url: URL of event page
        save_path: Path to save screenshot
        retries: Number of retry attempts

    Returns:
        True if successful, False otherwise
    """
    for attempt in range(retries):
        try:
            await page.goto(event_url, wait_until='domcontentloaded', timeout=60000)
            await asyncio.sleep(3)  # Let page fully render

            # Capture full page screenshot
            await page.screenshot(path=save_path, full_page=True)
            print(f"  Captured screenshot: {Path(save_path).name}")
            return True

        except Exception as e:
            if attempt < retries - 1:
                print(f"  Screenshot attempt {attempt + 1} failed, retrying...")
                await asyncio.sleep(2)
            else:
                print(f"  Error capturing screenshot after {retries} attempts: {str(e)[:100]}")
                return False

    return False


def convert_meetup_html_to_markdown(html_content: Optional[str]) -> str:
    """Convert Meetup event description HTML to clean markdown"""
    if not html_content:
        return ""

    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False

    markdown = h.handle(html_content)
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    markdown = markdown.strip()

    return markdown


def generate_event_markdown(event_data: Dict, images_relative_path: str = '../images') -> str:
    """Generate markdown for a single event matching tab_pastevents.md format"""
    lines = []
    lines.append("---")
    lines.append("")

    # Date/Time
    if event_data.get('start_date'):
        try:
            start_dt = date_parser.parse(event_data['start_date'])
            date_str = start_dt.strftime("%B %d, %Y, %I:%M %p")

            if event_data.get('end_date'):
                end_dt = date_parser.parse(event_data['end_date'])
                date_str += f" to {end_dt.strftime('%I:%M %p')}"

            timezone = start_dt.strftime("%Z")
            if timezone:
                date_str += f" {timezone}"

            lines.append(f"**Date/Time**: {date_str}")
        except:
            lines.append(f"**Date/Time**: {event_data.get('start_date', 'Unknown')}")

    # Location
    location = event_data.get('location', {})
    if isinstance(location, dict):
        if location.get('type') == 'online' and location.get('url'):
            lines.append(f"**Location**: online: {location['url']}")
        elif location.get('name'):
            lines.append(f"**Location**: {location['name']}")
        else:
            lines.append(f"**Location**: See event details")

    # Attendee count
    if event_data.get('attendee_count'):
        lines.append(f"**Attendees**: {event_data['attendee_count']} RSVPs")

    lines.append("")

    # Title
    if event_data.get('title'):
        lines.append(f"**{event_data['title']}**")
        lines.append("")

    # Summary/Description
    if event_data.get('description'):
        markdown_desc = convert_meetup_html_to_markdown(event_data['description'])
        if markdown_desc:
            lines.append("**Summary:**")
            lines.append("")
            lines.append(markdown_desc)
            lines.append("")

    # Event URL
    if event_data.get('url'):
        lines.append(f"[View on Meetup]({event_data['url']})")
        lines.append("")

    # Screenshot
    if event_data.get('screenshot_file'):
        lines.append(f"![Event Screenshot]({images_relative_path}/{event_data['screenshot_file']})")
        lines.append("")

    return '\n'.join(lines)


async def main():
    """Main scraper execution with browser automation"""
    print("=" * 60)
    print("OWASP Toronto Meetup Event Scraper (Browser Edition)")
    print("=" * 60)
    print()

    # Parse cookies
    print("Step 1: Parsing authentication cookies...")
    try:
        cookies = parse_cookies_from_request_file()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return

    # Setup paths
    script_dir = Path(__file__).parent
    output_dir = script_dir / "../../archive/meetup-events"
    images_dir = output_dir / "images"
    screenshots_dir = output_dir / "screenshots"

    # Create directories
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    print("\nStep 2: Launching browser...")
    async with async_playwright() as p:
        # Launch browser (headless mode)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = await context.new_page()

        # Check if we have a pre-discovered event list
        discovered_events_file = script_dir / "discovered_events.txt"
        events = []

        if discovered_events_file.exists():
            print("\nStep 3: Using pre-discovered event list...")
            with open(discovered_events_file, 'r') as f:
                event_urls = [line.strip() for line in f if line.strip()]

            print(f"Found {len(event_urls)} events in pre-discovered list")

            # Convert URLs to event objects
            for url in event_urls:
                if url.startswith('/'):
                    url = f"https://www.meetup.com{url}"

                match = re.search(r'/events/(\d+)', url)
                if match:
                    events.append({
                        'event_id': match.group(1),
                        'url': url,
                        'needs_fetch': True
                    })
        else:
            print("\nStep 3: Loading past events page with authentication...")
            url = "https://www.meetup.com/owasp-toronto/events/?type=past"
            await load_page_with_cookies(page, url, cookies)

            print("\nStep 4: Scrolling to load all events (this may take a while)...")
            await scroll_to_load_all_events(page)

            print("\nStep 5: Extracting event data...")
            html = await page.content()

            # Save the fully-scrolled HTML for debugging
            debug_html_path = output_dir / "fully-scrolled-page.html"
            with open(debug_html_path, 'w') as f:
                f.write(html)
            print(f"Saved fully-scrolled HTML to: {debug_html_path}")

            events = extract_events_from_html(html)

        if not events:
            print("No events found!")
            await browser.close()
            return

        # Add cookies to context for fetching individual pages
        await load_page_with_cookies(page, events[0]['url'], cookies)

        print(f"\nFound {len(events)} past events")

        print("\nStep 4: Fetching details for events and capturing screenshots...")
        all_events = []

        for i, event in enumerate(events, 1):
            # If event needs fetching (older event from HTML link), get details from page
            if event.get('needs_fetch'):
                print(f"\nEvent {i}/{len(events)}: Fetching event {event['event_id']}...")
                try:
                    await page.goto(event['url'], wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(2)

                    event_html = await page.content()
                    event_soup = BeautifulSoup(event_html, 'lxml')

                    # Extract data from individual event page
                    # Try to find title
                    title_elem = event_soup.select_one('h1, [data-testid="event-title"]')
                    event['title'] = title_elem.get_text(strip=True) if title_elem else f"Event {event['event_id']}"

                    # Try to extract description
                    desc_elem = event_soup.select_one('[class*="description"], [class*="eventDescription"]')
                    event['description'] = str(desc_elem) if desc_elem else None

                    # Try to extract date (look for time elements or structured data)
                    time_elem = event_soup.select_one('time[datetime]')
                    if time_elem:
                        event['date_time'] = time_elem.get('datetime')

                    print(f"  → {event['title'][:60]}")

                except Exception as e:
                    print(f"  Error fetching event details: {e}")
                    event['title'] = f"Event {event['event_id']}"

                await asyncio.sleep(1)  # Rate limiting

            print(f"\nEvent {i}/{len(events)}: {event.get('title', 'Unknown')[:60]}")

            # Capture screenshot
            if event.get('url'):
                screenshot_filename = f"{event['event_id']}-screenshot.png"
                screenshot_path = screenshots_dir / screenshot_filename

                if await capture_event_screenshot(page, event['url'], str(screenshot_path)):
                    event['screenshot_file'] = screenshot_filename

            # Normalize field names for markdown generation
            event['start_date'] = event.get('date_time')
            event['end_date'] = event.get('end_time')
            event['attendee_count'] = event.get('going_count')

            # Build location dict
            if event.get('is_online'):
                event['location'] = {
                    'type': 'online',
                    'name': 'Online event',
                    'url': event.get('url')
                }
            elif event.get('venue_name'):
                location_parts = [event.get('venue_name')]
                if event.get('venue_address'):
                    location_parts.append(event['venue_address'])
                if event.get('venue_city'):
                    location_parts.append(event['venue_city'])

                event['location'] = {
                    'type': 'physical',
                    'name': ', '.join(location_parts)
                }
            else:
                event['location'] = {'type': 'unknown', 'name': 'See event details'}

            all_events.append(event)

            # Rate limiting
            await asyncio.sleep(1)

        await browser.close()

    # Save JSON output
    print("\nStep 5: Saving JSON output...")
    json_path = output_dir / "all-events.json"
    with open(json_path, 'w') as f:
        json.dump(all_events, f, indent=2, default=str)
    print(f"Saved to: {json_path}")

    # Generate markdown files
    print("\nStep 6: Generating markdown files...")
    events_by_year = {}
    events_by_year_month = {}

    for event in all_events:
        if event.get('start_date'):
            try:
                dt = date_parser.parse(event['start_date'])
                year = dt.year
                month = dt.month

                if year not in events_by_year:
                    events_by_year[year] = []
                events_by_year[year].append(event)

                year_month_key = (year, month)
                if year_month_key not in events_by_year_month:
                    events_by_year_month[year_month_key] = []
                events_by_year_month[year_month_key].append(event)
            except:
                pass

    # Generate individual markdown files per event in year/month directories
    print("\n  Creating individual event markdown files...")
    individual_event_count = 0
    for event in all_events:
        if event.get('start_date'):
            try:
                dt = date_parser.parse(event['start_date'])
                year = dt.year
                month = dt.strftime('%m')  # Zero-padded month

                # Create year/month directory
                event_dir = output_dir / str(year) / month
                event_dir.mkdir(parents=True, exist_ok=True)

                # Generate filename from event ID and slugified title
                event_slug = event['title'][:50].lower()
                event_slug = re.sub(r'[^\w\s-]', '', event_slug)
                event_slug = re.sub(r'[-\s]+', '-', event_slug).strip('-')
                filename = f"{event['event_id']}-{event_slug}.md"

                # Generate markdown for this event
                event_md = generate_event_markdown(event, images_relative_path='../../screenshots')

                # Save individual event file
                event_path = event_dir / filename
                with open(event_path, 'w') as f:
                    f.write(event_md)

                individual_event_count += 1
            except Exception as e:
                print(f"    Error creating file for event {event.get('event_id')}: {e}")

    print(f"  Created {individual_event_count} individual event files")

    # Generate year summary files
    print("\n  Creating year summary files...")
    for year in sorted(events_by_year.keys(), reverse=True):
        year_events = events_by_year[year]

        markdown_lines = []
        markdown_lines.append(f"### {year} ###")
        markdown_lines.append("")

        # Sort events by date (newest first)
        year_events.sort(
            key=lambda e: date_parser.parse(e['start_date']) if e.get('start_date') else datetime.min,
            reverse=True
        )

        for event in year_events:
            event_md = generate_event_markdown(event, images_relative_path='./screenshots')
            markdown_lines.append(event_md)

        # Save year summary file
        md_path = output_dir / f"events-{year}.md"
        with open(md_path, 'w') as f:
            f.write('\n'.join(markdown_lines))

        print(f"  Generated: {md_path.name} ({len(year_events)} events)")

    # Print summary
    print("\n" + "=" * 60)
    print("SCRAPING COMPLETE!")
    print("=" * 60)
    print(f"Total events scraped: {len(all_events)}")
    print(f"Years covered: {sorted(events_by_year.keys())}")
    print(f"\nOutput location: {output_dir}")
    print("\nFiles generated:")
    print("  - all-events.json (raw data)")
    print(f"  - {individual_event_count} individual event markdown files in YYYY/MM/ directories")
    for year in sorted(events_by_year.keys()):
        print(f"  - events-{year}.md ({len(events_by_year[year])} events)")
    print(f"\nScreenshots saved to: {screenshots_dir}")

    # Show directory structure sample
    print("\nDirectory structure:")
    print("  archive/meetup-events/")
    print("    ├── YYYY/")
    print("    │   └── MM/")
    print("    │       └── EVENT_ID-title.md")
    print("    ├── events-YYYY.md")
    print("    └── screenshots/")
    print()


if __name__ == '__main__':
    asyncio.run(main())
