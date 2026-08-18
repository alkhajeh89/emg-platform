FROM golang:1.25-alpine@sha256:1e0126852075c9c60731c8ba49088448b91f63e2aed97ca9d1a9791622a05946 AS build

WORKDIR /build
COPY services/recovery-authority/go.mod services/recovery-authority/go.sum ./
RUN go mod download
COPY services/recovery-authority/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/recovery-signer ./cmd/recovery-signer

FROM alpine:3.22@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce AS runtime
RUN apk add --no-cache ca-certificates \
    && addgroup -g 10001 emg \
    && adduser -D -H -u 10001 -G emg emg
COPY --from=build /out/recovery-signer /usr/local/bin/recovery-signer
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/recovery-signer"]
