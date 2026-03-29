#!/usr/bin/env python3
"""Gas Town City Dashboard — Textual TUI with tabs and incremental cache."""

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import (
    DataTable, Header, Static, Label, TabbedContent, TabPane,
)
from textual import work
from textual.worker import get_current_worker

CITY_ROOT = "/mnt/ext-fast/gc"
RIGS = {
    "reli": {"repo": "alexsiri7/reli", "path": f"{CITY_ROOT}/rigs/reli"},
    "annie": {"repo": "alexsiri7/word-coach-annie", "path": f"{CITY_ROOT}/rigs/annie"},
    "gascity": {"repo": "alexsiri7/gascity", "path": f"{CITY_ROOT}/rigs/gascity"},
}

AGENT_INTERVAL = 5
BEADS_INTERVAL = 15
DEPLOYS_INTERVAL = 30
ISSUES_INTERVAL = 60


# ── helpers ──────────────────────────────────────────────────────────────

def run(cmd, cwd=None, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           cwd=cwd, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def idle_str(secs):
    if secs < 0:
        return "?"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m{secs % 60:02d}s"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"


def extract_issue_nums(title):
    """Extract all issue numbers from a string (GH#NNN, #NNN, etc)."""
    return [int(m) for m in re.findall(r'(?:GH#|#)(\d+)', title)]


def extract_issue_num(title):
    nums = extract_issue_nums(title)
    return nums[0] if nums else None


# ── cache ────────────────────────────────────────────────────────────────

class DataCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._agents = []
        self._session_count = 0
        self._bead_titles = {}
        self._rig_data = {}
        self._timestamps = {}
        # Agent idle lookup: "reli/polecat-3" -> idle_seconds
        self._agent_idle = {}

    def _stale(self, key, interval):
        return time.time() - self._timestamps.get(key, 0) > interval

    def refresh_agents(self):
        if not self._stale("agents", AGENT_INTERVAL):
            return False

        now = time.time()
        tmux = {}
        out = run("tmux -L gc list-sessions -F '#{session_name} #{session_activity}'")
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    tmux[parts[0]] = int(now - int(parts[1]))
                except ValueError:
                    tmux[parts[0]] = -1

        if self._stale("gc_sessions", 15):
            gc_out = run("gc session list --json")
            if gc_out:
                try:
                    gc_sessions = json.loads(gc_out)
                    bead_titles = {}
                    for s in gc_sessions:
                        sn = s.get("SessionName", "")
                        if sn:
                            bead_titles[sn] = s.get("Title", sn)
                    with self._lock:
                        self._bead_titles = bead_titles
                except json.JSONDecodeError:
                    pass
            self._timestamps["gc_sessions"] = time.time()

        agents = []
        agent_idle = {}
        with self._lock:
            titles = self._bead_titles

        for name, idle in sorted(tmux.items()):
            display = titles.get(name, name) if name.startswith("s-gc-") else name
            if "--" in display:
                rig, role = display.split("--", 1)
            elif "/" in display:
                rig, role = display.split("/", 1)
            else:
                rig, role = "city", display
            agents.append({"rig": rig, "role": role, "idle": idle, "tmux": name})
            # Index for cross-referencing: "reli/polecat-1" -> idle
            agent_idle[f"{rig}/{role}"] = idle

        with self._lock:
            self._agents = agents
            self._session_count = len(tmux)
            self._agent_idle = agent_idle
            self._timestamps["agents"] = time.time()
        return True

    def refresh_beads(self, rig_name):
        key = f"beads_{rig_name}"
        if not self._stale(key, BEADS_INTERVAL):
            return False

        rig_info = RIGS[rig_name]
        out = run("bd list --json", cwd=rig_info["path"])
        all_beads = []
        if out:
            try:
                all_beads = json.loads(out)
            except json.JSONDecodeError:
                pass

        tasks = [b for b in all_beads if b.get("issue_type") == "task"]

        # Build rich mapping: issue_num -> {status, assignee, branch, bead_id}
        issue_map = {}  # issue_num -> bead info
        for b in tasks:
            nums = extract_issue_nums(b.get("title", ""))
            meta = b.get("metadata", {})
            info = {
                "bead_id": b["id"],
                "status": b.get("status", "open"),
                "assignee": b.get("assignee", ""),
                "branch": meta.get("branch", ""),
                "worktree": meta.get("worktree", ""),
            }
            for n in nums:
                # Prefer in_progress over open
                existing = issue_map.get(n)
                if not existing or info["status"] == "in_progress":
                    issue_map[n] = info

        with self._lock:
            rd = self._rig_data.setdefault(rig_name, {})
            rd["issue_map"] = issue_map
            self._timestamps[key] = time.time()
        return True

    def refresh_issues(self, rig_name):
        key = f"issues_{rig_name}"
        if not self._stale(key, ISSUES_INTERVAL):
            return False

        rig_info = RIGS[rig_name]
        issues = []
        out = run(
            f"gh issue list -R {rig_info['repo']} --state open --limit 50 "
            f"--json number,title --jq '[.[] | {{number, title}}]'",
            timeout=15,
        )
        if out:
            try:
                issues = json.loads(out)
            except json.JSONDecodeError:
                pass

        with self._lock:
            rd = self._rig_data.setdefault(rig_name, {})
            rd["issues"] = issues
            rd["repo"] = rig_info["repo"]
            self._timestamps[key] = time.time()
        return True

    def refresh_deploys(self, rig_name):
        key = f"deploys_{rig_name}"
        if not self._stale(key, DEPLOYS_INTERVAL):
            return False

        rig_info = RIGS[rig_name]
        deploys = []
        out = run('git log --oneline --since="6 hours ago" master', cwd=rig_info["path"])
        for line in (out or "").splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                deploys.append({"sha": parts[0], "msg": parts[1]})

        deployed = set()
        for d in deploys:
            for n in extract_issue_nums(d["msg"]):
                deployed.add(n)

        with self._lock:
            rd = self._rig_data.setdefault(rig_name, {})
            rd["deployed"] = deployed
            rd["deploy_count"] = len(deploys)
            self._timestamps[key] = time.time()
        return True

    def snapshot(self):
        with self._lock:
            return {
                "agents": list(self._agents),
                "agent_idle": dict(self._agent_idle),
                "rigs": {k: dict(v) for k, v in self._rig_data.items()},
                "session_count": self._session_count,
                "ts": datetime.now().strftime("%H:%M:%S"),
            }


# ── widgets ──────────────────────────────────────────────────────────────

class CityTab(Static):
    """City-wide overview: all agents."""

    def compose(self) -> ComposeResult:
        yield Label(" Agents ", id="city-header")
        yield DataTable(id="city-agent-table")
        yield Label("", id="city-summary")

    def on_mount(self) -> None:
        hdr = self.query_one("#city-header", Label)
        hdr.styles.text_style = "bold"
        hdr.styles.background = "darkblue"
        hdr.styles.width = "100%"

        table = self.query_one("#city-agent-table", DataTable)
        table.cursor_type = "none"
        table.zebra_stripes = True
        table.add_columns("Rig", "Role", "Idle", "Status")

    def update_data(self, data: dict) -> None:
        table = self.query_one("#city-agent-table", DataTable)
        table.clear()

        agents = data["agents"]
        active = 0
        stale = 0

        for a in agents:
            idle = a["idle"]
            if idle < 120:
                status = "[green]● active[/]"
                active += 1
            elif idle < 600:
                status = "[yellow]◐ idle[/]"
            else:
                status = "[red]○ stale[/]"
                stale += 1

            style = "green" if idle < 120 else ("yellow" if idle < 600 else "red")
            table.add_row(a["rig"], a["role"], f"[{style}]{idle_str(idle)}[/]", status)

        total = data["session_count"]
        idle_n = total - active - stale
        summary = self.query_one("#city-summary", Label)
        summary.update(
            f"  [bold]{total}[/] sessions  │  "
            f"[green]{active} active[/]  [yellow]{idle_n} idle[/]  [red]{stale} stale[/]"
        )


class RigTab(Static):
    """Per-rig view: agents + issues with real status."""

    def __init__(self, rig_name: str, **kwargs):
        super().__init__(**kwargs)
        self.rig_name = rig_name

    def compose(self) -> ComposeResult:
        yield Label(f" {self.rig_name} — agents ", id=f"rh-agents-{self.rig_name}")
        yield DataTable(id=f"rig-agents-{self.rig_name}")
        yield Label(f" {self.rig_name} — issues ", id=f"rh-issues-{self.rig_name}")
        yield DataTable(id=f"rig-issues-{self.rig_name}")

    def on_mount(self) -> None:
        for label_id in (f"rh-agents-{self.rig_name}", f"rh-issues-{self.rig_name}"):
            lbl = self.query_one(f"#{label_id}", Label)
            lbl.styles.text_style = "bold"
            lbl.styles.background = "darkblue"
            lbl.styles.width = "100%"

        at = self.query_one(f"#rig-agents-{self.rig_name}", DataTable)
        at.cursor_type = "none"
        at.zebra_stripes = True
        at.add_columns("Role", "Idle", "Status", "Working On")

        it = self.query_one(f"#rig-issues-{self.rig_name}", DataTable)
        it.cursor_type = "none"
        it.zebra_stripes = True
        it.add_columns("#", "Status", "Worker", "Title")

    def update_data(self, data: dict) -> None:
        agents = data["agents"]
        agent_idle = data["agent_idle"]
        rig_info = data["rigs"].get(self.rig_name, {})
        issue_map = rig_info.get("issue_map", {})
        issues = rig_info.get("issues", [])
        deployed = rig_info.get("deployed", set())
        deploy_count = rig_info.get("deploy_count", 0)

        # ── agents table ─────────────────────────────────────────────
        at = self.query_one(f"#rig-agents-{self.rig_name}", DataTable)
        at.clear()

        rig_agents = [a for a in agents if a["rig"] == self.rig_name]

        # Build reverse: which polecat is working on what
        worker_to_issue = {}
        for num, info in issue_map.items():
            assignee = info.get("assignee", "")
            wt = info.get("worktree", "")
            # Extract polecat name from worktree path or assignee
            polecat = ""
            if "polecat" in wt:
                m = re.search(r'polecat-\d+', wt)
                if m:
                    polecat = m.group(0)
            if not polecat and "polecat" in assignee:
                m = re.search(r'polecat-\d+', assignee)
                if m:
                    polecat = m.group(0)
            if polecat and info["status"] == "in_progress":
                worker_to_issue.setdefault(polecat, []).append(num)

        for a in rig_agents:
            idle = a["idle"]
            role = a["role"]

            if idle < 120:
                status = "[green]● active[/]"
            elif idle < 600:
                status = "[yellow]◐ idle[/]"
            else:
                status = "[red]○ stale[/]"

            style = "green" if idle < 120 else ("yellow" if idle < 600 else "red")

            # What is this agent working on?
            work_desc = ""
            issue_nums = worker_to_issue.get(role, [])
            if issue_nums and idle < 600:
                work_desc = ", ".join(f"#{n}" for n in issue_nums)
            elif issue_nums and idle >= 600:
                work_desc = f"[dim]was: {', '.join(f'#{n}' for n in issue_nums)}[/]"

            at.add_row(role, f"[{style}]{idle_str(idle)}[/]", status, work_desc)

        # ── issues table ─────────────────────────────────────────────
        it = self.query_one(f"#rig-issues-{self.rig_name}", DataTable)
        it.clear()

        # Update header
        ip_count = sum(1 for info in issue_map.values() if info["status"] == "in_progress")
        hdr = self.query_one(f"#rh-issues-{self.rig_name}", Label)
        hdr.update(
            f" {self.rig_name}  │  "
            f"{len(issues)} open  │  {ip_count} working  │  "
            f"{len(deployed)} deployed (6h)  │  {deploy_count} commits "
        )

        for issue in issues:
            num = issue["number"]
            title = issue["title"]
            info = issue_map.get(num)

            worker = ""

            if num in deployed:
                status = "[green bold]DEPLOYED[/]"
            elif info and info["status"] == "in_progress":
                # Check if the assigned worker is actually active
                assignee = info.get("assignee", "")
                wt = info.get("worktree", "")
                polecat = ""
                if "polecat" in wt:
                    m = re.search(r'polecat-\d+', wt)
                    if m:
                        polecat = m.group(0)
                if not polecat and "polecat" in assignee:
                    m = re.search(r'polecat-\d+', assignee)
                    if m:
                        polecat = m.group(0)

                if polecat:
                    worker_idle = agent_idle.get(f"{self.rig_name}/{polecat}", -1)
                    if worker_idle >= 0 and worker_idle < 600:
                        status = "[yellow bold]WORKING[/]"
                        style = "green" if worker_idle < 120 else "yellow"
                        worker = f"[{style}]{polecat}[/]"
                    elif worker_idle < 0:
                        status = "[red]ORPHANED[/]"
                        worker = f"[red]{polecat} (dead)[/]"
                    else:
                        status = "[red]STALLED[/]"
                        worker = f"[red]{polecat} ({idle_str(worker_idle)})[/]"
                elif "refinery" in assignee:
                    ref_idle = agent_idle.get(f"{self.rig_name}/refinery", -1)
                    if ref_idle >= 0 and ref_idle < 600:
                        status = "[cyan bold]MERGING[/]"
                        worker = "[cyan]refinery[/]"
                    elif ref_idle < 0:
                        status = "[red]ORPHANED[/]"
                        worker = "[red]refinery (dead)[/]"
                    else:
                        status = "[red]STALLED[/]"
                        worker = f"[red]refinery ({idle_str(ref_idle)})[/]"
                else:
                    status = "[red]STALLED[/]"
                    worker = f"[dim]{assignee[:12]}[/]" if assignee else ""
            elif info and info["status"] == "open":
                status = "[cyan]QUEUED[/]"
            else:
                status = "[dim]idle[/]"

            it.add_row(str(num), status, worker, title)


class StatusBar(Static):
    def update_status(self, data: dict) -> None:
        agents = data["agents"]
        total = data["session_count"]
        active = sum(1 for a in agents if a["idle"] < 120)
        stale = sum(1 for a in agents if a["idle"] >= 600)
        idle_n = total - active - stale
        self.update(
            f" {data['ts']}  │  "
            f"Sessions: {total}  │  "
            f"[green]{active} active[/]  "
            f"[yellow]{idle_n} idle[/]  "
            f"[red]{stale} stale[/]  │  "
            f"r=refresh  q=quit"
        )


# ── app ──────────────────────────────────────────────────────────────────

class GasTownDashboard(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text;
    }
    DataTable {
        height: auto;
        max-height: 30;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "force_refresh", "Refresh"),
    ]

    def __init__(self):
        super().__init__()
        self.cache = DataCache()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("City", id="tab-city"):
                with VerticalScroll():
                    yield CityTab(id="city-tab")
            for rig_name in RIGS:
                with TabPane(rig_name.capitalize(), id=f"tab-{rig_name}"):
                    with VerticalScroll():
                        yield RigTab(rig_name, id=f"rig-tab-{rig_name}")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        self.title = "Gas Town"
        self.sub_title = CITY_ROOT
        self.set_interval(AGENT_INTERVAL, self.refresh_agents)
        self.set_interval(BEADS_INTERVAL, self.refresh_rig_beads)
        self.set_interval(DEPLOYS_INTERVAL, self.refresh_rig_deploys)
        self.set_interval(ISSUES_INTERVAL, self.refresh_rig_issues)
        self.refresh_all()

    def action_force_refresh(self) -> None:
        self.cache._timestamps.clear()
        self.refresh_all()

    @work(thread=True)
    def refresh_all(self) -> None:
        worker = get_current_worker()
        self.cache.refresh_agents()
        for rig in RIGS:
            if worker.is_cancelled:
                return
            self.cache.refresh_beads(rig)
            self.cache.refresh_deploys(rig)
            self.cache.refresh_issues(rig)
        if not worker.is_cancelled:
            self.call_from_thread(self._apply)

    @work(thread=True)
    def refresh_agents(self) -> None:
        worker = get_current_worker()
        if self.cache.refresh_agents() and not worker.is_cancelled:
            self.call_from_thread(self._apply)

    @work(thread=True)
    def refresh_rig_beads(self) -> None:
        worker = get_current_worker()
        changed = any(self.cache.refresh_beads(r) for r in RIGS if not worker.is_cancelled)
        if changed and not worker.is_cancelled:
            self.call_from_thread(self._apply)

    @work(thread=True)
    def refresh_rig_deploys(self) -> None:
        worker = get_current_worker()
        changed = any(self.cache.refresh_deploys(r) for r in RIGS if not worker.is_cancelled)
        if changed and not worker.is_cancelled:
            self.call_from_thread(self._apply)

    @work(thread=True)
    def refresh_rig_issues(self) -> None:
        worker = get_current_worker()
        changed = any(self.cache.refresh_issues(r) for r in RIGS if not worker.is_cancelled)
        if changed and not worker.is_cancelled:
            self.call_from_thread(self._apply)

    def _apply(self) -> None:
        data = self.cache.snapshot()
        self.query_one("#city-tab", CityTab).update_data(data)
        for rig_name in RIGS:
            self.query_one(f"#rig-tab-{rig_name}", RigTab).update_data(data)
        self.query_one("#status-bar", StatusBar).update_status(data)


def main():
    os.chdir(CITY_ROOT)
    GasTownDashboard().run()


if __name__ == "__main__":
    main()
