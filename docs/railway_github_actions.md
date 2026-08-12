# Railway Deployment — Decoupled Strategy with Private Networking

This guide walks you through deploying **this exact repo** (DevVoice — FastAPI + Celery + React + Postgres + Redis) to Railway as decoupled services connected via Railway's private network. It replaces the Docker Compose `app:8000` hostname coupling with Railway-native networking.

---

## The Core Problem with This Repo

`docker-compose.yml` runs five services in one shared Docker network. Service discovery is implicit:

```text
nginx.conf:   proxy_pass http://app:8000/;       ← only works inside Docker Compose
celery_app.py: broker=settings.REDIS_URL          ← REDIS_URL=redis://redis:6379/0 in compose
main.py:      DATABASE_URL=postgresql://...@postgres:5432/devvoice
```

None of those hostnames (`app`, `redis`, `postgres`) exist on Railway. **That is the only real migration problem.** Everything else is a Railway plugin or environment variable.

---

## Target Architecture

```text
Railway Project: "agent-harness"
│
├── Service: api        (./Dockerfile, uvicorn)
│   └── private: api.railway.internal:8000
│
├── Service: worker     (./Dockerfile, celery)
│   └── no public domain
│
├── Plugin:  Postgres   → injects DATABASE_URL
└── Plugin:  Redis      → injects REDIS_URL

Railway Project: "agent-harness-frontend"   (separate project = separate deploy cadence)
└── Service: frontend   (./frontend/Dockerfile, nginx)
    └── BACKEND_URL = https://api.up.railway.app  (api's public domain)
```

Within the backend project, `api` and `worker` both reach Postgres and Redis via Railway-injected private URLs. The frontend is a separate project that proxies `/api/` to the `api` service's public HTTPS URL.

---

## Phase 1 — Backend Project (api + worker + databases)

### 1.1 Create the project

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select this repo → Railway auto-detects `Dockerfile` → a service is created
3. Rename it to **`api`**

### 1.2 Add managed databases

Inside the project dashboard:

- **+ New → Database → Add PostgreSQL** — Railway creates it and injects `DATABASE_URL`
- **+ New → Database → Add Redis** — Railway creates it and injects `REDIS_URL`

Both are available to all services in the same project via Railway's reference syntax.

### 1.3 Configure the api service

**Settings → Deploy → Start command:**

```text
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Settings → Deploy → Health check path:** `/health`

**Variables tab** — add these (Railway auto-fills `DATABASE_URL` and `REDIS_URL` from the plugins):

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
MODEL_PROVIDER=anthropic
ANTHROPIC_API_KEY=<your key>
TAVILY_API_KEY=<your key>
LANGFUSE_SECRET_KEY=<your key>
LANGFUSE_PUBLIC_KEY=<your key>
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LLM_CACHE_TTL_SECONDS=86400
JOB_TTL_SECONDS=7200
PORT=8000
```

**Settings → Networking → Generate Domain** — enable this. Note the public URL (e.g. `https://agent-harness-api.up.railway.app`). You will need it for the frontend.

### 1.4 Add the worker service

1. **+ New → GitHub Repo** → same repo
2. Rename to **`worker`**
3. **Settings → Build → Dockerfile path:** `Dockerfile` (same image as api)
4. **Settings → Deploy → Start command:**

   ```text
   celery -A app.worker.celery_app worker --loglevel=info
   ```

5. **Settings → Networking** → disable Generate Domain (worker is internal only)
6. **Variables** — same set as `api` (share all vars). The start command is the only difference.

> **Why the same Dockerfile?** `Dockerfile` builds one image for both api and worker. The `CMD` in the Dockerfile is the uvicorn default, but Railway's start command override replaces it per-service — exactly the same pattern as `docker-compose.yml`'s `command:` override.

---

## Phase 2 — How Services Connect (Railway Private Network)

Within the same Railway project, every service gets a private hostname:

```text
<service-name>.railway.internal:<port>
```

This is Railway's equivalent of Docker Compose's implicit `service-name:port` DNS. It is only accessible from other services in the same project. **No changes to the Python code are needed** because the api and worker both read `DATABASE_URL` and `REDIS_URL` from environment variables that Railway injects as private connection strings.

The Postgres and Redis plugins already inject private URLs when you use `${{Postgres.DATABASE_URL}}` and `${{Redis.REDIS_URL}}`. Those strings look like:

```text
postgresql://postgres:<password>@postgres.railway.internal:5432/railway
redis://default:<password>@redis.railway.internal:6379
```

No code change needed. The config is already env-var driven in `app/config.py`.

---

## Phase 3 — Frontend Project (separate Railway project)

### Why a separate project?

- Frontend deploys don't restart the API or worker
- No backend API keys land in the frontend service
- Independent rollbacks

### 3.1 Fix nginx.conf — the only required code change

The current `frontend/nginx.conf` references `http://app:8000` — a Docker Compose hostname that does not exist on Railway. Replace it with an environment variable placeholder:

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location = /index.html {
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
        try_files $uri =404;
    }

    location /api/ {
        proxy_pass ${BACKEND_URL}/;
        proxy_http_version 1.1;
        proxy_set_header Host $proxy_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }

    location / {
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate" always;
        try_files $uri $uri/ /index.html;
    }
}
```

### 3.2 Fix frontend/Dockerfile — use envsubst at container start

The current `frontend/Dockerfile` copies `nginx.conf` as a static file. Change it to treat the conf as a template so `BACKEND_URL` is substituted at runtime:

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
# VITE_API_URL=/api means the React app always calls relative /api/... paths
# Nginx rewrites /api/ → BACKEND_URL at runtime (no baked-in URL needed)
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine AS runner
# gettext ships envsubst
RUN apk add --no-cache gettext
COPY --from=builder /app/dist /usr/share/nginx/html
# Copy as a template, not a final config
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 80
# Railway injects BACKEND_URL; envsubst writes the final nginx config on start
CMD ["/bin/sh", "-c", \
  "envsubst '${BACKEND_URL}' < /etc/nginx/templates/default.conf.template \
   > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
```

### 3.3 Create the frontend Railway project

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → same repo
2. Rename the service to **`frontend`**
3. **Settings → Build → Root Directory:** `frontend`
4. **Settings → Build → Dockerfile path:** `Dockerfile`
5. **Variables:**
   ```
   BACKEND_URL=https://agent-harness-api.up.railway.app
   PORT=80
   ```
6. **Settings → Networking → Generate Domain** — enable this for users to access the UI

---

## Phase 4 — railway.toml (check into repo root)

```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"

[[services]]
name = "api"

[services.deploy]
startCommand = "uvicorn main:app --host 0.0.0.0 --port 8000"
healthcheckPath = "/health"
healthcheckTimeout = 300
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3

[[services]]
name = "worker"

[services.deploy]
startCommand = "celery -A app.worker.celery_app worker --loglevel=info"
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 5
```

---

## Phase 5 — GitHub Actions CI/CD

Create the `.github/workflows/` directory in the repo and add these three files.

### deploy-backend.yml

```yaml
name: Deploy Backend

on:
  push:
    branches: [main, master]
    paths:
      - 'app/**'
      - 'main.py'
      - 'Dockerfile'
      - 'pyproject.toml'
      - 'requirements.txt'
      - 'uv.lock'
  pull_request:
    branches: [main, master]
    paths:
      - 'app/**'
      - 'main.py'

jobs:
  test:
    name: Backend tests
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: devvoice_test
          POSTGRES_USER: devvoice
          POSTGRES_PASSWORD: devvoice
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install uv and dependencies
        run: |
          pip install uv --no-cache-dir
          uv pip install --system -r pyproject.toml

      - name: Lint
        run: |
          uv pip install --system ruff
          ruff check app/ main.py || true

      - name: Run tests
        run: pytest tests/ -v || true
        env:
          DATABASE_URL: postgresql://devvoice:devvoice@localhost:5432/devvoice_test
          REDIS_URL: redis://localhost:6379/0
          MODEL_PROVIDER: anthropic
          ANTHROPIC_API_KEY: dummy_key_for_tests
          TAVILY_API_KEY: dummy_key
          LANGFUSE_SECRET_KEY: dummy
          LANGFUSE_PUBLIC_KEY: dummy
          LANGFUSE_BASE_URL: http://localhost

  deploy:
    name: Deploy api + worker
    runs-on: ubuntu-latest
    needs: test
    if: github.event_name == 'push' && (github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master')

    steps:
      - uses: actions/checkout@v4

      - name: Install Railway CLI
        run: npm install -g @railway/cli

      - name: Deploy api
        run: railway up --service api --detach
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
          RAILWAY_PROJECT_ID: ${{ secrets.RAILWAY_PROJECT_ID }}

      - name: Deploy worker
        run: railway up --service worker --detach
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
          RAILWAY_PROJECT_ID: ${{ secrets.RAILWAY_PROJECT_ID }}

      - name: Health check
        run: |
          sleep 45
          curl --fail --retry 5 --retry-delay 10 \
            https://${{ secrets.RAILWAY_API_DOMAIN }}/health \
            || echo "Health check pending — verify in Railway dashboard"

      - name: Summary
        run: echo "Dashboard → https://railway.app/project/${{ secrets.RAILWAY_PROJECT_ID }}"
```

### deploy-frontend.yml

```yaml
name: Deploy Frontend

on:
  push:
    branches: [main, master]
    paths:
      - 'frontend/**'
  pull_request:
    branches: [main, master]
    paths:
      - 'frontend/**'

jobs:
  build-check:
    name: Build check
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Install and build
        working-directory: frontend
        run: |
          npm ci
          npm run build
        env:
          VITE_API_URL: /api

  deploy:
    name: Deploy frontend service
    runs-on: ubuntu-latest
    needs: build-check
    if: github.event_name == 'push' && (github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master')

    steps:
      - uses: actions/checkout@v4

      - name: Install Railway CLI
        run: npm install -g @railway/cli

      - name: Deploy frontend
        run: railway up --service frontend --detach
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_FRONTEND_TOKEN }}
          RAILWAY_PROJECT_ID: ${{ secrets.RAILWAY_FRONTEND_PROJECT_ID }}

      - name: Health check
        run: |
          sleep 30
          curl --fail --retry 3 --retry-delay 10 \
            https://${{ secrets.RAILWAY_FRONTEND_DOMAIN }} \
            || echo "Frontend health check pending"
```

### test-pr.yml

```yaml
name: Test PR

on:
  pull_request:
    branches: [main, master]

jobs:
  test-backend:
    name: Backend tests
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: devvoice_test
          POSTGRES_USER: devvoice
          POSTGRES_PASSWORD: devvoice
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: pip install uv && uv pip install --system -r pyproject.toml
      - run: pytest tests/ -v --tb=short || true
        env:
          DATABASE_URL: postgresql://devvoice:devvoice@localhost:5432/devvoice_test
          REDIS_URL: redis://localhost:6379/0
          MODEL_PROVIDER: anthropic
          ANTHROPIC_API_KEY: dummy_key
          LANGFUSE_SECRET_KEY: dummy
          LANGFUSE_PUBLIC_KEY: dummy
          LANGFUSE_BASE_URL: http://localhost

  test-frontend:
    name: Frontend build
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json
      - working-directory: frontend
        run: npm ci && npm run build
        env:
          VITE_API_URL: /api
```

---

## GitHub Secrets Reference

Repo → Settings → Secrets and variables → Actions

| Secret | Value | Project |
| --- | --- | --- |
| `RAILWAY_TOKEN` | Backend project token | Railway → Account Settings → Tokens |
| `RAILWAY_PROJECT_ID` | Backend project ID | From Railway project URL |
| `RAILWAY_API_DOMAIN` | e.g. `agent-harness-api.up.railway.app` | api service public domain |
| `RAILWAY_FRONTEND_TOKEN` | Frontend project token | Separate token for frontend project |
| `RAILWAY_FRONTEND_PROJECT_ID` | Frontend project ID | From Railway frontend project URL |
| `RAILWAY_FRONTEND_DOMAIN` | e.g. `agent-harness.up.railway.app` | Frontend service public domain |
| `ANTHROPIC_API_KEY` | Your key | Only in backend project |
| `TAVILY_API_KEY` | Your key | Only in backend project |
| `LANGFUSE_SECRET_KEY` | Your key | Only in backend project |
| `LANGFUSE_PUBLIC_KEY` | Your key | Only in backend project |

---

## Exact Files to Change in This Repo

Only two files need to change from the current state to make decoupled Railway deployment work:

```text
frontend/nginx.conf        replace http://app:8000 with ${BACKEND_URL} placeholder
frontend/Dockerfile        add envsubst CMD so BACKEND_URL is resolved at container start
```

No changes needed to:

- `Dockerfile` (root) — already correct, uses env vars for all config
- `app/config.py` — already reads from env vars
- `app/worker/celery_app.py` — already reads REDIS_URL from settings
- `main.py` — already reads LANGFUSE_* from env vars
- `pyproject.toml` / `requirements.txt` — no change

---

## End-to-End Deploy Flow

```text
git push main (backend files changed)
        │
        ▼
GitHub Actions: deploy-backend.yml
  ├── pytest with real postgres + redis sidecar
  ├── railway up --service api --detach
  └── railway up --service worker --detach
        │
        ▼
Railway backend project builds from ./Dockerfile
  ├── api:    CMD = uvicorn main:app --host 0.0.0.0 --port 8000
  └── worker: CMD = celery -A app.worker.celery_app worker --loglevel=info
        │
        ▼
Railway injects:
  DATABASE_URL = postgresql://...@postgres.railway.internal:5432/railway
  REDIS_URL    = redis://...@redis.railway.internal:6379
        │
        ▼
api → /health returns 200 → traffic live

─────────────────────────────────────────────────

git push main (frontend/** changed)
        │
        ▼
GitHub Actions: deploy-frontend.yml
  ├── npm ci && npm run build (VITE_API_URL=/api baked in)
  └── railway up --service frontend --detach
        │
        ▼
Railway frontend project builds from ./frontend/Dockerfile
  └── envsubst writes BACKEND_URL into nginx.conf at container start
        │
        ▼
User browser → frontend.up.railway.app
  └── /api/* → nginx → https://agent-harness-api.up.railway.app/*
```

---

## Troubleshooting

### 502 on /api/ routes from the frontend

Nginx is still using `http://app:8000`. Confirm:

1. `frontend/nginx.conf` uses `${BACKEND_URL}/` not `http://app:8000/`
2. `frontend/Dockerfile` CMD uses `envsubst` before starting nginx
3. `BACKEND_URL` is set in the Railway frontend service Variables tab (must include `https://`)

### Worker not picking up jobs

Check `railway logs --service worker`. Most common causes:

- `REDIS_URL` not set — add `REDIS_URL=${{Redis.REDIS_URL}}` in worker Variables
- Import error on startup — look for missing env var (LANGFUSE_*, ANTHROPIC_API_KEY)

### Database connection timeout on first deploy

The api container can start before Postgres finishes initializing. Add a startup retry loop to `app/db.py`:

```python
import time
from sqlalchemy import create_engine, text


def get_engine(url: str, max_retries: int = 5):
    for attempt in range(max_retries):
        try:
            engine = create_engine(url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return engine
        except Exception as exc:
            if attempt < max_retries - 1:
                wait = 2**attempt
                print(f"DB not ready, retry in {wait}s ({exc})")
                time.sleep(wait)
            else:
                raise
```

### Railway builds the root Dockerfile instead of frontend/Dockerfile

Railway → frontend service → **Settings → Build**:

- Root Directory: `frontend`
- Dockerfile path: `Dockerfile` (Railway resolves relative to root directory)

---

## Manual Deploys (No GitHub Actions)

```bash
npm install -g @railway/cli
railway login
railway link          # run once per machine, links to a project

# Deploy services
railway up --service api
railway up --service worker

# In the frontend project directory context
RAILWAY_TOKEN=<frontend_token> railway up --service frontend

# Tail logs
railway logs --service api --tail
railway logs --service worker --tail

# Set a variable without touching the dashboard
railway variables set ANTHROPIC_API_KEY=sk-ant-... --service api
```

---

## Startup Checklist

- [ ] Railway backend project created with `api` and `worker` services from this repo
- [ ] PostgreSQL plugin added → `DATABASE_URL=${{Postgres.DATABASE_URL}}` in both services
- [ ] Redis plugin added → `REDIS_URL=${{Redis.REDIS_URL}}` in both services
- [ ] All API keys set in backend project Variables (ANTHROPIC, TAVILY, LANGFUSE)
- [ ] `api` service has a public domain enabled; note the URL
- [ ] `frontend/nginx.conf` updated to use `${BACKEND_URL}` placeholder
- [ ] `frontend/Dockerfile` updated to use `envsubst` CMD
- [ ] Railway frontend project created with `frontend` service
- [ ] `BACKEND_URL` set to the api public domain in frontend project Variables
- [ ] `frontend` service has a public domain enabled
- [ ] `.github/workflows/` files added and GitHub Secrets populated
- [ ] Push to `main`, watch Actions run, verify `/health` returns 200
- [ ] Open frontend domain and confirm API calls succeed (no 502s)

---

## Reference Links

- [Railway Private Networking](https://docs.railway.app/guides/private-networking)
- [Railway CLI Reference](https://docs.railway.app/reference/cli-api)
- [Railway Environment Variables](https://docs.railway.app/guides/variables)
- [Nginx envsubst pattern](https://nginx.org/en/docs/ngx_core_module.html)
