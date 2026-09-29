"""Exam/subject labels are separate from calibrated recognition templates."""
EXAMS = {'oge': 'ОГЭ', 'ege': 'ЕГЭ'}
SUBJECTS = {'math': 'Математика', 'russian': 'Русский язык'}


def profile_for(meta):
    exam = meta.get('exam', 'oge')
    subject = meta.get('subject', 'math')
    return {'exam': exam, 'subject': subject,
            'label': EXAMS.get(exam, 'Неизвестный экзамен') + ' · ' + SUBJECTS.get(subject, 'Неизвестный предмет'),
            'supported': exam == 'oge' and subject == 'math'}
