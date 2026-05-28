# NODE.JS AND TYPESCRIPT CODING STANDARDS
# Version: 2.1 | Language: Node.js 20 LTS+ | TypeScript 5.x
# Injected via CODING_STANDARDS_PLACEHOLDER into engine/prompt.txt
# This section is evaluated by the AI reviewer for all .js .ts .mjs .cjs files

---

## AI AGENT INSTRUCTION — NODE.JS AND TYPESCRIPT SECTION

You are reviewing Node.js and TypeScript source code. For every .js, .ts, .mjs, and .cjs file in the diff you MUST:

STEP 1 — Read every rule in this document before producing any finding.
STEP 2 — Check each rule against the code under review. Do not skip sections.
STEP 3 — For every violation produce a finding in this exact format:

FINDING:
  RULE: {rule ID, e.g. NODE-1.1}
  SEVERITY: {CRITICAL | HIGH | MEDIUM | LOW | INFO}
  FILE: {filename}
  LINE: {line number or range if available}
  VIOLATION: {what the code does that breaks the rule}
  REQUIRED FIX: {what the code must do instead}

STEP 4 — After all findings, output the STANDARDS_SCORE block defined at the end of this document.
STEP 5 — Never suppress a finding because the code appears to work. Compliance and correctness are independent concerns.

---

## SECTION NODE-1 — TYPE SAFETY

### NODE-1.1 — TypeScript Is Required

RULE: TypeScript is REQUIRED for all new Node.js service code. Plain JavaScript files in the service layer are a violation for new code. The tsconfig.json MUST exist and MUST have strict set to true. This enables all strict type checks including strictNullChecks, noImplicitAny, strictFunctionTypes, and strictPropertyInitialization.

VIOLATIONS:
- New service code written in plain JavaScript instead of TypeScript = MEDIUM
- tsconfig.json absent from the project = HIGH
- strict not set to true in tsconfig.json = HIGH
- strictNullChecks explicitly set to false overriding strict = HIGH

### NODE-1.2 — No any Type

RULE: The any type is PROHIBITED in all TypeScript service code. When the type of a value is genuinely unknown at the point of receipt (e.g., parsed JSON, external API response, user input), use unknown and narrow it explicitly to a typed representation before use. Every use of unknown must be narrowed before the value is passed further into the application.

VIOLATION PATTERN:
function processPayment(data: any) { ... }

CORRECT PATTERN:
function processPayment(data: unknown): PaymentResult {
    const input = parsePaymentInput(data);
    ...
}

VIOLATIONS:
- any used as a parameter type = MEDIUM
- any used as a return type = MEDIUM
- any used as a variable or field type = MEDIUM
- unknown used but not narrowed before further use = MEDIUM
- Type assertion as any used to bypass type checking = HIGH

### NODE-1.3 — No Type Suppression Without Justification

RULE: @ts-ignore and @ts-expect-error MUST NOT be used without an inline comment explaining the specific reason the suppression is needed and a linked ticket reference for resolution. Suppression directives without this documentation are a violation.

VIOLATIONS:
- @ts-ignore present with no comment = MEDIUM
- @ts-expect-error present with no comment = MEDIUM
- @ts-ignore present with a comment but no linked ticket = LOW
- @ts-ignore used to suppress a type error that could be fixed with a proper type = MEDIUM

### NODE-1.4 — Variable Declaration

RULE: const MUST be used by default for all variable declarations. let is permitted only when the variable is explicitly reassigned after its initial declaration. var is PROHIBITED in all new TypeScript and JavaScript code.

VIOLATIONS:
- var used in any new code = LOW
- let used for a variable that is never reassigned = LOW

---

## SECTION NODE-2 — ASYNC AND ERROR HANDLING

### NODE-2.1 — All Promises Must Be Handled

RULE: Every async function call MUST be awaited or have its returned Promise explicitly handled via .catch() or a .then().catch() chain. A floating Promise that is neither awaited nor caught is a CRITICAL violation because it silently swallows errors and unpredictably affects application state.

VIOLATION PATTERN:
fetchPayment(id).then(process);

async function createRefund(id: string) {
    refundService.process(id);
}

CORRECT PATTERN:
async function createRefund(id: string): Promise<RefundResult> {
    try {
        const result = await refundService.process(id);
        return result;
    } catch (error) {
        throw new RefundProcessingError('Refund failed', { cause: error });
    }
}

VIOLATIONS:
- Promise returned from an async call not awaited and not chained with .catch() = CRITICAL
- async function called without await and the return value not stored or handled = CRITICAL
- .then() used with no corresponding .catch() = HIGH

### NODE-2.2 — Global Unhandled Rejection Handler

RULE: Every application entry point MUST attach a process.on('unhandledRejection') handler before any async code runs. This handler MUST log the reason and promise with full detail using the structured logger and MUST call process.exit(1) to prevent the process from continuing in an undefined state.

CORRECT PATTERN:
process.on('unhandledRejection', (reason, promise) => {
    logger.error({ reason, promise }, 'Unhandled promise rejection');
    process.exit(1);
});

VIOLATIONS:
- No unhandledRejection handler at the application entry point = HIGH
- unhandledRejection handler present but does not call process.exit(1) = MEDIUM
- unhandledRejection handler present but uses console instead of structured logger = MEDIUM

### NODE-2.3 — Throw Error Objects Only

RULE: throw MUST always be used with an Error object or a custom class that extends Error. Throwing a raw string, number, plain object, or null is PROHIBITED. When wrapping a caught error, pass the original as the cause option to preserve the full error chain.

VIOLATION PATTERN:
throw 'Refund failed';
throw { message: 'Not found' };

CORRECT PATTERN:
throw new RefundProcessingError('Refund failed', { cause: error });

VIOLATIONS:
- throw used with a string literal = MEDIUM
- throw used with a plain object literal = MEDIUM
- throw used with a number or null = MEDIUM
- Caught error rethrown as a new Error without preserving the original cause = MEDIUM
- Custom error class does not extend Error = MEDIUM

### NODE-2.4 — async/await Over Promise Chains

RULE: Use async/await for all asynchronous logic. Raw .then().catch() chains are discouraged for any logic involving more than one sequential async step because they reduce readability and make error propagation harder to trace. Simple single-step transforms on a resolved value are acceptable.

VIOLATIONS:
- Multi-step sequential async logic written as a .then().then() chain = LOW
- Complex error handling split across multiple .catch() callbacks where try/catch would be clearer = LOW

---

## SECTION NODE-3 — ARCHITECTURE

### NODE-3.1 — Module Structure

RULE: The source directory MUST follow a layered structure where each directory has a single defined responsibility. Files MUST be placed in the directory that matches their responsibility. No file may import from a layer above it in the dependency hierarchy.

REQUIRED DIRECTORY STRUCTURE:
src/api/           — HTTP route definitions and handler wiring only
src/services/      — Business logic and orchestration
src/repositories/  — Data access and persistence
src/domain/        — Types, interfaces, value objects, domain errors
src/middleware/    — Express or Fastify middleware functions
src/config/        — Configuration loading from environment variables

VIOLATIONS:
- Business logic present in a file under src/api/ = MEDIUM
- Database query in a file under src/services/ instead of src/repositories/ = MEDIUM
- Type definition defined in a service file instead of src/domain/ = LOW
- Config loaded from environment inside a service or repository file = MEDIUM

### NODE-3.2 — Dependency Injection via Constructor

RULE: All service, repository, and middleware classes MUST receive their dependencies via constructor parameters. Module-level singleton instantiation of stateful dependencies (database clients, HTTP clients, loggers) that cannot be overridden in tests is PROHIBITED.

VIOLATION PATTERN:
const db = new DatabaseClient(process.env.DSN);

CORRECT PATTERN:
class PaymentService {
    constructor(
        private readonly store: PaymentStore,
        private readonly notifier: NotificationSender,
        private readonly logger: Logger,
    ) {}
}

VIOLATIONS:
- Module-level instantiation of a stateful dependency that cannot be replaced in tests = MEDIUM
- Service class that creates its own dependencies internally instead of receiving them = MEDIUM
- Dependency imported and used directly from a module without injection = MEDIUM

### NODE-3.3 — Interface Naming Conventions

RULE: TypeScript interfaces used as data contracts MUST be named as nouns. Interfaces that represent a role or capability MUST be named as agent nouns. The naming must reflect the purpose of the interface without ambiguity.

CORRECT PATTERNS:
interface PaymentStore — noun, data contract for storage operations
interface NotificationSender — agent noun, capability interface

VIOLATIONS:
- Interface named with a verb (e.g., IProcessPayment) = LOW
- Interface named with the I prefix (IPaymentStore) instead of a descriptive noun = LOW
- Interface named so generically (e.g., Manager, Handler) that its purpose is unclear = LOW

### NODE-3.4 — One Responsibility Per File

RULE: Each file MUST have a single well-defined responsibility. A service file defines and exports one service class. A repository file defines and exports one repository class. A domain file defines related types and value objects for one domain entity.

VIOLATIONS:
- Multiple unrelated service classes exported from a single file = MEDIUM
- Service class and its repository class defined in the same file = MEDIUM
- Route definition and business logic mixed in the same file = MEDIUM

---

## SECTION NODE-4 — INPUT VALIDATION

### NODE-4.1 — Schema Validation Required

RULE: All external input MUST be validated against an explicit schema using Zod (preferred), Joi, or class-validator before the validated data is passed to any service. Manual field-by-field checking in handler code using if statements is PROHIBITED as the primary validation mechanism.

CORRECT PATTERN:
import { z } from 'zod';

const CreatePaymentSchema = z.object({
    amount: z.number().int().positive(),
    currency: z.enum(['USD', 'EUR', 'GBP']),
    idempotencyKey: z.string().uuid(),
});

type CreatePaymentInput = z.infer<typeof CreatePaymentSchema>;

const result = CreatePaymentSchema.safeParse(req.body);
if (!result.success) {
    return res.status(422).json({ errors: result.error.flatten() });
}
const input: CreatePaymentInput = result.data;

VIOLATIONS:
- Request body passed to a service without schema validation = HIGH
- Manual if checks used as the primary input validation strategy = HIGH
- Schema validation present but errors returned expose internal schema structure = MEDIUM
- Zod schema defined inline at the call site instead of as a named export = LOW

### NODE-4.2 — Body Size Limits

RULE: All HTTP servers MUST enforce a maximum request body size before the body is parsed. The limit MUST be configured at the middleware level, not left at the framework default.

CORRECT PATTERN:
app.use(express.json({ limit: '1mb' }));

VIOLATIONS:
- express.json() or equivalent used without a limit option = MEDIUM
- Body size limit not configured before body parsing middleware = MEDIUM

### NODE-4.3 — Rate Limiting

RULE: Rate limiting MUST be applied to all public-facing routes. Use express-rate-limit or an equivalent library. The rate limit configuration MUST define both windowMs and max.

CORRECT PATTERN:
app.use(rateLimit({ windowMs: 15 * 60 * 1000, max: 100 }));

VIOLATIONS:
- Public routes exposed with no rate limiting middleware = MEDIUM
- Rate limiting applied after route definitions instead of before = MEDIUM

---

## SECTION NODE-5 — SECURITY

### NODE-5.1 — SQL Parameterization

RULE: All SQL queries MUST use parameterized placeholders. Template literals that interpolate any variable into a SQL string are a CRITICAL violation regardless of whether that variable comes from user input. This applies to all database clients including pg, mysql2, and knex raw queries.

VIOLATION PATTERN:
const query = `SELECT * FROM users WHERE email = '${email}'`;

CORRECT PATTERN:
const result = await db.query(
    'SELECT * FROM users WHERE email = $1',
    [email]
);

VIOLATIONS:
- Template literal used to construct a SQL query with any interpolated variable = CRITICAL
- String concatenation used to build a SQL query = CRITICAL
- Knex or similar query builder bypassed with a raw query string containing interpolation = CRITICAL

### NODE-5.2 — No eval or Equivalent

RULE: eval(), the Function() constructor used with dynamic strings, and vm.runInNewContext or vm.runInThisContext with user-supplied input are PROHIBITED without exception. These constructs allow arbitrary code execution.

VIOLATIONS:
- eval() called with any argument = CRITICAL
- new Function(userInput) or new Function('...', userInput) used = CRITICAL
- vm.runInNewContext or vm.runInThisContext called with user-supplied code = CRITICAL

### NODE-5.3 — Safe Child Process Execution

RULE: child_process.exec() and child_process.execSync() MUST NOT be called with any string that includes user-supplied input because they invoke a shell and are vulnerable to shell injection. Use child_process.execFile() or child_process.spawn() with an explicit arguments array instead.

VIOLATION PATTERN:
exec(`convert ${userFile} output.pdf`);

CORRECT PATTERN:
execFile('convert', [sanitizedFile, 'output.pdf']);

VIOLATIONS:
- exec() called with a string containing any interpolated variable = CRITICAL
- execSync() called with a string containing any interpolated variable = CRITICAL
- spawn() called with shell: true and user-supplied input in the command = CRITICAL

### NODE-5.4 — Required Security Middleware

RULE: All Express and Fastify HTTP servers MUST apply the following middleware in the order listed before any route definitions. Omitting any of these from a public-facing service is a violation.

REQUIRED MIDDLEWARE ORDER:
1. helmet() — sets secure HTTP headers
2. express.json({ limit: '1mb' }) — body parsing with size limit
3. rateLimit({ windowMs: 15 * 60 * 1000, max: 100 }) — rate limiting

VIOLATIONS:
- helmet() not applied to the Express or Fastify application = MEDIUM
- Middleware applied after route definitions instead of before = MEDIUM
- Any required middleware absent from the stack = MEDIUM

### NODE-5.5 — No console in Service Code

RULE: console.log(), console.error(), console.warn(), and all other console methods MUST NOT be used in service code. Use the structured logger injected as a dependency. This is enforced by the no-console ESLint rule.

VIOLATIONS:
- console.log() present in service, repository, or middleware code = MEDIUM
- console.error() used instead of the structured logger = MEDIUM
- console present in any file outside of a one-time script or CLI tool = MEDIUM

---

## SECTION NODE-6 — PERFORMANCE

### NODE-6.1 — No Synchronous I/O in Request Handlers

RULE: Synchronous file system operations including readFileSync, writeFileSync, existsSync, and any other *Sync variant MUST NOT be used inside HTTP request handlers, service methods, or middleware. Synchronous I/O blocks the Node.js event loop and degrades throughput for all concurrent requests.

VIOLATION PATTERN:
app.get('/report', (req, res) => {
    const data = fs.readFileSync('large-report.csv');
    res.send(data);
});

CORRECT PATTERN:
app.get('/report', async (req, res) => {
    const stream = fs.createReadStream('large-report.csv');
    stream.pipe(res);
});

VIOLATIONS:
- readFileSync used in a request handler = HIGH
- writeFileSync used in a request handler = HIGH
- Any *Sync file system method used inside a handler, service, or middleware = HIGH

### NODE-6.2 — No N+1 Query Patterns

RULE: Database queries executed inside a loop that iterate over a collection are PROHIBITED. This N+1 pattern scales linearly with the collection size and will cause latency and database overload at production volumes. Use batch queries, JOIN operations, or Promise.all with a single batched call instead.

VIOLATION PATTERN:
for (const userId of userIds) {
    const user = await db.findUser(userId);
}

CORRECT PATTERN:
const users = await db.findUsersByIds(userIds);

VIOLATIONS:
- await inside a for loop that iterates over an array of IDs or entities = HIGH
- Sequential await calls for data that could be fetched in parallel = MEDIUM
- Promise.all used with per-item database calls instead of a single batched query = MEDIUM

### NODE-6.3 — Streaming for Large Data

RULE: Large datasets MUST be processed and transferred using Node.js streams. Fully buffering a large dataset into memory before sending a response is PROHIBITED. Use stream.Readable and stream.Writable or their pipeline equivalents for file downloads, report exports, and large data transformations.

VIOLATIONS:
- Entire large file read into memory before being sent as a response = MEDIUM
- Large query result set fully loaded into an array before being serialised = MEDIUM
- stream.pipeline not used where multiple stream transforms are chained = LOW

### NODE-6.4 — CPU-Intensive Work Off the Main Thread

RULE: CPU-intensive operations such as image processing, large data transformations, cryptographic operations on large inputs, and complex report generation MUST be offloaded to worker_threads. Running CPU-intensive work on the main event loop blocks all concurrent request handling.

VIOLATIONS:
- CPU-intensive operation running synchronously in the main event loop = HIGH
- Large synchronous computation inside a request handler = HIGH

---

## SECTION NODE-7 — TESTING

### NODE-7.1 — Test Framework

RULE: Use either Jest or Vitest as the test framework. Both are acceptable but MUST NOT be mixed within a single service. Once a framework is chosen for a service it must be used consistently across all test files in that service.

VIOLATIONS:
- Jest and Vitest both present as dependencies in the same service = MEDIUM
- Test framework not configured with a coverage threshold = MEDIUM

### NODE-7.2 — Test Naming

RULE: Test names MUST describe the unit under test, the scenario, and the expected outcome. Use nested describe blocks to group by unit and method. Use it() with a plain-language description of the scenario and outcome.

CORRECT PATTERN:
describe('PaymentService', () => {
    describe('refund', () => {
        it('returns error when payment is not in completed status', async () => {});
        it('updates status and sends notification when payment is valid', async () => {});
    });
});

VIOLATIONS:
- it() description does not state the expected outcome = LOW
- it() description starts with should without stating the condition = LOW
- describe() blocks not nested to reflect the unit and method under test = LOW
- Test name too generic to identify the scenario being tested = LOW

### NODE-7.3 — Mocking External Dependencies

RULE: All external dependencies including database clients, HTTP clients, file system access, and third-party SDK calls MUST be mocked in unit tests. Use jest.mock() or vi.mock() at the module level. Do not allow unit tests to make real network calls or file system writes.

VIOLATIONS:
- Unit test making a real database query = MEDIUM
- Unit test making a real HTTP request to an external service = HIGH
- File system write performed in a unit test without mocking = MEDIUM
- Mock not reset between tests causing state leakage between test cases = MEDIUM

### NODE-7.4 — HTTP Integration Testing

RULE: HTTP handler integration tests MUST use supertest or an equivalent library to make requests against the mounted application without starting a real server. Do not test HTTP handlers by calling the handler function directly.

VIOLATIONS:
- HTTP handler function called directly in tests instead of via supertest = MEDIUM
- Integration test starting a real HTTP server on a fixed port = LOW

### NODE-7.5 — Coverage Thresholds

RULE: Coverage thresholds MUST be configured in jest.config.ts or vitest.config.ts and enforced in CI. Tests that do not meet the threshold must fail the build.

REQUIRED THRESHOLDS:
branches: 80
functions: 85
lines: 85

CORRECT CONFIGURATION:
coverageThreshold: {
    global: { branches: 80, functions: 85, lines: 85 }
}

VIOLATIONS:
- Coverage thresholds not configured in the test config file = MEDIUM
- Configured thresholds below the required minimums = MEDIUM
- New business logic added with no corresponding test coverage = HIGH
- Test file present but only covering the happy path = MEDIUM

---

## SECTION NODE-8 — TOOLCHAIN

### NODE-8.1 — Required Toolchain Gates

RULE: All of the following tools MUST pass with zero blocking findings before a merge is approved. Each tool covers a distinct quality dimension and none may be skipped.

REQUIRED TOOLS AND PURPOSE:
- tsc --noEmit: full TypeScript type checking with zero errors
- eslint src/: linting with zero errors on all required rules
- jest --coverage or vitest --coverage: tests pass and coverage thresholds met
- npm audit --audit-level=high or equivalent: zero HIGH or CRITICAL CVE findings

VIOLATIONS:
- tsc --noEmit producing type errors = HIGH
- ESLint producing errors on required rules = MEDIUM
- Test suite failing = HIGH
- Coverage threshold not met = MEDIUM
- npm audit HIGH or CRITICAL finding present = HIGH
- npm audit CRITICAL finding present = CRITICAL

### NODE-8.2 — Required ESLint Rules

RULE: The following ESLint rules MUST be enabled and passing with zero errors. These rules are non-negotiable for all TypeScript service code.

REQUIRED RULES:
- @typescript-eslint/no-explicit-any: enforces no any type
- @typescript-eslint/no-floating-promises: enforces all Promises are handled
- import/order: enforces correct import grouping order
- no-console: enforces structured logger usage over console methods

VIOLATIONS:
- @typescript-eslint/no-explicit-any not enabled or suppressed = MEDIUM
- @typescript-eslint/no-floating-promises not enabled = HIGH
- import/order not enabled = LOW
- no-console not enabled = MEDIUM
- Any of the required rules set to warn instead of error = LOW

### NODE-8.3 — Import Order

RULE: Imports MUST be grouped in the following order with a blank line between each group. This is enforced by the import/order ESLint rule. Mixing import groups without separation is a violation.

REQUIRED ORDER:
1. Node.js built-in modules (node:fs, node:path, node:crypto)
2. Third-party modules from node_modules
3. Internal modules using path aliases or relative paths

VIOLATIONS:
- Internal imports mixed with third-party imports without separation = LOW
- Built-in modules not in the first group = LOW
- No blank line between import groups = LOW

---

## SECTION NODE-9 — SEVERITY TABLE

CRITICAL — Security vulnerability, unhandled rejection risk, SQL injection, eval usage, or data loss risk. Action: Block merge immediately.
HIGH — Significant reliability, correctness, security posture, or event loop blocking risk. Action: Block merge. Fix required before approval.
MEDIUM — Meaningful deviation from standards with maintainability, testability, or correctness risk. Action: Fix within current sprint.
LOW — Style, readability, or minor advisory issue. Action: Add to backlog.
INFO — Observation or suggestion with no compliance impact. Action: Optional.

---

## SECTION NODE-10 — STANDARDS_SCORE RUBRIC

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

*Standards Version: 2.1 | Language: Node.js 20 LTS+ | TypeScript 5.x | Last Reviewed: March 2026*
*Owner: Engineering Standards Committee*
*Amendments: Raise a PR against scripts/standards/node_standards.md*