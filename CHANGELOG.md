# Changelog

Each release has a section; its text becomes the GitHub release notes and the Marketplace's
"what's new". New entries are fragments in `changelog.d/`: `python scripts/changelog.py collect`
adds them under `## [Unreleased]`, and `mason bump` turns that into the version.

## 1.1.0

- Each subnet also reports how many of its addresses are used, so Floorbit can say when it runs
  full at the current rate (Floorbit issue #1061).

## 1.0.0

- First release: a Kea DHCP server on the health wall (the server, its high-availability state, and
  how full each subnet is).
