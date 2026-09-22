"""
tests/test_lrc_handler.py — unit tests for the LRC parser/generator.
"""

from __future__ import annotations

import pytest

from audio_suite_shared.lrc_handler import (
    LrcDocument,
    LrcLine,
    LrcMetadata,
    LrcParseError,
    format_timestamp,
    generate_lrc,
    parse_lrc,
    timestamps_ordered,
)


def test_parse_simple_lines_and_meta() -> None:
    text = (
        "[ti:Test Title]\n"
        "[ar:Test Artist]\n"
        "[al:Test Album]\n"
        "[by:Wilte]\n"
        "[00:01.50]Hello\n"
        "[00:03.00]World\n"
    )
    doc = parse_lrc(text)
    assert doc.metadata == LrcMetadata(
        title="Test Title",
        artist="Test Artist",
        album="Test Album",
        creator="Wilte",
    )
    assert doc.lines == (
        LrcLine(timestamp_ms=1500, text="Hello"),
        LrcLine(timestamp_ms=3000, text="World"),
    )


def test_parse_timestamp_math_and_format() -> None:
    doc = parse_lrc("[00:01.50]byte\n[01:05.00]kilo\n[1:02:03.25]mega\n")
    expected = (
        LrcLine(timestamp_ms=1500, text="byte"),
        LrcLine(timestamp_ms=65000, text="kilo"),
        LrcLine(timestamp_ms=3723250, text="mega"),
    )
    assert doc.lines == expected


def test_parse_fraction_is_hundredths() -> None:
    # ".5" is 5 hundredths of a second = 50 ms; ".25" = 250 ms.
    doc = parse_lrc("[00:00.5]five\n[00:00.25]twentyfive\n")
    assert doc.lines[0].timestamp_ms == 50
    assert doc.lines[1].timestamp_ms == 250


def test_parse_multi_timestamp_line_expands() -> None:
    doc = parse_lrc("[00:01.00][00:02.00][00:03.00]sync\n")
    assert doc.lines == (
        LrcLine(timestamp_ms=1000, text="sync"),
        LrcLine(timestamp_ms=2000, text="sync"),
        LrcLine(timestamp_ms=3000, text="sync"),
    )


def test_parse_extended_minutes() -> None:
    doc = parse_lrc("[62:03.00]long track\n")
    assert doc.lines[0].timestamp_ms == 3723000


def test_parse_tolerates_bom_and_crlf() -> None:
    text = "\ufeff[ar:B\u00f6y]\r\n[00:01.00]line one\r\n[00:02.00]line two\r\n"
    doc = parse_lrc(text)
    assert doc.metadata.artist == "B\u00f6y"
    assert doc.lines[0].timestamp_ms == 1000


def test_parse_ignores_blank_and_timestamp_only_lines() -> None:
    doc = parse_lrc("\n[00:01.00]visible\n\n[00:02.00]\n[00:03.00]after\n")
    assert doc.lines == (
        LrcLine(timestamp_ms=1000, text="visible"),
        LrcLine(timestamp_ms=3000, text="after"),
    )


def test_parse_ignores_unknown_meta_tags() -> None:
    text = "[re:some]\n[ve:1.0]\n[au:who]\n[00:01.00]x\n"
    doc = parse_lrc(text)
    assert doc.metadata == LrcMetadata()
    assert len(doc.lines) == 1


def test_parse_offset_positive_negative_and_default() -> None:
    assert parse_lrc("[offset:+500]\n[00:01.00]x\n").metadata.offset_ms == 500
    assert parse_lrc("[offset:-200]\n[00:01.00]x\n").metadata.offset_ms == -200
    assert parse_lrc("[00:01.00]x\n").metadata.offset_ms == 0


def test_parse_malformed_offset_raises() -> None:
    with pytest.raises(LrcParseError, match="offset"):
        parse_lrc("[offset:abc]\n[00:01.00]x\n")


def test_parse_lyric_without_timestamp_raises() -> None:
    with pytest.raises(LrcParseError, match="without a timestamp"):
        parse_lrc("[00:01.00]ok\nplain lyric\n")


def test_parse_blank_only_document() -> None:
    doc = parse_lrc("\n\n")
    assert doc.lines == ()
    assert doc.metadata == LrcMetadata()


def test_parse_last_meta_wins() -> None:
    doc = parse_lrc("[ti:First]\n[ti:Second]\n[00:01.00]x\n")
    assert doc.metadata.title == "Second"


def test_format_timestamp() -> None:
    assert format_timestamp(0) == "00:00.00"
    assert format_timestamp(1500) == "00:01.50"
    assert format_timestamp(60000) == "01:00.00"
    assert format_timestamp(3723000) == "62:03.00"
    assert format_timestamp(99999) == "01:39.99"


def test_format_timestamp_negative_raises() -> None:
    with pytest.raises(ValueError):
        format_timestamp(-1)


def test_generate_lrc_without_metadata() -> None:
    out = generate_lrc([(1500, "Hello"), (3000, "World")])
    assert out == "[00:01.50]Hello\n[00:03.00]World"


def test_generate_lrc_with_metadata() -> None:
    meta = LrcMetadata(title="Hi", artist="Wilte", creator="me", offset_ms=500)
    out = generate_lrc([(1000, "x")], metadata=meta)
    assert out.splitlines()[:4] == ["[ti:Hi]", "[ar:Wilte]", "[by:me]", "[offset:+500]"]
    assert out.splitlines()[4] == "[00:01.00]x"


def test_generate_lrc_skips_empty_meta_and_zero_offset() -> None:
    out = generate_lrc([(1000, "x")], metadata=LrcMetadata(offset_ms=0))
    assert out == "[00:01.00]x"


def test_generate_then_parse_round_trip() -> None:
    lines = [(1500, "Hello"), (3000, "World"), (4520, "Bye")]
    text = generate_lrc(lines, metadata=LrcMetadata(title="T"))
    doc = parse_lrc(text)
    assert doc.lines == tuple(LrcLine(timestamp_ms=ms, text=text) for ms, text in lines)
    assert doc.metadata.title == "T"


def test_timestamps_ordered() -> None:
    ok = parse_lrc("[00:01.00]a\n[00:02.00]b\n[00:02.00]c\n")
    assert timestamps_ordered(ok)
    bad = parse_lrc("[00:03.00]b\n[00:01.00]a\n")
    assert not timestamps_ordered(bad)
    assert timestamps_ordered(LrcDocument(LrcMetadata(), ()))
    solo = parse_lrc("[00:01.00]a\n")
    assert timestamps_ordered(solo)
