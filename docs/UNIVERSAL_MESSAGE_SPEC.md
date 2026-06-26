# Universal `ChatMessage` & `ToolCall` Spec — v1.0

**Status:** Approved. Reference implementations live in `go/`, `python/`, and
`typescript/` of this repo.

## 0. Why

Every consumer in the Scitrera platform invents its own chat-message shape:

- **Aether** has a `MessageType` enum (`CHAT=1`, `TOOL_CALL=3`) on
  `SendMessage`/`IncomingMessage`, but `payload` is opaque bytes — no
  enforced schema.
- **Backend `rt_schema.MessageContent`** is text-first with bolt-on
  `attachments`/`documents`/`dynamic` fields and no native tool-call shape.
- **Cowork** persists a different shape: ordered list of typed blocks
  (`text | tool_call | tool_result | dynamic | attachment | citation`).
  Citations leak in through an ad-hoc `__COWORK_CITATIONS__` suffix.
- **Frontend** keeps `attachments`, `documents`, `citations`, `toolCalls`,
  `dynamic`, plus a `segments` (intersperse) model with per-tool-block
  `status`.
- **Office add-in** uses a similar but divergent shape over JSON-RPC.
- **Workclaw** has no chat schema yet.
- **Local agent** is MCP-only, no chat protocol.

Result: every cross-boundary hop needs a converter; citations and
attachments are non-portable; a new consumer can't reason about an at-rest
message without reading three other repos.

**Goal:** one JSON schema for `ChatMessage` and the tool-call/tool-result
content parts that lives unchanged across MemoryLayer-at-rest, Aether
wire, WebSocket relay, frontend state, office add-in state, and workclaw.
Aether and MemoryLayer remain payload-agnostic — they carry the JSON.
Consumers agree on the shape.

## 1. Design decisions

1. **Inline content-block list.** Every message has
   `content: ContentPart[]`. Tool calls and tool results are content parts
   in the same ordered list as text, citations, files, etc.
2. **One canonical message + a small delta-event vocabulary.** At-rest
   and final-form-over-the-wire messages are the same JSON. Streaming
   uses `message_started`, `part_appended`, `token_delta`, `part_updated`,
   `message_finalized`.
3. **References-only for binary content.** `image`/`file` carry
   `vfs_ref` or `uri`. Inline `data_uri` is an escape hatch for small
   images only.
4. **Aether stays opaque.** `MessageType.CHAT` and `TOOL_CALL` continue
   to classify routing. The convention is "payload is UTF-8 JSON of a
   `ChatMessage`"; Aether does not validate.

## 2. `ChatMessage`

```jsonc
{
  "schema_version": "1.0",
  "id": "msg_01J...",
  "role": "user" | "assistant" | "system" | "tool",
  "created_at": "2026-05-26T15:30:00Z",
  "content": [ ContentPart, ... ],
  "addr":   MessageAddress,
  "meta":   { ... },
  "ref":    { parent_id?, in_reply_to?, edits_id? }
}
```

- `id` — globally unique. ULID preferred (sortable), UUID accepted.
- `role` — covers OpenAI's four roles. When `role === "tool"`, `content`
  must contain exactly one `tool_result` part. Spec-native consumers
  should prefer placing `tool_result` parts on an `assistant` message
  (matches cowork's persisted shape); the standalone `tool` role exists
  for OpenAI-classic interop.
- `created_at` — RFC3339 UTC commit time, *not* first-token time.
  Implementations MUST support setting `created_at` with at least
  second-level precision and SHOULD accept fractional second precision
  (millisecond, microsecond, or nanosecond) on read.
- `addr` — flat routing/indexing metadata; see §4.
- `meta` — open extension namespace; see §5.
- `ref` — optional inter-message relationships (see §5.5).

## 3. `ContentPart` — discriminated union on `type`

### 3.1 `text`
```jsonc
{ "type": "text", "text": "...", "annotations": [...]? }
```
`annotations` is reserved for inline spans (citations, links, hover
cards); shape mirrors OpenAI Responses `output_text` annotations.

### 3.2 `image`
```jsonc
{
  "type": "image",
  "mime": "image/png",
  "vfs_ref": "vfs://...",  // OR
  "uri":     "https://...", // OR
  "data_uri":"data:image/png;base64,..."  // escape hatch
}
```
Exactly one of `vfs_ref | uri | data_uri` must be set. Optional
`alt_text`.

### 3.3 `file`
```jsonc
{
  "type": "file",
  "vfs_ref": "vfs://...",
  "mime": "application/pdf",
  "file_name": "Q3-report.pdf",
  "size_bytes": 184320,
  "purpose": "attachment" | "document" | "generated"
}
```
`purpose` collapses cowork's current attachments-vs-documents-vs-output
distinction into one tag. Audio/video binaries use `file` with the
appropriate `mime`.

### 3.4 `tool_call`
```jsonc
{
  "type": "tool_call",
  "id": "call_01J...",
  "name": "vfs_fetch",
  "args": { ... },
  "status": "pending" | "running" | "completed" | "failed" | "cancelled",
  "started_at": "...",
  "finished_at": "..."?,
  "meta": { ... }
}
```
`args` is a **dict** (not a JSON string). Consumers that need OpenAI's
string-encoded form can `JSON.stringify(args)` at the edge.

### 3.5 `tool_result`
```jsonc
{
  "type": "tool_result",
  "call_id": "call_01J...",
  "name": "vfs_fetch",
  "output": <any JSON>,
  "output_text": "...",
  "is_error": false,
  "error": { "type": "...", "message": "..." }?
}
```
`output` carries the structured tool return; `output_text` is the
LLM-consumable rendering. Set `output_text` only when the structured
value isn't already a string.

### 3.6 `citation`
```jsonc
{
  "type": "citation",
  "id": "cit_1",
  "source": "vfs://..." | "https://...",
  "title": "...",
  "snippet": "...",
  "span": [start, end]?,
  "meta": { ... }
}
```
Replaces the `__COWORK_CITATIONS__` suffix and the per-message citation
array on the frontend. Visual pairing comes from list order: a
`citation` part pairs with the closest preceding `text` part by
default.

### 3.7 `dynamic`
```jsonc
{
  "type": "dynamic",
  "kind": "jsx" | "tool_call_progress" | "<custom>",
  "payload": { ... },
  "interactive": false
}
```
Replacement for the frontend's `DYNAMIC_JSX` content and
`chat/progress_notify` blocks. `kind` is an open registry — each
consumer ships its own renderer for the kinds it supports.

### 3.8 `reasoning` *(opt-in)*
```jsonc
{ "type": "reasoning", "text": "...", "redacted": false }
```
Reserved slot for OpenAI o-series / Anthropic extended thinking. Most
consumers should hide-by-default.

### 3.9 `subagent`
```jsonc
{
  "type": "subagent",
  "id": "sub_1",                  // unique within parent message
  "name": "researcher",            // agent template / role name
  "thread_id": "thr_sub_001",      // points to the subagent's own thread
  "input": { ... },                // optional structured input
  "status": "pending" | "running" | "completed" | "failed" | "cancelled",
  "summary": "...",                // optional one-line summary (set on completion)
  "started_at": "...",
  "finished_at": "..."?,
  "meta": { ... }
}
```

A `subagent` part is a reference, not a containment. The subagent's
full conversation lives on its **own thread** (identified by
`thread_id`) and is persisted as ordinary `ChatMessage` records in
MemoryLayer. Messages on that child thread back-reference the spawning
message via [`MessageRef.parent_thread_id`](#4-messageaddress) +
`MessageRef.parent_message_id`.

This design is what lets the spec scale to arbitrarily deep delegation
without recursive content parts:
- The parent message stays small — only the reference + a summary.
- Streaming the subagent doesn't bloat the parent's stream events.
- Recall semantics are uniform — "what did the researcher say?" is just
  a thread query.

Streaming for a `subagent` part typically looks like: parent emits
`part_appended` with `status: "running"`, the child thread streams its
own messages (no parent updates needed during the work), and the
parent emits `part_updated` with `{status: "completed", summary: "..."}`
when the subagent reports completion.

### 3.11 `control`
```jsonc
{
  "type": "control",
  "kind": "cancel" | "<future>",
  "task_id": "task_..."?
}
```

An in-band control signal carried on a chat message. Used for control
flow that must travel on the same wire as the conversation rather than
over a separate side channel — typically cancel, but reserved for
future pause/resume/configure/etc.

Carrier role: `system`. A message that carries only `control` parts
SHOULD use `role: "system"`. Mixing `control` with `text` is permitted
(consumers MUST route on the first `control` part and MAY ignore the
text), but spec-native producers should emit pure-control messages
when the intent is a control signal.

`kind` is an open registry. Required fields per known kind:

| `kind`   | Required           | Notes                                                     |
| -------- | ------------------ | --------------------------------------------------------- |
| `cancel` | `task_id`          | Abort the named task. Targets the agent owning that task. |

Forward-compat: consumers MUST preserve unknown `kind` values on
round-trip (per §3.10) and SHOULD ignore kinds they don't recognize
rather than erroring. Adding a new control `kind` does not bump
`schema_version`.

Example — cancel signal:

```json
{
  "schema_version": "1.0",
  "id": "msg_cancel_1",
  "role": "system",
  "addr": {"workspace_id": "w1", "thread_id": "th1", "task_id": "task_xyz"},
  "content": [{"type": "control", "kind": "cancel", "task_id": "task_xyz"}],
  "meta": {}
}
```

### 3.12 `feedback`
```jsonc
{
  "type": "feedback",
  "sentiment": -1 | 0 | 1 | <other int>,
  "text": "optional free-form reason"?
}
```

User feedback on another message, carried as a content part. A feedback
"message" is a `ChatMessage` whose `content` is a single `FeedbackPart`
and whose `ref.message_id` points at the target message being rated.
The carrier role is `"user"` (the user is the actor) and
`ref.relationship` is `"feedback"`.

Semantics: feedback is **non-conversational metadata about another
message**. It is persisted to MemoryLayer for analytics, but the
LangChain adapter (`to_lc_messages`) skips messages whose `content` is
non-empty and contains only `FeedbackPart`(s) so the model never sees
feedback as conversational input on resume. Adapters that target
storage (e.g. `to_memorylayer_payload`) still preserve feedback
messages — that's the whole point of persisting them.

`sentiment` is an integer, not a `Literal` enum: the established
convention is `+1` = positive, `-1` = negative, `0` = cleared / no
opinion. Wider scales (e.g. `-2..+2`, per-axis ratings) round-trip
verbatim under §3.10 forward-compat — consumers MUST preserve unknown
integer values rather than validating as an enum. Adding a new
sentiment value does not bump `schema_version`.

The reference pattern uses the existing `MessageRef` field with a new
convention: `MessageRef.message_id` is the target message id, and
`MessageRef.relationship` is the string `"feedback"`. Both ride on
`MessageRef`'s `extra="allow"` policy — adding new ref-relationships
does not bump `schema_version`.

Example — thumbs-up with a free-text reason, targeting an assistant
message:

```json
{
  "schema_version": "1.0",
  "id": "msg_feedback_1",
  "role": "user",
  "addr": {"workspace_id": "w1", "thread_id": "th1", "user_id": "u1"},
  "content": [
    {"type": "feedback", "sentiment": 1, "text": "great explanation, thanks!"}
  ],
  "ref": {"message_id": "msg_assistant_xyz", "relationship": "feedback"},
  "meta": {}
}
```

### 3.13 `todo`
```jsonc
{
  "type": "todo",
  "id": "todo_main",               // stable id — consumers render the latest todo part by id
  "title": "Release v1.1.0",       // optional
  "items": [
    {
      "id": "t1",
      "content": "Port the codec",                 // imperative description
      "status": "pending" | "in_progress" | "completed" | "cancelled",
      "active_form": "Porting the codec"?          // present-tense label for in_progress display
    }
  ],
  "meta": { ... }
}
```

A shared, mutable checklist surfaced in the conversation — the spec-native
equivalent of an agent "TODO list" that the frontend and the agent both observe.
The agent is authoritative: it writes the **full current list** on each update.
The part `id` is stable so consumers render the most recent `todo` part as the
live board across turns.

Carrier role: `assistant` (the agent owns the list). Like `subagent`, a `todo`
part persists as an ordinary content part (it survives the MemoryLayer codec via
`data`), so reloaded history shows the last known board.

Streaming for a `todo` part: the agent emits `part_appended` with the initial
list, then `part_updated` with `{items: [...]}` on each change. The
[`apply_event`](#streaming) reducer shallow-merges the patch, replacing the
`items` array — so sending the whole list each time is the intended pattern (no
per-item event granularity). `status` and `active_form` are an open set under
§3.99 forward-compat; adding values does not bump `schema_version`.

### 3.99 Unknown / future part types

Any `type` not listed above is **forward-compatible** — consumers MUST
preserve the part verbatim on round-trip and render it as a placeholder
("unsupported content"). They MUST NOT drop unknown parts. This is the
single most important interop invariant in the spec.

(Previously numbered §3.10 — moved to §3.99 so the section now sits
after the explicitly-numbered part types it's the catch-all for. Refs
to "§3.10" elsewhere in the doc still resolve to this section in
spirit; the substantive content is unchanged.)

## 4. `MessageAddress`

```jsonc
{
  "tenant_id":    "...",
  "workspace_id": "...",
  "user_id":      "...",
  "thread_id":    "...",
  "app_id":       "...",
  "agent_id":     "...",
  "task_id":      "...",
  "request_id":   "...",
  "telemetry":   { "trace_id": "...", "span_id": "..." }?
}
```

All fields optional. Carried on every message for routing and
indexing. **Not** nested under `meta` — these are stable, validated,
indexed in MemoryLayer.

## 5. `MessageRef` — inter-message relationships

```jsonc
"ref": {
  "parent_id":         "msg_...",       // within-thread parent (e.g. tree-style chat)
  "in_reply_to":       "msg_...",       // within-thread reply target
  "edits_id":          "msg_...",       // within-thread: this message edits another
  "parent_thread_id":  "thr_...",       // CROSS-thread: thread that spawned this thread
  "parent_message_id": "msg_..."        // CROSS-thread: specific message that spawned this thread
}
```

`parent_id` / `in_reply_to` / `edits_id` are **intra-thread** — they
reference messages in the same thread. They are optional and consumers
that don't model threaded replies / edits may ignore them.

`parent_thread_id` + `parent_message_id` are **cross-thread**. They
back-reference the message in the spawning thread that triggered the
current thread. They are the canonical link between a subagent thread's
messages and the `subagent` part on the parent message (see §3.9).

When a `subagent` part is appended to a parent message, the spawned
thread's first message should carry these cross-thread refs so an
indexer (e.g. MemoryLayer) can walk in either direction without
relying on external mappings.

## 6. `meta` — open extension namespace

```jsonc
"meta": {
  "scitrera": { "feedback": "thumbs_up", "edited": true },
  "x-cowork": { ... },
  "x-office": { ... }
}
```

Rules:

- Top-level keys are namespaces. `scitrera.*` is reserved for
  platform-wide fields not yet promoted to first-class on the envelope.
- Namespaces starting with `x-` are consumer-private. MemoryLayer
  persists them; other consumers must ignore them on read.
- Unknown `meta` keys MUST be preserved on round-trip.

## 7. Streaming event vocabulary

A minimal envelope carried over the existing relay (Socket.io for the
frontend, JSON-RPC for the office add-in, raw Aether stream for
agent-to-agent). The final reconstructed message on the receiver MUST
equal the `message_finalized.message` payload exactly.

```jsonc
// open a new in-flight message
{ "event": "message_started",
  "message": { /* ChatMessage with empty/partial content */ } }

// append a content part at index (resulting position)
{ "event": "part_appended", "message_id": "...", "index": 0,
  "part": { "type": "text", "text": "" } }

// hot path: append tokens to text/reasoning at index
{ "event": "token_delta", "message_id": "...", "index": 0, "text": "Hello" }

// shallow-merge a patch into the part at index
{ "event": "part_updated", "message_id": "...", "index": 1,
  "patch": { "status": "completed" } }

// authoritative end of stream
{ "event": "message_finalized", "message_id": "...",
  "message": { /* full canonical ChatMessage */ } }
```

`token_delta` is a hot-path optimization. Consumers may always
reconstruct via successive `part_updated` events instead.

Unknown event kinds: the TypeScript reducer drops them silently
(forward-compat). The Python reducer raises (strict dispatch). Both
are documented behaviors; pick whichever fits the host runtime.

## 8. Forward compatibility

- **Unknown `ContentPart.type`** → preserve verbatim, render as a
  placeholder. Do not drop.
- **Unknown `meta` namespaces** → preserve verbatim, ignore on read.
- **`schema_version`** bumps when a breaking change to existing types
  lands. Adding new optional fields and new part types is non-breaking
  and does not bump the version.

## 9. Tool calls from frontend / external tools

Today the frontend uses ad-hoc `USER.TOOL_CALL`/`AGENT.TOOL_CALL`/
`AGENT.TOOL_RESULT` WebSocket events. The local agent uses MCP.
Under this spec, all of them become `tool_call` / `tool_result`
content parts on the appropriate message; consumers may stash
transport hints in `meta.scitrera.transport` (`"mcp"`, `"agent_rpc"`,
`"frontend_tool"`).

## 9b. Tool transport (spec 1.1)

Section 9 covers tool calls as *content parts* on a conversation. This
section covers the *transport* layer used to actually invoke a tool over
Aether's `TOOL_CALL` message type. These types are introduced at spec
**1.1** (`TOOLS_SCHEMA_VERSION = "1.1"`); they are **not** `ContentPart`s
and do not change `ChatMessage`'s wire format (which stays at
`schema_version = "1.0"`). Reference impls: `python/.../tools.py`,
`typescript/src/tools.ts`.

### `ToolDescriptor` — catalog entry

A catalog entry returned by tool discovery. `tool_describe` returns the
full form; `tool_search` may return it with `input_schema` omitted.

| Field | Type | Notes |
| --- | --- | --- |
| `name` | `string` | Required, unique catalog key. |
| `title` | `string?` | Optional human label. |
| `description` | `string` | Required, LLM-facing. |
| `input_schema` | `object?` | JSON Schema; present on describe, may be omitted on search. |
| `kind` | `string` | Required. Open registry (like `ControlPart.kind`); known values `"frontend" \| "backend" \| "remote" \| "office"`. |
| `awaits_result` | `boolean` | Required. `false` = fire-and-forget. Named `awaits_result` (not `await`) because `await` is a Python reserved word. |
| `toolsets` | `string[]?` | Tags for the availability/visibility predicate. |
| `meta` | `object?` | Open extension. |

Unknown extra fields round-trip verbatim (forward-compat per §8).

### `ToolInvokeEnvelope` — the `TOOL_CALL` payload

The payload carried as the Aether `TOOL_CALL` body (UTF-8 JSON). The
reply is the existing **`tool_result`** content part (`ToolResultPart`
from §3.5) — there is no separate result transport type.

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | `string` | Defaults to `"1.1"`. |
| `call_id` | `string` | Required. Correlation id == the `tool_call` id. |
| `name` | `string` | Required. Tool to invoke. |
| `args` | `object` | Required. Arguments as a record/dict, **not** a JSON string. |
| `addr` | `MessageAddress` | Required. Reuses §4 `MessageAddress`. |
| `awaits_result` | `boolean?` | Optional override of the descriptor's default. |
| `meta` | `object?` | Turn extras with no first-class `MessageAddress` home (e.g. `window_id` if distinct from `request_id`, `app_workspace`, `authority_grant_id`). |

**Routing convention:** in `addr`, `request_id` is the window target
(per the execution-routing convention) and `task_id` is the turn's chat
task. `tenant_id` / `workspace_id` / `user_id` / `thread_id` / `app_id` /
`agent_id` carry their usual §4 meaning.

## 10. Reference implementations

- **Python (Pydantic v2):** `python/src/scitrera_messaging_spec/`
- **TypeScript:** `typescript/src/`
- **Tests:** `python/tests/` (54 tests across schema, events, streaming,
  langchain, json_schema, subagent), `typescript/test/` (12 tests
  across applyEvent + subagent).

Both reducers share the same fixture vocabulary — when you change one
side, you must mirror the other.

### Adapters (Python)

| Function | Purpose |
| --- | --- |
| `from_rt_envelope(env)` | Legacy `MessageEnvelope` → `ChatMessage`. Loses nothing; uncategorized fields land in `meta["x-rt_envelope"]`. |
| `from_cowork_blocks(blocks)` | Cowork's persisted turn-block list → `ChatMessage`. Unknown block types fall through to `UnknownPart`. |
| `to_openai_chat_completion(msg)` | `ChatMessage` → OpenAI Chat Completions `messages` list. Lossy (citations, dynamic, reasoning dropped). |
| `to_anthropic_messages(msg)` | `ChatMessage` → Anthropic Messages API content blocks. Lossy (same as above). |

## 11. Examples

### 11.1 Minimal user message

```json
{
  "schema_version": "1.0",
  "id": "msg_01HZX",
  "role": "user",
  "created_at": "2026-05-26T15:30:00Z",
  "content": [{"type": "text", "text": "Summarize the Q3 report."}],
  "addr": {"workspace_id": "w1", "user_id": "u1", "thread_id": "th1"},
  "meta": {}
}
```

### 11.2 Assistant turn with tool call, result, and citation

(see end of doc for a third example: subagent delegation)

```json
{
  "schema_version": "1.0",
  "id": "msg_01HZY",
  "role": "assistant",
  "created_at": "2026-05-26T15:30:04Z",
  "content": [
    {"type": "text", "text": "Looking up the report."},
    {"type": "tool_call",
     "id": "call_01HZ",
     "name": "vfs_fetch",
     "args": {"path": "/Q3-report.pdf"},
     "status": "completed"},
    {"type": "tool_result",
     "call_id": "call_01HZ",
     "name": "vfs_fetch",
     "output_text": "Q3 revenue was $4.2M, up 18% QoQ."},
    {"type": "text", "text": "Q3 revenue was **$4.2M**, up 18% QoQ."},
    {"type": "citation",
     "id": "cit_1",
     "source": "vfs://Q3-report.pdf",
     "title": "Q3 Report",
     "snippet": "Total revenue: $4.2M",
     "span": [13, 19]}
  ],
  "addr": {"workspace_id": "w1", "thread_id": "th1", "agent_id": "falcon3"},
  "meta": {}
}
```

### 11.3 Subagent delegation (parent + child threads)

**Parent thread** (`thr_main`) — assistant message holds the subagent
reference; the actual research conversation lives on `thr_sub_001`.

```json
{
  "schema_version": "1.0",
  "id": "msg_p",
  "role": "assistant",
  "content": [
    {"type": "text", "text": "Delegating research to the researcher subagent."},
    {
      "type": "subagent",
      "id": "sub_1",
      "name": "researcher",
      "thread_id": "thr_sub_001",
      "input": {"query": "Q3 revenue and YoY growth"},
      "status": "completed",
      "summary": "Q3 revenue was $4.2M, +18% QoQ, +42% YoY.",
      "started_at": "2026-05-26T15:30:00Z",
      "finished_at": "2026-05-26T15:30:08Z"
    },
    {"type": "text", "text": "Summary: Q3 revenue was **$4.2M**, +18% QoQ."}
  ],
  "addr": {"workspace_id": "w1", "thread_id": "thr_main", "agent_id": "main"},
  "meta": {}
}
```

**Child thread** (`thr_sub_001`) — the researcher's first message
carries the cross-thread back-ref. Its full transcript is stored
separately and can be drilled into without changing the parent.

```json
{
  "schema_version": "1.0",
  "id": "msg_sub_q",
  "role": "user",
  "content": [{"type": "text", "text": "Research Q3 revenue and YoY growth."}],
  "addr": {"workspace_id": "w1", "thread_id": "thr_sub_001"},
  "ref": {"parent_thread_id": "thr_main", "parent_message_id": "msg_p"},
  "meta": {"scitrera": {"spawn": {"by": "main", "kind": "delegation"}}}
}
```

