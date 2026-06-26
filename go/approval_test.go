package spec

import (
	"encoding/json"
	"testing"
)

func Test_ApprovalRequestPart_construct_decode_and_codec(t *testing.T) {
	part := NewApprovalRequestPart(ApprovalRequestPart{
		ID:      "appr_1",
		Tool:    "shell",
		Summary: "Run: npm test",
		Args:    json.RawMessage(`{"command":"npm test"}`),
		Options: []string{"once", "session", "always"},
		Reason:  "shell is not pre-authorized",
	})
	if part.Type() != PartApprovalRequest {
		t.Fatalf("type = %q", part.Type())
	}
	body, ok := part.AsApprovalRequest()
	if !ok {
		t.Fatalf("AsApprovalRequest failed: %s", part.Raw())
	}
	if body.Tool != "shell" || body.Status != ApprovalPending {
		t.Fatalf("body = %#v", body)
	}
	if len(body.Options) != 3 {
		t.Fatalf("options = %#v", body.Options)
	}
	var args map[string]string
	if err := json.Unmarshal(body.Args, &args); err != nil || args["command"] != "npm test" {
		t.Fatalf("args = %s (err %v)", body.Args, err)
	}

	// Survives the MemoryLayer codec (non-text part → data) round-trip.
	msg := ChatMessage{SchemaVersion: "1.0", ID: "m1", Role: RoleAssistant, Addr: MessageAddress{ThreadID: "thr"}, Content: []ContentPart{part}}
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	raw, _ := json.Marshal(map[string]any{"id": "ml", "thread_id": "thr", "role": payload["role"], "content": payload["content"], "metadata": payload["metadata"]})
	var generic map[string]any
	if err := json.Unmarshal(raw, &generic); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	back, err := FromMemoryLayerMessage(generic)
	if err != nil {
		t.Fatalf("from message: %v", err)
	}
	rt, ok := back.Content[0].AsApprovalRequest()
	if !ok || rt.ID != "appr_1" || rt.Tool != "shell" || rt.Status != ApprovalPending {
		t.Fatalf("approval part lost through codec: %#v", rt)
	}
}

func Test_ControlPart_carries_approve_with_request_id_and_scope(t *testing.T) {
	// The inbound approve/deny control rides request_id + scope.
	raw := []byte(`{"type":"control","kind":"approve","request_id":"appr_1","scope":"session"}`)
	part, err := RawPart(raw)
	if err != nil {
		t.Fatalf("raw part: %v", err)
	}
	body, ok := part.AsControl()
	if !ok {
		t.Fatalf("AsControl failed")
	}
	if body.Kind != ControlApprove || body.RequestID != "appr_1" || body.Scope != "session" {
		t.Fatalf("control body = %#v", body)
	}
}
