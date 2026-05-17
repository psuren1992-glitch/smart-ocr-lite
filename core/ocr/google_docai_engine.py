import logging
import os
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from core.interfaces.ocr_engine import BaseOcrEngine
from core.models.data_models import OcrHypothesis

logger = logging.getLogger(__name__)


def _ensure_google_credentials_env() -> Optional[str]:
    existing = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if existing and os.path.exists(existing):
        return existing

    project_root = Path(__file__).resolve().parents[2]
    fallback = project_root / ".secrets" / "google-service-account.json"
    if fallback.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(fallback)
        return str(fallback)
    return None


class GoogleDocAIEngine(BaseOcrEngine):
    """Google Cloud Document AI OCR engine.

    Requires:
    - GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account-key.json
    - DOCUMENT_AI_PROCESSOR_ID=projects/.../locations/.../processors/...
    """

    _DEFAULT_PROCESSOR_ID = (
        "projects/nodal-strength-491704/locations/asia-south1/processors/"
        "d44aa5609b7abd4a"
    )

    def __init__(
        self,
        engine_name: str = "google_docai",
        min_confidence: float = 0.50,
    ):
        super().__init__(engine_name=engine_name)
        self.min_confidence = min_confidence
        self.processor_id = os.environ.get(
            "DOCUMENT_AI_PROCESSOR_ID",
            self._DEFAULT_PROCESSOR_ID,
        )
        self._client = None
        self.enabled = False
        self._init_error: Optional[str] = None

    def _ensure_client(self) -> bool:
        if self.enabled and self._client is not None:
            return True
        if self._init_error:
            return False

        try:
            from google.cloud import documentai
            _ensure_google_credentials_env()

            self._client = documentai.DocumentProcessorServiceClient()
            self.enabled = True
            logger.info("GoogleDocAIEngine initialized: %s", self.processor_id)
            return True
        except Exception as exc:
            self._init_error = str(exc)
            self.enabled = False
            logger.error(
                "GoogleDocAIEngine initialization failed: %s. "
                "Check google-cloud-documentai and GOOGLE_APPLICATION_CREDENTIALS.",
                exc,
            )
            return False

    def _prepare_image_bytes(self, image: np.ndarray) -> Optional[bytes]:
        if image is None or image.size == 0:
            return None
        success, encoded_image = cv2.imencode(".png", image)
        if not success:
            return None
        return encoded_image.tobytes()

    def _filter_text(self, text: str, allowed_chars: str) -> str:
        raw = (text or "").replace("\n", " ").strip()
        if not allowed_chars:
            return raw
        return "".join(ch for ch in raw if ch in allowed_chars or ch == " ")

    def _disable_after_api_error(self, message: str) -> None:
        self._init_error = message
        self.enabled = False
        self._client = None

    def process_image(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        from google.cloud import documentai

        raw_document = documentai.RawDocument(
            content=image_bytes,
            mime_type=mime_type,
        )

        request = documentai.ProcessRequest(
            name=self.processor_id,
            raw_document=raw_document,
        )

        result = self._client.process_document(request=request)
        return (result.document.text or "").strip()

    def recognize_cell(
        self,
        processed_image: np.ndarray,
        allowed_chars: str = "0123456789-,.",
    ) -> List[OcrHypothesis]:
        if not self._ensure_client():
            return []

        content = self._prepare_image_bytes(processed_image)
        if not content:
            return []

        try:
            text = self.process_image(content, mime_type="image/png")
            filtered = self._filter_text(text, allowed_chars).strip()
            if len(filtered) != 1:
                return []
            return [OcrHypothesis(symbol=filtered, confidence=0.95, source=self.engine_name)]
        except Exception as exc:
            logger.error("GoogleDocAIEngine cell recognition failed: %s", exc)
            self._disable_after_api_error(str(exc))
            return []

    def recognize_line(
        self,
        processed_image: np.ndarray,
        allowed_chars: str = "",
        is_handwritten: bool = False,
    ) -> List[OcrHypothesis]:
        if not self._ensure_client():
            return []

        content = self._prepare_image_bytes(processed_image)
        if not content:
            return []

        try:
            text = self.process_image(content, mime_type="image/png")
            filtered = " ".join(self._filter_text(text, allowed_chars).split())
            if not filtered:
                return []
            return [OcrHypothesis(symbol=filtered, confidence=0.95, source=f"{self.engine_name}_line")]
        except Exception as exc:
            logger.error("GoogleDocAIEngine line recognition failed: %s", exc)
            self._disable_after_api_error(str(exc))
            return []
