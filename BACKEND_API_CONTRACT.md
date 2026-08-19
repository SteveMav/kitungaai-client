# Backend API Contract for Kitunga Pi Client

Routes proposees pour `RealApiClient`. Les noms peuvent changer, mais seules les methodes de `RealApiClient` doivent etre adaptees si le contrat Django final differe.

Base URL :

```text
API_BASE_URL=http://IP_BACKEND:8000
```

Headers :

```http
Content-Type: application/json
Accept: application/json
Authorization: Device <secret>
X-Device-Code: KITUNGA-PI-001
```

Les deux en-têtes d'identité sont obligatoires sur le backend Django. Pour les
requêtes qui modifient l'état (`detections` et `rfid-payment`), le client envoie
aussi `Idempotency-Key: <UUID>` et le conserve lors d'un retry réseau.

## 1. START SESSION

Identifier un client par RFID et ouvrir une session panier active.

```http
POST /api/iot/sessions/start/
```

Request :

```json
{
  "device_id": "KITUNGA-PI-001",
  "rfid_uid": "04A732B19C"
}
```

Response 200 :

```json
{
  "status": "ACTIVE",
  "basket_id": "KITUNGA-0042",
  "customer": {
    "id": "CUST-0042",
    "display_name": "Monsieur X"
  }
}
```

Carte inconnue, à faire approuver dans l'interface serveur :

```json
{
  "status": "RFID_ENROLLMENT_PENDING",
  "message": "The card is awaiting administrator approval.",
  "enrollment_id": 12
}
```

Cette réponse utilise HTTP `202`. La Pi affiche l'état d'attente et le client
doit retirer puis représenter la carte après son acceptation par un administrateur.

Erreurs attendues : `INVALID_RFID` (`400`), `DEVICE_UNAUTHORIZED` (`401`),
`RFID_CARD_INACTIVE` ou `RFID_ENROLLMENT_REJECTED` (`403`), et
`SESSION_ALREADY_ACTIVE` (`409`).

## 2. SEND DETECTION

Ajouter un produit detecte au panier. YOLO sert uniquement a ajouter.

```http
POST /api/iot/baskets/{basket_id}/detections/
```

Request :

```json
{
  "device_id": "KITUNGA-PI-001",
  "label": "ESP32",
  "confidence": 0.95
}
```

Response 200/201 :

```json
{
  "status": "PRODUCT_ADDED",
  "basket_id": "KITUNGA-0042",
  "label": "ESP32",
  "accepted": true
}
```

Erreurs attendues :

```json
{
  "status": "UNKNOWN_PRODUCT",
  "message": "No product matches this YOLO label"
}
```

Codes possibles : `400`, `404`, `409`, `422`, `500`.

## 3. GET BASKET STATUS

Permettre au Raspberry de savoir si le panier attend le paiement.

```http
GET /api/iot/baskets/{basket_id}/status/
```

Response 200 :

```json
{
  "status": "ACTIVE",
  "basket_id": "KITUNGA-0042"
}
```

Ou :

```json
{
  "status": "CHECKOUT_PENDING",
  "basket_id": "KITUNGA-0042"
}
```

Statuts attendus au minimum : `ACTIVE`, `CHECKOUT_PENDING`, `PAID`, `CANCELLED`.

Codes possibles : `404`, `409`, `500`.

## 4. CONFIRM RFID PAYMENT

Confirmer le paiement RFID du panier en attente.

```http
POST /api/iot/baskets/{basket_id}/rfid-payment/
```

Request :

```json
{
  "device_id": "KITUNGA-PI-001",
  "rfid_uid": "04A732B19C"
}
```

Response 200 :

```json
{
  "status": "PAID",
  "payment_status": "PAID",
  "basket_id": "KITUNGA-0042",
  "reset_command_id": "commande-uuid-a-acquitter"
}
```

Après `PAID`, le client acquitte `reset_command_id` sur l'endpoint V1 de
commande appareil avant de démarrer le client suivant.

Erreurs attendues :

```json
{
  "status": "INSUFFICIENT_FUNDS",
  "message": "Wallet balance is insufficient"
}
```

Autres statuts possibles : `RFID_MISMATCH`, `PAYMENT_DECLINED`, `CHECKOUT_REQUIRED`, `BASKET_NOT_FOUND`.

Codes possibles : `400`, `402`, `403`, `404`, `409`, `500`.

## Contraintes cote backend

- Le backend reste source de verite pour prix, wallet, paiement, ventes et stocks.
- Le Raspberry n'envoie pas de retrait produit.
- Le backend doit accepter les retries reseau sans creer de corruption commerciale.
- Les reponses doivent etre des objets JSON.
- Les erreurs doivent contenir au moins `status` et idealement `message`.

## Diagnostic de connexion Pi

- `401 DEVICE_UNAUTHORIZED` : le code appareil ou le secret est absent, faux,
  tourné avec `provision_device --rotate`, ou l'appareil est désactivé. Le
  secret doit être conservé dans le `.env` local de la Pi.
- `404 API_ROUTE_NOT_FOUND` : l'URL pointe vers le mauvais PC ou un ancien
  serveur Django est toujours lancé. Relancer `start_lan_server.ps1`, puis
  vérifier `API_BASE_URL=http://IP_DU_PC:8000`.
