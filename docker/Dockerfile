# CPU-only image bundling both conda envs + models. No GPU required.
# SKELETON — fill in once the pipeline scripts are done.
FROM continuumio/miniconda3:latest

WORKDIR /app

# --- Two conda envs (Suite2p is NOT here; users run it themselves) ---
COPY envs/cascade.yml  envs/analysis.yml  /app/envs/
RUN conda env create -f /app/envs/cascade.yml && \
    conda env create -f /app/envs/analysis.yml && \
    conda clean -afy

# --- Bake in models so first run needs no internet (deterministic) ---
# TODO: download CASCADE Pretrained_models and Cellpose cpsam at build time.
# RUN <fetch CASCADE Pretrained_models into /root/Cascade/Pretrained_models>
# RUN <fetch Cellpose cpsam into /root/.cellpose/models>

# --- Pipeline code ---
COPY pipeline/  /app/pipeline/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# User mounts their recording folder at /data
ENTRYPOINT ["/app/entrypoint.sh"]
