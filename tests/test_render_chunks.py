from itertools import pairwise

from services.render_chunks import checkpoint_key, plan_chunks


def test_chunks_respect_hook_card_and_outro_boundaries() -> None:
    plan = plan_chunks(
        total_frames=9000,
        fps=30,
        target_chunk_seconds=40,
        protected_ranges=[(0, 360), (8760, 9000)],
        card_boundaries=list(range(360, 8761, 150)),
    )

    assert plan[0].start_frame == 0
    assert plan[-1].end_frame == 8999
    assert all(
        chunk.end_frame + 1 == following.start_frame
        for chunk, following in pairwise(plan)
    )
    assert all(
        chunk.end_frame + 1 not in range(1, 360)
        and chunk.end_frame + 1 not in range(8761, 9000)
        for chunk in plan[:-1]
    )


def test_chunks_use_nearest_legal_boundary_to_target() -> None:
    plan = plan_chunks(
        total_frames=3000,
        fps=30,
        target_chunk_seconds=40,
        protected_ranges=[],
        card_boundaries=[900, 1200, 1500, 2400],
    )

    assert [(item.start_frame, item.end_frame) for item in plan] == [
        (0, 1199),
        (1200, 2399),
        (2400, 2999),
    ]


def test_valid_checkpoint_is_stable_but_changed_assets_invalidate_it() -> None:
    first = checkpoint_key(
        video_hash="v1", asset_hash="a1", start_frame=0, end_frame=1199
    )
    same = checkpoint_key(
        video_hash="v1", asset_hash="a1", start_frame=0, end_frame=1199
    )
    changed = checkpoint_key(
        video_hash="v1", asset_hash="a2", start_frame=0, end_frame=1199
    )

    assert same == first
    assert changed != first
