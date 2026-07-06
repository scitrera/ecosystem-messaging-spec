package spec

import (
	"encoding/json"
	"testing"
)

// rawPart builds a ContentPart from a JSON literal (mirrors the Python tests'
// use of typed part constructors without depending on every Go constructor).
func rawPart(t *testing.T, jsonStr string) ContentPart {
	t.Helper()
	p, err := RawPart([]byte(jsonStr))
	if err != nil {
		t.Fatalf("raw part %q: %v", jsonStr, err)
	}
	return p
}

func fixtureMessage(t *testing.T) ChatMessage {
	t.Helper()
	return ChatMessage{
		SchemaVersion: "1.0",
		ID:            "msg_1",
		Role:          RoleAssistant,
		CreatedAt:     "2026-05-26T15:30:00Z",
		Addr: MessageAddress{
			TenantID: "t1", WorkspaceID: "w1", UserID: "u1",
			ThreadID: "thr_1", AgentID: "ag1", TaskID: "task_1",
		},
		Content: []ContentPart{
			rawPart(t, `{"type":"text","text":"Looking up."}`),
			rawPart(t, `{"type":"tool_call","id":"c1","name":"fetch","args":{"x":1},"status":"completed"}`),
			rawPart(t, `{"type":"tool_result","call_id":"c1","name":"fetch","output_text":"42","is_error":false}`),
			rawPart(t, `{"type":"text","text":"Done."}`),
			rawPart(t, `{"type":"reasoning","text":"thinking","redacted":false}`),
		},
		Meta: map[string]json.RawMessage{
			"scitrera": json.RawMessage(`{"feedback":"thumbs_up"}`),
			"x-cowork": json.RawMessage(`{"trace":"abc"}`),
		},
		Ref: &MessageRef{ParentThreadID: "thr_main", ParentMessageID: "msg_p"},
	}
}

// simulateMLRecord round-trips a payload through JSON to mimic exactly what a
// MemoryLayer get_messages call would return (a generic map).
func simulateMLRecord(t *testing.T, threadID string, payload map[string]any) map[string]any {
	t.Helper()
	rec := map[string]any{
		"id":            "ml_id_1",
		"thread_id":     threadID,
		"message_index": 0,
		"role":          payload["role"],
		"content":       payload["content"],
		"metadata":      payload["metadata"],
		"created_at":    "2026-05-26T15:30:00Z",
	}
	raw, err := json.Marshal(rec)
	if err != nil {
		t.Fatalf("marshal record: %v", err)
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatalf("unmarshal record: %v", err)
	}
	return out
}

func Test_ToMemoryLayerPayload_shape(t *testing.T) {
	payload, err := ToMemoryLayerPayload(fixtureMessage(t))
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	if payload["role"] != "assistant" {
		t.Fatalf("role = %v", payload["role"])
	}
	if _, ok := payload["content"].([]any); !ok {
		t.Fatalf("content not a list: %T", payload["content"])
	}
	if _, ok := payload["metadata"].(map[string]any); !ok {
		t.Fatalf("metadata not a map: %T", payload["metadata"])
	}
}

func Test_ToMemoryLayerPayload_text_part_uses_native_text_field(t *testing.T) {
	msg := ChatMessage{ID: "m", Role: RoleUser, Content: []ContentPart{rawPart(t, `{"type":"text","text":"hi"}`)}}
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	block := payload["content"].([]any)[0].(map[string]any)
	if block["type"] != "text" || block["text"] != "hi" {
		t.Fatalf("text block = %#v", block)
	}
	if _, hasData := block["data"]; hasData {
		t.Fatalf("plain text part should have no data: %#v", block)
	}
}

func Test_ToMemoryLayerPayload_non_text_parts_go_to_data(t *testing.T) {
	msg := ChatMessage{ID: "m", Role: RoleAssistant, Content: []ContentPart{
		rawPart(t, `{"type":"tool_call","id":"c1","name":"t","args":{"x":1},"status":"completed"}`),
	}}
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	block := payload["content"].([]any)[0].(map[string]any)
	if block["type"] != "tool_call" {
		t.Fatalf("type = %v", block["type"])
	}
	if _, hasText := block["text"]; hasText {
		t.Fatalf("non-text part should not carry text: %#v", block)
	}
	data := block["data"].(map[string]any)
	if data["id"] != "c1" || data["name"] != "t" {
		t.Fatalf("data = %#v", data)
	}
}

func Test_ToMemoryLayerPayload_metadata_carries_scitrera_namespace(t *testing.T) {
	payload, err := ToMemoryLayerPayload(fixtureMessage(t))
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	sc := payload["metadata"].(map[string]any)[memorylayerNS].(map[string]any)
	if sc["feedback"] != "thumbs_up" { // pre-existing user-set scitrera key preserved
		t.Fatalf("feedback = %v", sc["feedback"])
	}
	if sc["schema_version"] != "1.0" || sc["message_id"] != "msg_1" {
		t.Fatalf("spec extras wrong: %#v", sc)
	}
	addr := sc["addr"].(map[string]any)
	if addr["thread_id"] != "thr_1" || addr["workspace_id"] != "w1" {
		t.Fatalf("addr = %#v", addr)
	}
	ref := sc["ref"].(map[string]any)
	if ref["parent_thread_id"] != "thr_main" {
		t.Fatalf("ref = %#v", ref)
	}
}

func Test_ToMemoryLayerPayload_user_namespaces_preserved(t *testing.T) {
	payload, err := ToMemoryLayerPayload(fixtureMessage(t))
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	xc := payload["metadata"].(map[string]any)["x-cowork"].(map[string]any)
	if xc["trace"] != "abc" {
		t.Fatalf("x-cowork = %#v", xc)
	}
}

func Test_RoundTrip_preserves_content_types_meta_addr_ref(t *testing.T) {
	msg := fixtureMessage(t)
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	back, err := FromMemoryLayerMessage(simulateMLRecord(t, msg.Addr.ThreadID, payload))
	if err != nil {
		t.Fatalf("from message: %v", err)
	}
	if len(back.Content) != len(msg.Content) {
		t.Fatalf("content len %d != %d", len(back.Content), len(msg.Content))
	}
	for i := range msg.Content {
		if back.Content[i].Type() != msg.Content[i].Type() {
			t.Fatalf("content[%d] type %q != %q", i, back.Content[i].Type(), msg.Content[i].Type())
		}
	}
	if back.ID != msg.ID || back.Role != msg.Role {
		t.Fatalf("id/role = %q/%q", back.ID, back.Role)
	}
	if back.Addr.ThreadID != "thr_1" || back.Addr.WorkspaceID != "w1" {
		t.Fatalf("addr = %#v", back.Addr)
	}
	if back.Ref == nil || back.Ref.ParentThreadID != "thr_main" {
		t.Fatalf("ref = %#v", back.Ref)
	}
	// Non-scitrera meta survives the round trip.
	var xc map[string]any
	if err := json.Unmarshal(back.Meta["x-cowork"], &xc); err != nil || xc["trace"] != "abc" {
		t.Fatalf("x-cowork meta = %s (err %v)", back.Meta["x-cowork"], err)
	}
	// Non-reserved scitrera.* meta survives (regression: the read codec used to
	// delete the entire scitrera namespace, dropping producer keys like the
	// per-message agent display name). Reserved spec-owned keys must NOT leak back.
	var sc map[string]any
	if err := json.Unmarshal(back.Meta["scitrera"], &sc); err != nil || sc["feedback"] != "thumbs_up" {
		t.Fatalf("scitrera meta = %s (err %v)", back.Meta["scitrera"], err)
	}
	if _, leaked := sc["message_id"]; leaked {
		t.Fatalf("reserved spec key leaked back into meta.scitrera: %#v", sc)
	}
	if _, leaked := sc["addr"]; leaked {
		t.Fatalf("reserved spec key leaked back into meta.scitrera: %#v", sc)
	}
}

func Test_RoundTrip_preserves_scitrera_agent_name(t *testing.T) {
	// The per-message agent display name (meta.scitrera.agent_name) must survive the
	// MemoryLayer round trip, or a renamed agent reverts to the default on reload.
	msg := ChatMessage{
		ID:      "m-name",
		Role:    RoleAssistant,
		Content: []ContentPart{rawPart(t, `{"type":"text","text":"I'm now Winick"}`)},
		Addr:    MessageAddress{ThreadID: "t1"},
		Meta:    map[string]json.RawMessage{"scitrera": json.RawMessage(`{"agent_name":"Winick"}`)},
	}
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("ToMemoryLayerPayload: %v", err)
	}
	back, err := FromMemoryLayerMessage(map[string]any{
		"id": "ml1", "thread_id": "t1", "role": "assistant",
		"content": payload["content"], "metadata": payload["metadata"],
	})
	if err != nil {
		t.Fatalf("FromMemoryLayerMessage: %v", err)
	}
	var sc map[string]any
	if err := json.Unmarshal(back.Meta["scitrera"], &sc); err != nil || sc["agent_name"] != "Winick" {
		t.Fatalf("agent_name not preserved: meta.scitrera = %s (err %v)", back.Meta["scitrera"], err)
	}
}

func Test_RoundTrip_tool_call_args_and_result_output_preserved(t *testing.T) {
	msg := ChatMessage{
		ID:   "m",
		Role: RoleAssistant,
		Addr: MessageAddress{ThreadID: "thr_1"},
		Content: []ContentPart{
			rawPart(t, `{"type":"tool_call","id":"c1","name":"t","args":{"a":1,"b":[2,3]},"status":"completed"}`),
			rawPart(t, `{"type":"tool_result","call_id":"c1","output":{"ok":true},"is_error":false}`),
		},
	}
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	back, err := FromMemoryLayerMessage(simulateMLRecord(t, "thr_1", payload))
	if err != nil {
		t.Fatalf("from message: %v", err)
	}
	var tc ToolCallPartBody
	if err := back.Content[0].Decode(&tc); err != nil {
		t.Fatalf("decode tool_call: %v", err)
	}
	var args struct {
		A int   `json:"a"`
		B []int `json:"b"`
	}
	raw, _ := json.Marshal(map[string]json.RawMessage{"a": tc.Args["a"], "b": tc.Args["b"]})
	_ = json.Unmarshal(raw, &args)
	if args.A != 1 || len(args.B) != 2 || args.B[1] != 3 {
		t.Fatalf("args round-trip wrong: %#v", tc.Args)
	}
	var tr ToolResultPartBody
	if err := back.Content[1].Decode(&tr); err != nil {
		t.Fatalf("decode tool_result: %v", err)
	}
	var out map[string]any
	if err := json.Unmarshal(tr.Output, &out); err != nil || out["ok"] != true {
		t.Fatalf("tool_result output = %s (err %v)", tr.Output, err)
	}
}

func Test_FromMemoryLayerMessage_non_scitrera_writer_plain_string_content(t *testing.T) {
	record := map[string]any{
		"id":         "ml_xyz",
		"thread_id":  "thr_x",
		"role":       "user",
		"content":    "just plain text",
		"metadata":   map[string]any{},
		"created_at": "2026-05-26T12:00:00Z",
	}
	back, err := FromMemoryLayerMessage(record)
	if err != nil {
		t.Fatalf("from message: %v", err)
	}
	if back.Role != RoleUser || back.Addr.ThreadID != "thr_x" {
		t.Fatalf("role/thread = %q/%q", back.Role, back.Addr.ThreadID)
	}
	if len(back.Content) != 1 || back.Content[0].Type() != "text" {
		t.Fatalf("content = %#v", back.Content)
	}
	var tp TextPart
	if err := back.Content[0].Decode(&tp); err != nil || tp.Text != "just plain text" {
		t.Fatalf("text = %q (err %v)", tp.Text, err)
	}
}

func Test_UnknownPartType_survives_round_trip(t *testing.T) {
	msg := ChatMessage{
		ID:      "m",
		Role:    RoleAssistant,
		Addr:    MessageAddress{ThreadID: "thr_x"},
		Content: []ContentPart{rawPart(t, `{"type":"screencast","url":"https://x","duration_ms":1234}`)},
	}
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	back, err := FromMemoryLayerMessage(simulateMLRecord(t, "thr_x", payload))
	if err != nil {
		t.Fatalf("from message: %v", err)
	}
	if back.Content[0].Type() != "screencast" {
		t.Fatalf("type = %q", back.Content[0].Type())
	}
	var body struct {
		URL        string `json:"url"`
		DurationMS int    `json:"duration_ms"`
	}
	if err := back.Content[0].Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.URL != "https://x" || body.DurationMS != 1234 {
		t.Fatalf("unknown part lost fields: %#v", body)
	}
}

func Test_ToMemoryLayerPayloads_bulk(t *testing.T) {
	msgs := []ChatMessage{
		{ID: "m1", Role: RoleUser, Content: []ContentPart{rawPart(t, `{"type":"text","text":"hi"}`)}},
		{ID: "m2", Role: RoleAssistant, Content: []ContentPart{rawPart(t, `{"type":"text","text":"hello"}`)}},
	}
	out, err := ToMemoryLayerPayloads(msgs)
	if err != nil {
		t.Fatalf("bulk: %v", err)
	}
	if len(out) != 2 || out[0]["role"] != "user" || out[1]["role"] != "assistant" {
		t.Fatalf("bulk roles wrong: %#v", out)
	}
}

func Test_ToMemoryLayerPayload_emits_top_level_app_workspace_from_addr(t *testing.T) {
	msg := ChatMessage{ID: "m_aw", Role: RoleUser, Addr: MessageAddress{WorkspaceID: "ws-real", ThreadID: "thr_1"}, Content: []ContentPart{rawPart(t, `{"type":"text","text":"hi"}`)}}
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	meta := payload["metadata"].(map[string]any)
	if meta[memorylayerAppWorkspaceKey] != "ws-real" {
		t.Fatalf("app_workspace = %v", meta[memorylayerAppWorkspaceKey])
	}
	if meta[memorylayerNS].(map[string]any)["addr"].(map[string]any)["workspace_id"] != "ws-real" {
		t.Fatalf("scitrera.addr.workspace_id missing")
	}
}

func Test_ToMemoryLayerPayload_explicit_meta_app_workspace_wins(t *testing.T) {
	msg := ChatMessage{
		ID: "m_aw2", Role: RoleUser,
		Addr:    MessageAddress{WorkspaceID: "ws-from-addr", ThreadID: "thr_1"},
		Content: []ContentPart{rawPart(t, `{"type":"text","text":"hi"}`)},
		Meta:    map[string]json.RawMessage{memorylayerAppWorkspaceKey: json.RawMessage(`"ws-explicit"`)},
	}
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	if payload["metadata"].(map[string]any)[memorylayerAppWorkspaceKey] != "ws-explicit" {
		t.Fatalf("explicit app_workspace did not win")
	}
}

func Test_ToMemoryLayerPayload_skips_app_workspace_when_addr_unset(t *testing.T) {
	msg := ChatMessage{ID: "m_aw3", Role: RoleUser, Addr: MessageAddress{ThreadID: "thr_1"}, Content: []ContentPart{rawPart(t, `{"type":"text","text":"hi"}`)}}
	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	if _, ok := payload["metadata"].(map[string]any)[memorylayerAppWorkspaceKey]; ok {
		t.Fatalf("app_workspace should be absent without addr.workspace_id")
	}
}

func Test_FromMemoryLayerMessage_falls_back_to_app_workspace(t *testing.T) {
	mlMsg := map[string]any{
		"id":        "srv_id_1",
		"thread_id": "thr_1",
		"role":      "user",
		"content":   []any{map[string]any{"type": "text", "text": "hi"}},
		"metadata":  map[string]any{memorylayerAppWorkspaceKey: "ws-from-sdk"},
	}
	back, err := FromMemoryLayerMessage(mlMsg)
	if err != nil {
		t.Fatalf("from message: %v", err)
	}
	if back.Addr.WorkspaceID != "ws-from-sdk" || back.Addr.ThreadID != "thr_1" {
		t.Fatalf("addr = %#v", back.Addr)
	}
}

func Test_FromMemoryLayerMessage_scitrera_addr_wins_over_app_workspace(t *testing.T) {
	mlMsg := map[string]any{
		"id":        "srv_id_2",
		"thread_id": "thr_1",
		"role":      "user",
		"content":   []any{map[string]any{"type": "text", "text": "hi"}},
		"metadata": map[string]any{
			memorylayerAppWorkspaceKey: "ws-fallback",
			memorylayerNS: map[string]any{
				"schema_version": "1.0",
				"message_id":     "m_xyz",
				"addr":           map[string]any{"thread_id": "thr_1", "workspace_id": "ws-spec"},
			},
		},
	}
	back, err := FromMemoryLayerMessage(mlMsg)
	if err != nil {
		t.Fatalf("from message: %v", err)
	}
	if back.Addr.WorkspaceID != "ws-spec" {
		t.Fatalf("scitrera addr should win: %#v", back.Addr)
	}
}
