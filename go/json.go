package spec

import "encoding/json"

// keySet builds a lookup set of known JSON keys.
func keySet(keys ...string) map[string]struct{} {
	out := make(map[string]struct{}, len(keys))
	for _, k := range keys {
		out[k] = struct{}{}
	}
	return out
}

// marshalWithExtra marshals v (a struct alias without its own MarshalJSON) and
// overlays any extra keys not already present. Known fields always win.
func marshalWithExtra(v any, extra map[string]json.RawMessage) ([]byte, error) {
	base, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	if len(extra) == 0 {
		return base, nil
	}
	var merged map[string]json.RawMessage
	if err := json.Unmarshal(base, &merged); err != nil {
		return nil, err
	}
	for k, val := range extra {
		if _, exists := merged[k]; exists {
			continue
		}
		merged[k] = val
	}
	return json.Marshal(merged)
}

// unmarshalWithExtra unmarshals known fields into v and returns the leftover
// (unknown) keys for forward-compat preservation.
func unmarshalWithExtra(data []byte, v any, known map[string]struct{}) (map[string]json.RawMessage, error) {
	if err := json.Unmarshal(data, v); err != nil {
		return nil, err
	}
	var all map[string]json.RawMessage
	if err := json.Unmarshal(data, &all); err != nil {
		return nil, err
	}
	var extra map[string]json.RawMessage
	for k, val := range all {
		if _, ok := known[k]; ok {
			continue
		}
		if extra == nil {
			extra = make(map[string]json.RawMessage)
		}
		extra[k] = val
	}
	return extra, nil
}

// cloneRawMap returns a shallow copy of a raw-message map (nil-safe).
func cloneRawMap(in map[string]json.RawMessage) map[string]json.RawMessage {
	if in == nil {
		return nil
	}
	out := make(map[string]json.RawMessage, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}
