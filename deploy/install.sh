#!/usr/bin/env bash
# Run as root: ./deploy/install.sh /path/to/dedicated-public-key.pub
set -euo pipefail
test "$(id -u)" -eq 0
test "$#" -eq 1
public_key="$(cat "$1")"
[[ "$public_key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ .*)?$ ]]
test "$(printf '%s' "$public_key" | wc -l)" -eq 0
ssh-keygen -l -f "$1" >/dev/null
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
test -L /opt/symphony/current
if ! id symphony-deploy >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/symphony-deploy --shell /bin/sh symphony-deploy
fi
install -d -o root -g root -m 755 /var/lib/symphony-deploy
install -d -o root -g root -m 755 /var/lib/symphony-deploy/.ssh
install -o root -g root -m 755 "$script_dir/deploy.py" /usr/local/sbin/symphony-deploy
cat > /usr/local/sbin/symphony-deploy-ssh <<'EOF'
#!/bin/sh
exec /usr/bin/sudo -n /usr/local/sbin/symphony-deploy "${SSH_ORIGINAL_COMMAND:-}"
EOF
chown root:root /usr/local/sbin/symphony-deploy-ssh
chmod 755 /usr/local/sbin/symphony-deploy-ssh
printf 'restrict,command="/usr/local/sbin/symphony-deploy-ssh" %s\n' "$public_key" > /var/lib/symphony-deploy/.ssh/authorized_keys
chown root:root /var/lib/symphony-deploy/.ssh/authorized_keys
chmod 644 /var/lib/symphony-deploy/.ssh/authorized_keys
sudoers="$(mktemp)"
trap 'rm -f "$sudoers"' EXIT
printf '%s\n' 'symphony-deploy ALL=(root) NOPASSWD: /usr/local/sbin/symphony-deploy' > "$sudoers"
visudo -cf "$sudoers"
install -o root -g root -m 440 "$sudoers" /etc/sudoers.d/symphony-deploy
echo 'Installed restricted Symphony deployment endpoint. Services were not restarted.'
