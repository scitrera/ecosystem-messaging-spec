# @scitrera/messaging-spec

TypeScript reference implementation of the Scitrera Ecosystem Messaging
Spec (v1.0).

```ts
import {
    type ChatMessage,
    type StreamEvent,
    applyEvent,
    makeChatMessage,
    MESSAGING_SCHEMA_VERSION,
} from "@scitrera/messaging-spec";

const m: ChatMessage = makeChatMessage({
    id: "msg_1",
    role: "assistant",
    content: [
        {type: "text", text: "hello"},
        {type: "tool_call", id: "c1", name: "now", args: {}, status: "completed"},
        {type: "tool_result", call_id: "c1", output_text: "3pm", is_error: false},
    ],
});
```

See the [spec](../docs/UNIVERSAL_MESSAGE_SPEC.md) for the normative
shape and the streaming event vocabulary.

## Install

```bash
npm install @scitrera/messaging-spec
```

Then `import {ChatMessage} from "@scitrera/messaging-spec";`.
