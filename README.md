# Random Coffee Bot

Telegram-бот для поддержания связи с важными контактами. Напоминает, когда пора написать, и помогает не терять связь с нужными людьми.

## Возможности

- **Управление контактами** — добавление, редактирование, удаление с описанием и тегами
- **Гибкие напоминания** — ежедневно, раз в неделю, раз в 2 недели, раз в месяц, произвольный интервал или конкретная дата
- **AI-поиск** — семантический поиск по контактам на естественном языке
- **Пересланные сообщения** — переслал сообщение от человека → бот предложит добавить в контакты
- **Расписание уведомлений** — утреннее (11:00) и вечернее (19:00) напоминание, еженедельная статистика по воскресеньям
- **AI-парсинг** — автоматическое извлечение тегов из описания и распознавание дат на естественном языке

## Стек

- Python 3.11
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — Telegram Bot API
- [Supabase](https://supabase.com/) — PostgreSQL база данных
- [OpenAI API](https://platform.openai.com/) — семантический поиск, парсинг контактов и дат
- [pydantic-settings](https://github.com/pydantic/pydantic-settings) — конфигурация через `.env`

## Установка

```bash
git clone <repo-url>
cd random_coffee_bot
pip install -r requirements.txt
```

## Настройка

Скопируй `.env.example` в `.env` и заполни переменные:

```bash
cp .env.example .env
```

| Переменная | Описание |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота от [@BotFather](https://t.me/BotFather) |
| `SUPABASE_URL` | URL проекта Supabase |
| `SUPABASE_KEY` | Anon-ключ Supabase |
| `OPENAI_API_KEY` | API-ключ OpenAI |

## Запуск

```bash
python -m src.main
```

### Docker

```bash
docker build -t random-coffee-bot .
docker run --env-file .env random-coffee-bot
```

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие и главное меню |
| `/add` | Добавить контакт (`@username описание`) |
| `/list` | Список всех контактов |
| `/search` | Поиск по контактам |
| `/edit @username` | Редактировать контакт |
| `/menu` | Главное меню |
| `/cancel` | Отменить текущую операцию |

## Деплой

Проект развёрнут на сервере, арендованном через [UFO Hosting](https://ufo.hosting/).

## Структура проекта

```
src/
├── main.py                  # Точка входа
├── config.py                # Конфигурация (env-переменные)
├── bot/
│   ├── app.py               # Настройка приложения и роутинг сообщений
│   ├── keyboards.py         # Inline-клавиатуры
│   ├── messages.py          # Шаблоны сообщений
│   ├── handlers/
│   │   ├── start.py         # /start, /help, /menu
│   │   ├── contacts.py      # /add, /list, /edit, /search
│   │   ├── search.py        # AI-поиск по контактам
│   │   ├── callbacks.py     # Обработка inline-кнопок
│   │   └── forwarded.py     # Пересланные сообщения
│   └── parsers/
│       └── frequency.py     # Парсинг частоты и дат
├── db/
│   ├── engine.py            # Supabase-клиент
│   ├── models.py            # Модели данных
│   └── repositories/
│       ├── base.py          # Базовый репозиторий
│       ├── users.py         # Репозиторий пользователей
│       └── contacts.py      # Репозиторий контактов
├── services/
│   └── ai_service.py        # OpenAI: поиск, парсинг, даты
└── scheduler/
    ├── setup.py             # Настройка планировщика
    └── jobs.py              # Утренние/вечерние напоминания, статистика
```
