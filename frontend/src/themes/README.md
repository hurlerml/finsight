# Theme palettes

Each file defines the full `:root` (light) and `.dark` token set.

## Switch palette

In `src/index.css`, change the import to exactly one palette:

```css
@import "./themes/warm-gold.css";
@import "./themes/ink-copper.css";
@import "./themes/glass-insight.css";
```

Light/dark mode (`finsight.theme` in localStorage) stays independent — it only toggles the `.dark` class.

## Glass notes

`glass-insight` expects translucent surfaces (`glass-surface`, `bg-card/55`, `backdrop-blur`). Soft glow blobs use `--glow-1` … `--glow-3`.

## Add a new palette

1. Copy an existing file in this folder.
2. Edit the HSL channel values (`H S% L%`, no `hsl()` wrapper).
3. Import it from `index.css` instead of the previous one.
