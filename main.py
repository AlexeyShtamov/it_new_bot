"""
Автономный образовательный Telegram-канал по backend/Java/Go/архитектуре/AI.

Пайплайн одного запуска:
1. Выбрать тему, которая ещё не была раскрыта (topics.py + history.json)
2. Написать по ней экспертный пост (в стиле Shtamov.dev)
3. Само-проверка: сверить пост со структурой и форматом
4. Придумать короткий англоязычный поисковый запрос под смысл поста
   и подобрать по нему картинку через Unsplash
5. Опубликовать в Telegram (фото + подпись, либо просто текст, если фото
   не нашлось)
6. Запомнить тему в history.json, чтобы не повторяться

Все настройки — через переменные окружения (см. README.md).
"""

import hashlib
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from topics import TOPICS

# ---------- Настройки ----------

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

MODEL = os.environ.get("CLAUDE_MODEL") or "claude-sonnet-5"
# Если используешь ключ от стороннего реселлера/прокси (не напрямую с
# console.anthropic.com) — укажи его адрес через секрет ANTHROPIC_BASE_URL,
# например https://api.apibazaar.shop/v1. Такие прокси обычно эмулируют
# OpenAI-совместимый Chat Completions API, а не нативный Anthropic API,
# поэтому запрос собирается вручную (см. call_llm ниже), а не через
# официальный anthropic SDK.
# Если переменная не задана — используется официальный Anthropic API напрямую.
ANTHROPIC_BASE_URL = (os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
USING_PROXY = bool(os.environ.get("ANTHROPIC_BASE_URL"))

HISTORY_PATH = Path(__file__).parent / "history.json"
HISTORY_KEEP_DAYS = 90  # темы не повторяются в течение ~3 месяцев

STYLE_SYSTEM_PROMPT = """Ты — опытный backend-разработчик и автор технического Telegram-канала.
Твоя задача: написать экспертный, образовательный пост без "воды" на переданную пользователем тему.
ОБЯЗАТЕЛЬНАЯ СТРУКТУРА ПОСТА:
1. Заголовок: Начни с одного эмодзи (например: 🧠, ⚙️, 🚀, 🛠) и напиши цепляющий заголовок. Это должен быть либо конкретный вопрос (например, «Как под капотом работает ConcurrentHashMap?»), либо подборка («Топ-5 паттернов в микросервисах»). Выдели заголовок **жирным шрифтом**.
2. Вводная часть: 1-2 коротких предложения. Строго по делу: о чем пост и в каких реальных задачах это применяется.
3. Основная часть (Мясо): Список конкретных фактов, советов или механик работы.
   - Каждый пункт начинай с эмодзи чекбокса (✅ или ☑️).
   - Пиши максимально плотно: используй правильную терминологию, упоминай алгоритмы, структуры данных или особенности фреймворка.
   - Избегай банальностей (не пиши "пишите чистый код" или "используйте ООП"). Фокус на хардах и архитектуре.
4. Тег: Последняя строка поста ВСЕГДА должна быть: @Shtamov.dev
ПРАВИЛА ФОРМАТИРОВАНИЯ И ОГРАНИЧЕНИЙ:
- Тон: Профессиональный, четкий, как техническая документация, но написанная человеческим языком.
- Выделяй **жирным** шрифтом ключевые концепции, названия классов (например, **ConcurrentHashMap**), интерфейсов или технологий.
- Используй `обратные кавычки` для inline-кода, названий методов или переменных (например, `put()`, `O(1)`).
- Выводи ТОЛЬКО готовый текст поста. Никаких приветствий, подтверждений или рассуждений от лица ИИ.
Сырая тема для поста будет передана в следующем сообщении."""


def call_llm(prompt: str, max_tokens: int, system: str | None = None) -> str:
    """Отправляет один prompt модели (опционально с system-инструкцией) и
    возвращает текст ответа.

    Поддерживает два режима:
    - официальный Anthropic API (/v1/messages, заголовок x-api-key)
    - OpenAI-совместимый прокси реселлера (/chat/completions, Bearer-токен)
    """
    if USING_PROXY:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = requests.post(
            f"{ANTHROPIC_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {ANTHROPIC_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": MODEL, "max_tokens": max_tokens, "messages": messages},
            timeout=60,
        )
        if not resp.ok:
            print(f"[error] LLM-прокси ответил {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    else:
        payload = {
            "model": MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        resp = requests.post(
            f"{ANTHROPIC_BASE_URL}/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        if not resp.ok:
            print(f"[error] Anthropic API ответил {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"].strip()


# ---------- Шаг 1: выбор темы ----------

def _hash_topic(topic: str) -> str:
    return hashlib.sha256(topic.strip().lower().encode("utf-8")).hexdigest()


def load_history() -> set[str]:
    if not HISTORY_PATH.exists():
        return set()
    data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_KEEP_DAYS)).isoformat()
    data = [d for d in data if d["date"] > cutoff]
    HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {d["hash"] for d in data}


def append_history(topic: str):
    data = []
    if HISTORY_PATH.exists():
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    data.append({
        "hash": _hash_topic(topic),
        "topic": topic,
        "date": datetime.now(timezone.utc).isoformat(),
    })
    HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pick_topic(used: set[str]) -> str:
    candidates = [t for t in TOPICS if _hash_topic(t) not in used]
    if candidates:
        return random.choice(candidates)

    # Все темы из списка уже раскрыты — просим модель придумать новую,
    # избегая уже использованных.
    already = "\n".join(f"- {t}" for t in TOPICS[:30])
    prompt = f"""Придумай ОДНУ новую тему для образовательного поста про backend,
Java, Go, программную архитектуру или ИИ/LLM-инженерию для бэкендеров.
Тема должна быть конкретной, "хардовой", не банальной — уровень мидл/сеньор
разработчика. Не повторяй темы из списка ниже:
{already}

Ответь ТОЛЬКО формулировкой темы, одной строкой, без кавычек и пояснений."""
    return call_llm(prompt, max_tokens=60)


# ---------- Шаг 2-3: написание и само-проверка поста ----------

def write_post(topic: str) -> str:
    return call_llm(topic, max_tokens=800, system=STYLE_SYSTEM_PROMPT)


def self_review(draft: str) -> str:
    prompt = f"""Вот черновик поста:
---
{draft}
---
Сверь его со структурой и правилами форматирования из своей системной
инструкции (эмодзи + жирный заголовок, короткая вводная часть, пункты
через ✅/☑️ с плотной терминологией без банальностей, обратные кавычки для
кода/методов, тег @Shtamov.dev последней строкой). Если что-то нарушено —
исправь. Верни только финальный текст поста, без комментариев."""
    return call_llm(prompt, max_tokens=800, system=STYLE_SYSTEM_PROMPT)


# ---------- Шаг 4: подбор картинки под смысл поста ----------

def image_query_for(topic: str) -> str:
    """Просит модель придумать короткий англоязычный поисковый запрос для
    Unsplash, подходящий по смыслу к абстрактной технической теме — дословный
    перевод темы почти никогда не даёт хороших результатов в фотостоке."""
    prompt = f"""Тема технического поста: "{topic}".
Придумай короткий (2-4 слова) поисковый запрос НА АНГЛИЙСКОМ для Unsplash,
чтобы подобрать абстрактную, стильную обложку к этому посту. Не переводи
термины дословно — думай об ассоциациях: серверная, код на экране,
дата-центр, сеть, микросхемы, абстрактная технологичная картинка и т.п.
Ответь только запросом, без кавычек и пояснений."""
    query = call_llm(prompt, max_tokens=20)
    return query.strip().strip('"').strip("'")


def find_image(query: str) -> str | None:
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            return results[0]["urls"]["regular"]
    except Exception as e:
        print(f"[warn] не удалось получить картинку по запросу {query!r}: {e}")
    return None


# ---------- Шаг 5: публикация ----------

def to_telegram_markdown(text: str) -> str:
    """Telegram (legacy Markdown) понимает *жирный* одной звёздочкой,
    а модель по привычке пишет **жирный** двумя — конвертируем."""
    return text.replace("**", "*")


def publish(text: str, image_url: str | None):
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    text = to_telegram_markdown(text)

    if image_url:
        caption = text[:1024]  # лимит Telegram на подпись к фото
        resp = requests.post(
            f"{base}/sendPhoto",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "photo": image_url,
                "caption": caption,
                "parse_mode": "Markdown",
            },
            timeout=30,
        )
        if resp.ok:
            return
        print(f"[warn] sendPhoto с разметкой не сработал ({resp.text}), пробую без разметки")
        resp = requests.post(
            f"{base}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "photo": image_url, "caption": caption},
            timeout=30,
        )
        if resp.ok:
            return
        print(f"[warn] sendPhoto всё равно не сработал ({resp.text}), пробую просто текст")

    resp = requests.post(
        f"{base}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096], "parse_mode": "Markdown"},
        timeout=30,
    )
    if resp.ok:
        return
    print(f"[warn] sendMessage с разметкой не сработал ({resp.text}), пробую без разметки")
    resp = requests.post(
        f"{base}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096]},
        timeout=30,
    )
    resp.raise_for_status()


# ---------- Основной сценарий ----------

def main():
    used = load_history()
    topic = pick_topic(used)
    print(f"Выбрана тема: {topic}")

    draft = write_post(topic)
    final_text = self_review(draft)
    print("---- итоговый текст ----")
    print(final_text)
    print("------------------------")

    image_query = image_query_for(topic)
    print(f"Поисковый запрос для картинки: {image_query}")
    image_url = find_image(image_query)

    publish(final_text, image_url)

    append_history(topic)
    print("Готово, опубликовано.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Пайплайн упал с ошибкой:", file=sys.stderr)
        raise
