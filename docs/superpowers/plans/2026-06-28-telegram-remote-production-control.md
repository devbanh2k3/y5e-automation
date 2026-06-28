# Telegram Remote Production Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Telegram-controlled multi-user production queue where allowed users can create video tasks and workers can pick tasks fairly by user.

**Architecture:** Store Telegram users, batches, and per-video production tasks in PostgreSQL-compatible repository functions, with a pure fair scheduler that chooses the next queued task by least recently served user. Telegram command handling is separated from Telegram network polling so commands are testable without calling Telegram.

**Tech Stack:** Python, asyncpg helper layer, FastAPI-compatible core services, existing batch/video production scripts, pytest.

---

### Task 1: Production Task Store and Fair Scheduler

**Files:**
- Modify: `db/schema.sql`
- Create: `core/production_tasks.py`
- Test: `tests/test_production_tasks.py`

- [ ] Add tables `telegram_users`, `production_batches`, `production_tasks`, and `production_user_scheduling`.
- [ ] Write tests for user authorization, batch task creation, and round-robin task selection.
- [ ] Implement repository helpers using `core.database.fetch/fetchrow/fetchval/execute`.
- [ ] Verify focused tests pass.

### Task 2: Telegram Command Handler

**Files:**
- Create: `services/telegram_remote.py`
- Test: `tests/test_telegram_remote.py`

- [ ] Write tests for `/start`, `/create 10 celebrity en flag_hero`, `/status`, unauthorized access, and max per-command count.
- [ ] Implement a command handler that validates users, creates task batches, and returns plain Telegram-safe text responses.
- [ ] Keep quota disabled; enforce only per-command max for technical safety.
- [ ] Verify focused tests pass.

### Task 3: Worker Bridge

**Files:**
- Create: `scripts/process_production_task.py`
- Test: `tests/test_process_production_task.py`

- [ ] Write tests that a task is claimed through fair scheduler and passed to `produce()`.
- [ ] Implement task runner for one task at a time; update task status to `pending_review` or `failed`.
- [ ] Persist `review_id`, `video_path`, and error text.
- [ ] Verify focused tests pass.

### Task 4: Documentation and Verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] Document Telegram allowed users and remote commands.
- [ ] Run `python3 -m pytest -q`.
- [ ] Commit the feature.

