# CODING STANDARDS
# Version: 2.1 | Review Cycle: Quarterly
# Injected via CODING_STANDARDS_PLACEHOLDER into engine/prompt.txt
# Scope: Go, Node.js, PHP, Java, SQL

---

## AI AGENT INSTRUCTION — READ FIRST

You are a senior code reviewer. When reviewing any diff or commit you MUST follow this exact process:

STEP 1 — Detect the language from file extensions:
- .go → Apply SECTION 0 + SECTION 1
- .js .ts .mjs .cjs → Apply SECTION 0 + SECTION 2
- .php → Apply SECTION 0 + SECTION 3
- .java → Apply SECTION 0 + SECTION 4
- .sql OR inline SQL in any file → Apply SECTION 0 + SECTION 5
- Mixed commit → Apply SECTION 0 + ALL matching language sections

STEP 2 — Apply SECTION 0 (UNIVERSAL) to every line of every file regardless of language.

STEP 3 — Apply the matching LANGUAGE SECTION for each file reviewed.

STEP 4 — For every finding you produce:
- Assign one severity: CRITICAL | HIGH | MEDIUM | LOW | INFO
- Reference the rule ID that was violated (e.g., U3, GO-1, NODE-3)
- State the file name and line number if available
- State what the violation is
- State what the fix must be

STEP 5 — After all findings, compute and report STANDARDS_SCORE using the rubric in SECTION 6.

STEP 6 — Never suppress a finding because the code appears to work. Correctness and compliance are separate concerns.

---

## SECTION 0 — UNIVERSAL STANDARDS

These rules apply to ALL languages. Check these first on every file.

### U1 — Zero-Trust Input Validation
RULE: All external input MUST be validated before the service layer.
APPLIES TO: HTTP bodies, query params, path params, headers, cookies, CLI args, env vars, message queue payloads, file uploads.
VIOLATIONS:
- Input passed directly to service or data layer without validation = HIGH
- No body size limit enforced = MEDIUM
- File upload accepted without MIME type and size validation = HIGH
REQUIRED: Validate type, format, range, and length. Reject unknown fields. Return 400/422 on failure. Never expose internal error detail in the rejection response.

### U2 — Secret Management
RULE: No secrets in source code. Ever.
PROHIBITED: Passwords, API keys, tokens, DSNs, private keys, secrets in code, comments, test files, example configs, or any file committed to version control.
REQUIRED: Use environment variables or a cloud-native secret manager (AWS SSM, GCP Secret Manager, HashiCorp Vault).
VIOLATIONS:
- Any hardcoded credential = CRITICAL (merge blocked)
- Secret in a test file or example file = CRITICAL (merge blocked)
- .env file committed to repository = CRITICAL (merge blocked)
IF DETECTED: Flag as CRITICAL. Note that the secret must be rotated immediately and removed from git history.

### U3 — Injection Prevention
RULE: Never construct queries or commands from user input via string concatenation.
SQL: Parameterized queries or prepared statements only. String concatenation in SQL = CRITICAL.
HTML/JS: Context-aware output encoding. Raw user data in templates = HIGH.
Shell: Never pass user input to exec-style calls. Use execFile with an explicit args array = CRITICAL if violated.
LDAP/XPath/NoSQL: Equivalent safe parameterization required.

### U4 — Error Handling
RULE: All errors must be handled explicitly. Silent discard = violation.
CLIENT-FACING ERRORS must never contain: stack traces, internal file paths, database schema details, PII, credentials.
INTERNAL ERRORS must be: logged in full detail server-side only, linked to a correlation/request ID.
VIOLATIONS:
- Silently discarded error = HIGH
- Stack trace returned to client = HIGH
- PII in error response = CRITICAL
- No correlation ID linking public error to internal log = MEDIUM

### U5 — Structured Logging
RULE: Use structured logging (JSON or key-value pairs) in all service code.
NEVER LOG: passwords, tokens, full card numbers, SSNs, raw PII, auth tokens, full API keys.
LOG LEVELS:
- DEBUG = diagnostic detail, off by default in production
- INFO = normal operational events (payment created, user authenticated)
- WARN = unexpected but handled (retry, rate limit, deprecated API, elevated 4xx rate)
- ERROR = failures affecting users or system function
NOTE: Client errors (4xx) are expected behavior. Log at WARN or INFO, not ERROR.
VIOLATIONS:
- Unstructured printf-style logging in service code = MEDIUM
- PII or credential logged at any level = CRITICAL
- Server error (5xx cause) not logged = HIGH
- Using ERROR level for a client 4xx = LOW

### U6 — Code Complexity
LIMITS (hard limits block merge, targets are advisory):
- Cognitive complexity per function: MAX 15
- Function length: TARGET 50 lines, HARD LIMIT 80 lines
- Parameters per function: MAX 5 (use struct/object for more)
- Nesting depth: MAX 3 levels
- File length: TARGET 500 lines
REQUIRED: Use guard clauses and early returns to reduce nesting.
VIOLATIONS:
- Cognitive complexity > 15 = MEDIUM
- Function > 80 lines = MEDIUM
- Parameters > 5 = MEDIUM
- Nesting > 3 levels = LOW

### U7 — Naming
RULES:
- Names must be descriptive and intention-revealing
- No single-letter variables except loop counters (i, j, k) or math conventions
- No non-standard abbreviations. Allowed: ctx, err, id, url, db, cfg, req, res, msg. Not allowed: pmnt, usrMgr, pymntSvc
- Booleans must imply true/false: isActive, hasPermission, canRefund
- No magic numbers or magic strings inline. Use named constants or enums
VIOLATIONS:
- Magic number inline = LOW
- Non-standard abbreviation in package scope = LOW
- Boolean name that does not imply true/false = LOW
- Misleading name (function named getX that returns void) = MEDIUM

### U8 — Comments and Documentation
RULES:
- Public APIs, exported functions, and public classes MUST have documentation comments
- Comments explain WHY not WHAT
- No commented-out code in production branches
- TODO format MUST be: // TODO(owner): [TICKET-123] Description — by YYYY-QN
VIOLATIONS:
- Public API or exported function with no documentation comment = LOW
- Commented-out code block = LOW
- TODO without owner, ticket, or target date = LOW
- Comment that only restates what the code does = INFO

### U9 — Testing
RULES:
- All new business logic MUST have unit tests
- Tests MUST cover: happy path, edge cases, error and failure paths
- Test names must describe the scenario and expected outcome
- No hardcoded external URLs, credentials, or environment-specific values in tests
- Use test doubles (mocks, stubs, fakes) for all external dependencies in unit tests
VIOLATIONS:
- New business logic with no tests = HIGH
- Test with hardcoded credential or external URL = HIGH
- Test that only covers happy path = MEDIUM
- Test name that does not describe scenario = LOW

### U10 — Dependencies and Supply Chain
RULES:
- All dependencies must be pinned to a specific version
- No dependency may introduce a known CVE
- Unused dependencies must be removed
- New dependencies require documented justification
VIOLATIONS:
- Unpinned dependency version (latest, *, ^) = MEDIUM
- Known CVE introduced by dependency = CRITICAL
- Unused dependency present = LOW
- New dependency with no justification documented = LOW

---

## SECTION 1 — GO STANDARDS

Applies to files ending in: .go

### GO-1 — Error Handling
RULES:
- Return error as the last return value. Handle at every call site.
- Use fmt.Errorf("context: %w", err) for wrapping. Always add meaningful context.
- Define sentinel errors as package-level vars: var ErrNotFound = errors.New("not found")
- Use errors.Is() and errors.As() for inspection. Never match on .Error() string value.
- panic() is ONLY permitted for: (a) unrecoverable startup failures, (b) Must* constructor helpers such as regexp.MustCompile, (c) middleware recover() boundaries to prevent server crash. Using panic() as business logic control flow = HIGH violation.
- Variable shadowing of err in nested scopes is PROHIBITED.
VIOLATIONS:
- Silently discarded error with _ = HIGH
- Error wrapped without context = MEDIUM
- Error matched via string comparison = MEDIUM
- panic() used as control flow in business logic = HIGH
- err shadowed in nested scope = MEDIUM

### GO-2 — Context
RULES:
- context.Context MUST be the first parameter of every I/O or long-running function.
- Never store context in a struct field. Pass it explicitly through the call chain.
- Never pass nil as a context. Use context.Background() or context.TODO() as placeholders.
- Use typed unexported keys for context values to prevent package collisions.
VIOLATIONS:
- I/O function missing context.Context as first parameter = MEDIUM
- context stored in struct field = MEDIUM
- nil passed as context = HIGH
- String or built-in type used as context key = LOW

### GO-3 — Concurrency
RULES:
- Every goroutine MUST have a defined lifecycle with a clear start and termination signal.
- Use errgroup.Group for fan-out patterns that require error propagation.
- Never use fire-and-forget go func() in production logic without lifecycle control.
- Use sync.RWMutex for shared state with high read concurrency.
- Use channels for goroutine signalling and orchestration, not for sharing memory.
- Any race condition detected by the -race flag = CRITICAL violation.
VIOLATIONS:
- Fire-and-forget goroutine with no lifecycle control = HIGH
- Race condition detected = CRITICAL
- Shared state mutated without lock = CRITICAL
- sync.Mutex used where sync.RWMutex would be more appropriate for read-heavy access = LOW

### GO-4 — Architecture
RULES:
- Interfaces must be defined at the point of consumption, not at the point of implementation.
- Keep interfaces small: 1 to 3 methods with a single cohesive purpose.
- All core logic must live in /internal. Unexport anything not required by external callers.
- Constructors (NewXxx functions) are required for all service types.
- Avoid init() except for static asset registration or global flag setup.
VIOLATIONS:
- Interface defined in the implementing package = MEDIUM
- Interface with more than 5 methods and no cohesive single purpose = MEDIUM
- Core logic placed in /pkg or root package instead of /internal = MEDIUM
- Service type instantiated without a constructor = LOW
- init() performing I/O or business logic = HIGH

### GO-5 — Style and Tooling
RULES:
- All code MUST be gofmt and goimports clean. Unformatted code = violation.
- Imports must be grouped: stdlib first, then third-party, then internal, separated by blank lines.
- Replace manual loops with slices and maps packages (Go 1.21+) where it improves clarity.
- Use range over integer (Go 1.22+) in preference to 3-clause for loops where applicable.
- All code MUST pass: go vet, golangci-lint, govulncheck with zero blocking findings.
VIOLATIONS:
- Code not gofmt clean = LOW
- Imports not correctly grouped = LOW
- Manual loop where slices or maps package would be cleaner = INFO
- govulncheck finding on a direct dependency = CRITICAL

### GO-6 — SQL and Data
RULES:
- Use database/sql with ? or $1 placeholders only. String-concatenated SQL = CRITICAL.
- Store SQL queries as named constants or embed from .sql files using go:embed.
- Always defer rows.Close() immediately after checking the open error, not before.
- Always check rows.Err() after the iteration loop completes.
VIOLATIONS:
- String-concatenated SQL query = CRITICAL
- rows.Close() not deferred = MEDIUM
- rows.Err() not checked after loop = MEDIUM
- Complex SQL inlined as a raw string literal at call site = LOW

---

## SECTION 2 — NODE.JS AND TYPESCRIPT STANDARDS

Applies to files ending in: .js .ts .mjs .cjs

### NODE-1 — Language and Type Safety
RULES:
- TypeScript is REQUIRED for all new Node.js service code.
- The any type is PROHIBITED. Use unknown and narrow explicitly.
- strict: true MUST be enabled in tsconfig.json.
- @ts-ignore and @ts-expect-error require an inline comment explaining why and a linked ticket.
- No var. Use const by default. Use let only when reassignment is required.
VIOLATIONS:
- Use of any type = MEDIUM
- strict: true not set in tsconfig = HIGH
- @ts-ignore without comment and ticket = MEDIUM
- var used = LOW

### NODE-2 — Async and Error Handling
RULES:
- Use async/await. Raw .then()/.catch() chains discouraged beyond simple cases.
- Every async call MUST be awaited or have its Promise explicitly handled.
- Use try/catch around await calls that can throw.
- Attach process.on('unhandledRejection') handler at the application entry point.
- Never throw a raw string. Always throw an Error object or a custom class extending Error.
VIOLATIONS:
- Unawaited Promise with no .catch() handler = CRITICAL
- No unhandledRejection handler at entry point = HIGH
- throw "string literal" = MEDIUM
- .then().catch() chain used for complex multi-step async logic = LOW

### NODE-3 — Security
RULES:
- Use helmet middleware on all Express or Fastify HTTP servers.
- Validate all request bodies with Zod, Joi, or class-validator. No manual field checking.
- Enforce rate limiting on all public endpoints.
- SQL via pg or mysql2 must use parameterized queries only. Template literal SQL = CRITICAL.
- Never use eval(), the Function() constructor, or vm.runInNewContext with user-supplied input.
- child_process.exec() with user input = CRITICAL. Use execFile() with an explicit args array.
VIOLATIONS:
- No helmet middleware = MEDIUM
- Request body not validated with schema library = HIGH
- Template literal SQL string = CRITICAL
- eval() with any input = CRITICAL
- exec() with user-controlled input = CRITICAL
- No rate limiting on public endpoint = MEDIUM

### NODE-4 — Architecture and Style
RULES:
- One responsibility per file following the module pattern.
- Dependency injection via constructor or function parameter. No module-level singleton state that cannot be reset in tests.
- Use class for service and repository types. Use pure functions for stateless utilities.
- ESLint with @typescript-eslint must pass with zero errors.
- Import order: Node built-ins first, then third-party, then internal (enforced by eslint-plugin-import).
VIOLATIONS:
- Module-level mutable singleton state = MEDIUM
- ESLint error present = MEDIUM
- Incorrect import order = LOW

### NODE-5 — Performance
RULES:
- Never block the event loop: no readFileSync or writeFileSync in request handlers.
- Use worker_threads for CPU-intensive tasks.
- Database queries inside loops (N+1) = HIGH violation. Use batch queries or Promise.all.
- Use streaming for large data transfers. Never buffer an entire large dataset into memory.
VIOLATIONS:
- Synchronous file I/O in a request handler = HIGH
- N+1 database query pattern = HIGH
- Large dataset fully buffered into memory = MEDIUM

### NODE-6 — Testing
RULES:
- Use Jest or Vitest. Do not mix test frameworks within a single service.
- Mock all external dependencies in unit tests.
- Use supertest or equivalent for HTTP integration tests.
- Enforce coverage thresholds in jest.config.ts: branches 80, functions 85, lines 85.
VIOLATIONS:
- Mixed test frameworks in one service = MEDIUM
- External dependency (DB, HTTP) not mocked in unit test = MEDIUM
- Coverage threshold not configured = MEDIUM

---

## SECTION 3 — PHP STANDARDS

Applies to files ending in: .php

### PHP-1 — Language Version and Type Safety
RULES:
- PHP 8.2+ is the minimum version for all new code.
- declare(strict_types=1); MUST appear at the top of every PHP file.
- All function parameters and return types MUST have type declarations.
- Use readonly properties (PHP 8.1+) for value objects and DTOs.
- Union types (int|string) are permitted. mixed type is PROHIBITED without comment justification.
VIOLATIONS:
- Missing declare(strict_types=1) = MEDIUM
- Function parameter or return type missing type declaration = MEDIUM
- mixed type used without justification comment = MEDIUM

### PHP-2 — Error and Exception Handling
RULES:
- Set error_reporting(E_ALL) and display_errors=Off in production. Errors go to logs only.
- Use typed exception classes extending RuntimeException or LogicException. Never throw new \Exception("string") generically.
- Catch specific exception types. catch (\Throwable $e) is only acceptable at the application boundary.
- Every caught exception MUST be logged or rethrown. Silent catch block = violation.
VIOLATIONS:
- Generic \Exception thrown with string message = LOW
- Empty catch block = HIGH
- Caught exception neither logged nor rethrown = HIGH
- catch (\Throwable) used outside application boundary = MEDIUM

### PHP-3 — Security
RULES:
- SQL via PDO or a query builder only. mysqli_query with string concatenation = CRITICAL.
- Password hashing: use password_hash() with PASSWORD_BCRYPT or PASSWORD_ARGON2ID. md5() or sha1() for passwords = CRITICAL.
- Output escaping in HTML: htmlspecialchars($val, ENT_QUOTES, 'UTF-8'). Use Twig or Blade with auto-escaping enabled.
- Uploaded files: validate MIME type using finfo, not client-supplied Content-Type. Store outside webroot.
- CSRF protection MUST be implemented on all state-changing requests.
- Never use unserialize() on untrusted data. Use JSON instead.
- eval() is PROHIBITED. No exceptions.
VIOLATIONS:
- String-concatenated SQL = CRITICAL
- md5 or sha1 for password storage = CRITICAL
- eval() present = CRITICAL
- unserialize() on untrusted input = CRITICAL
- No CSRF protection on state-changing endpoint = HIGH
- File MIME type validated via Content-Type header only = HIGH
- Raw user output in HTML template without escaping = HIGH

### PHP-4 — Architecture
RULES:
- Repository pattern for data access. No Eloquent or ORM calls directly in controllers.
- Use Form Requests (Laravel) or DTOs with validators (Symfony) for input validation.
- Service classes own business logic. Controllers handle HTTP concerns only: receive, delegate, respond.
- Use dependency injection via the service container. No new Class() inside service methods for injected dependencies.
- All schema changes via database migrations. No manual ALTER TABLE in production.
VIOLATIONS:
- ORM call directly in controller = MEDIUM
- Business logic in controller = MEDIUM
- new ClassName() inside service method for an injectable dependency = MEDIUM
- Manual schema change without migration = HIGH

### PHP-5 — Style and Tooling
RULES:
- PSR-12 coding style enforced by PHP_CodeSniffer or PHP-CS-Fixer.
- PHPStan at level 8+ or Psalm at level 3+. Must pass with zero errors.
- Use Composer for all dependency management. No manual require of vendor files.
- PSR-4 autoloading only. No require_once in application code.
VIOLATIONS:
- PSR-12 violation = LOW
- PHPStan or Psalm error present = MEDIUM
- require_once in application code = MEDIUM

### PHP-6 — Testing
RULES:
- Use PHPUnit at the version matching the project PHP support matrix.
- Use Mockery or PHPUnit mocks for dependencies.
- Minimum 80% coverage for service and domain layer.
- Use database transactions in integration tests and roll back after each test.
VIOLATIONS:
- Service or domain layer below 80% coverage = MEDIUM
- Integration test that does not roll back database state = MEDIUM

---

## SECTION 4 — JAVA STANDARDS

Applies to files ending in: .java

### JAVA-1 — Language Version and Modern Usage
RULES:
- Java 21 LTS is the minimum version for all new code.
- Use record types for immutable data carriers (DTOs, value objects).
- Use sealed classes and interfaces to model closed domain hierarchies.
- Use var for local type inference where the type is obvious from the right-hand side. Do not use var when it reduces readability.
- Use pattern matching for instanceof (Java 16+). No old-style cast after instanceof check.
- Use text blocks for multi-line SQL, JSON, or HTML strings.
VIOLATIONS:
- Old-style cast after instanceof check = LOW
- Mutable class used as DTO where record would be appropriate = LOW
- var used where type is not obvious from right-hand side = LOW

### JAVA-2 — Error and Exception Handling
RULES:
- Prefer unchecked exceptions (RuntimeException subclasses) for programming errors. Checked exceptions for genuinely recoverable conditions only.
- Never swallow exceptions with an empty catch block. At minimum log the exception.
- Always preserve the original cause: throw new ServiceException("context", originalException).
- Use Optional<T> for return values that may be absent. Never return null from a public method.
- Do not use exceptions for control flow.
VIOLATIONS:
- Empty catch block = HIGH
- Exception thrown without preserving original cause = MEDIUM
- null returned from a public method = MEDIUM
- Exception used for non-exceptional control flow = MEDIUM
- Optional not used where null is a valid absent-value scenario = LOW

### JAVA-3 — Security
RULES:
- SQL via Spring Data JPA with named params, or JdbcTemplate with ? placeholders only. String-concatenated JPQL or SQL = CRITICAL.
- Use @Valid or @Validated on all controller method parameters and request body DTOs.
- Encode all output in HTML templates. Use Thymeleaf auto-escaping or equivalent.
- Secrets via Spring Cloud Config with Vault or environment variables. No real credentials in application.properties.
- Enable Spring Security CSRF protection for all stateful endpoints.
- Never expose stack traces in HTTP error responses. Use @ControllerAdvice with a safe error response DTO.
VIOLATIONS:
- String-concatenated SQL or JPQL = CRITICAL
- No @Valid on request body DTO in controller = HIGH
- Real credentials in application.properties = CRITICAL
- Stack trace returned in HTTP response = HIGH
- CSRF disabled for stateful endpoints = HIGH

### JAVA-4 — Architecture
RULES:
- Strict layered architecture: Controller to Service to Repository. No @Repository or @Entity in @Controller classes.
- Constructor injection only. No @Autowired field injection. Field injection prevents testing without a Spring context.
- DTOs for API surface. Never expose @Entity objects directly in API responses.
- @Transactional at the service layer only. Never on the controller layer.
- Use ApplicationEventPublisher for cross-domain communication. No direct service-to-service calls across domain boundaries.
VIOLATIONS:
- @Entity exposed directly in API response = HIGH
- @Autowired field injection used = MEDIUM
- @Transactional on controller method = MEDIUM
- @Repository or @Entity imported in @Controller = MEDIUM
- Direct service-to-service call across domain boundary = MEDIUM

### JAVA-5 — Style and Tooling
RULES:
- Follow Google Java Style Guide enforced by google-java-format or Checkstyle.
- All code MUST pass SpotBugs with zero HIGH or CRITICAL findings.
- Use PMD for code quality. Cognitive complexity max 15.
- SonarQube quality gate MUST be green before merge.
- Declare fields final wherever possible.
- Use List.of(), Map.of(), Set.of() for unmodifiable collections.
VIOLATIONS:
- SpotBugs HIGH or CRITICAL finding = HIGH
- SonarQube quality gate red = HIGH
- Mutable collection used where List.of() or equivalent would apply = LOW
- Non-final field where final is possible = LOW

### JAVA-6 — Concurrency
RULES:
- Prefer CompletableFuture, ExecutorService, or reactive streams (Project Reactor, RxJava) over raw Thread.
- Never use Thread.sleep() in production code for timing logic. Use ScheduledExecutorService.
- All shared mutable state MUST be protected by synchronization or redesigned to be immutable.
- Prefer java.util.concurrent collections (ConcurrentHashMap, CopyOnWriteArrayList) over manually synchronized collections.
VIOLATIONS:
- Raw Thread used instead of ExecutorService or CompletableFuture = MEDIUM
- Thread.sleep() in production timing logic = MEDIUM
- Shared mutable state without synchronization = CRITICAL

### JAVA-7 — Testing
RULES:
- Use JUnit 5 with AssertJ for assertions. No JUnit 4 in new code.
- Use Mockito with @ExtendWith(MockitoExtension.class) for mocking.
- Use @SpringBootTest sparingly. Prefer @WebMvcTest or @DataJpaTest for layer-specific tests.
- Use Testcontainers for tests requiring a real database or message broker.
- Coverage targets: 85% line coverage for service layer, 80% overall.
VIOLATIONS:
- JUnit 4 used in new code = MEDIUM
- @SpringBootTest used where @WebMvcTest or @DataJpaTest would suffice = LOW
- Service layer below 85% coverage = MEDIUM
- Real database or broker tested without Testcontainers = MEDIUM

---

## SECTION 5 — SQL STANDARDS

Applies to: .sql files, inline SQL in any language file, ORM query definitions, migration files.

### SQL-1 — Safety and Injection Prevention
RULES:
- Parameterized queries or prepared statements in ALL application code. No exceptions.
- No dynamic SQL constructed from user input in stored procedures.
- Application DB user MUST NOT have DROP, CREATE, ALTER, TRUNCATE, or GRANT privileges.
- Use a separate migration user with elevated privileges, run only during deployments.
VIOLATIONS:
- String-concatenated SQL in any form = CRITICAL
- Application user with ALTER or DROP privilege = HIGH
- Dynamic SQL from user input in stored procedure = CRITICAL

### SQL-2 — Schema Design
RULES:
- All tables MUST have a primary key.
- Use NOT NULL as the default. Allow NULL only when absence is semantically meaningful and the column is documented as nullable.
- Use TIMESTAMPTZ or equivalent timezone-aware type for all timestamps. Never store timestamps in local time.
- Soft deletes MUST use deleted_at TIMESTAMPTZ NULL, not a boolean is_deleted flag.
- Foreign key constraints MUST be defined for all relational links.
- All migration files MUST be reversible with both up and down directions.
VIOLATIONS:
- Table without a primary key = HIGH
- Timestamp stored without timezone = MEDIUM
- Soft delete implemented as boolean flag = LOW
- Missing foreign key constraint = MEDIUM
- Migration without a down direction = MEDIUM

### SQL-3 — Performance
RULES:
- All columns used in WHERE, JOIN ON, or ORDER BY in high-traffic queries MUST be indexed.
- Avoid SELECT * in application queries. Select only required columns.
- N+1 query patterns = HIGH violation. Use JOINs or batch loading.
- Queries touching more than 10,000 rows MUST use pagination via LIMIT/OFFSET or cursor-based approach.
- EXPLAIN ANALYZE output MUST be reviewed for new queries on large tables.
VIOLATIONS:
- SELECT * in application query = MEDIUM
- Unindexed column in WHERE or JOIN of a high-traffic query = HIGH
- N+1 query pattern = HIGH
- Unbounded query on large table with no pagination = HIGH

### SQL-4 — Naming Conventions
RULES:
- Table names: snake_case, plural noun. Example: payment_transactions
- Column names: snake_case. Example: created_at, account_id
- Index names: idx_{table}_{columns}. Example: idx_payments_user_id
- Foreign key constraint names: fk_{table}_{referenced_table}
- Primary key column: always named id unless a natural key is explicitly justified with a comment
VIOLATIONS:
- Table name not snake_case or not plural = LOW
- Index name not following idx_ convention = LOW
- Foreign key constraint unnamed = LOW

---

## SECTION 6 — SEVERITY TABLE AND STANDARDS_SCORE RUBRIC

### Severity Definitions

CRITICAL — Security vulnerability, data loss risk, or production crash risk. Action: Block merge immediately.
HIGH — Significant reliability, security posture, or standards compliance risk. Action: Block merge. Requires fix before approval.
MEDIUM — Meaningful deviation from standards with maintainability or correctness risk. Action: Must be fixed within the current sprint.
LOW — Style, readability, or minor advisory issue. Action: Add to backlog.
INFO — Observation or suggestion with no compliance impact. Action: Optional.

### STANDARDS_SCORE Rubric

The STANDARDS_SCORE is an integer from 1 to 10. Assign it after all findings are listed.

SCORE 10 — Perfect compliance. Zero violations across all applicable sections.
SCORE 9 — Excellent. Only 1 or 2 LOW or INFO findings. No MEDIUM, HIGH, or CRITICAL.
SCORE 8 — Good. A small number of LOW or MEDIUM findings. No HIGH or CRITICAL.
SCORE 7 — Acceptable. Multiple MEDIUM findings OR exactly 1 HIGH finding.
SCORE 6 — Below standard. Multiple HIGH findings OR pervasive MEDIUM issues throughout the diff.
SCORE 5 — Poor. Exactly 1 CRITICAL finding OR many HIGH findings.
SCORE 4 — Failing. Multiple CRITICAL findings.
SCORE 1 to 3 — Unacceptable. Severe security violations, data exposure risk, or systemic non-compliance. Immediate escalation required.

### STANDARDS_SCORE Output Format

After all findings, output the score block in exactly this format:

STANDARDS_SCORE: {score}/10
SCORE_RATIONALE: {one sentence explaining the primary reason for this score}
MERGE_RECOMMENDATION: {APPROVE | APPROVE_WITH_COMMENTS | REQUEST_CHANGES | BLOCK}

---

*Standards Version: 2.1 | Last Reviewed: March 2026*
*Owner: Engineering Standards Committee*
*Amendments: Raise a PR against scripts/my_coding_standards.md*