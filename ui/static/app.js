const upload = document.querySelector('[data-upload]');
if (upload) {
  const file = upload.querySelector('[name=pdf]');
  const zone = document.getElementById('dropzone');
  const exam = upload.querySelector('[data-exam]');
  const subject = upload.querySelector('[data-subject]');
  if (exam && subject) {
    const updateProfile = () => {
      const supported = exam.value === 'oge' && subject.value === 'math';
      upload.querySelector('[data-profile-note]').textContent = supported
        ? 'ОГЭ · Математика: распознаётся настроенный бланк 2026/27, задания 1–19.'
        : 'Шаблон ещё не настроен. PDF будет сохранён с выбранным экзаменом и предметом, без распознавания и оценивания.';
      upload.querySelector('[data-upload-button]').textContent = supported ? 'Распознать бланки →' : 'Сохранить PDF →';
    };
    exam.addEventListener('change', updateProfile);
    subject.addEventListener('change', updateProfile);
    updateProfile();
  }
  const showName = () => { document.getElementById('filename').textContent = file.files[0]?.name || 'Выберите PDF с бланками'; };
  file.addEventListener('change', showName);
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragging'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
  zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('dragging'); if(e.dataTransfer.files.length) { file.files = e.dataTransfer.files; showName(); } });
  upload.addEventListener('submit', () => { const button = upload.querySelector('button'); button.disabled = true; button.textContent = 'Загружаем PDF…'; });
}
if (document.querySelector('[data-progress]')) setTimeout(() => location.reload(), 5000);
const review = document.getElementById('review-form');
if (review) {
  let dirty = false;
  review.addEventListener('input', () => { dirty = true; document.getElementById('save-hint').textContent = 'Есть несохранённые изменения'; });
  review.addEventListener('submit', e => {
    if(e.submitter?.value === 'verify' && !review.querySelector('[name=checked_corrections]').checked) {
      e.preventDefault(); const checkbox = review.querySelector('[name=checked_corrections]'); checkbox.focus(); checkbox.scrollIntoView({block:'center'});
      document.getElementById('save-hint').textContent = 'Сначала подтвердите проверку блока замен'; return;
    }
    dirty = false;
  });
  window.addEventListener('beforeunload', e => { if(dirty) { e.preventDefault(); e.returnValue = ''; } });
  const showCrop = button => { document.getElementById('large-crop').src = button.dataset.crop; document.getElementById('crop-title').textContent = 'Задание ' + button.dataset.task; };
  review.querySelectorAll('[data-crop]').forEach(button => button.addEventListener('click', () => showCrop(button)));
  review.querySelectorAll('.answer-row input').forEach(input => {
    input.addEventListener('focus', () => { const button = input.parentElement.querySelector('[data-crop]'); if(button) showCrop(button); });
    input.addEventListener('keydown', e => { if(e.key === 'Enter') { e.preventDefault(); const inputs = [...review.querySelectorAll('.answer-row input')]; inputs[inputs.indexOf(input)+1]?.focus(); } });
  });
}
const accessCode = document.querySelector('[data-access-code]');
if (accessCode && location.hash.length > 1) {
  accessCode.value = location.hash.slice(1);
  history.replaceState(null, '', location.pathname);
}
document.querySelectorAll('[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    const source = document.getElementById(button.dataset.copy);
    try {
      await navigator.clipboard.writeText(source.value);
      button.textContent = 'Ссылка скопирована';
    } catch {
      source.focus(); source.select();
      button.textContent = 'Нажмите Ctrl+C';
    }
  });
});
