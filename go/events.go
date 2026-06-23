package spec

import (
	"encoding/json"
	"fmt"
)

// Streaming event vocabulary for the universal ChatMessage spec. Mirror of
// typescript/src/events.ts and python events.py. The wire shape is a flat JSON
// object discriminated by the "event" field.

// Event names.
const (
	EventMessageStarted   = "message_started"
	EventPartAppended     = "part_appended"
	EventTokenDelta       = "token_delta"
	EventPartUpdated      = "part_updated"
	EventMessageFinalized = "message_finalized"
)

// StreamEvent is implemented by all concrete stream event types.
type StreamEvent interface {
	EventName() string
}

// MessageStartedEvent announces a new message and its initial state.
type MessageStartedEvent struct {
	Message ChatMessage
}

func (MessageStartedEvent) EventName() string { return EventMessageStarted }

func (e MessageStartedEvent) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Event   string      `json:"event"`
		Message ChatMessage `json:"message"`
	}{Event: EventMessageStarted, Message: e.Message})
}

// PartAppendedEvent appends a content part at an index.
type PartAppendedEvent struct {
	MessageID string
	Index     int
	Part      ContentPart
}

func (PartAppendedEvent) EventName() string { return EventPartAppended }

func (e PartAppendedEvent) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Event     string      `json:"event"`
		MessageID string      `json:"message_id"`
		Index     int         `json:"index"`
		Part      ContentPart `json:"part"`
	}{Event: EventPartAppended, MessageID: e.MessageID, Index: e.Index, Part: e.Part})
}

// TokenDeltaEvent appends streamed text to a text/reasoning part.
type TokenDeltaEvent struct {
	MessageID string
	Index     int
	Text      string
}

func (TokenDeltaEvent) EventName() string { return EventTokenDelta }

func (e TokenDeltaEvent) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Event     string `json:"event"`
		MessageID string `json:"message_id"`
		Index     int    `json:"index"`
		Text      string `json:"text"`
	}{Event: EventTokenDelta, MessageID: e.MessageID, Index: e.Index, Text: e.Text})
}

// PartUpdatedEvent merges a patch into an existing part.
type PartUpdatedEvent struct {
	MessageID string
	Index     int
	Patch     map[string]json.RawMessage
}

func (PartUpdatedEvent) EventName() string { return EventPartUpdated }

func (e PartUpdatedEvent) MarshalJSON() ([]byte, error) {
	patch := e.Patch
	if patch == nil {
		patch = map[string]json.RawMessage{}
	}
	return json.Marshal(struct {
		Event     string                     `json:"event"`
		MessageID string                     `json:"message_id"`
		Index     int                        `json:"index"`
		Patch     map[string]json.RawMessage `json:"patch"`
	}{Event: EventPartUpdated, MessageID: e.MessageID, Index: e.Index, Patch: patch})
}

// MessageFinalizedEvent carries the authoritative final message.
type MessageFinalizedEvent struct {
	MessageID string
	Message   ChatMessage
}

func (MessageFinalizedEvent) EventName() string { return EventMessageFinalized }

func (e MessageFinalizedEvent) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Event     string      `json:"event"`
		MessageID string      `json:"message_id"`
		Message   ChatMessage `json:"message"`
	}{Event: EventMessageFinalized, MessageID: e.MessageID, Message: e.Message})
}

// DecodeStreamEvent parses a wire event into its concrete type. Unknown event
// names return (nil, nil) so callers can drop them (forward-compat).
func DecodeStreamEvent(data []byte) (StreamEvent, error) {
	var head struct {
		Event string `json:"event"`
	}
	if err := json.Unmarshal(data, &head); err != nil {
		return nil, fmt.Errorf("spec: decode stream event: %w", err)
	}
	switch head.Event {
	case EventMessageStarted:
		var body struct {
			Message ChatMessage `json:"message"`
		}
		if err := json.Unmarshal(data, &body); err != nil {
			return nil, fmt.Errorf("spec: %s: %w", head.Event, err)
		}
		return MessageStartedEvent{Message: body.Message}, nil
	case EventPartAppended:
		var body struct {
			MessageID string      `json:"message_id"`
			Index     int         `json:"index"`
			Part      ContentPart `json:"part"`
		}
		if err := json.Unmarshal(data, &body); err != nil {
			return nil, fmt.Errorf("spec: %s: %w", head.Event, err)
		}
		return PartAppendedEvent{MessageID: body.MessageID, Index: body.Index, Part: body.Part}, nil
	case EventTokenDelta:
		var body struct {
			MessageID string `json:"message_id"`
			Index     int    `json:"index"`
			Text      string `json:"text"`
		}
		if err := json.Unmarshal(data, &body); err != nil {
			return nil, fmt.Errorf("spec: %s: %w", head.Event, err)
		}
		return TokenDeltaEvent{MessageID: body.MessageID, Index: body.Index, Text: body.Text}, nil
	case EventPartUpdated:
		var body struct {
			MessageID string                     `json:"message_id"`
			Index     int                        `json:"index"`
			Patch     map[string]json.RawMessage `json:"patch"`
		}
		if err := json.Unmarshal(data, &body); err != nil {
			return nil, fmt.Errorf("spec: %s: %w", head.Event, err)
		}
		return PartUpdatedEvent{MessageID: body.MessageID, Index: body.Index, Patch: body.Patch}, nil
	case EventMessageFinalized:
		var body struct {
			MessageID string      `json:"message_id"`
			Message   ChatMessage `json:"message"`
		}
		if err := json.Unmarshal(data, &body); err != nil {
			return nil, fmt.Errorf("spec: %s: %w", head.Event, err)
		}
		return MessageFinalizedEvent{MessageID: body.MessageID, Message: body.Message}, nil
	default:
		return nil, nil
	}
}
