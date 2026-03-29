#!/usr/bin/env python3
"""Unit tests for health.py — each check function tested in isolation with mocked subprocesses."""

import json
import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch, call

# Ensure color codes are empty during testing (not a tty)
os.environ.setdefault("TERM", "dumb")

import health


def _cp(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    """Shortcut to build a CompletedProcess."""
    return subprocess.CompletedProcess("test", returncode, stdout=stdout, stderr=stderr)


class TestRunCmd(unittest.TestCase):
    @patch("subprocess.run")
    def test_timeout_returns_rc1(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
        r = health.run_cmd("sleep 999", timeout=1)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr, "timeout")

    @patch("subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = _cp(stdout="hello\n")
        r = health.run_cmd("echo hello")
        self.assertEqual(r.stdout, "hello\n")

    @patch("subprocess.run")
    def test_run_cmd_output_strips(self, mock_run):
        mock_run.return_value = _cp(stdout="  42  \n")
        self.assertEqual(health.run_cmd_output("echo 42"), "42")

    @patch("subprocess.run")
    def test_run_cmd_output_failure_returns_empty(self, mock_run):
        mock_run.return_value = _cp(returncode=1)
        self.assertEqual(health.run_cmd_output("false"), "")


class TestJsonCmd(unittest.TestCase):
    @patch("subprocess.run")
    def test_valid_json(self, mock_run):
        mock_run.return_value = _cp(stdout='[{"id": 1}]')
        result = health.json_cmd("cmd")
        self.assertEqual(result, [{"id": 1}])

    @patch("subprocess.run")
    def test_invalid_json_returns_empty_list(self, mock_run):
        mock_run.return_value = _cp(stdout="not json")
        result = health.json_cmd("cmd")
        self.assertEqual(result, [])

    @patch("subprocess.run")
    def test_failure_returns_empty_list(self, mock_run):
        mock_run.return_value = _cp(returncode=1)
        result = health.json_cmd("cmd")
        self.assertEqual(result, [])


class TestHealthReport(unittest.TestCase):
    def test_ok_does_not_increment_problems(self):
        r = health.HealthReport()
        r.ok("all good")
        self.assertEqual(r.problems, 0)
        self.assertEqual(len(r.results), 1)

    def test_warn_increments_problems(self):
        r = health.HealthReport()
        r.warn("disk high")
        self.assertEqual(r.problems, 1)

    def test_fail_increments_problems(self):
        r = health.HealthReport()
        r.fail("dolt down")
        r.fail("controller down")
        self.assertEqual(r.problems, 2)

    def test_info_does_not_increment(self):
        r = health.HealthReport()
        r.info("just info")
        self.assertEqual(r.problems, 0)


class TestCheckController(unittest.TestCase):
    @patch("health.run_cmd")
    def test_controller_running(self, mock_run):
        mock_run.return_value = _cp(stdout="Controller: supervisor\nCity running")
        report = health.HealthReport()
        health.check_controller(report, fix=False)
        ok_msgs = [r for r in report.results if r.level == "ok"]
        self.assertTrue(any("Controller running" in r.message for r in ok_msgs))
        self.assertEqual(report.problems, 0)

    @patch("health.run_cmd")
    def test_controller_stopped_no_fix(self, mock_run):
        mock_run.return_value = _cp(stdout="city stopped", returncode=0)
        report = health.HealthReport()
        health.check_controller(report, fix=False)
        fails = [r for r in report.results if r.level == "fail"]
        self.assertTrue(any("not running" in r.message for r in fails))
        self.assertEqual(report.problems, 1)

    @patch("health.run_cmd")
    def test_controller_fix_starts_city(self, mock_run):
        # First call: gc status (stopped), second: gc start, third: gc status (running)
        mock_run.side_effect = [
            _cp(stdout="city stopped"),          # gc status check
            _cp(stdout=""),                       # gc start
            _cp(stdout="Controller: supervisor\nCity running"),  # gc status re-check
        ]
        report = health.HealthReport()
        health.check_controller(report, fix=True)
        ok_msgs = [r for r in report.results if r.level == "ok"]
        self.assertTrue(any("started successfully" in r.message for r in ok_msgs))


class TestCheckDisk(unittest.TestCase):
    @patch("health.run_cmd_output")
    def test_disk_ok(self, mock_output):
        mock_output.side_effect = ["  42%", "  100G"]
        report = health.HealthReport()
        health.check_disk(report)
        self.assertEqual(report.problems, 0)

    @patch("health.run_cmd_output")
    def test_disk_warn_90(self, mock_output):
        mock_output.side_effect = ["  91%", "  10G"]
        report = health.HealthReport()
        health.check_disk(report)
        self.assertEqual(report.problems, 1)
        warns = [r for r in report.results if r.level == "warn"]
        self.assertEqual(len(warns), 1)

    @patch("health.run_cmd_output")
    def test_disk_fail_95(self, mock_output):
        mock_output.side_effect = ["  96%", "  2G"]
        report = health.HealthReport()
        health.check_disk(report)
        fails = [r for r in report.results if r.level == "fail"]
        self.assertEqual(len(fails), 1)


class TestCheckDolt(unittest.TestCase):
    @patch("health.run_cmd")
    @patch("health.run_cmd_output")
    def test_dolt_not_running(self, mock_output, mock_run):
        mock_output.return_value = ""  # pgrep returns nothing
        report = health.HealthReport()
        health.check_dolt(report, fix=False, city="/tmp/fake-city")
        fails = [r for r in report.results if r.level == "fail"]
        self.assertTrue(any("not running" in f.message for f in fails))

    @patch("health.run_cmd")
    @patch("health.run_cmd_output")
    @patch("pathlib.Path.is_dir", return_value=False)
    @patch("pathlib.Path.is_file", return_value=False)
    def test_dolt_running_healthy(self, mock_isfile, mock_isdir, mock_output, mock_run):
        # pgrep returns PID, port, size
        mock_output.side_effect = ["12345", "12345", "3306", "1.5G"]
        mock_run.return_value = _cp(stdout="[]")  # bd list succeeds
        report = health.HealthReport()
        health.check_dolt(report, fix=False, city="/tmp/fake-city")
        self.assertEqual(report.problems, 0)


class TestCheckAgents(unittest.TestCase):
    def _make_sessions(self, now):
        return [
            {"name": "mayor", "activity": now - 30, "created": now - 3600,
             "pane_dead": False, "pane_pid": "1001"},
            {"name": "reli--refinery", "activity": now - 700, "created": now - 3600,
             "pane_dead": False, "pane_pid": "1002"},
            {"name": "dead-agent", "activity": now - 100, "created": now - 3600,
             "pane_dead": True, "pane_pid": "1003"},
            {"name": "s-gc-witness", "activity": now - 5, "created": now - 3600,
             "pane_dead": False, "pane_pid": "1004"},
        ]

    @patch("health.tmux_capture_tail", return_value="normal output here")
    @patch("health.process_cpu", return_value=1)
    @patch("health.process_alive", return_value=True)
    def test_counts_dead_and_stale(self, mock_alive, mock_cpu, mock_tail):
        now = 1000000
        sessions = self._make_sessions(now)
        report = health.HealthReport()
        health.check_agents(report, fix=False, now=now, sessions=sessions)
        self.assertEqual(report.agent_total, 4)
        self.assertEqual(report.agent_dead, 1)
        self.assertEqual(report.agent_stale, 1)  # reli--refinery at 700s

    @patch("health.tmux_capture_tail", return_value="hit your limit on this plan")
    @patch("health.process_alive", return_value=True)
    @patch("health.run_cmd")
    def test_quota_detection(self, mock_run, mock_alive, mock_tail):
        now = 1000000
        sessions = [
            {"name": "worker-1", "activity": now - 30, "created": now - 3600,
             "pane_dead": False, "pane_pid": "2001"},
        ]
        report = health.HealthReport()
        health.check_agents(report, fix=True, now=now, sessions=sessions)
        self.assertEqual(report.agent_quota, 1)
        fails = [r for r in report.results if r.level == "fail"]
        self.assertTrue(any("QUOTA" in f.message for f in fails))

    @patch("health.tmux_capture_tail", return_value="authentication_error: bad token")
    @patch("health.process_alive", return_value=True)
    def test_auth_error_detection(self, mock_alive, mock_tail):
        now = 1000000
        sessions = [
            {"name": "worker-2", "activity": now - 30, "created": now - 3600,
             "pane_dead": False, "pane_pid": "2002"},
        ]
        report = health.HealthReport()
        health.check_agents(report, fix=False, now=now, sessions=sessions)
        self.assertEqual(report.agent_auth, 1)

    @patch("health.tmux_capture_tail", return_value="working...")
    @patch("health.process_alive", return_value=True)
    def test_active_agent_cpu_high(self, mock_alive, mock_tail):
        """Agent with stale output but high CPU should be OK."""
        now = 1000000
        sessions = [
            {"name": "worker-3", "activity": now - 800, "created": now - 3600,
             "pane_dead": False, "pane_pid": "2003"},
        ]
        report = health.HealthReport()
        with patch("health.process_cpu", return_value=50):
            health.check_agents(report, fix=False, now=now, sessions=sessions)
        self.assertEqual(report.agent_stale, 0)
        oks = [r for r in report.results if r.level == "ok"]
        self.assertTrue(any("active" in o.message and "CPU 50%" in o.message for o in oks))

    @patch("health.tmux_capture_tail", return_value="")
    @patch("health.process_alive", return_value=False)
    def test_process_gone(self, mock_alive, mock_tail):
        now = 1000000
        sessions = [
            {"name": "worker-4", "activity": now - 30, "created": now - 3600,
             "pane_dead": False, "pane_pid": "9999"},
        ]
        report = health.HealthReport()
        health.check_agents(report, fix=False, now=now, sessions=sessions)
        self.assertEqual(report.agent_dead, 1)
        fails = [r for r in report.results if r.level == "fail"]
        self.assertTrue(any("process gone" in f.message for f in fails))


class TestCheckCriticalAgents(unittest.TestCase):
    @patch("health.run_cmd_output", return_value="")
    @patch("health.tmux_has_session")
    def test_all_present(self, mock_has, mock_output):
        mock_has.return_value = True
        report = health.HealthReport()
        health.check_critical_agents(report, fix=False)
        self.assertEqual(report.problems, 0)

    @patch("health.run_cmd_output", return_value="")
    @patch("health.tmux_has_session", return_value=False)
    def test_missing_agent(self, mock_has, mock_output):
        report = health.HealthReport()
        health.check_critical_agents(report, fix=False)
        self.assertEqual(report.problems, 2)  # both mayor and reli--refinery missing


class TestCheckDelivery(unittest.TestCase):
    @patch("health.run_cmd_output")
    @patch("os.path.isdir", return_value=True)
    def test_no_commits(self, mock_isdir, mock_output):
        mock_output.side_effect = [
            "",   # git log (no commits)
            "3",  # branch count
            "",   # git log (no commits) -- second rig
            "0",  # branch count
            "",   # git log (no commits) -- third rig
            "0",  # branch count
        ]
        report = health.HealthReport()
        health.check_delivery(report, city="/tmp/fake")
        # No problems from delivery -- only info messages for no merges
        self.assertEqual(report.problems, 0)

    @patch("health.run_cmd_output")
    @patch("os.path.isdir", return_value=True)
    def test_with_commits(self, mock_isdir, mock_output):
        mock_output.side_effect = [
            "abc123 fix bug\ndef456 add feature",  # 2 commits
            "5",                                     # branches
            "abc123 fix bug\ndef456 add feature",    # latest log
            "",                                      # second rig: no commits
            "0",
            "",                                      # third rig: no commits
            "0",
        ]
        report = health.HealthReport()
        health.check_delivery(report, city="/tmp/fake")
        oks = [r for r in report.results if r.level == "ok"]
        self.assertTrue(any("2 commits merged" in o.message for o in oks))


class TestCheckOrphanedBeads(unittest.TestCase):
    @patch("health.run_cmd")
    @patch("health.run_cmd_output")
    @patch("health.bd_list")
    def test_orphaned_bead_reset(self, mock_bd, mock_output, mock_run):
        mock_bd.return_value = [
            {
                "id": "bead-123",
                "assignee": "polecat-1",
                "metadata": {"branch": "fix-bug"},
            }
        ]
        # git ls-remote finds the branch on origin
        mock_output.return_value = "abc123\trefs/heads/fix-bug"
        # bd update succeeds
        mock_run.return_value = _cp()
        report = health.HealthReport()
        health._check_orphaned_beads(report, "reli", "/tmp/rigs/reli", running_agents=[])
        oks = [r for r in report.results if r.level == "ok"]
        self.assertTrue(any("reset orphaned bead-123" in o.message for o in oks))

    @patch("health.bd_list")
    def test_skips_always_restarted_roles(self, mock_bd):
        mock_bd.return_value = [
            {"id": "b-1", "assignee": "reli/refinery", "metadata": {}},
            {"id": "b-2", "assignee": "gascity/witness", "metadata": {}},
            {"id": "b-3", "assignee": "deacon", "metadata": {}},
            {"id": "b-4", "assignee": "mayor", "metadata": {}},
        ]
        report = health.HealthReport()
        health._check_orphaned_beads(report, "reli", "/tmp/rigs/reli", running_agents=[])
        # None should be reset
        self.assertEqual(report.problems, 0)
        self.assertEqual(len(report.results), 0)


class TestCheckUnassignedBeads(unittest.TestCase):
    @patch("health.bd_list")
    def test_warns_above_threshold(self, mock_bd):
        mock_bd.return_value = [
            {"assignee": "", "type": "work", "title": "fix-1"},
            {"assignee": "", "type": "work", "title": "fix-2"},
            {"assignee": "", "type": "work", "title": "fix-3"},
            {"assignee": "", "type": "work", "title": "fix-4"},
        ]
        report = health.HealthReport()
        health._check_unassigned_beads(report, "reli", "/tmp/rigs/reli")
        self.assertEqual(report.problems, 1)

    @patch("health.bd_list")
    def test_no_warn_at_threshold(self, mock_bd):
        mock_bd.return_value = [
            {"assignee": "", "type": "work", "title": "fix-1"},
            {"assignee": "", "type": "work", "title": "fix-2"},
            {"assignee": "", "type": "work", "title": "fix-3"},
        ]
        report = health.HealthReport()
        health._check_unassigned_beads(report, "reli", "/tmp/rigs/reli")
        self.assertEqual(report.problems, 0)

    @patch("health.bd_list")
    def test_skips_warrants_and_mol(self, mock_bd):
        mock_bd.return_value = [
            {"assignee": "", "type": "warrant", "title": "w-1"},
            {"assignee": "", "type": "work", "title": "mol-something"},
            {"assignee": "", "type": "work", "title": "fix-1"},
            {"assignee": "", "type": "work", "title": "fix-2"},
            {"assignee": "", "type": "work", "title": "fix-3"},
            {"assignee": "", "type": "work", "title": "fix-4"},
        ]
        report = health.HealthReport()
        health._check_unassigned_beads(report, "reli", "/tmp/rigs/reli")
        # 4 real unassigned (warrant and mol- excluded)
        self.assertEqual(report.problems, 1)


class TestPipelineFlow(unittest.TestCase):
    @patch("health.tmux_has_session", return_value=False)
    @patch("health.gh_pr_list", return_value=[])
    @patch("health.gh_issue_list", return_value=[{"number": 1, "title": "t", "url": "u"}])
    @patch("health.get_repo_slug", return_value="owner/repo")
    @patch("health.tmux_sessions", return_value=[])
    @patch("os.path.isdir", return_value=True)
    def test_issues_no_polecats_warns(self, *mocks):
        report = health.HealthReport()
        # Only test for one rig by patching RIGS
        with patch.object(health, "RIGS", ["gascity"]):
            health.check_pipeline_flow(report, fix=False, city="/tmp/fake", now=1000000)
        warns = [r for r in report.results if r.level == "warn"]
        self.assertTrue(any("NO polecats" in w.message for w in warns))

    @patch("health.tmux_has_session", return_value=False)
    @patch("health.gh_issue_list", return_value=[])
    @patch("health.gh_pr_list", return_value=[{"number": 1, "headRefName": "fix-1"}])
    @patch("health.get_repo_slug", return_value="owner/repo")
    @patch("health.tmux_sessions", return_value=[])
    @patch("os.path.isdir", return_value=True)
    def test_prs_no_refinery_warns(self, *mocks):
        report = health.HealthReport()
        with patch.object(health, "RIGS", ["gascity"]):
            health.check_pipeline_flow(report, fix=False, city="/tmp/fake", now=1000000)
        warns = [r for r in report.results if r.level == "warn"]
        self.assertTrue(any("no refinery" in w.message for w in warns))


class TestForemanDispatch(unittest.TestCase):
    @patch("health.run_cmd")
    @patch("health.run_cmd_output", return_value="")
    @patch("health.gh_pr_list", return_value=[])
    @patch("health.get_repo_slug", return_value="owner/repo")
    @patch("os.path.isdir", return_value=True)
    def test_sends_mail(self, mock_isdir, mock_slug, mock_prs, mock_output, mock_run):
        mock_run.return_value = _cp()
        report = health.HealthReport()
        report.problems = 5
        health.dispatch_foreman(report, city="/tmp/fake")
        # gc mail send should be called
        self.assertTrue(mock_run.called)
        cmd = mock_run.call_args[0][0]
        self.assertIn("gc mail send foreman", cmd)
        self.assertIn("HEALTH ALERT", cmd)

    def test_not_dispatched_when_below_threshold(self):
        """main() should only dispatch when problems > threshold AND --fix."""
        report = health.HealthReport()
        report.problems = 1  # below threshold of 2
        # dispatch_foreman should not be called — tested via main logic


class TestFixActions(unittest.TestCase):
    @patch("health.run_cmd")
    @patch("health.tmux_capture_tail", return_value="hit your limit")
    @patch("health.process_alive", return_value=True)
    def test_fix_kills_quota_blocked(self, mock_alive, mock_tail, mock_run):
        mock_run.return_value = _cp()
        now = 1000000
        sessions = [
            {"name": "worker-1", "activity": now - 30, "created": now - 3600,
             "pane_dead": False, "pane_pid": "5001"},
        ]
        report = health.HealthReport()
        health.check_agents(report, fix=True, now=now, sessions=sessions)
        # Should have called tmux kill-session
        kill_calls = [c for c in mock_run.call_args_list
                      if "kill-session" in str(c)]
        self.assertTrue(len(kill_calls) > 0)

    @patch("health.run_cmd")
    @patch("health.tmux_capture_tail", return_value="")
    @patch("health.process_alive", return_value=True)
    def test_fix_kills_dead_pane_critical(self, mock_alive, mock_tail, mock_run):
        mock_run.return_value = _cp()
        now = 1000000
        sessions = [
            {"name": "mayor", "activity": now - 30, "created": now - 3600,
             "pane_dead": True, "pane_pid": "5002"},
        ]
        report = health.HealthReport()
        health.check_agents(report, fix=True, now=now, sessions=sessions)
        kill_calls = [c for c in mock_run.call_args_list
                      if "kill-session" in str(c)]
        self.assertTrue(len(kill_calls) > 0)


class TestProblemCounting(unittest.TestCase):
    def test_multiple_fails_and_warns(self):
        r = health.HealthReport()
        r.fail("a")
        r.fail("b")
        r.warn("c")
        r.ok("d")
        r.info("e")
        self.assertEqual(r.problems, 3)

    def test_zero_problems(self):
        r = health.HealthReport()
        r.ok("all good")
        r.ok("still good")
        self.assertEqual(r.problems, 0)


class TestGetRepoSlug(unittest.TestCase):
    @patch("health.run_cmd_output")
    def test_https_url(self, mock_output):
        mock_output.return_value = "https://github.com/owner/repo.git"
        self.assertEqual(health.get_repo_slug("/tmp/rig"), "owner/repo")

    @patch("health.run_cmd_output")
    def test_ssh_url(self, mock_output):
        mock_output.return_value = "git@github.com:owner/repo.git"
        self.assertEqual(health.get_repo_slug("/tmp/rig"), "owner/repo")

    @patch("health.run_cmd_output")
    def test_empty(self, mock_output):
        mock_output.return_value = ""
        self.assertEqual(health.get_repo_slug("/tmp/rig"), "")


if __name__ == "__main__":
    unittest.main()
