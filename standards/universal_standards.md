# UNIVERSAL CODING STANDARDS
# Version: 2.1 | Applies to: ALL languages and ALL code
# Injected via CODING_STANDARDS_PLACEHOLDER into engine/prompt.txt
# These rules are evaluated FIRST before any language-specific section
# If a language standard conflicts with a universal standard, the universal standard wins

---

## AI AGENT INSTRUCTION — UNIVERSAL SECTION

You are reviewing code in any language. These universal rules MUST be applied to every file in every diff regardless of language, framework, or file type. Do not skip this section for any review.

STEP 1 — Read every rule in this document before producing any finding.
STEP 2 — Apply every rule to every file in the diff. Universal rules have no language exceptions.
STEP 3 — For every violation produce a finding in this exact format:

FINDING:
  RULE: {rule ID, e.g. U1.1}
  SEVERITY: {CRITICAL | HIGH | MEDIUM | LOW | INFO}
  FILE: {filename}
  LINE: {line number or range if available}
  VIOLATION: {what the code does that breaks the rule}
  REQUIRED FIX: {what the code must do instead}

STEP 4 — After completing the universal review, proceed to the language-specific section that matches the file extension.
STEP 5 — After all findings from all sections, output the STANDARDS_SCORE block defined at the end of this document.
STEP 6 — Never suppress a finding because the code appears to work. Compliance and correctness are independent concerns.

---

## SECTION U1 — SECURITY: INPUT VALIDATION

### U1.1 — Every External Input Is Hostile Until Validated

RULE: All external input MUST be validated before it reaches the service or business logic layer. The handler or adapter layer is the trust boundary. Input that passes this boundary without validation is a violation regardless of whether the input appears safe.

WHAT COUNTS AS EXTERNAL INPUT — apply this rule to all of the following:
- HTTP request body
- HTTP query string parameters
- HTTP path parameters
- HTTP headers and cookies
- Message queue and event bus payloads
- File uploads
- CLI arguments
- Environment variables (validate format and presence at startup)
- Data read from a database owned by a third party
- Responses received from external APIs

### U1.2 — Validation Must Be Complete

RULE: Validation MUST check all four dimensions for every field. Checking only one or two dimensions is insufficient.

REQUIRED VALIDATION DIMENSIONS:
- TYPE — the value must be of the expected type (string, integer, boolean, UUID)
- FORMAT — the value must match the expected pattern (ISO 8601 date, email format, UUID v4)
- RANGE — the value must be within acceptable bounds (positive amount, valid currency code)
- LENGTH — the value must not exceed the maximum permitted length (string length, array size, file size)

VIOLATIONS:
- Input passed to a service method without any validation = HIGH
- Input type checked but format, range, or length not checked = MEDIUM
- Unknown or unexpected fields silently ignored instead of rejected = MEDIUM
- File upload accepted without validating MIME type, extension, and size independently = HIGH

### U1.3 — Validation Failure Response

RULE: When validation fails the response MUST return HTTP 400 (Bad Request) or HTTP 422 (Unprocessable Entity) with a safe, structured error message. The response MUST NEVER contain stack traces, internal error messages, database schema details, file paths, or PII.

VIOLATIONS:
- Stack trace returned in a validation failure response = HIGH
- Internal error message included in a 400 or 422 response = HIGH
- Validation failure responded to with a 500 status code = MEDIUM
- No error response returned on validation failure (silent acceptance of invalid input) = HIGH

---

## SECTION U2 — SECURITY: SECRET MANAGEMENT

### U2.1 — No Secrets in Source Code

RULE: The following are CRITICAL violations that block merge immediately. No review score or comment can override a CRITICAL finding. If any of the following are detected the MERGE_RECOMMENDATION MUST be BLOCK.

PROHIBITED — presence of any of the following = CRITICAL:
- Passwords in source code
- API keys in source code
- Authentication tokens in source code
- Database connection strings (DSNs) in source code
- Private cryptographic keys in source code
- Secrets in code comments
- Secrets in test files
- Secrets in example or sample configuration files committed to the repository
- .env files committed to the repository
- Secrets logged at any log level

### U2.2 — Required Secret Injection Methods

RULE: All secrets MUST be injected at runtime via one of the following approved mechanisms. No other mechanism is permitted for production secrets.

APPROVED MECHANISMS:
- Environment variables for simple cases
- AWS SSM Parameter Store for AWS-hosted services
- GCP Secret Manager for GCP-hosted services
- HashiCorp Vault for multi-cloud or on-premises services

ADDITIONAL REQUIREMENTS:
- All credentials MUST be rotatable without a code deployment
- Pre-commit secret scanning MUST be configured using detect-secrets or gitleaks
- Secret scanning MUST run as a CI gate before any merge

VIOLATIONS:
- Secret injected via a mechanism not on the approved list = HIGH
- No pre-commit secret scanning configured = HIGH
- Secret scanning not present as a CI gate = HIGH

### U2.3 — Incident Response for Accidentally Committed Secrets

RULE: If a secret is detected in a commit the following actions are MANDATORY and IMMEDIATE. These are not optional steps.

REQUIRED ACTIONS IN ORDER:
1. Rotate the secret immediately. Treat it as compromised from the moment of commit.
2. Remove the secret from git history using git filter-branch or BFG Repo Cleaner.
3. File a security incident report with the Security team within 24 hours.

VIOLATIONS:
- Evidence that a previously committed secret was not rotated = CRITICAL
- Secret removed from current code but still present in git history = CRITICAL

---

## SECTION U3 — SECURITY: INJECTION PREVENTION

### U3.1 — Injection Attack Prevention Rules

RULE: String concatenation or string interpolation used to construct any query, command, or output that will be interpreted by another system is a CRITICAL violation. This applies without exception to all attack surfaces listed below.

REQUIRED PREVENTION BY ATTACK TYPE:

SQL injection: Use parameterized queries or prepared statements only. String concatenation in SQL = CRITICAL.

HTML and XSS injection: Use context-aware output encoding. Use a templating engine with auto-escaping enabled. Raw user data in templates = HIGH.

Shell injection: Use execFile or equivalent with an explicit arguments array. Never pass user input to exec, shell_exec, system, or equivalent. exec with user input = CRITICAL.

LDAP injection: Escape all special characters. Use framework-level LDAP abstractions that handle escaping. Never build LDAP filter strings from user input = HIGH.

XML and XXE injection: Disable external entity processing in all XML parsers. Never parse user-supplied XML with external entity processing enabled = HIGH.

Path traversal: Validate and normalize all file paths. Use a whitelist of permitted directories. Never construct file paths from user input without normalization = HIGH.

VIOLATIONS:
- String concatenation used to build a SQL query = CRITICAL
- String interpolation used to build a SQL query = CRITICAL
- User input passed to exec or shell equivalent = CRITICAL
- Raw user data rendered into an HTML template without escaping = HIGH
- XML parser used with external entity processing enabled = HIGH
- File path constructed from user input without normalization and directory whitelist = HIGH

---

## SECTION U4 — ERROR HANDLING: TWO-LAYER MODEL

### U4.1 — Internal Error Layer

RULE: The internal error representation MUST contain full diagnostic detail. It MUST be written to the structured log only. It MUST NEVER be sent to a client.

INTERNAL LAYER MUST CONTAIN:
- Full error message
- Stack trace
- Request context (correlation ID, user ID, entity IDs)
- Query or operation that failed
- All relevant parameters (with PII redacted)

INTERNAL LAYER MUST NEVER:
- Be serialized into an HTTP response body
- Be included in a redirect URL
- Be sent to a client via any channel

### U4.2 — Public Error Layer

RULE: The public error response returned to API consumers MUST be opaque and safe. It MUST contain a human-readable message that does not expose internal detail, and a correlation ID that links the response to the internal log entry. The HTTP status code MUST be semantically correct.

CORRECT PUBLIC ERROR PATTERN:
Client receives: { "error": "Payment not found", "ref": "a3f8bc92" }
Logger receives: { "level": "error", "ref": "a3f8bc92", "query": "SELECT...", "params": {...}, "stack": "..." }

REQUIRED PUBLIC RESPONSE FIELDS:
- error: safe, opaque human-readable message
- ref: correlation ID linking to the internal log entry

PROHIBITED IN PUBLIC RESPONSE:
- Stack traces
- Internal file paths
- Database query text or schema details
- PII including names, emails, card numbers
- Internal service names or infrastructure topology

VIOLATIONS:
- Stack trace present in HTTP response body = HIGH
- Internal error message included in HTTP response body = HIGH
- PII present in HTTP error response = CRITICAL
- No correlation ID in error response = MEDIUM
- 5xx response with no corresponding internal log entry = HIGH
- HTTP status code semantically incorrect (e.g., 200 returned for an error) = MEDIUM

---

## SECTION U5 — LOGGING STANDARDS

### U5.1 — Structured Logging Required

RULE: All logging in service code MUST use a structured logging library that produces JSON or key-value pair output. Unstructured printf-style logging (console.log, fmt.Printf, print, System.out.println) is PROHIBITED in service, handler, repository, and middleware code.

REQUIRED FIELDS IN EVERY LOG ENTRY:
- timestamp: ISO 8601 format in UTC
- level: one of debug, info, warn, error
- service: the name of the service producing the log
- correlation_id: the request trace ID linking all log entries for one request
- message: a human-readable description of the event
- Relevant entity IDs where applicable: payment_id, user_id, account_id

VIOLATIONS:
- Unstructured printf-style logging in service code = MEDIUM
- Log entry missing timestamp = MEDIUM
- Log entry missing correlation_id = MEDIUM
- Log entry missing service name = LOW
- Structured logging library not used = MEDIUM

### U5.2 — Sensitive Data Must Never Be Logged

RULE: The following categories of data MUST NEVER appear in any log entry at any log level. This applies to raw values, partial values unless the exception below applies, and values derived from or containing the prohibited data.

NEVER LOG:
- Passwords at any stage of processing (plaintext, hashed, or partial)
- Full payment card numbers (log last 4 digits only)
- Social security numbers or national identity numbers
- Authentication tokens or session IDs
- Full API keys (log first 4 and last 4 characters only if needed for debugging)
- Raw request bodies that may contain any of the above

VIOLATIONS:
- Password logged at any level in any form = CRITICAL
- Full card number present in any log entry = CRITICAL
- Authentication token logged = CRITICAL
- SSN or national ID logged = CRITICAL
- Full API key logged = HIGH
- Raw request body logged without PII scrubbing = HIGH

### U5.3 — Log Level Discipline

RULE: Log levels MUST reflect the nature of the event. Using ERROR for expected client behaviour artificially raises alert noise and desensitises on-call engineers to real failures.

REQUIRED LOG LEVEL MAPPING:
- DEBUG: Variable values, query details, function entry and exit. MUST be disabled by default in production.
- INFO: Normal operational events such as payment created, refund initiated, user authenticated.
- WARN: Unexpected but handled conditions such as rate limit approaching, retry attempt, deprecated API used, or elevated 4xx rate.
- ERROR: Failures that affect a user request or system function such as payment failed, database connection lost, or downstream service timeout.

EXPLICITLY PROHIBITED:
- Using ERROR for a client 4xx response. Client errors are expected. Log at WARN or INFO only if elevated rates require monitoring.

VIOLATIONS:
- ERROR level used for a client 4xx condition = MEDIUM
- DEBUG logging enabled by default in production configuration = MEDIUM
- No logging present for a failure that affects a user request = HIGH
- INFO level used for a security-relevant event that should be WARN = LOW

---

## SECTION U6 — COMPLEXITY LIMITS

### U6.1 — Complexity Metrics and Hard Limits

RULE: The following complexity limits apply to all code in all languages. Targets are advisory. Hard limits block merge. SonarQube measures these in CI. Exceeding a hard limit is a merge-blocking finding.

REQUIRED LIMITS:
- Cognitive complexity per function: TARGET 10, HARD LIMIT 15
- Function length in lines: TARGET 50 lines, HARD LIMIT 80 lines
- Parameters per function: HARD LIMIT 5 (group into a struct or object for more)
- Nesting depth: HARD LIMIT 3 levels (use guard clauses and early returns)
- File length in lines: TARGET 500 lines (split by responsibility if exceeded)

VIOLATIONS:
- Function with cognitive complexity above 15 = MEDIUM
- Function exceeding 80 lines = MEDIUM
- Function with more than 5 parameters = MEDIUM
- Nesting depth exceeding 3 levels = MEDIUM
- File exceeding 500 lines without a documented justification = LOW

### U6.2 — Guard Clauses Over Nesting

RULE: The happy path MUST remain at the leftmost indentation level. Handle error cases immediately at the point of detection and return early. Do not nest the happy path inside conditional blocks.

VIOLATIONS:
- Happy path buried under two or more levels of nesting = MEDIUM
- Error condition handled via else branch instead of early return = LOW
- Nested if/else chain that could be flattened with guard clauses = MEDIUM

---

## SECTION U7 — NAMING PRINCIPLES

### U7.1 — Names Must Reveal Intent

RULE: Every identifier including variables, functions, methods, classes, and constants must communicate its purpose to a reader who has no prior context. If the name requires a comment to explain what it refers to, the name is wrong.

VIOLATIONS:
- Variable or function name that requires a comment to understand = LOW
- Single-letter variable name used outside of a loop counter (i, j, k) or a mathematical convention = LOW
- Abbreviation used that is not on the approved list below = LOW

APPROVED ABBREVIATIONS ONLY:
ctx, err, id, url, db, cfg, req, res, msg, ok, buf, idx

Any abbreviation not on this list requires the full word or a descriptive name.

### U7.2 — No Magic Numbers or Magic Strings

RULE: Numeric literals and string literals that represent a domain concept MUST be extracted to a named constant or enum. Inline magic values make code unreadable and create maintenance risk when the value needs to change.

VIOLATION PATTERN:
if retries > 3 { ... }
if status == "pending" { ... }

CORRECT PATTERN:
if retries > MaxPaymentRetries { ... }
if status == PaymentStatus.Pending { ... }

VIOLATIONS:
- Numeric literal used inline that represents a domain or configuration concept = LOW
- String literal used inline that represents a domain state, status, or code = LOW
- Same magic value duplicated in multiple locations = MEDIUM

### U7.3 — Boolean Names Are Propositions

RULE: Boolean variable and function names MUST be phrased as a proposition that is either true or false. The name must make the true and false states self-evident without reading the code that sets the value.

REQUIRED PATTERN: isXxx, hasXxx, canXxx, shouldXxx, wasXxx

VIOLATIONS:
- Boolean named without a proposition prefix = LOW
- Boolean named active, deleted, enabled where isActive, isDeleted, isEnabled would be clearer = LOW
- Boolean named so that the true state is ambiguous = LOW

### U7.4 — Consistent Vocabulary

RULE: Choose one word per concept and use it consistently throughout the entire codebase. Mixing synonyms for the same operation creates cognitive overhead and makes text-search-based navigation unreliable.

EXAMPLES OF PROHIBITED MIXING:
- fetchUser in one file and getUser in another when both retrieve a user by ID = LOW
- createPayment in one service and makePayment in another = LOW
- store and repository used interchangeably for the same layer = LOW

VIOLATIONS:
- Multiple synonyms used for the same operation across files = LOW

---

## SECTION U8 — COMMENTS AND DOCUMENTATION

### U8.1 — Documentation Is Required

RULE: The following code elements MUST have documentation comments explaining their purpose, parameters, and return values. Absence of documentation on these elements is a violation.

REQUIRED DOCUMENTATION TARGETS:
- Public API endpoints: purpose, authentication requirement, request schema, response schema, error codes
- Exported or public functions and methods: what it does, what each parameter means, what it returns
- Public classes and interfaces: the role they play in the system
- Non-obvious algorithmic decisions: why this approach was chosen over alternatives
- Workarounds for external system bugs: cite the bug report or ticket number
- Business rule implementations: cite the requirement or ticket number

VIOLATIONS:
- Public API endpoint with no documentation comment = LOW
- Exported function with no documentation comment = LOW
- Non-obvious algorithm with no explanation of why it works = MEDIUM
- Workaround with no reference to the external bug being worked around = MEDIUM

### U8.2 — Comments Explain Why, Not What

RULE: Comments MUST explain the reasoning, trade-offs, or constraints that motivated the code. Comments that restate what the code literally does add noise without value and MUST be removed.

VIOLATION PATTERN (WHAT comment):
i++

CORRECT PATTERN (WHY comment):
We use idempotency keys here because the payment gateway may return a timeout
even after successfully processing the charge. Without this key we would create
duplicate charges on retry. [TICKET-892]

VIOLATIONS:
- Comment that only restates what the code literally does = INFO
- Comment explaining a non-obvious decision with no reasoning = LOW

### U8.3 — No Commented-Out Code

RULE: Commented-out code MUST NOT be present in any file on the main branch or in any pull request targeting the main branch. Version control preserves history. Commented-out code clutters files and creates confusion about whether it is intentionally disabled or forgotten.

VIOLATIONS:
- Block of commented-out code present in a production file = LOW

### U8.4 — TODO Format Is Enforced

RULE: TODO comments MUST follow the exact format below. TODOs without all three required components are a violation.

REQUIRED TODO FORMAT:
TODO(owner.name): [TICKET-123] Description of what needs to be done — by YYYY-QN

EXAMPLE:
TODO(john.smith): [PAY-1234] Migrate to async queue — by 2026-Q3

REQUIRED COMPONENTS:
- owner.name: the person responsible for resolving the TODO
- TICKET-123: a linked ticket in the issue tracker
- by YYYY-QN: a target quarter for resolution

VIOLATIONS:
- TODO with no owner = MEDIUM
- TODO with no linked ticket = MEDIUM
- TODO with no target date = MEDIUM
- TODO older than two quarters from today's date with no update = MEDIUM

---

## SECTION U9 — TESTING REQUIREMENTS

### U9.1 — Minimum Coverage Targets

RULE: The following coverage targets are enforced in CI. Falling below these targets is a violation. Coverage is a floor, not a goal. High coverage with weak assertions is worse than lower coverage with precise assertions.

REQUIRED MINIMUM COVERAGE BY LAYER:
- Business and domain logic layer: 85% line coverage
- API handler layer: 80% line coverage
- Data access layer: 75% line coverage

VIOLATIONS:
- Business logic layer below 85% coverage = MEDIUM
- API handler layer below 80% coverage = MEDIUM
- Data access layer below 75% coverage = MEDIUM
- New business logic added with no corresponding tests = HIGH

### U9.2 — Every Test Must Cover Three Paths

RULE: Every test suite for a unit of logic MUST include tests for the following three categories. A suite that only covers the happy path is incomplete.

REQUIRED TEST CATEGORIES:
1. Happy path: valid input produces the expected output
2. Edge cases: boundary values, empty collections, zero amounts, maximum lengths
3. Error and failure paths: invalid input, dependency failures, timeouts, network errors

VIOLATIONS:
- Test suite covering only the happy path = MEDIUM
- No test for error or failure paths in a function that returns errors = MEDIUM
- No test for boundary values in a function with range constraints = LOW

### U9.3 — Test Quality Rules

RULE: Tests MUST meet all of the following quality criteria. Tests that violate these criteria produce false confidence and increase maintenance cost.

REQUIRED TEST PROPERTIES:

Deterministic: Tests MUST produce the same result on every run. No random sleep, no time.Now() without clock injection, no dependence on execution order.

Independent: No test may depend on state left by another test. Each test sets up its own state and tears it down.

Fast: Unit tests MUST complete in under 100ms each. Integration tests MUST be isolated with explicit setup and teardown.

Isolated from production: No if testing_mode or equivalent flag in production code that changes behaviour during tests.

Using test doubles: All external dependencies including databases, HTTP clients, file systems, and message queues MUST be replaced with mocks, stubs, or fakes in unit tests. Real infrastructure is only permitted in explicitly labelled integration tests.

VIOLATIONS:
- Test using time.Now() or equivalent without clock injection = MEDIUM
- Test that depends on execution order or state from a previous test = HIGH
- Production code containing a testing mode flag = HIGH
- Unit test making a real database query or network call = MEDIUM
- No setup or teardown in an integration test that modifies shared state = MEDIUM

---

## SECTION U10 — DEPENDENCIES AND SUPPLY CHAIN

### U10.1 — Dependency Justification Required

RULE: Before any new dependency may be merged the following five checks MUST be completed and documented in docs/dependencies.md. A new dependency with no documented justification is a violation.

REQUIRED PRE-ADDITION CHECKS:
1. Actively maintained: the dependency must have had a commit within the last 6 months
2. Security history: check the CVE database for known vulnerabilities in the dependency and its transitive dependencies
3. Standard library alternative: confirm there is no standard library function that would satisfy the requirement
4. License compatibility: confirm the license is compatible with commercial use (GPL may be incompatible)
5. Documented justification: record the answers to checks 1 through 4 in docs/dependencies.md

VIOLATIONS:
- New dependency added with no entry in docs/dependencies.md = LOW
- New dependency with no commit in the last 6 months = MEDIUM
- New dependency with a GPL or other potentially incompatible license and no legal review = HIGH

### U10.2 — Version Pinning

RULE: All dependencies MUST be pinned to an exact version in the relevant lock file. Floating version specifiers are PROHIBITED in production dependency definitions.

PROHIBITED VERSION SPECIFIERS:
- latest
- * (wildcard)
- ^major.x (caret range in npm)
- ~major.minor.x (tilde range)
- >= without an upper bound

REQUIRED:
- go.sum for Go modules
- package-lock.json or yarn.lock for Node.js
- composer.lock for PHP
- Maven lock or Gradle lock file for Java

VIOLATIONS:
- Dependency version specified as latest = MEDIUM
- Dependency version specified with a wildcard or range operator = MEDIUM
- Lock file absent from the repository = HIGH
- Lock file present but not committed or not up to date = MEDIUM

### U10.3 — Automated Vulnerability Scanning

RULE: Dependency vulnerability scanning MUST run as a required CI gate before every merge. A known CVE in a direct dependency is a merge blocker until the dependency is updated or a written exception is granted by the Security team.

REQUIRED SCANNING TOOLS BY LANGUAGE:
- Go: govulncheck ./...
- Node.js: npm audit --audit-level=high
- PHP: composer audit
- Java: OWASP Dependency Check Maven or Gradle plugin

REQUIRED CI BEHAVIOUR:
- HIGH CVE in direct dependency: merge blocked
- CRITICAL CVE in direct dependency: merge blocked and security incident filed
- Exception process: written approval from Security team required, time-limited, tracked in the dependency document

VIOLATIONS:
- Vulnerability scanning not configured in CI = HIGH
- Known HIGH CVE in a direct dependency with no exception documented = HIGH
- Known CRITICAL CVE in a direct dependency = CRITICAL
- Vulnerability scan skipped for a merge = HIGH

### U10.4 — Unused Dependencies

RULE: Unused dependencies MUST be removed. They increase the attack surface, slow build times, and create confusion about what the project requires.

VIOLATIONS:
- Dependency present in the dependency manifest but not imported or used anywhere = LOW

---

## SECTION U11 — SEVERITY TABLE

CRITICAL — Secret in source code, SQL injection, shell injection, full PAN storage, plaintext password, or unhandled CVE. Action: Block merge immediately. No override permitted.
HIGH — Stack trace in response, PII in log, missing auth, no test for new logic, dependency CVE, or missing CI gate. Action: Block merge. Fix required before approval.
MEDIUM — Missing validation dimension, incorrect log level, complexity limit exceeded, TODO without required fields, or below-coverage threshold. Action: Fix within current sprint.
LOW — Magic number, naming convention violation, missing documentation comment, commented-out code, or advisory style issue. Action: Add to backlog.
INFO — Observation or suggestion with no compliance impact. Action: Optional.

---

## SECTION U12 — STANDARDS_SCORE RUBRIC

Assign a single integer score from 1 to 10 after all findings across all sections (universal and language-specific) are listed.

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

*Universal Standards Version: 2.1 | Last Reviewed: March 2026*
*Owner: Engineering Standards Committee*
*These standards apply unconditionally to all languages and all code.*
*No exceptions without written sign-off from the Security team.*
*Amendments: Raise a PR against scripts/standards/universal_standards.md*