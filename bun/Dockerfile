FROM oven/bun:1.1.38-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN bun install --production
COPY src ./src
EXPOSE 3000
CMD ["bun", "src/server.ts"]
