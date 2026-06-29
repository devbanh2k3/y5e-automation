# Cloudflare Named Tunnel Design

## Objective

Replace the temporary Cloudflare Quick Tunnel with a stable production hostname:

`https://studio.veo3depzai.io.vn`

The hostname must remain unchanged across application and server restarts so Telegram previews and Google OAuth callbacks remain dependable.

## Architecture

Use a remotely managed Cloudflare Named Tunnel named `youtube-automation-production`. A dedicated `cloudflared` Docker Compose service connects outbound to Cloudflare and forwards traffic to the internal `api:8000` service.

```text
Telegram / Google OAuth / Browser
              |
              v
studio.veo3depzai.io.vn
              |
              v
Cloudflare Named Tunnel
              |
              v
cloudflared container -> api:8000
```

No inbound router port or public server IP is required for tunnel traffic. Port `8000` may remain published for local administration, but public clients use only the HTTPS hostname.

## Configuration

The Cloudflare dashboard owns the tunnel and its public hostname route:

- Tunnel name: `youtube-automation-production`
- Public hostname: `studio.veo3depzai.io.vn`
- Origin service: `http://api:8000`

The application configuration uses:

```dotenv
PUBLIC_BASE_URL=https://studio.veo3depzai.io.vn
CLOUDFLARE_TUNNEL_TOKEN=<named-tunnel-token>
```

`CLOUDFLARE_TUNNEL_TOKEN` is secret. It is documented in `.env.example` with an empty value, stored only in the deployment `.env`, and never committed.

Google Cloud must register this exact authorized redirect URI:

`https://studio.veo3depzai.io.vn/api/youtube/oauth/callback`

## Docker Service

Docker Compose adds a `cloudflared` service using the official Cloudflare image. It runs the remotely managed tunnel with the token from `.env`, depends on the API service, and uses `restart: unless-stopped`.

The service must fail clearly when the token is absent instead of silently creating a Quick Tunnel. It must not mount Cloudflare account certificates or locally managed tunnel credentials.

## Runtime Behavior

Starting the production Compose stack starts the tunnel automatically. Restarting Docker or the Windows server reconnects the same Named Tunnel and preserves the hostname.

Cloudflare controls DNS routing for the published hostname. The application does not create or edit DNS records at runtime.

Existing YouTube refresh tokens remain valid. New channel connections and reconnections use the stable callback URL.

## Failure Handling

- Missing or invalid tunnel token: `cloudflared` exits and Docker reports the service failure; API and workers remain available locally.
- API unavailable: Cloudflare returns an origin error while `cloudflared` retries according to its built-in backoff.
- Tunnel disconnect: `cloudflared` reconnects automatically without changing the public hostname.
- Compromised token: rotate it in Cloudflare, update `.env`, and recreate only the `cloudflared` service.

## Verification

Implementation is accepted when all checks pass:

1. Compose configuration includes the `cloudflared` service and resolves successfully.
2. `cloudflared` remains running after startup with a valid token.
3. `https://studio.veo3depzai.io.vn/health` or the repository's current API health endpoint returns a successful response.
4. Telegram preview links use the stable hostname.
5. Google OAuth starts and returns through the registered stable callback.
6. Restarting `cloudflared` does not change the hostname.
7. Automated configuration tests prevent removal of the tunnel service, token variable, and stable-domain deployment documentation.

## Deployment Scope

This change includes Docker Compose integration, environment examples, production setup scripts/documentation, and runtime verification instructions. Creating the Cloudflare account, activating the DNS zone, and obtaining the initial tunnel token remain operator actions in the Cloudflare dashboard because they require account ownership.

