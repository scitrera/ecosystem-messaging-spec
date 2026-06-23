# Scitrera Ecosystem Messaging Spec

A universal `ChatMessage` / `ToolCall` JSON schema and streaming-event
vocabulary for AI agent platforms — a single, transport-agnostic shape for
chat messages, tool calls/results, and incremental (streamed) updates, with
reference implementations in **Go, Python, and TypeScript** that are
fixture-for-fixture compatible.

It is the wire/at-rest contract used across the Scitrera AI platform, but the
schema itself is generic and dependency-light; any agent runtime, frontend, or
storage layer can adopt it.

## Layout

| Path | Purpose |
| --- | --- |
| `docs/UNIVERSAL_MESSAGE_SPEC.md` | Normative spec (v1.0) — the source of truth |
| `go/` | Go implementation — module `github.com/scitrera/ecosystem-messaging-spec/go` |
| `python/` | Pydantic v2 implementation — `scitrera-messaging-spec` (PyPI) |
| `typescript/` | TS types + pure reducer — `@scitrera/messaging-spec` (npm) |

All three expose the same schema, the same streaming event vocabulary, and an
`apply_event` / `applyEvent` reducer with matching fixtures.

## Install

**Go**
```sh
go get github.com/scitrera/ecosystem-messaging-spec/go
```
```go
import spec "github.com/scitrera/ecosystem-messaging-spec/go"

m := spec.NewChatMessage("msg_1", spec.RoleAssistant)
m.Content = []spec.ContentPart{spec.NewTextPart("hello")}
```

**Python**
```sh
pip install scitrera-messaging-spec
```
```python
from scitrera_messaging_spec import ChatMessage, TextPart
m = ChatMessage(id="msg_1", role="assistant", content=[TextPart(text="hello")])
```

**TypeScript**
```sh
npm install @scitrera/messaging-spec
```
```ts
import { makeChatMessage } from "@scitrera/messaging-spec";
const m = makeChatMessage({ id: "msg_1", role: "assistant",
  content: [{ type: "text", text: "hello" }] });
```

See the per-language READMEs (`go/`, `python/`, `typescript/`) and the
[normative spec](./docs/UNIVERSAL_MESSAGE_SPEC.md) for the full schema and the
streaming-event reducer.

## Status

v1.0 — stable schema across all three languages. See the spec doc for the
normative shape and versioning.

## License

Apache-2.0 — see [LICENSE](./LICENSE) and [NOTICE](./NOTICE).
