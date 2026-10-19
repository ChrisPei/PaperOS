# NDS application for PaperOS KT3

Target: **逆转裁判：复苏的逆转**, the user's Japanese NDS image with ACE text
and fciq 2023 image translation. This is a separate, locally executing ARM
application using the pinned DeSmuME2015 core. It retains the NDS game; there
is no GBA substitution, PC streaming or rewritten game script.

The application package contains no commercial ROM, Nintendo BIOS or Nintendo
logo. The user supplied the local game archive; only its `.nds` member was
extracted. No executable from that archive was run.

## Implemented

- Both 256×192 screens at integer 2× scale in the 600×800 framebuffer. Touch
  the bottom screen directly; side rails provide A/B/X/Y, L/R, Start, Select,
  menu, full refresh and held simulated microphone noise (吹气). Direction
  buttons are in the pause menu.
- Game/input execution paced at 60 Hz independently from panel refresh. Core
  frameskip 9 renders one image every ten emulated frames; the panel updates
  at most four times a second when pixels change. RGB565 conversion uses an
  exact 65,536-entry grayscale lookup table. A 60 Hz game clock is not a 60 Hz
  physical display: animations are intentionally sparse on e-ink.
- Quick save/load, automatic resume after normal exit, and save-and-return to
  the launcher. State files have atomic publication, payload SHA-256 and
  bindings to the full ROM SHA-256 and exact core revision. Corrupt, truncated,
  other-ROM and other-core states are rejected. Save writes can take a few
  seconds; wait for the completion message before another action.
- The core also writes ordinary `.dsv` game saves. These are distinct from
  PaperOS snapshots. A first-episode in-game save was reloaded from disk in a
  new process with the runtime snapshot removed from the QA directory.
- Existing PaperOS lock, full lock-screen cleanup, alarm/transfer overlays and
  sleep-display acknowledgement are shared with the native launcher. Game
  execution pauses under system overlays. The suspend worker now recognizes
  installed native foreground processes exec'd directly by PaperOS, checks
  process start identity and pauses/resumes them along with the launcher.
  External power still means five-times idle timeout and no hardware suspend.
- The normal `.papp` installer/uninstaller manages the executable. ROMs and
  saved progress are external data; uninstalling the program preserves them.

## Build, import and install

In the existing WSL Ubuntu-24.04 build environment:

```sh
python3 /mnt/d/kindle/scripts/build-nds-player.py
python3 /mnt/d/kindle/scripts/test-nds-player.py
python3 /mnt/d/kindle/scripts/test-nds-device.py
python3 /mnt/d/kindle/scripts/import-ace-attorney.py /path/to/your/game.nds
```

`dist/ace-attorney-1.papp/` is the application. Send it through the existing
PaperOS app receiver or install it through the pinned development SSH connection:

```sh
paperos --install /path/to/ace-attorney-1.papp
```

The importer checks image bounds, streams the user-owned image over pinned SSH,
checks the device SHA-256 and atomically changes the selection. It does not
download games. A newer image gets separate saves instead of silently reusing
progress from another translation revision. The player supports images up to
128 MiB; do not raise the general 64 MiB application-package limit for ROMs.

| Device path | Purpose |
| --- | --- |
| `/var/lib/paperos/apps/org.paperos.ace-attorney-1/` | Installed executable and entry script |
| `/mnt/us/paperos/games/ace-attorney-1/<sha256>.nds` | Immutable imported game image |
| `/mnt/us/paperos/games/ace-attorney-1/current.sha256` | Selected image |
| `/var/lib/paperos/apps/.data/org.paperos.ace-attorney-1/<sha256>/` | `.dsv`, `quick.state`, `resume.state` |
| `/var/lib/paperos/apps/.data/org.paperos.ace-attorney-1/session.log` | Last application session log |

The FAT userstore is mounted **noexec**. Installed programs execute from the
independent ext3 root; short-lived QA binaries execute from `/run`. Do not
remount the userstore executable or export the live root image as a USB disk.

## Validation and limits, 2026-10-18

Physical KT3 tests of original, source-authored homebrew pass touch boundaries,
core touch coordinates, A press/release, simulated ADC noise and its release,
pause behavior, paced execution, atomic save/load, corruption rejection and a
second-process resume. Host SHA-256 checks cover nine standard/boundary cases.
The local QEMU-user ARM JIT check raises SIGILL; this is not counted as a pass.

The supplied 64 MiB image has game code `AGYJ`, title `GYAKUTEN YOM`, SHA-256
`e5335868311982c26beba9446d5fe89c7189eb29496c293789539a237bbae837`.
It boots on the physical KT3, displays the translated title/episode selection
and progresses through the first episode's waiting-room dialogue using actual
game input, then reaches the first courtroom scenes. These are real game
captures, not mockups.

The installed application also passed quick save/load, save-and-return,
reopening the saved scene, lock/unlock with full cleanup, a real ten-second
countdown overlay whose Stop button returns to the game, and foreground-process
stop/resume. The latter was a bounded pause test, not a new hardware suspend
cycle; the device stayed connected to external power throughout this integration.

Two ARM UI regression tests run under QEMU without loading the ROM/JIT, against
the real isolated host backend. They verify Stop returning to a locked state
and Snooze preserving an unlocked state. This is separate from the known QEMU
ARM JIT failure and from the physical-device game tests.

At the same episode-selection screen, a 300-frame headless measurement changed
from 32.908 to 112.781 emulated frames/s after reducing rendering and adding
the conversion LUT. Opening sequences measured 90–104 emulated frames/s;
waiting-room dialogue samples were mostly 68–89 with some slower transitions.
These unthrottled measurements exclude EPDC and measure processing headroom.
The installed application's title and waiting-room pause menus separately
showed approximately 100% game speed while driving the physical framebuffer.

Full-game completion, later investigation/3D evidence interactions and the
fifth episode's microphone puzzles have **not** been certified. Simulated
microphone ADC input is proven in the core test, not by completing those
puzzles. The device has no speaker or physical microphone.

Runtime reports, screenshots and local game data stay under ignored
`build/nds/`. Headless game-session saves are isolated under the userstore's
`.validation/` directory and do not replace the installed app's progress.
Run one emulator instance at a time during device QA.

## Sources

DeSmuME2015: <https://github.com/libretro/desmume2015>, commit
`422b688009ccb9f2917c086a8fe79c8cecb030ae`. No core source changes were required.
The ARM JIT files carry GPLv3-or-later notices; preserve upstream licenses,
copyright notices and corresponding source when distributing linked binaries.
FBInk is pinned in `sources.lock.json`. The repository's native adapter and
source-authored probe ROMs use the repository's GPLv3 license.
