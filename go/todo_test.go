package spec

import (
	"encoding/json"
	"testing"
)

func Test_TodoPart_construct_and_decode(t *testing.T) {
	part := NewTodoPart(TodoPart{
		ID:    "todo_main",
		Title: "Release",
		Items: []TodoItem{
			{ID: "t1", Content: "Port codec", Status: TodoCompleted, ActiveForm: "Porting codec"},
			{ID: "t2", Content: "Wire sahara", Status: TodoInProgress},
		},
	})
	if part.Type() != PartTodo {
		t.Fatalf("type = %q", part.Type())
	}
	body, ok := part.AsTodo()
	if !ok {
		t.Fatalf("AsTodo failed")
	}
	if body.ID != "todo_main" || len(body.Items) != 2 {
		t.Fatalf("body = %#v", body)
	}
	if body.Items[0].Status != TodoCompleted || body.Items[1].Status != TodoInProgress {
		t.Fatalf("statuses = %v / %v", body.Items[0].Status, body.Items[1].Status)
	}
	if body.Items[0].ActiveForm != "Porting codec" {
		t.Fatalf("active_form lost: %#v", body.Items[0])
	}
}

func Test_TodoPart_survives_memorylayer_codec(t *testing.T) {
	part := NewTodoPart(TodoPart{ID: "todo_main", Items: []TodoItem{
		{ID: "t1", Content: "A", Status: TodoInProgress},
	}})
	msg := ChatMessage{SchemaVersion: "1.0", ID: "m1", Role: RoleAssistant, Addr: MessageAddress{ThreadID: "thr"}, Content: []ContentPart{part}}

	payload, err := ToMemoryLayerPayload(msg)
	if err != nil {
		t.Fatalf("to payload: %v", err)
	}
	raw, _ := json.Marshal(map[string]any{
		"id": "ml", "thread_id": "thr", "role": payload["role"],
		"content": payload["content"], "metadata": payload["metadata"],
	})
	var generic map[string]any
	if err := json.Unmarshal(raw, &generic); err != nil {
		t.Fatalf("unmarshal record: %v", err)
	}
	back, err := FromMemoryLayerMessage(generic)
	if err != nil {
		t.Fatalf("from message: %v", err)
	}
	if len(back.Content) != 1 || back.Content[0].Type() != PartTodo {
		t.Fatalf("codec lost todo part: %#v", back.Content)
	}
	rt, ok := back.Content[0].AsTodo()
	if !ok || len(rt.Items) != 1 || rt.Items[0].Status != TodoInProgress {
		t.Fatalf("todo items lost through codec: %#v", rt)
	}
}
