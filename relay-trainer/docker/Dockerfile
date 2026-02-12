FROM docker.io/pytorch/pytorch:2.9.1-cuda12.8-cudnn9-devel

WORKDIR /workspace/slime/relay-trainer

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y git libnuma1 python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Avoid PEP 668 "externally managed" issues, while reusing the base image's PyTorch install.
RUN python -m venv --system-site-packages /root/venv
ENV PATH=/root/venv/bin:$PATH

# Copy the whole repo so the image uses the *local* slime + relay-trainer sources.
COPY . /workspace/slime

# Install Slime + relay-trainer deps (Ray/Transformers/etc). Keep torch from base image.
RUN python -m pip install --no-cache-dir -U pip \
    && python -m pip install --no-cache-dir -e /workspace/slime \
    && python -m pip install --no-cache-dir -e /workspace/slime/relay-trainer

# SGLang runtime: install without deps to avoid clobbering the base image's
# `torch==2.9.1+cu128` with CPU / non-local-version wheels.
RUN python -m pip install --no-cache-dir --no-deps "sglang==0.5.8.post1" \
    && python -m pip install --no-cache-dir --no-deps \
      "sgl-kernel==0.3.21" \
      "flashinfer_python==0.6.1" \
      "flashinfer_cubin==0.6.1" \
      "cuda-python==12.9" \
      "torch_memory_saver==0.0.9" \
      "torchao==0.9.0" \
    && python -m pip install --no-cache-dir \
      "einops==0.8.2" \
      "tabulate==0.9.0" \
      "nvidia-ml-py==13.590.48" \
      "pybase64" \
      "pyzmq>=25.1.2" \
      "msgspec" \
      "interegular" \
      "partial_json_parser" \
      "sentencepiece" \
      "tiktoken" \
      "uvloop" \
      "apache-tvm-ffi==0.1.8.post2" \
      "nvidia-cudnn-frontend==1.18.0" \
      "nvidia-cutlass-dsl==4.3.5" \
      "openai==2.6.1" \
      "openai-harmony==0.0.4" \
      "transformers==4.57.1" \
      "blobfile==3.0.0" \
      "grpcio==1.75.1" \
      "grpcio-health-checking==1.75.1" \
      "grpcio-reflection==1.75.1" \
      "grpcio-tools==1.75.1" \
      "compressed-tensors==0.13.0" \
      "gguf==0.17.1" \
      "hf_transfer==0.1.9" \
      "llguidance==0.7.11" \
      "outlines==0.1.11" \
      "quack-kernels==0.2.4" \
      "scipy==1.17.0" \
      "soundfile==0.13.1" \
      "timm==1.0.16" \
      "torchcodec==0.8.0" \
      "xgrammar==0.1.27" \
      "anthropic==0.79.0" \
      "modelscope==1.34.0" \
      "decord2==3.0.0"

RUN chmod +x docker/entrypoint.sh trainer_blackbox/launch_sft.sh trainer_blackbox/launch_rl.sh \
    && chmod +x lium_real_test/run_sft.sh lium_real_test/run_rl.sh

ENTRYPOINT ["bash", "docker/entrypoint.sh"]
