from concurrent.futures import ThreadPoolExecutor

import pytest

from core.topic_history import TopicHistoryError, TopicHistoryRepository


def reservation(key="movie_salary"):
    return {
        "reservation_id": key,
        "title": "Top Movie Salaries",
        "normalized_title": "top movie salaries",
        "angle": key,
        "metric_label": "SALARY",
        "status": "reserved",
    }


def test_repository_persists_status_transitions(tmp_path):
    repo = TopicHistoryRepository(tmp_path / "celebrity_topic_history.json")

    repo.reserve_many([reservation()])
    repo.mark_produced("movie_salary", topic_id="123")

    record = repo.load()[0]
    assert record["status"] == "produced"
    assert record["topic_id"] == "123"


def test_repository_refuses_duplicate_reservation_across_threads(tmp_path):
    path = tmp_path / "celebrity_topic_history.json"

    def reserve():
        return TopicHistoryRepository(path).reserve_many([reservation()])

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: reserve(), range(2)))

    assert sum(bool(value) for value in outcomes) == 1


def test_repository_preserves_corrupt_history(tmp_path):
    path = tmp_path / "celebrity_topic_history.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(TopicHistoryError, match="corrupt"):
        TopicHistoryRepository(path).load()

    assert path.read_text(encoding="utf-8") == "{broken"
