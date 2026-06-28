from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_installs_node_runtime_for_remotion_render() -> None:
    source = (ROOT / "Dockerfile").read_text()

    assert "FROM node:20-bookworm-slim AS node_runtime" in source
    assert "chromium" in source
    assert "COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node" in source
    assert "COPY --from=node_runtime /usr/local/lib/node_modules /usr/local/lib/node_modules" in source
    assert "apt-get install -y --no-install-recommends gcc libpq-dev nodejs npm" not in source
    assert "npm ci" in source
    assert "video_engine/package-lock.json" in source


def test_compose_builds_one_shared_application_image() -> None:
    source = (ROOT / "docker-compose.yml").read_text()

    assert "image: youtube_ai_automation-app:latest" in source
    assert source.count("build:") == 1
    assert "db-migrate:\n    image: youtube_ai_automation-app:latest" in source
    assert "worker:\n    image: youtube_ai_automation-app:latest" in source
    assert "telegram-bot:\n    image: youtube_ai_automation-app:latest" in source
    assert "production-worker:\n    image: youtube_ai_automation-app:latest" in source
    assert source.count("REMOTION_BROWSER_EXECUTABLE: /usr/bin/chromium") == 3
    assert "condition: service_completed_successfully" in source


def test_compose_runs_remote_production_inside_docker() -> None:
    source = (ROOT / "docker-compose.yml").read_text()

    assert 'command: ["python", "scripts/telegram_remote_bot.py"]' in source
    assert (
        'command: ["python", "scripts/process_production_task.py", "--loop", "--idle-sleep", "10"]'
        in source
    )
    assert 'command: ["python", "scripts/apply_db_migrations.py"]' in source


def test_compose_runs_youtube_upload_worker_with_shared_output() -> None:
    source = (ROOT / "docker-compose.yml").read_text()

    assert "youtube-upload-worker:" in source
    assert (
        'command: ["python", "scripts/process_youtube_upload_job.py", "--loop", "--idle-sleep", "5"]'
        in source
    )
    assert "./output:/app/output" in source


def test_dockerignore_excludes_runtime_and_generated_assets() -> None:
    source = (ROOT / ".dockerignore").read_text()

    assert ".git" in source
    assert ".env" in source
    assert "output/" in source
    assert "video_engine/node_modules/" in source
    assert "video_engine/public/images/country_scene_*.svg" in source
    assert "*.mp4" in source
