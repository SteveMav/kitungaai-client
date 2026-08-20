"""Animations métier pour une matrice LED MAX7219 8x8.

Les motifs restent volontairement simples : sur 64 pixels, une silhouette
stable et un mouvement court sont plus faciles à reconnaître qu'un texte.
"""

from __future__ import annotations

from dataclasses import dataclass


MatrixFrame = tuple[int, ...]


@dataclass(frozen=True)
class AnimationStep:
    frame: MatrixFrame
    duration: float


@dataclass(frozen=True)
class MatrixAnimation:
    steps: tuple[AnimationStep, ...]
    loop: bool = False


def _frame(*rows: str) -> MatrixFrame:
    if len(rows) != 8 or any(len(row) != 8 or set(row) - {"0", "1"} for row in rows):
        raise ValueError("un motif de matrice doit contenir 8 lignes binaires de 8 pixels")
    return tuple(int(row, 2) for row in rows)


def _step(frame: MatrixFrame, duration: float) -> AnimationStep:
    return AnimationStep(frame=frame, duration=duration)


BLANK = _frame(
    "00000000",
    "00000000",
    "00000000",
    "00000000",
    "00000000",
    "00000000",
    "00000000",
    "00000000",
)

# Démarrage : le panier "s'allume" depuis son centre, puis révèle le K Kitunga.
STARTUP_DOT = _frame(
    "00000000",
    "00000000",
    "00000000",
    "00011000",
    "00011000",
    "00000000",
    "00000000",
    "00000000",
)
STARTUP_SMALL = _frame(
    "00000000",
    "00000000",
    "00011000",
    "00100100",
    "00100100",
    "00011000",
    "00000000",
    "00000000",
)
STARTUP_LARGE = _frame(
    "00011000",
    "00100100",
    "01000010",
    "10000001",
    "10000001",
    "01000010",
    "00100100",
    "00011000",
)
KITUNGA_K = _frame(
    "11000110",
    "11001100",
    "11011000",
    "11110000",
    "11110000",
    "11011000",
    "11001100",
    "11000110",
)

# Carte RFID en attente, avec un halo discret qui signifie "présentez la carte".
WAITING_CARD = _frame(
    "00000000",
    "00111100",
    "01000010",
    "01011010",
    "01011010",
    "01000010",
    "00111100",
    "00000000",
)
WAITING_CARD_PULSE = _frame(
    "10000001",
    "00111100",
    "01000010",
    "01011010",
    "01011010",
    "01000010",
    "00111100",
    "10000001",
)

# La ligne lumineuse traverse la carte pendant la lecture RFID.
RFID_SCAN_1 = _frame(
    "00000000",
    "01111110",
    "01000010",
    "01011010",
    "01011010",
    "01000010",
    "00111100",
    "00000000",
)
RFID_SCAN_2 = _frame(
    "00000000",
    "00111100",
    "01111110",
    "01011010",
    "01011010",
    "01000010",
    "00111100",
    "00000000",
)
RFID_SCAN_3 = _frame(
    "00000000",
    "00111100",
    "01000010",
    "01111110",
    "01011010",
    "01000010",
    "00111100",
    "00000000",
)
RFID_SCAN_4 = _frame(
    "00000000",
    "00111100",
    "01000010",
    "01011010",
    "01111110",
    "01000010",
    "00111100",
    "00000000",
)
RFID_SCAN_5 = _frame(
    "00000000",
    "00111100",
    "01000010",
    "01011010",
    "01011010",
    "01111110",
    "00111100",
    "00000000",
)

# Enrôlement : carte + point d'exclamation, sans ressembler à une erreur fatale.
ENROLLMENT_CARD = _frame(
    "00111100",
    "01000010",
    "01011010",
    "01011010",
    "01000010",
    "00111100",
    "00011000",
    "00011000",
)
ENROLLMENT_ALERT = _frame(
    "00111100",
    "01000010",
    "01011010",
    "01011010",
    "01000010",
    "00111100",
    "00000000",
    "00011000",
)

# Panier actif et initialisation : panier, roues et petite étincelle animée.
CART_EMPTY = _frame(
    "00000000",
    "10000000",
    "11111100",
    "01000100",
    "01111100",
    "00101000",
    "00101000",
    "00000000",
)
CART_ACTIVE_LEFT = _frame(
    "10000000",
    "10000000",
    "11111100",
    "01000100",
    "01111100",
    "00101000",
    "00101000",
    "00000001",
)
CART_ACTIVE_RIGHT = _frame(
    "00000001",
    "10000000",
    "11111100",
    "01000100",
    "01111100",
    "00101000",
    "00101000",
    "10000000",
)
CART_CHECK = _frame(
    "00000000",
    "10000001",
    "11111110",
    "01001100",
    "01111000",
    "00111000",
    "00101000",
    "00000000",
)

# Ajout produit : un + se déploie puis devient une coche.
PLUS_SMALL = _frame(
    "00000000",
    "00000000",
    "00011000",
    "00111100",
    "00111100",
    "00011000",
    "00000000",
    "00000000",
)
PLUS_LARGE = _frame(
    "00011000",
    "00011000",
    "00011000",
    "11111111",
    "11111111",
    "00011000",
    "00011000",
    "00011000",
)
CHECK = _frame(
    "00000000",
    "00000001",
    "00000011",
    "10000110",
    "11001100",
    "01111000",
    "00110000",
    "00000000",
)

# Paiement demandé : une carte envoie des ondes vers la caisse.
PAYMENT_WAVE_1 = _frame(
    "00000000",
    "11110000",
    "10010000",
    "11110010",
    "10010000",
    "11110000",
    "00000000",
    "00000000",
)
PAYMENT_WAVE_2 = _frame(
    "00000000",
    "11110000",
    "10010010",
    "11110001",
    "10010010",
    "11110000",
    "00000000",
    "00000000",
)
PAYMENT_WAVE_3 = _frame(
    "00000000",
    "11110010",
    "10010001",
    "11110000",
    "10010001",
    "11110010",
    "00000000",
    "00000000",
)

# Validation caisse en attente : anneau tournant, donc état vivant et non bloqué.
PENDING_TOP = _frame(
    "00011000",
    "01100110",
    "01000010",
    "10000001",
    "10000001",
    "01000010",
    "01100110",
    "00000000",
)
PENDING_RIGHT = _frame(
    "00000000",
    "01100110",
    "01000011",
    "10000001",
    "10000001",
    "01000011",
    "01100110",
    "00000000",
)
PENDING_BOTTOM = _frame(
    "00000000",
    "01100110",
    "01000010",
    "10000001",
    "10000001",
    "01000010",
    "01100110",
    "00011000",
)
PENDING_LEFT = _frame(
    "00000000",
    "01100110",
    "11000010",
    "10000001",
    "10000001",
    "11000010",
    "01100110",
    "00000000",
)

# Confirmation : la coche se dessine, puis pulse sans jamais devenir ambiguë.
CHECK_START = _frame(
    "00000000",
    "00000000",
    "00000000",
    "10000000",
    "11000000",
    "01100000",
    "00000000",
    "00000000",
)
CHECK_MIDDLE = _frame(
    "00000000",
    "00000000",
    "00000011",
    "10000110",
    "11001100",
    "01111000",
    "00110000",
    "00000000",
)
CHECK_GLOW = _frame(
    "10000001",
    "00000001",
    "00000011",
    "10000110",
    "11001100",
    "01111000",
    "00110000",
    "10000001",
)

# Solde insuffisant et erreur générique ont des silhouettes distinctes.
EMPTY_WALLET = _frame(
    "00111100",
    "01000010",
    "11111111",
    "10000001",
    "10110001",
    "10000001",
    "11111111",
    "00011000",
)
ERROR_X = _frame(
    "11000011",
    "01100110",
    "00111100",
    "00011000",
    "00011000",
    "00111100",
    "01100110",
    "11000011",
)


ANIMATIONS: dict[str, MatrixAnimation] = {
    "STARTUP": MatrixAnimation(
        (
            _step(STARTUP_DOT, 0.08),
            _step(STARTUP_SMALL, 0.10),
            _step(STARTUP_LARGE, 0.14),
            _step(KITUNGA_K, 0.42),
        )
    ),
    "WAITING_CUSTOMER": MatrixAnimation(
        (_step(WAITING_CARD, 0.65), _step(WAITING_CARD_PULSE, 0.18)),
        loop=True,
    ),
    "RFID_SCANNING": MatrixAnimation(
        tuple(
            _step(frame, 0.09)
            for frame in (RFID_SCAN_1, RFID_SCAN_2, RFID_SCAN_3, RFID_SCAN_4, RFID_SCAN_5)
        )
    ),
    "RFID_ENROLLMENT_PENDING": MatrixAnimation(
        (_step(ENROLLMENT_CARD, 0.70), _step(ENROLLMENT_ALERT, 0.20)),
        loop=True,
    ),
    "BASKET_INITIALIZED": MatrixAnimation(
        (
            _step(STARTUP_DOT, 0.10),
            _step(CART_EMPTY, 0.24),
            _step(CART_CHECK, 0.48),
        )
    ),
    "ACTIVE": MatrixAnimation(
        (_step(CART_ACTIVE_LEFT, 0.70), _step(CART_ACTIVE_RIGHT, 0.70)),
        loop=True,
    ),
    "CLIENT_IDENTIFIED": MatrixAnimation((_step(CART_CHECK, 0.70),)),
    "PRODUCT_ADDED": MatrixAnimation(
        (_step(PLUS_SMALL, 0.10), _step(PLUS_LARGE, 0.18), _step(CHECK, 0.42))
    ),
    "PAYMENT_REQUESTED": MatrixAnimation(
        (
            _step(PAYMENT_WAVE_1, 0.16),
            _step(PAYMENT_WAVE_2, 0.16),
            _step(PAYMENT_WAVE_3, 0.16),
        )
    ),
    "CHECKOUT_PENDING": MatrixAnimation(
        (
            _step(PENDING_TOP, 0.16),
            _step(PENDING_RIGHT, 0.16),
            _step(PENDING_BOTTOM, 0.16),
            _step(PENDING_LEFT, 0.16),
        ),
        loop=True,
    ),
    "PAYMENT_SUCCESS": MatrixAnimation(
        (
            _step(CHECK_START, 0.12),
            _step(CHECK_MIDDLE, 0.16),
            _step(CHECK, 0.70),
            _step(CHECK_GLOW, 0.18),
        ),
        loop=True,
    ),
    "INSUFFICIENT_FUNDS": MatrixAnimation(
        (_step(EMPTY_WALLET, 0.50), _step(BLANK, 0.12), _step(EMPTY_WALLET, 0.50))
    ),
    "ERROR": MatrixAnimation(
        (_step(ERROR_X, 0.24), _step(BLANK, 0.12), _step(ERROR_X, 0.36))
    ),
}


def get_animation(state: str) -> MatrixAnimation:
    """Retourne l'animation d'un état, ou une erreur explicite de programmation."""
    normalized = state.strip().upper()
    try:
        return ANIMATIONS[normalized]
    except KeyError as error:
        raise ValueError(f"animation de matrice inconnue: {state}") from error


def animation_names() -> tuple[str, ...]:
    return tuple(ANIMATIONS)
