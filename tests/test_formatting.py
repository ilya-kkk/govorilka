from __future__ import annotations

from english_voice_bot.formatting import (
    escape_markdown_v2,
    format_review_report,
    format_spoiler_text,
    format_transcription,
    sanitize_telegram_html,
    split_telegram_html,
)


def test_transcript_text_is_html_escaped() -> None:
    rendered = format_transcription("I used <bad> & tags")

    assert "<blockquote>I used &lt;bad&gt; &amp; tags</blockquote>" in rendered


def test_spoiler_text_is_html_escaped() -> None:
    rendered = format_spoiler_text("Try <again> & listen")

    assert rendered == "<tg-spoiler>Try &lt;again&gt; &amp; listen</tg-spoiler>"


def test_sanitize_telegram_html_preserves_allowed_tags_and_escapes_text() -> None:
    rendered = sanitize_telegram_html("<b>Good</b><script>x</script> 2 < 3")

    assert rendered == "<b>Good</b>&lt;script&gt;x&lt;/script&gt; 2 &lt; 3"


def test_sanitize_telegram_html_replaces_br_with_line_break() -> None:
    rendered = sanitize_telegram_html("one<br>two<br />three")

    assert rendered == "one\ntwo\nthree"


def test_escape_markdown_v2_escapes_telegram_special_chars() -> None:
    assert escape_markdown_v2("Hi. Let's talk!") == "Hi\\. Let's talk\\!"


def test_format_review_report_converts_markdown_table_to_markdown_v2() -> None:
    report = """**🔎 Обратная связь по вашим сообщениям**

| № | Оригинальная фраза | Как лучше сказать | Что поправлено |
|---|---------------------|-------------------|----------------|
| 1 | **Hi, let's talk.** | *Hi, let’s talk.* | Убрана лишняя запятая.<br>Фраза стала естественнее. |

### Что уже хорошо 👍
- Используете **let’s talk about…** правильно.
"""

    rendered = format_review_report(report)

    assert "*🔎 Обратная связь по вашим сообщениям*" in rendered
    assert "*№ 1*" in rendered
    assert "*Оригинальная фраза:* *Hi, let's talk\\.*" in rendered
    assert "*Как лучше сказать:* _Hi, let’s talk\\._" in rendered
    assert "Убрана лишняя запятая\\.\nФраза стала естественнее\\." in rendered
    assert "*Что уже хорошо 👍*" in rendered
    assert "• Используете *let’s talk about…* правильно\\." in rendered
    assert "|" not in rendered
    assert "**" not in rendered
    assert "<br" not in rendered
    assert "<b>" not in rendered
    assert "</b>" not in rendered


def test_format_review_report_converts_html_to_markdown_v2() -> None:
    rendered = format_review_report("<b>Report</b>\n<i>Try again.</i>")

    assert rendered == "*Report*\n_Try again\\._"


def test_split_telegram_html_keeps_chunks_under_limit() -> None:
    text = "one two three four five six seven eight nine ten"

    chunks = split_telegram_html(text, limit=12)

    assert all(len(chunk) <= 12 for chunk in chunks)
    assert " ".join(chunk.strip() for chunk in chunks).replace("  ", " ") == text


def test_split_telegram_html_splits_long_unbroken_text() -> None:
    chunks = split_telegram_html("x" * 25, limit=10)

    assert chunks == ["x" * 10, "x" * 10, "x" * 5]
