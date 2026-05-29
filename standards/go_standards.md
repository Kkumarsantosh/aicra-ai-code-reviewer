# GO CODING STANDARDS
# Version: 2.1 | Language: Go 1.21+
# Injected via CODING_STANDARDS_PLACEHOLDER into engine/prompt.txt
# This section is evaluated by the AI reviewer for all .go files

---

## AI AGENT INSTRUCTION — GO SECTION

You are reviewing Go source code. For every .go file in the diff you MUST:

STEP 1 — Read every rule in this document before producing any finding.
STEP 2 — Check each rule against the code under review. Do not skip sections.
STEP 3 — For every violation produce a finding in this exact format:

FINDING:
  RULE: {rule ID, e.g. GO-1.1}
  SEVERITY: {CRITICAL | HIGH | MEDIUM | LOW | INFO}
  FILE: {filename}
  LINE: {line number or range if available}
  VIOLATION: {what the code does that breaks the rule}
  REQUIRED FIX: {what the code must do instead}

STEP 4 — After all findings, output the STANDARDS_SCORE block defined at the end of this document.
STEP 5 — Never omit a finding because the code appears to function correctly. Compliance and correctness are independent concerns.

---

## SECTION GO-1 — ERROR HANDLING

### GO-1.1 — Errors as Values

RULE: error MUST be the last return value of any function that can fail. Every call site MUST handle the returned error explicitly. Silent discard using _ is a violation unless the discard is intentional and documented with an inline comment.

VIOLATION PATTERN:
result, _ := strconv.Atoi(input)

CORRECT PATTERN:
result, err := strconv.Atoi(input)
if err != nil {
    return fmt.Errorf("parsing user ID %q: %w", input, err)
}

VIOLATIONS:
- error silently discarded with _ and no comment = HIGH
- error return value ignored entirely = HIGH
- error returned but never checked by caller = HIGH

### GO-1.2 — Error Wrapping

RULE: Use fmt.Errorf with the %w verb to wrap errors. Every wrapped error MUST add context that narrows the problem. Do not rewrap an error with a generic or identical message. Callers MUST use errors.Is() or errors.As() for inspection, never .Error() string comparison.

VIOLATION PATTERN:
return fmt.Errorf("error: %w", err)

CORRECT PATTERN:
return fmt.Errorf("fetching account %d from store: %w", accountID, err)

VIOLATIONS:
- error wrapped with no meaningful context added = MEDIUM
- error inspected via .Error() string comparison = MEDIUM
- errors.Is() or errors.As() not used when checking error type = MEDIUM
- error returned from a package boundary without wrapping = MEDIUM

### GO-1.3 — Sentinel Errors

RULE: Sentinel errors MUST be defined as package-level variables using errors.New. They MUST be exported with the Err prefix. Callers MUST check them with errors.Is().

CORRECT PATTERN:
var (
    ErrAccountNotFound   = errors.New("account not found")
    ErrInsufficientFunds = errors.New("insufficient funds")
)

VIOLATIONS:
- sentinel error defined as a string constant = MEDIUM
- sentinel error not exported when it is part of the package contract = MEDIUM
- sentinel error checked with string comparison instead of errors.Is() = MEDIUM

### GO-1.4 — Custom Error Types

RULE: When callers need to inspect structured error detail, define a concrete error type implementing the error interface. The type MUST implement Error() string. If it wraps another error it MUST implement Unwrap() error so errors.As() and errors.Is() work correctly up the chain.

CORRECT PATTERN:
type ValidationError struct {
    Field   string
    Message string
}

func (e *ValidationError) Error() string {
    return fmt.Sprintf("validation failed on field %q: %s", e.Field, e.Message)
}

VIOLATIONS:
- custom error type does not implement Unwrap() when it wraps a cause = MEDIUM
- custom error type used for a sentinel that errors.New() would cover = INFO

### GO-1.5 — PII-Safe Error Model

RULE: Errors returned to clients MUST never contain PII, credentials, stack traces, internal paths, or database schema detail. Use a two-layer model: a PublicMessage safe for API responses and an InternalErr logged server-side only. Link both with a CorrelationID.

CORRECT PATTERN:
type SafeError struct {
    PublicMessage string
    InternalErr   error
    CorrelationID string
}

func (e *SafeError) Error() string { return e.PublicMessage }
func (e *SafeError) Unwrap() error { return e.InternalErr }

VIOLATIONS:
- internal error detail returned directly in HTTP response body = HIGH
- PII present in an error message sent to the client = CRITICAL
- no correlation ID linking the public response to the internal log entry = MEDIUM
- stack trace included in API error response = HIGH

### GO-1.6 — panic() Usage

RULE: panic() is permitted only in the three scenarios listed below. Using panic() as a substitute for error returns in business logic is a HIGH violation.

PERMITTED SCENARIOS:
- Unrecoverable startup failure where continuing would corrupt state
- Must* constructor helpers such as regexp.MustCompile and template.Must
- HTTP middleware recover() boundary to prevent a single goroutine panic from crashing the server

NOT PERMITTED:
- Business logic error handling
- Replacing error return values
- Signalling expected failure conditions

VIOLATIONS:
- panic() used for a recoverable business logic error = HIGH
- panic() used instead of returning an error from a service function = HIGH
- recover() used outside a middleware or Must* pattern = MEDIUM

### GO-1.7 — Variable Shadowing

RULE: Shadowing err or any other meaningful variable in a nested scope using := is PROHIBITED. Use a distinct variable name or a plain assignment = for the inner scope.

VIOLATION PATTERN:
err := openConnection(ctx)
if err != nil {
    if err := logFailure(err); err != nil {
        return err
    }
}

CORRECT PATTERN:
err := openConnection(ctx)
if err != nil {
    if logErr := logFailure(err); logErr != nil {
        return fmt.Errorf("logging connection failure: %w", logErr)
    }
    return fmt.Errorf("opening connection: %w", err)
}

VIOLATIONS:
- err redeclared with := in a nested scope where outer err is still in use = MEDIUM
- any meaningful variable shadowed in a nested scope = MEDIUM

TOOLING: Enable govet shadow check via golangci-lint to detect this automatically.

---

## SECTION GO-2 — CONTEXT

### GO-2.1 — Context as First Parameter

RULE: context.Context MUST be the first parameter of every function that performs I/O, network calls, database operations, or any blocking work.

VIOLATIONS:
- I/O or database function does not accept context.Context = MEDIUM
- context.Context is not the first parameter when present = LOW

### GO-2.2 — No Context in Structs

RULE: context.Context MUST NOT be stored as a struct field. Pass it explicitly through the call chain on every function that needs it.

VIOLATIONS:
- context.Context stored as a struct field = MEDIUM

### GO-2.3 — No Nil Context

RULE: nil MUST NOT be passed as a context argument. Use context.Background() at the top-level entry point or context.TODO() as a traceable placeholder during development. context.TODO() MUST be replaced before merge.

VIOLATIONS:
- nil passed as context.Context argument = HIGH
- context.TODO() present in non-development code without a linked ticket = LOW

### GO-2.4 — Typed Context Keys

RULE: Values stored in a context MUST use a typed unexported key type to prevent key collisions across packages. Never use a built-in type or a plain string as a context key.

CORRECT PATTERN:
type contextKey string
const correlationIDKey contextKey = "correlationID"

VIOLATIONS:
- string or int used directly as context key = MEDIUM
- exported type used as context key (allows external collision) = LOW

---

## SECTION GO-3 — CONCURRENCY

### GO-3.1 — Goroutine Lifecycle

RULE: Every goroutine MUST have a defined lifecycle. A clear start point and a termination signal are both required. Fire-and-forget goroutines with no lifecycle control are PROHIBITED in production logic.

VIOLATION PATTERN:
go processPayment(payment)

CORRECT PATTERN:
g, ctx := errgroup.WithContext(ctx)
for _, p := range payments {
    p := p
    g.Go(func() error {
        return s.processOne(ctx, p)
    })
}
return g.Wait()

NOTE: The p := p loop variable capture is required for Go versions before 1.22. For Go 1.22+ the loop variable semantics changed and the capture is no longer needed. Flag the version context when reviewing.

VIOLATIONS:
- goroutine started with no mechanism to wait for completion = HIGH
- goroutine started with no cancellation or context propagation = HIGH
- fire-and-forget go func() in production service logic = HIGH

### GO-3.2 — Synchronization Primitive Selection

RULE: Choose the correct primitive for the access pattern. Mismatched primitives are a design violation.

REQUIRED MAPPING:
- Shared state with high read concurrency: use sync.RWMutex
- Simple mutual exclusion over shared state: use sync.Mutex
- One-time initialization: use sync.Once
- Goroutine signalling and pipeline orchestration: use chan
- Fan-out with error propagation: use errgroup.Group
- High-frequency reusable buffers to reduce GC pressure: use sync.Pool

VIOLATIONS:
- sync.Mutex used for read-heavy state where sync.RWMutex is appropriate = LOW
- raw chan used for error collection from multiple goroutines where errgroup would be cleaner = LOW
- sync.WaitGroup used where errgroup.Group would propagate errors that are currently lost = MEDIUM

### GO-3.3 — sync.Pool Usage

RULE: sync.Pool MUST be used for short-lived high-frequency allocations such as bytes.Buffer to reduce GC pressure. Objects retrieved from a pool MUST be Reset() before use. The caller MUST copy the result before calling Put() because the pool may reclaim the object at any time. Never retain a reference to a pooled object after returning it.

CORRECT PATTERN:
var bufPool = sync.Pool{
    New: func() any { return new(bytes.Buffer) },
}

func marshalResponse(v any) ([]byte, error) {
    buf := bufPool.Get().(*bytes.Buffer)
    buf.Reset()
    defer bufPool.Put(buf)
    // copy result before returning
}

VIOLATIONS:
- pooled object not Reset() before use = HIGH
- reference retained to a pooled object after Put() is called = HIGH
- pooled buffer result not copied before the buffer is returned to the pool = HIGH

### GO-3.4 — Race Conditions

RULE: Any race condition detected by go test -race = CRITICAL violation. The -race flag MUST be enabled in CI.

VIOLATIONS:
- shared variable written from multiple goroutines without synchronization = CRITICAL
- map written and read concurrently without a lock = CRITICAL
- slice appended from multiple goroutines without synchronization = CRITICAL

---

## SECTION GO-4 — ARCHITECTURE

### GO-4.1 — Interface Design

RULE: Interfaces MUST be defined at the point of consumption, not at the point of implementation. This is the Go accept-interfaces-return-structs principle. Interfaces MUST be small: 1 to 3 methods with a single cohesive purpose.

CORRECT PATTERN:
// Defined in the consuming package, not in the store package
type accountStore interface {
    GetByID(ctx context.Context, id int64) (*Account, error)
}

VIOLATIONS:
- interface defined in the same package as its implementation = MEDIUM
- interface with more than 5 methods and no single cohesive purpose = MEDIUM
- large interface used where a smaller focused subset would satisfy the consumer = MEDIUM

### GO-4.2 — Directory and Visibility Structure

RULE: All core domain logic MUST live under /internal. The Go compiler enforces this boundary. Anything not required by an external caller MUST be unexported. Use /pkg only for code that is deliberately and intentionally reusable by external consumers.

REQUIRED LAYOUT:
cmd/api/main.go          — entry point, wiring only, no business logic
internal/payment/        — core domain, compiler-protected
internal/platform/       — database, middleware, config
pkg/                     — intentionally public and reusable
api/                     — OpenAPI specs, protobuf definitions

VIOLATIONS:
- business logic placed in root package or /pkg without justification = MEDIUM
- exported identifier that has no external consumer = LOW
- cmd/main.go containing business logic beyond wiring = MEDIUM

### GO-4.3 — Constructors

RULE: All service types MUST be constructed via a NewXxx constructor function. The constructor MUST validate all required dependencies and return an error if any are nil or invalid. This makes dependencies explicit and enables testing.

CORRECT PATTERN:
func NewPaymentService(
    store accountStore,
    notifier notificationSender,
    logger *slog.Logger,
    cfg PaymentConfig,
) (*PaymentService, error) {
    if store == nil {
        return nil, errors.New("NewPaymentService: store must not be nil")
    }
}

VIOLATIONS:
- service type instantiated with a struct literal instead of a constructor = MEDIUM
- constructor does not validate nil dependencies = MEDIUM
- constructor returns the service without an error return = LOW

### GO-4.4 — init() Restrictions

RULE: init() MUST NOT perform I/O, establish connections, or execute business logic. Permitted uses are static asset registration and global flag setup only.

VIOLATIONS:
- init() opening a database connection = HIGH
- init() making an HTTP request = HIGH
- init() executing business logic = HIGH

---

## SECTION GO-5 — STYLE AND TOOLING

### GO-5.1 — Formatting

RULE: All Go code MUST be clean under gofmt and goimports before commit. Unformatted code is a violation. This is non-negotiable.

VIOLATIONS:
- code not formatted by gofmt = LOW
- imports not organized by goimports = LOW

### GO-5.2 — Import Grouping

RULE: Imports MUST be grouped in exactly this order with a blank line between each group: standard library first, then third-party packages, then internal packages.

CORRECT PATTERN:
import (
    "context"
    "fmt"

    "github.com/jackc/pgx/v5"

    "github.com/your-org/your-app/internal/payment"
)

VIOLATIONS:
- imports not separated into the three groups = LOW
- internal and third-party imports mixed in one group = LOW

### GO-5.3 — Modern Language Features

RULE: Use the slices and maps standard library packages (available since Go 1.21) in preference to manual loops where they improve clarity. Use range over integer (available since Go 1.22) in preference to 3-clause for loops where applicable. Version-gate these usages to the minimum Go version declared in go.mod.

VIOLATIONS:
- manual search loop where slices.Contains would be cleaner = INFO
- 3-clause for loop iterating over an integer where range n applies = INFO

### GO-5.4 — Naming Conventions

RULE: Apply the following naming conventions to all identifiers.

REQUIRED MAPPING:
- Package: short, lowercase, no underscores, no stutter
- Struct: Noun in PascalCase
- Interface: Agent noun with er suffix where natural (Storer, Notifier, Processor)
- Exported error variable: ErrXxx
- Error type: XxxError
- Context key: typed unexported string alias

VIOLATIONS:
- package name contains underscore or uppercase = LOW
- interface name does not reflect a role or agent noun = LOW
- error variable does not use Err prefix = LOW
- context key uses a built-in or string type instead of a typed alias = MEDIUM
- stutter in naming such as payment.PaymentService instead of payment.Service = LOW

### GO-5.5 — Mandatory Toolchain Gates

RULE: All of the following tools MUST pass with zero blocking findings before a merge is approved.

REQUIRED TOOLS AND PURPOSE:
- gofmt and goimports: canonical formatting
- go vet: standard correctness checks
- golangci-lint: aggregated linting
- govulncheck ./...: vulnerability scan against Go vulnerability database
- go test -race ./...: race condition detection
- go mod verify: module integrity

REQUIRED GOLANGCI-LINT LINTERS:
- errcheck: silent error discard detection
- govet with shadow: variable shadowing detection
- staticcheck: advanced static analysis
- gosimple: simplification opportunities
- ineffassign: useless assignments
- gocognit: cognitive complexity enforcement
- gosec: security-focused checks
- noctx: missing context in HTTP and DB calls
- wrapcheck: error wrapping at package boundaries
- exhaustive: switch exhaustiveness on enums

VIOLATIONS:
- govulncheck finding on a direct dependency = CRITICAL
- go vet error present = HIGH
- golangci-lint error from a required linter present = MEDIUM
- go test -race failure = CRITICAL

### GO-5.6 — Happy Path and Guard Clauses

RULE: The success path MUST remain on the left margin. Use guard clauses and early returns to handle errors immediately at the point of detection. Deep nesting that buries the happy path is a violation.

VIOLATION PATTERN:
func Refund(ctx context.Context, id int64) error {
    if p, err := s.store.Get(ctx, id); err == nil {
        if p.Status == StatusCompleted {
            // happy path buried in nesting
        }
    }
}

CORRECT PATTERN:
func Refund(ctx context.Context, id int64) error {
    p, err := s.store.Get(ctx, id)
    if err != nil {
        return fmt.Errorf("fetching payment %d: %w", id, err)
    }
    if p.Status != StatusCompleted {
        return ErrPaymentNotCompleted
    }
    // happy path continues at the left margin
}

VIOLATIONS:
- happy path buried under two or more levels of nesting = MEDIUM
- error handled via else branch instead of early return = MEDIUM
- nesting depth exceeds 3 levels = MEDIUM

---

## SECTION GO-6 — SQL AND DATA ACCESS

### GO-6.1 — Parameterized Queries

RULE: All SQL queries MUST use parameterized placeholders. String concatenation to build SQL is a CRITICAL violation regardless of the source of the concatenated value.

VIOLATION PATTERN:
query := "SELECT * FROM accounts WHERE email = '" + email + "'"

CORRECT PATTERN:
const getAccountByEmail = `
    SELECT id, email, status
    FROM accounts
    WHERE email = $1
    AND deleted_at IS NULL
`
row := db.QueryRowContext(ctx, getAccountByEmail, email)

VIOLATIONS:
- SQL built with string concatenation = CRITICAL
- SQL built with fmt.Sprintf interpolating a variable = CRITICAL
- template literal used to interpolate user input into SQL = CRITICAL

### GO-6.2 — SQL Storage

RULE: SQL queries MUST be stored as named package-level constants or embedded from .sql files using go:embed. Do not inline complex query strings at the call site.

VIOLATIONS:
- complex multi-line SQL inlined as a raw string literal at the call site = LOW
- SQL duplicated across multiple locations without a shared constant = MEDIUM

### GO-6.3 — Row Handling

RULE: rows.Close() MUST be deferred immediately after verifying the open error, not before the error check. rows.Err() MUST be checked after the iteration loop completes.

CORRECT SEQUENCE:
rows, err := db.QueryContext(ctx, query, args...)
if err != nil {
    return fmt.Errorf("querying payments: %w", err)
}
defer rows.Close()

for rows.Next() {
    // scan
}

if err := rows.Err(); err != nil {
    return fmt.Errorf("iterating payments: %w", err)
}

VIOLATIONS:
- rows.Close() not deferred = MEDIUM
- rows.Close() deferred before the error check on QueryContext = MEDIUM
- rows.Err() not checked after the loop = MEDIUM

---

## SECTION GO-7 — TESTING

### GO-7.1 — Table-Driven Tests

RULE: Any function with more than one input scenario MUST use table-driven tests. This is the idiomatic Go pattern and reduces repetition.

CORRECT PATTERN:
func TestPaymentService_Refund_WhenPaymentNotCompleted_ReturnsError(t *testing.T)
func TestPaymentService_Refund_WhenValid_UpdatesStatusAndNotifies(t *testing.T)

VIOLATIONS:
- multiple scenarios tested with duplicated test functions instead of table-driven approach = MEDIUM
- table-driven test with no subtest name (t.Run with empty string) = LOW

### GO-7.2 — Test Naming

RULE: Test function names MUST describe the scenario under test and the expected outcome. The format TestUnit_Method_Scenario_ExpectedOutcome is required.

VIOLATIONS:
- test name does not describe scenario = LOW
- test name does not describe expected outcome = LOW
- test named TestFoo with no further qualification = LOW

### GO-7.3 — Mocking and Test Isolation

RULE: Use interface-based mocks for all external dependencies in unit tests. Do not use monkey-patching libraries. For store-layer tests use a real database via testcontainers-go. Do not substitute SQLite or an in-memory database for PostgreSQL tests.

VIOLATIONS:
- monkey-patching library used for mocking = MEDIUM
- store layer unit test uses SQLite instead of a real Postgres instance = MEDIUM
- test hits a live external service or real database without Testcontainers = MEDIUM

### GO-7.4 — Parallelism and Cleanup

RULE: Use t.Parallel() for tests that do not share mutable state to reduce CI duration. Use t.Cleanup() to register teardown logic in tests and subtests.

VIOLATIONS:
- stateless test does not call t.Parallel() = INFO
- defer used for teardown inside a subtest where t.Cleanup() is appropriate = LOW

### GO-7.5 — Coverage Targets

RULE: The following minimum coverage targets MUST be met and enforced in CI.

REQUIRED TARGETS:
- Service layer: 85% line coverage
- Handler layer: 80% line coverage
- Store layer: 75% line coverage (backed by integration tests against real DB)

VIOLATIONS:
- service layer below 85% coverage = MEDIUM
- handler layer below 80% coverage = MEDIUM
- new business logic added with no corresponding tests = HIGH

---

## SECTION GO-8 — SEVERITY TABLE

CRITICAL — Security vulnerability, data loss risk, race condition, or production crash risk. Action: Block merge immediately.
HIGH — Significant reliability, correctness, or security posture risk. Action: Block merge. Fix required before approval.
MEDIUM — Meaningful deviation from standards with maintainability or correctness risk. Action: Fix within current sprint.
LOW — Style, readability, or minor advisory issue. Action: Add to backlog.
INFO — Observation or suggestion with no compliance impact. Action: Optional.

---

## SECTION GO-9 — STANDARDS_SCORE RUBRIC

Assign a single integer score from 1 to 10 after all findings are listed.

SCORE 10 — Perfect compliance. Zero violations in all sections.
SCORE 9 — Excellent. Only 1 or 2 LOW or INFO findings. No MEDIUM, HIGH, or CRITICAL.
SCORE 8 — Good. A small number of LOW or MEDIUM findings. No HIGH or CRITICAL.
SCORE 7 — Acceptable. Multiple MEDIUM findings OR exactly 1 HIGH finding.
SCORE 6 — Below standard. Multiple HIGH findings OR pervasive MEDIUM issues throughout the diff.
SCORE 5 — Poor. Exactly 1 CRITICAL finding OR many HIGH findings.
SCORE 4 — Failing. Multiple CRITICAL findings.
SCORE 1 to 3 — Unacceptable. Severe security violations, data exposure, or systemic non-compliance. Escalate immediately.

Output the score block in exactly this format after all findings:

STANDARDS_SCORE: {score}/10
SCORE_RATIONALE: {one sentence stating the primary reason for this score}
MERGE_RECOMMENDATION: {APPROVE | APPROVE_WITH_COMMENTS | REQUEST_CHANGES | BLOCK}

---

*Standards Version: 2.1 | Language: Go 1.21+ | Last Reviewed: March 2026*
*Owner: Engineering Standards Committee*
*Amendments: Raise a PR against scripts/standards/go_standards.md*