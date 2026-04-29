#!/bin/bash
set -e

echo "[*] Diagnostic: Current User is $(whoami) (id: $(id -u))"
echo "[*] Initializing SSH environment in $(hostname)..."

# CRITICAL: Enforce strict file permissions for the private key
# sshd client will fail if the private key is too permissive.
echo "[*] Enforcing strict file permissions..."
chown -R mcpuser:mcpuser /home/mcpuser/.ssh
chmod 700 /home/mcpuser/.ssh
chmod 600 /home/mcpuser/.ssh/id_rsa

echo "[*] Diagnostic: SSH directory state:"
ls -ld /home/mcpuser/.ssh
ls -la /home/mcpuser/.ssh

echo "[*] Diagnostic: Global authorized_keys state:"
ls -l /etc/ssh/authorized_keys_mcpuser

# Ensure runtime directory for sshd
mkdir -p /var/run/sshd

# Execute the requested command
echo "[*] Starting: $@"
exec "$@"
