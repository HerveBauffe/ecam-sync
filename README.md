# ecam-sync — calendrier ECAM → Google Calendar, depuis Home Assistant

Un appui sur un bouton dans Home Assistant (ou le timer hebdomadaire) déclenche, sur le Debian :
téléchargement de l'ICS → transformation des événements → synchronisation d'un calendrier Google dédié.

```
 Home Assistant                                      Serveur Debian (ex. petit SBC)
 ┌───────────────────────┐   MQTT: ecam_sync/command  ┌─────────────────────────────┐
 │ input_button  ────────┼──────────(sync)──────────▶ │ ecam-sync-listener (démon)  │
 │ capteur + notification│◀────── ecam_sync/status ───┤   └─ ecam-sync sync         │
 └───────────────────────┘     (running / ok / error) │ ecam-sync.timer (dimanche)  │
                                                      │   └─ ecam-sync sync         │
                                                      └──────────────┬──────────────┘
                                          ICS public ◀───────────────┤ HTTPS
                                          Google Calendar API ◀──────┘ compte de service
```

## Ce que fait la synchronisation

1. Télécharge l'ICS (état complet à chaque fois).
2. Déplie les événements récurrents (RRULE) en occurrences individuelles.
3. **Ne garde que les événements d'aujourd'hui et du futur** (les passés ne sont jamais ajoutés).
4. Transforme chaque événement :
   - la 1re ligne de `DESCRIPTION` devient le titre ; `Act:` est retiré ; l'ancien titre est abandonné ;
   - un titre trop vague (« théorie », « exercices »…) est préfixé du nom du cours, retrouvé grâce au code de
     l'ancien titre (`®-TH2C-T1-…`) dans les examens du même fichier (`TH2C:Thermo`) → « Thermo – théorie »
     (à défaut, le code : « TH2C – théorie ») ;
   - les lignes suivantes (`Groupe:`, `Rem:`, `Ens:`) restent dans la description ;
   - le `\ `parasite des examens (`[ECRIT]\ `) est nettoyé, les doubles espaces sont réduits ;
   - le lieu est conservé s'il existe ; aucun rappel n'est ajouté.
5. Compare avec le calendrier Google et **ajoute / modifie / supprime** le nécessaire (synchro complète).

Comment un événement est reconnu d'un téléchargement à l'autre : par **début + fin + titre** (pas par l'UID de la
source, dont la stabilité n'est pas garantie). Donc : lieu ou description modifiés → mise à jour sur place ;
horaire ou titre modifiés → l'ancien événement est supprimé et le nouveau créé.
Chaque événement créé porte un marqueur invisible : **le programme ne touche jamais aux événements
que vous ajoutez à la main** dans ce calendrier, et ne supprime pas les événements déjà passés.

Garde-fous : refuse de synchroniser si la source est vide alors que Google contient des événements, et refuse
de supprimer plus de 50 % (et plus de 10) des événements d'un coup. Dans ce cas, l'erreur remonte dans Home
Assistant ; après vérification, forcer avec `ecam-sync sync --force`.

## Mise en place

### 1. Google : compte de service (une seule fois, ~10 min)

Un compte de service est un « robot » Google avec sa propre clé : pas de fenêtre de connexion, pas d'expiration
(contrairement à une autorisation OAuth classique, qui expire au bout de 7 jours tant que l'application n'est pas
publiée — inadapté à un traitement hebdomadaire sur un serveur sans écran).

1. <https://console.cloud.google.com> → **Nouveau projet** (nom : `ecam-sync`).
2. **API et services → Bibliothèque** → « Google Calendar API » → **Activer**.
3. **IAM et administration → Comptes de service → Créer un compte de service** (nom : `ecam-sync`, aucun rôle à donner).
4. Ouvrir ce compte → onglet **Clés → Ajouter une clé → Créer une clé → JSON**. Un fichier se télécharge : c'est un secret.
5. Noter l'**adresse e-mail du compte de service** (`ecam-sync@<projet>.iam.gserviceaccount.com`).
6. Dans <https://calendar.google.com> : le calendrier dédié → **Paramètres et partage** → « Partager avec des personnes ou des groupes spécifiques » → ajouter l'adresse du compte de service avec l'autorisation **« Apporter des modifications aux événements »**.
7. Même page → **Intégrer l'agenda** → copier l'**ID de l'agenda** (`xxxx@group.calendar.google.com`).

> Utilisez un calendrier **vide** : des événements déjà importés à la main n'ont pas le marqueur du programme,
> ils ne seraient ni mis à jour ni supprimés et feraient doublon.

### 2. Broker MQTT

Créer un utilisateur dédié pour le Debian (avec le module Mosquitto : un utilisateur Home Assistant `ecam_sync`,
réglage « autorisé à se connecter seulement en local »). Facultatif : une ACL qui limite cet utilisateur au topic `ecam_sync/#`.

### 3. Debian

```bash
sudo apt install python3-venv
# copier ce dossier sur le Debian (scp -r ecam-sync/ user@debian:), puis :
cd ecam-sync && sudo ./deploy/install.sh

sudo nano /etc/ecam-sync/ecam-sync.env            # ICS_URL, GOOGLE_CALENDAR_ID, MQTT_*
sudo cp ~/clé-google.json /etc/ecam-sync/google-service-account.json
sudo chown root:ecam-sync /etc/ecam-sync/google-service-account.json
sudo chmod 640 /etc/ecam-sync/google-service-account.json

sudo -u ecam-sync /opt/ecam-sync/venv/bin/ecam-sync check          # ICS, Google, MQTT : tout doit être « OK »
sudo -u ecam-sync /opt/ecam-sync/venv/bin/ecam-sync sync --dry-run # montre ce qui serait ajouté, sans rien faire
sudo -u ecam-sync /opt/ecam-sync/venv/bin/ecam-sync sync           # première vraie synchro

sudo systemctl enable --now ecam-sync-listener.service ecam-sync.timer
```

### 4. Home Assistant

Copier `deploy/homeassistant/ecam_sync.yaml` dans `/config/packages/` (instructions en tête du fichier), redémarrer.
Ajouter ensuite sur un tableau de bord une carte « Entités » avec `input_button.ecam_sync` et `sensor.sync_calendrier_ecam`.
Si l'entité du capteur a un autre identifiant que `sensor.sync_calendrier_ecam`, l'ajuster dans l'automatisation.

## Exploitation

| Besoin                    | Commande                                                                                             |
|---------------------------|------------------------------------------------------------------------------------------------------|
| Voir les logs             | `journalctl -u ecam-sync-listener -u ecam-sync -e`                                                   |
| Prochain passage du timer | `systemctl list-timers ecam-sync.timer`                                                              |
| Changer le jour / l'heure | éditer `OnCalendar=` dans `/etc/systemd/system/ecam-sync.timer`, puis `sudo systemctl daemon-reload` |
| Synchroniser à la main    | `sudo -u ecam-sync /opt/ecam-sync/venv/bin/ecam-sync sync`                                           |
| Mettre à jour le code     | recopier le dossier puis `sudo ./deploy/install.sh && sudo systemctl restart ecam-sync-listener`     |

Si le bouton et le timer se déclenchent en même temps, la 2e demande est ignorée (verrou).

## Sécurité

- Secrets uniquement dans `/etc/ecam-sync/` (`root:ecam-sync`, mode 640) ; jamais dans le code ni dans les logs (l'URL ICS contient un jeton : elle est masquée dans les erreurs).
- Services sous un utilisateur système dédié, sans shell, avec durcissement systemd (système de fichiers en lecture seule, aucune capacité, réseau limité à IPv4/IPv6 et aux sockets locaux nécessaires au DNS).
- Le compte de service n'a accès qu'à **ce** calendrier, avec la portée minimale `calendar.events`.
- MQTT : aucun port ouvert côté Debian (connexion sortante vers le broker). Les commandes « retenues » sont ignorées.
- L'URL ICS est **personnelle** (chacun a la sienne) : ne la mettez ni dans le code, ni dans un message. Si elle a fuité, régénérez le jeton si ECAM le permet.
- Pour partager ce projet, copiez uniquement le dossier source : jamais `/etc/ecam-sync/`, un fichier `.env` ni la clé JSON (exclus par `.gitignore`).

## Structure du code (pour les évolutions)

| Fichier                      | Rôle                                                                                                                                  |
|------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `src/ecam_sync/transform.py` | **règles de titre/description** (fonctions pures ; `LABEL_PREFIX` pour retirer d'autres préfixes, par ex. les codes de cours `PM1C:` ; `GENERIC_TITLES` pour les titres à préciser) |
| `src/ecam_sync/source.py`    | téléchargement, lecture ICS, récurrences, filtre « à venir »                                                                          |
| `src/ecam_sync/sync.py`      | identité des événements, plan ajout/modif/suppression, garde-fous                                                                     |
| `src/ecam_sync/gcal.py`      | appels à l'API Google (seul fichier qui la connaît)                                                                                   |
| `src/ecam_sync/mqtt.py`      | écoute des commandes, publication de l'état                                                                                           |
| `src/ecam_sync/runner.py`    | orchestration d'une exécution : verrou, erreurs, état publié                                                                          |
| `src/ecam_sync/cli.py`       | commandes `sync`, `listen`, `check`                                                                                                   |
| `tests/`                     | 46 tests (`pip install -e '.[dev]' && pytest`)                                                                                        |

## Limites connues / pistes

- Les titres d'examens restent `PM1C:Pont Math[ECRIT]` (seul `Act:` est retiré). Pour retirer aussi les codes de cours, voir `LABEL_PREFIX`.
  Attention : changer cette règle change tous les titres, donc l'identité de tous les événements ; la synchro suivante
  voudra tout supprimer et recréer et sera bloquée par le garde-fou → vérifier avec `--dry-run`, puis `--force`.
- Les événements « journée entière » et `STATUS:CANCELLED` sont ignorés.
- Un appui sur le bouton pendant une synchro lancée par le bouton déclenche une nouvelle synchro juste après.
- Si les UID de la source se révèlent stables, on pourrait les utiliser pour suivre un événement dont l'horaire change.