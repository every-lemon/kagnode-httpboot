## Ecosystem update panel — packaging preview 2

## Shared loading spinner preview

Use KagNode Core 1.0.5 for the shared split-orbit loading mark, with reduced-motion support and existing status/recovery controls retained. This changes web presentation without resetting data or provisioning native services.

## Core integration preview

Shared local UI components, manual animated navigation, natural scrolling rails and icon account menus. Added separate appearance-only account connections and signed UI patch controls. Existing storage, native services and prior release records are retained.

- Add local-administrator update checks, review and progress through KagNode CLI.
- Keep local permissions, CSRF checks, data paths and native provisioning unchanged.
- Source preview only; no new hardware qualification or native deployment claim.

## Unreleased — 3.1.16 qualification

- Show boot-media copy, flush and readback stages separately, with measured copy progress and an indeterminate state during device waits. Coalesce durable progress samples to reduce boot-card fsync traffic.
- Keep desktop sessions running during ordinary Client-authority restarts while retaining startup ordering and PAM session checks; guard legacy runtime repair against custom display dependencies.

- Fix update downloads failing when their progress callback supplies its own elapsed time; retain transfer measurements and stage timing fallback.

- Treat unknown serial-console dimensions as 80 × 24, keep pairing codes and transfer status visible, and use readable text on genuinely tiny terminals.

## 3.1.16-beta.3 — Web console 0.1.0 (source preview)

- Added a separate localhost web server with routed KagNode pages, Client review, existing account assignment and sanitized reports.
- Added bounded requests, same-origin checks, independent console credentials and fingerprinted UI assets.
- Retained native Server/Client services, image qualification status and existing release history.

Client and recovery images use the KagNode application paths. Offline image
preparation retains legacy launchers through a compatibility link, rejects
conflicting trees, and keeps new code paths readable under a private umask.
Legacy build-only configuration is also excluded when reusing an image cache.
Existing published images, Client sessions and saved work are unchanged.
Debian upgrades also restore package-owned compatibility links from a verified
migration journal, without activating services or replacing existing data.

The Server keeps an idle SQLite connection to avoid checkpointing and recreating
the write-ahead log after every request. Durable commits and independent read
transactions are retained. Storage contention returns a structured temporary-busy
response; other database errors return a generic storage error. Clients do not
automatically replay submissions after an error, and pending saves remain pending.

## 3.1.16-beta.2

Larger canonical ASCII startup logo, mixed-case wordmark, responsive terminal sizes and blue/plain output. Boot behavior and deployment remain unchanged.

# 3.1.16-beta.1

KagNode branding, project-scoped path defaults and an explicit migration tool. Source history and prior releases are retained. See PATHS.md and LICENSES/.

# 3.1.15-beta.2

Fixed for update 3.1.15-beta.2

## Account profile integration preview

Added optional KagNode Account display-name/photo linking, local administrator disable controls and private credential storage. Existing local account authentication and data remain independent.
