from app.llm import parse_llm_turn


def test_parse_llm_turn_reads_reply_and_notes() -> None:
    turn = parse_llm_turn(
        '{"reply":"Nice — what did you buy?","notes":["You said: I was in Turkey.","Better: I went to Turkey."]}',
    )
    assert turn.reply_text == "Nice — what did you buy?"
    assert turn.notes == ["You said: I was in Turkey.", "Better: I went to Turkey."]


def test_parse_llm_turn_empty_notes() -> None:
    turn = parse_llm_turn('{"reply":"Sounds good. What next?","notes":[]}')
    assert turn.reply_text == "Sounds good. What next?"
    assert turn.notes == []


def test_parse_llm_turn_caps_notes_at_three() -> None:
    turn = parse_llm_turn(
        '{"reply":"Ok","notes":["a","b","c","d"]}',
    )
    assert turn.notes == ["a", "b", "c"]
