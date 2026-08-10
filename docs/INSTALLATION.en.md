# Installation Guide

[中文](INSTALLATION.md) · [English](INSTALLATION.en.md)

## 1. Requirements

- Python 3.11 or newer
- Codex installed and launched at least once
- Git; an authenticated GitHub CLI is recommended for the private repository
- Node.js 24 only for development checks, not for daily use

The complete execution flow is primarily validated on macOS. Linux supports scanning, reports, dashboard, and tests. Windows symlinks may require Developer Mode or administrator privileges.

## 2. Install the canonical source

The single shared maintenance source must be:

```text
~/.agents/skills/wushijing-codex-session-manager
```

First installation:

```bash
mkdir -p ~/.agents/skills
gh repo clone wushijing123/wushijing-codex-session-manager \
  ~/.agents/skills/wushijing-codex-session-manager
cd ~/.agents/skills/wushijing-codex-session-manager
```

If it already exists:

```bash
cd ~/.agents/skills/wushijing-codex-session-manager
git pull --ff-only
```

## 3. Create agent entry points

Preview changes:

```bash
python3 scripts/install_skill.py --dry-run
```

Install Codex, Claude Code, Antigravity, and WorkBuddy links:

```bash
python3 scripts/install_skill.py
```

Install selected entry points:

```bash
python3 scripts/install_skill.py --targets codex
python3 scripts/install_skill.py --targets codex workbuddy
```

The installer reports only:

- `OK` — already linked to the canonical source
- `CREATED` — a new link was created
- `CONFLICT` — an existing target is different; it is preserved and installation stops

There is no `--force` option and no silent overwrite.

## 4. Verify

```bash
python3 scripts/install_skill.py --verify
python3 scripts/doctor.py
```

All requested entry points should be `OK`, and Doctor should report no `FAIL`.

## 5. Launch

```bash
python3 scripts/session_manager.py dashboard
```

Prevent automatic browser opening:

```bash
python3 scripts/session_manager.py dashboard --no-open
```

Or ask Codex:

```text
Use $wushijing-codex-session-manager to open the session lifecycle dashboard.
```

## 6. Update

```bash
cd ~/.agents/skills/wushijing-codex-session-manager
git pull --ff-only
python3 scripts/doctor.py
```

Entry points are links and do not need to be recreated after every update.

## 7. Install from a release package

Every GitHub Release includes a runtime-only Skill ZIP. After extraction, keep one root directory with exactly one root `SKILL.md`. Place that directory under `~/.agents/skills/`, then run the installer.

## 8. Windows note

Creating directory symlinks may require Developer Mode or administrator privileges. The installer reports the error without overwriting the target. The Windows permanent-deletion execution flow is not marked as validated by current Releases or CI.

## 9. Troubleshooting

### `source_must_be_canonical`

Move or clone the repository to `~/.agents/skills/wushijing-codex-session-manager`.

### `CONFLICT`

The target is a real directory or points somewhere else. Review it manually. Move it to a backup location only after confirming it is safe, then rerun the installer.

### The dashboard URL does not open

Confirm the dashboard command is still running and use the URL printed by the current launch. Old launch tokens cannot be reused.

### Doctor warns that Node.js is missing

This is a development-check warning and does not block daily scanning or dashboard use. Install Node.js before contributing code.
