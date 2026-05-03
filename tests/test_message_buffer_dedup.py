from autobots.services.message_buffer.models import (
    RedisKeyBuilder,
    build_buffer_id,
    build_session_id,
)


def test_processed_key_is_stable_for_duplicate_message_id():
    assert RedisKeyBuilder.processed("ABC123") == RedisKeyBuilder.processed("ABC123")
    assert RedisKeyBuilder.processed("ABC123") != RedisKeyBuilder.processed("XYZ789")


def test_processed_key_sanitizes_message_id():
    assert RedisKeyBuilder.processed("abc 123/@bad") == "processed:abc_123_bad"


def test_session_id_groups_by_instance_and_phone():
    assert build_session_id("autobots demo", "+595 981 123456") == "autobots_demo:595_981_123456"


def test_buffer_id_is_deterministic_for_same_events():
    event_ids = ["msg-1", "msg-2"]

    assert build_buffer_id("demo", "595981123456", event_ids) == build_buffer_id(
        "demo",
        "595981123456",
        event_ids,
    )
