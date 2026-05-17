import os
from pathlib import Path
from typing import List, Optional, Tuple

from core.interfaces.ocr_engine import BaseOcrEngine
from core.ocr.digit_engine import DigitEngine
from core.ocr.heuristic_engine import HeuristicEngine
from core.ocr.hog_svm_engine import HogSvmEngine
from core.ocr.paddle_ocr_engine import PaddleOcrEngine
from core.ocr.tesseract_engine import TesseractEngine
from core.symbol_classifier import SymbolClassifier


def default_hog_model_path() -> str:
    return str(Path(__file__).resolve().parent.parent / "models" / "hog_svm_digits.joblib")


def google_credentials_available() -> bool:
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if env_path and Path(env_path).exists():
        return True

    fallback = Path(__file__).resolve().parent.parent / ".secrets" / "google-service-account.json"
    return fallback.exists()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_default_ocr_engines(
    tesseract_cmd: Optional[str] = None,
    include_hog_svm: bool = True,
    include_paddleocr: bool = False,
    include_google_vision: bool = False,
    include_google_docai: bool = False,
    hog_model_path: Optional[str] = None,
    hog_min_confidence: float = 0.62,
    paddle_min_confidence: float = 0.72,
    paddle_model_name: str = "eslav_PP-OCRv5_mobile_rec",
) -> Tuple[List[BaseOcrEngine], List[BaseOcrEngine]]:
    heuristic = HeuristicEngine(empty_threshold=0.02)
    digit = DigitEngine()
    tesseract = TesseractEngine(tesseract_cmd=tesseract_cmd)

    engines: List[BaseOcrEngine] = [heuristic, tesseract]
    digit_vote_engines: List[BaseOcrEngine] = [digit, tesseract]

    if include_paddleocr:
        paddle_engine = PaddleOcrEngine(
            model_name=paddle_model_name,
            min_confidence=paddle_min_confidence,
        )
        if paddle_engine._ensure_model():
            engines.append(paddle_engine)
            digit_vote_engines.append(paddle_engine)

    if include_google_vision:
        from core.ocr.google_vision_engine import GoogleVisionEngine
        google_engine = GoogleVisionEngine()
        engines.append(google_engine)
        digit_vote_engines.append(google_engine)

    if include_google_docai:
        try:
            from core.ocr.google_docai_engine import GoogleDocAIEngine
            docai_engine = GoogleDocAIEngine()
            engines.append(docai_engine)
            digit_vote_engines.append(docai_engine)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "GoogleDocAIEngine не поднялся: %s", exc
            )

    if include_hog_svm:
        hog_path = hog_model_path or default_hog_model_path()
        hog_engine = HogSvmEngine(model_path=hog_path, min_confidence=hog_min_confidence)
        if hog_engine.enabled:
            digit_vote_engines.append(hog_engine)

    return engines, digit_vote_engines


def build_google_only_ocr_engines() -> Tuple[List[BaseOcrEngine], List[BaseOcrEngine]]:
    from core.ocr.google_docai_engine import GoogleDocAIEngine
    from core.ocr.google_vision_engine import GoogleVisionEngine

    engines: List[BaseOcrEngine] = []

    vision_engine = GoogleVisionEngine()
    if vision_engine._ensure_client():
        engines.append(vision_engine)

    try:
        docai_engine = GoogleDocAIEngine()
        if docai_engine._ensure_client():
            engines.append(docai_engine)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "GoogleDocAIEngine не поднялся в google-only профиле: %s", exc
        )

    if not engines:
        raise RuntimeError(
            "Google-only OCR profile requested, but neither Google Vision nor Google Doc AI could be initialized."
        )

    return engines, list(engines)


def build_default_symbol_classifier(
    tesseract_cmd: Optional[str] = None,
    doubt_threshold: float = 0.65,
    handwritten_mode: bool = False,
    include_hog_svm: bool = True,
    include_paddleocr: bool = False,
    include_google_vision: bool = False,
    include_google_docai: bool = False,
    hog_model_path: Optional[str] = None,
    hog_min_confidence: float = 0.62,
    paddle_min_confidence: float = 0.72,
    paddle_model_name: str = "eslav_PP-OCRv5_mobile_rec",
) -> SymbolClassifier:
    engines, digit_vote_engines = build_default_ocr_engines(
        tesseract_cmd=tesseract_cmd,
        include_hog_svm=include_hog_svm,
        include_paddleocr=include_paddleocr,
        include_google_vision=include_google_vision,
        include_google_docai=include_google_docai,
        hog_model_path=hog_model_path,
        hog_min_confidence=hog_min_confidence,
        paddle_min_confidence=paddle_min_confidence,
        paddle_model_name=paddle_model_name,
    )
    return SymbolClassifier(
        engines=engines,
        digit_vote_engines=digit_vote_engines,
        doubt_threshold=doubt_threshold,
        handwritten_mode=handwritten_mode,
    )


def build_google_only_symbol_classifier(
    doubt_threshold: float = 0.65,
    handwritten_mode: bool = False,
) -> SymbolClassifier:
    engines, digit_vote_engines = build_google_only_ocr_engines()
    return SymbolClassifier(
        engines=engines,
        digit_vote_engines=digit_vote_engines,
        doubt_threshold=doubt_threshold,
        handwritten_mode=handwritten_mode,
    )


def build_ai_ready_symbol_classifier(
    tesseract_cmd: Optional[str] = None,
    doubt_threshold: float = 0.65,
    handwritten_mode: bool = False,
    include_hog_svm: bool = True,
    include_paddleocr: bool = True,
    include_google_vision: Optional[bool] = None,
    include_google_docai: Optional[bool] = None,
    hog_model_path: Optional[str] = None,
    hog_min_confidence: float = 0.62,
    paddle_min_confidence: float = 0.72,
    paddle_model_name: str = "eslav_PP-OCRv5_mobile_rec",
) -> SymbolClassifier:
    google_available = google_credentials_available()
    use_google_vision = include_google_vision
    if use_google_vision is None:
        use_google_vision = _env_flag("ENABLE_GOOGLE_VISION", default=google_available)

    use_google_docai = include_google_docai
    if use_google_docai is None:
        use_google_docai = _env_flag("ENABLE_GOOGLE_DOCAI", default=google_available)

    return build_default_symbol_classifier(
        tesseract_cmd=tesseract_cmd,
        doubt_threshold=doubt_threshold,
        handwritten_mode=handwritten_mode,
        include_hog_svm=include_hog_svm,
        include_paddleocr=include_paddleocr,
        include_google_vision=use_google_vision,
        include_google_docai=use_google_docai,
        hog_model_path=hog_model_path,
        hog_min_confidence=hog_min_confidence,
        paddle_min_confidence=paddle_min_confidence,
        paddle_model_name=paddle_model_name,
    )
