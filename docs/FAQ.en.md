# FAQ

[中文](FAQ.md) · [English](FAQ.en.md)

## How is Codex archive different from cold storage?

Codex archive removes a session from the everyday view while keeping its local log, so it normally does not reclaim space. Cold storage verifies the content and database snapshot, saves a recoverable package, and removes the session from the Codex index. It frees space on the Codex disk only when the destination is on another disk.

## Will a restored session return to Settings → Archived chats?

Yes. Restore returns the original JSONL to `archived_sessions` and restores the database row with `archived=1`, so the session returns as an archived Codex conversation rather than an active one. In the real macOS test on 2026-08-23, a fresh dashboard scan also recognized it as a regular archive.

## Do the conversation and dates change after restore?

They did not change in the real restore test. The restored JSONL had the exact pre-archive SHA-256. Session ID, title, `created_at`, `updated_at`, `archived_at`, and their millisecond fields retained their original values. Restore time is written only to a separate audit record and never impersonates the conversation update time.

## Why is the restore button sometimes disabled?

Restore writes both the file and database index, so Codex must be fully closed. The button is enabled only after the machine completes one real running → fully closed → restored loop. A manually created marker does not count.

## Why does a plan still appear after confirmation?

Confirmation creates an immutable execution manifest; it does not mean files have moved. v0.6.0 locks and hides the duplicate plan while a manifest exists, clears the completed plan after execution, and keeps only the completion or failure record. If an old plan remains, confirm that v0.6.0 or later is running and refresh sessions.

## Is “Lock this session out of cleanup” cold storage?

No. A lock only excludes the session from recommendations and actions. It does not change the file or Codex state. Cold storage is the action that moves content and creates a restore package.

## Why does the cold-storage folder use a native picker?

The picker avoids path-typing mistakes. Advanced manual input remains available, but Save immediately checks that the directory exists, is writable, and does not dangerously overlap the home or Codex data directory.

## Does cold storage always reclaim disk space?

No. Moving within the same disk only reorganizes files. Moving to another disk, such as an external drive, reclaims space on the original disk. The operation receipt states which case applies.

## Is conversation data uploaded?

No. Inventory, summaries, plans, hashes, restore, and audit all run locally; the dashboard binds only to `127.0.0.1`. Never upload databases, JSONL logs, cold packages, launch tokens, or real reports to an issue.

## Which platforms are supported?

macOS is the fully tested execution platform. Linux CI covers inventory, dashboard, reports, tests, and packaging; native folder selection and desktop-app shutdown may differ. Windows is not yet verified.

## Should I permanently delete the only copy of an important session?

No. Keep an independent backup and validate cold storage or the 14-day quarantine restore first. Permanent deletion cannot be recovered, and its complete real-machine flow is still marked unverified.
