# How the Scene site works (checked 2026-11-04)

Each branch has its own subdomain, e.g. `cfc.scenecinemas.com` and `district5.scenecinemas.com`. The pages are plain HTML and answer the bot's honest User-Agent with HTTP 200, from home and from GitHub's servers alike. Saved copies are in `tests/fixtures/scene/`. Files starting `synthetic_` are real pages edited to show a state not seen live.

| Question | Answer |
|---|---|
| Which films can be booked | The branch homepage links every bookable film (pre-sales included) as `/movie-details/<slug>.html`, with the title in the link's `title` attribute. A film with several format groups can have several slugs, e.g. `avengers-doomsday-infinity-vision-sx-4dx`. |
| Which dates are on sale | The movie page lists them as `<li class="calanderdays" id="data-DD-MM-YYYY">`. |
| Showtimes for one date | `GET <movie page>?business_day=DD-MM-YYYY&ajax=1`, the same request the page's own JavaScript makes. It returns `div.program_item`, then one `div.ex_<kind>_content` per format with a `span.ex_<kind>` label ("ScreenX", "IMAX", "Standard & Deluxe"), then the time links. |
| Bookable showtime | A link to `https://<branch>.scenecinemas.com/showtime-<hex id>`. That's the booking page. |
| Nothing on sale | The date isn't in the list. A film with no dates shows the site's own "There is no showtimes" notice, which is otherwise hidden with `display:none`. |
| Right date? | The plain movie page shows times for whichever date is *selected*, not today. The bot always asks for the exact date and only trusts dates that are in the list. |
| Sold out | Not seen yet. A time without a booking link is treated as not bookable. |

**OPEN** means the date is in the list and that date's showtimes have at least one booking link. **CLOSED** means the film isn't on the homepage, or the date isn't in its list. Anything else is **ERROR**: a failed request, a redirect, an empty or unfamiliar page, or a showtimes page for another branch.

## Why only Scene

- **Vox** (`egy.voxcinemas.com`) sits behind Akamai Bot Manager, which drops every request that isn't a full browser.
- **Premiere** (`premiere-cinemas.com`) loads its showtimes from an API that answers bots with 403 "You are not authorized", and blocks GitHub's servers outright.

Getting past either would mean disguising the bot, which this project doesn't do.
