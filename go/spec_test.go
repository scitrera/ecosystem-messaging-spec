package spec

import (
	"bytes"
	"encoding/json"
	"reflect"
	"testing"
)

// jsonEqual compares two JSON documents by value (ignoring key order).
func jsonEqual(t *testing.T, a, b []byte) bool {
	t.Helper()
	var av, bv any
	if err := json.Unmarshal(a, &av); err != nil {
		t.Fatalf("unmarshal a: %v\n%s", err, a)
	}
	if err := json.Unmarshal(b, &bv); err != nil {
		t.Fatalf("unmarshal b: %v\n%s", err, b)
	}
	return reflect.DeepEqual(av, bv)
}

// canonicalMessage carries known parts, an unknown part type, addr/meta extras,
// and an unknown top-level field — all of which must round-trip verbatim.
const canonicalMessage = `{
  "schema_version": "1.0",
  "id": "m1",
  "role": "assistant",
  "created_at": "2026-06-21T00:00:00Z",
  "content": [
    {"type": "text", "text": "hi", "annotations": [{"k": 1}]},
    {"type": "tool_call", "id": "c1", "name": "search", "args": {"q": "go"}, "status": "completed"},
    {"type": "tool_result", "call_id": "c1", "output": {"hits": 3}, "is_error": false},
    {"type": "future_part", "novel_field": "keep me"}
  ],
  "addr": {"thread_id": "t1", "user_id": "u1", "custom_addr_key": "x"},
  "meta": {"trace": "abc"},
  "ref": {"parent_id": "m0"},
  "top_level_extra": {"nested": true}
}`

func TestChatMessageRoundTripValueIdentity(t *testing.T) {
	var msg ChatMessage
	if err := json.Unmarshal([]byte(canonicalMessage), &msg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	out, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if !jsonEqual(t, []byte(canonicalMessage), out) {
		t.Fatalf("round-trip not value-identical:\nwant %s\ngot  %s", canonicalMessage, out)
	}
}

func TestUnknownPartTypePreserved(t *testing.T) {
	var msg ChatMessage
	if err := json.Unmarshal([]byte(canonicalMessage), &msg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(msg.Content) != 4 {
		t.Fatalf("want 4 parts, got %d", len(msg.Content))
	}
	if got := msg.Content[3].Type(); got != "future_part" {
		t.Fatalf("unknown part type lost: %q", got)
	}
	if !bytes.Contains(msg.Content[3].Raw(), []byte("keep me")) {
		t.Fatalf("unknown part field dropped: %s", msg.Content[3].Raw())
	}
}

func TestAddressAndTopLevelExtrasPreserved(t *testing.T) {
	var msg ChatMessage
	if err := json.Unmarshal([]byte(canonicalMessage), &msg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := msg.Addr.Extra["custom_addr_key"]; !ok {
		t.Fatalf("addr extra dropped: %+v", msg.Addr.Extra)
	}
	if _, ok := msg.Extra["top_level_extra"]; !ok {
		t.Fatalf("top-level extra dropped: %+v", msg.Extra)
	}
}

func TestToolResultUsesSpecFieldNames(t *testing.T) {
	var msg ChatMessage
	if err := json.Unmarshal([]byte(canonicalMessage), &msg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	tr, ok := msg.Content[2].AsToolResult()
	if !ok {
		t.Fatal("part 2 should decode as tool_result")
	}
	if tr.CallID != "c1" {
		t.Fatalf("call_id = %q", tr.CallID)
	}
	if !bytes.Contains(tr.Output, []byte(`"hits"`)) {
		t.Fatalf("output not decoded into spec 'output' field: %s", tr.Output)
	}
}

func TestToolInvokeEnvelopeWireShape(t *testing.T) {
	env := NewToolInvokeEnvelope("c1", "search")
	env.Args = map[string]json.RawMessage{"q": json.RawMessage(`"go"`)}
	out, err := json.Marshal(env)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(out, &m); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	for _, k := range []string{"schema_version", "call_id", "name", "args", "addr"} {
		if _, ok := m[k]; !ok {
			t.Fatalf("envelope missing %q: %s", k, out)
		}
	}
	if _, bad := m["arguments"]; bad {
		t.Fatalf("envelope used non-spec 'arguments' key: %s", out)
	}
	if string(m["schema_version"]) != `"1.1"` {
		t.Fatalf("schema_version = %s", m["schema_version"])
	}
}

func TestReducerTokenDeltaAccumulates(t *testing.T) {
	msg := NewChatMessage("m1", RoleAssistant)
	msg.Content = []ContentPart{NewTextPart("")}
	state := ReduceEvents([]StreamEvent{
		MessageStartedEvent{Message: msg},
		TokenDeltaEvent{MessageID: "m1", Index: 0, Text: "hello"},
		TokenDeltaEvent{MessageID: "m1", Index: 0, Text: " world"},
	})
	got, ok := state["m1"].Content[0].AsText()
	if !ok {
		t.Fatal("content[0] not text")
	}
	if got.Text != "hello world" {
		t.Fatalf("text = %q", got.Text)
	}
}

func TestReducerPartAppendedAndFinalize(t *testing.T) {
	msg := NewChatMessage("m1", RoleAssistant)
	final := NewChatMessage("m1", RoleAssistant)
	final.Content = []ContentPart{NewTextPart("done")}
	state := ReduceEvents([]StreamEvent{
		MessageStartedEvent{Message: msg},
		PartAppendedEvent{MessageID: "m1", Index: 0, Part: NewReasoningPart("think", false)},
		MessageFinalizedEvent{MessageID: "m1", Message: final},
	})
	// finalize replaces state wholesale.
	if n := len(state["m1"].Content); n != 1 {
		t.Fatalf("finalized content len = %d", n)
	}
	txt, _ := state["m1"].Content[0].AsText()
	if txt.Text != "done" {
		t.Fatalf("finalized text = %q", txt.Text)
	}
}

func TestReducerTokenDeltaIgnoresNonTextPart(t *testing.T) {
	msg := NewChatMessage("m1", RoleAssistant)
	msg.Content = []ContentPart{NewToolCallPart(ToolCallPartBody{ID: "c1", Name: "x"})}
	state := ReduceEvents([]StreamEvent{
		MessageStartedEvent{Message: msg},
		TokenDeltaEvent{MessageID: "m1", Index: 0, Text: "nope"},
	})
	if got := state["m1"].Content[0].Type(); got != PartToolCall {
		t.Fatalf("part type changed: %s", got)
	}
}

func TestReducerImmutability(t *testing.T) {
	msg := NewChatMessage("m1", RoleAssistant)
	msg.Content = []ContentPart{NewTextPart("")}
	base := ApplyEvent(MessageState{}, MessageStartedEvent{Message: msg})
	_ = ApplyEvent(base, TokenDeltaEvent{MessageID: "m1", Index: 0, Text: "mutated?"})
	got, _ := base["m1"].Content[0].AsText()
	if got.Text != "" {
		t.Fatalf("base state was mutated: %q", got.Text)
	}
}

func TestStreamEventEncodeDecode(t *testing.T) {
	events := []StreamEvent{
		PartAppendedEvent{MessageID: "m1", Index: 0, Part: NewTextPart("x")},
		TokenDeltaEvent{MessageID: "m1", Index: 0, Text: "y"},
		MessageFinalizedEvent{MessageID: "m1", Message: NewChatMessage("m1", RoleAssistant)},
	}
	for _, ev := range events {
		raw, err := json.Marshal(ev)
		if err != nil {
			t.Fatalf("marshal %s: %v", ev.EventName(), err)
		}
		decoded, err := DecodeStreamEvent(raw)
		if err != nil {
			t.Fatalf("decode %s: %v", ev.EventName(), err)
		}
		if decoded == nil || decoded.EventName() != ev.EventName() {
			t.Fatalf("decoded type mismatch for %s: %#v", ev.EventName(), decoded)
		}
	}
}

func TestDecodeUnknownEventDropped(t *testing.T) {
	decoded, err := DecodeStreamEvent([]byte(`{"event":"some_future_event","x":1}`))
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if decoded != nil {
		t.Fatalf("unknown event should decode to nil, got %#v", decoded)
	}
	// ApplyEvent with nil is a no-op.
	state := MessageState{"m1": NewChatMessage("m1", RoleAssistant)}
	if out := ApplyEvent(state, decoded); len(out) != 1 {
		t.Fatalf("nil event mutated state")
	}
}
