"""Static reference card metadata, loaded from an extracted-data snapshot.

The JSON at ``sts2_env/cards/data/reference_static_metadata.json`` is a
snapshot extracted from the reference game sources (a 2026-05 game build
snapshot). The extraction/regeneration pipeline runs in the maintainer
environment and is intentionally not part of this repository: this module
only reconstructs Python objects (enums by name, frozensets from lists)
from that snapshot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sts2_env.core.card_pools import CardPoolId
from sts2_env.core.enums import CardId, CardRarity, CardTag, CardType, OrbEvokeType, TargetType


MULTIPLAYER_CONSTRAINT_NONE = "None"
MULTIPLAYER_CONSTRAINT_MULTIPLAYER_ONLY = "MultiplayerOnly"
MULTIPLAYER_CONSTRAINT_SINGLEPLAYER_ONLY = "SingleplayerOnly"

_DATA_PATH = Path(__file__).resolve().parent / "data" / "reference_static_metadata.json"


@dataclass(frozen=True)
class ReferenceCardStaticMetadata:
    card_id: CardId
    cost: int
    card_type: CardType
    target_type: TargetType
    rarity: CardRarity
    keywords: frozenset[str]
    tags: frozenset[CardTag]
    has_energy_cost_x: bool
    star_cost: int
    has_star_cost_x: bool
    max_upgrade_level: int
    can_be_generated_in_combat: bool
    can_be_generated_by_modifiers: bool
    has_turn_end_in_hand_effect: bool
    gains_block: bool
    orb_evoke_type: OrbEvokeType
    visual_card_pool: CardPoolId | None
    should_show_in_card_library: bool
    has_custom_playability: bool
    has_custom_should_play: bool
    has_custom_card_type: bool
    has_custom_target_type: bool
    multiplayer_constraint: str


def _snapshot() -> dict:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def _reconstruct_metadata(entry: dict) -> ReferenceCardStaticMetadata:
    return ReferenceCardStaticMetadata(
        card_id=CardId[entry["card_id"]],
        cost=entry["cost"],
        card_type=CardType[entry["card_type"]],
        target_type=TargetType[entry["target_type"]],
        rarity=CardRarity[entry["rarity"]],
        keywords=frozenset(entry["keywords"]),
        tags=frozenset(CardTag[name] for name in entry["tags"]),
        has_energy_cost_x=entry["has_energy_cost_x"],
        star_cost=entry["star_cost"],
        has_star_cost_x=entry["has_star_cost_x"],
        max_upgrade_level=entry["max_upgrade_level"],
        can_be_generated_in_combat=entry["can_be_generated_in_combat"],
        can_be_generated_by_modifiers=entry["can_be_generated_by_modifiers"],
        has_turn_end_in_hand_effect=entry["has_turn_end_in_hand_effect"],
        gains_block=entry["gains_block"],
        orb_evoke_type=OrbEvokeType[entry["orb_evoke_type"]],
        visual_card_pool=(
            CardPoolId[entry["visual_card_pool"]]
            if entry["visual_card_pool"] is not None
            else None
        ),
        should_show_in_card_library=entry["should_show_in_card_library"],
        has_custom_playability=entry["has_custom_playability"],
        has_custom_should_play=entry["has_custom_should_play"],
        has_custom_card_type=entry["has_custom_card_type"],
        has_custom_target_type=entry["has_custom_target_type"],
        multiplayer_constraint=entry["multiplayer_constraint"],
    )


@lru_cache(maxsize=1)
def _metadata_snapshot() -> tuple[dict, dict, dict, dict]:
    data = _snapshot()
    static = {CardId[name]: _reconstruct_metadata(entry) for name, entry in data["static"].items()}
    upgraded_static = {
        CardId[name]: _reconstruct_metadata(entry)
        for name, entry in data["upgraded_static"].items()
    }
    dynamic_vars = {CardId[name]: dict(vars_) for name, vars_ in data["dynamic_vars"].items()}
    upgraded_dynamic_vars = {
        CardId[name]: dict(vars_) for name, vars_ in data["upgraded_dynamic_vars"].items()
    }
    return static, upgraded_static, dynamic_vars, upgraded_dynamic_vars


@lru_cache(maxsize=1)
def reference_metadata_by_card_id() -> dict[CardId, ReferenceCardStaticMetadata]:
    return _metadata_snapshot()[0]


@lru_cache(maxsize=1)
def upgraded_reference_metadata_by_card_id() -> dict[CardId, ReferenceCardStaticMetadata]:
    return _metadata_snapshot()[1]


@lru_cache(maxsize=1)
def reference_dynamic_vars_by_card_id() -> dict[CardId, dict[str, int]]:
    return _metadata_snapshot()[2]


@lru_cache(maxsize=1)
def upgraded_reference_dynamic_vars_by_card_id() -> dict[CardId, dict[str, int]]:
    return _metadata_snapshot()[3]
