# Автономный IT-новостной Telegram-канал

Скрипт раз в день (или с любой другой периодичностью) сам:
1. собирает свежие новости из RSS (`feeds.py`),
2. выбирает через Claude самую значимую,
3. пишет пост, затем сам же его перепроверяет и переписывает,
4. подбирает картинку через Unsplash,
5. публикует в Telegram,
6. запоминает, что уже публиковал, чтобы не повторяться.

Запускается бесплатно через GitHub Actions — свой сервер не нужен.

## Настройка (займёт ~10 минут)

### 1. Создать Telegram-бота
- Написать [@BotFather](https://t.me/BotFather) → `/newbot` → следовать инструкциям.
- Сохранить токен бота — это `TELEGRAM_BOT_TOKEN`.

### 2. Создать канал и добавить бота админом
- Создать Telegram-канал (публичный или приватный).
- Добавить бота в администраторы канала (право "публиковать сообщения").
- Узнать chat_id канала:
  - для публичного канала это просто `@your_channel_name`;
  - для приватного — перешли любое сообщение из канала боту [@userinfobot](https://t.me/userinfobot) или воспользуйся `https://api.telegram.org/bot<ТОКЕН>/getUpdates` после того как что-то напишешь в канал.
- Это будет `TELEGRAM_CHAT_ID`.

### 3. Получить ключ Anthropic API
- [console.anthropic.com](https://console.anthropic.com) → API Keys → создать ключ.
- Это `ANTHROPIC_API_KEY`. Обрати внимание, это платный API (Telegram и GitHub Actions бесплатны, но за токены Claude будет списываться небольшая сумма — при 1 посте в день это копейки).

### 4. (Опционально) Получить ключ Unsplash
- [unsplash.com/developers](https://unsplash.com/developers) → создать приложение → взять Access Key.
- Это `UNSPLASH_ACCESS_KEY`. Без него скрипт просто будет постить без картинки.

### 5. Залить этот код в свой репозиторий на GitHub
```bash
cd tg-it-news
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<твой-юзернейм>/<репозиторий>.git
git push -u origin main
```

### 6. Добавить секреты в репозиторий
Repo → Settings → Secrets and variables → Actions → New repository secret.
Добавить четыре секрета: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `UNSPLASH_ACCESS_KEY` (последний можно пропустить).

### 7. Проверить вручную
Вкладка Actions → workflow "Post IT news to Telegram" → Run workflow.
Если всё настроено верно, в канале появится пост.

Дальше всё будет работать само по расписанию из `post.yml` (сейчас — раз в день в 09:00 UTC).

## Как настроить под себя

- **Периодичность** — поменяй `cron` в `.github/workflows/post.yml`. Например `"0 */6 * * *"` — раз в 6 часов. Формат — как в обычном crontab.
- **Темы/источники** — правь список в `feeds.py`, можно добавить RSS конкретного языка/фреймворка (у большинства репозиториев на GitHub есть `github.com/{repo}/releases.atom`).
- **Язык постов** — переменная `POST_LANGUAGE` в workflow (`ru` или `en`).
- **Несколько постов за раз** — сейчас скрипт публикует одну новость за запуск; если хочешь 3 поста в день — просто поставь `cron` три раза в день, дедупликация через `history.json` не даст повторов.
- **Модель** — переменная `CLAUDE_MODEL`, по умолчанию `claude-sonnet-5`.

## Локальный запуск (для теста перед деплоем)
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export UNSPLASH_ACCESS_KEY=...   # опционально
python main.py
```
