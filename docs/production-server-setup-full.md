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

PUBLIC_BASE_URL=https://your-public-domain-or-cloudflare-tunnel

YOUTUBE_UPLOAD_ENABLED=true
YOUTUBE_OAUTH_CLIENT_ID=your_google_oauth_client_id
YOUTUBE_OAUTH_CLIENT_SECRET=your_google_oauth_client_secret
YOUTUBE_OAUTH_CALLBACK_PATH=/api/youtube/oauth/callback
YOUTUBE_TOKEN_ENCRYPTION_KEY=your_fernet_key

STORAGE_PATH=./output
LOG_LEVEL=INFO
```

Tao `YOUTUBE_TOKEN_ENCRYPTION_KEY`:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Khong commit `.env`.

## 5. Cloudflare Quick Tunnel tam thoi

Dung khi chua co domain rieng.

Tren may server:

```bash
cloudflared tunnel --url http://localhost:8000
```

Copy URL dang:

```text
https://xxxxx.trycloudflare.com
```

Gan vao `.env`:

```env
PUBLIC_BASE_URL=https://xxxxx.trycloudflare.com
```

Sau do restart service:

```bash
docker compose up -d --build api telegram-bot production-worker youtube-upload-worker
```

Luu y: Quick Tunnel co the doi URL moi lan chay. Khi URL doi, Google OAuth redirect URI cung phai cap nhat.

## 6. Google OAuth / YouTube upload

Trong Google Cloud Console:

1. Tao project.
2. Enable `YouTube Data API v3`.
3. Tao OAuth Client.
4. Authorized redirect URI:

```text
https://your-public-base-url/api/youtube/oauth/callback
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
```

Log quan trong:

```bash
docker compose logs -f api
docker compose logs -f telegram-bot
docker compose logs -f production-worker
docker compose logs -f youtube-upload-worker
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
docker compose up -d --build api telegram-bot production-worker youtube-upload-worker
docker compose ps
curl -fsS http://localhost:8000/api/health
```

Neu co thay doi DB:

```bash
docker compose up db-migrate
docker compose up -d api telegram-bot production-worker youtube-upload-worker
```

## 12. Checklist truoc khi san xuat hang loat

- Git server dang o branch dung va working tree sach.
- `.env` da co token Telegram, Router/AI, YouTube OAuth, encryption key.
- `PUBLIC_BASE_URL` la HTTPS public URL.
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
