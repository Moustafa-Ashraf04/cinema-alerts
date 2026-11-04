# Discovery (2026-11-04)

Every request used `User-Agent: cinema-alert-bot (personal use)`, a 20 s timeout, and ran one at a time from a home connection in Cairo. Fixtures are in `tests/fixtures/<provider>/`. Per-session CSRF tokens are replaced with `REDACTED`.

## Scene Cinemas: usable

Each branch has its own subdomain: `cfc.scenecinemas.com` (Cairo Festival City) and `district5.scenecinemas.com`. The pages are plain server-rendered HTML (Laravel and jQuery, with Cloudflare in front). Every request returned HTTP 200 with no challenge page. The reCAPTCHA script on the page is only for the login and register forms.

| Question | Answer (evidence) |
|---|---|
| Movie list | `https://<branch>.scenecinemas.com/` lists "Now Showing" as links to `/movie-details/<slug>.html`, with the title in `<h1 class="title">`. Films on pre-sale are listed here with an "Advanced Booking" button (e.g. `dune-part-three.html`). `/next_releasing` ("Coming Soon") was empty on 2026-11-04 (`cfc_home_*`, `cfc_next_releasing_empty_*`). |
| Slugs | One page per film per format group, e.g. `avengers-doomsday-infinity-vision-sx-4dx.html` covers ScreenX and 4DX. A film can have several slugs, so the bot matches all slugs whose title matches. |
| Dates on sale | The movie page has a date strip of `<li class="calanderdays" id="data-DD-MM-YYYY">`, each wrapped in `javascript:LoadShowtimes('DD-MM-YYYY')`. Avengers at CFC and District 5: 16-12-2026 to 23-12-2026. |
| Showtimes for a date | `GET <movie page>?business_day=DD-MM-YYYY&ajax=1` returns an HTML fragment (the same request the page's own JavaScript makes). The fragment contains `div.program_item`, then `div.branch` (the branch name), then one `div.ex_<kind>_content` per format with a `span.ex_<kind>` label (`ex_imax` "ScreenX" or "IMAX", `ex_stand` "Standard" or "Standard & Deluxe"), then `ul li a[href]` (time text, e.g. "12:00 PM"). |
| Bookable showtime | `a[href^="https://<branch>.scenecinemas.com/showtime-<24 hex id>"]`. That URL is the booking link. |
| No showtimes | A date outside the strip gives an **empty 200 body** (`cfc_ajax_*_30-12-2026_empty.html`, 0 bytes). |
| Confirming the requested date | The plain movie page shows the *active* date (17-12 here, not today), so its embedded times must **not** be used. Fetch the `ajax=1` fragment for the exact date, and only trust it if that date is in the strip. |
| Sold out or disabled | Not seen yet: every showtime on 2026-11-04 was a normal link. Until a fixture shows the sold-out markup, a time without a `showtime-` link isn't counted as bookable. |

**OPEN / CLOSED / ERROR for Scene**
- OPEN: the movie page is recognised, the requested date is in the strip, and the fragment for that date has at least one `showtime-` link with a time.
- CLOSED: the branch homepage and Coming Soon page are recognised and the film isn't on them, **or** the movie page is recognised and the date isn't in the strip.
- ERROR: any non-200 response, an empty fragment for a date that *is* in the strip, a missing date strip or `#ShowtimesAjax`, or any other unrecognised page.

Cost per check is one request per branch for the homepage (shared by all watches), plus one per matching slug for the movie page, plus one fragment per watched date that's in the strip.

## Premiere Cinemas (1Premiere): blocked at the data API

- `www.premiere-cinemas.com` is a Next.js site (Cloudflare in front). The movie page `/en/movie-details/5180.855/1` returns HTTP 200, but **its HTML has no showtimes or cinema list** (`movie_5180.855_raw_*.html`).
- In a real browser the page loads its data from `https://mifcentral-api.premiere-cinemas.com/api/external/cinemas` and `/api/v1/hybrid/get-movie-show-dates/<movie id>?fromDate=YYYY-MM-DD&lang_id=1&cinema_id=<n>`.
- The bot calling those URLs directly gets **HTTP 403 `{"message":"You are not authorized"}`** (`api_show_dates_403.json`). The site's own JavaScript supplies an authorization of some kind that the bot doesn't have. Under the no-evasion rule we don't copy it.
- In the browser, Avengers: Doomsday was offered at Nile Cinema, Galaxy elManial and Premiere Point90, **not at Americana Plaza**, on 2026-11-04.
- Fallback looked at: elCinema's Premiere IMAX page (`elcinema.com/en/theater/3101134/`) is readable, plain HTML with showtimes and elCinema booking links. But its date selector covers only **7 days ahead** (04–10 Nov), so it can't show December pre-sales. It's too late to be useful for pre-booking alerts.

## GitHub runner probe (`probe.yml`, [run 41757507914](https://github.com/Moustafa-Ashraf04/cinema-alerts/actions/runs/41757507914))

| Check | Result from GitHub |
|---|---|
| Scene CFC home | HTTP 200, 65784 bytes, movie links present |
| Scene CFC Avengers page | HTTP 200, 54404 bytes, 23-12-2026 in the date strip |
| Scene CFC fragment, 23-12-2026 | HTTP 200, 1282 bytes, `showtime-` links present |
| Scene District 5 Avengers page | HTTP 200, 54250 bytes, 23-12-2026 in the date strip |
| Premiere movie page | **HTTP 403**, 4555 bytes (Cloudflare blocks GitHub's servers, even for the plain HTML) |

The Scene sizes match the local fetches byte for byte, so the content is the same from GitHub. Premiere is blocked from GitHub's servers as well as at the API.

## Vox Cinemas: parked

`egy.voxcinemas.com` is behind Akamai Bot Manager. Every honest non-browser request was dropped (HTTP/2 reset or a 0-byte timeout, the homepage included). In a browser the showtimes are server-rendered `a.action.showtime[href^="/booking/"]`, with dates as `?d=YYYYMMDD`. Vox stays parked until a polite source turns up. elCinema doesn't list Vox.
