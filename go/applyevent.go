package spec

import "encoding/json"

// Pure reducer for the streaming event vocabulary. Sibling of
// typescript/src/applyEvent.ts and python apply_event; the implementations must
// agree fixture-for-fixture.
//
// Contract:
//   - Inputs are never mutated; ApplyEvent returns a new state map.
//   - Unknown event kinds are silently dropped (forward-compat).
//   - The final reconstructed message must equal the
//     message_finalized.message payload.

// MessageState maps message id -> reconstructed message.
type MessageState map[string]ChatMessage

// ApplyEvent applies a single event, returning a new state map (copy-on-write).
func ApplyEvent(state MessageState, event StreamEvent) MessageState {
	switch e := event.(type) {
	case MessageStartedEvent:
		return putMessage(state, e.Message.ID, e.Message)
	case MessageFinalizedEvent:
		return putMessage(state, e.MessageID, e.Message)
	case PartAppendedEvent:
		return applyPartAppended(state, e)
	case TokenDeltaEvent:
		return applyTokenDelta(state, e)
	case PartUpdatedEvent:
		return applyPartUpdated(state, e)
	default:
		return state
	}
}

// ReduceEvents replays a sequence of events into a fresh state map.
func ReduceEvents(events []StreamEvent) MessageState {
	state := MessageState{}
	for _, e := range events {
		state = ApplyEvent(state, e)
	}
	return state
}

func cloneState(state MessageState) MessageState {
	out := make(MessageState, len(state)+1)
	for k, v := range state {
		out[k] = v
	}
	return out
}

func putMessage(state MessageState, id string, msg ChatMessage) MessageState {
	out := cloneState(state)
	out[id] = msg.Clone()
	return out
}

func applyPartAppended(state MessageState, e PartAppendedEvent) MessageState {
	msg, ok := state[e.MessageID]
	if !ok {
		return state
	}
	msg = msg.Clone()
	idx := clampInsert(e.Index, len(msg.Content))
	content := make([]ContentPart, 0, len(msg.Content)+1)
	content = append(content, msg.Content[:idx]...)
	content = append(content, e.Part)
	content = append(content, msg.Content[idx:]...)
	msg.Content = content
	out := cloneState(state)
	out[e.MessageID] = msg
	return out
}

func applyTokenDelta(state MessageState, e TokenDeltaEvent) MessageState {
	msg, ok := state[e.MessageID]
	if !ok {
		return state
	}
	if e.Index < 0 || e.Index >= len(msg.Content) {
		return state
	}
	part := msg.Content[e.Index]
	if part.Type() != PartText && part.Type() != PartReasoning {
		return state
	}
	updated, ok, err := appendTextDelta(part, e.Text)
	if err != nil || !ok {
		return state
	}
	msg = msg.Clone()
	msg.Content[e.Index] = updated
	out := cloneState(state)
	out[e.MessageID] = msg
	return out
}

func applyPartUpdated(state MessageState, e PartUpdatedEvent) MessageState {
	msg, ok := state[e.MessageID]
	if !ok {
		return state
	}
	if e.Index < 0 || e.Index >= len(msg.Content) {
		return state
	}
	updated, err := patchPart(msg.Content[e.Index], e.Patch)
	if err != nil {
		return state
	}
	msg = msg.Clone()
	msg.Content[e.Index] = updated
	out := cloneState(state)
	out[e.MessageID] = msg
	return out
}

func clampInsert(index, length int) int {
	if index < 0 {
		return 0
	}
	if index > length {
		return length
	}
	return index
}

// appendTextDelta returns a new part with delta appended to its "text" field,
// preserving all other fields. ok is false if the part is not text/reasoning.
func appendTextDelta(p ContentPart, delta string) (ContentPart, bool, error) {
	if p.Type() != PartText && p.Type() != PartReasoning {
		return p, false, nil
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(p.Raw(), &m); err != nil {
		return p, true, err
	}
	var cur string
	if rawText, ok := m["text"]; ok {
		_ = json.Unmarshal(rawText, &cur)
	}
	encoded, err := json.Marshal(cur + delta)
	if err != nil {
		return p, true, err
	}
	m["text"] = encoded
	raw, err := json.Marshal(m)
	if err != nil {
		return p, true, err
	}
	np, err := RawPart(raw)
	return np, true, err
}

// patchPart shallow-merges patch keys into the part, preserving others.
func patchPart(p ContentPart, patch map[string]json.RawMessage) (ContentPart, error) {
	var m map[string]json.RawMessage
	if err := json.Unmarshal(p.Raw(), &m); err != nil {
		return p, err
	}
	for k, v := range patch {
		m[k] = v
	}
	raw, err := json.Marshal(m)
	if err != nil {
		return p, err
	}
	return RawPart(raw)
}
