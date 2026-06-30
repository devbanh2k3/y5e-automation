from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

import pytest

from core import queue as queue_module


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, deque[str]] = defaultdict(deque)
        self.hashes: dict[str, dict[str, str]] = defaultdict(dict)
        self.sorted_sets: dict[str, dict[str, float]] = defaultdict(dict)
        self.strings: dict[str, str] = {}
        self.sets: dict[str, set[str]] = defaultdict(set)
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def lpush(self, key: str, value: str) -> int:
        self.lists[key].appendleft(value)
        return len(self.lists[key])

    async def rpop(self, key: str) -> str | None:
        if not self.lists[key]:
            return None
        return self.lists[key].pop()

    async def brpop(self, key: str, timeout: int = 0) -> tuple[str, str] | None:
        value = await self.rpop(key)
        if value is None:
            return None
        return key, value

    async def hset(
        self,
        key: str,
        field: str | None = None,
        value: str | None = None,
        mapping: dict[str, str] | None = None,
    ) -> int:
        target = self.hashes[key]
        updated = 0

        if mapping is not None:
            for map_key, map_value in mapping.items():
                if target.get(map_key) != map_value:
                    updated += 1
                target[map_key] = map_value
            return updated

        if field is None or value is None:
            raise TypeError("field and value are required when mapping is not provided")

        if target.get(field) != value:
            updated = 1
        target[field] = value
        return updated

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes[key].get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes[key])

    async def llen(self, key: str) -> int:
        return len(self.lists[key])

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        del ex
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.strings:
                del self.strings[key]
                removed += 1
            if key in self.hashes:
                del self.hashes[key]
                removed += 1
        return removed

    async def sadd(self, key: str, *values: str) -> int:
        before = len(self.sets[key])
        self.sets[key].update(values)
        return len(self.sets[key]) - before

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets[key])

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        target = self.sorted_sets[key]
        updated = 0
        for member, score in mapping.items():
            if member not in target:
                updated += 1
            target[member] = score
        return updated

    async def zrevrange(self, key: str, start: int, end: int) -> list[str]:
        items = sorted(
            self.sorted_sets[key].items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if end == -1:
            sliced = items[start:]
        else:
            sliced = items[start : end + 1]
        return [member for member, _score in sliced]

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(queue_module, "_redis", fake)
    return fake
