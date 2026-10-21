# CI/CD

GitHub Actions runs on pushes to `main`, pull requests targeting `main`, `v*` tags,
and manual dispatches. Actions are pinned to commit hashes; Dependabot checks for
action updates weekly.

## Checks

- Gitleaks 8.30.1 scans the complete Git history with redacted output. Its executable
  archive is verified against a pinned SHA-256 checksum.
- Python 3.13 and uv 0.13.1 install `backend/uv.lock` using
  `uv sync --locked --group dev`. `uv run --no-sync pytest` runs API, unit, security,
  and labeled evaluation tests with the existing 90% coverage threshold.
- Node 22 installs the frontend lockfile with `npm ci`, runs Vitest with the existing
  90% line/branch thresholds, runs independent authentication security tests, and
  builds the production application with type checking. Production type checking
  excludes test files; Vitest executes those files separately.
- After these checks pass, Docker builds backend, frontend, Elasticsearch with IK,
  and LiteLLM gateway images. Pull requests and `main` pushes only build images.

Real-stack smoke tests are opt-in (`STACK_INTEGRATION=1`) and skipped in CI. Fixtures
use SQLite and mocked external dependencies; production credentials are unnecessary.

## Publish a version

Create a release tag on the intended `main` revision:

```bash
git tag v1.0.0
git push origin v1.0.0
```

After that revision passes all checks again, the workflow publishes:

```text
ghcr.io/nicoyazawa/clausewise-backend:v1.0.0
ghcr.io/nicoyazawa/clausewise-frontend:v1.0.0
ghcr.io/nicoyazawa/clausewise-es:v1.0.0
ghcr.io/nicoyazawa/clausewise-litellm:v1.0.0
```

Each image also receives a `sha-<commit>` tag. Publishing uses the built-in
`GITHUB_TOKEN` with `packages: write`; no personal access token or Docker Hub
credentials are required. Package visibility is managed through GitHub Packages.
This pipeline delivers images. Server deployment requires selecting infrastructure
and configuring its environment and secrets separately; no server deployment is
configured here.

## Local verification

```bash
cd backend
uv sync --locked --group dev
uv run --no-sync pytest
cd ../frontend
npm ci
npm run test -- --coverage --maxWorkers=2
node --test tests/auth-security.test.mjs
npm run build
```

## Publication privacy checks

- Runtime `.env` files, private keys, database dumps, contract storage, logs,
  coverage output, dependencies, and generated contract files are ignored.
- `backend/tests/data/` is intentionally included; only runtime `/data/` is ignored.
- Docker contexts exclude environment files and private keys as well as runtime data.
- Preset-account and initialization seed phone numbers are masked. Test literals
  exercise masking/validation. Demo credentials are public examples; preset accounts
  remain disabled by default and must stay disabled in production.
- README screenshots show the demo interface with masked contract identifiers and
  phone numbers. Screenshots and seed records contain examples, not credentials.
- The initial commit uses the account's GitHub noreply email to avoid publishing
  the locally configured private email address.

Secret scans cannot establish the provenance of business names or contract text.
Review future documents, screenshots, and seed data before committing.
