import pytest

from core.card_production import (
    Candidate,
    CardRecord,
    CardState,
    InsufficientReadyCardsError,
    ProductionInventory,
    normalize_person_key,
)


def test_candidate_pool_deduplicates_normalized_names_and_aliases():
    inventory = ProductionInventory(
        target_cards=4,
        format_minimum_cards=2,
        minimum_ratio=0.90,
    )

    inventory.add_candidates(
        [
            Candidate("Beyonce", "US", aliases=("Beyoncé",)),
            Candidate("Beyoncé", "US"),
            Candidate("Adele", "GB"),
        ]
    )

    assert [item.name for item in inventory.candidates] == ["Beyonce", "Adele"]
    assert normalize_person_key("  Beyoncé! ") == "beyonce"


def test_failed_card_consumes_each_reserve_candidate_once():
    inventory = ProductionInventory(
        target_cards=2,
        format_minimum_cards=1,
        minimum_ratio=0.50,
    )
    inventory.lock_candidates(
        [
            Candidate("Adele", "GB"),
            Candidate("Rihanna", "BB"),
            Candidate("Pink", "US"),
        ]
    )

    replacement = inventory.replace("card-1", reason="image_missing")

    assert replacement.candidate.name == "Pink"
    assert replacement.state is CardState.REPLACING
    assert list(inventory.reserve) == []
    assert inventory.replaced_count == 1


def test_minimum_gate_accepts_90_percent_and_reindexes_ranking():
    inventory = ProductionInventory(
        target_cards=10,
        format_minimum_cards=6,
        minimum_ratio=0.90,
    )
    inventory.cards = {
        f"card-{index}": CardRecord(
            card_id=f"card-{index}",
            candidate=Candidate(f"Person {index}", "US"),
            state=CardState.READY,
            scene={"title": f"Person {index}", "statusText": "FACT"},
        )
        for index in range(9)
    }

    scenes = inventory.finalize_scenes(content_format="ranking")

    assert inventory.minimum_cards == 9
    assert inventory.can_render is True
    assert [scene["title"].split()[0] for scene in scenes] == [
        f"#{rank}" for rank in range(9, 0, -1)
    ]


def test_finalize_rejects_inventory_below_minimum():
    inventory = ProductionInventory(
        target_cards=10,
        format_minimum_cards=6,
        minimum_ratio=0.90,
    )
    inventory.cards["card-1"] = CardRecord(
        card_id="card-1",
        candidate=Candidate("Adele", "GB"),
        state=CardState.READY,
        scene={"title": "Adele"},
    )

    with pytest.raises(InsufficientReadyCardsError):
        inventory.finalize_scenes(content_format="ranking")
