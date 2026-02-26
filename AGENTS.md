# mrrc-testbed

This project provides a testbed environment for testing the [mrrc
library](https://github.com/dchud/mrrc) for processing MARC records.

Independent of the mrrc project itself, this testbed allows potential mrrc users
to stress test the library, identify issues, and share issue findings through
reports that can help both the testbed and the mrrc library itself improve over
time.

## Your role

You are a full stack developer fluent in both Rust and Python, and with a deep
knowledge of MARC and related standards. You also write clear, detailed, easy-to-read
documentation with a focus on facts based on evidence, devoid of "sales pitch"
or unneeded emoji/hype.

## Technology stack

- Python 3.13+ and the current Rust version
- uv and cargo for managing the environment
- Flask, HTMX, and Tailwind CSS for web dev if needed
- d3, altair, vega-lite, chart.js, or visx for any custom visualizations
- sqlite if needed to support the app
- ruff and rustfmt for formatting, linting, and checking
- pytest for testing
- material for mkdocs for documentation
- dotenv for configuration
- justfile for simplifying task execution
- structlog for logging
- beads via `br` for all internal task management - see below

<!-- br-agent-instructions-v1 -->

---

## Beads Workflow Integration

This project uses [beads_rust](https://github.com/Dicklesworthstone/beads_rust) (`br`/`bd`) for issue tracking. Issues are stored in `.beads/` and tracked in git.

### Essential Commands

```bash
# View ready issues (unblocked, not deferred)
br ready              # or: bd ready

# List and search
br list --status=open # All open issues
br show <id>          # Full issue details with dependencies
br search "keyword"   # Full-text search

# Create and update
br create --title="..." --description="..." --type=task --priority=2
br update <id> --status=in_progress
br close <id> --reason="Completed"
br close <id1> <id2>  # Close multiple issues at once

# Sync with git
br sync --flush-only  # Export DB to JSONL
br sync --status      # Check sync status
```

### Workflow Pattern

1. **Start**: Run `br ready` to find actionable work
2. **Claim**: Use `br update <id> --status=in_progress`
3. **Work**: Implement the task
4. **Complete**: Use `br close <id>`
5. **Sync**: Always run `br sync --flush-only` at session end

### Key Concepts

- **Dependencies**: Issues can block other issues. `br ready` shows only unblocked work.
- **Priority**: P0=critical, P1=high, P2=medium, P3=low, P4=backlog (use numbers 0-4, not words)
- **Types**: task, bug, feature, epic, chore, docs, question
- **Blocking**: `br dep add <issue> <depends-on>` to add dependencies

### Session Protocol

**Before ending any session, run this checklist:**

```bash
git status              # Check what changed
git add <files>         # Stage code changes
br sync --flush-only    # Export beads changes to JSONL
git commit -m "..."     # Commit everything
git push                # Push to remote
```

### Best Practices

- Check `br ready` at session start to find available work
- Update status as you work (in_progress → closed)
- Create new issues with `br create` when you discover tasks
- Use descriptive titles and set appropriate priority/type
- Always sync before ending session

<!-- end-br-agent-instructions -->
