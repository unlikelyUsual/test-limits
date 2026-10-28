import http from "k6/http";
import { check } from "k6";

export const options = {
  vus: Number(__ENV.VUS || 50),
  duration: __ENV.DURATION || "60s",
};

const baseUrl = __ENV.TARGET_URL || "http://node:3000";

export default function () {
  const email = `run-${Date.now()}-vu-${__VU}-iteration-${__ITER}@benchmark.test`;
  const created = http.post(
    `${baseUrl}/users`,
    JSON.stringify({ name: "Benchmark User", email }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(created, {
    "signup returns 201": (response) => response.status === 201,
  });

  if (created.status === 201) {
    const user = JSON.parse(created.body);
    const fetched = http.get(`${baseUrl}/users/${user.id}`);
    check(fetched, {
      "get user returns 200": (response) => response.status === 200,
      "get user returns same id": (response) =>
        JSON.parse(response.body).id === user.id,
    });
  }
}
