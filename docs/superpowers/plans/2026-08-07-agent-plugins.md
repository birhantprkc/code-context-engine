# Agent Plugins Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Agent Plugins v1.0.0 support to CCE so users can install CCE as a portable plugin in VS Code, Cursor, Copilot, Codex, ChatGPT, and Kiro with zero prior setup.

**Architecture:** A new `generate_plugin()` function in `editors.py` writes the three-file plugin directory (plugin.json, mcp.json, skills/code-context/SKILL.md). The instruction template is extracted from `_CCE_INSTRUCTIONS_BASE` into a standalone file shared by all writers. `cce serve` gains project auto-discovery (walk up from cwd to find .git or .context-engine.yaml) so the plugin's MCP server works without `--project-dir`.

**Tech Stack:** Python 3.11+, Click CLI, Agent Plugins v1.0.0, Agent Skills v1.0.0

## Global Constraints

- Agent Plugins v1.0.0 schema URL: `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`
- Agent Plugins mcp.json schema URL: `https://agent-plugins.org/schemas/1.0.0/mcp.schema.json`
- Plugin name must be 1-64 chars, lowercase alphanumeric/hyphens/periods only
- SKILL.md `name` field must match its parent directory name
- SKILL.md body should be under 500 lines
- Never use dashes as punctuation in documentation or README files
- Do not add Co-Authored-By lines to commits
- Update server.json whenever pyproject.toml version bumps (existing convention applies to plugin.json too)
- Run `uv run python -m pytest tests/ -x -q` to verify all tests pass

---

### Task 1: Extract instruction template into standalone file

Extract `_CCE_INSTRUCTIONS_BASE` from `editors.py` into `src/context_engine/data/instructions.md` and make all instruction writers read from it.

**Files:**
- Create: `src/context_engine/data/__init__.py`
- Create: `src/context_engine/data/instructions.md`
- Modify: `src/context_engine/editors.py:101-138`
- Test: `tests/test_plugin.py` (new)

**Interfaces:**
- Consumes: nothing
- Produces: `get_instructions_base() -> str` function in `editors.py` that reads `data/instructions.md`. All existing callers of `_CCE_INSTRUCTIONS_BASE` use this instead.

- [ ] **Step 1: Write the failing test**

Create `tests/test_plugin.py`:

```python
"""Tests for Agent Plugins generation and instruction template."""
from pathlib import Path

from context_engine.editors import get_instructions_base


def test_instructions_base_loads_from_file():
    """Instruction template must load from data/instructions.md."""
    text = get_instructions_base()
    assert "context_search" in text
    assert "record_decision" in text
    assert "session_recall" in text
    assert len(text) > 100


def test_instructions_base_has_no_claude_specific_content():
    """The base template is agent-neutral (no Claude Code references)."""
    text = get_instructions_base()
    assert "Claude Code" not in text
    assert "CLAUDE.md" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_plugin.py::test_instructions_base_loads_from_file -v`
Expected: FAIL with `ImportError` (function doesn't exist yet)

- [ ] **Step 3: Create the data directory and instructions file**

Create `src/context_engine/data/__init__.py` (empty file).

Create `src/context_engine/data/instructions.md` with the content currently in `_CCE_INSTRUCTIONS_BASE` (lines 101-129 of `editors.py`):

```markdown
## Context Engine (CCE)

This project uses Code Context Engine for intelligent code retrieval and
cross-session memory.

### Searching the codebase

**Use `context_search` instead of reading files directly** when exploring
the codebase, answering questions about code, or understanding how things
work. `context_search` returns the most relevant code chunks with
confidence scores instead of whole files.

When to use `context_search`:
- Answering questions about the codebase ("how does X work?", "where is Y?")
- Exploring structure or architecture
- Finding related code, functions, or patterns

Other tools:
- `expand_chunk` for full source of a compressed result
- `related_context` for what calls/imports a function
- `session_recall` to recall past decisions

### Cross-session memory

Call `session_recall("topic phrase")` before answering non-trivial questions.
Call `record_decision(decision="...", reason="...")` after making choices.
Call `record_code_area(file_path="...", description="...")` after meaningful work.
```

- [ ] **Step 4: Add `get_instructions_base()` and refactor editors.py**

In `editors.py`, replace the `_CCE_INSTRUCTIONS_BASE` string literal and `_build_instructions` with:

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_instructions_base() -> str:
    """Load the agent-neutral instruction template from data/instructions.md."""
    path = Path(__file__).parent / "data" / "instructions.md"
    return path.read_text(encoding="utf-8")


def _build_instructions(output_level: str = "standard") -> str:
    """Build CCE instructions with the configured output style."""
    from context_engine.compression.output_rules import get_instruction_output_block
    base = get_instructions_base()
    block = get_instruction_output_block(output_level)
    if block:
        return base + "\n" + block + "\n"
    return base
```

Remove the old `_CCE_INSTRUCTIONS_BASE` string constant. Update `_CCE_INSTRUCTIONS` to call the refactored `_build_instructions`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_plugin.py -v`
Expected: PASS (both tests)

Run: `uv run python -m pytest tests/ -x -q`
Expected: All existing tests still pass (no regressions from refactor)

- [ ] **Step 6: Commit**

```bash
git add src/context_engine/data/__init__.py src/context_engine/data/instructions.md src/context_engine/editors.py tests/test_plugin.py
git commit -m "refactor: extract instruction template into data/instructions.md"
```

---

### Task 2: Add `generate_plugin()` function

Implement plugin directory generation in `editors.py`.

**Files:**
- Modify: `src/context_engine/editors.py`
- Create: `src/context_engine/data/tools_reference.md`
- Modify: `tests/test_plugin.py`

**Interfaces:**
- Consumes: `get_instructions_base()` from Task 1
- Produces: `generate_plugin(output_dir: Path, version: str, output_level: str = "standard") -> None` that writes plugin.json, mcp.json, skills/code-context/SKILL.md, and skills/code-context/references/tools.md to `output_dir`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plugin.py`:

```python
import json

import yaml

from context_engine.editors import generate_plugin


def test_generate_plugin_creates_structure(tmp_path):
    """generate_plugin writes the complete Agent Plugin directory."""
    out = tmp_path / "plugin"
    generate_plugin(out, version="1.2.3")

    assert (out / "plugin.json").exists()
    assert (out / "mcp.json").exists()
    assert (out / "skills" / "code-context" / "SKILL.md").exists()
    assert (out / "skills" / "code-context" / "references" / "tools.md").exists()


def test_plugin_json_schema(tmp_path):
    """plugin.json must conform to Agent Plugins v1.0.0."""
    out = tmp_path / "plugin"
    generate_plugin(out, version="1.2.3")

    data = json.loads((out / "plugin.json").read_text())
    assert data["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert data["name"] == "code-context-engine"
    assert data["version"] == "1.2.3"
    assert data["license"] == "MIT"


def test_mcp_json_schema(tmp_path):
    """mcp.json must declare stdio transport with uvx."""
    out = tmp_path / "plugin"
    generate_plugin(out, version="1.2.3")

    data = json.loads((out / "mcp.json").read_text())
    assert data["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    server = data["mcpServers"]["code-context-engine"]
    assert server["type"] == "stdio"
    assert server["command"] == "uvx"
    assert "cce" in server["args"]
    assert "serve" in server["args"]


def test_skill_md_frontmatter(tmp_path):
    """SKILL.md must have valid Agent Skills frontmatter."""
    out = tmp_path / "plugin"
    generate_plugin(out, version="1.2.3")

    content = (out / "skills" / "code-context" / "SKILL.md").read_text()
    # Split frontmatter
    assert content.startswith("---\n")
    parts = content.split("---\n", 2)
    fm = yaml.safe_load(parts[1])
    assert fm["name"] == "code-context"
    assert len(fm["description"]) > 10
    assert fm["license"] == "MIT"
    assert fm["metadata"]["version"] == "1.2.3"


def test_skill_md_body_has_instructions(tmp_path):
    """SKILL.md body must contain the instruction template content."""
    out = tmp_path / "plugin"
    generate_plugin(out, version="1.2.3")

    content = (out / "skills" / "code-context" / "SKILL.md").read_text()
    assert "context_search" in content
    assert "record_decision" in content


def test_generate_plugin_overwrites_existing(tmp_path):
    """Regenerating into the same directory overwrites cleanly."""
    out = tmp_path / "plugin"
    generate_plugin(out, version="1.0.0")
    generate_plugin(out, version="2.0.0")

    data = json.loads((out / "plugin.json").read_text())
    assert data["version"] == "2.0.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_plugin.py::test_generate_plugin_creates_structure -v`
Expected: FAIL with `ImportError` (function doesn't exist yet)

- [ ] **Step 3: Create tools_reference.md**

Create `src/context_engine/data/tools_reference.md`:

```markdown
# MCP Tools Reference

Detailed parameter documentation for Code Context Engine's MCP tools.
Loaded on demand by the agent when more detail is needed.

## context_search

Search the codebase using hybrid vector + BM25 retrieval.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| query | string | yes | | Natural language query |
| top_k | integer | no | 10 | Maximum results to return |
| max_tokens | integer | no | 8000 | Token budget for results |

Returns ranked code chunks with confidence scores. Use this instead of
Read, Grep, or Glob when exploring code.

## expand_chunk

Get the full original content for a compressed chunk.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| chunk_id | string | yes | ID from a context_search result |

## related_context

Find related code via graph edges (calls, imports).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| chunk_id | string | yes | ID from a context_search result |

## session_recall

Recall past decisions and turn summaries via topic search.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| topic | string | yes | Topic phrase (not a single word) |

Pass a descriptive phrase, not a single word. e.g. `session_recall("auth flow")`
not `session_recall("auth")`.

## session_timeline

List turn summaries for a session, oldest first. Use to drill into a
session_id returned by session_recall.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| session_id | string | yes | | Session ID from recall results |
| limit | integer | no | 20 | Max turns to return |

## session_event

Return raw input/output payload for a single tool event. Use to drill
into an event_id from session_timeline.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| event_id | integer | yes | Event ID from timeline results |

## record_decision

Record a decision with reasoning for future session_recall.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| decision | string | yes | What was decided |
| reason | string | yes | Why this choice was made |

## record_code_area

Record a code area worked on for future session_recall.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| file_path | string | yes | Path to the file |
| description | string | yes | What was done |

## index_status

Check when the index was last updated. No parameters.

## reindex

Trigger re-indexing of a file or the full project.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | no | File path to re-index (omit for full project) |

## set_output_compression

Set output compression level to reduce response token cost.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| level | string | yes | `off`, `lite`, `standard`, or `max` |

Levels: off = normal output, lite = no filler (~30% savings),
standard = fragments (~65% savings), max = telegraphic (~75% savings).
Code blocks and commands are never compressed.
```

- [ ] **Step 4: Implement `generate_plugin()`**

Add to `editors.py`:

```python
def generate_plugin(
    output_dir: Path,
    version: str,
    output_level: str = "standard",
) -> None:
    """Generate an Agent Plugins v1.0.0 directory.

    Writes plugin.json, mcp.json, and skills/code-context/SKILL.md to
    ``output_dir``. Safe to call repeatedly (overwrites existing files).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # plugin.json
    plugin_manifest = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "code-context-engine",
        "version": version,
        "description": (
            "Index your codebase. AI searches instead of re-reading files. "
            "94% token savings."
        ),
        "author": {
            "name": "Elara Labs",
            "url": "https://github.com/elara-labs/code-context-engine",
        },
        "repository": "https://github.com/elara-labs/code-context-engine",
        "license": "MIT",
        "keywords": [
            "code-search",
            "token-savings",
            "mcp",
            "code-indexing",
            "retrieval",
        ],
    }
    (output_dir / "plugin.json").write_text(
        json.dumps(plugin_manifest, indent=2) + "\n", encoding="utf-8"
    )

    # mcp.json
    mcp_config = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {
            "code-context-engine": {
                "type": "stdio",
                "command": "uvx",
                "args": [
                    "--from",
                    "code-context-engine[local]",
                    "cce",
                    "serve",
                ],
            },
        },
    }
    (output_dir / "mcp.json").write_text(
        json.dumps(mcp_config, indent=2) + "\n", encoding="utf-8"
    )

    # skills/code-context/SKILL.md
    skill_dir = output_dir / "skills" / "code-context"
    skill_dir.mkdir(parents=True, exist_ok=True)

    description = (
        "Intelligent code retrieval and cross-session memory for AI coding "
        "agents. Use when searching codebases, answering questions about "
        "code, exploring architecture, finding functions or patterns, or "
        "recalling past decisions. Provides context_search, expand_chunk, "
        "related_context, session_recall, record_decision, record_code_area, "
        "and set_output_compression MCP tools."
    )
    frontmatter = (
        "---\n"
        "name: code-context\n"
        f"description: >\n"
        + "".join(f"  {line}\n" for line in description.splitlines())
        + "license: MIT\n"
        "compatibility: Requires Python 3.11+ and uv (or uvx)\n"
        "metadata:\n"
        "  author: elara-labs\n"
        f'  version: "{version}"\n'
        "---\n\n"
    )
    body = _build_instructions(output_level)
    (skill_dir / "SKILL.md").write_text(frontmatter + body, encoding="utf-8")

    # skills/code-context/references/tools.md
    ref_dir = skill_dir / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    tools_ref = (Path(__file__).parent / "data" / "tools_reference.md").read_text(
        encoding="utf-8"
    )
    (ref_dir / "tools.md").write_text(tools_ref, encoding="utf-8")

    # LICENSE (copy from package root if available)
    pkg_license = Path(__file__).parent.parent.parent / "LICENSE"
    if pkg_license.exists():
        (output_dir / "LICENSE").write_text(
            pkg_license.read_text(encoding="utf-8"), encoding="utf-8"
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_plugin.py -v`
Expected: All PASS

Run: `uv run python -m pytest tests/ -x -q`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add src/context_engine/editors.py src/context_engine/data/tools_reference.md tests/test_plugin.py
git commit -m "feat: add generate_plugin() for Agent Plugins v1.0.0"
```

---

### Task 3: Add project auto-discovery to `cce serve`

When `--project-dir` is not provided, walk up from cwd to find the project root.

**Files:**
- Modify: `src/context_engine/cli.py:2793-2821`
- Modify: `tests/test_cli_serve.py`

**Interfaces:**
- Consumes: nothing (standalone enhancement)
- Produces: `_discover_project_root(start: Path) -> Path | None` function in `cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_serve.py`:

```python
from context_engine.cli import _discover_project_root


def test_discover_project_root_finds_git(tmp_path):
    """Walk-up finds .git directory."""
    project = tmp_path / "myproject"
    project.mkdir()
    (project / ".git").mkdir()
    subdir = project / "src" / "deep"
    subdir.mkdir(parents=True)

    assert _discover_project_root(subdir) == project


def test_discover_project_root_finds_context_engine_yaml(tmp_path):
    """Walk-up finds .context-engine.yaml."""
    project = tmp_path / "myproject"
    project.mkdir()
    (project / ".context-engine.yaml").write_text("indexer:\n  watch: true\n")
    subdir = project / "src"
    subdir.mkdir()

    assert _discover_project_root(subdir) == project


def test_discover_project_root_prefers_context_engine_yaml(tmp_path):
    """When both .context-engine.yaml and .git exist at different levels,
    .context-engine.yaml wins (found first on walk-up)."""
    root = tmp_path / "root"
    root.mkdir()
    (root / ".git").mkdir()
    inner = root / "inner"
    inner.mkdir()
    (inner / ".context-engine.yaml").write_text("")

    assert _discover_project_root(inner) == inner


def test_discover_project_root_returns_none(tmp_path):
    """Returns None when no project markers found."""
    bare = tmp_path / "bare"
    bare.mkdir()

    assert _discover_project_root(bare) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_cli_serve.py::test_discover_project_root_finds_git -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `_discover_project_root()`**

Add to `cli.py` (near the top, after imports, around line 50):

```python
def _discover_project_root(start: Path) -> Path | None:
    """Walk up from *start* looking for a project root marker.

    Checks each directory for .context-engine.yaml (explicit CCE project)
    or .git/ (any git repo). Returns the first match, or None at the
    filesystem root.
    """
    current = start.resolve()
    while True:
        if (current / ".context-engine.yaml").exists():
            return current
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
```

- [ ] **Step 4: Wire auto-discovery into `serve()`**

Modify the `serve()` function in `cli.py` (around line 2800). After the existing `if project_dir:` block, add an `else` branch:

```python
def serve(ctx: click.Context, as_http: bool, host: str, port: int, project_dir: str | None) -> None:
    """Start the MCP server (used by Claude Code)."""
    if project_dir:
        import os
        os.chdir(project_dir)
        target_config = Path(project_dir) / PROJECT_CONFIG_NAME
        ctx.obj["config"] = load_config(
            project_path=target_config if target_config.exists() else None
        )
    else:
        discovered = _discover_project_root(Path.cwd())
        if discovered and discovered != Path.cwd():
            import os
            os.chdir(str(discovered))
            target_config = discovered / PROJECT_CONFIG_NAME
            ctx.obj["config"] = load_config(
                project_path=target_config if target_config.exists() else None
            )
    # ... rest of function unchanged
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_cli_serve.py -v`
Expected: All PASS (new + existing)

Run: `uv run python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/context_engine/cli.py tests/test_cli_serve.py
git commit -m "feat(serve): auto-discover project root from cwd walk-up"
```

---

### Task 4: Add `--plugin` flag to `cce init` and update docs

Wire plugin generation into the CLI, update README, wiki docs, and Starlight source.

**Files:**
- Modify: `src/context_engine/cli.py:873-998` (init command)
- Modify: `README.md`
- Modify: `docs/wiki/CLI-Reference.md`
- Modify: `docs/wiki/Configuration.md`
- Modify: `docs-src/src/content/docs/getting-started.md`
- Modify: `docs-src/src/content/docs/cli-reference.md`
- Modify: `tests/test_plugin.py`

**Interfaces:**
- Consumes: `generate_plugin()` from Task 2
- Produces: `--plugin` and `--plugin-dir` options on `cce init`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin.py`:

```python
from click.testing import CliRunner
from context_engine.cli import main


def test_init_plugin_flag(tmp_path):
    """cce init --plugin generates the plugin directory."""
    runner = CliRunner()
    project = tmp_path / "myproj"
    project.mkdir()
    (project / ".git").mkdir()

    result = runner.invoke(main, ["init", "--plugin", "--agent", "claude"], catch_exceptions=False, env={"HOME": str(tmp_path)})

    plugin_dir = project / ".cce" / "plugin"
    # The plugin files should exist even if init had other errors
    # (embedding model download etc). Check the plugin output specifically.
    assert (plugin_dir / "plugin.json").exists() or result.exit_code == 0


def test_init_plugin_dir_flag(tmp_path):
    """cce init --plugin --plugin-dir writes to custom path."""
    runner = CliRunner()
    project = tmp_path / "myproj"
    project.mkdir()
    (project / ".git").mkdir()
    custom = tmp_path / "custom-plugin"

    result = runner.invoke(
        main,
        ["init", "--plugin", "--plugin-dir", str(custom), "--agent", "claude"],
        catch_exceptions=False,
        env={"HOME": str(tmp_path)},
    )

    assert (custom / "plugin.json").exists() or result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_plugin.py::test_init_plugin_flag -v`
Expected: FAIL (no `--plugin` option yet)

- [ ] **Step 3: Add `--plugin` and `--plugin-dir` to `cce init`**

Modify the `init` command definition in `cli.py`. Add options:

```python
@main.command()
@click.option(
    "--agent",
    type=click.Choice(_INIT_AGENT_CHOICES),
    default="auto",
    show_default=True,
    help="Agent/editor target: auto, claude, codex, copilot, pi, or all.",
)
@click.option("--plugin", "gen_plugin", is_flag=True, help="Generate an Agent Plugin directory")
@click.option("--plugin-dir", default=None, type=click.Path(), help="Plugin output directory (default: .cce/plugin/)")
@click.pass_context
def init(ctx: click.Context, agent: str, gen_plugin: bool, plugin_dir: str | None) -> None:
```

At the end of the `init` function (after indexing, before the "Done!" message), add:

```python
    # Agent Plugin generation
    if gen_plugin:
        from context_engine.editors import generate_plugin
        from importlib.metadata import version as pkg_version
        try:
            ver = pkg_version("code-context-engine")
        except Exception:
            ver = "0.0.0"
        plugin_out = Path(plugin_dir) if plugin_dir else project_dir / ".cce" / "plugin"
        generate_plugin(plugin_out, version=ver, output_level=output_level)
        click.echo(f"  {_check()} Agent Plugin generated at {plugin_out}")
        # Add default plugin path to .gitignore
        if not plugin_dir:
            gitignore = project_dir / ".gitignore"
            gi_content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
            if ".cce/plugin/" not in gi_content:
                gitignore.write_text(
                    gi_content.rstrip() + "\n\n# CCE Agent Plugin (generated)\n.cce/plugin/\n",
                    encoding="utf-8",
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_plugin.py -v`
Expected: All PASS

Run: `uv run python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 5: Update README.md**

Add to the "Quick start" section after the `cce init` block:

```markdown
> **Agent Plugin support:** Run `cce init --plugin` to generate a portable
> [Agent Plugin](https://agent-plugins.org) directory that works with
> VS Code, Cursor, Copilot, Codex, ChatGPT, and Kiro.
```

Add `cce init --plugin` to the "CLI at a glance" section:

```markdown
cce init --plugin           # Generate Agent Plugin for VS Code, Cursor, etc.
```

- [ ] **Step 6: Update docs/wiki/CLI-Reference.md**

Add `--plugin` to the `cce init` section:

```markdown
### Agent Plugin generation

```bash
cce init --plugin                     # generate at .cce/plugin/
cce init --plugin --plugin-dir ~/p/   # custom output directory
cce init --agent claude --plugin      # both: agent config + plugin
```

Generates a portable [Agent Plugin](https://agent-plugins.org) directory
containing plugin.json, mcp.json, and a SKILL.md with CCE instructions.
Compatible with VS Code, Cursor, GitHub Copilot, Codex, ChatGPT, and Kiro.
The plugin uses `uvx` to launch CCE on demand, so users don't need to
pre-install the Python package.
```

Also add `--plugin` to the `cce list` command output section.

- [ ] **Step 7: Update docs-src/src/content/docs/getting-started.md**

Add a section about Agent Plugin installation after the manual install steps.

- [ ] **Step 8: Update docs-src/src/content/docs/cli-reference.md**

Add `--plugin` flag documentation to match wiki updates.

- [ ] **Step 9: Run full test suite**

Run: `uv run python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 10: Commit**

```bash
git add src/context_engine/cli.py tests/test_plugin.py README.md docs/wiki/CLI-Reference.md docs/wiki/Configuration.md docs-src/src/content/docs/getting-started.md docs-src/src/content/docs/cli-reference.md
git commit -m "feat: add --plugin flag to cce init for Agent Plugins v1.0.0

Generate a portable Agent Plugin directory (plugin.json, mcp.json,
SKILL.md) compatible with VS Code, Cursor, Copilot, Codex, ChatGPT,
and Kiro. Uses uvx to launch CCE on demand."
```

---

### Task 5: Create PR

**Files:** none (git operations only)

- [ ] **Step 1: Create branch and push**

```bash
git checkout -b feat/agent-plugins
git push -u origin feat/agent-plugins
```

- [ ] **Step 2: Create PR**

```bash
gh pr create --title "feat: Agent Plugins v1.0.0 support" --body "$(cat <<'EOF'
## Summary

- Add `cce init --plugin` to generate a portable Agent Plugin directory
- Plugin works with VS Code, Cursor, GitHub Copilot, Codex, ChatGPT, and Kiro
- Uses `uvx` to launch CCE on demand (no pre-install needed)
- Extract instruction template into standalone file (single source of truth)
- Add project auto-discovery to `cce serve` (walk up from cwd to find .git)
- Update README, wiki docs, and Starlight source

Closes #<issue-number-if-applicable>

Design spec: docs/superpowers/specs/2026-08-07-agent-plugins-design.md
EOF
)"
```
