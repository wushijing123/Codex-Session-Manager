# Codex-Session-Manager

[中文](README.md) · [English](README.en.md)

A local tool to search, read, and organize Codex session history. MIT licensed.

Current version: `0.7.0`.

A two-pane session list and conversation reader keep the main workflow focused.

- Search titles, projects, IDs, and first messages as you type. Press Enter to search conversation text across active and archived sessions.
- Read actual user requests and Codex replies; leading injected plugin lists, project instructions and loaded skill context are filtered before pagination and text search. Quoted examples remain intact. Read sanitized Markdown with tables, code and lists, plus local or embedded raster image previews. Embedded originals remain viewable after temporary source files are gone. Remote images are not fetched automatically. Load 20 messages per page, including histories longer than 200 messages.
- Open the original session through `codex://threads/SESSION_ID`.
- Archive or unarchive through the native Codex App Server.
- Back up the original JSONL, SHA-256, and session database rows as a downloadable ZIP.
- Delete through the native API after saving and verifying a recovery copy. Confirmed deletions enter Trash for 30 days. Trash supports restore, selection, select all and permanent deletion. Copies expire on startup, library refresh or opening Trash. Manual and legacy backups do not expire. No plan page, confirmation sheet, or second dialog.
- Browse 50 sessions per page with previous/next buttons and a page selector. Selections survive page changes; the selected count distinguishes this page, other pages and outside the filter.
- In Suggested, filter by active or archived status. Apply suggestions archives or deletes each selected session according to its displayed recommendation, saving a backup before each deletion. Changed recommendations are skipped.
- Select sessions individually, select the displayed page, or select all filtered matches for batch archive, unarchive, backup or delete. View background progress and individual results; each deletion saves its own backup.
- See explainable archive/delete suggestions based on local rules. Suggestions never execute automatically.

## Settings and appearance

Open Settings from the home header to choose the manual backup folder. The first manual backup also collects a destination. Existing files stay in place when the location changes. ZIP files use `sessionID-randomID.zip`; Backups shows their titles and timestamps. Single and batch backups show progress and support cancellation: completed files stay, unfinished files are cleaned up. Closing the progress dialog keeps the task running.

Choose **B Warm reading (default), A Light minimal, or C Dark workspace**. Theme changes apply immediately and persist in this browser.

![Fictional-data demo](assets/demo/session-library-v0.7.0.png)

Only local Codex sessions are supported. Claude Code session support is not implemented; installing this Skill in Claude Code does not add that capability.

## Install and launch

Requires Python 3.11+, Git, Codex CLI, and an existing Codex installation.

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/wushijing123/Codex-Session-Manager.git \
  ~/.agents/skills/codex-session-lifecycle-manager
cd ~/.agents/skills/codex-session-lifecycle-manager
python3 scripts/install_skill.py
python3 scripts/session_manager.py dashboard
```

Keep the server running and use its printed launch URL. The server binds only to `127.0.0.1`; do not share the launch token. The UI supports Chinese and English. Session data stays on your computer.

Try fictional data first (search, read and back up; archive/delete are disabled):

```bash
python3 scripts/demo_dashboard.py --no-open
```

## Behavior and limits

- Available operations are detected from the installed Codex protocol schema. Older CLIs may support archive but lack `thread/delete`; deletion is disabled with an explanation. This tool does not upgrade your CLI.
- Native mutations do not edit Codex SQLite directly, kill writers, or bypass native refusals.
- Known pinned/protected sessions, the current session, and linked tasks cannot be deleted from the library.
- Verified recovery copies stay in Trash for 30 days; permanent deletion removes those copies. Manual backups remain independent.
- ZIP backups include transcripts and session rows, excluding credentials and full databases. The backup drawer supports download and restore after ID/hash validation, without overwriting existing sessions. Restoring compressed backups produces plain JSONL and preserves session ID, content and archive state; internal database fields and original ordering times are not all restored.
- Reading/search supports `.jsonl`, `.jsonl.zst`, paginated `item_completed` messages and mixed history. Duplicate representations of one ID count once. Individual long messages retain the parser's text limit.
- Compressed reading uses Python 3.14, the `zstandard` Python package, or the system `zstd` command, without caching decompressed transcripts.
- Project and inactivity filters narrow the list. `CODEX_HOME` and configured SQLite homes are respected.
- Legacy cold-storage and quarantine packages remain visible; use legacy commands to restore them. Their old planning flow is not part of the new interface.
- Desktop and 375px browser layouts are verified. Native deep links require a compatible installed Codex app.

## Validate

```bash
python3 -m unittest discover -s tests -q
python3 scripts/doctor.py --project-only
node --check assets/dashboard/app.js
node --check assets/dashboard/i18n.js
```

See [installation](docs/INSTALLATION.en.md), [changelog](CHANGELOG.md), and [security](SECURITY.en.md). Legacy workflow documents and screenshots describe the 0.6 cold-storage/quarantine tools.
