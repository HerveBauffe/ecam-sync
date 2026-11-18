#!/usr/bin/env bash
# Installe (ou met à jour) ecam-sync sur Debian. À lancer depuis le dossier du projet : sudo ./deploy/install.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Lancer avec sudo." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 est requis." >&2; exit 1; }
python3 -c 'import venv, ensurepip' 2>/dev/null || { echo "Installer d'abord : apt install python3-venv" >&2; exit 1; }

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/ecam-sync
CONF=/etc/ecam-sync
SVC_USER=ecam-sync

# Utilisateur système dédié, sans shell ni mot de passe
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home-dir /var/lib/ecam-sync --shell /usr/sbin/nologin "$SVC_USER"

# Dossier d'état (verrou) : nécessaire dès les tests manuels « sudo -u ecam-sync ... sync »,
# avant que systemd (StateDirectory=) ne l'ait créé
install -d -o "$SVC_USER" -g "$SVC_USER" -m 700 /var/lib/ecam-sync

# Dossier de configuration (secrets) : lisible par root et par le service uniquement
install -d -o root -g "$SVC_USER" -m 750 "$CONF"
[ -f "$CONF/ecam-sync.env" ] || install -o root -g "$SVC_USER" -m 640 "$SRC/deploy/ecam-sync.env.example" "$CONF/ecam-sync.env"

# Application dans un environnement virtuel isolé
install -d -m 755 "$APP"
[ -d "$APP/venv" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --quiet "$SRC"
"$APP/venv/bin/pip" install --quiet --force-reinstall --no-deps "$SRC"   # applique aussi les mises à jour du code

install -m 644 "$SRC"/deploy/ecam-sync.service "$SRC"/deploy/ecam-sync.timer "$SRC"/deploy/ecam-sync-listener.service /etc/systemd/system/
systemctl daemon-reload

cat <<MSG

Installation terminée. Étapes suivantes :
  1. Éditer  $CONF/ecam-sync.env
  2. Copier la clé Google dans $CONF/google-service-account.json
       sudo chown root:$SVC_USER $CONF/google-service-account.json && sudo chmod 640 $CONF/google-service-account.json
  3. Tester :  sudo -u $SVC_USER $APP/venv/bin/ecam-sync check
  4. Activer : sudo systemctl enable --now ecam-sync-listener.service ecam-sync.timer
MSG
