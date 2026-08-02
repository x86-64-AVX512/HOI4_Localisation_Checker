# Локальные ресурсы шрифтов

Эта папка намеренно не хранится в публичном репозитории. Проверке нужны
bitmap-описания `.fnt` из установленной Hearts of Iron IV и Equestria at War,
но эти файлы принадлежат их правообладателям и не входят в лицензию исходного
кода LocalisationChecker.

Подготовить локальную копию ресурсов можно командой из корня проекта:

```powershell
python tools/prepare_font_resources.py `
  --game-root "C:\Program Files (x86)\Steam\steamapps\common\Hearts of Iron IV" `
  --mod-root "C:\path\to\equestria_dev"
```

Скрипт читает `font_profile.json` и копирует только перечисленные в профиле
`.fnt` в подпапки `fonts/base` и `fonts/mod`. Он не изменяет игру или мод.

Проверка готовности ресурсов без копирования:

```powershell
python tools/prepare_font_resources.py --check-only
```

Не добавляйте скопированные игровые файлы в Git без явного разрешения их
правообладателей.
