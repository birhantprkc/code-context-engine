# Agent Plugins Integration for CCE

**Date:** 2026-08-07
**Status:** Draft
**Scope:** Add Agent Plugins v1.0.0 support to CCE as a new distribution channel

## Problem

CCE's onboarding requires multiple steps: install the Python package, run `cce init`, restart the editor. Each step loses users. The `cce init` command maintains 8 editor-specific config writers and 6 instruction file formats. Instruction blocks written to repos go stale when CCE adds new tools.

Agent Plugins is an open standard (v1.0.0) backed by Amazon, Cursor, Microsoft, OpenAI, and Vercel. Compatible clients include VS Code, GitHub Copilot, ChatGPT, Codex, Cursor, and Kiro. Adopting it gives CCE a zero-friction install path for 6 major clients and eliminates instruction staleness for those clients.

## Goals

1. Users can install CCE as an Agent Plugin with zero prior setup
2. Instructions stay in sync with CCE version (no stale repo files)
3. Existing `cce init` flow is unaffected (additive only)
4. Implementation is small (3 generated files, 1 new CLI flag, 1 `cce serve` enhancement)

## Non-Goals

- Drop any existing `cce init --agent` support
- Add client extensions (`com.cce/` namespace)
- Bundle the Python package inside the plugin
- Publish to a plugin registry (future PR once registries stabilize)
- Support multiple skills (CCE is one product, one skill)

## Design

### 1. Plugin Output Structure

`cce init --plugin` generates a self-contained Agent Plugin directory:

```
<output-dir>/
├── plugin.json
├── mcp.json
├── skills/
│   └── code-context/
│       ├── SKILL.md
│       └── references/
│           └── tools.md
└── LICENSE
```

Default output path: `.cce/plugin/` inside the project directory.
Override with `--plugin-dir <path>` for custom locations or global installs.

### 2. plugin.json

Minimal manifest per the Agent Plugins v1.0.0 spec:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "code-context-engine",
  "version": "<from pyproject.toml>",
  "description": "Index your codebase. AI searches instead of re-reading files. 94% token savings.",
  "author": {
    "name": "Elara Labs",
    "url": "https://github.com/elara-labs/code-context-engine"
  },
  "repository": "https://github.com/elara-labs/code-context-engine",
  "license": "MIT",
  "keywords": ["code-search", "token-savings", "mcp", "code-indexing", "retrieval"]
}
```

The `version` field is read from `importlib.metadata.version("code-context-engine")` at generation time, keeping it in sync with the installed CCE version.

### 3. mcp.json

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "code-context-engine": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "code-context-engine[local]", "cce", "serve"]
    }
  }
}
```

Design decisions:

- **`uvx` as command:** Users don't need CCE pre-installed. `uvx` fetches and runs it on demand. `uvx` is a bare executable name, valid per the spec. Falls back gracefully if `uvx` is not installed (client reports server failed to start).
- **No `--project-dir`:** The MCP server discovers the project from cwd (see section 5). This avoids hardcoding paths and keeps the plugin portable.
- **No `cwd` override:** The spec defaults cwd to plugin root. Workspace-aware clients (Cursor, some VS Code modes) override cwd to the workspace. Either way, `cce serve` handles it via auto-discovery.
- **`[local]` extra:** Includes fastembed + ONNX Runtime so the plugin works without Ollama. Users with Ollama can install without `[local]` separately.

### 4. SKILL.md

Frontmatter per the Agent Skills specification:

```yaml
---
name: code-context
description: >
  Intelligent code retrieval and cross-session memory for AI coding agents.
  Use when searching codebases, answering questions about code, exploring
  architecture, finding functions or patterns, or recalling past decisions.
  Provides context_search, expand_chunk, related_context, session_recall,
  record_decision, record_code_area, and set_output_compression MCP tools.
license: MIT
compatibility: Requires Python 3.11+ and uv (or uvx)
metadata:
  author: elara-labs
  version: "<from pyproject.toml>"
---
```

The body contains the agent-neutral instruction text. This is the same content currently in `_CCE_INSTRUCTIONS_BASE` in `editors.py`, covering:

- When and how to use `context_search` instead of reading files directly
- Available tools: `expand_chunk`, `related_context`, `session_recall`
- Cross-session memory: `record_decision`, `record_code_area`
- Output compression: `set_output_compression`

The `references/tools.md` file contains per-tool parameter documentation (parameters, types, examples, edge cases). The agent loads this on demand per the progressive disclosure model, keeping SKILL.md under 500 lines.

### 5. Project Auto-Discovery in `cce serve`

When `--project-dir` is not provided, `cce serve` walks up from cwd to find the project root:

```
1. Start at cwd
2. At current directory, check for .context-engine.yaml or .git/
   (if both exist, .context-engine.yaml wins as it's an explicit CCE marker)
3. If either is found, use that directory as the project root
4. If neither is found, move to parent directory and repeat
5. Stop at filesystem root
6. If no project found, start server but return a helpful message
   on first tool call: "No project found. Run `cce init` in your
   project directory, or start with `cce serve --project-dir <path>`."
```

This matches the convention used by git, npm, cargo, and similar tools.

This change benefits all users, not just plugin users. Anyone running `cce serve` from a subdirectory gets the right project automatically.

When the project is found via auto-discovery, `cce serve` reloads config from that directory's `.context-engine.yaml` (same as the existing `--project-dir` behavior).

### 6. Instruction Template Consolidation

Extract the instruction text into a standalone file at `src/context_engine/data/instructions.md`. This file becomes the single source of truth for:

- **Plugin path:** SKILL.md body content (copied verbatim)
- **Existing agent path:** `write_instruction_file()` reads it for .cursorrules, AGENTS.md, GEMINI.md, TABNINE.md, .github/copilot-instructions.md
- **Claude Code path:** `_build_claude_md_block()` reads it and appends Claude-specific extras (session_timeline, session_event, stricter language)

The file is plain markdown with no frontmatter. Output compression rules are appended dynamically based on config, same as today.

### 7. CLI Interface

```
cce init --plugin                     # generate plugin at .cce/plugin/
cce init --plugin --plugin-dir ~/p/   # custom output directory
cce init --agent claude --plugin      # both: agent config + plugin
```

`--plugin` is independent of `--agent`. They can be used together or separately.

When `--plugin` is used:
1. Generate plugin.json with version from installed CCE
2. Generate mcp.json with uvx command
3. Generate skills/code-context/SKILL.md from instruction template
4. Generate skills/code-context/references/tools.md with per-tool docs
5. Copy LICENSE from CCE package
6. Add `.cce/plugin/` to .gitignore (if default path)

### 8. Version Synchronization

The plugin.json `version` and SKILL.md metadata `version` are set from `importlib.metadata.version("code-context-engine")` at generation time. This follows the same pattern as `server.json` version syncing (per existing project convention).

Users regenerate the plugin after `cce upgrade` to pick up new versions. A future enhancement could auto-regenerate the plugin during `cce upgrade` if the plugin directory exists.

## File Changes

| File | Change |
|------|--------|
| `src/context_engine/cli.py` | Add `--plugin` and `--plugin-dir` to `cce init`. Add project auto-discovery to `serve()`. |
| `src/context_engine/editors.py` | Add `generate_plugin()` function. Refactor `_CCE_INSTRUCTIONS_BASE` to read from `data/instructions.md`. |
| `src/context_engine/data/instructions.md` | New file. Extracted instruction template (single source of truth). |
| `tests/test_plugin.py` | New file. Tests for plugin generation and project auto-discovery. |

## Testing

1. **Plugin generation:** `cce init --plugin` produces valid plugin.json, mcp.json, and SKILL.md with correct schema URLs, version, and instruction content.
2. **Plugin validation:** Generated plugin.json and mcp.json pass JSON Schema validation against the Agent Plugins v1.0.0 schemas.
3. **SKILL.md validation:** Frontmatter has required `name` and `description` fields. Name matches directory name (`code-context`). Body is non-empty.
4. **Project auto-discovery:** `cce serve` without `--project-dir` finds the project from a subdirectory. Returns helpful error when no project found. Respects `.context-engine.yaml` over `.git/` when both exist at different levels.
5. **Instruction consolidation:** All instruction writers (plugin, agent files, CLAUDE.md) produce the same base content from the shared template.
6. **Backward compatibility:** Existing `cce init --agent claude` behavior is unchanged. Existing `cce serve --project-dir` behavior is unchanged.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| `uvx` not installed on user's machine | Client reports "server failed to start." SKILL.md can include a fallback note. Plugin is still useful for its skill content even without MCP. |
| Client sets cwd to plugin root (not workspace) | Auto-discovery walks up from cwd. If plugin is inside the project (`.cce/plugin/`), it finds the project two levels up. If plugin is global, auto-discovery won't find a project, and the server returns a helpful error. |
| Agent Plugins spec changes in v2 | Plugin generation is isolated in one function. Schema URLs are easy to update. |
| Claude Code doesn't support Agent Plugins yet | No impact. Claude Code continues using `.mcp.json` + `CLAUDE.md` via existing `cce init --agent claude`. |

## Future Work (out of scope for this PR)

- Publish plugin to VS Code Marketplace or other plugin registries
- Auto-regenerate plugin during `cce upgrade`
- `cce init --plugin --no-uvx` variant for environments where `cce` is already on PATH
- Streamable HTTP transport option for remote/containerized CCE
