# DHCP (Kea) for Floorbit

[![Test and release](https://github.com/bitsandbricks-ch/floorbit-plugin-dhcp/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/bitsandbricks-ch/floorbit-plugin-dhcp/actions/workflows/release.yml?query=branch%3Amain)

The `dhcp` plugin for [Floorbit](https://github.com/bitsandbricks-ch/floorbit): the event's Kea DHCP server on the health wall, with how many addresses each subnet has left.
Install it under Settings > Plugins > Marketplace; how to set it up is in Floorbit's
[docs/plugins.md](https://github.com/bitsandbricks-ch/floorbit/blob/master/docs/plugins.md).

## What it shows

It asks [Kea](https://www.isc.org/kea/)'s control API (the Control Agent, or from Kea 2.7 the
DHCPv4 server's own HTTP socket) three commands that need no hook library: `status-get`,
`config-get` and `statistic-get-all`.

- **The server** (kind dhcp): it answers, how long it has been up, and its high-availability state.
  Amber while it serves alone (`partner-down`) or is syncing, waiting or in maintenance.
- **Each subnet** (kind dhcp): free addresses (declined ones count as used), amber from the warning
  setting (80%), red from 95%. Named by the subnet's `user-context` `name` or `comment`, its shared
  network, and its prefix.

Only counts leave the hall: never a lease's address, MAC or host name.

Other DHCP servers:

- **IP to MAC** for check-in and the seat walk comes from the DHCP server's syslog, which Floorbit
  reads for ISC dhcpd, Kea, dnsmasq and MikroTik already
  ([docs/syslog.md](https://github.com/bitsandbricks-ch/floorbit/blob/master/docs/syslog.md)).
- **pfSense** pools are on the health wall through the
  [pfSense plugin](https://github.com/bitsandbricks-ch/floorbit-plugin-pfsense).
- ISC dhcpd and dnsmasq have no API to ask for pool use.

<!-- TODO(Mike): checked against the Kea 2.6 API reference, not yet against a real server. Which
DHCP server does Lock & Load run? -->

## What is where

| File | What |
| --- | --- |
| `plugin.yaml` | The manifest: settings and what it may touch. |
| `plugin.py` | The plugin. Floorbit runs it on the local agent in the hall, which reaches the DHCP server on the event network. |
| `tests/` | Tests against a fake Kea, with Floorbit at the commit in `FLOORBIT_REF`. No network. |

## Testing

```
git clone https://github.com/bitsandbricks-ch/floorbit ../floorbit
git -C ../floorbit checkout "$(cat FLOORBIT_REF)"
pip install -r ../floorbit/requirements.txt pytest ruff
ruff check --config ../floorbit/pyproject.toml --config 'lint.isort.known-third-party=["floorbit"]' .
PYTHONPATH=../floorbit python -m pytest -q tests
```

## Releasing

Put the new version into `plugin.yaml`, add a `## <version>` section to `CHANGELOG.md`, merge, then
push the tag (or `mason release tag floorbit-plugin-dhcp`):

```
git tag v1.0.0 && git push origin v1.0.0
```

The [workflow](.github/workflows/release.yml) tests it, signs `dhcp-<version>.tar.gz` with the
Floorbit plugin key (environment `plugin-signing`, secret `FLOORBIT_PLUGIN_SIGNING_KEY`) and
attaches it to the GitHub release. The Marketplace picks it up within the hour. A version is
withdrawn in [floorbit-plugins](https://github.com/bitsandbricks-ch/floorbit-plugins)' `plugins.yaml`,
never by deleting the release.
