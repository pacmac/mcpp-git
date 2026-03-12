# mcpp-git

Git version control for AI coding agents. Gives Claude Code (or any MCP-compatible agent) per-file commit tracking, multi-user ownership, and structured metadata that works across git, deployment, and system updates.

> **Designed for machines and humans.** Every commit carries structured `[mcpp:key=val,...]` metadata that is machine-parseable by Node.js, human-readable in audit files, and greppable with standard tools.
>
> **Per-file commits.** Each changed file gets its own commit with version tracking — no more monolithic commits where one file's history is buried inside another's.
>
> **Multi-user safe.** File ownership is tracked per-commit. Restore operations are blocked if the file belongs to another user.

## Why

AI agents working on shared codebases need more than `git add -A && git commit`. They need to know who owns which file, what version a file is at, and whether a restore is safe. mcpp-git wraps git with structured metadata so agents can checkpoint, commit, and restore with full context.

## Metadata format

All metadata uses a unified bracket format:

```
[mcpp:ver=1,user=alice,project=infra,task=tls-upgrade,step=2,flags=l,sid=a3f7b2c,notes=renewed wildcard cert]
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `ver` | string | File version (commit count for that file) |
| `user` | string | User identifier (defaults to OS username) |
| `project` | string | Project name |
| `task` | string | Active task name |
| `step` | integer | Active step number |
| `flags` | string | Compact char flags (e.g. `l` = locked, `lx` = locked + extra) |
| `sid` | string | Short commit ID (first 8 chars of SHA) |
| `notes` | string | Free-text note (always last; quoted if it contains `,` or `]`) |

All fields are optional. Omitted fields don't appear in the output.

### Commit message structure

```
checkpoint: tls-upgrade step 2

nginx.conf [mcpp:ver=12,user=alice,project=infra,task=tls-upgrade,step=2,notes=renewed wildcard cert]
[mcpp:user=alice,project=infra,task=tls-upgrade,step=2]
```

- **Per-file lines**: `filename [mcpp:...]` — one per changed file, carries file-specific metadata (ver, notes)
- **Commit-level tag**: standalone `[mcpp:...]` — last line, summary for grep/filtering

### Parsing

The format is designed for easy parsing:

- **grep**: `git log --grep='\[mcpp:'` finds all mcpp commits
- **Node.js**: split on `[mcpp:`, extract key=value pairs, notes is always last
- **Python**: `parse_tag()` and `parse_file_lines()` in `git.py`

## Installation

mcpp-git is an [mcpp](https://github.com/pacmac/mcpp) tool module. Install it by adding the tool path to your mcpp configuration.

### Prerequisites

- Python 3.10+
- Git
- An MCP-compatible agent (Claude Code, etc.)

### Setup

1. Clone as a sibling to mcpp:

```bash
cd ~/projects
git clone git@github.com:pacmac/mcpp.git
git clone git@github.com:pacmac/mcpp-git.git
```

mcpp's default `tools.yaml` already includes `../mcpp-git`, so no extra configuration is needed if they're side by side.

2. Register the MCP server with Claude Code:

```bash
claude mcp add mcpp --scope user \
  --env MCPP_LOG_LEVEL=error \
  --env MCPP_TIMEOUT_SECONDS=30 \
  -- python3 ~/projects/mcpp/mcpp.py
```

Replace `~/projects` with your install folder.

## Tools

All tools are exposed via MCP with the `dev_` prefix.

### Version control

| Tool | Description |
|------|-------------|
| `dev_checkpoint` | Save current state as a checkpoint (auto or custom message) |
| `dev_commit` | Commit with a meaningful message |
| `dev_push` | Pull (fast-forward) then push to remote |
| `dev_sync` | Merge worktree branch into main and push |

### History & inspection

| Tool | Description |
|------|-------------|
| `dev_log` | Show commit history filtered by user/task/step |
| `dev_status` | Show uncommitted changes with user ownership |
| `dev_diff` | Show changes since last checkpoint or between two points |
| `dev_show` | Show full commit details: author, date, message, diff |

### File operations

| Tool | Description |
|------|-------------|
| `dev_file_restore` | Restore a file from a specific commit (ownership-checked) |
| `dev_file_history` | Show line-by-line authorship (git blame) |
| `dev_file_owner` | Show who last modified a file |

### Search

| Tool | Description |
|------|-------------|
| `dev_search` | Search file contents for a pattern (grep) |
| `dev_find` | Find files by name pattern or extension (git ls-files) |

### Context parameters

`dev_checkpoint`, `dev_commit`, and `dev_file_restore` accept optional context parameters:

| Parameter | Description |
|-----------|-------------|
| `project` | Project name |
| `task` | Active task name |
| `step` | Active step number |
| `user` | User identifier (defaults to OS username) |

These are passed explicitly by the calling agent (e.g. mcpp-plan injects them from the active task).

## How it works

### Per-file commits

When you checkpoint or commit, mcpp-git commits each changed file individually:

1. Detect changed files via `git status --porcelain`
2. For each file: stage it, compute its version (commit count + 1), build the metadata, commit
3. Each commit contains one per-file `[mcpp:...]` line and one commit-level tag

This means every file has its own linear version history, and `dev_log` can filter by file, user, task, or step.

### File ownership

`dev_file_owner` checks per-file metadata first (the `user` field in `[mcpp:...]` lines), then falls back to the commit-level tag. `dev_file_restore` uses this to block restores of files owned by other users.

### Worktrees

When `enable_worktrees: true` in config, each user gets an isolated git worktree:

```
.worktrees/
  alice/    ← mcpp/alice branch
  bob/      ← mcpp/bob branch
```

Users work in parallel without conflicts. `dev_sync` merges a user's branch into main.

## Configuration

Settings live in `config.yaml` in the workspace directory. The file is optional — all keys have sensible defaults.

```yaml
enable_worktrees: false    # give each user their own worktree
```

## Architecture

```
tool.yaml          MCP tool definitions (schema for all dev_* tools)
mcpptool.py        MCP entry point — routes tool calls to GitCommands
commands.py        Command handlers (checkpoint, commit, log, diff, etc.)
git.py             Git subprocess wrappers + metadata format (McppTag, parse, build)
config.py          Configuration loading
```

### How a tool call flows

1. MCP host calls `execute("dev_commit", {"message": "fix auth", "user": "alice", "task": "t1"}, {"workspace_dir": "/my/project"})`
2. `mcpptool.py` routes to `GitCommands.commit()`
3. Handler builds `McppTag` from args, calls `_commit_per_file()`
4. Each file is staged, committed with metadata, result returned
5. Response includes structured data and a `display` string for the user

## Testing

```bash
python -m pytest tests/ -v
```

Tests cover tag parsing, file operations, per-file commits, worktree isolation, multi-user scenarios, and all command handlers.

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/)

Free for personal use, research, education, non-profits, and government. Not permitted for commercial use. See [LICENSE](LICENSE) for the full text.
