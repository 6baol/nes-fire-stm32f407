# Pixel UI font

Press Start 2P, Copyright 2012 The Press Start 2P Project Authors.
Source: https://github.com/google/fonts/tree/main/ofl/pressstart2p
License: SIL OFL 1.1, bundled in OFL.txt. The reserved font name is unchanged.
The original font hash and generated dimensions are in manifest.json.

The UI uses real 8x8 glyphs at integer 1x/2x/3x size, without antialiasing.
Lowercase is displayed as uppercase. Glyphs are streamed directly to the MCU
LCD. The table uses 760 bytes of Flash and no menu framebuffer. The compiled
ARM renderer's scaling and clipping are checked by Tests/render_menu_arm.py.
Only interface text changes; the emulated game's own graphics stay unchanged.

Regenerate with: python Nes_fire_emulator/tools/embed_pixel_font.py
Then run the project's build.ps1 for a local preview build.

The NES/SNES-inspired theme does not imply SNES game emulation.
Current user preference is local builds and previews only. No flashing or
board tests until the user explicitly requests them.
