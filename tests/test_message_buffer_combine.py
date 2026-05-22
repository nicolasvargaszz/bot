from datetime import UTC, datetime, timedelta

from autobots.services.message_buffer.models import (
    BufferedMessage,
    MessageType,
    combine_buffered_messages,
)


def test_combine_buffered_messages_in_timestamp_order():
    base = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    messages = [
        BufferedMessage(
            instance="autobots-demo",
            phone="595981123456",
            message_id="msg-2",
            timestamp=base + timedelta(seconds=2),
            message_type=MessageType.TEXT,
            text="Nico",
        ),
        BufferedMessage(
            instance="autobots-demo",
            phone="595981123456",
            message_id="msg-1",
            timestamp=base,
            message_type=MessageType.TEXT,
            text="Hola",
            push_name="Nico",
        ),
        BufferedMessage(
            instance="autobots-demo",
            phone="595981123456",
            message_id="msg-3",
            timestamp=base + timedelta(seconds=3),
            message_type=MessageType.TEXT,
            text="Como estas?",
        ),
    ]

    payload = combine_buffered_messages(messages)

    assert payload.combined_text == "Hola Nico Como estas?"
    assert payload.message_count == 3
    assert payload.event_ids == ["msg-1", "msg-2", "msg-3"]
    assert payload.push_name == "Nico"
    assert payload.contains_audio is False


def test_combine_includes_audio_metadata_without_transcribing():
    base = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    messages = [
        BufferedMessage(
            instance="autobots-demo",
            phone="595981123456",
            message_id="text-1",
            timestamp=base,
            message_type=MessageType.TEXT,
            text="Hola",
        ),
        BufferedMessage(
            instance="autobots-demo",
            phone="595981123456",
            message_id="audio-1",
            timestamp=base + timedelta(seconds=1),
            message_type=MessageType.AUDIO,
            audio={"url": "https://example.test/audio.ogg", "mime_type": "audio/ogg"},
        ),
    ]

    payload = combine_buffered_messages(messages)

    assert payload.combined_text == "Hola"
    assert payload.contains_audio is True
    assert payload.audio_messages[0]["message_id"] == "audio-1"
    assert payload.audio_messages[0]["audio"]["url"] == "https://example.test/audio.ogg"


def test_combine_audio_transcription_with_follow_up_text():
    base = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    messages = [
        BufferedMessage(
            instance="autobots-demo",
            phone="595981123456",
            message_id="audio-1",
            timestamp=base,
            message_type=MessageType.AUDIO,
            text="[Audio transcription]: Hola, estoy interesado en el departamento.",
            audio={"transcription_status": "success"},
        ),
        BufferedMessage(
            instance="autobots-demo",
            phone="595981123456",
            message_id="text-1",
            timestamp=base + timedelta(seconds=1),
            message_type=MessageType.TEXT,
            text="Me pasas mas info?",
        ),
    ]

    payload = combine_buffered_messages(messages)

    assert (
        payload.combined_text
        == "[Audio transcription]: Hola, estoy interesado en el departamento. Me pasas mas info?"
    )
