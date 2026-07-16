package spec

import (
	"encoding/json"
	"testing"
)

func TestToolCallProgressPart_RoundTrip(t *testing.T) {
	part := NewToolCallProgressPart(ToolCallProgressPayload{
		BarID: "stqdm_0", Desc: "Scoring", N: 42, Total: 100, ElapsedS: 12.4, Rate: 3.4, EtaS: 17.1,
	})
	if part.Type() != PartDynamic {
		t.Fatalf("type = %q, want dynamic", part.Type())
	}

	d, ok := part.AsDynamic()
	if !ok || d.Kind != DynamicToolCallProgress {
		t.Fatalf("AsDynamic kind = %q, ok=%v", d.Kind, ok)
	}

	pl, ok := part.AsToolCallProgress()
	if !ok {
		t.Fatal("AsToolCallProgress returned false")
	}
	if pl.BarID != "stqdm_0" || pl.N != 42 || pl.Total != 100 {
		t.Fatalf("payload mismatch: %+v", pl)
	}
	if pl.Status != ProgressRunning {
		t.Fatalf("status = %q, want running (default)", pl.Status)
	}
	if pl.Unit != "it" {
		t.Fatalf("unit = %q, want it (default)", pl.Unit)
	}

	// Verbatim JSON round-trip through the raw-preserving ContentPart.
	raw, err := json.Marshal(part)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var back ContentPart
	if err := json.Unmarshal(raw, &back); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if pl2, ok := back.AsToolCallProgress(); !ok || pl2.EtaS != 17.1 {
		t.Fatalf("round-trip lost payload: ok=%v pl=%+v", ok, pl2)
	}
}

func TestAsToolCallProgress_WrongKind(t *testing.T) {
	other, err := NewDynamicPart(DynamicJSX, map[string]string{"x": "y"}, false)
	if err != nil {
		t.Fatalf("NewDynamicPart: %v", err)
	}
	if _, ok := other.AsToolCallProgress(); ok {
		t.Fatal("AsToolCallProgress must be false for a non-progress dynamic kind")
	}
}
