# KagNode httpboot paths

New installations use project-scoped application, configuration, state and log directories. Upstream operating-system locations are retained.

- `/usr/lib/httpboot-source` → `/opt/kagnode/httpboot/source`
- `/etc/httpboot-build` → `/etc/kagnode/httpboot-builder`
- `/etc/httpboot` → `/etc/kagnode/httpboot`
- `/var/lib/httpboot-builder-v2` → `/var/lib/kagnode/httpboot-builder`
- `/var/lib/httpboot-build-cache` → `/var/cache/kagnode/httpboot`
- `/var/lib/httpboot-server` → `/var/lib/kagnode/httpboot-server`
- `/var/lib/httpboot` → `/var/lib/kagnode/httpboot`
- `/opt/httpboot` → `/opt/kagnode/httpboot`
- `/var/log/httpboot` → `/var/log/kagnode/httpboot`

Existing installations are not migrated automatically. Stop the listed application and data-writing services, take your normal external backup, and inspect `python3 scripts/migrate-paths.py` (dry-run). Then run with `--apply` only after reviewing its exact paths. The journal permits resuming an interrupted copy. The tool retains original directories and verifies copied content, ownership and modes before adding compatibility links. Install the matching new application release and review service configuration before starting it.

`--rollback` restores retained originals and preserves any post-migration writes in a separately named tree for review; it does not silently merge newer data into the old state. `--root` is for disposable fixture tests. No servers, images, Client sessions or user saves were migrated by publishing this release. Never run this migrator against another project that happens to use a similarly named directory.

New shared parent directories are created with mode `0755`, including when the administrator uses `umask 077`. Copied project directories and private files retain their original ownership and permissions. Existing parent permissions are left unchanged; review service-user access to those parents before restarting an existing installation.

Debian may remove the package-owned `/usr/lib/httpboot-source` compatibility
link during an upgrade. Package configuration restores missing links only from
a completed migration journal with retained originals and valid destinations.
It refuses unrelated files or links and starts no service. Operators can run
`python3 scripts/migrate-paths.py --repair-links` to repeat this check.

Large Builder caches need separate review: they can exceed the space available
for a verified copy and contain filesystem images with device nodes that the
general copier deliberately refuses. After stopping Builders, confirming the
worker lock is free and checking for mounted filesystems inside the cache, an
operator can relocate the cache to `/var/cache/kagnode/httpboot` on the same
filesystem. Migrate the remaining application paths while the old cache path is
absent, then create its compatibility link. Verify the directory identity and
build checkpoints before reuse. This preserves the current cache without making
an immutable duplicate; moving it back restores its location, not an earlier
cache snapshot. Keep qualified images and user saves separately.

Client and recovery images install their application code in
`/opt/kagnode/httpboot/client` and fonts in
`/usr/local/share/fonts/kagnode/httpboot`. The offline image builder moves a
retained legacy Client library without copying or deleting its contents, then
leaves `/usr/local/lib/httpboot` as a compatibility link for retained launchers.
Conflicting trees or unexpected symlinks stop the build for review. This image
step never migrates a running Client, its RAM session, or its saved work. The
small `/httpboot` directory inside the initial RAM disk is a boot payload, not
a persistent system installation.
