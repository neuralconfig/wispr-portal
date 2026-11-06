# Linux lab host deploy (e.g. Ubuntu 24.04 VM on the guest VLAN)

Built for the DHA lab VM `dha-portal` (10.7.39.10/24 on VLAN 739, GW 10.7.39.1), which
reaches the SZ NBI at 192.168.37.6/.8:9443 through the MikroTik. Guests reach
`http://10.7.39.10:8080/` (walled garden: 10.7.39.10).

1. On a build machine: `deploy/linux/make-bundle.sh /tmp` gives `wispr-portal-bundle-<rev>.tar.gz`
   (source + this directory + the amd64 Docker image).
2. Copy the bundle, the NBI password file and the SZ 9443 leaf PEM to the VM, then:
   ```bash
   tar xzf wispr-portal-bundle-*.tar.gz && cd wispr-portal/deploy/linux
   sudo ./setup-host.sh ~/sz-nbi.password ~/sz9443-leaf.pem     # /etc/wispr-portal, user wispr (uid 10001)
   sudo nano /etc/wispr-portal/portal.env                        # mode, hosts, facility name
   ```
3. Run it one of two ways:
   - **Docker** (host networking, so the log shows the guests' real source IPs; read-only root, no capabilities):
     `sudo ./run-docker.sh debug ../../../wispr-portal-image-amd64.tar.gz`, later `sudo ./run-docker.sh customer`
   - **Native** (venv + gunicorn under a hardened systemd unit): `sudo ./install-native.sh ../..`.
     To switch modes, set `PORTAL_MODE` in `portal.env` and run `systemctl restart wispr-portal`.
4. Evidence: `/var/log/wispr-portal/events.jsonl` (JSON lines), the live SSE stream at
   `curl -N "http://10.7.39.10:8080/events?token=$(sudo cat /etc/wispr-portal/secrets/events_token)"`.

Run 1b (Authorize test): set `SZ_AUTH_METHOD=authorize` in `portal.env` and restart.
Run 2 (HTTPS): put the lab-CA cert/key in `secrets/`, set `PORT=8443`, `TLS_CERT_FILE`, `TLS_KEY_FILE` and restart.
