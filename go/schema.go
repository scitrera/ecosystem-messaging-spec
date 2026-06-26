// Package spec is the authoritative Go implementation of the Scitrera
// universal ChatMessage messaging spec.
//
// It mirrors python/src/scitrera_messaging_spec and typescript/src. JSON
// round-trips between the three implementations must be value-identical; if
// you change one side, change the others. See docs/UNIVERSAL_MESSAGE_SPEC.md
// for the normative spec.
//
// ContentPart is intentionally raw-preserving: it stores the exact JSON bytes
// of a part so that unknown part types and unknown fields within known parts
// round-trip verbatim (spec invariant §3.10). Typed constructors and accessors
// are provided for the known part types.
package spec

import (
	"encoding/json"
	"errors"
	"fmt"
)

// MessagingSchemaVersion is the wire version of the ChatMessage envelope.
const MessagingSchemaVersion = "1.0"

var (
	// ErrInvalidContentPart indicates a malformed or untyped content part.
	ErrInvalidContentPart = errors.New("spec: invalid content part")
	// ErrWrongPartType indicates a typed accessor was called on a part of a
	// different type.
	ErrWrongPartType = errors.New("spec: wrong content part type")
)

// Role is the author role of a ChatMessage. The spec defines exactly these
// four; consumers MUST preserve unknown roles on round-trip but SHOULD treat
// them conservatively.
type Role string

const (
	RoleUser      Role = "user"
	RoleAssistant Role = "assistant"
	RoleSystem    Role = "system"
	RoleTool      Role = "tool"
)

// PartType is the discriminator of a content part.
type PartType string

const (
	PartText            PartType = "text"
	PartImage           PartType = "image"
	PartFile            PartType = "file"
	PartToolCall        PartType = "tool_call"
	PartToolResult      PartType = "tool_result"
	PartCitation        PartType = "citation"
	PartDynamic         PartType = "dynamic"
	PartReasoning       PartType = "reasoning"
	PartSubagent        PartType = "subagent"
	PartControl         PartType = "control"
	PartFeedback        PartType = "feedback"
	PartTodo            PartType = "todo"
	PartApprovalRequest PartType = "approval_request"
)

// Control kinds (open registry; new kinds do not bump the schema version).
const (
	ControlCancel  = "cancel"  // requires task_id
	ControlApprove = "approve" // user grants an approval_request; requires request_id (+ optional scope)
	ControlDeny    = "deny"    // user rejects an approval_request; requires request_id
)

// ApprovalStatus is the lifecycle of an approval_request content part.
type ApprovalStatus string

const (
	ApprovalPending  ApprovalStatus = "pending"
	ApprovalApproved ApprovalStatus = "approved"
	ApprovalDenied   ApprovalStatus = "denied"
	ApprovalExpired  ApprovalStatus = "expired"
)

// ToolCallStatus is the lifecycle status of a tool_call content part.
type ToolCallStatus string

const (
	ToolCallPending   ToolCallStatus = "pending"
	ToolCallRunning   ToolCallStatus = "running"
	ToolCallCompleted ToolCallStatus = "completed"
	ToolCallFailed    ToolCallStatus = "failed"
	ToolCallCancelled ToolCallStatus = "cancelled"
)

// TodoStatus is the lifecycle status of a single todo item.
type TodoStatus string

const (
	TodoPending    TodoStatus = "pending"
	TodoInProgress TodoStatus = "in_progress"
	TodoCompleted  TodoStatus = "completed"
	TodoCancelled  TodoStatus = "cancelled"
)

// MessageAddress carries routing identifiers. Unknown fields round-trip via
// Extra.
type MessageAddress struct {
	TenantID    string                     `json:"tenant_id,omitempty"`
	WorkspaceID string                     `json:"workspace_id,omitempty"`
	UserID      string                     `json:"user_id,omitempty"`
	ThreadID    string                     `json:"thread_id,omitempty"`
	AppID       string                     `json:"app_id,omitempty"`
	AgentID     string                     `json:"agent_id,omitempty"`
	TaskID      string                     `json:"task_id,omitempty"`
	RequestID   string                     `json:"request_id,omitempty"`
	Telemetry   map[string]json.RawMessage `json:"telemetry,omitempty"`
	Extra       map[string]json.RawMessage `json:"-"`
}

var addrKnownKeys = keySet(
	"tenant_id", "workspace_id", "user_id", "thread_id",
	"app_id", "agent_id", "task_id", "request_id", "telemetry",
)

func (a MessageAddress) MarshalJSON() ([]byte, error) {
	type alias MessageAddress
	return marshalWithExtra(alias(a), a.Extra)
}

func (a *MessageAddress) UnmarshalJSON(data []byte) error {
	type alias MessageAddress
	var base alias
	extra, err := unmarshalWithExtra(data, &base, addrKnownKeys)
	if err != nil {
		return fmt.Errorf("spec: message address: %w", err)
	}
	*a = MessageAddress(base)
	a.Extra = extra
	return nil
}

// MessageRef links a message to related messages. Unknown fields round-trip
// via Extra.
type MessageRef struct {
	ParentID        string                     `json:"parent_id,omitempty"`
	InReplyTo       string                     `json:"in_reply_to,omitempty"`
	EditsID         string                     `json:"edits_id,omitempty"`
	ParentThreadID  string                     `json:"parent_thread_id,omitempty"`
	ParentMessageID string                     `json:"parent_message_id,omitempty"`
	Extra           map[string]json.RawMessage `json:"-"`
}

var refKnownKeys = keySet(
	"parent_id", "in_reply_to", "edits_id", "parent_thread_id", "parent_message_id",
)

func (r MessageRef) MarshalJSON() ([]byte, error) {
	type alias MessageRef
	return marshalWithExtra(alias(r), r.Extra)
}

func (r *MessageRef) UnmarshalJSON(data []byte) error {
	type alias MessageRef
	var base alias
	extra, err := unmarshalWithExtra(data, &base, refKnownKeys)
	if err != nil {
		return fmt.Errorf("spec: message ref: %w", err)
	}
	*r = MessageRef(base)
	r.Extra = extra
	return nil
}

// ChatMessage is the universal message envelope. Unknown top-level fields
// round-trip via Extra.
type ChatMessage struct {
	SchemaVersion string                     `json:"schema_version"`
	ID            string                     `json:"id"`
	Role          Role                       `json:"role"`
	CreatedAt     string                     `json:"created_at,omitempty"`
	Content       []ContentPart              `json:"content"`
	Addr          MessageAddress             `json:"addr"`
	Meta          map[string]json.RawMessage `json:"meta"`
	Ref           *MessageRef                `json:"ref,omitempty"`
	Extra         map[string]json.RawMessage `json:"-"`
}

var msgKnownKeys = keySet(
	"schema_version", "id", "role", "created_at", "content", "addr", "meta", "ref",
)

// NewChatMessage builds a message with spec defaults filled in (schema_version,
// empty content/addr/meta). created_at is left to the caller to avoid a hidden
// clock dependency.
func NewChatMessage(id string, role Role) ChatMessage {
	return ChatMessage{
		SchemaVersion: MessagingSchemaVersion,
		ID:            id,
		Role:          role,
		Content:       []ContentPart{},
		Meta:          map[string]json.RawMessage{},
	}
}

func (m ChatMessage) MarshalJSON() ([]byte, error) {
	type alias ChatMessage
	norm := alias(m)
	if norm.SchemaVersion == "" {
		norm.SchemaVersion = MessagingSchemaVersion
	}
	if norm.Content == nil {
		norm.Content = []ContentPart{}
	}
	if norm.Meta == nil {
		norm.Meta = map[string]json.RawMessage{}
	}
	return marshalWithExtra(norm, m.Extra)
}

func (m *ChatMessage) UnmarshalJSON(data []byte) error {
	type alias ChatMessage
	var base alias
	extra, err := unmarshalWithExtra(data, &base, msgKnownKeys)
	if err != nil {
		return fmt.Errorf("spec: chat message: %w", err)
	}
	*m = ChatMessage(base)
	m.Extra = extra
	return nil
}

// Clone returns a deep-ish copy safe for independent mutation of the content
// slice and top-level maps. Content parts are immutable (raw bytes) so they are
// shared by reference.
func (m ChatMessage) Clone() ChatMessage {
	out := m
	if m.Content != nil {
		out.Content = append([]ContentPart(nil), m.Content...)
	}
	out.Meta = cloneRawMap(m.Meta)
	out.Extra = cloneRawMap(m.Extra)
	out.Addr.Telemetry = cloneRawMap(m.Addr.Telemetry)
	out.Addr.Extra = cloneRawMap(m.Addr.Extra)
	if m.Ref != nil {
		ref := *m.Ref
		ref.Extra = cloneRawMap(m.Ref.Extra)
		out.Ref = &ref
	}
	return out
}

// ContentPart is a raw-preserving content part. It stores the exact JSON bytes
// of the part, exposing the discriminator via Type and typed access via the
// As* / decode helpers. This guarantees unknown part types and unknown fields
// round-trip verbatim.
type ContentPart struct {
	typ PartType
	raw json.RawMessage
}

// RawPart wraps pre-encoded part bytes after validating it carries a string
// "type" discriminator.
func RawPart(raw []byte) (ContentPart, error) {
	var header struct {
		Type PartType `json:"type"`
	}
	if err := json.Unmarshal(raw, &header); err != nil {
		return ContentPart{}, fmt.Errorf("%w: %w", ErrInvalidContentPart, err)
	}
	if header.Type == "" {
		return ContentPart{}, fmt.Errorf("%w: missing type", ErrInvalidContentPart)
	}
	cp := make([]byte, len(raw))
	copy(cp, raw)
	return ContentPart{typ: header.Type, raw: cp}, nil
}

// Type returns the part discriminator.
func (p ContentPart) Type() PartType { return p.typ }

// Raw returns a copy of the underlying part bytes.
func (p ContentPart) Raw() json.RawMessage {
	cp := make([]byte, len(p.raw))
	copy(cp, p.raw)
	return cp
}

// Decode unmarshals the part into v (a typed part struct).
func (p ContentPart) Decode(v any) error {
	if len(p.raw) == 0 {
		return fmt.Errorf("%w: empty part", ErrInvalidContentPart)
	}
	return json.Unmarshal(p.raw, v)
}

func (p ContentPart) MarshalJSON() ([]byte, error) {
	if len(p.raw) == 0 {
		return nil, fmt.Errorf("%w: empty raw part", ErrInvalidContentPart)
	}
	cp := make([]byte, len(p.raw))
	copy(cp, p.raw)
	return cp, nil
}

func (p *ContentPart) UnmarshalJSON(data []byte) error {
	parsed, err := RawPart(data)
	if err != nil {
		return err
	}
	*p = parsed
	return nil
}

// ─── typed part bodies (mirror schema.ts) ────────────────────────────────

// TextPart is a text content part.
type TextPart struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// ReasoningPart is a model reasoning content part.
type ReasoningPart struct {
	Type     string `json:"type"`
	Text     string `json:"text"`
	Redacted bool   `json:"redacted"`
}

// ToolCallPartBody is the tool_call content part (note: id/args, per spec —
// distinct from the ToolInvokeEnvelope transport type which uses call_id).
type ToolCallPartBody struct {
	Type       string                     `json:"type"`
	ID         string                     `json:"id"`
	Name       string                     `json:"name"`
	Args       map[string]json.RawMessage `json:"args"`
	Status     ToolCallStatus             `json:"status"`
	StartedAt  string                     `json:"started_at,omitempty"`
	FinishedAt string                     `json:"finished_at,omitempty"`
	Meta       map[string]json.RawMessage `json:"meta,omitempty"`
}

// ToolError is the error body of a failed tool result.
type ToolError struct {
	Type    string `json:"type,omitempty"`
	Message string `json:"message"`
}

// ToolResultPartBody is the tool_result content part (spec: call_id/output/
// output_text/is_error/error — NOT a "result" field).
type ToolResultPartBody struct {
	Type       string                     `json:"type"`
	CallID     string                     `json:"call_id"`
	Name       string                     `json:"name,omitempty"`
	Output     json.RawMessage            `json:"output,omitempty"`
	OutputText string                     `json:"output_text,omitempty"`
	IsError    bool                       `json:"is_error"`
	Error      *ToolError                 `json:"error,omitempty"`
	Meta       map[string]json.RawMessage `json:"meta,omitempty"`
}

// ControlPartBody is an in-band control signal (kind is an open registry; the
// known kind "cancel" requires task_id).
type ControlPartBody struct {
	Type   string `json:"type"`
	Kind   string `json:"kind"`
	TaskID string `json:"task_id,omitempty"`
	// RequestID + Scope are used by the approve/deny kinds to resolve a specific
	// approval_request (RequestID = the approval_request's id; Scope is the grant
	// breadth: once|session|always, ignored for deny).
	RequestID string `json:"request_id,omitempty"`
	Scope     string `json:"scope,omitempty"`
}

// ImagePart is an image content part. Prefer vfs_ref/uri; data_uri is an escape
// hatch carrying inline "data:image/...;base64,..." bytes.
type ImagePart struct {
	Type    string `json:"type"`
	Mime    string `json:"mime,omitempty"`
	VFSRef  string `json:"vfs_ref,omitempty"`
	URI     string `json:"uri,omitempty"`
	DataURI string `json:"data_uri,omitempty"`
	AltText string `json:"alt_text,omitempty"`
}

// FilePart is a generic non-image binary attachment (PDFs, audio, video, etc.).
type FilePart struct {
	Type      string `json:"type"`
	Mime      string `json:"mime,omitempty"`
	VFSRef    string `json:"vfs_ref,omitempty"`
	URI       string `json:"uri,omitempty"`
	FileName  string `json:"file_name,omitempty"`
	SizeBytes int64  `json:"size_bytes,omitempty"`
	Purpose   string `json:"purpose,omitempty"`
}

// TodoItem is a single entry in a todo content part.
type TodoItem struct {
	ID      string     `json:"id,omitempty"`
	Content string     `json:"content"`
	Status  TodoStatus `json:"status"`
	// ActiveForm is the present-tense label shown while the item is in_progress
	// (e.g. "Wiring sahara commit"); optional.
	ActiveForm string `json:"active_form,omitempty"`
}

// TodoPart is a shared, mutable checklist surfaced in the conversation. The
// agent writes the full list each update; live updates ride part_updated
// (patch {items}). It persists via the MemoryLayer codec like any other part.
type TodoPart struct {
	Type  string         `json:"type"`
	ID    string         `json:"id,omitempty"`
	Title string         `json:"title,omitempty"`
	Items []TodoItem     `json:"items"`
	Meta  map[string]any `json:"meta,omitempty"`
}

// ApprovalRequestPart is a human-in-the-loop permission prompt: the agent asks
// the user to authorize a tool call that is not pre-authorized. The user answers
// with a control part (kind approve/deny, request_id = this part's id). It is
// mutated in place (part_updated) to flip status as it resolves, and persists
// like any other part.
type ApprovalRequestPart struct {
	Type    string          `json:"type"`
	ID      string          `json:"id"`
	Tool    string          `json:"tool"`
	Summary string          `json:"summary,omitempty"`
	Args    json.RawMessage `json:"args,omitempty"`
	// Options are the scopes the user may grant (subset of once|session|always).
	Options []string       `json:"options,omitempty"`
	Status  ApprovalStatus `json:"status"`
	Reason  string         `json:"reason,omitempty"`
	Meta    map[string]any `json:"meta,omitempty"`
}

// ─── typed constructors ──────────────────────────────────────────────────

func partFrom(v any) (ContentPart, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return ContentPart{}, fmt.Errorf("spec: marshal part: %w", err)
	}
	return RawPart(raw)
}

// NewTextPart builds a text part.
func NewTextPart(text string) ContentPart {
	p, _ := partFrom(TextPart{Type: string(PartText), Text: text})
	return p
}

// NewReasoningPart builds a reasoning part.
func NewReasoningPart(text string, redacted bool) ContentPart {
	p, _ := partFrom(ReasoningPart{Type: string(PartReasoning), Text: text, Redacted: redacted})
	return p
}

// NewToolCallPart builds a tool_call content part.
func NewToolCallPart(body ToolCallPartBody) ContentPart {
	body.Type = string(PartToolCall)
	if body.Args == nil {
		body.Args = map[string]json.RawMessage{}
	}
	if body.Status == "" {
		body.Status = ToolCallPending
	}
	p, _ := partFrom(body)
	return p
}

// NewToolResultPart builds a tool_result content part.
func NewToolResultPart(body ToolResultPartBody) ContentPart {
	body.Type = string(PartToolResult)
	p, _ := partFrom(body)
	return p
}

// NewControlPart builds a control part.
func NewControlPart(kind, taskID string) ContentPart {
	p, _ := partFrom(ControlPartBody{Type: string(PartControl), Kind: kind, TaskID: taskID})
	return p
}

// NewImagePart builds an image content part.
func NewImagePart(body ImagePart) ContentPart {
	body.Type = string(PartImage)
	p, _ := partFrom(body)
	return p
}

// NewFilePart builds a file content part.
func NewFilePart(body FilePart) ContentPart {
	body.Type = string(PartFile)
	p, _ := partFrom(body)
	return p
}

// NewTodoPart builds a todo content part.
func NewTodoPart(body TodoPart) ContentPart {
	body.Type = string(PartTodo)
	if body.Items == nil {
		body.Items = []TodoItem{}
	}
	p, _ := partFrom(body)
	return p
}

// NewApprovalRequestPart builds an approval_request content part.
func NewApprovalRequestPart(body ApprovalRequestPart) ContentPart {
	body.Type = string(PartApprovalRequest)
	if body.Status == "" {
		body.Status = ApprovalPending
	}
	p, _ := partFrom(body)
	return p
}

// ─── typed accessors ─────────────────────────────────────────────────────

// AsText returns the text of a text part.
func (p ContentPart) AsText() (TextPart, bool) {
	if p.typ != PartText {
		return TextPart{}, false
	}
	var body TextPart
	if err := p.Decode(&body); err != nil {
		return TextPart{}, false
	}
	return body, true
}

// AsToolCall decodes a tool_call content part.
func (p ContentPart) AsToolCall() (ToolCallPartBody, bool) {
	if p.typ != PartToolCall {
		return ToolCallPartBody{}, false
	}
	var body ToolCallPartBody
	if err := p.Decode(&body); err != nil {
		return ToolCallPartBody{}, false
	}
	return body, true
}

// AsToolResult decodes a tool_result content part.
func (p ContentPart) AsToolResult() (ToolResultPartBody, bool) {
	if p.typ != PartToolResult {
		return ToolResultPartBody{}, false
	}
	var body ToolResultPartBody
	if err := p.Decode(&body); err != nil {
		return ToolResultPartBody{}, false
	}
	return body, true
}

// AsControl decodes a control content part.
func (p ContentPart) AsControl() (ControlPartBody, bool) {
	if p.typ != PartControl {
		return ControlPartBody{}, false
	}
	var body ControlPartBody
	if err := p.Decode(&body); err != nil {
		return ControlPartBody{}, false
	}
	return body, true
}

// AsTodo decodes a todo content part.
func (p ContentPart) AsTodo() (TodoPart, bool) {
	if p.typ != PartTodo {
		return TodoPart{}, false
	}
	var body TodoPart
	if err := p.Decode(&body); err != nil {
		return TodoPart{}, false
	}
	return body, true
}

// AsApprovalRequest decodes an approval_request content part.
func (p ContentPart) AsApprovalRequest() (ApprovalRequestPart, bool) {
	if p.typ != PartApprovalRequest {
		return ApprovalRequestPart{}, false
	}
	var body ApprovalRequestPart
	if err := p.Decode(&body); err != nil {
		return ApprovalRequestPart{}, false
	}
	return body, true
}

// AsImage decodes an image content part.
func (p ContentPart) AsImage() (ImagePart, bool) {
	if p.typ != PartImage {
		return ImagePart{}, false
	}
	var body ImagePart
	if err := p.Decode(&body); err != nil {
		return ImagePart{}, false
	}
	return body, true
}

// AsFile decodes a file content part.
func (p ContentPart) AsFile() (FilePart, bool) {
	if p.typ != PartFile {
		return FilePart{}, false
	}
	var body FilePart
	if err := p.Decode(&body); err != nil {
		return FilePart{}, false
	}
	return body, true
}
