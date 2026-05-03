from autobots.services.message_buffer.models import EvolutionWebhookParser, MessageType


def test_parse_evolution_text_message():
    payload = {
        "instance": "autobots-demo",
        "data": {
            "key": {
                "remoteJid": "595981123456@s.whatsapp.net",
                "fromMe": False,
                "id": "msg-1",
            },
            "pushName": "Nico",
            "messageTimestamp": 1_714_000_000,
            "message": {
                "conversation": " Hola   Nico ",
            },
        },
    }

    result = EvolutionWebhookParser.parse(payload)

    assert result.accepted is True
    assert result.message is not None
    assert result.message.instance == "autobots-demo"
    assert result.message.phone == "595981123456"
    assert result.message.message_id == "msg-1"
    assert result.message.message_type == MessageType.TEXT
    assert result.message.text == "Hola Nico"
    assert result.message.push_name == "Nico"


def test_parse_evolution_audio_message_metadata():
    payload = {
        "instance": "autobots-demo",
        "data": {
            "key": {
                "remoteJid": "595981123456@s.whatsapp.net",
                "fromMe": False,
                "id": "audio-1",
            },
            "message": {
                "audioMessage": {
                    "url": "https://example.test/audio.ogg",
                    "mimetype": "audio/ogg",
                    "seconds": 4,
                    "ptt": True,
                },
            },
        },
    }

    result = EvolutionWebhookParser.parse(payload)

    assert result.accepted is True
    assert result.message is not None
    assert result.message.message_type == MessageType.AUDIO
    assert result.message.audio is not None
    assert result.message.audio["url"] == "https://example.test/audio.ogg"
    assert result.message.audio["mime_type"] == "audio/ogg"


def test_parse_ignores_from_me_messages():
    payload = {
        "instance": "autobots-demo",
        "data": {
            "key": {
                "remoteJid": "595981123456@s.whatsapp.net",
                "fromMe": True,
                "id": "msg-from-me",
            },
            "message": {
                "conversation": "This was sent by our own instance",
            },
        },
    }

    result = EvolutionWebhookParser.parse(payload)

    assert result.accepted is False
    assert result.reason == "message_from_self"


def test_parse_ignores_group_messages():
    payload = {
        "instance": "autobots-demo",
        "data": {
            "key": {
                "remoteJid": "120363123456@g.us",
                "fromMe": False,
                "id": "group-msg",
            },
            "message": {
                "conversation": "Group message",
            },
        },
    }

    result = EvolutionWebhookParser.parse(payload)

    assert result.accepted is False
    assert result.reason == "group_message_ignored"
