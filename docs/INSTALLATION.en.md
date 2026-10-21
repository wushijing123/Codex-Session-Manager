# Installation Guide

[中文](INSTALLATION.md) · [English](INSTALLATION.en.md)

## 1. Requirements

- Python 3.11 or newer
- Codex installed and launched at least once
- Git
- Node.js 24 only for development checks, not for daily use

The complete execution flow is primarily validated on macOS. Linux supports scanning, reports, the dashboard, and tests. Windows symlinks may require Developer Mode or administrator privileges.

## 2. Recommended: install as a Codex Skill

The single shared maintenance source is:

```text
~/.agents/skills/codex-session-lifecycle-manager
```

Clone it once and create the Codex entry point:

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/wushijing123/Codex-Session-Manager.git \
  ~/.agents/skills/codex-session-lifecycle-manager
python3 ~/.agents/skills/codex-session-lifecycle-manager/scripts/install_skill.py
```

By default, the installer creates only the Codex entry point. It does not change Claude Code, Antigravity, or WorkBuddy.

Verify the installation:

```bash
python3 ~/.agents/skills/codex-session-lifecycle-manager/scripts/doctor.py
```

## 3. Run the dashboard without installing a Skill

For dashboard-only use, clone the repository anywhere. No symlinks are required:

```bash
git clone https://github.com/wushijing123/Codex-Session-Manager.git
cd Codex-Session-Manager
python3 scripts/doctor.py --project-only
python3 scripts/session_manager.py dashboard
```

Prevent automatic browser opening:

```bash
python3 scripts/session_manager.py dashboard --no-open
```

The standalone library supports search, reading, backups, and operations available through the installed native protocol. Protected, known pinned, current and linked sessions are skipped. Installing the Skill in another agent adds an entry point, not another session data source.

## 4. Optional: connect other agents

Preview without writing:

```bash
python3 scripts/install_skill.py --targets all --dry-run
```

Connect Codex, Claude Code, Antigravity, and WorkBuddy:

```bash
python3 scripts/install_skill.py --targets all
```

Connect selected agents only:

```bash
python3 scripts/install_skill.py --targets codex workbuddy
```

Installer results:

- `OK` — already linked to the canonical source
- `CREATED` — a new link was created
- `CONFLICT` — an existing target is different; it is preserved and installation stops

There is no `--force` option. The installer never silently overwrites an existing directory or Skill.

## 5. Safely migrate from the old Skill name

The legacy maintenance source was:

```text
~/.agents/skills/wushijing-codex-session-manager
```

Preview the migration:

```bash
cd ~/.agents/skills/wushijing-codex-session-manager
python3 scripts/install_skill.py --migrate-legacy --dry-run
```

Then run it:

```bash
python3 scripts/install_skill.py --migrate-legacy
```

The migration does only three things:

1. Atomically renames the legacy source when the new directory does not exist.
2. Migrates symlinks that clearly point to the legacy source.
3. Creates the default Codex entry point.

If the new directory, a same-name agent entry, or a real directory already exists, migration stops and preserves it. The installer never merges directories or overwrites user files.

## 6. Launch

```bash
python3 ~/.agents/skills/codex-session-lifecycle-manager/scripts/session_manager.py dashboard
```

Or ask Codex:

```text
Use $codex-session-lifecycle-manager to open Codex-Session-Manager.
```

## 7. Update

```bash
cd ~/.agents/skills/codex-session-lifecycle-manager
git pull --ff-only
python3 scripts/doctor.py
```

Entry points are symlinks and do not need to be recreated after every update.

## 8. Install from a release package

Every GitHub Release includes a runtime-only Skill ZIP. Keep one root directory with exactly one root `SKILL.md`. For Skill use, place that root at `~/.agents/skills/codex-session-lifecycle-manager` and run the installer. For standalone dashboard use, extract it anywhere.

## 9. Windows note

Creating directory symlinks may require Developer Mode or administrator privileges. The installer reports errors without overwriting the target. Current Releases and CI do not mark the Windows permanent-deletion flow as validated.

## 10. Troubleshooting

### `legacy_source_detected`

The project is still in the legacy source directory. Follow section 5: run `--migrate-legacy --dry-run`, review the result, and then run the migration.

### `migration_target_exists` / `migration_entry_conflict`

The new source or entry path already exists. The migration will not guess which copy to keep or overwrite it. Review both paths manually; do not delete an unknown directory.

### `source_must_be_canonical`

The canonical path is required only when installing the project as a Skill. For dashboard-only use, run `doctor.py --project-only`; moving the repository is unnecessary.

### `CONFLICT`

The target is a real directory or points somewhere else. Review it manually. Move it to a backup location only after confirming it is safe, then rerun the installer.

### The dashboard URL does not open

Confirm the dashboard command is still running and use the URL printed by the current launch. Old launch tokens cannot be reused.

### Doctor warns that Node.js is missing

This is a development-check warning and does not block daily scanning or dashboard use. Install Node.js before contributing code.
