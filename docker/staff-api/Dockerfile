# Farmer Registry — Staff Portal API image.
#
# Under the inverted build model the registry-platform publishes the base image
# (platform code + fastapi-common/iam-core runtime + entrypoint/CMD/ENV). This
# image only adds the farmer domain model on top: the farmer-extension is pip-
# installed under its own import name (openg2p_registry_farmer_extension) and
# selected at runtime by REGISTRY_EXTENSION_MODULE (Option C). ENV defaults and
# the migrate+gunicorn CMD are inherited from the base.
#
# RP_VERSION pins the openg2p-registry base image tag. Keep it in lockstep with
# the openg2p-registry chart dependency pinned in helm/openg2p-farmer-registry/Chart.yaml.
#
# Build context = repo root (so farmer-extension/ is reachable).
ARG RP_VERSION=1.2.0-rc.434
FROM openg2p/openg2p-registry-staff-api:${RP_VERSION}

# Option C: select farmer's domain model (coexists with the base image's
# reference extension; env picks farmer, no uninstall needed).
ENV REGISTRY_EXTENSION_MODULE=openg2p_registry_farmer_extension

COPY farmer-extension/ /app/farmer-extension/
RUN pip install --no-cache-dir /app/farmer-extension
