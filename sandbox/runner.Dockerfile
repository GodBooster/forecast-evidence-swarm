# Runner image for the local NEAR Sandbox harness. Built once by sandbox/run.sh.
# Adds only the native build inputs that near-workspaces' dependency tree needs
# (openssl-sys wants pkg-config + libssl headers). No wallets, keys or project
# files are baked in; the repository is bind-mounted at run time.
# trixie (glibc 2.41) is required: the near-sandbox 2.14.0 node binary links glibc 2.39 symbols.
ARG BASE_IMAGE=rust:1.99-slim-trixie
FROM ${BASE_IMAGE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends pkg-config libssl-dev ca-certificates \
 && rm -rf /var/lib/apt/lists/*
