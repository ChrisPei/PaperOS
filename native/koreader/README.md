# KOReader on PaperOS KT3

The application is the official KOReader **kindlepw2 v2026.07.1** release,
installed as `org.paperos.koreader`. It runs locally on the independent
PaperOS userspace; the vendor framework, KUAL and original Kindle UI are not
runtime requirements.

Build with `bash scripts/build-koreader-overlay.sh` followed by
`python3 scripts/build-koreader.py` inside Ubuntu-24.04 WSL. The builder verifies
the release's published SHA-256. The pinned archive, upstream AGPL license,
GNU runtime copyright notices and source receipt are retained. The native
overlay helper is built from this repository's `native/paperos.c`.

The result is `dist/koreader.papp/`, within the existing 64 MiB / 256 entry
package limit. The official distribution contains over 1,000 files. Its code
and the app's isolated GNU loader live in a compressed 128 MiB read-only ext3
image. First launch verifies and expands the image under
`/mnt/us/paperos/app-cache/org.paperos.koreader/<sha256>.ext3`; it can take
several minutes. Later launches verify that cached image before mounting it
read-only under `/run/paperos/koreader-runtime`. The FAT userstore retains
`noexec`; the system's musl runtime, vendor kernel and boot partitions are
unchanged. Normal exit unmounts the app runtime.

`KO_HOME` points to the app's normal persistent data directory. App removal
preserves settings, book annotations, progress and the runtime cache. The
package owns its executable and overlay helper. Upstream's stock-firmware
launcher and OTA updater are bypassed; update through a new verified `.papp`.

The small Lua adapter retains the upstream KT3 display and touchscreen backend.
It skips Lab126's absent fake event generator and reads existing PaperOS network
state. Wi-Fi and Tailscale configuration remain in PaperOS settings.
Every half second it checks the existing local state snapshot. For system
overlays it closes KOReader input, runs the shared native lock/reminder/transfer
interface, then opens input afresh and fully repaints the preserved book.
Real input reports activity to the OS. The helper reuses the established full
lock cleanup and sleep-display acknowledgement; it introduces no network API.

To leave, tap the top menu, choose its rightmost tab, then **返回 PaperOS**.
This is a direct action, without an empty submenu. Alternatively, short-press
Power and tap **返回 PaperOS** on the lock screen. Both paths use upstream's
normal Exit event to save reading state before returning to the launcher.
Normal unlock instead restores the same book.

## Physical validation, 2026-10-19

The legal sample shelf is `/mnt/us/documents/Reading-Samples`. Fetch it with
`scripts/fetch-reading-samples.py` (requires PyMuPDF for the explicitly derived
CBZ sample). `sources.json` retains original URLs and SHA-256 values.

Verified by actual framebuffer captures and page turns on the physical KT3:

| Format | Sample | Result |
| --- | --- | --- |
| EPUB | Lu Xun, Nahan; Lewis Carroll, Alice | Chinese/English text and page turns |
| PDF | Allen B. Downey, Think Python 2 | 244 pages, first/second-page display |
| MOBI | Nahan, Gutenberg download | Chinese text, 234 pages |
| TXT | Nahan, Gutenberg UTF-8 download | Unicode text, 367 pages |
| FB2 | Explicit conversion of downloaded Nahan text | Chinese text, 243 pages |
| HTML | Gutenberg Nahan HTML with its cover | Chinese text, 314 pages |
| CBZ | First eight Think Python PDF pages rendered to grayscale | Image pages and page turns |
| AZW3 | Gutenberg Nahan KF8 download | Failed: forcing the AZW provider produces garbled text; no provider override is shipped |

The unsupported AZW3 original remains in the computer's download folder, outside
the device's trial shelf. No DRM removal was performed. These are sample-format
checks, not a certification of every possible book in these formats.

The native lock image, normal unlock, both black/white phases of a real
countdown interrupt and return to the same page, menu Exit and lock-screen Exit
were exercised. A new process reopened Nahan EPUB at its saved page 7/312.
The pre-test ten-second countdown duration was restored. Existing NAS
permissions, credentials, games and app data were verified unchanged. This work
does not claim an additional physical suspend cycle: the KT3 remained on USB
power. Local captures and validation records are under ignored `build/`.

KindleForge was also requested. Its official `v4.1.0-eol` release retires 4.x,
removes the downloadable assets and says the application is unavailable while
the KPM-based successor is prepared. No unavailable/archived installer is
presented as a working PaperOS app:
<https://github.com/KindleTweaks/KindleForge/releases/tag/v4.1.0-eol>.
