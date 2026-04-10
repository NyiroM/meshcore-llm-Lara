import pytest

import auto_reply_priv as arp


class DummySerial:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def disable_threads(monkeypatch):
    """Prevent AutoReplyBot from spawning cleanup threads during tests."""
    monkeypatch.setattr(arp.AutoReplyBot, "_start_dedup_cleanup_thread", lambda self: None)
    yield


def test_check_port_available_success(monkeypatch):
    monkeypatch.setattr(arp.serial, "Serial", lambda port, timeout=1: DummySerial())
    assert arp.check_port_available("COM1") is True


def test_check_port_available_failure(monkeypatch):
    def fake_serial(port, timeout=1):
        raise arp.serial.SerialException("port unavailable")

    monkeypatch.setattr(arp.serial, "Serial", fake_serial)
    assert arp.check_port_available("COM1") is False


def test_find_available_ports_with_preferred(monkeypatch):
    import sys
    import types

    class Port:
        def __init__(self, device):
            self.device = device

    list_ports_module = types.ModuleType("serial.tools.list_ports")
    list_ports_module.comports = lambda: [Port("COM3"), Port("COM6")]
    serial_tools_module = types.ModuleType("serial.tools")
    serial_tools_module.list_ports = list_ports_module

    monkeypatch.setitem(sys.modules, "serial.tools", serial_tools_module)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", list_ports_module)

    ports = arp.find_available_ports(preferred_port="COM6")

    assert ports[0] == "COM6"
    assert "COM3" in ports


def test_openwebui_health_url_default():
    bot = arp.AutoReplyBot({"ai": {}, "radio": {"port": "COM6"}, "bot_behavior": {}, "system": {}})
    assert bot._openwebui_health_url() == "http://127.0.0.1:8080/api/health"


def test_openwebui_health_url_from_api_url():
    bot = arp.AutoReplyBot(
        {
            "ai": {"api_url": "http://localhost:8080/api/v1"},
            "radio": {"port": "COM6"},
            "bot_behavior": {},
            "system": {},
        }
    )
    assert bot._openwebui_health_url() == "http://localhost:8080/api/health"


def test_is_openwebui_up_false_on_request_error(monkeypatch):
    bot = arp.AutoReplyBot({"ai": {}, "radio": {"port": "COM6"}, "bot_behavior": {}, "system": {}})

    class Response:
        status_code = 503

    monkeypatch.setattr(arp.requests, "get", lambda url, timeout: Response())
    assert bot._is_openwebui_up() is False


def test_wait_for_openwebui_returns_false_when_unavailable(monkeypatch):
    bot = arp.AutoReplyBot({"ai": {}, "radio": {"port": "COM6"}, "bot_behavior": {}, "system": {}})
    monkeypatch.setattr(bot, "_is_openwebui_up", lambda: False)
    assert bot._wait_for_openwebui(timeout=0) is False


def test_start_openwebui_no_uvx(monkeypatch):
    cfg = {"ai": {"openwebui_autostart": True}, "radio": {"port": "COM6"}, "bot_behavior": {}, "system": {}}
    bot = arp.AutoReplyBot(cfg)
    monkeypatch.setattr(bot, "_is_openwebui_up", lambda: False)
    monkeypatch.setattr(arp.shutil, "which", lambda name: None)

    bot._start_openwebui()
    assert bot._openwebui_proc is None
