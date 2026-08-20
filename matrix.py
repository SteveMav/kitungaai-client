#!/usr/bin/env python3
"""Pilotage d'une matrice LED 8x8 MAX7219 depuis un Raspberry Pi."""

from __future__ import annotations

import argparse
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import Any

from matrix_animations import ANIMATIONS, animation_names, get_animation


MAX_IDENTIFIER = 4095
DEFAULT_DEVICE = "/dev/spidev0.0"
DEFAULT_INTENSITY = 2
DEFAULT_SPEED_HZ = 1_000_000
DEFAULT_CASCADED = 1

MASKS = (0x000, 0xA5B, 0x5A4)
BOTTOM_PATTERN = (True, True, False, True, False, False, True, True)
RIGHT_PATTERN = (True, False, True, False, False, True, False, True)

REG_DECODE_MODE = 0x09
REG_INTENSITY = 0x0A
REG_SCAN_LIMIT = 0x0B
REG_SHUTDOWN = 0x0C
REG_DISPLAY_TEST = 0x0F

BLANK_FRAME = (0x00,) * 8

GLYPHS: dict[str, tuple[str, ...]] = {
    " ": (
        "00000000",
        "00000000",
        "00000000",
        "00000000",
        "00000000",
        "00000000",
        "00000000",
        "00000000",
    ),
    "A": (
        "00111100",
        "01100110",
        "11000011",
        "11000011",
        "11111111",
        "11000011",
        "11000011",
        "11000011",
    ),
    "C": (
        "00111110",
        "01100011",
        "11000000",
        "11000000",
        "11000000",
        "11000000",
        "01100011",
        "00111110",
    ),
    "D": (
        "11111100",
        "01100110",
        "01100011",
        "01100011",
        "01100011",
        "01100011",
        "01100110",
        "11111100",
    ),
    "E": (
        "11111111",
        "11000000",
        "11000000",
        "11111100",
        "11000000",
        "11000000",
        "11000000",
        "11111111",
    ),
    "I": (
        "01111110",
        "00011000",
        "00011000",
        "00011000",
        "00011000",
        "00011000",
        "00011000",
        "01111110",
    ),
    "K": (
        "11000110",
        "11001100",
        "11011000",
        "11110000",
        "11110000",
        "11011000",
        "11001100",
        "11000110",
    ),
    "O": (
        "00111100",
        "01100110",
        "11000011",
        "11000011",
        "11000011",
        "11000011",
        "01100110",
        "00111100",
    ),
    "P": (
        "11111100",
        "11000110",
        "11000110",
        "11111100",
        "11000000",
        "11000000",
        "11000000",
        "11000000",
    ),
    "R": (
        "11111100",
        "11000110",
        "11000110",
        "11111100",
        "11011000",
        "11001100",
        "11000110",
        "11000011",
    ),
    "S": (
        "00111111",
        "01100000",
        "11000000",
        "01111100",
        "00000110",
        "00000011",
        "00000110",
        "11111100",
    ),
    "T": (
        "11111111",
        "00011000",
        "00011000",
        "00011000",
        "00011000",
        "00011000",
        "00011000",
        "00011000",
    ),
    "V": (
        "11000011",
        "11000011",
        "11000011",
        "11000011",
        "01100110",
        "01100110",
        "00111100",
        "00011000",
    ),
    "W": (
        "11000011",
        "11000011",
        "11000011",
        "11011011",
        "11011011",
        "11111111",
        "01100110",
        "01100110",
    ),
}

STATE_TEXT = {
    "STARTUP": "K",
    "WAITING_CUSTOMER": "WAIT",
    "RFID_SCANNING": "SCAN",
    "RFID_ENROLLMENT_PENDING": "PEND",
    "BASKET_INITIALIZED": "INIT",
    "ACTIVE": "ACT",
    "CLIENT_IDENTIFIED": "ID",
    "PRODUCT_ADDED": "ADD",
    "PAYMENT_REQUESTED": "PAY",
    "CHECKOUT_PENDING": "PAY",
    "PAYMENT_SUCCESS": "OK",
    "INSUFFICIENT_FUNDS": "NO",
    "ERROR": "ERR",
}

STATE_ICON_FRAMES: dict[str, tuple[int, ...]] = {
    name: animation.steps[-1].frame for name, animation in ANIMATIONS.items()
}

PERSISTENT_STATES = frozenset(
    {
        "STARTUP",
        "WAITING_CUSTOMER",
        "RFID_ENROLLMENT_PENDING",
        "BASKET_INITIALIZED",
        "ACTIVE",
        "CHECKOUT_PENDING",
        "INSUFFICIENT_FUNDS",
        "ERROR",
    }
)
TEMPORARY_STATES = frozenset(
    {
        "RFID_SCANNING",
        "CLIENT_IDENTIFIED",
        "PRODUCT_ADDED",
        "PAYMENT_REQUESTED",
        "PAYMENT_SUCCESS",
    }
)
BUSINESS_STATES = PERSISTENT_STATES | TEMPORARY_STATES


def validate_identifier(identifier: int) -> int:
    """Valide et retourne un identifiant code sur 12 bits."""
    if isinstance(identifier, bool) or not isinstance(identifier, int):
        raise TypeError("l'identifiant doit etre un entier")
    if not 0 <= identifier <= MAX_IDENTIFIER:
        raise ValueError(f"l'identifiant doit etre compris entre 0 et {MAX_IDENTIFIER}")
    return identifier


def parse_identifier(text: str) -> int:
    """Convertit une saisie decimale en identifiant valide."""
    cleaned = text.strip()
    if not cleaned.isdecimal():
        raise ValueError("entrez uniquement des chiffres")
    return validate_identifier(int(cleaned, 10))


def _set_pixel(rows: list[int], row: int, column: int, is_on: bool) -> None:
    mask = 1 << (7 - column)
    if is_on:
        rows[row] |= mask
    else:
        rows[row] &= ~mask


def build_frame(identifier: int) -> tuple[int, ...]:
    """Construit les huit octets du motif associe a un identifiant."""
    validate_identifier(identifier)
    rows = [0] * 8

    # Reperes d'orientation asymetriques sur le contour.
    for index in range(8):
        _set_pixel(rows, 0, index, True)
        _set_pixel(rows, index, 0, True)
        _set_pixel(rows, 7, index, BOTTOM_PATTERN[index])
        _set_pixel(rows, index, 7, RIGHT_PATTERN[index])

    # Zone centrale 6x6 : trois copies masquees des 12 bits.
    for position in range(36):
        copy_index, bit_index = divmod(position, 12)
        raw_bit = bool((identifier >> (11 - bit_index)) & 1)
        mask_bit = bool((MASKS[copy_index] >> (11 - bit_index)) & 1)
        encoded_bit = raw_bit ^ mask_bit
        row, column = divmod(position, 6)
        _set_pixel(rows, row + 1, column + 1, encoded_bit)

    return tuple(rows)


def render_ascii(frame: Sequence[int]) -> str:
    """Produit un apercu texte d'un motif 8x8."""
    if len(frame) != 8:
        raise ValueError("une trame doit contenir exactement 8 lignes")

    return "\n".join(
        "".join("██" if row & (1 << (7 - column)) else "  " for column in range(8))
        for row in frame
    )


def render_frames_ascii(frames: Sequence[Sequence[int]]) -> str:
    """Produit un apercu texte de plusieurs matrices 8x8 chainees."""
    normalized = [_validate_frame(frame) for frame in frames]
    if not normalized:
        normalized = [BLANK_FRAME]

    lines = []
    for row_index in range(8):
        parts = []
        for frame in normalized:
            row = frame[row_index]
            parts.append(
                "".join("██" if row & (1 << (7 - column)) else "  " for column in range(8))
            )
        lines.append("  ".join(parts))
    return "\n".join(lines)


def text_to_frames(text: str, cascaded: int) -> tuple[tuple[int, ...], ...]:
    if cascaded <= 0:
        raise ValueError("cascaded must be strictly positive")

    characters = (text or " ")[:cascaded].upper().ljust(cascaded)
    return tuple(_glyph_to_frame(character) for character in characters)


def state_to_text(state: str) -> str:
    return STATE_TEXT.get(state.strip().upper(), state.strip().upper()[:DEFAULT_CASCADED] or " ")


def state_to_frames(state: str, cascaded: int) -> tuple[tuple[int, ...], ...]:
    if cascaded <= 0:
        raise ValueError("cascaded must be strictly positive")

    normalized_state = state.strip().upper()
    if cascaded == 1 and normalized_state in STATE_ICON_FRAMES:
        return (_validate_frame(STATE_ICON_FRAMES[normalized_state]),)

    return text_to_frames(state_to_text(normalized_state), cascaded)


def _glyph_to_frame(character: str) -> tuple[int, ...]:
    glyph = GLYPHS.get(character.upper(), GLYPHS[" "])
    return tuple(int(row, 2) for row in glyph)


def _validate_frame(frame: Sequence[int]) -> tuple[int, ...]:
    if len(frame) != 8 or any(not 0 <= row <= 0xFF for row in frame):
        raise ValueError("la trame doit contenir 8 octets")
    return tuple(int(row) for row in frame)


class Max7219Display:
    """Petit pilote MAX7219 utilisant le peripherique Linux spidev."""

    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        intensity: int = DEFAULT_INTENSITY,
        speed_hz: int = DEFAULT_SPEED_HZ,
        cascaded: int = DEFAULT_CASCADED,
        reverse_order: bool = False,
        spi_factory: Callable[[], Any] | None = None,
    ) -> None:
        if not 0 <= intensity <= 15:
            raise ValueError("l'intensite doit etre comprise entre 0 et 15")
        if speed_hz <= 0:
            raise ValueError("la vitesse SPI doit etre strictement positive")
        if cascaded <= 0:
            raise ValueError("le nombre de modules chaines doit etre strictement positif")

        if spi_factory is None:
            try:
                import spidev  # type: ignore[import-not-found]
            except ImportError as error:
                raise RuntimeError(
                    "Le module spidev est absent. Installez requirements.txt."
                ) from error
            spi_factory = spidev.SpiDev

        self._spi = spi_factory()
        self.cascaded = cascaded
        self.reverse_order = reverse_order
        try:
            self._open_device(device)
            self._spi.mode = 0
            self._spi.max_speed_hz = speed_hz
            self._initialize(intensity)
        except Exception:
            self._spi.close()
            raise

    def __enter__(self) -> "Max7219Display":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _open_device(self, device: str) -> None:
        if hasattr(self._spi, "open_path"):
            self._spi.open_path(device)
            return

        if not device.startswith("/dev/spidev"):
            raise RuntimeError(
                f"peripherique SPI invalide pour spidev.open(bus, device): {device}"
            )
        bus, chip = device.replace("/dev/spidev", "", 1).split(".", 1)
        self._spi.open(int(bus), int(chip))

    def _send(self, address: int, value: int) -> None:
        self._send_all(address, value)

    def _send_all(self, address: int, value: int) -> None:
        self._send_registers(address, [value] * self.cascaded)

    def _send_registers(self, address: int, values: Sequence[int]) -> None:
        if len(values) != self.cascaded:
            raise ValueError("nombre de valeurs SPI incompatible avec le chainage")

        ordered_values = list(values)
        if self.reverse_order:
            ordered_values.reverse()

        payload: list[int] = []
        for value in ordered_values:
            payload.extend([address, int(value) & 0xFF])
        self._spi.xfer2(payload)

    def _initialize(self, intensity: int) -> None:
        self._send_all(REG_DISPLAY_TEST, 0x00)
        self._send_all(REG_DECODE_MODE, 0x00)
        self._send_all(REG_SCAN_LIMIT, 0x07)
        self._send_all(REG_INTENSITY, intensity)
        self._send_all(REG_SHUTDOWN, 0x01)
        self.clear()

    def show_frame(self, frame: Sequence[int], *, device_index: int = 0) -> None:
        if not 0 <= device_index < self.cascaded:
            raise ValueError("device_index hors limites")

        frames = [BLANK_FRAME for _ in range(self.cascaded)]
        frames[device_index] = _validate_frame(frame)
        self.show_frames(frames)

    def show_frames(self, frames: Sequence[Sequence[int]]) -> None:
        if len(frames) > self.cascaded:
            raise ValueError("trop de trames pour le nombre de modules chaines")

        normalized = [_validate_frame(frame) for frame in frames]
        while len(normalized) < self.cascaded:
            normalized.append(BLANK_FRAME)

        for row_index, register in enumerate(range(1, 9)):
            self._send_registers(
                register,
                [frame[row_index] for frame in normalized],
            )

    def show_text(self, text: str) -> None:
        self.show_frames(text_to_frames(text, self.cascaded))

    def show_identifier(self, identifier: int) -> None:
        self.show_frame(build_frame(identifier))

    def clear(self) -> None:
        for register in range(1, 9):
            self._send_all(register, 0x00)

    def test(self, duration: float = 0.7) -> None:
        self._send_all(REG_DISPLAY_TEST, 0x01)
        time.sleep(duration)
        self._send_all(REG_DISPLAY_TEST, 0x00)

    def close(self) -> None:
        self._spi.close()


def _identifier_argument(text: str) -> int:
    try:
        return parse_identifier(text)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _intensity_argument(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("l'intensite doit etre un entier") from error
    if not 0 <= value <= 15:
        raise argparse.ArgumentTypeError("l'intensite doit etre comprise entre 0 et 15")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Affiche un identifiant de 0 a 4095 sur une matrice MAX7219."
    )
    parser.add_argument(
        "identifier",
        nargs="?",
        type=_identifier_argument,
        help="identifiant a afficher; sans valeur, ouvre le mode interactif",
    )
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help=f"peripherique SPI (defaut: {DEFAULT_DEVICE})",
    )
    parser.add_argument(
        "--intensity",
        type=_intensity_argument,
        default=DEFAULT_INTENSITY,
        help="luminosite de 0 a 15 (defaut: 2)",
    )
    parser.add_argument(
        "--speed-hz",
        type=int,
        default=DEFAULT_SPEED_HZ,
        help="frequence SPI (defaut: 1000000)",
    )
    parser.add_argument(
        "--cascaded",
        type=int,
        default=DEFAULT_CASCADED,
        help=f"nombre de matrices MAX7219 chainees (defaut: {DEFAULT_CASCADED})",
    )
    parser.add_argument(
        "--reverse-order",
        action="store_true",
        help="inverse l'ordre logique des modules chaines",
    )
    parser.add_argument(
        "--state",
        choices=sorted(set(STATE_TEXT) | set(animation_names())),
        help="affiche un etat local Kitunga au lieu d'un identifiant",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="affiche le motif dans le terminal sans acceder au materiel",
    )
    return parser


def run_interactive(display: Max7219Display) -> None:
    current_identifier = 1
    display.test()
    display.show_identifier(current_identifier)

    print("=== Matrice 8x8 MAX7219 ===")
    print("Entrez un identifiant de 0 a 4095.")
    print("Commandes : test, clear, help, quit")

    while True:
        try:
            command = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not command:
            continue
        if command in {"quit", "exit"}:
            return
        if command == "help":
            print("Nombre 0..4095 | test | clear | quit")
            continue
        if command == "clear":
            display.clear()
            print("Matrice eteinte.")
            continue
        if command == "test":
            display.test()
            display.show_identifier(current_identifier)
            print("Test termine.")
            continue

        try:
            current_identifier = parse_identifier(command)
        except (TypeError, ValueError) as error:
            print(f"Erreur : {error}.")
            continue

        display.show_identifier(current_identifier)
        print(f"Code affiche pour l'identifiant {current_identifier}.")


@dataclass
class _DisplayCommand:
    kind: str
    value: Any = None
    resume_state: str | None = None
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


class MatrixDisplay:
    """Adaptateur non bloquant avec un unique writer SPI MAX7219.

    Après l'initialisation du contrôleur, seul ``_run_writer`` appelle le
    pilote bas niveau. Les événements sont joués dans l'ordre et ne peuvent
    donc pas être effacés par une réponse backend trop rapide.
    """

    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        intensity: int = DEFAULT_INTENSITY,
        speed_hz: int = DEFAULT_SPEED_HZ,
        cascaded: int = DEFAULT_CASCADED,
        reverse_order: bool = False,
        spi_factory: Any | None = None,
    ) -> None:
        self.logger = logging.getLogger("kitunga_matrix")
        self._display = Max7219Display(
            device=device,
            intensity=intensity,
            speed_hz=speed_hz,
            cascaded=cascaded,
            reverse_order=reverse_order,
            spi_factory=spi_factory,
        )
        self.cascaded = cascaded
        self._commands: Queue[_DisplayCommand] = Queue()
        self._state_lock = threading.Lock()
        self._persistent_state = "WAITING_CUSTOMER"
        self._active_event: str | None = None
        self._current_identifier: int | None = None
        self._closed = False
        self._worker = threading.Thread(
            target=self._run_writer,
            name="kitunga-matrix-writer",
            daemon=True,
        )
        self._worker.start()
        self.logger.info(
            "MAX7219 matrix ready on %s with cascaded=%s reverse_order=%s",
            device,
            cascaded,
            reverse_order,
        )

    def __enter__(self) -> "MatrixDisplay":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def current_identifier(self) -> int | None:
        with self._state_lock:
            return self._current_identifier

    @property
    def current_state(self) -> str:
        with self._state_lock:
            return self._active_event or self._persistent_state

    def show_identifier(self, identifier: int) -> int:
        identifier = validate_identifier(identifier)
        if self._is_closed():
            raise RuntimeError("la matrice est fermee")
        self._submit("identifier", identifier)
        self.logger.info("Displaying matrix identifier: %s", identifier)
        return identifier

    def test(self, duration: float = 0.7) -> None:
        if not self._is_closed():
            self._submit("test", float(duration))

    def show_text(self, text: str) -> None:
        if not self._is_closed():
            self._submit("text", str(text))

    def show_state(self, state: str) -> None:
        """Affiche un état persistant ou programme un événement temporaire."""
        if self._is_closed():
            return
        normalized = self._normalize_state(state)
        kind = "event" if normalized in TEMPORARY_STATES else "state"
        self._submit(kind, normalized)
        self.logger.info("Matrix %s accepted: %s", kind, normalized)

    def play_animation(self, state: str, *, resume_state: str | None = None) -> None:
        """Programme une animation complète puis reprend l'état persistant."""
        if self._is_closed():
            return
        normalized = self._normalize_state(state)
        normalized_resume = None
        if resume_state is not None:
            normalized_resume = self._normalize_state(resume_state)
            if normalized_resume not in PERSISTENT_STATES:
                raise ValueError("resume_state doit être un état persistant")
        self._submit("event", normalized, resume_state=normalized_resume)
        self.logger.info(
            "Matrix event accepted: %s (resume=%s)",
            normalized,
            normalized_resume or self._persistent_state,
        )

    def show_detection(self, label: str, confidence: float) -> None:
        self.play_animation("PRODUCT_ADDED", resume_state="ACTIVE")

    def show_status(self, message: str) -> None:
        normalized = message.strip().upper()
        if normalized in BUSINESS_STATES:
            self.show_state(normalized)
        else:
            self.show_text(message)

    def clear(self) -> None:
        if not self._is_closed():
            self._submit("clear")

    def close(self) -> None:
        command = _DisplayCommand("close")
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._commands.put(command)
        try:
            self._wait_for(command)
        finally:
            self._worker.join()
        self.logger.info("MAX7219 matrix closed.")

    def _submit(
        self,
        kind: str,
        value: Any = None,
        *,
        resume_state: str | None = None,
    ) -> None:
        command = _DisplayCommand(kind, value, resume_state)
        with self._state_lock:
            if self._closed:
                return
            self._commands.put(command)
        self._wait_for(command)

    def _wait_for(self, command: _DisplayCommand) -> None:
        while not command.done.wait(0.1):
            if not self._worker.is_alive():
                raise RuntimeError("le writer de la matrice s'est arrêté")
        if command.error is not None:
            raise command.error

    def _is_closed(self) -> bool:
        with self._state_lock:
            return self._closed

    @staticmethod
    def _normalize_state(state: str) -> str:
        normalized = state.strip().upper()
        if normalized not in BUSINESS_STATES:
            raise ValueError(f"état de matrice inconnu: {state}")
        return normalized

    def _set_runtime_state(
        self,
        *,
        persistent_state: str,
        active_event: str | None,
        identifier: int | None,
    ) -> None:
        with self._state_lock:
            self._persistent_state = persistent_state
            self._active_event = active_event
            self._current_identifier = identifier

    def _run_writer(self) -> None:
        persistent_state = "WAITING_CUSTOMER"
        active_event: str | None = None
        pending_events: list[str] = []
        identifier: int | None = None
        manual_mode = True
        holding_last_frame = False
        step_index = 0
        running = True

        while running:
            timeout: float | None = None
            if not manual_mode and not holding_last_frame:
                displayed_state = active_event or persistent_state
                animation = get_animation(displayed_state)
                step = animation.steps[step_index]
                try:
                    self._display.show_frames(
                        self._frames_for_step(displayed_state, step.frame)
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Could not render matrix animation %s: %s",
                        displayed_state,
                        exc,
                    )
                timeout = step.duration

            try:
                command = self._commands.get(timeout=timeout)
            except Empty:
                displayed_state = active_event or persistent_state
                animation = get_animation(displayed_state)
                step_index += 1
                if step_index < len(animation.steps):
                    continue

                if active_event is not None:
                    active_event = pending_events.pop(0) if pending_events else None
                    step_index = 0
                    holding_last_frame = False
                    self._set_runtime_state(
                        persistent_state=persistent_state,
                        active_event=active_event,
                        identifier=identifier,
                    )
                elif animation.loop:
                    step_index = 0
                else:
                    holding_last_frame = True
                continue

            try:
                if command.kind == "state":
                    persistent_state = str(command.value)
                    manual_mode = False
                    identifier = None
                elif command.kind == "event":
                    if command.resume_state is not None:
                        persistent_state = command.resume_state
                    event = str(command.value)
                    if active_event is None:
                        active_event = event
                    elif event != active_event and event not in pending_events:
                        pending_events.append(event)
                    manual_mode = False
                    identifier = None
                elif command.kind == "identifier":
                    active_event = None
                    pending_events.clear()
                    manual_mode = True
                    identifier = int(command.value)
                    self._display.show_identifier(identifier)
                elif command.kind == "text":
                    active_event = None
                    pending_events.clear()
                    manual_mode = True
                    identifier = None
                    self._display.show_text(str(command.value))
                elif command.kind == "test":
                    active_event = None
                    pending_events.clear()
                    manual_mode = True
                    identifier = None
                    self._display.test(float(command.value))
                elif command.kind == "clear":
                    active_event = None
                    pending_events.clear()
                    manual_mode = True
                    identifier = None
                    self._display.clear()
                elif command.kind == "close":
                    running = False
                    try:
                        self._display.clear()
                    finally:
                        self._display.close()
                else:
                    raise ValueError(f"commande de matrice inconnue: {command.kind}")

                step_index = 0
                holding_last_frame = False
                self._set_runtime_state(
                    persistent_state=persistent_state,
                    active_event=active_event,
                    identifier=identifier,
                )
            except BaseException as exc:
                command.error = exc
            finally:
                command.done.set()
                self._commands.task_done()

    def _frames_for_step(
        self,
        state: str,
        icon_frame: Sequence[int],
    ) -> tuple[tuple[int, ...], ...]:
        icon = _validate_frame(icon_frame)
        if self.cascaded == 1:
            return (icon,)

        label_frames = text_to_frames(state_to_text(state), self.cascaded - 1)
        return (icon, *label_frames)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.speed_hz <= 0:
        raise SystemExit("Erreur : --speed-hz doit etre strictement positif.")
    if args.cascaded <= 0:
        raise SystemExit("Erreur : --cascaded doit etre strictement positif.")

    if args.preview:
        if args.state:
            print(f"Apercu de l'etat {args.state} :")
            print(render_frames_ascii(state_to_frames(args.state, args.cascaded)))
        else:
            identifier = 1 if args.identifier is None else args.identifier
            print(f"Apercu du code {identifier} :")
            print(render_ascii(build_frame(identifier)))
        return 0

    try:
        with Max7219Display(
            args.device,
            args.intensity,
            args.speed_hz,
            cascaded=args.cascaded,
            reverse_order=args.reverse_order,
        ) as display:
            if args.state:
                display.show_frames(state_to_frames(args.state, args.cascaded))
                print(f"Etat {args.state} affiche.")
            elif args.identifier is None:
                run_interactive(display)
            else:
                display.show_identifier(args.identifier)
                print(f"Code affiche pour l'identifiant {args.identifier}.")
    except (OSError, RuntimeError) as error:
        raise SystemExit(
            f"Impossible d'ouvrir {args.device} : {error}\n"
            "Verifiez le cablage, l'activation de SPI et l'installation de spidev."
        ) from error

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
