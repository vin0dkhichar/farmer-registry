# Farmer Registry — Partner API image.
#
# Thin extension of the registry-platform base image (see
# docker/staff-api/Dockerfile for the full rationale). Adds only the
# farmer domain model; ENV defaults and the migrate+gunicorn CMD are inherited.
#
# Build context = repo root (so farmer-extension/ is reachable).
ARG RP_VERSION=1.2.0-rc.434
FROM openg2p/openg2p-registry-partner-api:${RP_VERSION}

# Option C: select farmer's domain model (coexists with the base image's
# reference extension; env picks farmer, no uninstall needed).
ENV REGISTRY_EXTENSION_MODULE=openg2p_registry_farmer_extension

COPY farmer-extension/ /app/farmer-extension/
RUN pip install --no-cache-dir /app/farmer-extension
