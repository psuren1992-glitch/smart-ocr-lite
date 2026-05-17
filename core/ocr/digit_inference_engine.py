import json
import logging
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
import torch
from torch import nn

from core.interfaces.ocr_engine import BaseOcrEngine
from core.models.data_models import OcrHypothesis

logger = logging.getLogger(__name__)


class DigitCnn(nn.Module):
    def __init__(self, num_classes: int):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64 * 4 * 4, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(p=0.15),
            nn.Linear(128, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        return self.classifier(x)


class DigitInferenceEngine(BaseOcrEngine):
    def __init__(
        self,
        model_path: str,
        device: str = "auto",
        engine_name: str = "digit_model",
        min_confidence: float = 0.60,
    ):
        super().__init__(engine_name=engine_name)
        self.model_path = Path(model_path).resolve()
        self.device = self._resolve_device(device)
        self.min_confidence = min_confidence
        self.model: Optional[DigitCnn] = None
        self.labels: List[str] = []
        self.image_size = 32
        self.enabled = False
        self._load()

    def _resolve_device(self, device: str) -> torch.device:
        if device == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return torch.device(device)

    def _load(self) -> None:
        if not self.model_path.exists():
            logger.warning("DigitInferenceEngine: модель не найдена: %s", self.model_path)
            return

        try:
            checkpoint = torch.load(self.model_path, map_location=self.device)
            labels = checkpoint.get("labels", [])
            if not labels:
                labels_path = self.model_path.with_name("labels.json")
                if labels_path.exists():
                    labels = json.loads(labels_path.read_text(encoding="utf-8"))
            if not labels:
                raise ValueError("Не найден labels в checkpoint или labels.json")

            self.labels = list(labels)
            self.image_size = int(checkpoint.get("image_size", 32))
            self.model = DigitCnn(num_classes=len(self.labels))
            self.model.load_state_dict(checkpoint["model_state_dict"])
            self.model.to(self.device)
            self.model.eval()
            self.enabled = True
            logger.info(
                "DigitInferenceEngine: модель загружена: %s, labels=%d, image_size=%d, device=%s",
                self.model_path,
                len(self.labels),
                self.image_size,
                self.device,
            )
        except Exception as exc:
            logger.error("DigitInferenceEngine: ошибка загрузки модели %s: %s", self.model_path, exc)
            self.enabled = False

    def _prepare_tensor(self, processed_image: np.ndarray) -> Optional[torch.Tensor]:
        if processed_image is None or processed_image.size == 0:
            return None

        foreground_ratio = float(cv2.countNonZero(processed_image)) / float(processed_image.size)
        if foreground_ratio <= 0.0:
            return None

        resized = cv2.resize(processed_image, (self.image_size, self.image_size), interpolation=cv2.INTER_AREA)
        image = resized.astype(np.float32) / 255.0
        image = np.expand_dims(image, axis=(0, 1))
        return torch.from_numpy(image).to(self.device)

    def recognize_cell(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        if not self.enabled or self.model is None:
            return []

        allowed_digits = {ch for ch in allowed_chars if ch.isdigit()} if allowed_chars else set("0123456789")
        if not allowed_digits:
            return []

        tensor = self._prepare_tensor(processed_image)
        if tensor is None:
            return []

        with torch.no_grad():
            logits = self.model(tensor)
            probs = torch.softmax(logits, dim=1)[0].detach().cpu().numpy()

        ranked = np.argsort(probs)[::-1]
        hypotheses: List[OcrHypothesis] = []
        for idx in ranked[:3]:
            label = self.labels[int(idx)]
            if label == "__empty__" or label not in allowed_digits:
                continue
            confidence = float(probs[int(idx)])
            if not hypotheses and confidence < self.min_confidence:
                return []
            hypotheses.append(OcrHypothesis(symbol=label, confidence=confidence, source=self.engine_name))
        return hypotheses

    def recognize_line(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        return []
