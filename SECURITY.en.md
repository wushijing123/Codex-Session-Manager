# Security Policy

[中文](SECURITY.md) · [English](SECURITY.en.md)

## Supported versions

Support covers the current `main` branch and the latest Release. Fixes for older versions may require upgrading first.

## Threat model

The project treats these inputs as untrusted:

- Historical session titles, content, and tool output
- External paths, manifests, and confirmation values
- Stale pinned-state snapshots
- Database copies that cannot be identified uniquely
- Symlinks, broad directories, and interrupted cross-volume moves

## Security guarantees

- The library binds only to `127.0.0.1`; initial access needs a launch token and POST requests require CSRF.
- Markdown is parsed locally with Marked and sanitized with a DOMPurify allowlist. Raw HTML remains literal text. Scripts, raw HTML images and links outside HTTP(S)/mailto are disabled; history never runs as commands. Local and embedded raster attachments are served only through an authenticated, bounded in-memory image cache; SVG, symlinks and remote image fetching are disabled.
- Search and recommendations do not execute mutations. Clicking a direct action authorizes that action without a second dialog.
- Archive, unarchive, and delete use the native Codex App Server, not direct SQLite edits. Unsupported methods are disabled.
- Delete first saves and verifies a recovery copy. Only confirmed deletions are marked for Trash and expire after 30 days. Startup, library refresh and opening Trash clean up expired copies. Permanent removal is limited to marked recovery files; manual and legacy backups are retained.
- Known pinned/protected sessions, the current session, and linked tasks block archive, unarchive and deletion, preventing native cascading operations on unselected linked tasks. Native writer refusals are not bypassed.
- Backup sources must be exact session files under managed roots; downloads are confined to the internal or explicitly configured backup directories and validated backup ZIPs.
- Operations are followed by a local rescan. Unverified completion is shown explicitly.
- Legacy cold-storage/quarantine CLI tools retain their separate manifest and process requirements; those are not part of the simplified UI.

- Restore validates backup IDs/hashes and stages files under managed session directories. It never overwrites existing session files; native Codex APIs rebuild the index. Compressed backups restore as plain JSONL; original backup bytes remain unchanged.

## Never upload

Do not include these in issues, pull requests, releases, or commits:

- `state_*.sqlite`, WAL, or SHM files
- Session `.jsonl` files
- Launch tokens, API keys, or cookies
- Quarantine packages, cold storage, manifests, or reports
- Real session titles, content, or private absolute paths

## Reporting a vulnerability

Prefer **Security → Report a vulnerability** so the report is visible only to maintainers. If that entry is not enabled, open only a detail-free public issue asking for a private contact channel. Do not publish reproduction steps, real session data, or exploitable details.

Include the affected version, a minimal reproduction, likely impact, and synthetic evidence without real session data.

## Response principles

1. Reproduce with synthetic data
2. Disable the affected execution path first when permanent deletion is involved
3. Add a regression test with the fix
4. Update the changelog and publish a patch release
5. Keep real local data out of remediation records
