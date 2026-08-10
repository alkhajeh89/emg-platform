# EMG Studio — governed production image.
# Build context is the repository root so npm's workspace lock remains authoritative.

FROM node:22.23.2-alpine3.24@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS dependencies

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /build
COPY package.json package-lock.json ./
COPY apps/studio/package.json apps/studio/package.json
RUN npm ci --workspace @emg/studio --include-workspace-root --include=dev

FROM dependencies AS builder
ARG STUDIO_BFF_INTERNAL_URL=http://emg-studio-bff:8000
ENV STUDIO_BFF_INTERNAL_URL=${STUDIO_BFF_INTERNAL_URL}
COPY apps/studio apps/studio
RUN npm run build --workspace @emg/studio

FROM node:22.23.2-alpine3.24@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN addgroup --system --gid 10001 emg && adduser --system --uid 10001 --ingroup emg emg
WORKDIR /app

COPY --from=builder --chown=10001:10001 /build/apps/studio/.next/standalone ./
COPY --from=builder --chown=10001:10001 /build/apps/studio/.next/static ./apps/studio/.next/static

# The Node base ships npm and Next traces build-only compiled helpers. The
# standalone server does not invoke them; remove that unnecessary tooling from
# the final attack surface rather than carrying scanner-visible build packages.
RUN rm -rf \
    /usr/local/lib/node_modules/npm \
    /usr/local/lib/node_modules/corepack \
    /usr/local/bin/npm \
    /usr/local/bin/npx \
    /usr/local/bin/corepack \
    /app/node_modules/next/dist/compiled/tar

USER 10001:10001
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "apps/studio/server.js"]
