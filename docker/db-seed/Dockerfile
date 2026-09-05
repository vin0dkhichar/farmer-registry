# Farmer Registry — DB-seed image.
#
# Thin extension of the registry-platform db-seed base image. The base ships the
# GENERIC seeding machinery (load_geo_data.py, sync_geo_widgets.py,
# upload_templates.py, the shared openg2p-data clone). This image adds farmer's
# own content, a farmer entrypoint (AWE policies before sample data), and the
# intake-form API sample loader.
#
# WHY THE SAMPLE LOADERS LIVE HERE
#   load_sample_data.py submits complete household then farmer intake forms
#   (land before crop/livestock/inputs) and approves them as alex.carter /
#   nina.patel. Those forms and registers are declared by farmer-extension.
#
# Build context = repo root (so farmer-extension/ and docker/db-seed/ are both
# reachable).
ARG RP_VERSION=1.2.0-rc.434
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION}

# The RP db-seed image ships the reference registry's seed; clear it so only
# farmer's seed is applied.
RUN rm -rf /seed/meta_data/* /seed/awe_meta_data/* /seed/templates/* /seed/seed-data/*

COPY farmer-extension/src/openg2p_registry_farmer_extension/meta_data/     /seed/meta_data/
COPY farmer-extension/src/openg2p_registry_farmer_extension/awe_meta_data/ /seed/awe_meta_data/
COPY farmer-extension/src/openg2p_registry_farmer_extension/templates/     /seed/templates/
COPY docker/db-seed/seed-data/                                             /seed/seed-data/

COPY docker/db-seed/entrypoint.sh          /seed/entrypoint.sh
COPY docker/db-seed/load_sample_data.py    /seed/load_sample_data.py
COPY docker/db-seed/upload_images.py       /seed/upload_images.py
RUN chmod +x /seed/entrypoint.sh /seed/load_sample_data.py /seed/upload_images.py

COPY docker/db-seed/generate_fr_bulk_sample.py /seed/generate_fr_bulk_sample.py
RUN chmod +x /seed/generate_fr_bulk_sample.py
