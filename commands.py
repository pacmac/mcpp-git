"""Git command handlers for MCP tools.

All handlers accept (workspace_dir, args) and return a dict with
{success, result, display?, error?}.

Context (user/project/task/step) is read directly from tool args.
User defaults to OS username when omitted.
"""

from __future__ import annotations

import getpass
import os
from typing import Any

from pathlib import Path
import importlib.util
import sys

_mod_dir = Path(__file__).resolve().parent


def _load_sibling(name: str):
    """Import a sibling .py file from the same directory."""
    mod_name = f"mcpp_git.{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _mod_dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


git = _load_sibling("git")
_config_mod = _load_sibling("config")

get_config = _config_mod.get_config


def _user_from_args(args: dict[str, Any]) -> str:
    """Extract user from args, falling back to OS username."""
    return args.get("user") or getpass.getuser().lower()


def _tag_from_args(args: dict[str, Any], **overrides) -> git.McppTag:
    """Build an McppTag from tool args with optional field overrides."""
    return git.McppTag(
        ver=overrides.get("ver", args.get("ver")),
        user=overrides.get("user", _user_from_args(args)),
        project=overrides.get("project", args.get("project")),
        task=overrides.get("task", args.get("task")),
        step=overrides.get("step", args.get("step")),
        flags=overrides.get("flags", args.get("flags")),
        sid=overrides.get("sid", args.get("sid")),
        notes=overrides.get("notes", args.get("notes")),
    )


class GitCommands:
    """Collection of git command handlers."""

    def _resolve_git_dir(self, workspace_dir: str) -> str:
        """Resolve the git working directory for the current user."""
        cfg = get_config(workspace_dir)
        if not cfg.get("enable_worktrees", False):
            return workspace_dir
        user = (os.environ.get("USER") or os.environ.get("USERNAME") or "default").lower()
        return git.resolve_workspace(workspace_dir, user, True)

    @staticmethod
    def _commit_per_file(git_dir: str, message: str, tag: git.McppTag) -> list[dict]:
        """Commit each changed file individually. Returns list of {sha, file, ver, sid}."""
        changed = git.status_porcelain(git_dir)
        results = []
        for item in changed:
            filepath = item["path"]
            ver = git.file_commit_count(git_dir, filepath) + 1
            git.add_file(git_dir, filepath)
            if not git.is_staged(git_dir, filepath):
                continue  # gitlink with unchanged SHA or already-clean entry
            # Per-file tag carries ver and notes; sid filled after commit
            file_tag = git.McppTag(
                ver=str(ver),
                user=tag.user,
                project=tag.project,
                task=tag.task,
                step=tag.step,
                flags=tag.flags,
                notes=message,
            )
            full_message = git.build_message(message, tag, [(filepath, file_tag)])
            sha = git.commit(git_dir, full_message)
            sid = sha[:8]
            results.append({"sha": sha, "sid": sid, "file": filepath, "ver": ver})
        return results

    def checkpoint(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Save current state as a checkpoint commit."""
        git_dir = self._resolve_git_dir(workspace_dir)

        if git.is_clean(git_dir):
            return {"success": False, "error": "Nothing to checkpoint — working tree is clean."}

        message = args.get("message")
        if not message:
            task = args.get("task")
            step = args.get("step")
            if step is not None and task:
                message = f"checkpoint: {task} step {step}"
            elif task:
                message = f"checkpoint: {task}"
            else:
                message = "checkpoint"

        tag = _tag_from_args(args)
        results = self._commit_per_file(git_dir, message, tag)
        files = [r["file"] for r in results]

        display = f"Checkpoint — {len(results)} commit(s)\n"
        for r in results:
            display += f"  {r['sid']} v{r['ver']} {r['file']}\n"

        return {
            "success": True,
            "result": {"commits": results, "files": files, "message": message},
            "display": display,
        }

    def commit(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Commit with a meaningful message."""
        message = args.get("message")
        if not message:
            return {"success": False, "error": "message is required"}

        git_dir = self._resolve_git_dir(workspace_dir)

        if git.is_clean(git_dir):
            return {"success": False, "error": "Nothing to commit — working tree is clean."}

        tag = _tag_from_args(args)
        results = self._commit_per_file(git_dir, message, tag)
        files = [r["file"] for r in results]

        display = f"Committed — {len(results)} file(s): {message}\n"
        for r in results:
            display += f"  {r['sid']} v{r['ver']} {r['file']}\n"

        return {
            "success": True,
            "result": {"commits": results, "files": files, "message": message},
            "display": display,
        }

    def push(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Pull (fast-forward only) then push."""
        git_dir = self._resolve_git_dir(workspace_dir)

        if not git.has_remote(git_dir):
            return {"success": False, "error": "No remote configured."}

        ok, msg = git.pull_ff_only(git_dir)
        if not ok:
            if "no tracking information" not in msg.lower() and "no such ref" not in msg.lower():
                return {
                    "success": False,
                    "error": f"Pull failed (remote has diverged): {msg}",
                    "display": f"Pull failed: {msg}\nResolve manually before pushing.",
                }

        ok, msg = git.push(git_dir)
        if not ok:
            return {"success": False, "error": f"Push failed: {msg}"}

        branch = git.current_branch(git_dir)
        display = f"Pushed **{branch}** to remote."
        return {"success": True, "result": {"branch": branch, "message": msg}, "display": display}

    def sync(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Merge the current user's worktree branch into main and push."""
        cfg = get_config(workspace_dir)

        if not cfg.get("enable_worktrees", False):
            return {"success": False, "error": "Worktrees are not enabled (enable_worktrees: false in config.yaml)."}

        user = (os.environ.get("USER") or os.environ.get("USERNAME") or "default").lower()
        user_branch = git.worktree_branch_for_user(user)

        repo_dir = workspace_dir

        main_branch = git.current_branch(repo_dir)

        if git.has_remote(repo_dir):
            ok, msg = git.pull_ff_only(repo_dir)
            if not ok:
                return {
                    "success": False,
                    "error": f"Pull failed on {main_branch}: {msg}",
                    "display": f"Cannot sync — {main_branch} has diverged from remote.\nResolve manually.",
                }

        ok, msg = git.merge_branch(repo_dir, user_branch)
        if not ok:
            git._run(["merge", "--abort"], repo_dir, check=False)
            return {
                "success": False,
                "error": f"Merge of {user_branch} into {main_branch} failed: {msg}",
                "display": f"Merge conflict — {user_branch} could not be cleanly merged into {main_branch}.\nResolve manually.",
            }

        push_msg = ""
        if git.has_remote(repo_dir):
            ok, push_result = git.push(repo_dir)
            if not ok:
                push_msg = f"\nPush failed: {push_result}"
            else:
                push_msg = "\nPushed to remote."

        display = f"Merged **{user_branch}** into **{main_branch}**.{push_msg}"
        return {
            "success": True,
            "result": {"user_branch": user_branch, "main_branch": main_branch},
            "display": display,
        }

    def file_restore(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Restore a single file from a specific commit using git checkout."""
        sha = args.get("sha")
        filepath = args.get("file")
        if not sha:
            return {"success": False, "error": "sha is required"}
        if not filepath:
            return {"success": False, "error": "file is required"}

        current_user = _user_from_args(args)
        git_dir = self._resolve_git_dir(workspace_dir)

        commit_msg = git.get_commit_message(git_dir, sha)
        tag = git.parse_tag(commit_msg)
        if not tag:
            return {"success": False, "error": f"Commit {sha[:8]} has no mcpp tag — cannot verify ownership."}
        if tag.user != current_user:
            return {"success": False, "error": f"Commit {sha[:8]} belongs to user '{tag.user}', not '{current_user}'."}

        files = git.diff_stat(git_dir, sha)
        if filepath not in files:
            return {"success": False, "error": f"File '{filepath}' was not changed in commit {sha[:8]}."}

        owner = git.file_owner(git_dir, filepath)
        if owner and owner != current_user:
            return {
                "success": False,
                "error": f"File '{filepath}' belongs to user '{owner}' — cannot restore.",
            }

        git.checkout_file(git_dir, sha, filepath)

        return {
            "success": True,
            "result": {"sha": sha, "file": filepath},
            "display": f"Restored **{filepath}** from commit **{sha[:8]}** (staged)",
        }

    def log(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Show commit history filtered by user/task/step."""
        git_dir = self._resolve_git_dir(workspace_dir)

        user_filter = args.get("user")
        task_filter = args.get("task")
        step_filter = args.get("step")
        show_all = args.get("show_all", False)
        max_count = args.get("max_count", 50)

        if not show_all and not user_filter:
            user_filter = _user_from_args(args)
        if not show_all and not task_filter:
            task_filter = args.get("task")

        entries = git.log(git_dir, max_count=max_count)

        filtered = []
        for e in entries:
            tag = e.get("tag")
            if not show_all and not tag:
                continue
            if user_filter and (not tag or tag.user != user_filter):
                continue
            if task_filter and (not tag or tag.task != task_filter):
                continue
            if step_filter is not None and (not tag or tag.step != step_filter):
                continue
            filtered.append(e)

        if not filtered:
            return {"success": True, "result": {"entries": []}, "display": "No matching commits."}

        lines = [f"**Log** ({len(filtered)} commits)"]
        for e in filtered:
            sha_short = e["sha"][:8]
            tag = e.get("tag")
            user_str = tag.user if tag else e["author"]
            subject = git.strip_tag(f"{e['subject']}\n{e['body']}").split("\n")[0]
            date_short = e["date"][:10]
            step_str = f" step {tag.step}" if tag and tag.step else ""
            lines.append(f"  {sha_short} {date_short} [{user_str}{step_str}] {subject}")

        result_entries = []
        for e in filtered:
            tag = e.get("tag")
            result_entries.append({
                "sha": e["sha"],
                "date": e["date"],
                "subject": git.strip_tag(f"{e['subject']}\n{e['body']}").split("\n")[0],
                "ver": tag.ver if tag else None,
                "user": tag.user if tag else e["author"],
                "project": tag.project if tag else None,
                "task": tag.task if tag else None,
                "step": tag.step if tag else None,
                "flags": tag.flags if tag else None,
                "sid": tag.sid if tag else None,
                "notes": tag.notes if tag else None,
            })

        return {
            "success": True,
            "result": {"entries": result_entries},
            "display": "\n".join(lines),
        }

    def status(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Show uncommitted changes with user ownership annotations."""
        git_dir = self._resolve_git_dir(workspace_dir)

        entries = git.status_porcelain(git_dir)
        if not entries:
            return {"success": True, "result": {"files": []}, "display": "Working tree is clean."}

        annotated = []
        for e in entries:
            filepath = e["path"]
            last_user = None
            try:
                recent = git.log(git_dir, max_count=5)
                for commit_entry in recent:
                    files_in_commit = git.diff_stat(git_dir, commit_entry["sha"])
                    if filepath in files_in_commit:
                        tag = commit_entry.get("tag")
                        if tag and tag.user:
                            last_user = tag.user
                        break
            except Exception:
                pass

            annotated.append({
                "status": e["status"],
                "path": filepath,
                "last_user": last_user,
            })

        status_map = {"M": "modified", "A": "added", "D": "deleted", "??": "new", "MM": "modified"}
        lines = [f"**Status** ({len(annotated)} files)"]
        for a in annotated:
            status_label = status_map.get(a["status"], a["status"])
            user_str = f" [{a['last_user']}]" if a["last_user"] else ""
            lines.append(f"  {status_label}: {a['path']}{user_str}")

        return {
            "success": True,
            "result": {"files": annotated},
            "display": "\n".join(lines),
        }

    def show(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Show full details of a specific commit."""
        sha = args.get("sha")
        if not sha:
            return {"success": False, "error": "sha is required"}

        git_dir = self._resolve_git_dir(workspace_dir)

        try:
            info = git.show_commit(git_dir, sha)
        except git.GitError as e:
            return {"success": False, "error": str(e)}

        clean_subject = git.strip_tag(info["subject"])
        clean_body = git.strip_tag(info["body"])

        display_lines = [
            f"**{info['sha'][:8]}** by {info['author']} on {info['date']}",
            f"**{clean_subject}**",
        ]
        if clean_body:
            display_lines.append(clean_body)
        if info["diff"]:
            diff_display = info["diff"]
            if len(diff_display) > 5000:
                diff_display = diff_display[:5000] + f"\n... ({len(info['diff'])} chars total, truncated)"
            display_lines.append(f"```diff\n{diff_display}\n```")
        else:
            display_lines.append("No file changes.")

        return {
            "success": True,
            "result": info,
            "display": "\n".join(display_lines),
        }

    def file_history(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Show line-by-line authorship of a file."""
        filepath = args.get("file")
        if not filepath:
            return {"success": False, "error": "file is required"}

        git_dir = self._resolve_git_dir(workspace_dir)

        try:
            result = git._run(["blame", filepath], git_dir)
        except git.GitError as e:
            return {"success": False, "error": str(e)}

        output = result.stdout.strip()
        if not output:
            return {"success": False, "error": f"No blame output for '{filepath}'."}

        display = output
        if len(display) > 5000:
            display = display[:5000] + f"\n... ({len(output)} chars total, truncated)"

        return {
            "success": True,
            "result": {"file": filepath, "blame": output},
            "display": f"```\n{display}\n```",
        }

    def file_owner(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Show who last modified a file."""
        filepath = args.get("file")
        if not filepath:
            return {"success": False, "error": "file is required"}

        git_dir = self._resolve_git_dir(workspace_dir)

        owner = git.file_owner(git_dir, filepath)
        if owner is None:
            return {
                "success": True,
                "result": {"file": filepath, "owner": None},
                "display": f"**{filepath}** — owner unknown (no mcpp metadata)",
            }

        return {
            "success": True,
            "result": {"file": filepath, "owner": owner},
            "display": f"**{filepath}** — owned by **{owner}**",
        }

    def diff(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Show diff between checkpoints or since last checkpoint."""
        git_dir = self._resolve_git_dir(workspace_dir)
        current_user = _user_from_args(args)
        current_task = args.get("task")

        from_ref = args.get("from")
        to_ref = args.get("to")

        if from_ref and to_ref:
            diff_text = git.diff_range(git_dir, from_ref, to_ref)
        elif from_ref:
            diff_text = git.diff_working(git_dir, from_ref)
        else:
            entries = git.log(git_dir, max_count=100)
            last_sha = None
            for e in entries:
                tag = e.get("tag")
                if tag and tag.user == current_user:
                    if current_task is None or tag.task == current_task:
                        last_sha = e["sha"]
                        break

            if last_sha:
                diff_text = git.diff_working(git_dir, last_sha)
            else:
                diff_text = git.diff_working(git_dir, "HEAD")

        if not diff_text.strip():
            return {"success": True, "result": {"diff": ""}, "display": "No differences."}

        display = diff_text
        if len(display) > 5000:
            display = display[:5000] + f"\n... ({len(diff_text)} chars total, truncated)"

        return {
            "success": True,
            "result": {"diff": diff_text},
            "display": f"```diff\n{display}\n```",
        }

    def search(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Search file contents using grep -r."""
        pattern = args.get("pattern")
        if not pattern:
            return {"success": False, "error": "pattern is required"}

        git_dir = self._resolve_git_dir(workspace_dir)
        include = args.get("include")
        max_results = args.get("max_count", 200)
        context_lines = args.get("context", 0)
        ignore_case = args.get("ignore_case", False)

        try:
            entries = git.grep_files(
                git_dir, pattern,
                include=include,
                max_results=max_results,
                context_lines=context_lines,
                ignore_case=ignore_case,
            )
        except git.GitError as e:
            return {"success": False, "error": str(e)}

        if not entries:
            return {"success": True, "result": {"matches": [], "count": 0}, "display": "No matches."}

        lines = [f"**{len(entries)} match(es)**"]
        for e in entries:
            lines.append(f"  {e['path']}:{e['line']}: {e['text']}")
        if len(entries) >= max_results:
            lines.append(f"  ... (limited to {max_results})")

        return {
            "success": True,
            "result": {"matches": entries, "count": len(entries)},
            "display": "\n".join(lines),
        }

    def find(self, workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
        """Find files by name pattern or extension."""
        git_dir = self._resolve_git_dir(workspace_dir)
        pattern = args.get("pattern")
        extension = args.get("extension")
        max_results = args.get("max_count", 500)

        if not pattern and not extension:
            return {"success": False, "error": "pattern or extension is required"}

        files = git.find_files(git_dir, pattern=pattern, extension=extension, max_results=max_results)

        if not files:
            return {"success": True, "result": {"files": [], "count": 0}, "display": "No files found."}

        lines = [f"**{len(files)} file(s)**"]
        for f in files:
            lines.append(f"  {f}")
        if len(files) >= max_results:
            lines.append(f"  ... (limited to {max_results})")

        return {
            "success": True,
            "result": {"files": files, "count": len(files)},
            "display": "\n".join(lines),
        }

    def dispatch_table(self) -> dict[str, Any]:
        """Return a name→handler mapping for MCP tool dispatch."""
        return {
            "dev_checkpoint": self.checkpoint,
            "dev_commit": self.commit,
            "dev_push": self.push,
            "dev_sync": self.sync,
            "dev_file_restore": self.file_restore,
            "dev_log": self.log,
            "dev_status": self.status,
            "dev_diff": self.diff,
            "dev_show": self.show,
            "dev_file_history": self.file_history,
            "dev_file_owner": self.file_owner,
            "dev_search": self.search,
            "dev_find": self.find,
        }
