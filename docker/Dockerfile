# CPU-only image bundling both conda envs + the CASCADE models. No GPU required.
# Pipeline scripts are vendored and working; CASCADE Pretrained_models are baked
# in at build time so a user's first run needs no internet.
#
# NOTE on scope: only the CASCADE (stage-2) models are baked. Cellpose `cpsam`
# is intentionally NOT included — segmentation/detection (stage 1) runs on the
# user's own machine in the Suite2p GUI, outside this container. Baking cpsam
# (~1.2 GB) would bloat the image with a model this container never loads. The
# canonical detection settings travel instead as settings/pipeline_settings.npy.
FROM continuumio/miniconda3:latest

WORKDIR /app

# --- Two conda envs (Suite2p is NOT here; users run detection themselves) ---
COPY envs/cascade.yml  envs/analysis.yml  /app/envs/
RUN conda env create -f /app/envs/cascade.yml && \
    conda env create -f /app/envs/analysis.yml && \
    conda clean -afy

# --- CASCADE repo + models baked in (deterministic, offline first run) ---
# The repo clone provides Pretrained_models/available_models.yaml (the model
# index run_cascade reads); bake_models.py then downloads the GC8s + GC8f models
# the pipeline routes to (~53 MB). Build has network; the resulting image does
# not need it. run_cascade expects this exact path: ~/Cascade/Pretrained_models.
RUN git clone --depth 1 https://github.com/HelmchenLabSoftware/Cascade /root/Cascade
COPY docker/bake_models.py /app/docker/bake_models.py
RUN conda run --no-capture-output -n cascade python /app/docker/bake_models.py

# --- Pipeline code ---
COPY pipeline/  /app/pipeline/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# User mounts their recording folder at /data
ENTRYPOINT ["/app/entrypoint.sh"]
