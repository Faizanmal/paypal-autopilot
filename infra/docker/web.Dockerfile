# Multi-stage Next.js production image.
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN --mount=type=cache,id=paypal-autopilot-npm,target=/root/.npm \
    npm ci --no-audit --no-fund --prefer-offline --maxsockets=5 \
    --fetch-retries=2 --fetch-timeout=120000

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Next resolves rewrites at build time. Keep this in sync with the runtime URL.
ARG API_INTERNAL_BASE_URL=http://api:8000
ENV API_INTERNAL_BASE_URL=$API_INTERNAL_BASE_URL
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
# This is a browser-visible vendor licence, not an API credential.
ARG NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY=
ENV NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY=$NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_OPTIONS=--max-old-space-size=2048
ENV RAYON_NUM_THREADS=2
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
