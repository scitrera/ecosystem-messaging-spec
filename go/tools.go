package spec

import (
	"encoding/json"
	"fmt"
)

// Tool transport types (spec 1.1). Mirror of typescript/src/tools.ts and python
// tools.py. These are the transport types used to invoke a tool over Aether's
// TOOL_CALL message type; they are NOT content parts. The reply to a
// ToolInvokeEnvelope is a ToolResultPart (reuse it; no new result type).

// ToolsSchemaVersion is the wire version of the tool transport layer.
const ToolsSchemaVersion = "1.1"

// ToolDescriptor is a tool catalog entry. kind is an open string registry;
// known values are "frontend" | "backend" | "remote" | "office".
type ToolDescriptor struct {
	Name         string                     `json:"name"`
	Title        string                     `json:"title,omitempty"`
	Description  string                     `json:"description"`
	InputSchema  map[string]json.RawMessage `json:"input_schema,omitempty"`
	Kind         string                     `json:"kind"`
	AwaitsResult bool                       `json:"awaits_result"`
	Toolsets     []string                   `json:"toolsets,omitempty"`
	Meta         map[string]json.RawMessage `json:"meta,omitempty"`
	Extra        map[string]json.RawMessage `json:"-"`
}

var toolDescriptorKnownKeys = keySet(
	"name", "title", "description", "input_schema", "kind", "awaits_result", "toolsets", "meta",
)

func (d ToolDescriptor) MarshalJSON() ([]byte, error) {
	type alias ToolDescriptor
	return marshalWithExtra(alias(d), d.Extra)
}

func (d *ToolDescriptor) UnmarshalJSON(data []byte) error {
	type alias ToolDescriptor
	var base alias
	extra, err := unmarshalWithExtra(data, &base, toolDescriptorKnownKeys)
	if err != nil {
		return fmt.Errorf("spec: tool descriptor: %w", err)
	}
	*d = ToolDescriptor(base)
	d.Extra = extra
	return nil
}

// ToolInvokeEnvelope is the payload carried as the Aether TOOL_CALL body (UTF-8
// JSON). call_id is the correlation id (== the tool_call part id). args is a
// record, NOT a JSON string. The reply is a ToolResultPart.
type ToolInvokeEnvelope struct {
	SchemaVersion string                     `json:"schema_version"`
	CallID        string                     `json:"call_id"`
	Name          string                     `json:"name"`
	Args          map[string]json.RawMessage `json:"args"`
	Addr          MessageAddress             `json:"addr"`
	AwaitsResult  *bool                      `json:"awaits_result,omitempty"`
	Meta          map[string]json.RawMessage `json:"meta,omitempty"`
	Extra         map[string]json.RawMessage `json:"-"`
}

var toolInvokeKnownKeys = keySet(
	"schema_version", "call_id", "name", "args", "addr", "awaits_result", "meta",
)

// NewToolInvokeEnvelope builds an envelope with spec defaults filled in.
func NewToolInvokeEnvelope(callID, name string) ToolInvokeEnvelope {
	return ToolInvokeEnvelope{
		SchemaVersion: ToolsSchemaVersion,
		CallID:        callID,
		Name:          name,
		Args:          map[string]json.RawMessage{},
	}
}

func (e ToolInvokeEnvelope) MarshalJSON() ([]byte, error) {
	type alias ToolInvokeEnvelope
	norm := alias(e)
	if norm.SchemaVersion == "" {
		norm.SchemaVersion = ToolsSchemaVersion
	}
	if norm.Args == nil {
		norm.Args = map[string]json.RawMessage{}
	}
	return marshalWithExtra(norm, e.Extra)
}

func (e *ToolInvokeEnvelope) UnmarshalJSON(data []byte) error {
	type alias ToolInvokeEnvelope
	var base alias
	extra, err := unmarshalWithExtra(data, &base, toolInvokeKnownKeys)
	if err != nil {
		return fmt.Errorf("spec: tool invoke envelope: %w", err)
	}
	*e = ToolInvokeEnvelope(base)
	e.Extra = extra
	return nil
}
