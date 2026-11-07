# Client startup and console controls

The startup interface keeps the KagNode mark inside stage and download dialogs, so a whiptail redraw cannot erase the identity while image files are being pulled. Byte counts, speed and remaining time come from the transfer; reconnection is limited to three attempts. Interrupted network transfers resume their private partial file through the authenticated HTTPS range protocol. Certificate failures, changed image identity, wrong ranges, storage failures and checksum mismatches are never automatically retried as connection errors.

The published image's kernel must match the running Client or its verified one-time kernel transition. If a verified EFI includes kernel-version metadata, it must match the selected manifest. Unrelated PE sections, such as zero-filled BSS, are not treated as missing kernel payload. Alternate init-shell command lines are rejected, and an already attempted repair cannot loop. Driver reports include link state and common Ethernet, wireless, USB and firmware errors. These checks do not claim support for untested devices or drivers.

## Desktop splash

Future Client builds install a Plymouth theme showing KagNode × Ubuntu with a short loading indicator. The KagNode image is bundled; Ubuntu's original mark is copied from the target distribution's own `plymouth` package. Ubuntu is a trademark of Canonical; the original distribution copyright notices remain with that package. The theme does not imply a partnership.

The default boot command line uses `quiet splash` and suppresses ordinary boot chatter. Kernel ring buffers and the system journal remain available. Ubuntu's Plymouth services retain Escape-to-details and normal splash shutdown. Explicit errors and recovery menus remain available. The Client authority's ordinary output goes to the journal; its error output retains the existing console route.

Use the Builder's `--boot-details` option when preparing diagnostic media; it omits quiet/splash and disables Plymouth for that image. This prepares a new image through the existing validation workflow. Do not edit signed published artifacts or turn off image/certificate verification. Serial qualification retains its separate diagnostic command line.

## Web controls

- `/clients`: pair a Client and manage the existing accounts assigned to each approved device. Assignment changes are atomic; an active persistent account cannot be removed until it saves work and signs out. This does not terminate sessions or change passwords.
- `/images`: inspect published release IDs, current/retained status, kernel, architecture and combined artifact size. Publishing, activation and rollback remain separate protected operations.
- `/reports`: filter sanitized Client diagnostics and download a report as JSON. Credentials and private filesystem locations are not put into download links.

Every server-side control requires the existing local console credential and same-origin request checks. Requests are bounded. Repeating the same assignment is safe; an uncertain submission should be checked with Refresh before retrying. Console startup still attaches to the existing database without creating or migrating its schema.

## Verification boundary

Isolated tests cover the persistent download identity, bounded retries, trust/storage failure handling, kernel handoff validation, generated theme files and assignment authorization/active-session protection. Browser checks use a disposable authority. Actual Plymouth rendering, kernel/driver compatibility and physical boot behavior still require a separately authorized new image build and Server/Client qualification. No new image or live device rollout is included in this source update.
