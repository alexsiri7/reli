#!/usr/bin/env python3
"""health.py — Quick city health check with inactivity detection.

Usage: scripts/health.py [--fix]
  --fix: restart dead/stale critical agents automatically

Rewrite of health.sh — same checks, same output, same CLI.
"""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CITY_ROOT = os.environ.get("GC_CITY_ROOT", "/mnt/ext-fast/gc")
STALE_THRESHOLD = 600       # 10 minutes — no output = stale
VERY_STALE_THRESHOLD = 600  # 10 minutes — hung polecat
REFINERY_IDLE_THRESHOLD = 1200  # 20 minutes idle with PRs
RIGS = ["gascity", "reli", "annie"]
CRITICAL_AGENTS = ["mayor", "reli--refinery"]
COLLISION_THRESHOLD = 5
UNASSIGNED_THRESHOLD = 3
FOREMAN_PROBLEM_THRESHOLD = 2
CMD_TIMEOUT = 30

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

if sys.stdout.isatty():
    RED = "\033[0;31m"
    YEL = "\033[0;33m"
    GRN = "\033[0;32m"
    DIM = "\033[0;90m"
    RST = "\033[0m"
else:
    RED = YEL = GRN = DIM = RST = ""

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    level: str   # "ok", "warn", "fail", "info"
    message: str

@dataclass
class FixAction:
    description: str
    command: str

@dataclass
class HealthReport:
    results: list = field(default_factory=list)
    problems: int = 0
    fixes: list = field(default_factory=list)
    # Section-specific counters
    agent_total: int = 0
    agent_dead: int = 0
    agent_stale: int = 0
    agent_quota: int = 0
    agent_auth: int = 0
    early_exit: bool = False

    def ok(self, msg: str) -> None:
        self.results.append(CheckResult("ok", msg))

    def warn(self, msg: str) -> None:
        self.results.append(CheckResult("warn", msg))
        self.problems += 1

    def fail(self, msg: str) -> None:
        self.results.append(CheckResult("fail", msg))
        self.problems += 1

    def info(self, msg: str) -> None:
        self.results.append(CheckResult("info", msg))

    def section(self, title: str) -> None:
        self.results.append(CheckResult("section", title))

    def add_fix(self, description: str, command: str) -> None:
        self.fixes.append(FixAction(description, command))


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def run_cmd(cmd: str, timeout: int = CMD_TIMEOUT, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run a shell command and return the CompletedProcess."""
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="timeout")
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=str(e))


def run_cmd_output(cmd: str, timeout: int = CMD_TIMEOUT, cwd: Optional[str] = None) -> str:
    """Run a command and return stripped stdout (empty string on failure)."""
    r = run_cmd(cmd, timeout=timeout, cwd=cwd)
    return r.stdout.strip() if r.returncode == 0 else ""


def json_cmd(cmd: str, timeout: int = CMD_TIMEOUT, cwd: Optional[str] = None) -> list | dict:
    """Run a command, parse stdout as JSON, return [] on failure."""
    r = run_cmd(cmd, timeout=timeout, cwd=cwd)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return []


def gh_pr_list(repo: str, state: str = "open") -> list:
    """List GitHub PRs for *repo* (owner/name)."""
    return json_cmd(f"gh pr list -R {repo} --state {state} --json number,headRefName", timeout=15)


def gh_issue_list(repo: str, state: str = "open") -> list:
    """List GitHub issues for *repo*."""
    return json_cmd(f"gh issue list -R {repo} --state {state} --json number,title,url", timeout=15)


def bd_list(type_: str | None = None, status: str | None = None,
            assignee: str | None = None, cwd: str | None = None,
            limit: int = 0) -> list:
    """Wrapper around ``bd list --json``."""
    parts = ["bd list --json", f"--limit={limit}"]
    if type_:
        parts.append(f"--type={type_}")
    if status:
        parts.append(f"--status={status}")
    if assignee:
        parts.append(f"--assignee={assignee}")
    return json_cmd(" ".join(parts), timeout=15, cwd=cwd) or []


def tmux_sessions() -> list[dict]:
    """Return list of dicts with keys: name, activity, created, pane_dead, pane_pid."""
    r = run_cmd(
        "tmux -L gc list-sessions -F "
        "'#{session_name} #{session_activity} #{session_created} #{pane_dead} #{pane_pid}'"
    )
    if r.returncode != 0:
        return []
    sessions = []
    for line in sorted(r.stdout.strip().splitlines()):
        parts = line.split()
        if len(parts) < 5:
            continue
        sessions.append({
            "name": parts[0],
            "activity": int(parts[1]),
            "created": int(parts[2]),
            "pane_dead": parts[3] == "1",
            "pane_pid": parts[4],
        })
    return sessions


def tmux_capture_tail(session_name: str, lines: int = 8) -> str:
    """Capture last *lines* from a tmux pane."""
    r = run_cmd(f"tmux -L gc capture-pane -t {session_name} -p")
    if r.returncode != 0:
        return ""
    all_lines = r.stdout.splitlines()
    return "\n".join(all_lines[-lines:])


def tmux_has_session(name: str) -> bool:
    return run_cmd(f"tmux -L gc has-session -t {name}").returncode == 0


def tmux_session_names() -> list[str]:
    r = run_cmd("tmux -L gc list-sessions -F '#{session_name}'")
    if r.returncode != 0:
        return []
    return sorted(r.stdout.strip().splitlines())


def process_alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, PermissionError):
        return False


def process_cpu(pid: str) -> Optional[int]:
    r = run_cmd(f"ps -p {pid} -o %cpu=")
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return int(float(r.stdout.strip()))
    except ValueError:
        return None


def get_repo_slug(rig_dir: str) -> str:
    """Extract owner/repo from git remote."""
    url = run_cmd_output(f"git -C {rig_dir} remote get-url origin")
    if not url:
        return ""
    # Handle both https and ssh urls
    url = re.sub(r".*github\.com[:/]", "", url)
    url = re.sub(r"\.git$", "", url)
    return url


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

def check_controller(report: HealthReport, fix: bool) -> None:
    """Section 0: Controller liveness."""
    report.section("CONTROLLER")
    r = run_cmd("gc status")
    status_out = r.stdout + r.stderr
    is_running = "Controller: supervisor" in status_out and "city stopped" not in status_out
    if is_running:
        report.ok("Controller running")
    else:
        report.fail("Controller not running")
        if fix:
            report.info("       -> starting city...")
            run_cmd("gc start", timeout=60)
            # Re-check
            r2 = run_cmd("gc status")
            out2 = r2.stdout + r2.stderr
            if "Controller: supervisor" in out2 and "city stopped" not in out2:
                report.ok("City started successfully")
            else:
                report.fail("City failed to start -- manual intervention needed")


def check_disk(report: HealthReport) -> None:
    """Section 1: Disk usage."""
    report.section("DISK")
    pct_out = run_cmd_output("df / --output=pcent 2>/dev/null | tail -1")
    avail_out = run_cmd_output("df -h / --output=avail 2>/dev/null | tail -1")
    pct_str = pct_out.strip().replace("%", "").strip()
    avail_str = avail_out.strip()
    try:
        pct = int(pct_str)
    except ValueError:
        report.warn(f"Could not parse disk usage: {pct_out!r}")
        return
    if pct >= 95:
        report.fail(f"Root filesystem {pct}% ({avail_str} free)")
    elif pct >= 90:
        report.warn(f"Root filesystem {pct}% ({avail_str} free)")
    else:
        report.ok(f"Root filesystem {pct}% ({avail_str} free)")


def check_dolt(report: HealthReport, fix: bool, city: str = CITY_ROOT) -> None:
    """Section 2: Dolt health."""
    report.section("DOLT")

    # Find dolt PID
    dolt_pid = run_cmd_output(f"pgrep -f 'dolt sql-server.*{city}' | head -1")
    if not dolt_pid:
        dolt_pid = run_cmd_output("pgrep -f 'dolt sql-server.*dolt-config' | head -1")
    if not dolt_pid:
        report.fail("Dolt server not running")
        return

    # Port and size
    dolt_port = run_cmd_output(
        f"ss -tlnp 2>/dev/null | grep 'pid={dolt_pid}' | grep -oP ':\\K\\d+' | head -1"
    ) or "?"
    dolt_size = run_cmd_output(f"du -sh {city}/.beads/dolt 2>/dev/null | cut -f1") or "?"

    info_str = f"PID {dolt_pid}, port {dolt_port}, {dolt_size}"

    # Check for journal files
    has_journal = False
    dolt_dir = Path(city) / ".beads" / "dolt"
    if dolt_dir.is_dir():
        for db_dir in dolt_dir.iterdir():
            if not db_dir.is_dir():
                continue
            for f in db_dir.glob(".dolt/noms/vvvv*"):
                has_journal = True
                break
            if has_journal:
                break

    # Check for journal corruption
    journal_corrupt = False
    log_path = Path(city) / ".gc" / "runtime" / "packs" / "dolt" / "dolt.log"
    log_tail = ""
    if log_path.is_file():
        try:
            with open(log_path) as f:
                lines = f.readlines()
                log_tail = "".join(lines[-50:])
        except OSError:
            pass

    if dolt_dir.is_dir():
        for db_dir in dolt_dir.iterdir():
            if not db_dir.is_dir() or db_dir.name.startswith("."):
                continue
            db_name = db_dir.name
            journal_file = db_dir / ".dolt" / "noms" / "vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv"
            if journal_file.is_file():
                patterns = [
                    f"checksum error.*{db_name}",
                    f"connectionDb={db_name}.*checksum",
                    "corrupted journal",
                    "possible data loss.*journal",
                ]
                if any(re.search(p, log_tail) for p in patterns):
                    report.fail(
                        f"Dolt UP ({info_str}) -- JOURNAL CORRUPT in {db_name} "
                        f"(run: cd .beads/dolt/{db_name} && dolt fsck --revive-journal-with-data-loss)"
                    )
                    journal_corrupt = True

    # Auto-repair
    if journal_corrupt and fix:
        report.info("       -> running automated dolt repair...")
        r = run_cmd(f"{city}/scripts/dolt-repair.sh", timeout=120)
        if r.returncode == 0:
            report.ok("Dolt repair completed -- agents restarting")
            report.info("")
            report.info(f"{GRN}Dolt repair triggered full recovery. Skipping remaining checks.{RST}")
            report.early_exit = True
            return
        else:
            report.fail("Dolt repair failed -- check /tmp/dolt-repair-*.log")

    if not journal_corrupt:
        # Write health test via bd
        bd_r = run_cmd("bd list --type=session --json --limit=1", timeout=15)
        if bd_r.returncode != 0:
            err = bd_r.stdout + bd_r.stderr
            if re.search(r"checksum error", err, re.IGNORECASE):
                report.fail(f"Dolt UP ({info_str}) -- WRITE CORRUPTION detected (checksum error)")
            elif re.search(r"database.*not found|connection refused", err, re.IGNORECASE):
                report.fail(f"Dolt UP ({info_str}) -- DATABASE UNREACHABLE")
            else:
                _dolt_ok_or_journal_warn(report, info_str, has_journal)
        else:
            _dolt_ok_or_journal_warn(report, info_str, has_journal)


def _dolt_ok_or_journal_warn(report: HealthReport, info_str: str, has_journal: bool) -> None:
    if has_journal:
        report.warn(f"Dolt UP ({info_str}) -- journal file exists (run dolt gc)")
    else:
        report.ok(f"Dolt UP ({info_str})")


def check_agents(report: HealthReport, fix: bool, now: int | None = None,
                 sessions: list[dict] | None = None) -> None:
    """Section 3: Agent sessions."""
    report.section("AGENTS")
    if now is None:
        now = int(time.time())
    if sessions is None:
        sessions = tmux_sessions()

    total = 0
    dead = 0
    stale = 0
    quota = 0
    auth = 0

    for s in sessions:
        total += 1
        name = s["name"]

        # Skip witness sessions
        if name.startswith("s-gc-"):
            continue

        age = now - s["activity"]
        age_min = age // 60

        # Pane dead
        if s["pane_dead"]:
            report.fail(f"{name} -- pane dead")
            dead += 1
            if fix and name in CRITICAL_AGENTS:
                report.info("       -> restarting via gc nudge...")
                run_cmd(f"tmux -L gc kill-session -t {name}")
            continue

        # Process gone
        if s["pane_pid"] and not process_alive(s["pane_pid"]):
            report.fail(f"{name} -- process gone (PID {s['pane_pid']})")
            dead += 1
            continue

        # Capture tail for pattern matching
        tail = tmux_capture_tail(name)

        # Quota check
        quota_patterns = [
            r"hit your limit", r"exceeded.*quota",
            r"insufficient_quota", r"rate limit exceeded",
        ]
        if any(re.search(p, tail, re.IGNORECASE) for p in quota_patterns):
            report.fail(f"{name} -- QUOTA BLOCKED (idle {age_min}m)")
            quota += 1
            if fix:
                report.info("       -> killing quota-blocked session")
                run_cmd(f"tmux -L gc kill-session -t {name}")
            continue

        # Auth check
        auth_patterns = [
            r"authentication_error", r"Please run /login",
            r"OAuth token.*expired",
        ]
        if any(re.search(p, tail, re.IGNORECASE) for p in auth_patterns):
            report.fail(f"{name} -- AUTH ERROR (idle {age_min}m)")
            auth += 1
            continue

        # Stale check
        if age > STALE_THRESHOLD:
            cpu = process_cpu(s["pane_pid"])
            if cpu is not None and cpu > 5:
                report.ok(f"{name} -- active (CPU {cpu}%, last output {age_min}m ago)")
            else:
                cpu_str = str(cpu) if cpu is not None else "?"
                report.warn(f"{name} -- STALE (no output for {age_min}m, CPU {cpu_str}%)")
                stale += 1
        else:
            report.ok(f"{name}{DIM} ({age_min}m ago){RST}")

    report.agent_total = total
    report.agent_dead = dead
    report.agent_stale = stale
    report.agent_quota = quota
    report.agent_auth = auth
    report.info("")
    report.info(
        f"  Total: {total} sessions | Dead: {dead} | Stale: {stale} | Quota: {quota} | Auth: {auth}"
    )


def check_critical_agents(report: HealthReport, fix: bool) -> None:
    """Section 4: Critical agents."""
    report.section("CRITICAL AGENTS")
    for agent in CRITICAL_AGENTS:
        if tmux_has_session(agent):
            report.ok(f"{agent} present")
        else:
            session_list = run_cmd_output("gc session list")
            if session_list and re.search(rf"{re.escape(agent)}.*(awake|active|creating)", session_list):
                report.ok(f"{agent} present (reconciler-managed)")
            else:
                report.fail(f"{agent} MISSING")
                if fix:
                    report.info("       -> reconciler should recreate on next cycle")


def check_session_bead_collisions(report: HealthReport, fix: bool, city: str = CITY_ROOT) -> None:
    """Section 3b: Session bead collision detection + cleanup."""
    if not fix:
        return

    logs = run_cmd_output("gc supervisor logs")
    collision_count = len(re.findall(
        r"session.*alias already exists|session.*name already exists", logs
    ))
    if collision_count <= COLLISION_THRESHOLD:
        return

    running_agents = tmux_session_names()
    stuck_agents = 0

    for rig in RIGS:
        for role in ("refinery", "witness"):
            session = f"{rig}--{role}"
            if session in running_agents or any(session in a for a in running_agents):
                continue
            rig_dir = os.path.join(city, "rigs", rig)
            if role == "refinery":
                repo = get_repo_slug(rig_dir)
                if repo:
                    prs = gh_pr_list(repo)
                    has_work = len(prs) if isinstance(prs, list) else 0
                else:
                    has_work = 0
            else:
                beads = bd_list(status="in_progress", cwd=rig_dir, limit=1)
                has_work = len(beads) if isinstance(beads, list) else 0
            if has_work > 0:
                stuck_agents += 1

    if "mayor" not in running_agents:
        stuck_agents += 1

    if stuck_agents > 0:
        report.warn(f"Session bead collision blocking {stuck_agents} agent(s) -- cleaning stale beads")
        session_beads = bd_list(type_="session", status="open", cwd=city, limit=0)
        for bead in session_beads:
            agent_name = (bead.get("metadata") or {}).get("agent_name", "")
            if not agent_name:
                bead_id = bead.get("id", "")
                if bead_id:
                    run_cmd(
                        f'bd close {bead_id} --reason "health.py: clearing bare session bead"',
                        cwd=city,
                    )
        report.ok("Cleaned bare session beads -- controller should recover on next tick")


def check_delivery(report: HealthReport, city: str = CITY_ROOT) -> None:
    """Section 5: Delivery (commits, branches per rig)."""
    report.section("DELIVERY (last 1h)")
    for rig in RIGS:
        rig_dir = os.path.join(city, "rigs", rig)
        if not os.path.isdir(os.path.join(rig_dir, ".git")):
            continue
        commits_out = run_cmd_output(
            f'git -C {rig_dir} log --oneline --since="1 hour ago" master'
        )
        commit_count = len(commits_out.splitlines()) if commits_out else 0
        branches_out = run_cmd_output(
            f"git -C {rig_dir} branch -r --no-merged master 2>/dev/null | grep -c 'origin/'"
        )
        try:
            branch_count = int(branches_out)
        except ValueError:
            branch_count = 0

        if commit_count > 0:
            latest = run_cmd_output(f"git -C {rig_dir} log --oneline -1 master")
            report.ok(
                f"{rig}: {commit_count} commits merged, {branch_count} unmerged branches -- latest: {latest}"
            )
        else:
            report.info(
                f"  {DIM}--{RST}  {rig}: no merges in last hour ({branch_count} unmerged branches)"
            )


def check_pipeline_flow(report: HealthReport, fix: bool, city: str = CITY_ROOT,
                        now: int | None = None) -> None:
    """Section 5b: Pipeline flow (issues -> polecats -> PRs -> refinery)."""
    if now is None:
        now = int(time.time())

    report.section("1. IS EVERYTHING FLOWING?")
    sessions = tmux_sessions()
    fixes: list[FixAction] = []

    for rig in RIGS:
        rig_dir = os.path.join(city, "rigs", rig)
        if not os.path.isdir(os.path.join(rig_dir, ".git")):
            continue

        repo = get_repo_slug(rig_dir)
        issues_data = gh_issue_list(repo) if repo else []
        prs_data = gh_pr_list(repo) if repo else []
        issue_count = len(issues_data) if isinstance(issues_data, list) else 0
        pr_count = len(prs_data) if isinstance(prs_data, list) else 0

        # Count polecats by activity state
        polecats_active = 0
        polecats_stale = 0
        polecats_very_stale = 0
        very_stale_names: list[str] = []

        for s in sessions:
            if not s["name"].startswith(f"{rig}--polecat"):
                continue
            age = now - s["activity"]
            if age > VERY_STALE_THRESHOLD:
                polecats_very_stale += 1
                very_stale_names.append(s["name"])
            elif age > STALE_THRESHOLD:
                polecats_stale += 1
            else:
                polecats_active += 1

        polecats_total = polecats_active + polecats_stale + polecats_very_stale
        has_refinery = tmux_has_session(f"{rig}--refinery")

        # Status line
        status = f"  {rig}: {issue_count} issues -> {polecats_active} polecats"
        if polecats_stale > 0:
            status += f" (+{polecats_stale} stale)"
        if polecats_very_stale > 0:
            status += f" (+{polecats_very_stale} hung)"
        status += f" -> {pr_count} PRs"
        status += " -> refinery" if has_refinery else f" -> {DIM}no refinery{RST}"
        report.info(status)

        # Detect stuck states
        if issue_count > 0 and polecats_total == 0:
            report.warn(f"{rig}: {issue_count} open issues but NO polecats -- work not being picked up")
            fixes.append(FixAction(
                f"{rig}: mail mayor to sling work",
                f"gc mail send mayor --subject 'Read {rig} issues' "
                f"'Read the GitHub issues for {rig} and sling work to polecats. "
                f"There are {issue_count} open issues and no polecats working.'"
            ))
        elif issue_count > 0 and polecats_active == 0 and polecats_very_stale > 0:
            report.warn(f"{rig}: all {polecats_very_stale} polecats hung 60m+ -- probably finished or stuck")
            kill_cmds = "; ".join(f"tmux -L gc kill-session -t {sn}" for sn in very_stale_names)
            fixes.append(FixAction(
                f"{rig}: kill hung polecats so reconciler creates fresh ones",
                kill_cmds,
            ))
        elif issue_count > 0 and polecats_active == 0 and polecats_stale > 0:
            report.warn(
                f"{rig}: {issue_count} open issues, all {polecats_stale} polecats stale "
                "-- work may be stuck (waiting before killing)"
            )

        if pr_count > 0 and not has_refinery:
            report.warn(f"{rig}: {pr_count} open PRs but no refinery -- PRs not being merged")
            fixes.append(FixAction(
                f"{rig}: mail refinery to wake and merge",
                f"gc mail send {rig}--refinery --subject 'PRs waiting' "
                f"'There are {pr_count} open PRs on {rig} waiting for review and merge.'"
            ))

        if pr_count > 0 and has_refinery:
            ref_activity = _session_activity(f"{rig}--refinery", sessions)
            if ref_activity is not None:
                ref_age = now - ref_activity
                if ref_age > VERY_STALE_THRESHOLD:
                    report.warn(
                        f"{rig}: refinery idle {ref_age // 60}m with {pr_count} PRs open -- may be stuck"
                    )
                    fixes.append(FixAction(
                        f"{rig}: kill stuck refinery, reconciler will restart",
                        f"tmux -L gc kill-session -t {rig}--refinery",
                    ))

    # Print fixes section
    report.section("2. WHAT CAN WE DO TO UNSTICK THINGS?")
    if not fixes:
        report.info(f"  {GRN}Nothing stuck -- pipeline is flowing.{RST}")
    else:
        for i, f in enumerate(fixes, 1):
            report.info(f"  {i}. {f.description}")
            report.info(f"     {DIM}$ {f.command}{RST}")
        report.info("")
        report.info(f"  {YEL}REMEMBER: IT'S YOUR JOB TO KEEP THINGS FLOWING.{RST}")
        report.info("  Don't just report -- fix it. Run with --fix or take the actions above.")
        if fix:
            report.info("")
            report.info("  Applying fixes...")
            for f in fixes:
                report.info(f"  -> {f.description}")
                r = run_cmd(f.command)
                report.info("    done" if r.returncode == 0 else "    failed")

    report.fixes.extend(fixes)


def _session_activity(name: str, sessions: list[dict]) -> Optional[int]:
    for s in sessions:
        if s["name"] == name:
            return s["activity"]
    return None


def check_work_flow(report: HealthReport, city: str = CITY_ROOT,
                    now: int | None = None) -> None:
    """Section 6 (--fix only): Work flow enforcement."""
    if now is None:
        now = int(time.time())

    report.section("WORK FLOW ENFORCEMENT")
    running_agents = tmux_session_names()
    sessions = tmux_sessions()

    for rig in RIGS:
        rig_dir = os.path.join(city, "rigs", rig)
        if not os.path.isdir(os.path.join(rig_dir, ".beads")):
            continue

        repo = get_repo_slug(rig_dir)

        # --- 6a. Orphaned bead recovery ---
        _check_orphaned_beads(report, rig, rig_dir, running_agents)

        # --- 6b. Unmerged branches with no tracking bead ---
        if repo:
            _check_untracked_branches(report, rig, rig_dir, repo)

        # --- 6c. PRs with no refinery bead ---
        if repo:
            _check_beadless_prs(report, rig, rig_dir, repo, sessions, now)

        # --- 6d/6e. Issues with no work beads ---
        if repo:
            _check_unslung_issues(report, rig, rig_dir, repo)

        # --- 6f. Stale session beads ---
        _check_stale_session_beads(report, rig, city, running_agents)

        # --- 6g. Unassigned beads stuck in pool ---
        _check_unassigned_beads(report, rig, rig_dir)


def _check_orphaned_beads(report: HealthReport, rig: str, rig_dir: str,
                          running_agents: list[str]) -> None:
    in_progress = bd_list(status="in_progress", cwd=rig_dir, limit=0)
    for bead in in_progress:
        assignee = bead.get("assignee", "") or ""
        if not assignee:
            continue
        # Skip always-restarted roles
        if any(r in assignee for r in ("witness", "refinery", "deacon", "mayor")):
            continue
        # Check if agent is running
        normalized = assignee.replace("/", "-")
        agent_running = any(normalized in a or assignee in a for a in running_agents)
        if agent_running:
            continue

        bead_id = bead.get("id", "")
        metadata = bead.get("metadata") or {}
        branch = metadata.get("branch", "")

        if branch:
            has_remote = run_cmd_output(
                f"git ls-remote --heads origin {branch} | head -1", timeout=10, cwd=rig_dir
            )
            if has_remote:
                r = run_cmd(f'bd update {bead_id} --status=open --assignee=""', timeout=10, cwd=rig_dir)
                if r.returncode == 0:
                    report.ok(f"{rig}: reset orphaned {bead_id} to pool (branch {branch} on origin)")
                else:
                    report.warn(f"{rig}: failed to reset {bead_id}")
            # If branch NOT on origin, leave for witness to salvage
        else:
            r = run_cmd(f'bd update {bead_id} --status=open --assignee=""', timeout=10, cwd=rig_dir)
            if r.returncode == 0:
                report.ok(f"{rig}: reset orphaned {bead_id} to pool (no branch)")
            else:
                report.warn(f"{rig}: failed to reset {bead_id}")


def _check_untracked_branches(report: HealthReport, rig: str, rig_dir: str,
                              repo: str) -> None:
    unmerged_out = run_cmd_output(
        f"git -C {rig_dir} branch -r --no-merged master 2>/dev/null | grep 'origin/' | grep -v 'HEAD' | sed 's|.*origin/||'"
    )
    if not unmerged_out:
        return

    open_beads = bd_list(status="open", cwd=rig_dir, limit=0)
    ip_beads = bd_list(status="in_progress", cwd=rig_dir, limit=0)

    untracked = 0
    for branch in unmerged_out.splitlines():
        branch = branch.strip()
        if not branch or branch in ("main", "master", "develop"):
            continue
        has_bead = any(
            (b.get("metadata") or {}).get("branch") == branch
            for b in (open_beads + ip_beads)
        )
        if not has_bead:
            untracked += 1

    if untracked > 0:
        report.warn(f"{rig}: {untracked} unmerged branch(es) with no tracking bead")
        run_cmd(
            f'gc nudge mayor "FLOW CHECK: {rig} has {untracked} unmerged branch(es) on origin '
            f'with no work bead tracking them. Check if they should be adopted or cleaned up."'
        )


def _check_beadless_prs(report: HealthReport, rig: str, rig_dir: str, repo: str,
                        sessions: list[dict], now: int) -> None:
    prs = gh_pr_list(repo)
    if not isinstance(prs, list) or not prs:
        return

    pr_count = len(prs)
    refinery_beads = bd_list(assignee=f"{rig}/refinery", status="open", cwd=rig_dir, limit=0)

    beadless_prs = 0
    beadless_list = ""
    for pr in prs:
        pr_branch = pr.get("headRefName", "")
        if not pr_branch:
            continue
        has_bead = any(
            (b.get("metadata") or {}).get("branch") == pr_branch for b in refinery_beads
        )
        if not has_bead:
            beadless_prs += 1
            beadless_list += f"#{pr.get('number', '?')} "

    if beadless_prs > 0:
        report.warn(f"{rig}: {beadless_prs} of {pr_count} open PR(s) have NO refinery bead: {beadless_list}")
        run_cmd(
            f'gc session nudge "{rig}/refinery" "FLOW CHECK: {beadless_prs} open PR(s) have no tracking bead '
            f"({beadless_list}). Run 'gh pr list -R {repo} --state open' and process each PR: rebase on master, "
            f'run tests, merge if clean. Do not wait for beads -- process the PRs directly."'
        )

    # Check idle refinery with PRs
    ref_session = f"{rig}--refinery"
    if tmux_has_session(ref_session):
        ref_activity = _session_activity(ref_session, sessions)
        ref_age = now - (ref_activity or now)
        if ref_age > REFINERY_IDLE_THRESHOLD:
            report.warn(f"{rig}: refinery idle {ref_age // 60}m with {pr_count} PR(s) -- killing to restart")
            run_cmd(f"tmux -L gc kill-session -t {ref_session}")
            report.ok(f"{rig}: killed idle refinery -- reconciler will restart")
    else:
        report.ok(f"{rig}: {pr_count} PR(s) open, refinery not running (work_query should auto-wake)")


def _check_unslung_issues(report: HealthReport, rig: str, rig_dir: str,
                          repo: str) -> None:
    issues = gh_issue_list(repo)
    if not isinstance(issues, list) or not issues:
        return

    issue_count = len(issues)
    all_open = bd_list(status="open", cwd=rig_dir, limit=0)
    all_ip = bd_list(status="in_progress", cwd=rig_dir, limit=0)
    all_closed = bd_list(status="closed", cwd=rig_dir, limit=0)
    all_beads = all_open + all_ip + all_closed

    unslung = 0
    unslung_urls = ""
    for issue in issues:
        url = issue.get("url", "")
        if not url:
            continue
        has_bead = any(url in (b.get("title", "") or "") for b in all_beads)
        if not has_bead:
            unslung += 1
            unslung_urls += f"{url} "

    if unslung > 0:
        report.warn(f"{rig}: {unslung} of {issue_count} open issue(s) have no work bead")
        run_cmd(
            f'gc session nudge mayor "FLOW CHECK: {rig} has {unslung} open issue(s) '
            f'with no work bead. Sling them to polecats: {unslung_urls}"'
        )
    else:
        report.ok(f"{rig}: all {issue_count} open issue(s) have tracking beads")


def _check_stale_session_beads(report: HealthReport, rig: str, city: str,
                               running_agents: list[str]) -> None:
    session_beads = bd_list(type_="session", status="open", cwd=city, limit=0)
    for bead in session_beads:
        title = bead.get("title", "") or ""
        if rig not in title:
            continue
        bead_id = bead.get("id", "")
        sb_session = title.replace("/", "-")
        sb_running = any(sb_session in a or title in a for a in running_agents)
        if not sb_running:
            r = run_cmd(
                f'bd close {bead_id} --reason "Stale session bead -- agent not running"',
                timeout=10, cwd=city,
            )
            if r.returncode == 0:
                report.ok(f"{rig}: closed stale session bead {bead_id} ({title})")
            else:
                report.warn(f"{rig}: failed to close stale session bead {bead_id}")


def _check_unassigned_beads(report: HealthReport, rig: str, rig_dir: str) -> None:
    beads = bd_list(status="open", cwd=rig_dir, limit=0)
    unassigned = 0
    for b in beads:
        assignee = b.get("assignee", "") or ""
        btype = b.get("type", "") or ""
        title = b.get("title", "") or ""
        if not assignee and btype != "warrant" and not re.search(r"mol-", title):
            unassigned += 1
    if unassigned > UNASSIGNED_THRESHOLD:
        report.warn(f"{rig}: {unassigned} unassigned work beads sitting in pool")


# ---------------------------------------------------------------------------
# Foreman dispatch
# ---------------------------------------------------------------------------

def dispatch_foreman(report: HealthReport, city: str = CITY_ROOT) -> None:
    """If >FOREMAN_PROBLEM_THRESHOLD problems and --fix, mail foreman."""
    summary = f"Health check found {report.problems} issue(s) at {time.strftime('%H:%M')}."
    summary += "\n\nRun these commands to assess:\n"
    summary += "  scripts/health.py     # see current state\n"
    summary += "  scripts/metrics.sh    # see throughput\n"
    summary += "  gc status             # see agent status\n"
    summary += "\nKey concerns:\n"

    for rig in RIGS:
        rig_dir = os.path.join(city, "rigs", rig)
        if not os.path.isdir(os.path.join(rig_dir, ".git")):
            continue
        repo = get_repo_slug(rig_dir)
        if repo:
            prs = gh_pr_list(repo)
            pr_count = len(prs) if isinstance(prs, list) else 0
        else:
            pr_count = 0
        commits_out = run_cmd_output(
            f'git -C {rig_dir} log --oneline --since="1 hour ago" master'
        )
        commits_1h = len(commits_out.splitlines()) if commits_out else 0
        if pr_count > 5:
            summary += f"- {rig}: {pr_count} open PRs (backlog)\n"
        if commits_1h == 0:
            summary += f"- {rig}: no commits merged in last hour\n"

    summary += "\nYour job: diagnose why the pipeline is stalled and fix it."
    summary += " Check stuck polecats, idle refineries, unslung issues."
    summary += " Don't just report -- ACT."

    r = run_cmd(
        f'gc mail send foreman -s "HEALTH ALERT: {report.problems} issue(s) need attention" '
        f'-m "{summary}"'
    )
    if r.returncode == 0:
        report.info(f"  {DIM}Mailed foreman for investigation.{RST}")


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

def render(report: HealthReport) -> None:
    """Print all collected results."""
    for r in report.results:
        if r.level == "section":
            print(f"=== {r.message} ===")
        elif r.level == "ok":
            print(f"  {GRN}OK{RST}  {r.message}")
        elif r.level == "warn":
            print(f"  {YEL}WARN{RST} {r.message}")
        elif r.level == "fail":
            print(f"  {RED}FAIL{RST} {r.message}")
        elif r.level == "info":
            print(r.message)
        print() if r.level == "section" and r.message == "CONTROLLER" else None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(args: list[str] | None = None) -> int:
    if args is None:
        args = sys.argv[1:]

    fix = "--fix" in args
    city = os.environ.get("GC_CITY_ROOT", CITY_ROOT)
    now = int(time.time())

    report = HealthReport()

    # Section 0: Controller
    check_controller(report, fix)
    if report.early_exit:
        render(report)
        return report.problems

    # Section 1: Disk
    check_disk(report)

    # Section 2: Dolt
    check_dolt(report, fix, city)
    if report.early_exit:
        render(report)
        return 0

    # Section 3: Agent sessions
    check_agents(report, fix, now)

    # Section 3b: Session bead collisions (fix only)
    check_session_bead_collisions(report, fix, city)

    # Section 4: Critical agents
    check_critical_agents(report, fix)

    # Section 5: Delivery
    check_delivery(report, city)

    # Section 5b: Pipeline flow
    check_pipeline_flow(report, fix, city, now)

    # Section 6: Work flow enforcement (fix only)
    if fix:
        check_work_flow(report, city, now)

    # Render output
    render(report)

    # Summary
    print()
    if report.problems == 0:
        print(f"{GRN}All healthy.{RST} {report.agent_total} agents running, no issues.")
    else:
        print(f"{YEL}{report.problems} issue(s) found.{RST}")
        if not fix:
            print("  Run with --fix to auto-restart dead critical agents.")
        if fix and report.problems > FOREMAN_PROBLEM_THRESHOLD:
            dispatch_foreman(report, city)

    return report.problems


if __name__ == "__main__":
    sys.exit(main())
