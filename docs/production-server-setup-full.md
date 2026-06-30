# Production Server Setup Full

Ngay luc nay repo local chua san sang de coi la da "up git" hoan chinh:

- Branch hien tai: `codex/production-foundation-v1`
- Remote: `https://github.com/devbanh2k3/y5e-automation.git`
- Local dang `ahead 34` so voi `origin/codex/production-foundation-v1`
- Working tree con nhieu file modified/untracked

Truoc khi deploy may moi, can commit va push het thay doi can dung. Neu muon may moi chay ban moi nhat, deploy tu branch da push, khong copy thu cong tu may hien tai.

## 1. Cau hinh may khuyen nghi

### Cau hinh toi thieu de chay on dinh

- CPU: 8 core / 16 thread tro len
- RAM: 32 GB
- Disk: NVMe SSD con trong 300 GB tro len
- OS: Windows 11 Pro + WSL2 Ubuntu 24.04, hoac Ubuntu Server 24.04 truc tiep
- Network: upload on dinh, uu tien day LAN

### Cau hinh khuyen nghi de render nhanh

- CPU: Ryzen 9 7900/7950X, Intel i7/i9 gen moi, hoac tuong duong
- RAM: 64 GB
- Disk: NVMe Gen4 1 TB
- GPU: khong phai yeu cau chinh. Remotion/Chromium render thuong an CPU/RAM nhieu hon GPU. GPU tot co ich cho desktop/browser, nhung dung CPU manh + NVMe nhanh se thuc te hon.
- Power: de Windows o che do `Best performance`, khong sleep khi render

### Docker Desktop resource settings tren Windows

Trong Docker Desktop:

- CPUs: 8-12 core, tuy CPU may
- Memory: 16-32 GB
- Swap: 8-16 GB
- Disk image: 200 GB tro len
- Enable WSL2 backend
- Dat repo trong filesystem WSL, vi du `/home/y5e/y5e-automation`, khong nen render truc tiep trong `/mnt/c/...` vi I/O cham hon.

## 2. Cai dat nen tren may Windows PC

### Cach tu dong khuyen nghi

Chay trong PowerShell Administrator tu repo da clone hoac file source vua tai ve:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\setup_windows_server.ps1 -InstallTools
```

Script Windows se:

- Kiem tra quyen Administrator
- Bat WSL2/Virtual Machine Platform neu can
- Cai Git/Docker Desktop qua `winget` neu dung `-InstallTools`
- Cai Ubuntu 24.04 neu chua co
- Goi `scripts/setup_wsl_production.sh` trong Ubuntu WSL

Neu chi muon chuan bi Windows va tu chay buoc WSL sau:

```powershell
.\scripts\setup_windows_server.ps1 -InstallTools -SkipWslDeploy
```

Trong Ubuntu WSL co the chay truc tiep:

```bash
bash scripts/setup_wsl_production.sh \
  --repo-url https://github.com/devbanh2k3/y5e-automation.git \
  --branch main \
  --project-dir /home/y5e/y5e-automation
```

Script se khong ghi de `.env`. Neu `.env` chua co, no tao tu `.env.example` va dung lai de ban dien token/key that.

### Windows

1. Cai Windows 11 Pro.
2. Bat virtualization trong BIOS.
3. Cai Docker Desktop.
4. Cai WSL2 Ubuntu:

```powershell
wsl --install -d Ubuntu-24.04
```

5. Trong Docker Desktop, bat WSL integration cho Ubuntu.

### Trong Ubuntu WSL

```bash
sudo apt update
sudo apt install -y git curl ca-certificates openssl
```

Kiem tra:

```bash
docker version
docker compose version
git --version
```

## 3. Clone source

Neu code da merge ve `main`:

```bash
git clone https://github.com/devbanh2k3/y5e-automation.git
cd y5e-automation
git checkout main
git pull
```

Neu chua merge ma can chay branch production hien tai:

```bash
git clone https://github.com/devbanh2k3/y5e-automation.git
cd y5e-automation
git checkout codex/production-foundation-v1
git pull
```

Kiem tra source:

```bash
git status --short --branch
```

May production nen hien working tree sach. Neu thay file modified/untracked tren server, dung lai va kiem tra truoc khi chay.

## 4. Tao file `.env`

```bash
cp .env.example .env
```

Bat buoc cau hinh cac bien sau:

```env
PRIMARY_API_BASE=https://your-router9-endpoint.com/v1
PRIMARY_API_KEY=your_router_key_here
PRIMARY_MODEL=gc/gemini-3-flash-preview

FALLBACK_API_BASE=https://generativelanguage.googleapis.com/v1beta/openai
FALLBACK_API_KEY=your_google_ai_studio_key
FALLBACK_MODEL=gemini-2.5-flash

TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_default_chat_id

PUBLIC_BASE_URL=https://studio.veo3depzai.io.vn
CLOUDFLARE_TUNNEL_TOKEN=eyJ...

YOUTUBE_UPLOAD_ENABLED=true
YOUTUBE_OAUTH_CLIENT_ID=your_google_oauth_client_id
YOUTUBE_OAUTH_CLIENT_SECRET=your_google_oauth_client_secret
YOUTUBE_OAUTH_CALLBACK_PATH=/api/youtube/oauth/callback
YOUTUBE_TOKEN_ENCRYPTION_KEY=your_fernet_key

STORAGE_PATH=./output
LOG_LEVEL=INFO

RESILIENT_CARD_PIPELINE_ENABLED=true
CARD_MINIMUM_RATIO=0.80
CARD_PLANNER_ATTEMPTS=4
CARD_CONTENT_REPAIR_ATTEMPTS=2
CARD_FACT_REPAIR_ATTEMPTS=2
CARD_REPLACEMENT_ATTEMPTS=3
AI_JSON_REPAIR_ATTEMPTS=2
AI_TRANSPORT_ATTEMPTS=3
```

Tao `YOUTUBE_TOKEN_ENCRYPTION_KEY`:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Khong commit `.env`.

### Resilient card production

Flow nay duoc dung cho video Celebrity dai:

1. AI lap danh sach nhan vat va candidate du phong.
2. Code loai trung tren toan video truoc khi viet scene.
3. Scene writer chi viet cac nhan vat da khoa.
4. Card loi duoc sua rieng, sau do thay candidate, sau cung moi bo qua.
5. Video van render neu so card dat chuan bang hoac cao hon `CARD_MINIMUM_RATIO`.

Voi `CARD_MINIMUM_RATIO=0.80`, video du kien 58 card co the render voi toi thieu
47 card dat chuan. He thong khong lam cham slide de bu thoi luong; duration thuc te
duoc tinh lai theo so card con lai. Ranking va metadata count cung duoc danh lai theo
so card thuc te.

Khong ha `CARD_MINIMUM_RATIO` chi de tang ti le hoan tat. Gia tri thap hon dong nghia
video co it noi dung duoc xac minh hon.

Checkpoint nam tai:

```text
./output/production_runs/<run_id>/
```

Thu muc nay chua candidate pool, card state, scene, fact/image verification va render
manifest. Khi worker/container restart, card da `ready` khong bi goi lai AI, fact API
hoac image search. Khong xoa checkpoint cua run dang xu ly.

Telegram co the bao video hoan tat o che do degraded, vi du `55/58 card dat chuan`.
Day la ket qua hop le: cac card khong du du lieu da bi loai co kiem soat, khong phai
toan video bi fail.

## 5. Cloudflare Named Tunnel co dinh

Trong Cloudflare Dashboard:

1. Mo `Networking -> Tunnels -> Create tunnel`.
2. Dat ten `youtube-automation-production`.
3. Them Public hostname `studio.veo3depzai.io.vn`.
4. Dat Service la `http://api:8000`.
5. Chon Docker va copy rieng token bat dau bang `eyJ...`.

Gan token vao `.env`, khong commit file nay:

```env
PUBLIC_BASE_URL=https://studio.veo3depzai.io.vn
CLOUDFLARE_TUNNEL_TOKEN=eyJ...
```

Khoi dong va kiem tra tunnel:

```bash
docker compose up -d cloudflared
docker compose logs --tail=80 cloudflared
./scripts/verify_named_tunnel.sh
```

Named Tunnel giu nguyen hostname sau khi Docker hoac may server restart.

## 6. Google OAuth / YouTube upload

Trong Google Cloud Console:

1. Tao project.
2. Enable `YouTube Data API v3`.
3. Tao OAuth Client.
4. Authorized redirect URI:

```text
https://studio.veo3depzai.io.vn/api/youtube/oauth/callback
```

Trong Telegram:

```text
/channels
```

Nhan `Add channel`, connect tung kenh YouTube. Moi Telegram user chi quan ly kenh cua chinh user do.

## 7. Start production stack

Lan dau:

```bash
docker compose up -d --build
```

Kiem tra:

```bash
docker compose ps
curl -fsS http://localhost:8000/api/health
curl -fsS http://localhost:8000/api/ready
./scripts/verify_named_tunnel.sh
```

Log quan trong:

```bash
docker compose logs -f api
docker compose logs -f telegram-bot
docker compose logs -f production-worker
docker compose logs -f youtube-upload-worker
docker compose logs -f cloudflared
```

## 8. Test flow that

Trong Telegram:

```text
/start
/status
/channels
/create 1 celebrity en flag_hero --duration 90
/reviews
```

Flow dung:

1. Bot nhan lenh tao video.
2. `production-worker` render MP4.
3. Bot bao video san sang duyet.
4. Bam `Preview video`.
5. Bam `Approve and choose channel`.
6. Chon kenh YouTube.
7. `youtube-upload-worker` upload video, set thumbnail, bao link public.

## 9. Toi uu render nhanh

### Mot server don gian, on dinh

De production-worker = 1 container neu may 8 core / 32 GB RAM:

```bash
docker compose up -d production-worker
```

Chay 1 render tai mot thoi diem giup it loi Chromium/Remotion va RAM on dinh.

### Khi may manh hon

Neu may 12-16 core va 64 GB RAM, co the scale:

```bash
docker compose up -d --scale production-worker=2
```

Chi tang len 2 truoc. Neu CPU/RAM on dinh moi tang tiep. Khong nen scale qua nhanh vi moi render co the mo Chromium va dung nhieu memory.

Theo doi:

```bash
docker stats
```

Neu RAM cao hon 80% hoac swap tang manh, giam worker.

### Disk/output

Video va artifact nam trong:

```text
./output
```

Nen dat repo/output tren NVMe. Khong dung HDD. Dinh ky backup va don file cu sau khi da upload.

## 10. Backup toi thieu

Can backup:

- `.env`
- `output/reviews`
- `output/topics`
- PostgreSQL volume `pgdata`

Backup DB nhanh:

```bash
docker compose exec postgres pg_dump -U ytbot youtube_automation > backup_youtube_automation.sql
```

Restore can lam tren may rieng truoc khi dung production.

## 11. Lenh cap nhat production

Neu code da push:

```bash
git pull
docker compose up -d --build api cloudflared telegram-bot production-worker youtube-upload-worker
docker compose ps
curl -fsS http://localhost:8000/api/health
./scripts/verify_named_tunnel.sh
```

Neu co thay doi DB:

```bash
docker compose up db-migrate
docker compose up -d api cloudflared telegram-bot production-worker youtube-upload-worker
```

Neu Cloudflare token bi rotate, cap nhat `CLOUDFLARE_TUNNEL_TOKEN` trong `.env`, sau do chi recreate connector:

```bash
docker compose up -d --force-recreate cloudflared
docker compose ps cloudflared
docker compose logs --since=10m cloudflared
./scripts/verify_named_tunnel.sh
```

## 12. Checklist truoc khi san xuat hang loat

- Git server dang o branch dung va working tree sach.
- `.env` da co token Telegram, Router/AI, YouTube OAuth, encryption key.
- `PUBLIC_BASE_URL=https://studio.veo3depzai.io.vn`.
- `CLOUDFLARE_TUNNEL_TOKEN` da duoc dat va khong nam trong Git.
- `/channels` connect duoc kenh YouTube.
- `/create 1 ...` render thanh cong.
- Preview video mo inline, khong bat tai file.
- `/reviews` hien title video, khong hien ID kho doc.
- Approve bat buoc chon channel.
- Upload public thanh cong va co thumbnail.
- `docker stats` cho thay CPU/RAM on dinh.

## 13. Cau hinh de bat dau thuc te

Voi mot Windows PC manh vua:

- Docker CPU: 8
- Docker Memory: 24 GB
- Production worker replicas: 1
- Upload worker replicas: 1
- Target duration: 60-90s
- Batch moi lan: 3-5 video de theo doi chat luong

Khi da on dinh:

- Tang batch len 10 video.
- Neu render cham nhung RAM con du, scale `production-worker=2`.
- Neu upload cham, giu upload worker = 1 de tranh quota/API issue.

## 14. Native Render Runner Full HD

Native Runner chi thay the buoc Remotion/FFmpeg. API, Telegram, PostgreSQL,
Redis, review va upload van chay trong Docker. Output giu nguyen 1920x1080,
30 fps va template landscape hien tai.

### macOS Apple Silicon

Kiem tra va cai runner:

```bash
bash scripts/setup_native_render_macos.sh
python3 scripts/native_render_runner.py --check
```

Chay foreground de test:

```bash
python3 scripts/native_render_runner.py
```

Sau khi smoke thanh cong, cai LaunchAgent:

```bash
bash scripts/setup_native_render_macos.sh --install-service
tail -f output/native-render-runner.log
```

### Windows NVIDIA

Mo PowerShell Administrator:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_native_render_windows.ps1
python scripts\native_render_runner.py --check
python scripts\native_render_runner.py
```

Sau khi test foreground thanh cong:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_native_render_windows.ps1 -InstallService
Get-ScheduledTask -TaskName Y5ENativeRenderRunner
```

`--check` phai hien `h264_videotoolbox` tren Mac hoac `h264_nvenc` tren PC
NVIDIA. Neu GPU encoder loi, runner tu fallback `libx264` tru khi bat strict mode.

### Cau hinh rollout

Giu fallback trong lan dau:

```dotenv
NATIVE_RENDER_ENABLED=true
NATIVE_RENDER_FALLBACK=docker
NATIVE_RENDER_ENCODER=auto
NATIVE_RENDER_CHUNK_SECONDS=40
NATIVE_RENDER_MAX_PARALLEL_CHUNKS=2
```

Docker Compose dang expose Redis host port `6380`; `.env` cua native runner can
dung `REDIS_URL=redis://localhost:6380/0`. Cac Docker service tiep tuc duoc
override bang `redis://redis:6379/0`. Khong expose port Redis ra Internet.

### Recovery

- Runner restart: khoi dong lai cung lenh; chunk hop le duoc reuse.
- GPU encode loi: kiem tra `--check`; pipeline van fallback CPU.
- Runner mat heartbeat: control plane dung Docker renderer khi fallback la `docker`.
- Chunk loi: xem `output/topics/{topic_id}/render-cache/*/render-manifest.json` va log runner.
- Tat native khan cap: dat `NATIVE_RENDER_ENABLED=false`, restart production worker.

### Benchmark gate

Ghi lai thoi gian baseline va native tren cung mot topic, sau do chay:

```bash
python3 scripts/benchmark_native_render.py \
  --latest-topic \
  --baseline-output output/topics/BASELINE_TOPIC/final_video.mp4 \
  --native-output output/topics/NATIVE_TOPIC/final_video.mp4 \
  --baseline-seconds 1200 \
  --native-seconds 600 \
  --encoder h264_videotoolbox \
  --report output/benchmarks/native-render-macos.json
```

Chi coi native la mac dinh khi report co `rollout_gate_passed=true`, video qua
review hinh/chu/am thanh va thoi gian giam toi thieu 40% tren cung may.
