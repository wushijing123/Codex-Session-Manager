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

- The dashboard binds only to `127.0.0.1`
- Initial access requires a one-time launch token; POST requests require CSRF
- Historical content is rendered with `textContent`, never as HTML or commands
- Scanning is read-only by default and plans remain separate from actual state
- Automatic recommendations never create permanent deletion plans
- Permanent deletion requires an explicit choice, receipt, second confirmation, and process gate
- Active, pinned, protected, conflicting, unindexed, ambiguous, or related sessions block execution
- Actions are limited to validated exact files; recursive, wildcard, and symlink targets are rejected
- Failures prefer rollback instead of hiding partial commits
- Successful permanent deletion keeps only a redacted audit record

## Never upload

Do not include these in issues, pull requests, releases, or commits:

- `state_*.sqlite`, WAL, or SHM files
- Session `.jsonl` files
- Launch tokens, API keys, or cookies
- Quarantine packages, cold storage, manifests, or reports
- Real session titles, content, or private absolute paths

## Reporting a vulnerability

This is a private repository. Use a private security report visible only to maintainers. If GitHub Private vulnerability reporting is not enabled, contact the repository owner directly and do not create a public issue.

Include the affected version, a minimal reproduction, likely impact, and synthetic evidence without real session data.

## Response principles

1. Reproduce with synthetic data
2. Disable the affected execution path first when permanent deletion is involved
3. Add a regression test with the fix
4. Update the changelog and publish a patch release
5. Keep real local data out of remediation records
