# Language API benchmark

Three small APIs provide the same signup and get-user flow:

| Runtime | Framework | Host port | Compose profile |
| --- | --- | ---: | --- |
| Node.js | Express | 3001 | `node` |
| Bun | Express | 3002 | `bun` |
| Python | FastAPI | 3003 | `python` |

Each profile starts an API with its own PostgreSQL 17 and Redis 7 containers.
The API containers all have the same Compose limits: one CPU and 512 MiB RAM.
Each API uses the same schema and behavior: signup inserts into PostgreSQL and
caches the user in Redis; get-user reads Redis first and falls back to
PostgreSQL. Cache entries expire after 60 seconds.

## Start one runtime

From this directory, build and start one profile at a time:

```sh
docker compose --profile node up --build -d
curl -s http://localhost:3001/health
docker compose --profile node down
```

Replace `node` with `bun` or `python` to test the other implementation. The
signup endpoint is `POST /users` with `{"name":"Ada","email":"ada@example.test"}`.
The response contains the new user's ID; retrieve it with `GET /users/{id}`.
Signup returns `409` if the email already exists. `GET /health` reports runtime
health.

Stopping a profile removes its containers but keeps its database volume-free
(the database is ephemeral). This gives each run a fresh database and avoids
state from prior test runs.

## Load test

With one runtime profile running, launch the matching profile plus the k6
profile. For example:

```sh
docker compose --profile node --profile load run --rm \
  -e TARGET_URL=http://node:3000 -e VUS=50 -e DURATION=60s k6 \
  run /scripts/users.js
```

Use `http://bun:3000` or `http://python:3000` and the matching Compose profile
to test the other runtimes. Adjust `VUS` and `DURATION` to run a load sweep.
k6 reports request throughput, latency, and failed checks. Each iteration
performs a signup and then retrieves that user, exercising both endpoints and
the Redis cache.

For apples-to-apples results, run one profile at a time on the same host, with
the same VU count, duration, and warm-up conditions. Record host details and
repeat runs; container startup, the database, and the cache are included in
the measured system but only the API container has the stated resource limit.

Monitor API container memory and CPU in a separate terminal while k6 runs:

```sh
docker stats
```

Memory per active request is an estimate, not a direct measurement: record
container memory at idle and under load, then divide the increase by the
number of in-flight requests. Use the same sampling interval and load level
for every runtime. Run `docker compose --profile node --profile load config`
to inspect the resolved Compose configuration before a test.
