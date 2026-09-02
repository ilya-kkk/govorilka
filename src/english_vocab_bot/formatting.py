from __future__ import annotations

from datetime import date

MAX_TELEGRAM_TEXT_LENGTH = 3900


def format_daily_vocab_message(local_date: date, words: list[str]) -> str:
    header = [
        f"Словарик за {local_date:%d.%m.%Y}",
        "",
        f"Новых слов: {len(words)}",
        "",
    ]
    if not words:
        return "\n".join(
            [
                *header,
                "Пока пусто. Кидай сюда английские слова или фразы, а я буду пополнять список.",
            ]
        )

    lines = [*header]
    hidden_count = 0
    for index, word in enumerate(words, start=1):
        next_line = f"{index}. {word}"
        candidate = "\n".join([*lines, next_line])
        if len(candidate) > MAX_TELEGRAM_TEXT_LENGTH:
            hidden_count = len(words) - index + 1
            break
        lines.append(next_line)

    if hidden_count:
        lines.extend(["", f"...и еще {hidden_count} слов в файле."])

    return "\n".join(lines)


def apkg_filename(local_date: date) -> str:
    return f"english_vocab_{local_date:%Y-%m-%d}.apkg"
