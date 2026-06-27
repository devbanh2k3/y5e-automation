from agents.topic_strategy_agent import (
    normalize_candidate,
    topic_similarity,
    validate_candidate,
)


def candidate(**overrides):
    value = {
        "title": "Top 10 Highest-Paid Movie Roles",
        "category": "film",
        "angle": "single_movie_salary",
        "metric_label": "SALARY",
        "entity_type": "individual_people",
        "data_availability_reason": "Public trade reporting exists",
        "image_availability_reason": "Editorial portraits exist",
        "viral_reason": "Recognizable names and money",
        "time_scope": "all_time",
    }
    value.update(overrides)
    return value


def test_normalize_candidate_uses_stable_keys():
    result = normalize_candidate(candidate(title="  Top 10 HIGHest Paid Movie Roles! "))

    assert result["normalized_title"] == "top 10 highest paid movie roles"
    assert result["angle"] == "single_movie_salary"
    assert result["metric_label"] == "SALARY"


def test_validation_accepts_open_taxonomy_but_rejects_unsafe_or_non_person_topics():
    open_taxonomy = normalize_candidate(candidate(category="touring_revenue"))
    non_person = normalize_candidate(candidate(entity_type="bands"))
    unsafe = normalize_candidate(candidate(title="Celebrity medical diagnosis ranking"))

    assert validate_candidate(open_taxonomy) == []
    assert "individual people" in " ".join(validate_candidate(non_person)).lower()
    assert "unsafe" in " ".join(validate_candidate(unsafe)).lower()


def test_similarity_detects_minor_title_variants():
    left = normalize_candidate(candidate())
    right = normalize_candidate(
        candidate(title="Top 10 Highest Paid Actors Per Movie Role")
    )

    assert topic_similarity(left, right) >= 0.72
