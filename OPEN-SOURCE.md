# Source distribution

PaperOS is a native Linux userspace and application platform for the Kindle KT3.
The existing vendor kernel and device-specific firmware are supplied by the owner;
this repository does not distribute Amazon firmware, backups, credentials or games.
Only KT3 has been validated. Other Kindle models require their own hardware port.

Original PaperOS code is GPL-3.0-or-later (LICENSE). Third-party code retains its
own license. FBInk is GPL-3.0-or-later at the commit in sources.lock.json.
stb_truetype uses its MIT/public-domain dual license. Noto CJK is SIL OFL 1.1.
The Go service uses klauspost/compress under BSD-3-Clause (go.mod/go.sum).
KOReader, its plugins, and optional game emulators retain their respective licenses.
No commercial game ROMs are included or required by the launcher/store.

## Build the launcher and service

Use Linux or Ubuntu WSL, a C11 compiler, Python 3 and make. Fetch pinned sources
with `python3 scripts/fetch-sources.py` and public font/header assets with
`python3 scripts/fetch-assets.py`. `make -C native` builds the host renderer.
`bash scripts/build-services.sh` fetches and verifies the Go version pinned by
services/toolchain.json, then builds host and ARM soft-float services.

The native ARM build needs an ARM EABI soft-float musl toolchain and FBInk:
set PAPEROS_MUSL_PREFIX to its absolute prefix, then use scripts/build-muyu.sh
or scripts/build-koreader-overlay.sh as the cross-compilation example.
The full independent root filesystem is a Buildroot external tree in os/.
Some deployment/recovery scripts retain workstation path defaults; read their
arguments and adapt local paths before using them. They are not a universal flasher.
Never apply a KT3 boot image to another model. Preserve a verified recovery backup.

## Test

Build the host C program; run `go test -race ./...` inside services, and
`python3 -m unittest discover -s tests`. The optional framebuffer render test
`python3 scripts/test-store-ui.py` needs Pillow and the fetched Noto font.
Real hardware remains necessary for e-ink, touch, sleep and power verification.

The store catalog and app releases live in the separate paperos-apps repository.
STORE.md documents compatibility and installation boundaries. Signing keys are
never source files. Public example NAS addresses use RFC 5737 documentation IPs;
substitute your own addresses and retain restrictive network permissions.
