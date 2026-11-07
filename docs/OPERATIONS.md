<!-- Retained operational documentation; historical version labels refer to their original release. -->
<p align="center"><img src="../assets/kagnode-wordmark.svg" width="440" alt="KagNode. HTTP Boot"></p>

# KagNode HTTP Boot

Open-source HTTP Boot Server, Builder and Client tooling. The Client boots an image delivered over the network with the project's existing activation, account, persistence and recovery workflows. Startup shows the KagNode symbol in blue when color is supported, with a plain text fallback for unattended consoles and `NO_COLOR`.

This repository is the public source export. It contains no private release images, signing secrets, Client credentials or saved user data. The existing local Server console is retained; no hosted cloud control plane is implied.

## Install and update

Read [installation instructions](../docs/INSTALL-v2.md) before using the packages. Source preview **3.1.16-beta.3** adds the private web console. The existing **3.1.16-beta.2** packages remain a branding/path preview until updated packages are published. Existing 3.1.15 releases and their verification records remain in history. This preview does not replace a qualified desktop image or claim new physical hardware qualification.

New paths are under `/opt/kagnode/httpboot`, `/etc/kagnode/httpboot`, `/var/lib/kagnode/httpboot` and related Server/Builder project directories. Existing systems need the explicit migration procedure in [PATHS.md](../PATHS.md). It preserves original data and compatibility links, can resume interrupted copies and supports rollback while retaining newer writes for review. No running Server, Builder, Client session or saved data is migrated by publishing source.

## Private web console

The optional KagNode web console has separate `/overview`, `/clients`, `/accounts`, `/reports` and `/access` pages. It reads the existing authority, shows sanitized boot health and approves pending Clients with selected existing accounts. It does not build images, create cloud services or restart Clients.

Run `sudo httpboot-web` (or `sudo httpboot-server web-console`) on an installed Server. It binds **127.0.0.1:8084** and creates a separate protected `web-console-token` in the Server state directory. The existing authority must already exist; the standalone console does not create a database or run migrations. To enable automatic startup, use `sudo systemctl enable --now kagnode-httpboot-web` after installing a package that contains it.

From your workstation, forward the private listener with `ssh -L 8084:127.0.0.1:8084 USER@SERVER`, then open `http://127.0.0.1:8084`. Read the console credential locally with `sudo cat /var/lib/kagnode/httpboot-server/web-console-token` and enter it in the connect screen. Never publish that credential. It is retained only in the browser tab’s session storage; **Lock console** clears browser access. Restarting the web console rotates its credential. Native Client credentials and the legacy console token are separate.

The UI uses the shared KagNode styling, keyboard focus, small-screen navigation and reduced-motion support. Readable sources are under `web/`; regenerate the committed asset module with `ESBUILD=/path/to/esbuild python3 scripts/build-web.py` (esbuild 0.28.2). Delivered CSS/JS are minified and fingerprinted without public source maps. This helps identify builds and cache assets; it cannot prevent browser inspection or reuse allowed by the license.

## Repairing update progress

If an older Client reports `dict.update() got multiple values for keyword argument 'elapsed_seconds'`, run `sudo python3 scripts/repair_update_progress.py` from a checked source checkout **on that Client**. `--check` validates compatibility without modifying files. The helper recognizes only the affected progress method, backs up the original in private RAM storage, waits for saves and update operations to finish, and checks the existing ordinary-service-restart guard before restarting the Client authority. It verifies session identities after restart; it does not reboot, release accounts or close applications. Choose **Retry** in the Updates page if staging does not resume automatically. An unfamiliar Client revision is refused rather than overwritten. Future images must include the corrected `client_updates.py`; this runtime repair alone does not change a signed image.

## Build and verify

Use Ubuntu 24.04 and the dependencies in the CI workflow. Build packages with `packaging/build-server-deb.py`; `packaging/public-source.py` creates an allowlisted source archive. Run `python3 -m unittest discover -s tests -p 'test_v2*.py' -v`. Image builds and hardware qualification are separate operations with their own resource requirements and evidence.

## License

Current combined release and new original work: **AGPL-3.0-only**. Earlier MIT-covered code retains the notice in `LICENSES/MIT-legacy.txt`; third-party code and fonts retain their own licenses. Prior MIT releases remain usable under their original grants. [Brand policy](../BRAND-POLICY.md) does not forbid forks or rebranding permitted by software licensing.

[KagNode](https://nebulacoder.com) · [Developer](https://developer.nebulacoder.com) · [Logos](https://github.com/every-lemon/kagnode-logos)
