"""Kea's control API against a fake Kea, never a real one."""
import pytest
import requests
from floorbit import health
from floorbit.plugins.base import PluginError

CONFIG = {"Dhcp4": {
    "subnet4": [{"id": 1, "subnet": "192.0.2.0/24", "user-context": {"name": "Players A"}},
                {"id": 2, "subnet": "198.51.100.0/24"}],
    "shared-networks": [{"name": "crew", "subnet4": [{"id": 3, "subnet": "203.0.113.0/26"}]}],
}}
STATS = {
    "subnet[1].total-addresses": [[200, "2026-11-19 10:00:00.000000"], [200, "2026-11-19 09:00:00.000000"]],
    "subnet[1].assigned-addresses": [[150, "2026-11-19 10:00:00.000000"], [3, "2026-11-19 09:00:00.000000"]],
    "subnet[1].declined-addresses": [[12, "2026-11-19 10:00:00.000000"]],
    "subnet[2].total-addresses": [[100, "2026-11-19 10:00:00.000000"]],
    "subnet[2].assigned-addresses": [[10, "2026-11-19 10:00:00.000000"]],
    "subnet[3].total-addresses": [[50, "2026-11-19 10:00:00.000000"]],
    "subnet[3].assigned-addresses": [[49, "2026-11-19 10:00:00.000000"]],
    "subnet[1].pool[0].total-addresses": [[200, "2026-11-19 10:00:00.000000"]],
    "pkt4-received": [[9000, "2026-11-19 10:00:00.000000"]],
}
STATUS = {"pid": 42, "uptime": 7200, "high-availability": [
    {"ha-mode": "hot-standby", "ha-servers": {"local": {"role": "primary", "state": "hot-standby"}}}]}


class Answer:
    def __init__(self, body=None, status=200):
        self.status_code = status
        self._body = body

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not JSON")
        return self._body


@pytest.fixture
def kea(monkeypatch):
    seen = []
    state = {"status": STATUS}

    def fake(self, method, url, **kw):
        body = kw.get("json") or {}
        seen.append(body)
        if self.auth not in (None, ("floorbit", "example-password")):
            return Answer({}, 401)
        args = {"status-get": state["status"], "config-get": CONFIG, "statistic-get-all": STATS}.get(body["command"])
        answer = {"result": 0, "arguments": args} if args is not None else {"result": 2, "text": "not supported"}
        return Answer([answer] if "service" in body else answer)

    monkeypatch.setattr(requests.Session, "request", fake)
    return seen, state


class Spec:
    id, name = "dhcp", "DHCP (Kea)"


def plugin(make, **extra):
    return make(url="http://192.0.2.53:8000", **extra)


def test_subnets_on_the_health_wall(make, kea):
    seen, _ = kea
    checks = {c["id"]: c for c in health.clean(Spec, plugin(make).health_checks())}
    players = checks["dhcp:subnet-1"]          # 150 + 12 declined of 200: 81%
    assert players["name"] == "DHCP Players A 192.0.2.0/24" and players["kind"] == "dhcp"
    assert players["status"] == "warn" and players["summary"] == "38 of 200 addresses free"
    assert {m["label"]: m["value"] for m in players["metrics"]} == {"Free": 38, "In use": 81, "Declined": 12}
    assert checks["dhcp:subnet-2"]["status"] == "up" and checks["dhcp:subnet-2"]["name"] == "DHCP 198.51.100.0/24"
    assert checks["dhcp:subnet-3"]["status"] == "down" and checks["dhcp:subnet-3"]["name"] == "DHCP crew 203.0.113.0/26"
    server = checks["dhcp:server"]
    assert server["status"] == "up" and {m["label"]: m["value"] for m in server["metrics"]} == {
        "Up for": 2.0, "HA": "primary hot-standby"}
    assert {tuple(b["service"]) for b in seen} == {("dhcp4",)}


def test_the_server_itself_and_a_partner_down(make, kea):
    seen, state = kea
    state["status"] = {"uptime": 60, "high-availability": [
        {"ha-servers": {"local": {"role": "primary", "state": "partner-down"}}}]}
    checks = {c["id"]: c for c in plugin(make, control_agent=False).health_checks()}
    assert checks["server"]["status"] == "warn" and checks["server"]["summary"] == "High availability: partner-down"
    assert not [b for b in seen if "service" in b]
    assert plugin(make, pool_warn=82).health_checks()[1]["status"] == "up"


def test_test_button_and_basic_auth(make, kea):
    assert plugin(make, username="floorbit", password="example-password").test() == \
        "Connected: 3 subnets, 129 addresses free."
    with pytest.raises(PluginError, match="refused"):
        plugin(make, username="floorbit", password="wrong").test()


def test_errors(make, kea, monkeypatch):
    with pytest.raises(PluginError, match="Kea API URL"):
        make().health_checks()
    monkeypatch.setattr(requests.Session, "request",
                        lambda self, m, u, **kw: Answer([{"result": 1, "text": "server is not running"}]))
    with pytest.raises(PluginError, match="Kea: server is not running"):
        plugin(make).test()
    monkeypatch.setattr(requests.Session, "request", lambda self, m, u, **kw: Answer("<html>"))
    with pytest.raises(PluginError, match="isn't JSON"):
        plugin(make).test()
