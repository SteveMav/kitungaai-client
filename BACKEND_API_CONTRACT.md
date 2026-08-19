# Contrat backend du client Kitunga Pi

La Pi configure uniquement :

```ini
API_BASE_URL=http://stevemavuela.local:8000
DEVICE_ID=KITUNGA-PI-001
```

Il n’y a aucun secret appareil, header d’autorisation, appairage ou identifiant de panier. Le `device_id` est inclus dans toutes les URLs. Les détections et paiements portent une clé `Idempotency-Key` conservée pendant les retries réseau.

## Ouvrir la facture active

```http
POST /api/iot/devices/KITUNGA-PI-001/invoice/start/
Content-Type: application/json

{"rfid_uid":"04A732B19C"}
```

```json
{
  "status": "ACTIVE",
  "customer": {"id":"CUST-0042","display_name":"Monsieur X"}
}
```

Une carte inconnue renvoie HTTP `202` et `RFID_ENROLLMENT_PENDING`. Elle doit être acceptée dans **Cartes RFID**, puis représentée.

## Ajouter un objet détecté

```http
POST /api/iot/devices/KITUNGA-PI-001/invoice/detections/
Idempotency-Key: <UUID>
Content-Type: application/json

{"label":"ESP32","confidence":0.95}
```

Le backend retrouve lui-même la facture active. Il renvoie `PRODUCT_ADDED` ou `UNCATALOGUED_OBJECT_ADDED`, avec `display_label`, `catalogued` et `accepted`.

## Lire l’état

```http
GET /api/iot/devices/KITUNGA-PI-001/invoice/status/
```

Statuts : `IDLE`, `ACTIVE`, `CHECKOUT_PENDING` ou `PAID`. Une réponse `PAID` contient la commande de reset quand elle reste à acquitter.

## Payer par RFID

```http
POST /api/iot/devices/KITUNGA-PI-001/invoice/rfid-payment/
Idempotency-Key: <UUID>
Content-Type: application/json

{"rfid_uid":"04A732B19C"}
```

```json
{
  "status":"PAID",
  "payment_status":"PAID",
  "sale_number":"KIT-20260819-ABCDEF1234",
  "reset_command_id":"<UUID>"
}
```

Django débite le wallet, crée la vente et ses lignes, diminue le stock et clôture la facture dans la même transaction. Les retries ne peuvent pas produire un second débit.

Erreurs principales : `DEVICE_UNAUTHORIZED`, `NO_ACTIVE_INVOICE`, `RFID_MISMATCH`, `INSUFFICIENT_FUNDS`, `PAYMENT_DECLINED` et `CHECKOUT_REQUIRED`.
