# Smart OCR Lite — автоматическая проверка бланков ОГЭ

Flask-сервис для автоматического распознавания и проверки рукописных ответов с **Бланка ответов №1** экзаменов ОГЭ/ЕГЭ.

Загружаете скан → выбираете вариант → получаете таблицу с ✅/❌ по каждому из 19 заданий.

---

## Возможности

- Принимает **JPG, PNG, PDF** (многостраничный PDF — пакетная обработка)
- Автоматическое **выравнивание по реперным маркерам** (устойчиво к наклону ±5°)
- **OCR-ансамбль**: Tesseract + PaddleOCR + HOG+SVM голосуют за каждый символ
- Эвристики для **запятых**, **знака минус**, дробных ответов
- Сверка с **ключом ответов** (JSON, поддерживает альтернативные формы: `0,5` = `0.5` = `1/2`)
- Распознавание **ФИО** ученика из верхней части бланка
- Выгрузка в **Excel** (один файл или ZIP для пакета)
- Веб-интерфейс на Flask, работает локально

---

## Быстрый старт

```bash
git clone https://github.com/psuren1992-glitch/smart-ocr-lite.git
cd smart-ocr-lite
pip install -r requirements.txt

# Tesseract должен быть установлен отдельно:
# Windows: https://github.com/UB-Mannheim/tesseract/wiki
# Linux:   sudo apt install tesseract-ocr tesseract-ocr-rus

python webapp.py
```

Откройте **http://localhost:5001** в браузере.

---

## Структура проекта

```
smart-ocr-lite/
├── webapp.py                   # Flask-приложение (точка входа)
├── requirements.txt
├── run_web_5001.bat            # Быстрый запуск на Windows
│
├── core/                       # Пайплайн обработки
│   ├── pipeline.py             # Оркестратор: от изображения до результата
│   ├── reper_detector.py       # Детектор угловых маркеров
│   ├── alignment.py            # Выравнивание перспективы (cv2.warpPerspective)
│   ├── cell_grid.py            # Извлечение ячеек по шаблону
│   ├── cell_shape_rules.py     # Эвристики: looks_like_comma(), looks_like_minus()
│   ├── row_answer_assembler.py # Сборка символов в строку-ответ
│   ├── answer_resolver.py      # Heal + key bias
│   ├── scoring.py              # Сверка с ключом ответов
│   ├── answer_key.py           # Загрузка и нормализация ключа
│   └── ocr/
│       ├── tesseract_engine.py
│       ├── paddle_ocr_engine.py
│       ├── hog_svm_engine.py   # HOG+SVM классификатор
│       └── heuristic_engine.py
│
├── config/
│   ├── templates/              # JSON-шаблоны бланков (координаты ячеек)
│   └── answer_keys/            # Ключи ответов по вариантам
│
├── models/
│   └── hog_svm_digits.joblib   # Обученная модель (scikit-learn)
│
├── ui/
│   ├── templates/              # Jinja2-шаблоны (index.html, results.html)
│   └── static/
│
└── data/
    ├── uploads/                # Загруженные файлы (в .gitignore)
    ├── results/                # Результаты обработки JSON (в .gitignore)
    └── labeling/               # Размеченные ячейки для переобучения (в .gitignore)
```

---

## Как добавить свой вариант

1. Создайте `config/templates/my_template.json` — скопируйте существующий и обновите `template_id` и `template_name`
2. Создайте `config/answer_keys/my_template.json` с правильными ответами:

```json
{
  "_comment": "Ключ ответов для варианта X",
  "answers": {
    "1": "205",
    "2": ["9/25", "0,36", "0.36"],
    "3": "577,6"
  }
}
```

Список вариантов появится в дропдауне автоматически при следующем запуске.

---

## Готовые шаблоны

| Шаблон | Описание |
|--------|----------|
| `bo1_oge_math_2026_v1` … `v6` | ОГЭ Математика, КИМ 19.03.2026, варианты 1–6 |
| `bo1_oge_math_2024` | ОГЭ Математика 2024 (реальный бланк) |
| `bo1_oge_geography_2026` | ОГЭ География 2026 |
| `bo1_oge_russian_2026` | ОГЭ Русский язык 2026 |
| `bo1_oge_social_2026` | ОГЭ Обществознание 2026 |
| `ege_math_base_2024` | ЕГЭ Математика База 2024 |
| `ege_math_profile_2024` | ЕГЭ Математика Профиль 2024 |

---

## Технологии

- Python 3.11+
- Flask, OpenCV, NumPy
- Tesseract OCR (+ `pytesseract`)
- PaddleOCR (`eslav_PP-OCRv5_mobile_rec`)
- scikit-learn (HOG+SVM)
- PyMuPDF (PDF → изображения)
- openpyxl (экспорт в Excel)

---

## Лицензия

MIT — используйте свободно, ссылка на репозиторий приветствуется.
