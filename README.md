# Kitunga AI Pi Client

Client IoT du système de panier intelligent Kitunga AI, prévu pour Raspberry Pi 5.

Client IoT Python pour Raspberry Pi 5. Ce dossier gere uniquement le cote Raspberry :

- camera Raspberry Pi / OpenCV / libcamera ;
- YOLO local existant avec détection simultanée de plusieurs objets ;
- ajout produit uniquement, sans retrait automatique ;
- suivi visuel par boîte YOLO, stabilisation et anti-doublon par objet ;
- PIR, buzzer, matrice MAX7219, RFID ;
- etat local minimal de la facture active, sans identifiant de panier ;
- communication HTTP avec backend Django ou mock local ;
- preview Flask technique ;
- logs et erreurs hardware/reseau non bloquantes.

Le backend reste la source de verite pour clients, panier, prix, wallet, paiement, ventes et stocks.

## Détection de plusieurs objets

Lorsqu'une présence est détectée, YOLO analyse toutes les boîtes visibles dans
l'image. Chaque objet est suivi par sa position (recouvrement IoU), puis ajouté
seulement après `DETECTION_STABILITY_FRAMES` images suffisamment fiables. Deux
objets avec le même label sont donc comptés séparément, tandis qu'un objet qui
reste dans le panier n'est envoyé qu'une fois. Une courte baisse de confiance
ne le réarme pas ; il doit réellement disparaître pendant
`DETECTION_DISAPPEAR_FRAMES` images avant de pouvoir être ajouté de nouveau.

Le client continue d'envoyer un événement HTTP par objet confirmé : cela donne
à chaque objet sa propre clé d'idempotence et évite qu'une reprise réseau ne
double le panier.

La caméra reste ouverte pour éviter son temps de démarrage, mais YOLO ne traite
des images que lorsqu'une présence PIR est détectée et pendant les 3 secondes
qui suivent la dernière présence. Cette période se règle avec
`PRESENCE_GRACE_SECONDS`.

## Installation

```bash
cd /home/admin/mon_oled/kitunga_pi_client
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Sur Raspberry Pi OS, si `opencv-python` ou `spidev` pose probleme via pip, installer les paquets systeme equivalents avec `apt`, puis relancer l'installation Python.

## Lancement mock complet

Demo sans backend Django, sans camera reelle et sans hardware :

```bash
HARDWARE_ENABLED=false MATRIX_ENABLED=false PREVIEW_ENABLED=false SIMULATED_RFID_INTERVAL_SECONDS=3 \
python main.py --api-mode mock --rfid-mode simulation --simulate-detection ESP32 --once --interval 0.1 --stability-frames 1
```

Scenario simule :

```text
WAITING_CUSTOMER
RFID 04A732B19C -> Monsieur X
ACTIVE
YOLO detecte -> ajout confirme par mock
RFID identique presente une seconde fois -> PAID
reset -> WAITING_CUSTOMER
```

Pour simuler plusieurs objets visibles dans la même image :

```bash
python main.py --api-mode mock --rfid-mode simulation --simulate-detection ESP32,Arduino,ESP32
```

Variables utiles du mock :

```bash
API_MODE=mock
RFID_MODE=simulation
SIMULATED_RFID_UID=04A732B19C
MOCK_CUSTOMER_NAME="Monsieur X"
```

Le mock simule seulement les reponses necessaires au client IoT. Il ne gere pas wallet, prix, stock, ventes ou base commerciale.

## Lancement Raspberry avec YOLO

```bash
API_MODE=mock RFID_MODE=simulation python main.py --camera-backend auto
```

Avec image fixe :

```bash
python main.py --api-mode mock --rfid-mode simulation --test-image captures/live_KITUNGA-PI-001.jpg
```

La vue web Flask est activee par defaut et ecoute tout le reseau local :

```text
http://IP_RASPBERRY:5000
http://IP_RASPBERRY:5000/status.json
```

Pour la consulter depuis un telephone ou un PC connecte au meme Wi-Fi, lancez
le client normalement (sans `--no-preview`), puis recuperez l'adresse de la
Raspberry avec `hostname -I`. Ouvrez par exemple `http://192.168.1.42:5000`.
La page affiche le flux camera, les cadres YOLO, les detections visibles et le
dernier objet transmis au backend. Si le port est inaccessible, verifiez que
les appareils ne sont pas sur un Wi-Fi invite/isole et, si UFW est active sur
la Pi, autorisez le port TCP 5000.

## Passage au backend reel

Le backend Django expose le contrat RFID sous `/api/iot/`. Enregistrez d'abord
l'équipement avec `python manage.py provision_device KITUNGA-PI-001 101`, puis
créez le fichier `.env` local de la Pi :

```bash
cd /home/admin/mon_oled/kitunga_pi_client
cp .env.example .env
nano .env
chmod 600 .env
python main.py --camera-backend auto
```

Dans `.env`, conservez le nom réseau du PC qui exécute Django (pas l'adresse
de la Pi) et le même `DEVICE_ID` que dans Django. Cela évite de
modifier la configuration de la Raspberry après un changement d'adresse IP du
PC :

```ini
API_MODE=real
API_BASE_URL=http://stevemavuela.local:8000
DEVICE_ID=KITUNGA-PI-001
```

Il n'existe ni `DEVICE_SECRET`, ni QR code, ni appairage. Les variables
exportees dans le terminal restent prioritaires sur `.env`, ce qui permet les
tests ponctuels.

Les détections et paiements utilisent une clé d'idempotence ; en cas de timeout,
le client réutilise la même clé pour la même opération en attente. Si les
endpoints ou JSON changent, adapter uniquement `RealApiClient` dans
`api_client.py`.

## Première carte RFID : validation par l'administrateur

Une carte inconnue ne peut ni démarrer un panier ni payer. La Pi envoie une
demande sécurisée à Django et affiche `PEND` sur la matrice. L'administrateur
connecté reçoit une notification, ouvre **Cartes RFID**, puis associe la carte à
un client existant ou crée le client. Un portefeuille à zéro est créé avec le
nouveau client.

Après l'acceptation, le client retire puis présente à nouveau la carte : ce
second scan démarre l'achat. Cela évite de commencer un panier si le client est
parti pendant que l'administrateur validait la demande.

Le passage suivant de la même carte, pendant l’achat, crée une demande de
paiement. La Pi affiche l’attente et ne considère la facture payée qu’après la
confirmation dans le popup backend. Si le portefeuille est insuffisant, aucun
débit ni facture n’est créé ; l’administrateur peut recharger la carte en francs
dans **Cartes RFID**.

Erreurs réseau et configuration affichées par le client :

- `DEVICE_UNAUTHORIZED (401)` : vérifier `DEVICE_ID` et que
  l'appareil est activé côté Django ;
- `API_ROUTE_NOT_FOUND (404)` : redémarrer le backend avec
  `start_lan_server.ps1` et vérifier que `API_BASE_URL` vise
  `http://stevemavuela.local:8000`.

Le guide complet côté serveur est dans
[`backend/docs/RFID_ENROLLMENT.md`](../backend/docs/RFID_ENROLLMENT.md).

## Configuration principale

Variables sans prefixe recommandees, avec compatibilite `KITUNGA_*` pour les anciennes configs :

```bash
API_MODE=mock
API_BASE_URL=http://stevemavuela.local:8000
DEVICE_ID=KITUNGA-PI-001
REQUEST_TIMEOUT=5
RFID_MODE=simulation
SIMULATED_RFID_UID=04A732B19C
CONFIDENCE_THRESHOLD=0.70
DETECTION_STABILITY_FRAMES=2
COOLDOWN_SECONDS=4
DETECTION_DISAPPEAR_FRAMES=3
PRESENCE_GRACE_SECONDS=3
TRACK_IOU_THRESHOLD=0.30
SCAN_INTERVAL_SECONDS=0.5
BASKET_STATUS_POLL_SECONDS=1
HARDWARE_ENABLED=true
PIR_PIN=17
BUZZER_PIN=18
MATRIX_ENABLED=true
MATRIX_DEVICE=/dev/spidev0.0
MATRIX_CASCADED=1
MATRIX_INTENSITY=2
PREVIEW_ENABLED=true
PREVIEW_HOST=0.0.0.0
PREVIEW_PORT=5000
LOG_FILE=/home/admin/mon_oled/kitunga_pi_client/logs/kitunga_pi_client.log
```

## RFID RC522

Le mode simulation reste disponible :

```bash
RFID_MODE=simulation API_MODE=mock python main.py --camera-backend auto
python diagnostics.py rfid --mode simulation
```

Le mode hardware utilise un lecteur MFRC522 / RC522 via `pi-rc522`, sur SPI0 CE1 :

```bash
RFID_MODE=hardware API_MODE=mock python main.py --camera-backend auto
python diagnostics.py rfid --mode hardware
```

Brochage RC522 -> Raspberry Pi 5 :

| RC522 | Raspberry Pi 5 |
| --- | --- |
| SCK | GPIO11 / pin 23 |
| MOSI | GPIO10 / pin 19 |
| MISO | GPIO9 / pin 21 |
| SDA/SS | GPIO7 / CE1 / pin 26 |
| RST | GPIO25 / pin 22 |
| 3.3V | 3.3V |
| GND | GND |

Configuration RFID hardware :

```bash
RFID_MODE=hardware
RFID_SPI_BUS=0
RFID_SPI_DEVICE=1
RFID_RST_PIN=25
```

Coexistence SPI :

```text
MAX7219 -> CE0 -> /dev/spidev0.0
RC522   -> CE1 -> /dev/spidev0.1
SCLK GPIO11 et MOSI GPIO10 sont partages
```

Le Raspberry lit uniquement l'UID normalise, par exemple `04A732B19C`. L'association UID -> client reste cote backend ou mock API.

## Matrice MAX7219

Le pilote utilise directement `spidev.SpiDev`. Si la bibliotheque expose `open_path`, elle est utilisee ; sinon le pilote parse `/dev/spidev0.0` et appelle `open(0, 0)`, compatible avec les versions `spidev` courantes sur Raspberry Pi.

Brochage de la matrice 8x8 MAX7219 utilise par le client :

| MAX7219 | Raspberry Pi 5 |
| --- | --- |
| CLK | GPIO11 / SCLK / pin 23 |
| CS | GPIO8 / CE0 / pin 24 |
| DIN | GPIO10 / MOSI / pin 19 |
| GND | GND |

`MATRIX_DEVICE=/dev/spidev0.0` sélectionne précisément CE0/GPIO8. CLK et DIN
sont les lignes SPI0 GPIO11 et GPIO10 ; il ne faut donc pas les déclarer comme
des sorties GPIO séparées.

La matrice fournit maintenant un langage visuel complet et non bloquant :

| Étape | Retour 8x8 |
| --- | --- |
| Mise sous tension | halo depuis le centre, puis `K` Kitunga |
| Panier prêt | carte RFID avec pulsation discrète |
| Première lecture RFID | barre lumineuse qui traverse la carte |
| Carte inconnue | carte + point d'exclamation en attente d'enrôlement |
| Panier initialisé | panier qui se construit puis coche |
| Panier actif | panier avec étincelle animée |
| Produit ajouté | `+` qui se transforme en coche |
| Paiement présenté | carte qui émet vers la caisse |
| Confirmation caisse attendue | anneau lumineux tournant |
| Paiement confirmé | coche qui se dessine et pulse |
| Solde insuffisant | portefeuille vide, maintenu jusqu'au prochain paiement |
| Erreur | croix maintenue jusqu'au prochain état métier |

Les animations et toutes les écritures SPI sont exécutées par un writer unique
dans un thread dédié. La lecture RFID, la caméra, YOLO et les appels HTTP
continuent donc pendant leur affichage. Les événements sont mis en file pour
qu'un scan reste visible même lorsque Django répond très vite.

Activer SPI sur Raspberry Pi avant le test hardware :

```bash
sudo raspi-config
```

Apercu sans hardware :

```bash
python matrix.py --preview --state WAITING_CUSTOMER
python matrix.py --preview --state CHECKOUT_PENDING
python matrix.py --preview 42
```

Test hardware :

```bash
python diagnostics.py matrix --hardware --state CHECKOUT_PENDING
python diagnostics.py matrix --hardware --cycle-states --pause 1.5
```

## Diagnostics

Commandes independantes :

```bash
python diagnostics.py api --api-mode mock
python diagnostics.py rfid --mode simulation
python diagnostics.py matrix --state PAYMENT_SUCCESS
python diagnostics.py pir --duration 5
python diagnostics.py buzzer --pattern all
python diagnostics.py camera --camera-backend auto
python diagnostics.py yolo --test-image /chemin/vers/image-de-test.jpg
```

`test_pir.py` reste disponible comme raccourci :

```bash
python test_pir.py --duration 5
```

## Confirmation du panier

La première lecture RFID identifie le client et ouvre une nouvelle facture. Lorsque le
client retire puis représente **la même carte**, la Pi demande le paiement RFID
de la facture active : Django vérifie la carte, le wallet, les articles, le
stock et l'idempotence avant de valider la vente. Une autre carte est refusée.

Un caissier peut aussi ouvrir **Paniers** dans le backend, choisir
**Vérifier et confirmer**, corriger si nécessaire et finaliser manuellement.
Cette action bloque les nouvelles détections ; la Pi récupère ensuite le
paiement et la commande de réinitialisation lors de son polling. La vente est
ensuite consultable dans **Factures**. Aucun appel du client Pi ne contient de
`basket_id`.

## Etats locaux

Etat centralise dans `LocalDeviceState` :

```text
WAITING_CUSTOMER -> RFID_ENROLLMENT_PENDING -> WAITING_CUSTOMER
WAITING_CUSTOMER -> ACTIVE -> PAYMENT_SUCCESS -> WAITING_CUSTOMER
                         \-> CHECKOUT_PENDING -> PAYMENT_SUCCESS
```

YOLO envoie des produits uniquement pendant `ACTIVE`.

## Limites volontaires de cette version

Non implemente :

- retrait produit automatique ;
- tracking directionnel ;
- ByteTrack entree/sortie ;
- barrieres IR ;
- detection de retrait physique ;
- wallet, stock, prix, ventes ou Mobile Money cote Raspberry ;
- dashboard ou interface smartphone.
