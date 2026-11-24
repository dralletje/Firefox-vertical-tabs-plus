/**
 * Moves newly created tabs to the top of the tab list, but only when Firefox
 * had no better place for them.
 *
 * Firefox already puts tabs in a sensible spot when it knows where they came
 * from (e.g. links opened in a new tab land next to the page that opened them).
 * Only tabs that got the "don't know, append at the end" treatment are moved:
 * the new tab button / Ctrl+T, links opened from other applications, etc.
 *
 * "Top" means right after the pinned tabs and any tab groups directly below
 * them, so groups at the top act as a sticky section.
 */

// Firefox starts a smooth scroll down to a new tab at the end of the list. If
// the tab's final spot below the sticky groups is already in view, moving it
// there doesn't scroll, and the list keeps sliding to the bottom. So we first
// move the tab to the very top, which is out of view by then: Firefox snaps
// the list up, which cancels the slide. After this pause (so that scroll
// happens first) the tab moves to its final spot.
const PAUSE_BEFORE_FINAL_MOVE_MS = 32;

// Moving a tab to where a group starts or ends puts it inside the group.
// Ungrouping straight away puts it just above/below the group instead. Both
// calls are sent back to back so Firefox usually handles them in one frame.
function moveOutsideGroups(tabId, index) {
  return Promise.all([
    browser.tabs.move(tabId, { index }),
    browser.tabs.ungroup(tabId),
  ]);
}

browser.tabs.onCreated.addListener(async (created) => {
  try {
    const tabs = await browser.tabs.query({ windowId: created.windowId });
    const tab = tabs.find((t) => t.id === created.id);
    if (!tab) return;

    // Positions are computed among the other tabs, so they are also the
    // index the new tab ends up at when moved there.
    const others = tabs.filter((t) => t.id !== tab.id);
    const top = others.filter((t) => t.pinned).length;
    let belowGroups = top; // first position after the sticky groups
    while (belowGroups < others.length && others[belowGroups].groupId !== -1) belowGroups++;

    if (tab.openerTabId !== undefined) {
      // Opened from another tab (link, middle-click, duplicate, window.open):
      // Firefox placed it next to its opener, so leave it alone. Except:
      // - From a pinned tab: Firefox puts it right after the pinned tabs,
      //   above the sticky groups.
      // - From the first sticky group: Firefox puts it inside that group.
      // Those go to the top below the sticky groups instead (the newest on top).
      const opener = tabs.find((t) => t.id === tab.openerTabId);
      if (!opener) return;
      const fromPinned = opener.pinned && tab.index < belowGroups;
      const firstStickyGroup = top < belowGroups ? others[top].groupId : -1;
      const fromFirstStickyGroup =
        firstStickyGroup !== -1 &&
        opener.groupId === firstStickyGroup &&
        tab.groupId === firstStickyGroup;
      if (fromPinned || fromFirstStickyGroup) {
        await moveOutsideGroups(tab.id, belowGroups);
      }
      return;
    }

    // Anywhere other than the end means Firefox chose a deliberate spot
    // (e.g. undo close tab restoring it to its old position). A tab that is
    // already in a group was put there on purpose ("New tab in group").
    if (tab.index !== tabs.length - 1 || tab.groupId !== -1) return;
    if (belowGroups === tab.index) return; // nothing but groups: stay at the end

    await moveOutsideGroups(tab.id, top);
    if (belowGroups !== top) {
      await new Promise((resolve) => setTimeout(resolve, PAUSE_BEFORE_FINAL_MOVE_MS));
      await moveOutsideGroups(tab.id, belowGroups);
    }
  } catch (e) {
    console.error("Failed to move new tab:", e);
  }
});
