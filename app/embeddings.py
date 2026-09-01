from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Iterable

import numpy as np


BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class LocalBGEEmbedder:
    """Lazy local BGE encoder using the already installed Transformers stack."""

    def __init__(
        self,
        model_path: Path,
        *,
        device: str = "cpu",
        batch_size: int = 8,
        max_length: int = 512,
    ):
        self.model_path = model_path.resolve()
        self.device = device.strip().lower() or "cpu"
        self.batch_size = max(1, min(64, int(batch_size)))
        self.max_length = max(64, min(512, int(max_length)))
        self.model_name = self.model_path.name
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._lock = Lock()

    @property
    def available(self) -> bool:
        return (
            (self.model_path / "config.json").is_file()
            and (self.model_path / "model.safetensors").is_file()
            and (self.model_path / "tokenizer.json").is_file()
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.available:
            raise FileNotFoundError(f"本地Embedding模型不完整：{self.model_path}")
        with self._lock:
            if self._model is not None:
                return
            import torch
            from transformers import AutoModel, AutoTokenizer

            if self.device.startswith("cuda") and not torch.cuda.is_available():
                raise RuntimeError("配置了CUDA语义检索，但当前PyTorch无法使用CUDA")
            tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_path), local_files_only=True, trust_remote_code=False
            )
            model = AutoModel.from_pretrained(
                str(self.model_path), local_files_only=True, trust_remote_code=False
            )
            model.to(self.device)
            model.eval()
            self._torch = torch
            self._tokenizer = tokenizer
            self._model = model

    def encode(self, texts: Iterable[str], *, is_query: bool = False) -> np.ndarray:
        values = [str(text).strip() for text in texts]
        if not values:
            return np.empty((0, 0), dtype=np.float32)
        if is_query:
            values = [f"{BGE_QUERY_INSTRUCTION}{text}" for text in values]
        self._load()
        assert self._torch is not None
        assert self._tokenizer is not None
        assert self._model is not None

        batches: list[np.ndarray] = []
        with self._lock, self._torch.inference_mode():
            for start in range(0, len(values), self.batch_size):
                encoded = self._tokenizer(
                    values[start:start + self.batch_size],
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                output = self._model(**encoded).last_hidden_state[:, 0]
                output = self._torch.nn.functional.normalize(output, p=2, dim=1)
                batches.append(output.detach().float().cpu().numpy())
        return np.concatenate(batches, axis=0).astype(np.float32, copy=False)
