# Contributing

[中文](CONTRIBUTING.md) · [English](CONTRIBUTING.en.md)

## Principles

- Keep it simple: reduce steps, concepts, and duplicate entry points
- Change only code directly related to the goal
- Keep actual state, recommendation, and plan separate
- Prefer recoverable actions over permanent deletion
- Support safety claims with synthetic regression tests
- Keep the default Chinese and English UI complete together

## Development setup

```bash
git clone <repository-url>
cd wushijing-codex-session-manager
python3 scripts/doctor.py --project-only
python3 -m unittest discover -s tests -v
```

Use Node.js 24 for dashboard checks:

```bash
node --check assets/dashboard/i18n.js
node --check assets/dashboard/app.js
```

## Dashboard changes

- Keep static Chinese source copy in `index.html`
- Render dynamic Chinese source copy through `t("Chinese source")`
- Add English translations to `assets/dashboard/i18n.js`
- Never duplicate the page or action logic for another language
- Review Chinese, English, 375px, desktop, keyboard focus, and console output

Automated tests fail when a Chinese UI source is missing an English mapping.

## Lifecycle action changes

Any change that moves, quarantines, restores, or deletes real data must:

1. Start with a synthetic failing test
2. Preserve the scan → plan → receipt → confirm → manifest → execute layers
3. Check database ambiguity, pinned state, relationships, conflicts, and Codex processes
4. Verify interrupted rollback and idempotent retry behavior
5. Update security documentation and the changelog

## Pre-commit checks

```bash
python3 scripts/doctor.py --project-only
python3 -m unittest discover -s tests -v
node --check assets/dashboard/i18n.js
node --check assets/dashboard/app.js
python3 scripts/package_release.py --output-dir dist
git diff --check
```

## Pull requests

A pull request must describe:

- The user-visible result
- Whether real sessions or destructive actions are affected
- Test evidence
- Compatibility or migration impact
- Chinese/English UI parity

Never upload real databases, session content, reports, manifests, or tokens.

## Versioning

The project uses semantic versioning:

- PATCH — compatible fixes
- MINOR — backward-compatible capabilities
- MAJOR — incompatible state, plan, or installation changes

Release tags must match `VERSION` exactly.
