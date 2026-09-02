from __future__ import annotations

from pathlib import Path
import random

import genanki

from english_vocab_bot.validators import validate_cards


def build_apkg(
    cards: list[tuple[str, str]],
    output_path: Path,
    deck_name: str = "English Vocabulary",
) -> Path:
    validate_cards(cards)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model = genanki.Model(
        random.randrange(1 << 30, 1 << 31),
        "Basic",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
            }
        ],
        css="""
.card {
    font-family: Arial;
    font-size: 24px;
    text-align: center;
    color: black;
    background-color: white;
}
""",
    )
    deck = genanki.Deck(random.randrange(1 << 30, 1 << 31), deck_name)

    for front, back in cards:
        note = genanki.Note(model=model, fields=[front, back])
        deck.add_note(note)

    package = genanki.Package(deck)
    package.write_to_file(str(output_path))
    return output_path
