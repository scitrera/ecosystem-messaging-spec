# messaging-spec (Go)

Go reference implementation of the Scitrera Ecosystem Messaging Spec (v1.0):
the `ChatMessage` / `ToolCall` schema, the streaming `StreamEvent` vocabulary,
and an `ApplyEvent` reducer — mirroring the Python and TypeScript packages.

## Install

```sh
go get github.com/scitrera/ecosystem-messaging-spec/go
```

```go
import spec "github.com/scitrera/ecosystem-messaging-spec/go"

m := spec.NewChatMessage("msg_1", spec.RoleAssistant)
m.Content = []spec.ContentPart{
    spec.NewTextPart("hello"),
    spec.NewToolCallPart(spec.ToolCallPartBody{ID: "c1", Name: "now"}),
}
```

See the [normative spec](../docs/UNIVERSAL_MESSAGE_SPEC.md) for the full schema
and the streaming-event reducer.
