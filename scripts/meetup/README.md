# Meetup Event Scraper

Scrapes past events from OWASP Toronto's Meetup page and generates markdown files matching the existing `tab_pastevents.md` format.

## Setup

### 1. Install Dependencies

This project uses [uv](https://github.com/astral-sh/uv) for dependency management.

```bash
cd scripts/meetup/
uv sync
```

### 2. Export Browser Cookies

The scraper requires authentication cookies to access Meetup's past events:

1. Open your browser and log into Meetup.com
2. Navigate to https://www.meetup.com/owasp-toronto/
3. Open Developer Tools (F12)
4. Go to the Network tab
5. Refresh the page
6. Click on any request to www.meetup.com
7. Right-click → Copy → Copy as cURL (or export request headers)
8. Save the request headers to `/request.txt` in the repository root

The `request.txt` file should contain headers in this format:
```
:authority
www.meetup.com
:method
GET
cookie
MEETUP_BROWSER_ID=...; MEETUP_SESSION=...; __meetup_auth_access_token=...
user-agent
Mozilla/5.0 ...
```

## Usage

```bash
# From repository root
uv run scripts/meetup/scrape_meetup_events.py

# Or from scripts/meetup/ directory
cd scripts/meetup/
uv run scrape_meetup_events.py
```

The scraper will:
1. Parse cookies from `request.txt`
2. Fetch the past events page
3. Extract event data from embedded JSON (Apollo/Next.js state)
4. Download featured photos (if available)
5. Generate markdown files organized by year
6. Save raw JSON data for reference

## Output

Files are generated in `/archive/meetup-events/`:

- `all-events.json` - Raw event data in JSON format
- `events-YYYY.md` - Markdown files organized by year (e.g., `events-2025.md`)
- `images/` - Downloaded event photos

## Current Limitations

### Pagination
The scraper currently only fetches events visible on the first page load (~10 most recent past events). Meetup uses infinite scroll to load older events dynamically.

**To scrape all historical events**, you would need to either:
- Use browser automation (Selenium/Playwright) to scroll and trigger additional loads
- Reverse-engineer Meetup's GraphQL pagination API

### Photo Downloads
Featured event photos may have incomplete URLs in the Apollo state, resulting in 404 errors. This doesn't affect the core event data scraping.

### Cookie Expiration
Session cookies expire after a period of time. If you see authentication errors, re-export fresh cookies from your browser to `request.txt`.

## Troubleshooting

**"Authentication failed" errors:**
- Your cookies have expired
- Re-export cookies from a logged-in browser session

**"No events found":**
- Check that `request.txt` is in the correct format
- Ensure you're logged into Meetup.com when exporting cookies
- Try accessing https://www.meetup.com/owasp-toronto/events/past/ in your browser to verify access

**"Could not find __NEXT_DATA__":**
- Meetup's page structure has changed
- The scraper may need updating to match new HTML structure

## Integration with Repository

The generated markdown files can be manually merged into `tab_pastevents.md` or kept as a separate archive. The format matches the existing event structure for easy integration.

## Future Enhancements

Potential improvements for the scraper:

- **Pagination**: Implement scrolling/pagination to fetch all historical events
- **Photo handling**: Fix photo URL extraction or skip photos entirely
- **Incremental updates**: Only fetch events since last run
- **Speaker extraction**: Parse speaker/presenter info from descriptions using LLM
- **Video links**: Extract YouTube/recording links from event descriptions
- **Merge tool**: Automatically merge new events into `tab_pastevents.md`
