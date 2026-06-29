from core.card_production import Candidate, CardRecord, CardState, ProductionInventory
from core.production_checkpoints import CheckpointStore


def test_checkpoint_round_trip_preserves_ready_cards(tmp_path):
    store = CheckpointStore(tmp_path, run_id="run-1")
    inventory = ProductionInventory(target_cards=1, format_minimum_cards=1)
    inventory.cards["card-1"] = CardRecord(
        card_id="card-1",
        candidate=Candidate("Adele", "GB"),
        state=CardState.READY,
        scene={"title": "Adele"},
    )

    store.save("card-states", inventory.to_dict())
    restored = ProductionInventory.from_dict(store.load("card-states"))

    assert restored.cards["card-1"].state is CardState.READY
    assert restored.cards["card-1"].scene == {"title": "Adele"}
    assert not list(store.run_dir.glob("*.tmp"))


def test_checkpoint_ignores_uncommitted_temp_file(tmp_path):
    store = CheckpointStore(tmp_path, run_id="run-1")
    store.run_dir.mkdir(parents=True)
    (store.run_dir / "scenes.json.tmp").write_text('{"broken":')

    assert store.load("scenes", default={}) == {}


def test_checkpoint_appends_structured_errors(tmp_path):
    store = CheckpointStore(tmp_path, run_id="run-1")
    store.append_error({"card_id": "card-1", "category": "json_exhausted"})

    assert '"category": "json_exhausted"' in (
        store.run_dir / "errors.jsonl"
    ).read_text()
