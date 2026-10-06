# Screenshot fixtures

The public screenshots are rendered from the real React application with a
fully synthetic, deterministic API fixture. The screenshot container does not
start the backend, connect to a database, or read a local finsight volume.

Regenerate every image from the repository root:

```bash
docker compose -f docker-compose.screenshots.yml run --build --rm screenshots
```

Review the generated files before committing them. Update
`frontend/screenshots/fixtures.ts` when a new screen needs additional API data.
