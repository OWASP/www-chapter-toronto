#!/usr/bin/env python3
"""
Meetup Event Scraper for OWASP Toronto Chapter

Scrapes all past events from Meetup.com using session cookie authentication
and generates markdown files matching the existing tab_pastevents.md format.

Usage:
    python scrape_meetup_events.py

Requirements:
    - request.txt file in repository root with exported browser headers
    - Python 3.7+
    - Dependencies from requirements.txt
"""

import requests
from bs4 import BeautifulSoup
import html2text
import json
import os
import re
import time
from datetime import datetime
from dateutil import parser as date_parser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse


class MeetupScraper:
    """Scraper for Meetup.com events using session cookies"""

    def __init__(self, cookies: Dict[str, str], headers: Dict[str, str]):
        """
        Initialize scraper with authentication

        Args:
            cookies: Dictionary of cookie key-value pairs
            headers: Dictionary of HTTP headers
        """
        self.session = requests.Session()
        self.session.cookies.update(cookies)
        self.session.headers.update(headers)
        self.base_url = "https://www.meetup.com"

    def get_past_events_page(self, group_urlname: str) -> str:
        """
        Fetch the past events page HTML

        Args:
            group_urlname: Meetup group URL name (e.g., 'owasp-toronto')

        Returns:
            HTML content as string
        """
        url = f"{self.base_url}/{group_urlname}/events/past/"
        print(f"Fetching past events from: {url}")

        response = self.session.get(url)

        if response.status_code == 401 or response.status_code == 403:
            raise Exception(
                "Authentication failed. Cookies may have expired. "
                "Please re-export cookies from your browser to request.txt"
            )

        response.raise_for_status()
        return response.text

    def parse_event_list(self, html: str) -> List[Dict]:
        """
        Extract event data from Next.js __APOLLO_STATE__ in HTML

        Args:
            html: HTML content of past events page

        Returns:
            List of event dictionaries with full details from Apollo state
        """
        events = []

        # Find __NEXT_DATA__ script content
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', html, re.DOTALL)

        if not match:
            print("Could not find __NEXT_DATA__ in HTML")
            return events

        try:
            next_data = json.loads(match.group(1))
            apollo_state = next_data.get('props', {}).get('pageProps', {}).get('__APOLLO_STATE__', {})

            # Find all Event objects (keys like "Event:312744618")
            event_keys = [k for k in apollo_state.keys() if k.startswith('Event:')]

            for event_key in event_keys:
                event_data = apollo_state[event_key]

                # Only include PAST events
                if event_data.get('status') == 'PAST':
                    # Extract venue information if available
                    venue_ref = event_data.get('venue', {}).get('__ref')
                    venue_data = apollo_state.get(venue_ref, {}) if venue_ref else {}

                    # Build event dictionary
                    event = {
                        'event_id': event_data.get('id'),
                        'title': event_data.get('title'),
                        'url': event_data.get('eventUrl'),
                        'description': event_data.get('description'),
                        'date_time': event_data.get('dateTime'),
                        'end_time': event_data.get('endTime'),
                        'going_count': event_data.get('going', {}).get('totalCount', 0),
                        'event_type': event_data.get('eventType'),
                        'venue_name': venue_data.get('name'),
                        'venue_address': venue_data.get('address'),
                        'venue_city': venue_data.get('city'),
                        'is_online': event_data.get('isOnline', False),
                        'created_time': event_data.get('createdTime')
                    }

                    # Extract featured photo if available
                    photo_ref = event_data.get('featuredEventPhoto', {}).get('__ref')
                    if photo_ref:
                        photo_data = apollo_state.get(photo_ref, {})
                        if photo_data.get('baseUrl'):
                            event['featured_photo_url'] = photo_data.get('baseUrl')

                    events.append(event)

            print(f"Found {len(events)} past events in Apollo state")

        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
        except Exception as e:
            print(f"Error extracting events from Apollo state: {e}")

        return events

    def get_event_details(self, event_url: str) -> Dict:
        """
        Scrape individual event page for full details

        Args:
            event_url: Full URL to event page

        Returns:
            Dictionary containing all event details
        """
        print(f"Fetching event details: {event_url}")

        try:
            response = self.session.get(event_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')

            # Extract event data using various selectors
            event_data = {
                'url': event_url,
                'title': self._extract_title(soup),
                'description': self._extract_description(soup),
                'start_date': self._extract_date(soup, 'startDate'),
                'end_date': self._extract_date(soup, 'endDate'),
                'location': self._extract_location(soup),
                'attendee_count': self._extract_attendee_count(soup),
                'photos': self._extract_photos(soup),
                'scraped_at': datetime.now().isoformat()
            }

            return event_data

        except Exception as e:
            print(f"Error fetching event details from {event_url}: {e}")
            return {
                'url': event_url,
                'error': str(e),
                'scraped_at': datetime.now().isoformat()
            }

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract event title from page"""
        # Try multiple selectors
        selectors = [
            '[itemProp="name"]',
            'h1',
            '[data-event-label="event-title"]'
        ]

        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                return element.get_text(strip=True)

        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract event description HTML"""
        selectors = [
            '[itemProp="description"]',
            '[class*="event-description"]',
            '[class*="eventDescription"]'
        ]

        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                return str(element)

        return None

    def _extract_date(self, soup: BeautifulSoup, prop: str) -> Optional[str]:
        """Extract date/time from itemProp or time elements"""
        # Try itemProp first
        element = soup.select_one(f'[itemProp="{prop}"]')
        if element:
            datetime_attr = element.get('datetime') or element.get('content')
            if datetime_attr:
                return datetime_attr

        # Try time elements
        time_elements = soup.select('time')
        for time_el in time_elements:
            dt = time_el.get('datetime')
            if dt:
                return dt

        return None

    def _extract_location(self, soup: BeautifulSoup) -> Dict:
        """Extract location information"""
        location = {
            'type': 'unknown',
            'name': None,
            'address': None,
            'url': None
        }

        # Look for online event indicators
        online_keywords = ['online', 'zoom', 'virtual', 'youtube', 'livestream']
        text_content = soup.get_text().lower()

        if any(keyword in text_content for keyword in online_keywords):
            location['type'] = 'online'

            # Try to find meeting URL
            for link in soup.select('a[href*="zoom"], a[href*="youtube"], a[href*="meet"]'):
                location['url'] = link.get('href')
                break

        # Look for location elements
        location_selectors = [
            '[itemProp="location"]',
            '[class*="venueDisplay"]',
            '[class*="event-venue"]'
        ]

        for selector in location_selectors:
            element = soup.select_one(selector)
            if element:
                location['name'] = element.get_text(strip=True)
                if 'online' not in location['name'].lower():
                    location['type'] = 'physical'
                break

        return location

    def _extract_attendee_count(self, soup: BeautifulSoup) -> Optional[int]:
        """Extract number of attendees/RSVPs"""
        # Look for attendee count in various places
        patterns = [
            r'(\d+)\s+(?:attendees|going|members?)',
            r'(\d+)\s+(?:RSVPs?|rsvps?)'
        ]

        text = soup.get_text()
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def _extract_photos(self, soup: BeautifulSoup) -> List[str]:
        """Extract event photo URLs"""
        photos = []

        # Look for Meetup's image hosting domains
        for img in soup.select('img'):
            src = img.get('src', '')
            if any(domain in src for domain in ['secure.meetupstatic.com', 'meetupstatic.com']):
                # Get highest quality version
                photos.append(src)

        return list(set(photos))  # Remove duplicates

    def download_photo(self, photo_url: str, save_path: str) -> bool:
        """
        Download event photo to disk

        Args:
            photo_url: URL of photo to download
            save_path: Path where photo should be saved

        Returns:
            True if successful, False otherwise
        """
        try:
            response = self.session.get(photo_url, timeout=30)
            response.raise_for_status()

            with open(save_path, 'wb') as f:
                f.write(response.content)

            print(f"Downloaded photo: {save_path}")
            return True

        except Exception as e:
            print(f"Error downloading photo {photo_url}: {e}")
            return False


def parse_cookies_from_request_file(filepath: str = '../../request.txt') -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Parse cookies and headers from exported request file

    Args:
        filepath: Path to request.txt file

    Returns:
        Tuple of (cookies_dict, headers_dict)
    """
    script_dir = Path(__file__).parent
    request_file = script_dir / filepath

    if not request_file.exists():
        raise FileNotFoundError(
            f"request.txt not found at {request_file}. "
            "Please export your browser request headers to this file."
        )

    cookies = {}
    headers = {}

    with open(request_file, 'r') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines and pseudo-headers
        if not line or line.startswith(':'):
            i += 1
            continue

        # Check if this is a header line (has value on next line)
        if i + 1 < len(lines):
            header_name = line
            header_value = lines[i + 1].strip()

            # Skip if next line looks like another header name (not a value)
            if not header_value or header_value.startswith(':'):
                i += 1
                continue

            # Special handling for cookie header
            if header_name.lower() == 'cookie':
                # Parse cookie string
                cookie_pairs = header_value.split('; ')
                for pair in cookie_pairs:
                    if '=' in pair:
                        key, value = pair.split('=', 1)
                        cookies[key.strip()] = value.strip()
                i += 2
            # Only add valid header names (alphanumeric with dashes)
            elif re.match(r'^[a-zA-Z0-9\-]+$', header_name):
                # Normalize header name for requests library
                header_name_normalized = header_name.replace('_', '-')
                headers[header_name_normalized] = header_value
                i += 2
            else:
                i += 1
        else:
            i += 1

    # Ensure essential headers are present
    if 'user-agent' not in headers and 'User-Agent' not in headers:
        headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'

    print(f"Parsed {len(cookies)} cookies and {len(headers)} headers")
    return cookies, headers


def convert_meetup_html_to_markdown(html_content: Optional[str]) -> str:
    """
    Convert Meetup event description HTML to clean markdown

    Args:
        html_content: HTML string from event description

    Returns:
        Markdown formatted string
    """
    if not html_content:
        return ""

    # Initialize html2text converter
    h = html2text.HTML2Text()
    h.body_width = 0  # Don't wrap text
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False

    # Convert to markdown
    markdown = h.handle(html_content)

    # Clean up excessive whitespace
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    markdown = markdown.strip()

    return markdown


def generate_event_markdown(event_data: Dict, images_relative_path: str = '../images') -> str:
    """
    Generate markdown for a single event matching tab_pastevents.md format

    Args:
        event_data: Dictionary containing event details
        images_relative_path: Relative path to images directory for markdown links

    Returns:
        Markdown formatted string for the event
    """
    lines = []
    lines.append("---")
    lines.append("")

    # Date/Time
    if event_data.get('start_date'):
        try:
            start_dt = date_parser.parse(event_data['start_date'])

            # Format date/time string
            date_str = start_dt.strftime("%B %d, %Y, %I:%M %p")

            if event_data.get('end_date'):
                end_dt = date_parser.parse(event_data['end_date'])
                date_str += f" to {end_dt.strftime('%I:%M %p')}"

            # Add timezone
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

    # Photos
    if event_data.get('photo_files'):
        for photo_file in event_data['photo_files']:
            photo_path = f"{images_relative_path}/{photo_file}"
            lines.append(f"![Event Photo]({photo_path})")
            lines.append("")

    return '\n'.join(lines)


def main():
    """Main scraper execution"""
    print("=" * 60)
    print("OWASP Toronto Meetup Event Scraper")
    print("=" * 60)
    print()

    # Parse cookies and headers
    print("Step 1: Parsing authentication from request.txt...")
    try:
        cookies, headers = parse_cookies_from_request_file()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return

    # Initialize scraper
    print("\nStep 2: Initializing scraper...")
    scraper = MeetupScraper(cookies, headers)

    # Fetch past events
    print("\nStep 3: Fetching past events list...")
    group_urlname = "owasp-toronto"

    try:
        html = scraper.get_past_events_page(group_urlname)

        # Debug: Save HTML to inspect
        debug_path = Path(__file__).parent / "../../archive/meetup-events/debug-page.html"
        with open(debug_path, 'w') as f:
            f.write(html)
        print(f"Saved HTML to {debug_path} for inspection")

        events = scraper.parse_event_list(html)
    except Exception as e:
        print(f"ERROR: {e}")
        return

    if not events:
        print("No events found!")
        return

    print(f"\nFound {len(events)} events to scrape")

    # Process events (they already have full details from Apollo state)
    print("\nStep 4: Processing events and downloading photos...")
    all_events = []

    for i, event in enumerate(events, 1):
        print(f"\nEvent {i}/{len(events)}: {event.get('title', 'Unknown')}")

        # Download featured photo if available
        downloaded_photos = []
        if event.get('featured_photo_url'):
            print(f"  Downloading featured photo...")
            filename = f"{event['event_id']}-featured.jpg"
            save_path = f"../../archive/meetup-events/images/{filename}"

            # Make path relative to script directory
            script_dir = Path(__file__).parent
            full_path = script_dir / save_path

            if scraper.download_photo(event['featured_photo_url'], str(full_path)):
                downloaded_photos.append(filename)

        event['photo_files'] = downloaded_photos

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

        # Be polite with rate limiting for photo downloads
        if downloaded_photos:
            time.sleep(1)

    # Save JSON output
    print("\nStep 5: Saving JSON output...")
    script_dir = Path(__file__).parent
    json_path = script_dir / "../../archive/meetup-events/all-events.json"

    with open(json_path, 'w') as f:
        json.dump(all_events, f, indent=2, default=str)

    print(f"Saved to: {json_path}")

    # Generate markdown files by year
    print("\nStep 6: Generating markdown files...")
    events_by_year = {}

    for event in all_events:
        if event.get('start_date'):
            try:
                dt = date_parser.parse(event['start_date'])
                year = dt.year

                if year not in events_by_year:
                    events_by_year[year] = []

                events_by_year[year].append(event)
            except:
                pass

    # Generate markdown file for each year
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
            event_md = generate_event_markdown(event)
            markdown_lines.append(event_md)

        # Save year file
        md_path = script_dir / f"../../archive/meetup-events/events-{year}.md"
        with open(md_path, 'w') as f:
            f.write('\n'.join(markdown_lines))

        print(f"Generated: {md_path} ({len(year_events)} events)")

    # Print summary
    print("\n" + "=" * 60)
    print("SCRAPING COMPLETE!")
    print("=" * 60)
    print(f"Total events scraped: {len(all_events)}")
    print(f"Years covered: {sorted(events_by_year.keys())}")
    print(f"\nOutput location: {script_dir / '../archive/meetup-events/'}")
    print("\nFiles generated:")
    print("  - all-events.json (raw data)")
    for year in sorted(events_by_year.keys()):
        print(f"  - events-{year}.md ({len(events_by_year[year])} events)")
    print()


if __name__ == '__main__':
    main()
