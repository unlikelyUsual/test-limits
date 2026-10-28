import json
import os
import re
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis


class UserInput(BaseModel):
    name: str = Field(min_length=1)
    email: str = Field(min_length=1)


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    created_at: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    app.state.redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await app.state.redis.ping()
    app.state.cache_ttl = int(os.getenv("CACHE_TTL_SECONDS", "60"))
    yield
    await app.state.redis.aclose()
    await app.state.pool.close()


app = FastAPI(lifespan=lifespan)
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@app.exception_handler(HTTPException)
async def handle_http_error(_request: Request, error: HTTPException):
    return JSONResponse(
        status_code=error.status_code,
        content={"error": str(error.detail)},
        headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, _error: RequestValidationError):
    message = (
        "name and email are required"
        if request.url.path == "/users"
        else "invalid user id"
    )
    return JSONResponse(status_code=400, content={"error": message})


@app.get("/health")
async def health():
    return {"status": "ok", "runtime": "python"}


@app.post("/users", response_model=User, status_code=201)
async def create_user(user_input: UserInput):
    name = user_input.name.strip()
    email = user_input.email.strip().lower()
    if not name or not email:
        raise HTTPException(status_code=400, detail="name and email are required")

    user_id = uuid4()
    try:
        async with app.state.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO users (id, name, email)
                VALUES ($1, $2, $3)
                RETURNING id, name, email, created_at
                """,
                user_id,
                name,
                email,
            )
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status_code=409, detail="email already exists") from error

    result = dict(row)
    result["id"] = str(result["id"])
    result["created_at"] = result["created_at"].isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    await app.state.redis.set(
        f"user:{user_id}", json.dumps(result), ex=app.state.cache_ttl
    )
    return result


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    if not UUID_PATTERN.fullmatch(user_id):
        raise HTTPException(status_code=400, detail="invalid user id")
    try:
        parsed_user_id = UUID(user_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="invalid user id") from error

    cache_key = f"user:{user_id}"
    cached = await app.state.redis.get(cache_key)
    if cached:
        return json.loads(cached)

    async with app.state.pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT id, name, email, created_at FROM users WHERE id = $1",
            parsed_user_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")

    result = dict(row)
    result["id"] = str(result["id"])
    result["created_at"] = result["created_at"].isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    await app.state.redis.set(
        cache_key, json.dumps(result), ex=app.state.cache_ttl
    )
    return result
