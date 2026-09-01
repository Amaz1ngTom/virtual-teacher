#!/usr/bin/env bash
set -euo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/config.sh"
if [[ ! "${PHYSICAL_GPU}" =~ ^[0-9]+$ ]]; then
  echo 'Set PHYSICAL_GPU in worker.env to your assigned physical GPU index.' >&2
  exit 1
fi

if [[ -n "${CONDA_SH:-}" && -f "${CONDA_SH}" ]]; then
  source "${CONDA_SH}"
elif command -v conda >/dev/null 2>&1; then
  eval "$(conda shell.bash hook)"
elif [[ -f /opt/conda/etc/profile.d/conda.sh ]]; then
  source /opt/conda/etc/profile.d/conda.sh
elif [[ -f /root/miniconda3/etc/profile.d/conda.sh ]]; then
  source /root/miniconda3/etc/profile.d/conda.sh
elif [[ -f /root/anaconda3/etc/profile.d/conda.sh ]]; then
  source /root/anaconda3/etc/profile.d/conda.sh
else
  echo "找不到 conda。请先在当前 shell 中确认 source activate ${FLOAT_ENV} 可用。" >&2
  exit 1
fi

conda activate "${FLOAT_ENV}"

mkdir -p \
  "${WORKER_ROOT}/inputs" \
  "${WORKER_ROOT}/outputs" \
  "${WORKER_ROOT}/runtime" \
  "${WORKER_ROOT}/logs"

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="${PHYSICAL_GPU}"
export NO_ALBUMENTATIONS_UPDATE=1

cd "${FLOAT_ROOT}"
exec python "${WORKER_ROOT}/server.py" \
  --float-root "${FLOAT_ROOT}" \
  --checkpoint "${FLOAT_ROOT}/checkpoints/float.pth" \
  --reference-image "${WORKER_ROOT}/assets/teacher.png" \
  --audio-root "${WORKER_ROOT}/inputs" \
  --reference-root "${WORKER_ROOT}/assets" \
  --output-dir "${WORKER_ROOT}/outputs" \
  --runtime-dir "${WORKER_ROOT}/runtime" \
  --upload-dir "${WORKER_ROOT}/inputs" \
  --cuda-visible-devices "${PHYSICAL_GPU}" \
  --host 127.0.0.1 \
  --port "${WORKER_PORT}"
