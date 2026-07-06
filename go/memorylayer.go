package spec

// MemoryLayer ↔ spec ChatMessage conversion helpers.
//
// MemoryLayer's chat history API (append_messages, get_messages) takes a
// generic content-block shape:
//
//	{"role": ..., "content": str | [{"type": str, "text": ?, "data": ?}], "metadata": {...}}
//
// These helpers produce / consume that shape from a typed spec ChatMessage
// losslessly: spec parts with no MemoryLayer-native field set go through
// "data", and the spec metadata fields (id, addr, ref, schema_version,
// created_at) ride in "metadata" under the "scitrera.*" namespace. This mirrors
// the Python reference implementation (scitrera_messaging_spec.memorylayer).
//
// The helpers carry NO MemoryLayer SDK dependency — they produce / consume
// generic maps. Callers wire a real MemoryLayer client themselves (e.g. the Go
// SDK's AppendMessages takes []map[string]any; GetMessages results can be
// JSON-round-tripped into map[string]any for FromMemoryLayerMessage).

import (
	"encoding/json"
	"fmt"
)

// memorylayerNS is the reserved metadata namespace for spec-only fields stashed
// alongside MemoryLayer's native metadata. Round-tripping a ChatMessage through
// MemoryLayer round-trips these keys verbatim.
const memorylayerNS = "scitrera"

// memorylayerAppWorkspaceKey is the top-level MemoryLayer message-metadata key
// carrying the originating app workspace at write time. Mirrors the SDK +
// server MESSAGE_META_APP_WORKSPACE_KEY constants; kept in sync by value (the
// spec deliberately avoids a runtime dep on the MemoryLayer SDK).
const memorylayerAppWorkspaceKey = "app_workspace"

// reservedScitreraKeys are the spec-OWNED keys stored under the reserved
// "scitrera" namespace by buildMLMetadata. On read they are harvested into
// dedicated ChatMessage fields; every OTHER scitrera.* key is producer/consumer
// data (e.g. the per-message agent display name "agent_name", "feedback",
// "telemetry", "authority_grant_id") and MUST survive on meta["scitrera"] or it
// is silently lost on history reload. Keep in sync with buildMLMetadata.
var reservedScitreraKeys = map[string]bool{
	"schema_version": true,
	"message_id":     true,
	"created_at":     true,
	"addr":           true,
	"ref":            true,
}

// ToMemoryLayerPayload converts a spec ChatMessage to a MemoryLayer
// append_messages entry. The returned map matches MemoryLayer's payload shape
// and is safe to pass into client.AppendMessages(threadID, []map[string]any{...}).
func ToMemoryLayerPayload(m ChatMessage) (map[string]any, error) {
	content := make([]any, 0, len(m.Content))
	for i, p := range m.Content {
		block, err := partToMLContent(p)
		if err != nil {
			return nil, fmt.Errorf("spec: memorylayer: content[%d]: %w", i, err)
		}
		content = append(content, block)
	}
	meta, err := buildMLMetadata(m)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"role":     string(m.Role),
		"content":  content,
		"metadata": meta,
	}, nil
}

// ToMemoryLayerPayloads is the bulk variant of ToMemoryLayerPayload.
func ToMemoryLayerPayloads(messages []ChatMessage) ([]map[string]any, error) {
	out := make([]map[string]any, 0, len(messages))
	for i, m := range messages {
		p, err := ToMemoryLayerPayload(m)
		if err != nil {
			return nil, fmt.Errorf("spec: memorylayer: message[%d]: %w", i, err)
		}
		out = append(out, p)
	}
	return out, nil
}

// FromMemoryLayerMessage converts a MemoryLayer chat message (the JSON-shaped
// map MemoryLayer returns) back to a spec ChatMessage. Reconstructs the original
// message losslessly when it was written via ToMemoryLayerPayload. For messages
// written by other producers (no scitrera.* metadata), best-effort: missing spec
// fields fall back to MemoryLayer's native fields (thread_id, role, …).
func FromMemoryLayerMessage(mlMessage map[string]any) (ChatMessage, error) {
	mlMeta := map[string]any{}
	if raw, ok := mlMessage["metadata"].(map[string]any); ok {
		for k, v := range raw {
			mlMeta[k] = v
		}
	}
	specExtras := map[string]any{}
	if sc, ok := mlMeta[memorylayerNS].(map[string]any); ok {
		specExtras = sc
		delete(mlMeta, memorylayerNS)
	}

	// addr: prefer the spec-native scitrera.addr namespace, then fall back to
	// MemoryLayer's native thread_id and the top-level app_workspace key.
	addrDump := map[string]any{}
	if a, ok := specExtras["addr"].(map[string]any); ok {
		for k, v := range a {
			addrDump[k] = v
		}
	}
	if _, ok := addrDump["thread_id"]; !ok {
		if tid := stringOf(mlMessage["thread_id"]); tid != "" {
			addrDump["thread_id"] = tid
		}
	}
	if _, ok := addrDump["workspace_id"]; !ok {
		if ws := stringOf(mlMeta[memorylayerAppWorkspaceKey]); ws != "" {
			addrDump["workspace_id"] = ws
		}
	}
	var addr MessageAddress
	if len(addrDump) > 0 {
		if err := mapToValue(addrDump, &addr); err != nil {
			return ChatMessage{}, fmt.Errorf("spec: memorylayer: addr: %w", err)
		}
	}

	var ref *MessageRef
	if r, ok := specExtras["ref"].(map[string]any); ok && len(r) > 0 {
		var rv MessageRef
		if err := mapToValue(r, &rv); err != nil {
			return ChatMessage{}, fmt.Errorf("spec: memorylayer: ref: %w", err)
		}
		ref = &rv
	}

	content, err := mlContentToParts(mlMessage["content"])
	if err != nil {
		return ChatMessage{}, fmt.Errorf("spec: memorylayer: content: %w", err)
	}

	// Re-attach non-reserved scitrera.* metadata (agent_name, feedback, telemetry, …)
	// so the round-trip is lossless: only the spec-owned keys were harvested into
	// dedicated fields above; every other scitrera key is producer/consumer data (e.g.
	// the per-message agent display name) and is otherwise dropped on reload.
	residualScitrera := map[string]any{}
	for k, v := range specExtras {
		if !reservedScitreraKeys[k] {
			residualScitrera[k] = v
		}
	}
	if len(residualScitrera) > 0 {
		mlMeta[memorylayerNS] = residualScitrera
	}

	// Remaining metadata (spec-owned scitrera keys removed) becomes meta.
	meta := map[string]json.RawMessage{}
	for k, v := range mlMeta {
		raw, err := json.Marshal(v)
		if err != nil {
			return ChatMessage{}, fmt.Errorf("spec: memorylayer: meta[%q]: %w", k, err)
		}
		meta[k] = raw
	}

	return ChatMessage{
		SchemaVersion: stringOr(specExtras["schema_version"], MessagingSchemaVersion),
		ID:            firstNonEmpty(stringOf(specExtras["message_id"]), stringOf(mlMessage["id"])),
		Role:          Role(stringOr(mlMessage["role"], string(RoleAssistant))),
		CreatedAt:     firstNonEmpty(stringOf(specExtras["created_at"]), stringOf(mlMessage["created_at"])),
		Content:       content,
		Addr:          addr,
		Meta:          meta,
		Ref:           ref,
	}, nil
}

// ---------------------------------------------------------------------------
// internals
// ---------------------------------------------------------------------------

// partToMLContent renders one spec ContentPart as a MemoryLayer content block.
// text parts go to the native "text" field (so MemoryLayer can run text search /
// token counting), with any extras under "data"; all other parts stash their
// full body (minus "type") under "data".
func partToMLContent(p ContentPart) (map[string]any, error) {
	var dump map[string]any
	if err := json.Unmarshal(p.Raw(), &dump); err != nil {
		return nil, fmt.Errorf("decode part: %w", err)
	}
	ptype, _ := dump["type"].(string)
	if ptype == "" {
		ptype = "unknown"
	}
	delete(dump, "type")

	if ptype == "text" {
		text := stringOf(dump["text"])
		delete(dump, "text")
		out := map[string]any{"type": "text", "text": text}
		if len(dump) > 0 { // leftover annotations / extras
			out["data"] = dump
		}
		return out, nil
	}
	return map[string]any{"type": ptype, "data": dump}, nil
}

// mlContentToParts is the inverse of partToMLContent. It accepts either a string
// (legacy plain-text message) or a list of MemoryLayer content blocks.
func mlContentToParts(content any) ([]ContentPart, error) {
	switch c := content.(type) {
	case string:
		if c == "" {
			return nil, nil
		}
		return []ContentPart{NewTextPart(c)}, nil
	case []any:
		parts := make([]ContentPart, 0, len(c))
		for _, raw := range c {
			block, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			inner := blockToPartMap(block)
			rawBytes, err := json.Marshal(inner)
			if err != nil {
				return nil, fmt.Errorf("encode block: %w", err)
			}
			part, err := RawPart(rawBytes)
			if err != nil {
				return nil, fmt.Errorf("block to part: %w", err)
			}
			parts = append(parts, part)
		}
		return parts, nil
	default:
		return nil, nil
	}
}

// blockToPartMap reconstructs a spec part's raw JSON map from a MemoryLayer
// content block, restoring the "type" discriminator and merging "data" extras.
func blockToPartMap(block map[string]any) map[string]any {
	btype, _ := block["type"].(string)
	if btype == "" {
		btype = "unknown"
	}
	inner := map[string]any{"type": btype}
	if btype == "text" {
		inner["text"] = stringOf(block["text"])
	}
	if data, ok := block["data"].(map[string]any); ok {
		for k, v := range data {
			inner[k] = v
		}
	}
	// A text field sitting on the block itself (non-text-only fields) is preserved.
	if t, ok := block["text"]; ok && t != nil {
		if _, exists := inner["text"]; !exists {
			inner["text"] = t
		}
	}
	return inner
}

// buildMLMetadata assembles the MemoryLayer metadata map: the message's own meta
// keys, a top-level app_workspace from addr.workspace_id, and the spec-only
// fields merged under the scitrera namespace.
func buildMLMetadata(m ChatMessage) (map[string]any, error) {
	specExtras := map[string]any{
		"schema_version": stringOr(m.SchemaVersion, MessagingSchemaVersion),
		"message_id":     m.ID,
	}
	if m.CreatedAt != "" {
		specExtras["created_at"] = m.CreatedAt
	}
	addrDump, err := toCompactMap(m.Addr)
	if err != nil {
		return nil, fmt.Errorf("spec: memorylayer: addr: %w", err)
	}
	if len(addrDump) > 0 {
		specExtras["addr"] = addrDump
	}
	if m.Ref != nil {
		refDump, err := toCompactMap(*m.Ref)
		if err != nil {
			return nil, fmt.Errorf("spec: memorylayer: ref: %w", err)
		}
		if len(refDump) > 0 {
			specExtras["ref"] = refDump
		}
	}

	metadata := map[string]any{}
	for k, v := range m.Meta {
		var dv any
		if err := json.Unmarshal(v, &dv); err != nil {
			return nil, fmt.Errorf("spec: memorylayer: meta[%q]: %w", k, err)
		}
		metadata[k] = dv
	}

	// Top-level app_workspace carries addr.workspace_id using MemoryLayer's
	// native naming so memorylayer-native consumers can index/filter on it.
	// setdefault: a value the caller explicitly placed there wins.
	if m.Addr.WorkspaceID != "" {
		if _, ok := metadata[memorylayerAppWorkspaceKey]; !ok {
			metadata[memorylayerAppWorkspaceKey] = m.Addr.WorkspaceID
		}
	}

	// Reserve the scitrera namespace, merging into any existing object so a
	// caller's own scitrera.* keys (e.g. feedback) survive alongside spec extras.
	if existing, ok := metadata[memorylayerNS].(map[string]any); ok {
		for k, v := range specExtras {
			existing[k] = v
		}
		metadata[memorylayerNS] = existing
	} else {
		metadata[memorylayerNS] = specExtras
	}
	return metadata, nil
}

// toCompactMap marshals v (which uses its own omitempty + Extra-aware encoding)
// and decodes it into a generic map, so only set fields survive.
func toCompactMap(v any) (map[string]any, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// mapToValue routes a generic map back through the target type's UnmarshalJSON
// (capturing Extra/unknown fields per the spec's round-trip guarantees).
func mapToValue(m map[string]any, target any) error {
	raw, err := json.Marshal(m)
	if err != nil {
		return err
	}
	return json.Unmarshal(raw, target)
}

func stringOf(v any) string {
	s, _ := v.(string)
	return s
}

func stringOr(v any, fallback string) string {
	if s := stringOf(v); s != "" {
		return s
	}
	return fallback
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}
