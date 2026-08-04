# Подготовка релиза

## Перед сборкой

- [ ] Обновлены `src/hoi4_l10n_checker/version.py`, `version_info.txt`,
      `README.md`, `README.txt` и `CHANGELOG.md`.
- [ ] В `settings.example.json` нет личных путей.
- [ ] `settings.json`, `dist/`, `build/`, `.venv/` и игровые `.fnt` не
      отслеживаются Git.
- [ ] Получено разрешение на распространение игровых `.fnt`, если они будут
      включены в публичный релизный ZIP.
- [ ] Условия распространения стороннего CLI соблюдены; CLI не вложен в
      архив без разрешения.

## Проверка

```powershell
.\run_tests.ps1
python tools/prepare_font_resources.py --check-only
.\build.ps1
```

- [ ] Все тесты прошли.
- [ ] Собранный EXE запускается.
- [ ] В заголовке и свойствах EXE указана правильная версия.
- [ ] В архиве присутствуют `README.txt`, `LICENSE` и
      `THIRD_PARTY_NOTICES.md`.
- [ ] В архиве отсутствуют личные абсолютные пути.

## GitHub Release

- [ ] Создан тег вида `v0.9.6F3-beta`.
- [ ] Релиз отмечен как Pre-release.
- [ ] Приложен только полный `LocalisationChecker-Windows.zip`, а не один
      EXE без `_internal` и ресурсов.
- [ ] В описание скопирован соответствующий раздел `CHANGELOG.md`.
- [ ] Опубликована SHA-256-сумма архива.
