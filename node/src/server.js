import { randomUUID } from "node:crypto";
import express from "express";
import pg from "pg";
import { createClient } from "redis";

const { Pool } = pg;
const port = Number(process.env.PORT ?? 3000);
const cacheTtl = Number(process.env.CACHE_TTL_SECONDS ?? 60);
const pool = new Pool({ connectionString: process.env.DATABASE_URL });
const redis = createClient({ url: process.env.REDIS_URL });
redis.on("error", (error) => console.error("Redis client error:", error));

const app = express();
app.use(express.json({ limit: "16kb" }));

app.get("/health", (_request, response) => {
  response.json({ status: "ok", runtime: "node" });
});

app.post("/users", async (request, response, next) => {
  const { name, email } = request.body ?? {};
  if (
    typeof name !== "string" ||
    !name.trim() ||
    typeof email !== "string" ||
    !email.trim()
  ) {
    return response.status(400).json({ error: "name and email are required" });
  }

  const id = randomUUID();
  try {
    const result = await pool.query(
      "INSERT INTO users (id, name, email) VALUES ($1, $2, $3) RETURNING id, name, email, created_at",
      [id, name.trim(), email.trim().toLowerCase()],
    );
    const user = result.rows[0];
    await redis.set(`user:${id}`, JSON.stringify(user), { EX: cacheTtl });
    return response.status(201).json(user);
  } catch (error) {
    if (error?.code === "23505") {
      return response.status(409).json({ error: "email already exists" });
    }
    return next(error);
  }
});

app.get("/users/:id", async (request, response, next) => {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(request.params.id)) {
    return response.status(400).json({ error: "invalid user id" });
  }

  try {
    const cached = await redis.get(`user:${request.params.id}`);
    if (cached) return response.json(JSON.parse(cached));

    const result = await pool.query(
      "SELECT id, name, email, created_at FROM users WHERE id = $1",
      [request.params.id],
    );
    if (result.rowCount === 0) return response.status(404).json({ error: "user not found" });

    const user = result.rows[0];
    await redis.set(`user:${user.id}`, JSON.stringify(user), { EX: cacheTtl });
    return response.json(user);
  } catch (error) {
    return next(error);
  }
});

app.use((error, _request, response, _next) => {
  console.error("Request failed:", error);
  response.status(500).json({ error: "internal server error" });
});

async function start() {
  await redis.connect();
  await pool.query("SELECT 1");
  app.listen(port, "0.0.0.0", () => {
    console.log(`node API listening on ${port}`);
  });
}

start().catch((error) => {
  console.error("Failed to start node API:", error);
  process.exitCode = 1;
});

async function shutdown() {
  await Promise.all([pool.end(), redis.isOpen ? redis.quit() : Promise.resolve()]);
  process.exit(0);
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
