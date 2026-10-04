# TransRealm application icon

The user rejected the first abstract speech-page symbol because its meaning was unclear. The revised icon uses two ordinary speech bubbles containing the visible characters **A** and **文**, in blue and white, so its translation purpose is explicit. Generated with the built-in imagegen tool on 2026-10-04; the original and the refinement prompt are recorded below.

Source artwork: `src/transrealm/ui/assets/transrealm.png`. Windows asset: `src/transrealm/ui/assets/transrealm.ico`, with 16, 20, 24, 32, 40, 48, 64, 128 and 256px frames. Reproduce the ICO with `.venv/Scripts/python.exe scripts/build_icon.py`; the native Qt conversion preserves artwork and alpha and adds no dependency.

The existing icon integration uses this asset in the sidebar, application/window and EXE. Revised visual and candidate evidence is under `.local/verification/t08-icon-v2/`. Previous artwork and evidence remain in Git history, prior package archives and `.local/verification/t08-icon/`.

## Generation prompt

```text
Use case: logo-brand.
Asset: one production Windows application icon for TransRealm / 译境, a translation app.
The meaning must be immediately obvious: TWO ORDINARY SPEECH BUBBLES labelled with different languages, exactly "A" and "文". This is a literal translation icon, with crisp familiar bubble silhouettes and readable large characters.
Composition: a softly rounded square tile in a restrained medium blue. A large white speech bubble at upper-left contains a bold blue Latin capital A. A second, slightly overlapping speech bubble at lower-right is a darker blue with a white outline and contains a bold white Chinese character 文. Both bubbles have a clearly visible conventional triangular chat tail. Keep the characters fully visible and separated. Only these two characters, no brand name or small text. Characters should occupy most of each bubble's face.
Flat, clean, modern, professional, high contrast. Use generous smooth rounded corners, simple thick shapes and thick typography so the two-language motif remains recognizable at 24px and 32px. No book, no folded pages, no ambiguous abstract monogram, no 3D, no texture, no gradients, no shadow, no decorative arrows or sparkles, no surrounding mockup, no watermark. The outside of the tile is genuinely transparent with smooth alpha edges. Square canvas, icon alone, centered, filling about 92% of the canvas.
Exact visible text: A and 文 (the standard Chinese character 文, with correct strokes).
```

## Refinement prompt

```text
Edit the provided translation application icon. Keep the exact composition, the two obvious speech bubbles, their positions, the blue-and-white palette, and the exact correctly formed characters A and 文.
Make this a crisp flat production icon. Remove all texture, grain, mottling, uneven shading and gradients; use uniform solid color fills. MOST IMPORTANT: clean the entire outer silhouette into ONE mathematically smooth rounded-square boundary. Remove every stray blue/cyan fragment, speck, halo, frayed pixel and paint splash outside that boundary. Everything outside the rounded tile must be 100% transparent, including the canvas edges. Preserve smooth antialiasing ONLY at the clean icon boundary. Keep balanced transparent padding on all four sides.
Do not redesign the symbol, do not add anything, do not change the letters, no shadows. The final result should look like a carefully rendered vector icon with clean typography and a completely clean alpha mask.
```
