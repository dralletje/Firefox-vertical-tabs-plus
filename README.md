# New Tab Opener: First Position (fork)

Moves new Firefox tabs to the start of the tab bar (top for vertical tabs, left
for horizontal), but only when Firefox has no better position for them.

**Sticky section:** tab groups directly below the pinned tabs stay above new
tabs. New tabs open right after the last of those groups. A group further
down (anything after an ungrouped tab) doesn't count.

With sticky groups, a new tab briefly goes to the very top (above the groups)
before dropping below them. That makes Firefox scroll the vertical tab list up
instead of sliding it to the bottom.

| How the tab was opened                         | Where it ends up                    |
| ---------------------------------------------- | ----------------------------------- |
| Link opened in new tab (middle-click, etc.)    | Next to the page it came from (unchanged) |
| Link opened from a pinned tab                  | Top, below the sticky groups (newest on top) |
| Link opened from the first sticky group        | Top, below the sticky groups (newest on top) |
| New tab button / Ctrl+T                        | Top, after pinned tabs and sticky groups |
| Link from another application                  | Top, after pinned tabs and sticky groups |
| "New Tab in Group"                              | In that group (unchanged)           |
| Undo close tab                                 | Its original position (unchanged)   |

Rule: a tab is moved only if it has no opener tab, isn't in a group, **and**
Firefox appended it at the end of the window. Or, if it was opened from a pinned
tab and Firefox put it above the sticky groups, or opened from the first sticky
group and Firefox put it inside that group. Only new tabs are moved: tabs
you move yourself (e.g. above the groups) stay where you put them.

Based on [New Tab Opener: First Position](https://addons.mozilla.org/firefox/addon/new-tab-opener-first-position/)
v1.1 by Jan Pittner (Apache-2.0, see `extension/LICENSE`). Changes: skip tabs that have
an opener or weren't appended at the end, drop the unnecessary `tabs`
permission and the 50 ms delay, fix the data-collection manifest key, new
add-on ID so it doesn't collide with the original, removed the unused
`userChrome.css`.

## Install

- Temporary: `about:debugging` → This Firefox → Load Temporary Add-on → `extension/manifest.json`
- Permanent: sign it via AMO (unlisted) or use Developer Edition/Nightly with
  `xpinstall.signatures.required = false` and install the `.xpi`.

## Build & test

- `./build.sh` → `new-tab-first-position-<version>.xpi` (contents of `extension/`)
- `./test/run.sh` → end-to-end tests in headless Firefox (Docker)
