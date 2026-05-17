import logging
import os
from pathlib import Path
import cv2
import numpy as np
from typing import List, Optional

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

class GoogleVisionEngine(BaseOcrEngine):
    def __init__(
        self,
        engine_name: str = "google_vision",
        min_confidence: float = 0.50,
    ):
        super().__init__(engine_name=engine_name)
        self.min_confidence = min_confidence
        self._client = None
        self.enabled = False
        self._init_error: Optional[str] = None

    def _ensure_client(self) -> bool:
        if self.enabled and self._client is not None:
            return True
        if self._init_error:
            return False

        try:
            from google.cloud import vision
            _ensure_google_credentials_env()
            # Google Cloud Vision library looks for GOOGLE_APPLICATION_CREDENTIALS environment variable
            # or uses default credentials if running in GCP.
            self._client = vision.ImageAnnotatorClient()
            self.enabled = True
            logger.info("GoogleVisionEngine initialized.")
            return True
        except Exception as exc:
            self._init_error = str(exc)
            self.enabled = False
            logger.error(f"GoogleVisionEngine initialization failed: {exc}. "
                         "Make sure google-cloud-vision is installed and GOOGLE_APPLICATION_CREDENTIALS is set.")
            return False

    def _prepare_image_bytes(self, image: np.ndarray) -> Optional[bytes]:
        if image is None or image.size == 0:
            return None
        success, encoded_image = cv2.imencode('.png', image)
        if not success:
            return None
        return encoded_image.tobytes()

    def _filter_text(self, text: str, allowed_chars: str) -> str:
        if not allowed_chars:
            return text.strip()
        return "".join(ch for ch in text.strip() if ch in allowed_chars)

    def _disable_after_api_error(self, message: str) -> None:
        self._init_error = message
        self.enabled = False
        self._client = None

    def recognize_cell(self, processed_image: np.ndarray, allowed_chars: str = "0123456789-,.") -> List[OcrHypothesis]:
        if not self._ensure_client():
            return []

        content = self._prepare_image_bytes(processed_image)
        if not content:
            return []

        try:
            from google.cloud import vision
            image = vision.Image(content=content)
            # Use document_text_detection for better handwriting support
            response = self._client.document_text_detection(image=image)
            
            if response.error.message:
                logger.error(f"Google Vision API Error: {response.error.message}")
                self._disable_after_api_error(response.error.message)
                return []

            text = response.full_text_annotation.text.strip()
            # Google doesn't return per-character confidence easily in full_text_annotation 
            # without deep parsing, but we can assume high confidence if it returned something.
            # Usually, document_text_detection is very robust.
            
            filtered_text = self._filter_text(text, allowed_chars)
            if not filtered_text:
                return []

            # For a cell, we usually expect 1 character, but let's take whatever it found if it fits allowed_chars
            # Confidence is 0.95 by default as Google is very good.
            return [OcrHypothesis(symbol=filtered_text[:1], confidence=0.95, source=self.engine_name)]

        except Exception as e:
            logger.error(f"Google Vision recognition failed: {e}")
            self._disable_after_api_error(str(e))
            return []

    def recognize_line(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        if not self._ensure_client():
            return []

        content = self._prepare_image_bytes(processed_image)
        if not content:
            return []

        try:
            from google.cloud import vision
            image = vision.Image(content=content)
            response = self._client.document_text_detection(image=image)
            
            if response.error.message:
                logger.error(f"Google Vision API Error: {response.error.message}")
                self._disable_after_api_error(response.error.message)
                return []

            text = response.full_text_annotation.text.replace('\n', ' ').strip()
            filtered_text = self._filter_text(text, allowed_chars)
            
            if not filtered_text:
                return []

            return [OcrHypothesis(symbol=filtered_text, confidence=0.98, source=f"{self.engine_name}_line")]

        except Exception as e:
            logger.error(f"Google Vision line recognition failed: {e}")
            self._disable_after_api_error(str(e))
            return []
