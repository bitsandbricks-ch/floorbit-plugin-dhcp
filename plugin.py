"""The event's Kea DHCP server on Floorbit's health wall.

Kea's REST API takes one command per POST and answers ``[{"result", "text", "arguments"}]`` through
the Control Agent (one entry per service), or the bare object from the server's own HTTP socket.
Three commands, none of which needs a hook library:

- ``status-get``: the server answers, its uptime, and its high-availability state
- ``config-get``: the subnets (``subnet4``, also inside ``shared-networks``), for their names
- ``statistic-get-all``: ``subnet[<id>].total-addresses``, ``assigned-addresses`` and
  ``declined-addresses`` per subnet

Floorbit runs this on the local agent in the hall. Only counts leave: never a lease's address, MAC
or host name. IP to MAC for check-in comes from the server's syslog (Floorbit's docs/syslog.md).
"""
import re

from floorbit.plugins.base import Plugin as Base
from floorbit.plugins.base import PluginError

FULL = 95                # % at which a subnet turns red
STAT = re.compile(r'^subnet\[(\d+)\]\.(total|assigned|declined)-addresses$')
# Kea's result codes: 0 success, 1 error, 2 unsupported, 3 empty, 4 conflict.
OK, EMPTY = 0, 3


def _latest(samples):
    """A statistic's newest value: Kea sends [[value, "time"], ...], newest first."""
    try:
        value = samples[0][0]
    except (IndexError, KeyError, TypeError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class Plugin(Base):
    def _command(self, http, command):
        if not self.settings.get('url'):
            raise PluginError('Set the Kea API URL under Settings > Plugins first.')
        body = {'command': command}
        if self.settings.get('control_agent', True):
            body['service'] = ['dhcp4']
        resp = http.post('/', json=body, headers={'Accept': 'application/json'})
        if resp.status_code in (401, 403):
            raise PluginError('Kea refused the username or password.')
        if resp.status_code >= 400:
            raise PluginError(f'Kea answered {resp.status_code}. Is the URL its control API?')
        try:
            answer = resp.json()
        except ValueError as exc:
            raise PluginError("Kea's answer isn't JSON. Is the URL its control API?") from exc
        if isinstance(answer, list):
            answer = answer[0] if answer else {}
        if not isinstance(answer, dict):
            raise PluginError("Kea's answer isn't JSON. Is the URL its control API?")
        if answer.get('result') not in (OK, EMPTY):
            raise PluginError(f"Kea: {str(answer.get('text') or 'command failed')[:200]}")
        args = answer.get('arguments')
        return args if isinstance(args, dict) else {}

    def _http(self):
        user = self.settings.get('username')
        auth = (user, self.settings.get('password') or '') if user else None
        return self.ctx.http(self.settings.get('url'), timeout=10, auth=auth)

    def _subnets(self, config):
        dhcp4 = config.get('Dhcp4') if isinstance(config.get('Dhcp4'), dict) else {}
        subnets = list(dhcp4.get('subnet4') or [])
        for shared in dhcp4.get('shared-networks') or []:
            if isinstance(shared, dict):
                subnets += [{**s, '_shared': shared.get('name')} for s in shared.get('subnet4') or []
                            if isinstance(s, dict)]
        out = {}
        for s in subnets:
            if not isinstance(s, dict) or not isinstance(s.get('id'), int):
                continue
            context = s.get('user-context') if isinstance(s.get('user-context'), dict) else {}
            label = context.get('name') or context.get('comment') or s.get('_shared') or ''
            out[s['id']] = {'subnet': str(s.get('subnet') or ''), 'label': str(label)}
        return out

    def _read(self):
        http = self._http()
        status = self._command(http, 'status-get')
        subnets = self._subnets(self._command(http, 'config-get'))
        stats = {}
        for key, samples in self._command(http, 'statistic-get-all').items():
            found = STAT.match(key)
            value = _latest(samples) if found else None
            if value is not None:
                stats.setdefault(int(found.group(1)), {})[found.group(2)] = value
        rows = []
        for subnet_id, s in sorted(stats.items()):
            total = s.get('total') or 0
            if total <= 0:
                continue
            used = min(total, (s.get('assigned') or 0) + (s.get('declined') or 0))
            info = subnets.get(subnet_id, {})
            rows.append({'id': subnet_id, 'subnet': info.get('subnet') or f'subnet {subnet_id}',
                         'label': info.get('label') or '', 'total': total, 'used': used,
                         'declined': s.get('declined') or 0})
        return status, rows

    def _warn(self):
        try:
            return min(FULL, max(1, int(self.settings.get('pool_warn') or 80)))
        except (TypeError, ValueError):
            return 80

    def health_checks(self):
        status, rows = self._read()
        checks = [self._server_check(status)]
        warn = self._warn()
        for r in rows:
            pct = r['used'] * 100 / r['total']
            free = r['total'] - r['used']
            state = 'down' if pct >= FULL else 'warn' if pct >= warn else 'up'
            tone = {'down': 'err', 'warn': 'warn'}.get(state, '')
            name = f"DHCP {r['label']} {r['subnet']}" if r['label'] else f"DHCP {r['subnet']}"
            metrics = [{'label': 'Free', 'value': free, 'tone': tone},
                       {'label': 'In use', 'value': round(pct), 'unit': '%', 'tone': tone}]
            if r['declined']:
                metrics.append({'label': 'Declined', 'value': r['declined'], 'tone': 'warn'})
            checks.append({'id': f"subnet-{r['id']}", 'name': name, 'kind': 'dhcp', 'status': state,
                           'summary': f"{free} of {r['total']} addresses free", 'metrics': metrics})
        return checks

    def _server_check(self, status):
        uptime = status.get('uptime')
        metrics = []
        if isinstance(uptime, int) and uptime >= 0:
            metrics.append({'label': 'Up for', 'value': round(uptime / 3600, 1), 'unit': 'h'})
        state, summary = 'up', 'Answers'
        for ha in status.get('high-availability') or []:
            if not isinstance(ha, dict):
                continue
            local = (ha.get('ha-servers') or {}).get('local') or {}
            role, ha_state = str(local.get('role') or ''), str(local.get('state') or '')
            if ha_state:
                metrics.append({'label': 'HA', 'value': f'{role} {ha_state}'.strip()[:40]})
                # Serving alone (partner-down) or not at all is worth a look; normal states are fine.
                if ha_state in ('partner-down', 'terminated', 'waiting', 'syncing', 'in-maintenance',
                                'partner-in-maintenance'):
                    state, summary = 'warn', f'High availability: {ha_state}'
        return {'id': 'server', 'name': 'Kea DHCPv4', 'kind': 'dhcp', 'status': state, 'summary': summary,
                'metrics': metrics}

    def test(self):
        _status, rows = self._read()
        free = sum(r['total'] - r['used'] for r in rows)
        return f'Connected: {len(rows)} subnets, {free} addresses free.'
