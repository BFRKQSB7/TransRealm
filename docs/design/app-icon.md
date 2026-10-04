# TransRealm application icon

Created with the built-in imagegen tool on 2026-10-04 for the rounded desktop UI. A charcoal rounded tile and two ivory speech-page shapes suggest reading and exchange between languages. The outer canvas has genuine alpha transparency.

Original generated artwork: `src/transrealm/ui/assets/transrealm.png`. Windows asset: `src/transrealm/ui/assets/transrealm.ico`, with 16, 20, 24, 32, 40, 48, 64, 128 and 256px frames. Run `.venv/Scripts/python.exe scripts/build_icon.py` to reproduce the ICO using the existing Qt dependency; conversion preserves the artwork and alpha. No API key or fallback CLI was used.

The runtime loads the ICO relative to the UI module; the build embeds it in the EXE and includes it for Qt windows and the sidebar. Keep the PNG as the editable source asset. Small-size inspection and artifact evidence are recorded under `.local/verification/t08-icon/`.

## Generation prompt

```text
Use case: logo-brand.
Asset type: production Windows desktop application icon for "TransRealm / 译境", a local AI-assisted translation workspace.
Create one polished, original icon, square 1024x1024 composition. A warm charcoal rounded-square tile with generous smooth rounded corners, centered and occupying about 92% of the canvas. Inside, a bold ivory symbol made of two interlocking rounded speech-page shapes facing one another, with a clean diagonal negative-space seam, suggesting an open book and an exchange between languages. Make the silhouette extremely simple, balanced, memorable, and clearly legible at 16px, 32px and 48px. Match a quiet modern monochrome desktop UI with rounded controls.
Flat vector-like precision, thick forms, excellent optical balance. No text, no letters, no tiny details, no gradients, no 3D, no texture, no decorative sparkles, no watermark, no mockup, no surrounding UI, no extra icons, no resemblance to OpenAI's knot logo. The area outside the charcoal rounded tile must be truly transparent; preserve smooth alpha edges. Deliver the icon alone, front-facing and centered.
```
