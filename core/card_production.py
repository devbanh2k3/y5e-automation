"""Domain rules for resilient card-based video production."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CardState(str, Enum):
    PLANNED = "planned"
    CONTENT_GENERATING = "content_generating"
    CONTENT_READY = "content_ready"
    FACT_CHECKING = "fact_checking"
    FACT_READY = "fact_ready"
    IMAGE_SEARCHING = "image_searching"
    READY = "ready"
    REPAIRING = "repairing"
    REPLACING = "replacing"
    SKIPPED = "skipped"
    FAILED = "failed"


class InsufficientReadyCardsError(ValueError):
    """The run exhausted recovery before reaching its render threshold."""

    category = "insufficient_ready_cards"


def normalize_person_key(value: str) -> str:
    """Return an accent- and punctuation-insensitive person identity key."""

    unaccented = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in unaccented if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


@dataclass(frozen=True)
class Candidate:
    name: str
    country_code: str
    selection_reason: str = ""
    aliases: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Candidate":
        aliases = value.get("aliases")
        return cls(
            name=str(value.get("name", "")).strip(),
            country_code=str(
                value.get("countryCode") or value.get("country_code") or ""
            ).strip().upper(),
            selection_reason=str(
                value.get("selectionReason") or value.get("selection_reason") or ""
            ).strip(),
            aliases=tuple(
                str(alias).strip()
                for alias in aliases
                if str(alias).strip()
            )
            if isinstance(aliases, list | tuple)
            else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "countryCode": self.country_code,
            "selectionReason": self.selection_reason,
            "aliases": list(self.aliases),
        }


@dataclass
class CardRecord:
    card_id: str
    candidate: Candidate
    state: CardState = CardState.PLANNED
    attempts: dict[str, int] = field(default_factory=dict)
    scene: dict[str, Any] | None = None
    fact_item: dict[str, Any] | None = None
    image_item: dict[str, Any] | None = None
    last_error: str = ""
    replacement_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "candidate": self.candidate.to_dict(),
            "state": self.state.value,
            "attempts": dict(self.attempts),
            "scene": self.scene,
            "fact_item": self.fact_item,
            "image_item": self.image_item,
            "last_error": self.last_error,
            "replacement_names": list(self.replacement_names),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CardRecord":
        return cls(
            card_id=str(value["card_id"]),
            candidate=Candidate.from_dict(dict(value["candidate"])),
            state=CardState(str(value.get("state", CardState.PLANNED.value))),
            attempts={
                str(key): int(count)
                for key, count in dict(value.get("attempts") or {}).items()
            },
            scene=value.get("scene"),
            fact_item=value.get("fact_item"),
            image_item=value.get("image_item"),
            last_error=str(value.get("last_error", "")),
            replacement_names=[
                str(name) for name in value.get("replacement_names") or []
            ],
        )


@dataclass
class ProductionInventory:
    target_cards: int
    format_minimum_cards: int
    minimum_ratio: float = 0.90
    candidates: list[Candidate] = field(default_factory=list)
    cards: dict[str, CardRecord] = field(default_factory=dict)
    reserve: deque[Candidate] = field(default_factory=deque)
    replaced_count: int = 0
    skipped_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_cards": self.target_cards,
            "format_minimum_cards": self.format_minimum_cards,
            "minimum_ratio": self.minimum_ratio,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "cards": {
                card_id: card.to_dict() for card_id, card in self.cards.items()
            },
            "reserve": [candidate.to_dict() for candidate in self.reserve],
            "replaced_count": self.replaced_count,
            "skipped_count": self.skipped_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProductionInventory":
        inventory = cls(
            target_cards=int(value["target_cards"]),
            format_minimum_cards=int(value["format_minimum_cards"]),
            minimum_ratio=float(value.get("minimum_ratio", 0.90)),
        )
        inventory.candidates = [
            Candidate.from_dict(dict(candidate))
            for candidate in value.get("candidates") or []
        ]
        inventory.cards = {
            str(card_id): CardRecord.from_dict(dict(card))
            for card_id, card in dict(value.get("cards") or {}).items()
        }
        inventory.reserve = deque(
            Candidate.from_dict(dict(candidate))
            for candidate in value.get("reserve") or []
        )
        inventory.replaced_count = int(value.get("replaced_count", 0))
        inventory.skipped_count = int(value.get("skipped_count", 0))
        return inventory

    @property
    def minimum_cards(self) -> int:
        return max(
            self.format_minimum_cards,
            math.ceil(self.target_cards * min(1.0, max(0.0, self.minimum_ratio))),
        )

    @property
    def ready_cards(self) -> list[CardRecord]:
        return [card for card in self.cards.values() if card.state is CardState.READY]

    @property
    def can_render(self) -> bool:
        return len(self.ready_cards) >= self.minimum_cards

    def add_candidates(self, candidates: list[Candidate]) -> None:
        known_keys: set[str] = set()
        for existing in self.candidates:
            known_keys.update(self._candidate_keys(existing))

        for candidate in candidates:
            candidate_keys = self._candidate_keys(candidate)
            if not candidate.name or not candidate_keys or candidate_keys & known_keys:
                continue
            self.candidates.append(candidate)
            known_keys.update(candidate_keys)

    def lock_candidates(self, candidates: list[Candidate]) -> None:
        self.cards.clear()
        primary = candidates[: self.target_cards]
        self.reserve = deque(candidates[self.target_cards :])
        for index, candidate in enumerate(primary, start=1):
            card_id = f"card-{index}"
            self.cards[card_id] = CardRecord(card_id=card_id, candidate=candidate)

    def replace(self, card_id: str, *, reason: str) -> CardRecord:
        card = self.cards[card_id]
        if not self.reserve:
            card.state = CardState.FAILED
            card.last_error = reason
            return card
        previous_name = card.candidate.name
        replacement = self.reserve.popleft()
        card.candidate = replacement
        card.state = CardState.REPLACING
        card.last_error = reason
        card.scene = None
        card.fact_item = None
        card.image_item = None
        card.replacement_names.append(previous_name)
        self.replaced_count += 1
        return card

    def skip(self, card_id: str, *, reason: str) -> None:
        card = self.cards[card_id]
        card.state = CardState.SKIPPED
        card.last_error = reason
        self.skipped_count += 1

    def finalize_scenes(self, *, content_format: str) -> list[dict[str, Any]]:
        if not self.can_render:
            raise InsufficientReadyCardsError(
                f"requires at least {self.minimum_cards} ready cards, got {len(self.ready_cards)}"
            )
        scenes = [dict(card.scene or {}) for card in self.ready_cards]
        if content_format == "ranking":
            total = len(scenes)
            for index, scene in enumerate(scenes):
                rank = total - index
                name = re.sub(r"^#\s*\d+\s*", "", str(scene.get("title", ""))).strip()
                scene["title"] = f"#{rank} {name}"
                status = str(scene.get("statusText", "")).strip()
                metric = status.split("|", 1)[1].strip() if "|" in status else status
                scene["statusText"] = f"#{rank} | {metric}" if metric else f"#{rank}"
        return scenes

    @staticmethod
    def _candidate_keys(candidate: Candidate) -> set[str]:
        return {
            key
            for key in (
                normalize_person_key(candidate.name),
                *(normalize_person_key(alias) for alias in candidate.aliases),
            )
            if key
        }
