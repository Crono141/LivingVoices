#!/usr/bin/env bash
# card 1 only; the venv's CUDA libs
cd "$(dirname "$0")/../data"
SP=$(echo ../.venv/lib/python3*/site-packages)
export CUDA_VISIBLE_DEVICES=1 LD_LIBRARY_PATH=$SP/nvidia/cublas/lib:$SP/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}
exec ../.venv/bin/python -W ignore ../tools/asr_check.py "$@"
