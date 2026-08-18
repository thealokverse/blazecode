from blazecode.agent.errors import (
    FailureKind,
    backoff_seconds,
    classify_error,
    should_retry,
)


def test_classify_error_kinds() -> None:
    assert classify_error("interrupted") is FailureKind.USER_ABORT
    assert classify_error("HTTP 401: invalid api key") is FailureKind.AUTH_ERROR
    assert classify_error("rate limit: HTTP 429") is FailureKind.RATE_LIMIT
    assert classify_error("context overflow: too many tokens") is FailureKind.CONTEXT_OVERFLOW
    assert classify_error("connection reset by peer") is FailureKind.NETWORK_ERROR
    assert classify_error("command timed out after 12s") is FailureKind.TOOL_TIMEOUT
    assert classify_error("empty model response") is FailureKind.INVALID_MODEL_RESPONSE
    assert classify_error("provider failure: boom") is FailureKind.PROVIDER_ERROR


def test_retry_policy_is_bounded() -> None:
    assert should_retry(FailureKind.NETWORK_ERROR, 0)
    assert should_retry(FailureKind.RATE_LIMIT, 2)
    assert not should_retry(FailureKind.RATE_LIMIT, 3)
    assert not should_retry(FailureKind.AUTH_ERROR, 0)
    assert not should_retry(FailureKind.PROVIDER_ERROR, 0)
    assert backoff_seconds(0) == 0.5
    assert backoff_seconds(4) == 8.0
