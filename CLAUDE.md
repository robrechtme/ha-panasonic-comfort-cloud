# panasonic-cc — Home Assistant custom integration (HACS)

## Release process

HACS tracks updates via GitHub releases, not commits — a merged fix/feature isn't
visible to installs until released.

1. Bump `version` in `custom_components/panasonic_aquarea/manifest.json`
   (semver: patch for fixes, minor for new entities/features).
2. Update `README.md` if entities or behavior changed.
3. Commit as `docs: <summary>; bump vX.Y.Z`.
4. Tag the commit `vX.Y.Z` and push both: `git push origin master --tags`.
5. `gh release create vX.Y.Z --title "vX.Y.Z — <short theme>" --notes "..."`
   (see past releases for title/notes style, e.g. `v0.3.0 — energy`).
