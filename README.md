<p align="center"><img src="assets/kagnode-wordmark.svg" width="440" alt="KagNode."></p>

# KagNode HTTP Boot

## Overview

Network boot, authenticated image delivery, desktop persistence and recovery tooling.

## Release status

Product source: **3.1.16-beta.3**. Packaging preview: **3.1.16-beta.3.packaging.6**.

Packaging prereleases do not change the latest stable release or establish new hardware or service compatibility. See [verification](docs/VERIFICATION.md) and [changelog](CHANGELOG.md).

## Features

- Persistent branded download dialogs, bounded authenticated resume retries, verified kernel handoff checks and driver/link diagnostics.
- A KagNode × Ubuntu desktop splash recipe with an explicit diagnostic-media option. New image and hardware qualification remain pending.
- Web controls for approved Client account assignments, image/kernel inspection and report filtering/downloads.

- Separate Server authority, Builder tooling and Client integration.
- Account assignment, image delivery, persistence and recovery.
- Private routed web console with independent access controls.

Optional KagNode Account linking syncs your display name and photo after explicit approval. Your local application administrator can disable it. Local sign-in and permissions stay independent.

## Requirements

Use the existing Server/Client prerequisites. The optional Builder remains amd64-specific; preview RPMs do not qualify Rocky Linux boot or image-building operation.

## Installation and downloads

Download from [GitHub Releases](https://github.com/every-lemon/kagnode-httpboot/releases). Verify `SHA256SUMS` before extracting or installing a package.

| Payload | Formats | Support |
| --- | --- | --- |
| Complete source / artwork | `.tar.xz`, `.tar.gz`, `.zip` | Named top-level directory; manual setup |
| Source preview | `.deb` | Source only; does not provision a service |
| Source preview | `.rpm` | Rocky Linux 10 packaging preview; native services unverified |

Existing Server/Builder `.deb` and Builder installer workflows remain available.

Source packages install under `/usr/share/kagnode/`; they do not replace an existing application, migrate data, start services or configure networking.  See [package details](docs/PACKAGING.md).

## Usage

```sh
python3 httpboot/server_v2.py --help
# Read docs/INSTALL-v2.md before native setup.
```

See [operations and existing setup instructions](docs/OPERATIONS.md) for the full workflow and its prerequisites.

## Configuration and storage

Shared presentation uses [KagNode Core](docs/CORE.md), with a pinned local fallback and reviewed server adapters. Compatible stable UI patches have a separate local-administrator policy.

Retain existing server authority, image stores and verified user saves. Source packaging never builds a Client image or restarts native services.

## Security

Use HTTPS and least-privilege accounts for hosted services. Keep secrets and user data out of Git. Preview packages are for inspection and controlled testing; native service and hardware claims remain limited to recorded verification. See [security guidance](docs/SECURITY.md).

## Development and testing

```sh
python3 -m unittest discover -s tests -p 'test_v2*.py' -v
python3 scripts/repository_check.py
python3 scripts/format_source.py --check
python3 scripts/release.py --output dist/packages
```

Install the formatting dependencies from `requirements-format.txt`. Package building additionally needs `dpkg-deb`, `rpmbuild`, XZ support and, for CLI binaries, Go. Read [the repository map](docs/STRUCTURE.md) before editing generated files.

## Documentation

- [Ecosystem installation and updates](docs/ECOSYSTEM.md)

- [Startup, splash and web controls](docs/BOOT-EXPERIENCE.md)

- [Repository structure](docs/STRUCTURE.md)
- [Operations](docs/OPERATIONS.md)
- [Packages and release process](docs/PACKAGING.md)
- [Verification and limits](docs/VERIFICATION.md)
- [KagNode Account linking](docs/ACCOUNT-SYNC.md)
- [Changelog](CHANGELOG.md)

## Licensing

See [LICENSE](LICENSE) and retained third-party notices. KagNode artwork retains its separate permission and brand policy; the application uses AGPL-3.0-only.
