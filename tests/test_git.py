"""Tests for git.py — tag parsing, git operations, multi-user scenarios, logging."""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from mcpp_git.git import (
    McppTag,
    parse_tag,
    parse_file_lines,
    build_message,
    strip_tag,
    GitError,
    status_porcelain,
    add_all,
    commit,
    log,
    diff_stat,
    diff_range,
    diff_working,
    checkout_file,
    file_owner,
    show_commit,
    is_clean,
    add_file,
    file_commit_count,
    current_branch,
    has_remote,
    get_commit_message,
    log_file_since,
    worktree_path_for_user,
    worktree_branch_for_user,
    worktree_list,
    worktree_add,
    worktree_remove,
    worktree_exists,
    ensure_worktree,
    resolve_workspace,
    merge_branch,
    branch_exists,
    _ensure_git_exclude,
    WORKTREE_DIR,
    _run,
    push,
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
    # Initial commit
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
    # Initial commit
    (local / "README.md").write_text("# Test repo\n")
    subprocess.run(["git", "add", "-A"], cwd=str(local), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(local), capture_output=True, check=True
    )
    subprocess.run(["git", "push"], cwd=str(local), capture_output=True, check=True)
    return bare, local


# ── Tag parsing tests ──

class TestTagParsing:
    def test_parse_full_tag(self):
        msg = "checkpoint: step 3\n[mcpp:user=alice,task=build-auth,step=3]"
        tag = parse_tag(msg)
        assert tag is not None
        assert tag.user == "alice"
        assert tag.task == "build-auth"
        assert tag.step == 3

    def test_parse_partial_tag_no_step(self):
        msg = "some commit\n[mcpp:user=bob,task=fix-bug]"
        tag = parse_tag(msg)
        assert tag is not None
        assert tag.user == "bob"
        assert tag.task == "fix-bug"
        assert tag.step is None

    def test_parse_user_only(self):
        msg = "[mcpp:user=charlie]"
        tag = parse_tag(msg)
        assert tag is not None
        assert tag.user == "charlie"
        assert tag.task is None
        assert tag.step is None

    def test_parse_no_tag(self):
        msg = "just a regular commit message"
        tag = parse_tag(msg)
        assert tag is None

    def test_parse_malformed_tag(self):
        msg = "[mcpp:broken"
        tag = parse_tag(msg)
        assert tag is None

    def test_parse_empty_message(self):
        tag = parse_tag("")
        assert tag is None

    def test_roundtrip(self):
        original = McppTag(user="alice", task="my-task", step=5)
        formatted = original.format()
        parsed = parse_tag(formatted)
        assert parsed == original

    def test_roundtrip_full(self):
        original = McppTag(ver="3", user="alice", project="infra", task="deploy",
                           step=2, flags="l", sid="a3f7b2c", notes="test note")
        formatted = original.format()
        parsed = parse_tag(formatted)
        assert parsed == original

    def test_format_tag(self):
        tag = McppTag(user="alice", task="build-auth", step=3)
        assert tag.format() == "[mcpp:user=alice,task=build-auth,step=3]"

    def test_format_full(self):
        tag = McppTag(ver="1", user="alice", project="infra", task="t", step=3, flags="l", sid="abc1234")
        assert tag.format() == "[mcpp:ver=1,user=alice,project=infra,task=t,step=3,flags=l,sid=abc1234]"

    def test_format_partial(self):
        tag = McppTag(user="bob")
        assert tag.format() == "[mcpp:user=bob]"

    def test_format_notes_quoted(self):
        tag = McppTag(user="alice", notes="rolled back, retrying")
        assert tag.format() == '[mcpp:user=alice,notes="rolled back, retrying"]'

    def test_parse_notes_quoted(self):
        msg = '[mcpp:user=alice,notes="rolled back, retrying"]'
        tag = parse_tag(msg)
        assert tag.user == "alice"
        assert tag.notes == "rolled back, retrying"

    def test_parse_notes_unquoted(self):
        msg = "[mcpp:user=alice,notes=simple note]"
        tag = parse_tag(msg)
        assert tag.notes == "simple note"

    def test_build_message(self):
        tag = McppTag(user="alice", task="t", step=1)
        msg = build_message("checkpoint: test", tag)
        assert "checkpoint: test" in msg
        assert "[mcpp:user=alice,task=t,step=1]" in msg

    def test_strip_tag(self):
        msg = "checkpoint: test\n[mcpp:user=alice,task=t,step=1]"
        stripped = strip_tag(msg)
        assert stripped == "checkpoint: test"

    def test_strip_tag_no_tag(self):
        msg = "just a message"
        assert strip_tag(msg) == "just a message"

    def test_unknown_keys_ignored(self):
        msg = "[mcpp:user=alice,foo=bar,task=t]"
        tag = parse_tag(msg)
        assert tag.user == "alice"
        assert tag.task == "t"

    def test_step_non_integer(self):
        msg = "[mcpp:user=alice,step=abc]"
        tag = parse_tag(msg)
        assert tag.user == "alice"
        assert tag.step is None


# ── File line tests ──

class TestFileLines:
    def test_parse_file_lines_empty(self):
        assert parse_file_lines("just a message") == []

    def test_parse_file_lines_single(self):
        msg = "fix stuff\n\nauth.py [mcpp:user=CLS,task=t,step=1,notes=fixed bug]\n[mcpp:user=CLS,task=t,step=1]"
        entries = parse_file_lines(msg)
        assert len(entries) == 1
        name, ftag = entries[0]
        assert name == "auth.py"
        assert ftag.user == "CLS"
        assert ftag.notes == "fixed bug"

    def test_parse_file_lines_multiple(self):
        msg = (
            "fix stuff\n\n"
            "auth.py [mcpp:user=CLS,notes=fixed bug]\n"
            "db.py [mcpp:user=CLS,notes=added index]\n"
            "[mcpp:user=CLS]"
        )
        entries = parse_file_lines(msg)
        assert len(entries) == 2
        assert entries[0][0] == "auth.py"
        assert entries[1][0] == "db.py"
        assert entries[1][1].notes == "added index"

    def test_parse_file_lines_with_version_and_flags(self):
        msg = "build\n\napp.js [mcpp:ver=3,user=PAC,flags=L,notes=locked for release]\n[mcpp:user=PAC]"
        entries = parse_file_lines(msg)
        assert len(entries) == 1
        _, ftag = entries[0]
        assert ftag.ver == "3"
        assert ftag.flags == "L"

    def test_parse_file_lines_ignores_non_tagged_lines(self):
        msg = "message\n\nsome random text\nauth.py [mcpp:user=CLS,notes=note]\nanother line\n[mcpp:user=CLS]"
        entries = parse_file_lines(msg)
        assert len(entries) == 1
        assert entries[0][0] == "auth.py"

    def test_build_message_with_file_tags(self):
        tag = McppTag(user="CLS", task="build-auth", step=3)
        file_tags = [
            ("auth.py", McppTag(user="CLS", notes="fixed bug")),
            ("db.py", McppTag(user="CLS", notes="added index")),
        ]
        msg = build_message("auth fixes", tag, file_tags)
        lines = msg.splitlines()
        assert lines[0] == "auth fixes"
        assert lines[1] == ""
        assert lines[2] == "auth.py [mcpp:user=CLS,notes=fixed bug]"
        assert lines[3] == "db.py [mcpp:user=CLS,notes=added index]"
        assert lines[4] == "[mcpp:user=CLS,task=build-auth,step=3]"

    def test_build_message_without_file_tags(self):
        tag = McppTag(user="CLS", task="t", step=1)
        msg = build_message("checkpoint", tag)
        assert msg == "checkpoint\n[mcpp:user=CLS,task=t,step=1]"

    def test_build_message_empty_file_list(self):
        tag = McppTag(user="CLS", task="t", step=1)
        msg = build_message("checkpoint", tag, [])
        assert msg == "checkpoint\n[mcpp:user=CLS,task=t,step=1]"

    def test_roundtrip_file_tags(self):
        tag = McppTag(user="CLS", task="t", step=1)
        file_tags = [
            ("a.py", McppTag(user="CLS", notes="note a")),
            ("b.py", McppTag(ver="2", user="PAC", flags="L", notes="note b")),
        ]
        msg = build_message("test", tag, file_tags)
        parsed_tag = parse_tag(msg)
        parsed_files = parse_file_lines(msg)
        assert parsed_tag == tag
        assert len(parsed_files) == 2
        assert parsed_files[0][0] == "a.py"
        assert parsed_files[1][1].ver == "2"
        assert parsed_files[1][1].flags == "L"

    def test_strip_tag_removes_file_lines(self):
        msg = "fix stuff\n\nauth.py [mcpp:user=CLS,notes=fixed bug]\ndb.py [mcpp:user=CLS,notes=index]\n[mcpp:user=CLS,task=t,step=1]"
        stripped = strip_tag(msg)
        assert stripped == "fix stuff"

    def test_strip_tag_preserves_message_only(self):
        msg = "multi line\nmessage body\n\nauth.py [mcpp:user=CLS,notes=note]\n[mcpp:user=CLS]"
        stripped = strip_tag(msg)
        assert "multi line" in stripped
        assert "message body" in stripped
        assert "auth.py" not in stripped
        assert "[mcpp:" not in stripped


# ── Git operation tests ──

class TestGitOperations:
    def test_status_clean(self, git_repo):
        entries = status_porcelain(git_repo)
        assert entries == []

    def test_status_modified(self, git_repo):
        (git_repo / "new_file.txt").write_text("hello\n")
        entries = status_porcelain(git_repo)
        assert len(entries) == 1
        assert entries[0]["path"] == "new_file.txt"

    def test_is_clean(self, git_repo):
        assert is_clean(git_repo)
        (git_repo / "x.txt").write_text("x\n")
        assert not is_clean(git_repo)

    def test_add_and_commit(self, git_repo):
        (git_repo / "file.txt").write_text("content\n")
        add_all(git_repo)
        sha = commit(git_repo, "test commit")
        assert len(sha) == 40
        assert is_clean(git_repo)

    def test_commit_with_tag(self, git_repo):
        (git_repo / "file.txt").write_text("content\n")
        tag = McppTag(user="alice", task="my-task", step=1)
        msg = build_message("checkpoint: step 1", tag)
        add_all(git_repo)
        sha = commit(git_repo, msg)
        full_msg = get_commit_message(git_repo, sha)
        parsed = parse_tag(full_msg)
        assert parsed is not None
        assert parsed.user == "alice"
        assert parsed.task == "my-task"
        assert parsed.step == 1

    def test_diff_stat(self, git_repo):
        (git_repo / "a.txt").write_text("aaa\n")
        (git_repo / "b.txt").write_text("bbb\n")
        add_all(git_repo)
        sha = commit(git_repo, "add two files")
        files = diff_stat(git_repo, sha)
        assert set(files) == {"a.txt", "b.txt"}

    def test_current_branch(self, git_repo):
        branch = current_branch(git_repo)
        assert branch in ("master", "main")

    def test_has_remote_false(self, git_repo):
        assert not has_remote(git_repo)

    def test_has_remote_true(self, git_repo_pair):
        _, local = git_repo_pair
        assert has_remote(local)

    def test_log_entries(self, git_repo):
        (git_repo / "f1.txt").write_text("1\n")
        add_all(git_repo)
        tag = McppTag(user="alice", task="t1", step=1)
        commit(git_repo, build_message("first", tag))

        (git_repo / "f2.txt").write_text("2\n")
        add_all(git_repo)
        tag2 = McppTag(user="bob", task="t2", step=2)
        commit(git_repo, build_message("second", tag2))

        entries = log(git_repo, max_count=10)
        # Most recent first
        assert len(entries) >= 2
        assert entries[0]["tag"].user == "bob"
        assert entries[1]["tag"].user == "alice"

    def test_log_empty_repo(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        entries = log(tmp_path, max_count=10)
        assert entries == []


# ── Checkout / restore tests ──

class TestCheckoutFile:
    def test_checkout_file_restores_content(self, git_repo):
        (git_repo / "file.txt").write_text("original\n")
        add_all(git_repo)
        sha1 = commit(git_repo, "add file")

        (git_repo / "file.txt").write_text("modified\n")
        add_all(git_repo)
        commit(git_repo, "modify file")

        checkout_file(git_repo, sha1, "file.txt")
        assert (git_repo / "file.txt").read_text() == "original\n"

    def test_checkout_file_auto_stages(self, git_repo):
        (git_repo / "file.txt").write_text("v1\n")
        add_all(git_repo)
        sha1 = commit(git_repo, "v1")

        (git_repo / "file.txt").write_text("v2\n")
        add_all(git_repo)
        commit(git_repo, "v2")

        checkout_file(git_repo, sha1, "file.txt")
        entries = status_porcelain(git_repo)
        assert any(e["path"] == "file.txt" for e in entries)

    def test_checkout_file_nonexistent_raises(self, git_repo):
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(git_repo),
            capture_output=True, text=True
        ).stdout.strip()
        with pytest.raises(GitError):
            checkout_file(git_repo, sha, "no-such-file.txt")


class TestFileOwner:
    def test_file_owner_from_file_metadata(self, git_repo):
        tag = McppTag(user="alice", task="t1", step=1)
        ft = ("owned.txt", McppTag(user="alice", notes="test"))
        (git_repo / "owned.txt").write_text("content\n")
        add_all(git_repo)
        commit(git_repo, build_message("alice adds", tag, [ft]))

        assert file_owner(git_repo, "owned.txt") == "alice"

    def test_file_owner_fallback_to_tag(self, git_repo):
        tag = McppTag(user="bob", task="t1", step=1)
        (git_repo / "old.txt").write_text("content\n")
        add_all(git_repo)
        commit(git_repo, build_message("bob adds", tag))

        assert file_owner(git_repo, "old.txt") == "bob"

    def test_file_owner_unknown(self, git_repo):
        assert file_owner(git_repo, "README.md") is None

    def test_file_owner_nonexistent(self, git_repo):
        assert file_owner(git_repo, "no-such-file.txt") is None


# ── Show / blame tests ──

class TestShowCommit:
    def test_show_commit_details(self, git_repo):
        (git_repo / "file.txt").write_text("content\n")
        add_all(git_repo)
        sha = commit(git_repo, "add a file")

        info = show_commit(git_repo, sha)
        assert info["sha"] == sha
        assert info["author"] == "Test User"
        assert "add a file" in info["subject"]
        assert "file.txt" in info["diff"]

    def test_show_commit_invalid_sha(self, git_repo):
        with pytest.raises(GitError):
            show_commit(git_repo, "deadbeef1234567890")


class TestBlame:
    def test_blame_output(self, git_repo):
        result = _run(["blame", "README.md"], git_repo)
        assert "Test User" in result.stdout
        assert "# Test repo" in result.stdout

    def test_blame_nonexistent_file(self, git_repo):
        with pytest.raises(GitError):
            _run(["blame", "no-such-file.txt"], git_repo)


class TestLogFileSince:
    def test_log_file_since(self, git_repo):
        (git_repo / "shared.txt").write_text("v1\n")
        add_all(git_repo)
        tag1 = McppTag(user="alice", task="t1", step=1)
        sha1 = commit(git_repo, build_message("alice adds", tag1))

        (git_repo / "shared.txt").write_text("v2\n")
        add_all(git_repo)
        tag2 = McppTag(user="bob", task="t2", step=1)
        commit(git_repo, build_message("bob modifies", tag2))

        entries = log_file_since(git_repo, sha1, "shared.txt")
        assert len(entries) == 1
        assert entries[0]["tag"].user == "bob"

    def test_log_file_since_no_changes(self, git_repo):
        (git_repo / "mine.txt").write_text("v1\n")
        add_all(git_repo)
        tag1 = McppTag(user="alice", task="t1", step=1)
        sha1 = commit(git_repo, build_message("alice adds", tag1))

        entries = log_file_since(git_repo, sha1, "mine.txt")
        assert entries == []


# ── Push tests ──

class TestPush:
    def test_push_success(self, git_repo_pair):
        _, local = git_repo_pair
        (local / "new.txt").write_text("new\n")
        add_all(local)
        commit(local, "new file")
        ok, msg = push(local)
        assert ok

    def test_push_no_remote(self, git_repo):
        ok, msg = push(git_repo)
        assert not ok


# ── Edge case tests ──

class TestEdgeCases:
    def test_commit_empty_repo_fails(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True, check=True
        )
        with pytest.raises(GitError):
            commit(tmp_path, "should fail")

    def test_get_commit_message(self, git_repo):
        (git_repo / "x.txt").write_text("x\n")
        add_all(git_repo)
        sha = commit(git_repo, "test message here")
        msg = get_commit_message(git_repo, sha)
        assert "test message here" in msg

    def test_diff_working(self, git_repo):
        (git_repo / "file.txt").write_text("new content\n")
        d = diff_working(git_repo)
        add_all(git_repo)
        d = diff_working(git_repo, "HEAD")
        assert "new content" in d

    def test_diff_range(self, git_repo):
        (git_repo / "a.txt").write_text("1\n")
        add_all(git_repo)
        sha1 = commit(git_repo, "first")

        (git_repo / "a.txt").write_text("2\n")
        add_all(git_repo)
        sha2 = commit(git_repo, "second")

        d = diff_range(git_repo, sha1, sha2)
        assert "a.txt" in d


# ── Logging tests ──

class TestGitLogging:
    def test_run_logs_command(self, git_repo, caplog):
        with caplog.at_level(logging.DEBUG, logger="mcpp_git"):
            status_porcelain(git_repo)
        assert any("running: git status --porcelain" in r.message for r in caplog.records)

    def test_run_logs_completion_time(self, git_repo, caplog):
        with caplog.at_level(logging.DEBUG, logger="mcpp_git"):
            status_porcelain(git_repo)
        assert any("completed in" in r.message and "rc=0" in r.message for r in caplog.records)

    def test_run_logs_error(self, git_repo, caplog):
        with caplog.at_level(logging.DEBUG, logger="mcpp_git"):
            try:
                _run(["log", "--invalid-flag-xyz"], git_repo)
            except GitError:
                pass
        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_run_logs_stderr(self, git_repo, caplog):
        with caplog.at_level(logging.DEBUG, logger="mcpp_git"):
            try:
                _run(["log", "--invalid-flag-xyz"], git_repo)
            except GitError:
                pass
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_records) > 0


# ── Worktree tests ──

class TestWorktreePaths:
    def test_worktree_path_for_user(self):
        path = worktree_path_for_user("/srv/project", "alice")
        assert path == Path("/srv/project/.worktrees/alice")

    def test_worktree_branch_for_user(self):
        assert worktree_branch_for_user("alice") == "mcpp/alice"

    def test_resolve_workspace_disabled(self, git_repo):
        result = resolve_workspace(str(git_repo), "alice", enable_worktrees=False)
        assert result == str(git_repo)

    def test_resolve_workspace_enabled_gives_worktree(self, git_repo):
        result = resolve_workspace(str(git_repo), "testuser", enable_worktrees=True)
        assert result == str(worktree_path_for_user(git_repo, "testuser"))


class TestWorktreeOperations:
    def test_worktree_list_initial(self, git_repo):
        wts = worktree_list(git_repo)
        assert len(wts) >= 1

    def test_worktree_add_and_exists(self, git_repo):
        wt_path = git_repo / ".worktrees" / "alice"
        worktree_add(git_repo, wt_path, "mcpp/alice")
        assert wt_path.exists()
        assert worktree_exists(git_repo, wt_path)

    def test_worktree_remove(self, git_repo):
        wt_path = git_repo / ".worktrees" / "alice"
        worktree_add(git_repo, wt_path, "mcpp/alice")
        assert worktree_exists(git_repo, wt_path)
        worktree_remove(git_repo, wt_path)
        assert not worktree_exists(git_repo, wt_path)

    def test_ensure_worktree_creates(self, git_repo):
        wt_path = ensure_worktree(git_repo, "bob")
        assert wt_path.exists()
        assert worktree_exists(git_repo, wt_path)
        assert current_branch(wt_path) == "mcpp/bob"

    def test_ensure_worktree_idempotent(self, git_repo):
        wt1 = ensure_worktree(git_repo, "bob")
        wt2 = ensure_worktree(git_repo, "bob")
        assert wt1 == wt2

    def test_worktree_isolation(self, git_repo):
        wt_alice = ensure_worktree(git_repo, "alice")
        wt_bob = ensure_worktree(git_repo, "bob")

        (wt_alice / "alice_file.txt").write_text("alice\n")
        add_all(wt_alice)
        commit(wt_alice, "alice commit")

        assert not (wt_bob / "alice_file.txt").exists()
        assert is_clean(wt_bob)

    def test_worktree_independent_branches(self, git_repo):
        wt_alice = ensure_worktree(git_repo, "alice")
        wt_bob = ensure_worktree(git_repo, "bob")
        assert current_branch(wt_alice) == "mcpp/alice"
        assert current_branch(wt_bob) == "mcpp/bob"


class TestMergeBranch:
    def test_merge_success(self, git_repo):
        wt = ensure_worktree(git_repo, "alice")
        (wt / "new.txt").write_text("from alice\n")
        add_all(wt)
        commit(wt, "alice adds file")

        ok, msg = merge_branch(git_repo, "mcpp/alice")
        assert ok
        assert (git_repo / "new.txt").exists()

    def test_merge_conflict(self, git_repo):
        wt = ensure_worktree(git_repo, "alice")

        (git_repo / "README.md").write_text("main version\n")
        add_all(git_repo)
        commit(git_repo, "main changes README")

        (wt / "README.md").write_text("alice version\n")
        add_all(wt)
        commit(wt, "alice changes README")

        ok, msg = merge_branch(git_repo, "mcpp/alice")
        assert not ok
        subprocess.run(["git", "merge", "--abort"], cwd=str(git_repo), capture_output=True)


# ── Integration tests: full lifecycle with worktrees ──

@pytest.fixture
def worktree_repo(tmp_path):
    """Create a repo with bare remote, suitable for worktree integration tests."""
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
    (local / "README.md").write_text("# Test project\n")
    subprocess.run(["git", "add", "-A"], cwd=str(local), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(local), capture_output=True, check=True
    )
    subprocess.run(["git", "push"], cwd=str(local), capture_output=True, check=True)
    return bare, local


class TestIntegrationFullCycle:
    def test_full_cycle_checkpoint_and_push(self, worktree_repo):
        bare, local = worktree_repo
        wt = ensure_worktree(local, "alice")

        (wt / "feature.py").write_text("print('hello')\n")
        tag = McppTag(user="alice", task="feat", step=1)
        add_all(wt)
        sha = commit(wt, build_message("add feature", tag))

        assert len(sha) == 40
        assert is_clean(wt)
        msg = get_commit_message(wt, sha)
        assert "alice" in msg

        ok, msg = push(wt)
        assert ok

    def test_worktrees_excluded_from_staging(self, worktree_repo):
        _, local = worktree_repo
        ensure_worktree(local, "alice")

        (local / "normal.txt").write_text("should be staged\n")
        add_all(local)

        entries = status_porcelain(local)
        staged_paths = [e["path"] for e in entries]
        for p in staged_paths:
            assert ".worktrees" not in p

    def test_git_exclude_written(self, worktree_repo):
        _, local = worktree_repo
        ensure_worktree(local, "alice")
        exclude_path = local / ".git" / "info" / "exclude"
        assert exclude_path.exists()
        content = exclude_path.read_text()
        assert ".worktrees" in content


class TestIntegrationMultiUser:
    def test_two_users_independent(self, worktree_repo):
        _, local = worktree_repo
        wt_alice = ensure_worktree(local, "alice")
        wt_bob = ensure_worktree(local, "bob")

        (wt_alice / "alice.py").write_text("# alice\n")
        add_all(wt_alice)
        commit(wt_alice, build_message("alice work", McppTag(user="alice", task="t1", step=1)))

        (wt_bob / "bob.py").write_text("# bob\n")
        add_all(wt_bob)
        commit(wt_bob, build_message("bob work", McppTag(user="bob", task="t2", step=1)))

        assert not (wt_alice / "bob.py").exists()
        assert not (wt_bob / "alice.py").exists()

        assert not (local / "alice.py").exists()
        assert not (local / "bob.py").exists()

    def test_users_on_different_branches(self, worktree_repo):
        _, local = worktree_repo
        wt_alice = ensure_worktree(local, "alice")
        wt_bob = ensure_worktree(local, "bob")
        assert current_branch(wt_alice) == "mcpp/alice"
        assert current_branch(wt_bob) == "mcpp/bob"
        main = current_branch(local)
        assert main in ("master", "main")


class TestIntegrationSync:
    def test_sync_merges_to_main(self, worktree_repo):
        bare, local = worktree_repo
        wt = ensure_worktree(local, "alice")

        (wt / "feature.py").write_text("# feature\n")
        add_all(wt)
        commit(wt, build_message("add feature", McppTag(user="alice", task="t1", step=1)))

        ok, msg = merge_branch(local, "mcpp/alice")
        assert ok
        assert (local / "feature.py").exists()

        ok, msg = push(local)
        assert ok

    def test_sync_does_not_affect_other_user(self, worktree_repo):
        _, local = worktree_repo
        wt_alice = ensure_worktree(local, "alice")
        wt_bob = ensure_worktree(local, "bob")

        (wt_alice / "alice.py").write_text("# alice\n")
        add_all(wt_alice)
        commit(wt_alice, "alice work")

        (wt_bob / "bob.py").write_text("# bob\n")
        add_all(wt_bob)
        commit(wt_bob, "bob work")

        ok, _ = merge_branch(local, "mcpp/alice")
        assert ok

        assert not (wt_bob / "alice.py").exists()
        assert (wt_bob / "bob.py").exists()


class TestIntegrationRevertSafety:
    def test_revert_in_worktree_isolated(self, worktree_repo):
        _, local = worktree_repo
        wt_alice = ensure_worktree(local, "alice")
        wt_bob = ensure_worktree(local, "bob")

        (wt_alice / "oops.py").write_text("# mistake\n")
        add_all(wt_alice)
        sha = commit(wt_alice, "alice oops")

        (wt_bob / "good.py").write_text("# good work\n")
        add_all(wt_bob)
        commit(wt_bob, "bob good work")

        subprocess.run(["git", "rm", "oops.py"], cwd=str(wt_alice), capture_output=True, check=True)

        assert not (wt_alice / "oops.py").exists()
        assert (wt_bob / "good.py").exists()
        assert is_clean(wt_bob)


class TestIntegrationEdgeCases:
    def test_branch_already_exists(self, worktree_repo):
        _, local = worktree_repo
        wt = ensure_worktree(local, "alice")
        (wt / "v1.txt").write_text("version 1\n")
        add_all(wt)
        commit(wt, "v1")

        worktree_remove(local, wt)
        assert not worktree_exists(local, wt)
        assert branch_exists(local, "mcpp/alice")

        wt2 = ensure_worktree(local, "alice")
        assert wt2.exists()
        assert (wt2 / "v1.txt").exists()

    def test_stale_directory_recovered(self, worktree_repo):
        _, local = worktree_repo
        stale_path = worktree_path_for_user(local, "alice")
        stale_path.mkdir(parents=True)
        (stale_path / "junk.txt").write_text("leftover\n")

        wt = ensure_worktree(local, "alice")
        assert wt.exists()
        assert not (wt / "junk.txt").exists()
        assert current_branch(wt) == "mcpp/alice"

    def test_git_exclude_idempotent(self, worktree_repo):
        _, local = worktree_repo
        ensure_worktree(local, "alice")
        ensure_worktree(local, "bob")

        exclude_path = local / ".git" / "info" / "exclude"
        content = exclude_path.read_text()
        assert content.count(".worktrees") == 1

    def test_add_all_never_stages_worktrees(self, worktree_repo):
        _, local = worktree_repo
        wt = ensure_worktree(local, "alice")

        (wt / "alice.txt").write_text("alice\n")
        (local / "main.txt").write_text("main\n")

        add_all(local)
        sha = commit(local, "main commit")
        files = diff_stat(local, sha)
        assert "main.txt" in files
        for f in files:
            assert ".worktrees" not in f


class TestPerFileCommit:
    def test_add_file_stages_single(self, git_repo):
        (git_repo / "a.txt").write_text("aaa\n")
        (git_repo / "b.txt").write_text("bbb\n")
        add_file(git_repo, "a.txt")
        entries = status_porcelain(git_repo)
        staged = [e for e in entries if e["status"].startswith("A")]
        unstaged = [e for e in entries if e["status"] == "??"]
        assert len(staged) == 1
        assert staged[0]["path"] == "a.txt"
        assert any(e["path"] == "b.txt" for e in unstaged)

    def test_per_file_commits_distinct_shas(self, git_repo):
        (git_repo / "a.txt").write_text("aaa\n")
        (git_repo / "b.txt").write_text("bbb\n")
        (git_repo / "c.txt").write_text("ccc\n")
        tag = McppTag(user="alice", task="t1", step=1)
        shas = []
        for f in ["a.txt", "b.txt", "c.txt"]:
            add_file(git_repo, f)
            ft = (f, McppTag(ver="1", user="alice", notes="test"))
            msg = build_message("test commit", tag, [ft])
            shas.append(commit(git_repo, msg))
        assert len(set(shas)) == 3
        assert is_clean(git_repo)

    def test_per_file_commit_single_file_tag(self, git_repo):
        (git_repo / "x.txt").write_text("xxx\n")
        tag = McppTag(user="bob", task="t2", step=1)
        add_file(git_repo, "x.txt")
        ft = ("x.txt", McppTag(ver="1", user="bob", notes="first"))
        msg = build_message("add x", tag, [ft])
        sha = commit(git_repo, msg)
        full_msg = get_commit_message(git_repo, sha)
        file_entries = parse_file_lines(full_msg)
        assert len(file_entries) == 1
        name, ftag = file_entries[0]
        assert name == "x.txt"
        assert ftag.ver == "1"

    def test_file_commit_count_new_file(self, git_repo):
        assert file_commit_count(git_repo, "nonexistent.txt") == 0

    def test_file_commit_count_increments(self, git_repo):
        (git_repo / "f.txt").write_text("v1\n")
        add_all(git_repo)
        commit(git_repo, "first")
        assert file_commit_count(git_repo, "f.txt") == 1
        (git_repo / "f.txt").write_text("v2\n")
        add_all(git_repo)
        commit(git_repo, "second")
        assert file_commit_count(git_repo, "f.txt") == 2

    def test_add_file_deleted(self, git_repo):
        (git_repo / "del.txt").write_text("gone\n")
        add_all(git_repo)
        commit(git_repo, "add del.txt")
        (git_repo / "del.txt").unlink()
        add_file(git_repo, "del.txt")
        sha = commit(git_repo, "remove del.txt")
        files = diff_stat(git_repo, sha)
        assert "del.txt" in files
