import os
import numpy as np
import cv2
import logging
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

class PdfLoader:
    def __init__(self, dpi: int = 300):
        self.dpi = dpi

    def load_pdf_as_images(self, pdf_path: str):
        """
        Конвертирует PDF в список OpenCV-изображений с помощью PyMuPDF.
        """
        logger.info(f"Конвертация PDF: {pdf_path}")
        if not os.path.exists(pdf_path):
            logger.error(f"Файл не найден: {pdf_path}")
            raise FileNotFoundError(f"Файл не найден: {pdf_path}")
        try:
            doc = fitz.open(pdf_path)
            results = []
            base_name = os.path.basename(pdf_path).replace('.pdf', '')
            
            # Рассчитываем масштаб (PDF стандартно 72 DPI)
            zoom = self.dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            
            for i in range(len(doc)):
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=mat)
                
                # Конвертация в NumPy массив
                img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                
                # Приведение к формату BGR для OpenCV
                if pix.n == 4:
                    open_cv_image = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
                elif pix.n == 3:
                    open_cv_image = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                else:
                    open_cv_image = cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)
                    
                page_name = f"{base_name}_page_{i+1}.png"
                results.append((page_name, open_cv_image))
                
            return results
        except Exception as e:
            logger.error(f"Ошибка при чтении PDF {pdf_path}: {e}")
            return []
