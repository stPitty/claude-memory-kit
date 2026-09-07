# claude-memory-kit — память «как в Letta» для Claude Code

Набор хуков, агентов, скиллов и CLI, который переносит в Claude Code архитектуру памяти Letta / MemGPT:
файловая память под git (MemFS), компиляция памяти в контекст на старте сессии, фоновая рефлексия
(sleep-time compute), recall по всей истории разговоров, guardrails на запись и бюджет контекста.
Память лежит в обычной папке с Markdown-файлами и открывается в Obsidian как vault — с графом связей,
поиском и историей правок.

Ресерч, на котором основан порт: `letta-memory-research.md` (раздел 12 — маппинг Letta → Claude Code).

## Маппинг Letta → kit

| Letta | claude-memory-kit |
|---|---|
| MemFS (`$MEMORY_DIR`, git-репозиторий) | vault `~/claude-memory/` под git; `autoMemoryDirectory` в `settings.json` указывает на него |
| Core memory (`persona`, `human`, …) в системном промпте | корневые `*.md` vault'а, инжектятся целиком хуком `SessionStart` в блок `<memory_system>` |
| Deferred память (путь + description) | подкаталоги с `MEMORY.md`; в контексте — дерево с описаниями, содержимое читается по запросу |
| `projects/`-каталог | `projects/<slug>/` — core-память **только** внутри этого проекта (slug = имя git-репозитория или папки) |
| Компиляция системного промпта | `hooks/session_start.py` → `additionalContext` (self / memory / external_projection / memory_metadata) |
| Инструмент `memory` с guardrails | `PreToolUse`-хук: запрет записи в неиндексированный каталог, в `read_only`-файлы, секретов, в `.git`/`.obsidian` |
| Обязательный commit («uncommitted = not saved») | `PostToolUse`-хук валидирует контракт файла и делает `git commit`; невалидный файл остаётся незакоммиченным |
| Reflection-сабагент (5 фаз, 5 фильтров) | агент `memory-reflection`; запускается фоном по `PreCompact` (или по счётчику `Stop`) через `claude -p`, вручную — `/memory-reflect` |
| Recall (`letta messages search`, needle + expand) | агент `memory-recall` + `memoryctl search / expand / sessions` по `~/.claude/projects/**/*.jsonl` |
| `/remember`, `/doctor`, `/init`, `/sleeptime`, `/recompile` | `/remember`, `/memory-doctor`, `/memory-init`, `/memory-sleeptime`; «recompile» = новая сессия или `/clear` |
| `letta memory status/tokens/diff/backup` | `memoryctl status / tokens / diff / backup / log / validate` |
| Pre-commit валидация MemFS | git-хук `pre-commit` в vault'е (`memoryctl validate`) |
| Импорт истории (`trajectories`) | `/memory-init` + параллельные агенты `memory-history-analyzer` |
| Shared memory (`letta shared-memory attach`) | `memoryctl mount add <path|url>` — внешние git-репозитории с памятью, в контексте только дерево, содержимое по запросу |

## Требования

- macOS или Linux, `python3` ≥ 3.8 (стандартная библиотека, зависимостей нет), `git`.
- Claude Code ≥ 2.1.234 (нужна настройка `autoMemoryDirectory`; проверено на 2.1.263).
- Для **фоновой** рефлексии — CLI `claude` в `$PATH`, залогиненный (`claude` → `/login`). Десктоп-приложение
  использует свою авторизацию, поэтому CLI надо залогинить отдельно, один раз.
- Для визуализации — Obsidian (`brew install --cask obsidian`), опционально.

## Установка (3 шага)

```bash
git clone <url-этого-репозитория> ~/claude-memory-kit-src   # или скопировать папку
cd ~/claude-memory-kit-src
./install.sh                     # можно: ./install.sh --vault ~/Documents/claude-memory
```

Затем:

1. **Перезапустить Claude Code** (хуки, агенты и скиллы читаются при старте). В новой сессии выполнить `/memory-status`.
2. Один раз залогинить CLI для фоновой рефлексии: в терминале `claude`, затем `/login`, выйти. Проверка: `claude auth status` → `"loggedIn": true`.
3. По желанию открыть память в Obsidian: `brew install --cask obsidian`, затем `memoryctl open`
   (или Obsidian → Open folder as vault → `~/claude-memory`).
4. По желанию собрать стартовую память из прошлых сессий: `/memory-init`.

Установщик идемпотентен — повторный запуск обновляет kit, не трогая содержимое vault'а.

### Что делает `install.sh`

| Шаг | Что происходит |
|---|---|
| kit | копирует `memkit/`, `hooks/`, `bin/`, `templates/` в `~/.claude/memory-kit/` |
| конфиг | создаёт `~/.claude/memory-config.json` (если нет) |
| vault | создаёт `~/claude-memory/` с seed-файлами, `.obsidian/`, `.gitignore`; `git init`; ставит `pre-commit` |
| миграция | переносит существующие `~/.claude/projects/*/memory/*.md` в корень vault'а, старую папку переименовывает в `memory.pre-kit-backup-<дата>` |
| агенты | `memory-reflection`, `memory-recall`, `memory-history-analyzer` → `~/.claude/agents/` |
| скиллы | `remember`, `memory-reflect`, `memory-recall`, `memory-doctor`, `memory-init`, `memory-status`, `memory-sleeptime` → `~/.claude/skills/` |
| settings | в `~/.claude/settings.json` добавляет `autoMemoryDirectory` и 5 хуков (свои прежние хуки сохраняются) |
| CLAUDE.md | вписывает секцию между `<!-- claude-memory-kit:start/end -->` в `~/.claude/CLAUDE.md` |
| commit | первый коммит vault'а и `memoryctl validate` |

## Как это работает

### Уровни памяти

| Уровень | Где | В контексте |
|---|---|---|
| Core | `~/claude-memory/*.md` (кроме `MEMORY.md`, `ARCHIVE.md`) | всегда, целиком, в любом проекте |
| Core проекта | `~/claude-memory/projects/<slug>/*.md` | целиком, когда cwd — этот проект; иначе только в дереве |
| Deferred | любые вложенные каталоги с `MEMORY.md` | путь + `description`; содержимое — `Read` по запросу |
| Index | `MEMORY.md` (корневой и в каждом каталоге) | корневой грузит сам Claude Code (первые 200 строк / 25 КБ) |
| Archive | `ARCHIVE.md` | не грузится; датированные записи отставного контекста |
| Recall | `~/.claude/projects/<proj>/<session>.jsonl` | не грузится; поиск агентом `memory-recall` |

Инвариант из Letta: **recall хранит опыт, память хранит выводы**. В память не пишется то, что выводимо поиском по истории или чтением файлов.

### Хуки (в `~/.claude/settings.json`)

| Событие | Скрипт | Что делает |
|---|---|---|
| `SessionStart` (startup/resume/clear/compact) | `session_start.py` | коммитит ручные правки (из Obsidian), валидирует vault, компилирует `<memory_system>` в контекст, считает бюджет |
| `PreToolUse` Edit/Write | `pre_tool_guard.py` | вне vault'а — молчит; внутри — allow, либо deny: неиндексированный каталог, `read_only: true`, секреты, `.git`/`.obsidian`, не-Markdown |
| `PostToolUse` Edit/Write | `post_tool_commit.py` | валидирует файл (frontmatter, `name` == имя файла, индексация); ошибка → exit 2 с объяснением; иначе `git commit` и напоминание «вступит в силу со следующей сессии» |
| `PreCompact` | `reflect_trigger.py` | по умолчанию запускает фоновую рефлексию (`trigger: compaction-event`) |
| `Stop` | `reflect_trigger.py` | считает ходы; при `trigger: step-count` / `both` запускает рефлексию каждые `stepCount` ходов |

Хуки внутри фоновой рефлексии отключаются переменной `CLAUDE_MEMORY_REFLECTING=1` (кроме компиляции памяти и guard'а), чтобы не было рекурсии.

### Рефлексия («сны»)

`memkit/reflect.py`: берёт транскрипт сессии → делает компактный дайджест (только новые строки с прошлой рефлексии; порог `minNewMessages`) → запускает
`claude -p --agent memory-reflection --model sonnet --allowedTools Bash Edit Read` в каталоге vault'а → агент проходит 5 фаз (Investigate → Extract → Update → Review → Commit)
и делает один коммит с трейлерами `Generated-By` / `Session`, либо ничего не меняет. Результат — в `memoryctl status` («last refl.») и в `~/.claude/memory-state/logs/`.
Одновременно работает только одна рефлексия (lock-файл). Правки применяются к следующей сессии.

Ручной запуск: `/memory-reflect` (fork текущего разговора — CLI-логин не нужен) или `memoryctl reflect --session <id>`.

### Recall

`memoryctl sessions | search "<текст>" | expand <session> <line>` — стратегия «needle + expand»: найти сообщение, развернуть контекст вокруг него.
Агент `memory-recall` (или `/memory-recall <вопрос>`) делает это в отдельном контексте и возвращает отчёт: ответ → находки с источниками → когда обсуждалось → чем кончилось.
Правило в CLAUDE.md: встретив незнакомое имя/проект/решение, агент **сначала ищет в recall**, а не считает, что не знает.

## Контракт формата vault'а

- `MEMORY.md` (корневой и в каждом каталоге) — индекс **без** frontmatter, одна строка на файл: `- [Название](file.md) — зачем`.
- Любой другой `.md` — frontmatter с `name` (равен имени файла без `.md`, kebab-case) и `description` («какого рода информация здесь», не пересказ).
  Допустимы `metadata: {type: user|feedback|project|reference}`, `tags`, `read_only: true`, `modified` (ставит сам Claude Code).
- Каталог является памятью **только если** в нём есть `MEMORY.md` («Memory requires MEMORY.md before writing …»).
- Связи — `[[wikilinks]]` по имени файла (их же рисует граф Obsidian).
- Секреты в память не пишутся (guard режет по регуляркам); ссылаться как `$SECRET_NAME`.
- Проверка: `memoryctl validate`. Git-хук `pre-commit` не даёт закоммитить нарушение (обход: `git commit --no-verify`).

Пример:

```markdown
---
name: human-prefs-coding
description: The user's coding preferences — languages, style, tooling, and chronic corrections.
metadata:
  type: feedback
---

Always `uv run`, never bare `python` — хроническая ошибка, ломает виртуальное окружение.
Go — целевой стек backend; Node.js — легаси в миграции (см. [[team-composition-and-stack]]).
```

## Команды

Слэш-команды в Claude Code:

| Команда | Что делает |
|---|---|
| `/remember <что>` | записать в память факт/предпочтение/коррекцию (3 шага: что → куда → подтверждение) |
| `/memory-recall <вопрос>` | поиск по прошлым разговорам |
| `/memory-reflect [фокус]` | рефлексия над текущим разговором прямо сейчас |
| `/memory-status` | дерево, бюджет, история коммитов, состояние рефлексии |
| `/memory-doctor` | лечение деградации: бюджет, дубли, битые ссылки, tier-check — без агрессивного сжатия |
| `/memory-init` | первичное построение памяти, импорт прошлых сессий параллельными агентами |
| `/memory-sleeptime off\|step-count\|compaction-event\|both [--step-count N]` | триггеры фоновой рефлексии |

CLI (`alias memoryctl='python3 ~/.claude/memory-kit/bin/memoryctl'`):

```
memoryctl status | compile [--cwd DIR] | tokens | validate | log | diff | commit -m "..."
memoryctl reflect [--session ID | --latest] [--force] [--background] [--model sonnet]
memoryctl sessions | search "text" [--role user] [--project slug] [--since 2026-08-01] | expand ID LINE | digest ID
memoryctl config [--set reflection.model=opus] | sleeptime both --step-count 25 | open | backup
memoryctl mount add <path|url> [--name N] [--rw] [--only 'glob,glob'] | list [--tree] | pull [name] | rm <name>
```

## Obsidian

- Открыть: `memoryctl open` или Obsidian → «Open folder as vault» → `~/claude-memory`. Конфиг `.obsidian/` уже в vault'е: wikilinks, свойства видимы,
  граф раскрашен по группам (persona / human-* / projects / MEMORY / ARCHIVE).
- Что смотреть: **Graph view** — связи между заметками (`[[...]]` и ссылки из `MEMORY.md`); **Backlinks** — кто ссылается на заметку;
  свойства `name` / `description` / `type` — в шапке заметки.
- Управление: редактировать, переименовывать (Obsidian сам обновит ссылки), удалять, ставить `read_only: true` — всё руками.
  Правки подхватит и закоммитит ближайший `SessionStart` в Claude Code (коммит `chore(manual): …`), либо `memoryctl commit`.
- Рекомендуемые community-плагины: **Obsidian Git** (история и diff прямо в Obsidian), **Dataview** (таблицы по `type`), **Properties**.
- Не создавать заметки без frontmatter и папки без `MEMORY.md` — `memoryctl validate` покажет, что агент их «не видит».

## Внешняя (shared) память — mounts

Чужой или командный git-репозиторий с памятью можно **подключить, не загружая в свою память**: в контекст попадает только дерево его Markdown-файлов с однострочными описаниями (frontmatter `description` или первый заголовок), а содержимое агент читает `Read`'ом, когда тема задачи совпадает. Аналог `shared-memory` в Letta.

```bash
memoryctl mount add git@gitlab.example.com:team/backend-memory.git          # клонирует в ~/.claude/memory-mounts/<name>
memoryctl mount add ~/repos/colleague-memory --name kolya --only 'courier-*,delivery-*'   # локальный путь; виден только в этих проектах
memoryctl mount add ~/repos/team-memory --rw                                # писать можно; коммиты идут в тот репозиторий
memoryctl mount list --tree | pull [name] | rm <name>
```

- По умолчанию mount **read-only**: guard-хук запретит правку файлов внутри него, выводы пишутся в свой vault.
- На старте сессии выполняется `git pull --ff-only` (`autoPull`), результат виден в атрибуте `sync=` и в `memory_metadata`; конфликты и грязные файлы репортятся, но не чинятся.
- `--only` ограничивает видимость mount'а проектами (glob по slug), чтобы не тратить контекст там, где он не нужен. Размер дерева ограничен `maxEntries` (80) и `maxDepth` (3) — правится в `~/.claude/memory-config.json`, секция `mounts`.
- Репозиторий не обязан соблюдать контракт vault'а: без frontmatter описанием станет первый `# заголовок` файла.
- Экономия контекста для больших репозиториев (настройки через `memoryctl mount set <name> key=value`):
  `exclude='system,skills'` — скрыть папки; `collapse='reference/*'` — показывать папки одной строкой с числом файлов;
  `focus=true` (по умолчанию) — папка, чьё имя совпадает со slug текущего проекта, раскрывается полностью; `descMax=100` — длина описания.
  Пример: память коллеги в раскладке Letta memfs-v1 (`system/`, `reference/<проект>/`, `skills/`) с `exclude='system,skills' collapse='reference/*'`
  стоит ~300 токенов вне проекта и ~600–1500 внутри него вместо ~10 000 целиком.

## Настройка — `~/.claude/memory-config.json`

```json
{
  "vault": "~/claude-memory",
  "autocommit": true,
  "reflection": { "trigger": "compaction-event", "stepCount": 25, "model": "sonnet", "maxTurns": 60, "minNewMessages": 6 },
  "budget": { "targetTokens": 20000, "warnTokens": 30000, "bytesPerToken": 4 }
}
```

`trigger`: `compaction-event` (дефолт Letta) | `step-count` (каждые N ходов) | `both` | `off`. Бюджет — оценка ~4 байта/токен; цель ≤ 10 % контекста.

## Проверка, что всё работает

```bash
memoryctl status                               # vault git, 0 errors, бюджет
memoryctl compile --cwd ~/my-project | head    # что именно инжектится в сессию
claude auth status                             # loggedIn: true — нужно для фоновой рефлексии
```

В Claude Code: `/memory-status`; попросить «запомни, что …» → в ответе хука появится `memory committed (<hash>)`, `memoryctl log` покажет коммит.
`/compact` → через несколько минут `memoryctl status` покажет «last refl.: … updated memory» и новый коммит `…(reflection): … 🔮`.

## Ручная установка (если не хочется скрипта)

1. Скопировать `memkit/ hooks/ bin/ templates/` в `~/.claude/memory-kit/`.
2. Создать `~/claude-memory/` из `templates/vault/`, `git init`, скопировать `templates/vault-pre-commit` в `.git/hooks/pre-commit`.
3. `~/.claude/memory-config.json` из `templates/memory-config.json` (подставить путь vault'а).
4. Скопировать `agents/*.md` в `~/.claude/agents/`, `skills/*/SKILL.md` в `~/.claude/skills/<name>/`, заменив `__MEMORYCTL__` и `__VAULT__` на абсолютные пути.
5. В `~/.claude/settings.json`: `"autoMemoryDirectory": "~/claude-memory"` и хуки из `install.sh` (секция «wanted»).
6. Добавить в `~/.claude/CLAUDE.md` содержимое `templates/CLAUDE.md.section` (с теми же заменами).
7. Перенести старые файлы из `~/.claude/projects/*/memory/` в корень vault'а, закоммитить, `memoryctl validate`.

## Диагностика

| Симптом | Причина / решение |
|---|---|
| в сессии нет блока `<memory_system>` | Claude Code не перезапущен после установки; проверить `~/.claude/settings.json` → `hooks.SessionStart`, вручную: `echo '{"cwd":"'$PWD'"}' \| python3 ~/.claude/memory-kit/hooks/session_start.py` |
| рефлексия «never» / лог `Not logged in` | залогинить CLI: `claude` → `/login`; см. `~/.claude/memory-state/logs/reflect-*.log` |
| `memory contract violation` после записи | поправить frontmatter (`name` == имя файла, есть `description`) или создать `MEMORY.md` в каталоге |
| правки из Obsidian не видны агенту | они применяются с новой сессии; проверить `memoryctl status` → `dirty` и `memoryctl commit` |
| память «раздулась» | `/memory-doctor`; переносить целые файлы в deferred-каталоги, не сжимать |
| нужно откатить память | `cd ~/claude-memory && git log` / `git revert <hash>` / `memoryctl backup` |

Логи: `~/.claude/memory-state/logs/kit.log` (хуки), `spawn.log`, `reflect-*.log`; состояние рефлексии — `last-reflection.json`, `reflected/<session>.json`.

## Удаление

`~/.claude/memory-kit/uninstall.sh` — убирает хуки, `autoMemoryDirectory`, агентов, скиллы и секцию в CLAUDE.md. Vault, конфиг и state остаются.

## Отличия от Letta и ограничения

- Компиляция идёт с рабочего дерева vault'а, но `SessionStart` сначала коммитит всё незакоммиченное — так что фактически «в контексте = в HEAD».
- У Letta обязательный `reason` на каждую правку; здесь автокоммит помечает файл и сессию, а осмысленное сообщение пишет рефлексия / `/remember`.
- Фоновая рефлексия — отдельный процесс `claude -p` с полным `Bash` (как у Letta); ограничить можно через `--allowedTools` в `memkit/reflect.py`.
- Recall — подстрочный/regex-поиск по JSONL, без векторного индекса; для объёмов одного разработчика этого достаточно.
- Персона намеренно короткая (см. раздел 12.4 ресерча): поведение Claude Code уже задаётся системным промптом и CLAUDE.md.
