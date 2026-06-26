from core.ai_client import parse_sse_chat_completion, resolve_docker_host_url


def test_resolve_docker_host_url_maps_localhost_inside_docker() -> None:
    assert (
        resolve_docker_host_url("http://localhost:20128/v1", running_in_docker=True)
        == "http://host.docker.internal:20128/v1"
    )
    assert (
        resolve_docker_host_url("http://127.0.0.1:20128/v1", running_in_docker=True)
        == "http://host.docker.internal:20128/v1"
    )


def test_resolve_docker_host_url_leaves_public_urls_and_host_urls_unchanged() -> None:
    assert (
        resolve_docker_host_url("https://openrouter.ai/api/v1", running_in_docker=True)
        == "https://openrouter.ai/api/v1"
    )
    assert (
        resolve_docker_host_url("http://localhost:20128/v1", running_in_docker=False)
        == "http://localhost:20128/v1"
    )


def test_parse_sse_chat_completion_from_9router_style_response() -> None:
    text = "\n\n".join(
        [
            'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":"{\\"ok\\":"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":" true}"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":2021}}',
            "data: [DONE]",
        ]
    )

    content, tokens = parse_sse_chat_completion(text)

    assert content == '{"ok": true}'
    assert tokens == 2021
