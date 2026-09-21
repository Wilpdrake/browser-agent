# Browser Agent — локальный GUI-агент

Python 3.12+, asyncio, Playwright Python, Pydantic, Rich и httpx. Собственный
последовательный tool-calling loop, без agent framework и веб-интерфейса.
Окно Chromium/Brave **всегда видимое (`headless=False`)**. В терминале видны
статусы, tool name, JSON arguments/result и duration. Скрытые reasoning-поля API
не печатаются и не сохраняются в диалог.

## Установка

Из этой директории:

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

На обычном Linux для отсутствующих системных библиотек Playwright предлагает
`uv run playwright install --with-deps chromium` (требуются права администратора).
Проект сам системные пакеты не устанавливает.

Если нужно держать даже кэш установщика и браузеры внутри проекта:

```bash
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.python"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright"
uv sync
uv run playwright install chromium
```

`PLAYWRIGHT_BROWSERS_PATH` должен оставаться таким же при последующих запусках.
При использовании установленного Brave/Chrome загрузка Chromium не нужна.

## Настройка LLM

В `.env` заполните:

```dotenv
LLM_BASE_URL=https://your-api.example/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
LLM_PROVIDER=openai-compatible
```

Это пример адреса, не настроенный сервис. `LLM_BASE_URL` — корень API,
**не** полный `/chat/completions`: адаптер добавляет этот путь сам.
Для удалённого API обязателен HTTPS; обычный HTTP разрешён только для loopback
(`localhost`, `127.0.0.1`, `::1`).
Нужна модель/API с поддержкой OpenAI-compatible `tools` / `tool_calls`.
Без настроек CLI выводит понятную ошибку и завершается с кодом 2 до запуска браузера.
Никаких реальных ключей в проекте нет. Переменные окружения имеют приоритет над `.env`.

Другой протокол подключается реализацией `llm/base.py::LLMProvider` и фабрикой в
`main.py`; одной смены имени provider для несовместимого API недостаточно.

## Запуск

```bash
uv run browser-agent
# или
uv run python -m browser_agent
# одна задача (после завершения браузер закрывается):
uv run browser-agent --task "Открой https://example.com и скажи заголовок"
```

В интерактивном режиме можно вводить следующие задачи без перезапуска.
Браузер остается открытым, а краткие пары «задача → итог» сохраняются как ограниченный
контекст текущего процесса. Сырые DOM-снимки и tool results в память не переносятся.
`/quit`, `/exit` — закрыть; `/reset` — очистить контекст и refs, не удаляя cookies
и не переходя со страницы. `/login` временно закрывает автоматизированный браузер,
открывает обычный браузер с тем же профилем для ручного ввода логина, пароля, CAPTCHA
или 2FA и после полного закрытия обычного браузера перезапускает агент. `Ctrl+C`
останавливает агент и закрывает его браузер.

Расположите окно терминала и окно браузера рядом средствами рабочего стола.
`BROWSER_SLOW_MO=150` делает действия заметнее. Не требуется отдельный UI.

Пример:

> Открой https://lavka.yandex.ru, найди хот-дог и добавь один в корзину, но ничего не оплачивай.

Сайт может потребовать адрес доставки или ручную авторизацию. Агент не должен
угадывать их; остановите автоматизацию, войдите вручную в отдельном профиле и
повторите задачу. Успех на конкретном коммерческом сайте не гарантируется.

## Brave, Chrome и NixOS

В `.env`:

```dotenv
BROWSER_EXECUTABLE_PATH=/run/current-system/sw/bin/brave
BROWSER_CHANNEL=
BROWSER_HEADLESS=false
BROWSER_PERSISTENT=true
ALLOW_PRIVATE_NETWORK=false
```

На других ОС укажите реальный путь к Brave/Chromium. `BROWSER_EXECUTABLE_PATH`
имеет приоритет над `BROWSER_CHANNEL`. Если оба пусты, используется Playwright
Chromium. Для установленного Chrome можно указать `BROWSER_CHANNEL=chrome`.
`BROWSER_HEADLESS=true` намеренно отклоняется валидацией: проект предназначен для GUI.

На NixOS скачанные Playwright бинарники могут не запускаться из-за динамического
загрузчика. Используйте системный Brave. Если bundled driver Node несовместим:

```bash
export PLAYWRIGHT_NODEJS_PATH="$(command -v node)"
BROWSER_EXECUTABLE_PATH="$(command -v brave)" uv run browser-agent
```

Приложение и orchestration написаны на Python. Playwright Python **сам использует
внутренний Node driver**; это неизбежная часть Playwright, не Node.js-приложение.
Короткие DOM-evaluate функции исполняются внутри страницы; Node/TypeScript исходников
и npm-зависимостей в проекте нет. Нужен рабочий DISPLAY/Wayland и GUI-сеанс.

## Вход Google: «This browser or app may not be secure»

[Google может блокировать вход из автоматизированных браузеров](https://support.google.com/accounts/answer/7675428).
Это не ошибка API модели; смена `headless` сама по себе не решает проверку.
Никаких stealth-патчей, подмены fingerprint, отключения защиты аккаунта или CAPTCHA bypass
в проекте нет.

Для входа используйте **обычный установленный браузер без Playwright**:

```bash
# Сначала закройте все окна агента с профилем browser-data.
BROWSER_EXECUTABLE_PATH=/run/current-system/sw/bin/brave uv run browser-agent --login
```

Если агент уже запущен в интерактивном режиме, введите `/login`: профиль будет
освобожден от Playwright, а после ручного входа и закрытия обычного браузера агент
продолжит работу с сохраненными cookies.

Режим `--login` не требует LLM key. Он открывает accounts.google.com с тем же
отдельным `browser-data/`, без automation и remote-debugging flags.
Введите пароль и 2FA **самостоятельно**, затем закройте все окна этого профиля.
Для агента укажите тот же `BROWSER_EXECUTABLE_PATH` и `BROWSER_PERSISTENT=true`.
Playwright использует нативное хранилище ключей, как ручной браузер, а не принудительный
`--password-store=basic`. Если ОС запросит доступ к keyring/кошельку, разрешайте его
только ожидаемому браузеру. Основной пользовательский профиль не используется.

Успешный запуск `--login` **не означает успешную авторизацию**: ее подтверждает только
страница аккаунта. Google может потребовать повторную проверку или заблокировать
дальнейшую автоматизацию. Если сообщение появляется и при ручном входе, проверьте
актуальность браузера, JavaScript, cookies и расширения по официальной инструкции;
не отключайте защиту аккаунта. Автоматизацию Google sign-in агенту не поручайте.

## Профиль и данные

`browser-data/` — отдельный persistent context, никогда основной профиль пользователя.
Cookies, localStorage и авторизация сохраняются после закрытия. `sessionStorage`
зависит от времени жизни вкладки: восстановление между запусками не гарантируется,
специального экспорта секретов sessionStorage нет. `BROWSER_PERSISTENT=false`
создает непостоянный context. Один профиль нельзя одновременно открывать двумя процессами.
Скриншоты сохраняются в `screenshots/`, неожиданные ошибки — `errors.log`.
Эти данные и `.env` исключены из Git. Не публикуйте профиль, скриншоты и логи:
они могут содержать персональные данные. Вводимый через `type_text` текст редактируется
в терминале; остальные аргументы и результаты tools видны в scrollback.

## Архитектура

```text
src/browser_agent/
  __main__.py, main.py       CLI, жизненный цикл
  config.py                 .env, лимиты, обязательный GUI
  agent/                    loop, system prompt, состояние диалога
  browser/                  BrowserSession, DOM snapshot, refs, scoring
  tools/registry.py         Pydantic schemas и dispatch
  llm/                      Protocol и OpenAI-compatible httpx adapter
  cli/console.py            Rich logging
scripts/browser_smoke.py     проверка браузера без LLM
 tests/                     unit tests (без внешних сайтов)
```

Небольшие wrappers tools собраны в один registry вместо десятка однотипных файлов.
LLM получает только tool schemas и результаты явно вызванных tools, не `Page`, context,
CSS selectors или tab IDs. `observe_page` отдает URL без query/fragment, title и
счетчики, но не текст страницы и не список элементов. Нужные данные и refs модель выбирает сама
через `query_dom`; ранжирование выполняется локально. Tool calls исполняются последовательно.
Refs вида `e1` — временные, после нового observation старые недействительны.
Не повторяются в пределах session, чтобы старый ref не попал на новый элемент.
При изменении страницы следует вызвать новый `observe_page`.

Внутренний снимок ограничен `MAX_ELEMENTS`, `MAX_TEXT_LENGTH`,
`MAX_ELEMENT_TEXT_LENGTH`. Полный HTML модели не передается. `query_dom` — локальный
текстовый scoring, не отдельный LLM call и не vector DB; он возвращает не более
`MAX_QUERY_RESULTS` элементов/фрагментов и `MAX_QUERY_TEXT_LENGTH` символов текста.
`MAX_CONTEXT_CHARS` ограничивает память между задачами и вытесняет старые записи.
`MAX_AGENT_STEPS` ограничивает работу агента, `MAX_HISTORY_CHARS` — один tool-calling run.

## Tools

| Tool | Аргументы | Назначение |
|---|---|---|
| `navigate_to_url` | `url` | HTTP(S) навигация; обычный URL без `@url` обертки |
| `observe_page` | — | URL без query/fragment, title и счетчики без текста/элементов |
| `query_dom` | `query`, `limit=10` | Выборка релевантного текста и элементов из snapshot |
| `click_element` | `ref` | Проверенный клик по известному элементу |
| `type_text` | `ref`, `text`, `typing=false` | fill или keyboard typing; без Enter |
| `press_key` | `key` | Enter/Tab/Escape/стрелки/Space и ограниченный набор клавиш |
| `scroll_page` | `direction`, `amount=600` | up/down, 1–5000 px |
| `scroll_into_view` | `ref` | Прокрутить к элементу |
| `take_screenshot` | `full_page=false` | PNG, возвращает локальный путь |
| `wait` | `seconds` | 0.1–10 секунд |
| `go_back` | — | Назад по истории |

Ошибки аргументов, timeout, stale/detached refs и закрытые страницы возвращаются
как `success: false`, а не обрушивают agent loop. Скриншоты сохраняются для
человека: данный адаптер **не отправляет изображения модели**.

## Проверка

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest -q                  # unit tests, без браузера и внешних сайтов
uv run pytest -q -m gui           # отдельно: локальные fixtures в видимом браузере
uv run python -m browser_agent --task test  # без .env: понятная ошибка, exit 2
# без LLM, с видимым браузером:
uv run python scripts/browser_smoke.py
# NixOS/Brave:
PLAYWRIGHT_NODEJS_PATH="$(command -v node)" \
BROWSER_EXECUTABLE_PATH="$(command -v brave)" \
uv run python scripts/browser_smoke.py
```

## Ограничения и безопасность

- Запреты оплаты/подтверждения заказа/сообщений/удаления и prompt-injection
  defense содержатся в system prompt. Это **не аппаратная гарантия и не sandbox**:
  универсальный клик может иметь последствия, поэтому следите за демонстрацией.
- Не подключайте чувствительные рабочие аккаунты. Не оставляйте без наблюдения.
- Агент должен проверять итог по странице, но корректность интерпретации зависит от LLM.
- CAPTCHA, anti-bot, адрес доставки, авторизация и платные API требуют участия пользователя.
- Основной механизм — DOM; canvas-only интерфейсы, сложные iframe и нестандартные
  closed shadow DOM могут оказаться недоступны. Нет OCR/координатного vision-агента.
- Локальные, loopback, link-local и literal private-IP URL блокируются по умолчанию.
  Для доверенного локального сайта задайте `ALLOW_PRIVATE_NETWORK=true`.
- Полный AI-проход нельзя проверить без вашей модели и API key. Unit tests
  используют управляемые ответы/fake transport, а не выдуманные реальные API результаты.
