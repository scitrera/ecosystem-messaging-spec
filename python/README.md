# scitrera-messaging-spec

Python reference implementation of the Scitrera Ecosystem Messaging Spec
(v1.0).

```python
from scitrera_messaging_spec import (
    ChatMessage, TextPart, ToolCallPart, ToolResultPart,
    apply_event, MessageStarted, PartAppended, TokenDelta,
    to_openai_chat_completion,
)

m = ChatMessage(
    id="msg_1",
    role="assistant",
    content=[
        TextPart(text="hello"),
        ToolCallPart(id="c1", name="get_time", args={}, status="completed"),
        ToolResultPart(call_id="c1", output_text="3pm"),
    ],
)
print(m.model_dump_json())
```

See the [spec](../docs/UNIVERSAL_MESSAGE_SPEC.md) for the normative shape.

## Install

```bash
pip install scitrera-messaging-spec
```

Or, for local development, from a checkout:

```bash
pip install -e python
```
