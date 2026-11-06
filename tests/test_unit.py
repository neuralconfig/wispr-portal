"""Unit tests: request building per backend, parameter validation, masking, allowlist, config."""

import pytest

from wispr.config import ConfigError, load_config
from wispr.masking import MASK, mask_body, mask_enc, mask_ip, mask_mac
from wispr.nbi import HostNotAllowed, NbiClient, NbiError, NbiExchange
from wispr.params import normalize_host, parse_redirect, safe_http_url

SZ_ENV = {"PORTAL_BACKEND": "smartzone", "SZ_NBI_HOSTS": "192.168.37.6, 192.168.37.8",
          "SZ_NBI_USERNAME": "nbiuser", "SZ_NBI_PASSWORD": "pw", "SECRET_KEY": "k" * 40,
          "SZ_GUEST_PASSWORD": "gpw"}
R1_ENV = {"PORTAL_BACKEND": "r1", "R1_NBI_HOSTS": "abc123.wispr.ruckus.cloud",
          "R1_INTEGRATION_KEY": "ikey", "SECRET_KEY": "k" * 40}

ENC_MAC = "ENCCDD319C6A476FA7127DF1FB80A63CD30ADC5E47C3DBE2157"
ENC_IP = "ENC12bc24c4777703327f2e0aabbf6b9f9e"
P = {"client_mac": ENC_MAC, "uip": ENC_IP, "proxy": "0"}


# ---- request building ---------------------------------------------------------------
def test_sz_login_body_matches_guide():
    c = NbiClient(load_config(SZ_ENV).nbi)
    body = c.build("login", P)
    assert body == {
        "Vendor": "ruckus", "RequestUserName": "nbiuser", "RequestPassword": "pw",
        "APIVersion": "1.0", "RequestCategory": "UserOnlineControl", "RequestType": "Login",
        "UE-IP": ENC_IP, "UE-MAC": ENC_MAC, "UE-Proxy": "0",
        "UE-Username": "guest", "UE-Password": "gpw",
    }


def test_sz_status_logout_disconnect_have_no_credentials_of_the_guest():
    c = NbiClient(load_config(SZ_ENV).nbi)
    for rt, wire in (("status", "Status"), ("logout", "Logout"), ("disconnect", "Disconnect")):
        body = c.build(rt, P)
        assert body["RequestType"] == wire
        assert "UE-Username" not in body and "UE-Password" not in body
        assert body["UE-MAC"] == ENC_MAC and body["UE-IP"] == ENC_IP


def test_sz_authorize_optin_and_decrypt():
    c = NbiClient(load_config({**SZ_ENV, "SZ_AUTH_METHOD": "authorize"}).nbi)
    assert c.cfg.auth_method == "authorize"
    body = c.build("authorize", P)
    assert body["RequestType"] == "Authorize" and "UE-Username" not in body
    dec = c.build("decrypt", P, data=ENC_MAC)
    assert dec["RequestCategory"] == "GetConfig" and dec["RequestType"] == "Decrypt"
    assert dec["Data"] == ENC_MAC and "UE-MAC" not in dec


def test_r1_defaults_authorize_with_integration_key():
    c = NbiClient(load_config(R1_ENV).nbi)
    assert (c.cfg.port, c.cfg.auth_method, c.cfg.vendor) == (443, "authorize", "Ruckus")
    body = c.build("authorize", P)
    assert body["RequestPassword"] == "ikey" and body["RequestUserName"] == "api"
    assert body["RequestType"] == "Authorize"


def test_clear_mac_passed_through_unchanged():
    c = NbiClient(load_config(SZ_ENV).nbi)
    body = c.build("login", {"client_mac": "aa-bb-cc-dd-ee-ff", "uip": "10.7.39.5"})
    assert body["UE-MAC"] == "aa-bb-cc-dd-ee-ff" and body["UE-IP"] == "10.7.39.5"


# ---- allowlist ----------------------------------------------------------------------
def test_allowlist_orders_nbiip_first():
    c = NbiClient(load_config(SZ_ENV).nbi)
    assert c.hosts_for("192.168.37.8") == ["192.168.37.8", "192.168.37.6"]
    assert c.hosts_for(None) == ["192.168.37.6", "192.168.37.8"]


@pytest.mark.parametrize("bad", ["10.0.0.1", "169.254.169.254", "evil.example.com",
                                 "https://192.168.37.6.evil.com/portalintf", "192.168.37.66",
                                 "user@192.168.37.6", "localhost"])
def test_allowlist_refuses_other_hosts(bad):
    c = NbiClient(load_config(SZ_ENV).nbi)
    with pytest.raises(HostNotAllowed):
        c.hosts_for(bad)


def test_r1_nbiip_url_form_is_normalised():
    c = NbiClient(load_config(R1_ENV).nbi)
    assert c.hosts_for("https://ABC123.wispr.ruckus.cloud:443/portalintf") == ["abc123.wispr.ruckus.cloud"]


def test_send_refuses_unlisted_host_even_if_called_directly():
    c = NbiClient(load_config(SZ_ENV).nbi)
    with pytest.raises(HostNotAllowed):
        c.send("status", {}, ["10.1.1.1"])


def test_failover_only_on_connect_errors(monkeypatch):
    c = NbiClient(load_config(SZ_ENV).nbi)
    calls = []

    def fake(rt, host, body, kind):
        calls.append(host)
        ex = NbiExchange(request_type="Login", host=host, url="", body=body, started=0)
        if host == "192.168.37.6":
            ex.error = NbiError(kind, "x", host)
        else:
            ex.reply = {"ResponseCode": 201}
        return ex

    monkeypatch.setattr(c, "_post_once", lambda rt, h, b: fake(rt, h, b, "connect"))
    assert c.send("login", {}, ["192.168.37.6", "192.168.37.8"]).code == 201
    assert calls == ["192.168.37.6", "192.168.37.8"]
    calls.clear()
    monkeypatch.setattr(c, "_post_once", lambda rt, h, b: fake(rt, h, b, "timeout"))
    assert c.send("login", {}, ["192.168.37.6", "192.168.37.8"]).error.kind == "timeout"
    assert calls == ["192.168.37.6"]


# ---- parameter validation -----------------------------------------------------------
def test_parse_full_sz_redirect():
    p = parse_redirect({"client_mac": ENC_MAC, "uip": ENC_IP, "nbiIP": "192.168.37.6",
                        "mac": "8c:0c:90:2b:8b:90", "ssid": "DHA-Guest", "url": "http://www.google.com/",
                        "startUrl": "https://dha.example/welcome", "reason": "Un-Auth-Captive",
                        "proxy": "0", "vlan": "739", "wlan": "1", "sip": "scg.ruckuswireless.com",
                        "dn": "scg.ruckuswireless.com", "wlanName": "DHA Guest", "zoneName": "%5BB%40453f2dba_14",
                        "sshTunnelStatus": "1", "foo": "bar"})
    assert p.ok and p.mac_encrypted
    assert p.values["vlan"] == "739" and p.unknown == {"foo": "bar"} and not p.rejected


@pytest.mark.parametrize("name,value", [
    ("client_mac", "not-a-mac"), ("client_mac", "ENCzz"), ("uip", "999.1.1.1"),
    ("url", "javascript:alert(1)"), ("startUrl", "//evil.example/"), ("url", "http://u:p@host/"),
    ("vlan", "5000"), ("wlan", "-1"), ("proxy", "2"), ("mac", "00:11:22:33:44"),
    ("ssid", "bad\x00ssid"), ("reason", "<script>"), ("nbiIP", "a b"),
])
def test_rejects_bad_values(name, value):
    p = parse_redirect({"client_mac": ENC_MAC, name: value} if name != "client_mac" else {name: value})
    assert name in p.rejected
    assert name not in p.values


def test_missing_client_mac_is_not_ok():
    p = parse_redirect({"uip": ENC_IP})
    assert not p.ok and p.missing == ["client_mac"]


def test_repeated_param_rejected():
    from werkzeug.datastructures import MultiDict
    p = parse_redirect(MultiDict([("client_mac", ENC_MAC), ("client_mac", "aa:bb:cc:dd:ee:ff")]))
    assert "client_mac" in p.rejected and not p.ok


@pytest.mark.parametrize("mac", ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabbccddeeff", "aabb.ccdd.eeff"])
def test_mac_formats(mac):
    assert parse_redirect({"client_mac": mac}).ok


def test_safe_http_url():
    assert safe_http_url("https://a.example/x?y=1") == "https://a.example/x?y=1"
    for bad in ("data:text/html,x", "ftp://a/", "https:///nohost", "http://a/\r\nX: y", "x" * 3000):
        assert safe_http_url(bad) is None


def test_normalize_host():
    assert normalize_host("192.168.37.6") == "192.168.37.6"
    assert normalize_host("192.168.37.6:9443") == "192.168.37.6"
    assert normalize_host("[fd00::6]") == "fd00::6"
    assert normalize_host("ftp://x/") is None


# ---- masking ------------------------------------------------------------------------
def test_mask_values():
    assert mask_mac("aa:bb:cc:dd:ee:ff") == "**:**:**:**:ee:ff"
    assert mask_mac("aabbccddeeff") == "********eeff"
    assert mask_ip("10.7.39.50") == "10.7.39.*"
    assert mask_ip("2001:db8:1:2::5") == "2001:0db8:*"
    assert mask_enc(ENC_MAC).startswith("ENCCDD3") and ENC_MAC not in mask_enc(ENC_MAC)
    assert mask_mac("garbage") == MASK


def test_mask_body_secrets_always():
    body = {"RequestPassword": "pw", "UE-Password": "gpw", "UE-MAC": "aa:bb:cc:dd:ee:ff",
            "UE-IP": "10.1.2.3", "RequestType": "Login"}
    open_ = mask_body(body, mask_ue=False)
    assert open_["RequestPassword"] == MASK and open_["UE-Password"] == MASK
    assert open_["UE-MAC"] == "aa:bb:cc:dd:ee:ff"
    closed = mask_body(body, mask_ue=True)
    assert closed["UE-MAC"] == "**:**:**:**:ee:ff" and closed["UE-IP"] == "10.1.2.*"
    assert body["RequestPassword"] == "pw"          # original untouched


# ---- config -------------------------------------------------------------------------
def test_config_requires_allowlist_and_password():
    with pytest.raises(ConfigError):
        load_config({**SZ_ENV, "SZ_NBI_HOSTS": ""})
    with pytest.raises(ConfigError):
        load_config({**SZ_ENV, "SZ_NBI_PASSWORD": ""})
    with pytest.raises(ConfigError):
        load_config({**SZ_ENV, "SZ_NBI_USERNAME": ""})
    with pytest.raises(ConfigError):
        load_config({**SZ_ENV, "PORTAL_MODE": "demo"})


def test_secret_file(tmp_path):
    f = tmp_path / "pw"
    f.write_text("from-file\n")
    cfg = load_config({**SZ_ENV, "SZ_NBI_PASSWORD_FILE": str(f)})
    assert cfg.nbi.request_password == "from-file"
    assert "from-file" not in repr(cfg)


def test_status_default_off_and_async_needs_status():
    assert load_config(SZ_ENV).nbi.status_supported is False
    with pytest.raises(ConfigError):
        load_config({**SZ_ENV, "SZ_AUTH_METHOD": "login_async"})
    assert load_config({**SZ_ENV, "SZ_AUTH_METHOD": "login_async", "SZ_STATUS_SUPPORTED": "1"}).nbi.auth_method == "login_async"


def test_bad_fingerprint_rejected():
    with pytest.raises(ConfigError):
        load_config({**SZ_ENV, "SZ_CERT_SHA256": "abcd"})
