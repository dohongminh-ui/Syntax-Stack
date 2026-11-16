# Social assets

HTML sources for the images in `frontend/`. They reuse the app's `css/base.css` (tokens, grain, real keycap).
Needs network for Google Fonts. `build.ps1` regenerates everything; the raw commands are below.

Social card (run from the repo root):

```
"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --screenshot=frontend/og-image.png --window-size=1200,630 --hide-scrollbars --force-device-scale-factor=1 --virtual-time-budget=4000 file:///F:/projects/sextax/tools/social/og-card.html
```

Icons: `icon.html?s=SIZE[&mask=1]`, with `--window-size=SIZE,SIZE`; 192, 180 and 32 are downscaled from the 512 render.
Outputs: `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` (`&mask=1`), `apple-touch-icon.png` (180).
`favicon.ico` is a 32px PNG wrapped in an ICO header (stdlib, done by `build.ps1`).

`set-site-url.py https://your-domain` rewrites the site domain in `index.html`, `robots.txt`, `sitemap.xml`.

Headless Edge can render the window a few px short; `build.ps1` checks the size and crops with System.Drawing if needed.
