# Contributing

finsight is an early local-first finance prototype. Small, understandable
changes that improve reliability and privacy are especially welcome.

## Development

Follow the [setup instructions](README.md#getting-started), then start the development stack:

```bash
docker compose -f docker-compose-dev.yml up --build
```

On macOS/Linux, set `USER_ID` and `GROUP_ID` in `.env` to the output of `id -u`
and `id -g` for correct ownership of mounted files. Development and production
use separate database volumes.

Run checks inside the development container:

```bash
docker compose -f docker-compose-dev.yml exec finsight-dev \
  sh -c 'cd backend && python -m pytest -q'
docker compose -f docker-compose-dev.yml exec finsight-dev \
  sh -c 'cd frontend && npm run build'
```

With dependencies installed locally, the equivalent checks are:

```bash
python -m compileall -q backend/app backend/tests
PYTHONPATH=backend python -m pytest -q backend/tests
npm --prefix frontend ci
npm --prefix frontend run build
npm --prefix frontend audit --omit=dev --audit-level=high
docker compose -f docker-compose-dev.yml config --quiet
docker compose config --quiet
(cd fints-gateway && mvn --batch-mode --strict-checksums verify)
```

## Version

The product version lives in `version.json`. The frontend `package.json` and
the FinTS gateway `pom.xml` must use that same version; a backend test fails
if they drift. Dependency versions, such as npm packages, Spring Boot and
HBCI4Java, stay independent of the product version.

## Pull requests

- Write code, comments, prompts, documentation and commit messages in English.
  Put translated interface text in the i18next locale files. Provider data and
  protocol-matching terms must preserve the original spelling.
- Describe the problem, the resulting behavior and how you checked it.
- Never commit real financial data, credentials, debug logs or `.env` files.
- Include migrations for schema changes and update relevant documentation.
- Check UI changes on both mobile and desktop.
- Explain new dependencies and preserve their license and integrity information.

Use synthetic data when testing encryption, sync and financial calculations.
Report vulnerabilities as described in [SECURITY.md](SECURITY.md).
