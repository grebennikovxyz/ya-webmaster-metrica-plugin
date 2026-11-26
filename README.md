# Site Desk

[![Boosty](https://img.shields.io/badge/Boosty-F15F2C?style=flat&logo=boosty&logoColor=white)](https://boosty.to/grebennikov.xyz/donate)
[![Релиз](https://img.shields.io/github/v/release/grebennikovxyz/ya-webmaster-metrica-plugin)](https://github.com/grebennikovxyz/ya-webmaster-metrica-plugin/releases/latest)
[![Проверки](https://github.com/grebennikovxyz/ya-webmaster-metrica-plugin/actions/workflows/release.yml/badge.svg)](https://github.com/grebennikovxyz/ya-webmaster-metrica-plugin/actions)

<img src="plugins/site-desk/assets/site-desk.png" width="88" align="right" alt="Карта с маршрутом до входа">

Site Desk помогает владельцу сайта подготовить карточку в Яндекс Бизнесе, подтвердить сайт в Вебмастере, настроить Метрику и объяснить клиенту, как дойти до двери. В основе плагина — локальный MCP-сервер на Python 3.13 и русскоязычный навык для агента.

> «Собери карточку нашей типографии по сайту. Покажи, где нашёл часы работы и адрес. Подготовь цели для звонка и успешно отправленной заявки. Дай разработчику код счётчика и примеры событий».

## Установка

Установите Git и [uv](https://docs.astral.sh/uv/getting-started/installation/). При первом запуске uvx загрузит Python и зависимости. Выберите команды своего клиента.

| Клиент | Команды |
| --- | --- |
| Codex | `codex plugin marketplace add grebennikovxyz/ya-webmaster-metrica-plugin`, затем `codex plugin add site-desk@grebennikov-web` |
| Claude Code | `claude plugin marketplace add grebennikovxyz/ya-webmaster-metrica-plugin`, затем `claude plugin install site-desk@grebennikov-web` |
| OpenClaw | `openclaw plugins install site-desk --marketplace grebennikovxyz/ya-webmaster-metrica-plugin --accept-capabilities` |
| Plugin Creator / локальный исполнитель | Скачайте ZIP с одним плагином со [страницы релизов](https://github.com/grebennikovxyz/ya-webmaster-metrica-plugin/releases/latest). В нём уже лежит wheel сервера. Исполнителю нужны uvx в PATH и подстановка `${PLUGIN_ROOT}`. |

Откройте новый чат и попросите «Покажи подключения Site Desk». Карточка, UTM, ссылки с пешеходным маршрутом и мониторинг публичных полей работают без OAuth. Для терминала установите команду из того же релиза.

```sh
uv tool install --python 3.13 https://github.com/grebennikovxyz/ya-webmaster-metrica-plugin/releases/download/v0.1.0/grebennikov_site_desk-0.1.0-py3-none-any.whl
site-desk connect webmaster
site-desk connect metrica
```

Другие MCP-клиенты могут запустить `site-desk serve` по stdio. Для обновления обновите marketplace и переустановите плагин. [Релизы и контрольные суммы](https://github.com/grebennikovxyz/ya-webmaster-metrica-plugin/releases)

## Подключение сервисов

Создайте приложение владельца в Яндекс OAuth. Выберите права для нужного сервиса и получите токен по инструкции Яндекса. Каждый вызов `connect` принимает значение скрытым вводом в терминале и сохраняет в системной связке ключей. Метрика и Вебмастер могут использовать разные токены. На Linux требуется доступный Secret Service либо переменные окружения в процессе MCP. На Windows используется хранилище учётных данных текущего пользователя. [Яндекс OAuth](https://oauth.yandex.ru/client/new) · [Авторизация Вебмастера](https://yandex.ru/dev/webmaster/doc/ru/tasks/how-to-get-oauth) · [Авторизация Метрики](https://yandex.ru/dev/metrika/ru/intro/authorization)

| Сервис для `site-desk connect` | Доступ | Переменная для автоматизации |
| --- | --- | --- |
| webmaster | `webmaster:hostinfo` для чтения, `webmaster:verify` для управления сайтами | `SITE_DESK_WEBMASTER_TOKEN` |
| metrica | `metrika:read` для отчётов, `metrika:write` для настройки | `SITE_DESK_METRICA_TOKEN` |
| geocoder | Ключ HTTP Геокодера для адресов и ближайшего метро | `SITE_DESK_GEOCODER_KEY` |
| router | Ключ API маршрутизации с доступом к пешеходным маршрутам | `SITE_DESK_ROUTER_KEY` |
| indexnow | Ключ IndexNow, опубликованный владельцем на выбранном домене | `SITE_DESK_INDEXNOW_KEY` |

Права на конкретные сайты и счётчики определяются аккаунтом. Одна локальная конфигурация обслуживает один набор учётных данных, а инструменты принимают выбранные идентификаторы сайта и счётчика. Для отзыва локального доступа выполните `site-desk disconnect SERVICE`, затем отзовите ключ у провайдера. [Кабинет Карт](https://developer.tech.yandex.ru/) · [IndexNow](https://yandex.ru/support/webmaster/ru/indexnow/reference)

## Сценарии

| Задача | Что вы получите |
| --- | --- |
| Заполнить карточку | Поля из JSON-LD, контактов, метаданных и текста на главной и до трёх страниц контактов. У каждого кандидата есть источник. После уточнения филиала и времени работы агент готовит LocalBusiness JSON-LD и помогает перенести данные в кабинет Бизнеса. Сохранение и модерация проходят у владельца в Бизнесе. |
| Подключить поиск | Добавление сайта, выбор метода подтверждения, диагностика, статистика индексации, популярные запросы, Sitemap, квота и очередь переобхода. Поддерживается пакетное уведомление IndexNow. |
| Настроить аналитику | Поиск существующих счётчиков, создание счётчика, автоцели, метки для группировки и UTM для ссылок. На основе действий на сайте агент предлагает URL-цели, JavaScript-события и клики по телефону или email. |
| Передать разработчику | HTML из API Метрики, вызовы reachGoal с фактическим ID, условия срабатывания и проверка установки. Для SPA учитываются виртуальные переходы. |
| Сверить сервисы | Проверка принадлежности Вебмастер-сайта и счётчика домену, сравнение с HTML, список целей и меток, переход к подтверждению связи между кабинетами. Отчёты по источникам, кампаниям, посадочным страницам, датам и конверсиям. |
| Построить карту | Точка входа, кандидаты метро и остановок, онлайн-ссылка на каждый пеший маршрут и GPX для новой карты Конструктора. С ключом маршрутизации — длина и время пути. Для сохранения геометрии требуется подходящая лицензия. |

Для наземного транспорта можно выбрать поиск по открытым данным OpenStreetMap через Overpass. В сервис передаются координаты входа и радиус. При его недоступности укажите точку остановки вручную. Ранжирование по длине пешего маршрута охватывает кандидатов, для которых Routing API вернул путь. Для импорта используйте координаты владельца или данные с правом сохранения. Конструктор принимает GPX с метками и треками на **новую** карту. По ссылке на Яндекс Карты сразу открывается пешеходный маршрут. Закрытые дворы, расположение двери и доступность прохода проверяет владелец. [Конструктор](https://yandex.ru/map-constructor/) · [Импорт GPX](https://yandex.ru/maps-api/docs/constructor/concept/markers_5.html) · [Условия Карт](https://yandex.ru/legal/maps_api/) · [Атрибуция OpenStreetMap](https://www.openstreetmap.org/copyright)

## Дежурный режим

Попросите агента проверять конкретный сайт по расписанию. Первый вызов сохраняет базовые значения. Последующие возвращают изменившиеся поля со старыми и новыми значениями. При неполном обходе сохраняется предыдущая успешная версия. С подключёнными сервисами проверяются также диагностика Вебмастера, цели, метки и видимость ID в HTML. Содержимое JS-приложений и данные уже опубликованной карточки Бизнеса требуют проверки в браузере.

```sh
site-desk watch https://example.org --every 86400
```

Команда работает, пока запущен процесс. Для системного планировщика уберите `--every`. Чтобы включить данные кабинетов, добавьте `--host-id` и `--counter-id`. В режиме повторения команда пишет в stdout JSON со стартовым снимком, изменениями и ошибками. Снимок хранится в `~/.site-desk/state.sqlite3`; каталог можно задать через `SITE_DESK_STATE_DIR`. Данные почты, календаря и Диска обслуживают отдельные плагины.

## Разработка

```sh
uv run --python 3.13 --with pytest pytest -q
uv build --wheel
uv run --python 3.13 python scripts/package.py
```

Тесты используют синтетические данные и проверяют обмен по stdio. Для проверки рабочих записей нужны тестовые сайт, счётчик и учётные данные владельца. [Документация Вебмастера](https://yandex.com/dev/webmaster/) · [Метрика](https://yandex.com/dev/metrika/) · [Карты](https://yandex.com/maps-api/) · [Как организация показывается в поиске](https://yandex.ru/support/webmaster/ru/addresses-organizations/organization-info)

Site Desk — независимый проект Антона Гребенникова. Товарный знак «Яндекс» принадлежит ООО «ЯНДЕКС». [Лицензия](LICENSE) · [Обработка данных](PRIVACY.ru.md) · [Условия использования](TERMS.ru.md) · [Поддержка](https://github.com/grebennikovxyz/ya-webmaster-metrica-plugin/issues)
