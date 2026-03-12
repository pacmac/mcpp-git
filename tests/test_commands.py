"""Tests for commands.py — GitCommands handlers."""

import os
import subprocess
from pathlib import Path

import pytest

from mcpp_git.commands import GitCommands
from mcpp_git.git import (
    McppTag,
    add_all,
    add_file,
    build_message,
    commit,
    get_commit_message,
    is_clean,
    parse_tag,
    status_porcelain,
)


# ── Fixtures ──

@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo with an initial commit."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(tmp_path), capture_output=True, check=True
    )
    (tmp_path / "README.md").write_text("# Test repo\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(tmp_path), capture_output=True, check=True
    )
    return tmp_path


@pytest.fixture
def git_repo_pair(tmp_path):
    """Create a bare remote and a cloned local repo."""
    bare = tmp_path / "remote.git"
    local = tmp_path / "local"
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    subprocess.run(["git", "clone", str(bare), str(local)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(local), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(local), capture_output=True, check=True
    )
    (local / "README.md").write_text("# Test repo\n")
    subprocess.run(["git", "add", "-A"], cwd=str(local), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(local), capture_output=True, check=True
    )
    subprocess.run(["git", "push"], cwd=str(local), capture_output=True, check=True)
    return bare, local


def _make_args(user="alice", task="test-task", step=1, **extra):
    """Build an args dict with context fields."""
    args = {"user": user, "task": task, "step": step}
    args.update(extra)
    return args


def _make_commands():
    return GitCommands()


# ── Checkpoint tests ──

class TestCheckpoint:
    def test_checkpoint_clean_tree(self, git_repo):
        cmds = _make_commands()
        result = cmds.checkpoint(str(git_repo), _make_args())
        assert not result["success"]
        assert "clean" in result["error"]

    def test_checkpoint_commits_files(self, git_repo):
        (git_repo / "a.txt").write_text("aaa\n")
        (git_repo / "b.txt").write_text("bbb\n")
        cmds = _make_commands()
        result = cmds.checkpoint(str(git_repo), _make_args())
        assert result["success"]
        assert len(result["result"]["commits"]) == 2
        assert is_clean(git_repo)

    def test_checkpoint_auto_message(self, git_repo):
        (git_repo / "f.txt").write_text("content\n")
        cmds = _make_commands()
        result = cmds.checkpoint(str(git_repo), _make_args(task="add-feature", step=3))
        assert result["success"]
        assert "step 3" in result["result"]["message"]

    def test_checkpoint_custom_message(self, git_repo):
        (git_repo / "f.txt").write_text("content\n")
        cmds = _make_commands()
        result = cmds.checkpoint(str(git_repo), _make_args(message="my custom msg"))
        assert result["success"]
        assert result["result"]["message"] == "my custom msg"

    def test_checkpoint_tags_commits(self, git_repo):
        (git_repo / "f.txt").write_text("content\n")
        cmds = _make_commands()
        result = cmds.checkpoint(str(git_repo), _make_args(user="bob", task="t1", step=2))
        assert result["success"]
        sha = result["result"]["commits"][0]["sha"]
        msg = get_commit_message(git_repo, sha)
        tag = parse_tag(msg)
        assert tag.user == "bob"
        assert tag.task == "t1"
        assert tag.step == 2


# ── Commit tests ──

class TestCommit:
    def test_commit_requires_message(self, git_repo):
        cmds = _make_commands()
        result = cmds.commit(str(git_repo), _make_args())
        assert not result["success"]
        assert "message is required" in result["error"]

    def test_commit_clean_tree(self, git_repo):
        cmds = _make_commands()
        result = cmds.commit(str(git_repo), _make_args(message="test"))
        assert not result["success"]
        assert "clean" in result["error"]

    def test_commit_success(self, git_repo):
        (git_repo / "f.txt").write_text("content\n")
        cmds = _make_commands()
        result = cmds.commit(str(git_repo), _make_args(message="add file"))
        assert result["success"]
        assert len(result["result"]["commits"]) == 1
        assert result["result"]["message"] == "add file"
        assert is_clean(git_repo)


# ── Push tests ──

class TestPush:
    def test_push_no_remote(self, git_repo):
        cmds = _make_commands()
        result = cmds.push(str(git_repo), {})
        assert not result["success"]
        assert "No remote" in result["error"]

    def test_push_success(self, git_repo_pair):
        _, local = git_repo_pair
        (local / "new.txt").write_text("new\n")
        add_all(local)
        commit(local, "new file")
        cmds = _make_commands()
        result = cmds.push(str(local), {})
        assert result["success"]


# ── Status tests ──

class TestStatus:
    def test_status_clean(self, git_repo):
        cmds = _make_commands()
        result = cmds.status(str(git_repo), {})
        assert result["success"]
        assert result["result"]["files"] == []
        assert "clean" in result["display"]

    def test_status_with_changes(self, git_repo):
        (git_repo / "new.txt").write_text("hello\n")
        cmds = _make_commands()
        result = cmds.status(str(git_repo), {})
        assert result["success"]
        assert len(result["result"]["files"]) == 1
        assert result["result"]["files"][0]["path"] == "new.txt"


# ── Show tests ──

class TestShow:
    def test_show_requires_sha(self, git_repo):
        cmds = _make_commands()
        result = cmds.show(str(git_repo), {})
        assert not result["success"]
        assert "sha is required" in result["error"]

    def test_show_valid_commit(self, git_repo):
        (git_repo / "f.txt").write_text("content\n")
        add_all(git_repo)
        sha = commit(git_repo, "test commit")
        cmds = _make_commands()
        result = cmds.show(str(git_repo), {"sha": sha})
        assert result["success"]
        assert result["result"]["sha"] == sha

    def test_show_invalid_sha(self, git_repo):
        cmds = _make_commands()
        result = cmds.show(str(git_repo), {"sha": "deadbeef1234567890"})
        assert not result["success"]


# ── Log tests ──

class TestLog:
    def test_log_empty(self, git_repo):
        cmds = _make_commands()
        result = cmds.log(str(git_repo), _make_args())
        assert result["success"]
        assert result["result"]["entries"] == []

    def test_log_with_commits(self, git_repo):
        (git_repo / "f.txt").write_text("content\n")
        cmds = _make_commands()
        cmds.checkpoint(str(git_repo), _make_args(user="alice", task="t1", step=1, message="test"))

        result = cmds.log(str(git_repo), _make_args(user="alice", task="t1"))
        assert result["success"]
        assert len(result["result"]["entries"]) >= 1
        assert result["result"]["entries"][0]["user"] == "alice"

    def test_log_show_all(self, git_repo):
        (git_repo / "f.txt").write_text("content\n")
        add_all(git_repo)
        commit(git_repo, "plain commit")
        cmds = _make_commands()
        result = cmds.log(str(git_repo), {"show_all": True})
        assert result["success"]
        assert len(result["result"]["entries"]) >= 1


# ── Diff tests ──

class TestDiff:
    def test_diff_no_changes(self, git_repo):
        cmds = _make_commands()
        result = cmds.diff(str(git_repo), _make_args())
        assert result["success"]
        assert result["result"]["diff"] == ""

    def test_diff_with_from_ref(self, git_repo):
        (git_repo / "f.txt").write_text("v1\n")
        add_all(git_repo)
        sha1 = commit(git_repo, "first")

        (git_repo / "f.txt").write_text("v2\n")
        add_all(git_repo)
        sha2 = commit(git_repo, "second")

        cmds = _make_commands()
        result = cmds.diff(str(git_repo), {"from": sha1, "to": sha2})
        assert result["success"]
        assert "f.txt" in result["result"]["diff"]


# ── File owner tests ──

class TestFileOwner:
    def test_file_owner_requires_file(self, git_repo):
        cmds = _make_commands()
        result = cmds.file_owner(str(git_repo), {})
        assert not result["success"]

    def test_file_owner_unknown(self, git_repo):
        cmds = _make_commands()
        result = cmds.file_owner(str(git_repo), {"file": "README.md"})
        assert result["success"]
        assert result["result"]["owner"] is None

    def test_file_owner_known(self, git_repo):
        tag = McppTag(user="alice", task="t1", step=1)
        ft = ("owned.txt", McppTag(user="alice", notes="test"))
        (git_repo / "owned.txt").write_text("content\n")
        add_all(git_repo)
        commit(git_repo, build_message("alice adds", tag, [ft]))

        cmds = _make_commands()
        result = cmds.file_owner(str(git_repo), {"file": "owned.txt"})
        assert result["success"]
        assert result["result"]["owner"] == "alice"


# ── File history tests ──

class TestFileHistory:
    def test_file_history_requires_file(self, git_repo):
        cmds = _make_commands()
        result = cmds.file_history(str(git_repo), {})
        assert not result["success"]

    def test_file_history_success(self, git_repo):
        cmds = _make_commands()
        result = cmds.file_history(str(git_repo), {"file": "README.md"})
        assert result["success"]
        assert "Test User" in result["result"]["blame"]


# ── File restore tests ──

class TestFileRestore:
    def test_file_restore_requires_sha(self, git_repo):
        cmds = _make_commands()
        result = cmds.file_restore(str(git_repo), _make_args(file="f.txt"))
        assert not result["success"]
        assert "sha is required" in result["error"]

    def test_file_restore_requires_file(self, git_repo):
        cmds = _make_commands()
        result = cmds.file_restore(str(git_repo), _make_args(sha="abc123"))
        assert not result["success"]
        assert "file is required" in result["error"]

    def test_file_restore_wrong_user(self, git_repo):
        tag = McppTag(user="bob", task="t1", step=1)
        (git_repo / "f.txt").write_text("content\n")
        add_all(git_repo)
        sha = commit(git_repo, build_message("bob adds", tag))

        cmds = _make_commands()
        result = cmds.file_restore(str(git_repo), _make_args(user="alice", sha=sha, file="f.txt"))
        assert not result["success"]
        assert "bob" in result["error"]

    def test_file_restore_success(self, git_repo):
        tag = McppTag(user="alice", task="t1", step=1)
        ft = ("f.txt", McppTag(user="alice", notes="original"))
        (git_repo / "f.txt").write_text("original\n")
        add_all(git_repo)
        sha1 = commit(git_repo, build_message("add file", tag, [ft]))

        (git_repo / "f.txt").write_text("modified\n")
        add_all(git_repo)
        commit(git_repo, build_message("modify file", tag))

        cmds = _make_commands()
        result = cmds.file_restore(str(git_repo), _make_args(user="alice", sha=sha1, file="f.txt"))
        assert result["success"]
        assert (git_repo / "f.txt").read_text() == "original\n"


# ── Search tests ──

class TestSearch:
    def test_search_requires_pattern(self, git_repo):
        cmds = _make_commands()
        result = cmds.search(str(git_repo), {})
        assert not result["success"]
        assert "pattern is required" in result["error"]

    def test_search_finds_content(self, git_repo):
        (git_repo / "app.js").write_text("function hello() { return 42; }\n")
        (git_repo / "util.js").write_text("const x = 1;\n")
        add_all(git_repo)
        commit(git_repo, "add js files")
        cmds = _make_commands()
        result = cmds.search(str(git_repo), {"pattern": "function"})
        assert result["success"]
        assert result["result"]["count"] == 1
        assert result["result"]["matches"][0]["path"] == "app.js"
        assert result["result"]["matches"][0]["line"] == 1

    def test_search_with_include(self, git_repo):
        (git_repo / "a.js").write_text("hello world\n")
        (git_repo / "b.py").write_text("hello world\n")
        add_all(git_repo)
        commit(git_repo, "add files")
        cmds = _make_commands()
        result = cmds.search(str(git_repo), {"pattern": "hello", "include": "*.js"})
        assert result["success"]
        assert result["result"]["count"] == 1
        assert result["result"]["matches"][0]["path"] == "a.js"

    def test_search_ignore_case(self, git_repo):
        (git_repo / "f.txt").write_text("TODO fix this\n")
        add_all(git_repo)
        commit(git_repo, "add file")
        cmds = _make_commands()
        result = cmds.search(str(git_repo), {"pattern": "todo", "ignore_case": True})
        assert result["success"]
        assert result["result"]["count"] == 1

    def test_search_no_matches(self, git_repo):
        cmds = _make_commands()
        result = cmds.search(str(git_repo), {"pattern": "zzzznonexistent"})
        assert result["success"]
        assert result["result"]["count"] == 0

    def test_search_max_count(self, git_repo):
        for i in range(10):
            (git_repo / f"f{i}.txt").write_text("match_me\n")
        add_all(git_repo)
        commit(git_repo, "add many files")
        cmds = _make_commands()
        result = cmds.search(str(git_repo), {"pattern": "match_me", "max_count": 3})
        assert result["success"]
        assert result["result"]["count"] == 3


class TestFind:
    def test_find_requires_pattern_or_extension(self, git_repo):
        cmds = _make_commands()
        result = cmds.find(str(git_repo), {})
        assert not result["success"]

    def test_find_by_extension(self, git_repo):
        (git_repo / "a.js").write_text("x\n")
        (git_repo / "b.py").write_text("x\n")
        add_all(git_repo)
        commit(git_repo, "add files")
        cmds = _make_commands()
        result = cmds.find(str(git_repo), {"extension": "js"})
        assert result["success"]
        assert "a.js" in result["result"]["files"]
        assert "b.py" not in result["result"]["files"]

    def test_find_by_pattern(self, git_repo):
        (git_repo / "config.yaml").write_text("x\n")
        (git_repo / "config.json").write_text("x\n")
        (git_repo / "other.txt").write_text("x\n")
        add_all(git_repo)
        commit(git_repo, "add files")
        cmds = _make_commands()
        result = cmds.find(str(git_repo), {"pattern": "config*"})
        assert result["success"]
        assert result["result"]["count"] == 2
        assert all("config" in f for f in result["result"]["files"])

    def test_find_no_matches(self, git_repo):
        cmds = _make_commands()
        result = cmds.find(str(git_repo), {"extension": "xyz"})
        assert result["success"]
        assert result["result"]["count"] == 0

    def test_find_max_count(self, git_repo):
        for i in range(10):
            (git_repo / f"f{i}.txt").write_text("x\n")
        add_all(git_repo)
        commit(git_repo, "add files")
        cmds = _make_commands()
        result = cmds.find(str(git_repo), {"extension": "txt", "max_count": 3})
        assert result["success"]
        assert result["result"]["count"] == 3


# ── Dispatch table tests ──

class TestDispatchTable:
    def test_dispatch_table_has_all_commands(self):
        cmds = _make_commands()
        table = cmds.dispatch_table()
        expected = {
            "dev_checkpoint", "dev_commit", "dev_push", "dev_sync",
            "dev_file_restore", "dev_log", "dev_status", "dev_diff",
            "dev_show", "dev_file_history", "dev_file_owner",
            "dev_search", "dev_find",
        }
        assert set(table.keys()) == expected

    def test_dispatch_table_callables(self):
        cmds = _make_commands()
        table = cmds.dispatch_table()
        for name, handler in table.items():
            assert callable(handler), f"{name} is not callable"
