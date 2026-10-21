# JetBrains Mono (vendored, offline)

TODO: this directory is missing the actual font binaries. This build
environment has no network access and no `fonttools`/`pyftsubset`, so the
real `.woff2` files could not be fetched or subset here.

To finish vendoring (offline-safe, per CLAUDE.md hard rule 7):

1. Download JetBrains Mono (OFL-licensed) from
   https://github.com/JetBrains/JetBrainsMono/releases — the Regular (400)
   and Bold (700) static weights.
2. Subset to ASCII (`U+0020-007E` is enough for this numeric dashboard):
   ```
   pip install fonttools
   pyftsubset JetBrainsMono-Regular.ttf --output-file=JetBrainsMono-Regular.woff2 \
     --flavor=woff2 --unicodes=U+0020-007E
   pyftsubset JetBrainsMono-Bold.ttf --output-file=JetBrainsMono-Bold.woff2 \
     --flavor=woff2 --unicodes=U+0020-007E
   ```
3. Drop the two `.woff2` files in this directory. `dashboard.css`'s
   `@font-face` rules already point here — nothing else needs to change.

Until then, `dashboard.css` falls back to `ui-monospace, monospace`, which
still gives tabular numerals on most platforms, so the dashboard is usable
without this step.
