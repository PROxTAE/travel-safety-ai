# Smart Travel Assistant web

Traveler-facing Next.js 16 application for Smart Travel Assistant. It uses React
19, HeroUI 3, Tailwind CSS 4, and will communicate only with the public API.

## Phase 1

The responsive application shell, route boundaries, visual tokens, runtime public
environment validation, testing configuration, and a production standalone Docker
image are in place. The visible application routes are deliberately empty states:
they do not contain mock travel conditions, contacts, or recommendations.

Implemented routes:

- `/login`
- `/dashboard`
- `/trips/new`
- `/trips/[tripId]`
- `/trips/[tripId]/compare`
- `/safety-map`
- `/assistant/[conversationId]`
- `/emergency`
- `/api/health`

Later phases add OIDC, the generated API client, SSE, live maps, and each feature
vertical slice. See [`screen-inventory.md`](docs/screen-inventory.md) for the
screen, interaction, and contract inventory.

## Local development

Node.js 22.22+ and pnpm are required.

```bash
cd apps/web
cp .env.example .env
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

`NEXT_PUBLIC_API_BASE_URL` must point to the public API. Map configuration is
optional until the MapLibre feature is implemented. Do not use `NEXT_PUBLIC_` for
secrets.

## Verification

```bash
corepack pnpm lint
corepack pnpm typecheck
corepack pnpm test
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 corepack pnpm build
docker build --tag smart-travel-web:local apps/web
```

The Docker image runs Next standalone output as the non-root `app` user. Its
healthcheck calls `GET /api/health`, which is a web-process liveness endpoint and
does not mask public API readiness.
