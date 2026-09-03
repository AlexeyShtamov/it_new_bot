"""
Автономный постер IT-новостей в Telegram.

Пайплайн одного запуска:
1. Собрать свежие записи из RSS-фидов (feeds.py)
2. Отсеять то, что уже публиковалось (history.json)
3. Отдать Claude список кандидатов -> модель выбирает 1 самую значимую новость
4. Claude пишет черновик поста
5. Claude же перепроверяет и переписывает черновик (убирает "нейро-слоп")
6. Найти картинку по теме через Unsplash
7. Опубликовать в Telegram (фото + подпись, либо просто текст, если фото не нашлось)
8. Записать хэш новости в history.json, чтобы не повторяться

Все настройки — через переменные окружения (см. README.md).
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

from feeds import FEEDS

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
# официальный anthropic SDK — SDK и такой прокси говорят на разных "языках".
# Если переменная не задана — используется официальный Anthropic API напрямую.
ANTHROPIC_BASE_URL = (os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
USING_PROXY = bool(os.environ.get("ANTHROPIC_BASE_URL"))

LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "26"))
POST_LANGUAGE = os.environ.get("POST_LANGUAGE", "ru")  # ru или en
HISTORY_PATH = Path(__file__).parent / "history.json"
HISTORY_KEEP_DAYS = 30


def call_llm(prompt: str, max_tokens: int) -> str:
    """Отправляет один prompt модели и возвращает текст ответа.

    Поддерживает два режима:
    - официальный Anthropic API (/v1/messages, заголовок x-api-key)
    - OpenAI-совместимый прокси реселлера (/chat/completions, Bearer-токен)
    """
    if USING_PROXY:
        resp = requests.post(
            f"{ANTHROPIC_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {ANTHROPIC_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        if not resp.ok:
            print(f"[error] LLM-прокси ответил {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    else:
        resp = requests.post(
            f"{ANTHROPIC_BASE_URL}/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        if not resp.ok:
            print(f"[error] Anthropic API ответил {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"].strip()


# ---------- Шаг 1: сбор новостей ----------

def collect_candidates() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    items = []

    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"[warn] не удалось прочитать {url}: {e}")
            continue

        source_name = feed.feed.get("title", url)

        for entry in feed.entries[:15]:
            published = _entry_time(entry)
            if published and published < cutoff:
                continue

            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = (entry.get("summary") or entry.get("description") or "")[:400]

            if not title or not link:
                continue

            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "source": source_name,
                "hash": _hash_for(title, link),
            })

    print(f"Собрано кандидатов до фильтрации дублей: {len(items)}")
    return items


def _entry_time(entry):
    for field in ("published_parsed", "updated_parsed"):
        t = entry.get(field)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def _hash_for(title: str, link: str) -> str:
    return hashlib.sha256((title + link).encode("utf-8")).hexdigest()


# ---------- Шаг 2: история публикаций ----------

def load_history() -> set[str]:
    if not HISTORY_PATH.exists():
        return set()
    data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_KEEP_DAYS)).isoformat()
    data = [d for d in data if d["date"] > cutoff]
    HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {d["hash"] for d in data}


def append_history(hash_: str, title: str):
    data = []
    if HISTORY_PATH.exists():
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    data.append({
        "hash": hash_,
        "title": title,
        "date": datetime.now(timezone.utc).isoformat(),
    })
    HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Шаг 3: отбор новости моделью ----------

def pick_story(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None

    listing = "\n".join(
        f"{i}. [{c['source']}] {c['title']}\n   {c['summary']}"
        for i, c in enumerate(candidates)
    )

    prompt = f"""Ниже список свежих IT-новостей из разных источников (RSS).
Выбери ОДНУ самую значимую и интересную для широкой IT-аудитории новость:
важные релизы, значимые технологические события, важные инструменты/фреймворки,
крупные изменения в индустрии. Игнорируй мелкие личные блог-посты и рекламу.

Список:
{listing}

Ответь ТОЛЬКО числом — индексом выбранной новости из списка выше. Ничего больше."""

    raw = call_llm(prompt, max_tokens=20)

    try:
        idx = int("".join(ch for ch in raw if ch.isdigit()))
        return candidates[idx]
    except (ValueError, IndexError):
        print(f"[warn] не смог распарсить индекс из ответа модели: {raw!r}, беру первую новость")
        return candidates[0]


# ---------- Шаг 4-5: написание и само-проверка поста ----------

def write_draft(story: dict) -> str:
    lang_note = "на русском языке" if POST_LANGUAGE == "ru" else "in English"

    prompt = f"""Напиши короткий пост для Telegram-канала об IT-новостях, {lang_note}.

Новость: {story['title']}
Источник: {story['source']}
Описание: {story['summary']}
Ссылка: {story['link']}

Требования:
- 3-6 предложений по делу, без вступлений в духе "сегодня хочу рассказать"
- живой, разговорный тон, как будто пишет человек, а не пресс-релиз
- никаких хэштегов и call-to-action в духе "подписывайся"
- в конце — ссылка на источник отдельной строкой
- без markdown-заголовков"""

    return call_llm(prompt, max_tokens=500)


def self_review(draft: str) -> str:
    prompt = f"""Вот черновик поста для Telegram-канала:

---
{draft}
---

Перепиши его, убрав всё, что выдаёт "нейро-слоп": канцелярит, шаблонные фразы
("в мире технологий", "стоит отметить", "это важный шаг вперёд"), избыточные
превосходные степени, искусственный энтузиазм, повторы структуры "не просто X, а Y".
Сделай текст короче и живее, как будто его написал человек, который реально
разбирается в теме и просто делится интересным. Сохрани фактическую точность
и ссылку в конце. Верни только финальный текст поста, без комментариев."""

    return call_llm(prompt, max_tokens=500)


# ---------- Шаг 6: картинка ----------

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
        print(f"[warn] не удалось получить картинку: {e}")
    return None


# ---------- Шаг 7: публикация ----------

def publish(text: str, image_url: str | None):
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    if image_url:
        caption = text[:1024]  # лимит Telegram на подпись к фото
        resp = requests.post(
            f"{base}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "photo": image_url, "caption": caption},
            timeout=30,
        )
        if resp.ok:
            return
        print(f"[warn] sendPhoto не сработал ({resp.text}), пробую просто текст")

    resp = requests.post(
        f"{base}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096]},
        timeout=30,
    )
    resp.raise_for_status()


# ---------- Основной сценарий ----------

def main():
    candidates = collect_candidates()
    already_posted = load_history()
    fresh = [c for c in candidates if c["hash"] not in already_posted]

    print(f"Новых кандидатов после отсева дублей: {len(fresh)}")
    if not fresh:
        print("Нечего постить в этот раз — выхожу.")
        return

    story = pick_story(fresh)
    print(f"Выбрана новость: {story['title']}")

    draft = write_draft(story)
    final_text = self_review(draft)
    print("---- итоговый текст ----")
    print(final_text)
    print("------------------------")

    image_url = find_image(story["title"])
    publish(final_text, image_url)

    append_history(story["hash"], story["title"])
    print("Готово, опубликовано.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Пайплайн упал с ошибкой:", file=sys.stderr)
        raise
