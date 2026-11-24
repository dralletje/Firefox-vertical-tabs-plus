"""
End-to-end test: loads the extension into headless Firefox, opens tabs in the
different ways a user would, and checks where they end up.

Run from the repo root:  ./test/run.sh
"""

import http.server
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile

from selenium import webdriver
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.mouse_button import MouseButton
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

EXTENSION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension")
PORT = 8765
SETTLE = 0.8  # seconds to let Firefox + the extension finish moving tabs


# --- tiny local site with links to click -----------------------------------

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        name = self.path.lstrip("/").split("?")[0] or "page"
        body = (
            f"<title>{name}</title><h1>{name}</h1>"
            f'<p><a id="link" href="/child-of-{name}">plain link</a></p>'
            f'<p><a id="blank" href="/blank-from-{name}" target="_blank">target=_blank</a></p>'
            f'<p><a id="blank_mid" href="/mid-from-{name}">second link</a></p>'
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def url(name):
    return f"http://localhost:{PORT}/{name}"


# --- helpers ----------------------------------------------------------------

def build_xpi(path):
    with zipfile.ZipFile(path, "w") as z:
        for dirpath, _, files in os.walk(EXTENSION):
            for f in files:
                full = os.path.join(dirpath, f)
                z.write(full, os.path.relpath(full, EXTENSION))


def chrome(driver, script, *args):
    with driver.context(driver.CONTEXT_CHROME):
        return driver.execute_script(script, *args)


def tab_names(driver):
    """Page names of all tabs in tab-strip order.

    '*a' = pinned tab a, 'S:a' = tab a in group S, 'new' = new tab page.
    """
    return chrome(driver, """
        return gBrowser.tabs.map(t => {
            const spec = t.linkedBrowser.currentURI.spec;
            let name = spec.startsWith('http') ? new URL(spec).pathname.slice(1) : spec;
            if (name === 'about:newtab' || name === 'about:home') name = 'new';
            return (t.pinned ? '*' : '') + (t.group ? t.group.label + ':' : '') + name;
        });
    """)


def wait_loaded(driver, n):
    """Wait until there are n tabs and none is still about:blank/loading."""
    deadline = time.time() + 10
    while time.time() < deadline:
        names = tab_names(driver)
        if len(names) == n and not any(x.endswith(("about:blank", ":")) or not x for x in names):
            break
        time.sleep(0.1)
    time.sleep(SETTLE)


def reset(driver, layout, pinned=0, collapsed=()):
    """Close everything and open tabs in the given layout.

    layout uses the same notation as tab_names(): "S:x" puts tab x in group S
    (consecutive entries with the same label form one group). The first
    `pinned` tabs are pinned; group labels in `collapsed` are collapsed.
    """
    names = [n.split(":")[-1] for n in layout]
    chrome(driver, """
        const [urls, pinned] = arguments;
        const first = gBrowser.addTrustedTab('about:blank');
        for (const t of [...gBrowser.tabs]) if (t !== first) gBrowser.removeTab(t, {animate: false});
        first.linkedBrowser.loadURI(Services.io.newURI(urls[0]),
            {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});
        // Insert at explicit indexes so the extension doesn't move these setup tabs.
        urls.slice(1).forEach((u, i) => gBrowser.addTrustedTab(u, {index: i + 1, relatedToCurrent: false}));
        for (let i = 0; i < pinned; i++) gBrowser.pinTab(gBrowser.tabs[i]);
    """, [url(n) for n in names], pinned)
    wait_loaded(driver, len(names))
    # Setup tabs past the first are created at the end and may be moved by the
    # extension, so rebuild order explicitly.
    chrome(driver, """
        const order = arguments[0];
        order.forEach((name, i) => {
            const t = gBrowser.tabs.find(t => t.linkedBrowser.currentURI.spec.endsWith('/' + name));
            gBrowser.moveTabTo(t, {tabIndex: i});
        });
    """, names)
    chrome(driver, """
        const [layout, collapsed] = arguments;
        const tabFor = name => gBrowser.tabs.find(t => t.linkedBrowser.currentURI.spec.endsWith('/' + name));
        const groups = new Map();
        for (const entry of layout) {
            const i = entry.lastIndexOf(':');
            if (i < 0) continue;
            const label = entry.slice(0, i);
            if (!groups.has(label)) groups.set(label, []);
            groups.get(label).push(tabFor(entry.slice(i + 1)));
        }
        for (const [label, tabs] of groups) {
            const g = gBrowser.addTabGroup(tabs, {label, color: 'blue', insertBefore: tabs[0]});
            if (collapsed.includes(label)) g.collapsed = true;
        }
    """, layout, list(collapsed))
    time.sleep(0.2)
    actual = tab_names(driver)
    expected = [("*" + n if i < pinned else n) for i, n in enumerate(layout)]
    assert actual == expected, f"setup failed: {actual} != {expected}"


def select(driver, name):
    name = name.split(":")[-1]
    chrome(driver, """
        const t = gBrowser.tabs.find(t => t.linkedBrowser.currentURI.spec.endsWith('/' + arguments[0]));
        gBrowser.selectedTab = t;
    """, name)
    # Point WebDriver at the selected tab's content.
    handles = driver.window_handles
    for h in handles:
        driver.switch_to.window(h)
        if driver.current_url.endswith("/" + name):
            return
    raise RuntimeError(f"no handle for {name}")


def middle_click(driver, elem_id):
    el = driver.find_element(By.ID, elem_id)
    ab = ActionBuilder(driver)
    ab.pointer_action.move_to(el).pointer_down(MouseButton.MIDDLE).pointer_up(MouseButton.MIDDLE)
    ab.perform()


# --- scenarios ----------------------------------------------------------------

def scenario_new_tab_button(d):
    reset(d, ["a", "b", "c"])
    select(d, "b")
    chrome(d, "gBrowser.tabContainer.newTabButton.click();")
    time.sleep(SETTLE)
    names = tab_names(d)
    return names, names == ["new", "a", "b", "c"]


def scenario_ctrl_t(d):
    reset(d, ["a", "b", "c"], pinned=1)
    select(d, "b")
    chrome(d, "document.getElementById('cmd_newNavigatorTab').doCommand();")
    time.sleep(SETTLE)
    names = tab_names(d)
    return names, names == ["*a", "new", "b", "c"]


def scenario_middle_click_middle_tab(d):
    reset(d, ["a", "b", "c"])
    select(d, "b")
    middle_click(d, "link")
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["a", "b", "child-of-b", "c"]


def scenario_middle_click_last_tab(d):
    reset(d, ["a", "b", "c"])
    select(d, "c")
    middle_click(d, "link")
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["a", "b", "c", "child-of-c"]


def scenario_target_blank_last_tab(d):
    reset(d, ["a", "b", "c"])
    select(d, "c")
    d.find_element(By.ID, "blank").click()
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["a", "b", "c", "blank-from-c"]


def scenario_external_link(d):
    reset(d, ["a", "b", "c"], pinned=1)
    select(d, "b")
    # Same code path as `firefox --new-tab URL` from another application.
    chrome(d, """
        window.browserDOMWindow.openURI(
            Services.io.newURI(arguments[0]), null,
            Ci.nsIBrowserDOMWindow.OPEN_NEWTAB, Ci.nsIBrowserDOMWindow.OPEN_EXTERNAL,
            Services.scriptSecurityManager.getSystemPrincipal());
    """, url("external"))
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["*a", "external", "b", "c"]


def scenario_undo_close_middle(d):
    reset(d, ["a", "b", "c", "d"])
    select(d, "b")
    chrome(d, "gBrowser.removeTab(gBrowser.selectedTab, {animate: false});")
    time.sleep(SETTLE)
    chrome(d, "SessionStore.undoCloseTab(window, 0);")
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["a", "b", "c", "d"]


# --- sticky groups at the top -------------------------------------------------

def new_tab_button(d):
    chrome(d, "gBrowser.tabContainer.newTabButton.click();")
    wait_loaded(d, len(tab_names(d)))
    return tab_names(d)


def ctrl_t(d):
    chrome(d, "document.getElementById('cmd_newNavigatorTab').doCommand();")
    wait_loaded(d, len(tab_names(d)))
    return tab_names(d)


def scenario_group_top_ctrl_t(d):
    reset(d, ["S:s1", "S:s2", "a", "b"])
    select(d, "b")
    names = ctrl_t(d)
    return names, names == ["S:s1", "S:s2", "new", "a", "b"]


def scenario_group_top_ctrl_t_from_inside_group(d):
    reset(d, ["S:s1", "S:s2", "a", "b"])
    select(d, "s1")
    names = ctrl_t(d)
    return names, names == ["S:s1", "S:s2", "new", "a", "b"]


def scenario_pinned_and_two_groups(d):
    reset(d, ["p", "S:s1", "W:w1", "W:w2", "a"], pinned=1)
    select(d, "a")
    names = new_tab_button(d)
    return names, names == ["*p", "S:s1", "W:w1", "W:w2", "new", "a"]


def scenario_collapsed_group_top(d):
    reset(d, ["S:s1", "S:s2", "a"], collapsed=["S"])
    select(d, "a")
    names = ctrl_t(d)
    return names, names == ["S:s1", "S:s2", "new", "a"]


def scenario_group_lower_down_ignored(d):
    reset(d, ["a", "L:l1", "L:l2", "b"])
    select(d, "b")
    names = ctrl_t(d)
    return names, names == ["new", "a", "L:l1", "L:l2", "b"]


def scenario_only_groups(d):
    reset(d, ["S:s1", "W:w1"])
    select(d, "w1")
    names = ctrl_t(d)
    return names, names == ["S:s1", "W:w1", "new"]


def scenario_external_link_group_top(d):
    reset(d, ["S:s1", "a", "b"])
    select(d, "b")
    chrome(d, """
        window.browserDOMWindow.openURI(
            Services.io.newURI(arguments[0]), null,
            Ci.nsIBrowserDOMWindow.OPEN_NEWTAB, Ci.nsIBrowserDOMWindow.OPEN_EXTERNAL,
            Services.scriptSecurityManager.getSystemPrincipal());
    """, url("external"))
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["S:s1", "external", "a", "b"]


def scenario_link_from_sticky_tab(d):
    reset(d, ["S:s1", "S:s2", "a"])
    select(d, "s1")
    middle_click(d, "link")
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["S:s1", "S:s2", "child-of-s1", "a"]


def scenario_two_links_from_sticky_tab(d):
    reset(d, ["S:s1", "S:s2", "a"])
    select(d, "s1")
    middle_click(d, "link")
    wait_loaded(d, 4)
    middle_click(d, "blank_mid")
    wait_loaded(d, 5)
    names = tab_names(d)
    return names, names == ["S:s1", "S:s2", "mid-from-s1", "child-of-s1", "a"]


def scenario_link_from_first_of_stacked_groups(d):
    reset(d, ["S:s1", "W:w1", "a"])
    select(d, "s1")
    middle_click(d, "link")
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["S:s1", "W:w1", "child-of-s1", "a"]


def scenario_link_from_second_sticky_group(d):
    reset(d, ["S:s1", "W:w1", "W:w2", "a"])
    select(d, "w1")
    middle_click(d, "link")
    wait_loaded(d, 5)
    names = tab_names(d)
    return names, names == ["S:s1", "W:w1", "W:child-of-w1", "W:w2", "a"]


def scenario_link_from_first_group_not_at_top(d):
    reset(d, ["a", "L:l1", "L:l2"])
    select(d, "l1")
    middle_click(d, "link")
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["a", "L:l1", "L:child-of-l1", "L:l2"]


def scenario_new_tab_in_sticky_group(d):
    reset(d, ["S:s1", "S:s2", "a"])
    select(d, "a")
    chrome(d, """
        const group = gBrowser.tabs[0].group;
        const onOpen = e => { group.addTabs([e.target]); window.removeEventListener('TabOpen', onOpen); };
        window.addEventListener('TabOpen', onOpen);
        gBrowser.addAdjacentNewTab(group.tabs.at(-1));
    """)
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["S:s1", "S:s2", "S:new", "a"]


def scenario_new_tab_in_group_at_end(d):
    reset(d, ["a", "L:l1", "L:l2"])
    select(d, "a")
    # Same steps as the group menu's "New Tab in Group".
    chrome(d, """
        const group = gBrowser.tabs.at(-1).group;
        const onOpen = e => { group.addTabs([e.target]); window.removeEventListener('TabOpen', onOpen); };
        window.addEventListener('TabOpen', onOpen);
        gBrowser.addAdjacentNewTab(group.tabs.at(-1));
    """)
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["a", "L:l1", "L:l2", "L:new"]


def scenario_link_from_pinned_tab(d):
    reset(d, ["p", "S:s1", "S:s2", "a"], pinned=1)
    select(d, "p")
    middle_click(d, "link")
    wait_loaded(d, 5)
    names = tab_names(d)
    return names, names == ["*p", "S:s1", "S:s2", "child-of-p", "a"]


def scenario_two_links_from_pinned_tab(d):
    reset(d, ["p", "S:s1", "a"], pinned=1)
    select(d, "p")
    middle_click(d, "link")
    wait_loaded(d, 4)
    middle_click(d, "blank_mid")
    wait_loaded(d, 5)
    names = tab_names(d)
    return names, names == ["*p", "S:s1", "mid-from-p", "child-of-p", "a"]


def scenario_link_from_pinned_no_groups(d):
    reset(d, ["p", "a", "b"], pinned=1)
    select(d, "p")
    middle_click(d, "link")
    wait_loaded(d, 4)
    names = tab_names(d)
    return names, names == ["*p", "child-of-p", "a", "b"]


def scenario_manual_move_above_group(d):
    reset(d, ["S:s1", "a", "b"])
    chrome(d, """
        const b = gBrowser.tabs.find(t => t.linkedBrowser.currentURI.spec.endsWith('/b'));
        gBrowser.moveTabTo(b, {tabIndex: 0, forceUngrouped: true});
    """)
    time.sleep(SETTLE)
    names = tab_names(d)
    return names, names == ["b", "S:s1", "a"]

SCENARIOS = [
    ("New tab button -> first", scenario_new_tab_button),
    ("Ctrl+T -> first unpinned (1 pinned tab)", scenario_ctrl_t),
    ("Middle-click link in middle tab -> next to opener", scenario_middle_click_middle_tab),
    ("Middle-click link in LAST tab -> next to opener (stays last)", scenario_middle_click_last_tab),
    ("target=_blank link in last tab -> next to opener", scenario_target_blank_last_tab),
    ("External link -> first unpinned (1 pinned tab)", scenario_external_link),
    ("Undo close tab (middle) -> original position", scenario_undo_close_middle),
    ("Sticky group: Ctrl+T -> after the group", scenario_group_top_ctrl_t),
    ("Sticky group: Ctrl+T from a tab inside it -> after the group", scenario_group_top_ctrl_t_from_inside_group),
    ("Pinned + two stacked groups: new tab button -> after both", scenario_pinned_and_two_groups),
    ("Collapsed sticky group -> after the group", scenario_collapsed_group_top),
    ("Group further down -> ignored, new tab first", scenario_group_lower_down_ignored),
    ("Only groups -> stays at end, ungrouped", scenario_only_groups),
    ("Sticky group: external link -> after the group", scenario_external_link_group_top),
    ("Link from first sticky group -> out of the group, below it", scenario_link_from_sticky_tab),
    ("Two links from first sticky group -> below it, newest on top", scenario_two_links_from_sticky_tab),
    ("Link from first of two stacked groups -> below both", scenario_link_from_first_of_stacked_groups),
    ("Link from second sticky group -> stays in that group (Firefox default)", scenario_link_from_second_sticky_group),
    ("Link from first group when it isn't at the top -> stays in group", scenario_link_from_first_group_not_at_top),
    ("'New tab in group' on sticky group -> stays in group", scenario_new_tab_in_sticky_group),
    ("'New tab in group' on last group -> stays in group", scenario_new_tab_in_group_at_end),
    ("Link from pinned tab -> below sticky group", scenario_link_from_pinned_tab),
    ("Two links from pinned tab -> below sticky group, newest on top", scenario_two_links_from_pinned_tab),
    ("Link from pinned tab, no groups -> right after pinned", scenario_link_from_pinned_no_groups),
    ("Manually moving a tab above the sticky group -> stays there", scenario_manual_move_above_group),
]


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    tmp = tempfile.mkdtemp()
    xpi = os.path.join(tmp, "ext.xpi")
    build_xpi(xpi)

    opts = Options()
    opts.binary_location = shutil.which("firefox-esr") or shutil.which("firefox")
    opts.add_argument("-headless")
    opts.set_preference("browser.startup.homepage_override.mstone", "ignore")
    opts.set_preference("browser.tabs.warnOnClose", False)
    d = webdriver.Firefox(options=opts, service=Service(shutil.which("geckodriver"), service_args=["--allow-system-access"]))  # chrome context
    failures = 0
    try:
        print("Firefox", d.capabilities.get("browserVersion"))
        d.install_addon(xpi, temporary=True)
        time.sleep(1)
        for name, fn in SCENARIOS:
            try:
                names, ok = fn(d)
            except Exception as e:  # noqa: BLE001
                names, ok = f"ERROR: {e!r}", False
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {name}\n      tabs: {names}")
    finally:
        d.quit()
        server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(SCENARIOS) - failures}/{len(SCENARIOS)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
