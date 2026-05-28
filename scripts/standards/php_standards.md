# PHP CODING STANDARDS
# Version: 2.1 | Language: PHP 8.2+ | Framework: Laravel / Symfony
# Injected via CODING_STANDARDS_PLACEHOLDER into engine/prompt.txt
# This section is evaluated by the AI reviewer for all .php files

---

## AI AGENT INSTRUCTION — PHP SECTION

You are reviewing PHP source code written for Laravel or Symfony on PHP 8.2+. For every .php file in the diff you MUST:

STEP 1 — Read every rule in this document before producing any finding.
STEP 2 — Check each rule against the code under review. Do not skip sections.
STEP 3 — For every violation produce a finding in this exact format:

FINDING:
  RULE: {rule ID, e.g. PHP-1.1}
  SEVERITY: {CRITICAL | HIGH | MEDIUM | LOW | INFO}
  FILE: {filename}
  LINE: {line number or range if available}
  VIOLATION: {what the code does that breaks the rule}
  REQUIRED FIX: {what the code must do instead}

STEP 4 — After all findings, output the STANDARDS_SCORE block defined at the end of this document.
STEP 5 — Never suppress a finding because the code appears to work. Compliance and correctness are independent concerns.

---

## SECTION PHP-1 — LANGUAGE REQUIREMENTS

### PHP-1.1 — Strict Types Declaration

RULE: Every PHP file MUST begin with the opening tag followed immediately by declare(strict_types=1). This declaration MUST appear before any other code including namespace declarations, use statements, and class definitions. Files missing this declaration will not enforce type coercion rules and are a violation.

REQUIRED FILE OPENING:
<?php

declare(strict_types=1);

VIOLATIONS:
- declare(strict_types=1) absent from a PHP file = MEDIUM
- declare(strict_types=1) present but not immediately after the opening tag = MEDIUM
- Short open tag used (<?=) without strict types declaration = MEDIUM

### PHP-1.2 — PHP Version Baseline

RULE: PHP 8.2 is the minimum supported version for all new code. Modern PHP 8.2+ features including readonly properties, fibers, enum types, intersection types, and first-class callable syntax are available and preferred over older workarounds.

VIOLATIONS:
- Code using workarounds for features available natively in PHP 8.2+ = LOW
- Deprecated PHP 8.1 or earlier functions used where a modern alternative exists = MEDIUM

### PHP-1.3 — Type Declarations Required

RULE: All function and method parameters MUST have type declarations. All functions and methods MUST have a return type declaration. This applies to all visibility levels: public, protected, and private. The mixed type is PROHIBITED unless the function is interacting with a legacy API that cannot be typed, in which case an inline comment explaining the reason and a linked ticket are required.

VIOLATION PATTERN:
function processPayment($amount, $currency) {
    // ...
}

CORRECT PATTERN:
function processPayment(int $amount, string $currency): PaymentResult
{
    // ...
}

VIOLATIONS:
- Function parameter without a type declaration = MEDIUM
- Function or method without a return type declaration = MEDIUM
- mixed type used without an explanatory comment and linked ticket = MEDIUM
- void return type omitted from a function that explicitly returns nothing = LOW

### PHP-1.4 — Readonly Properties for Value Objects

RULE: Properties of DTOs, value objects, and request objects MUST be declared readonly where the value is assigned once in the constructor and never reassigned. Use PHP 8.1+ readonly property syntax. Do not use a private property with only a getter method when readonly achieves the same result.

VIOLATIONS:
- DTO or value object property not declared readonly when the value is never reassigned after construction = LOW
- Private property with manual getter where readonly would apply = LOW

### PHP-1.5 — No mixed Type Without Justification

RULE: The mixed type MUST NOT be used unless the code must interact with a legacy or external API where the type cannot be narrowed. Every use of mixed requires an inline comment with a justification and a ticket reference for future remediation.

VIOLATIONS:
- mixed parameter or return type with no inline comment = MEDIUM
- mixed used for a new function where a specific type or union type would apply = MEDIUM

---

## SECTION PHP-2 — ERROR AND EXCEPTION HANDLING

### PHP-2.1 — No Silent Exception Swallowing

RULE: Empty catch blocks are PROHIBITED. Every caught exception MUST be either logged with sufficient context for diagnosis and rethrown as a typed domain exception with the original as the previous argument, or handled with a documented and intentional decision. A catch block containing only a comment with no action is also a violation.

VIOLATION PATTERN:
try {
    $this->store->save($payment);
} catch (\Exception $e) {
    // nothing
}

CORRECT PATTERN:
try {
    $this->store->save($payment);
} catch (DatabaseException $e) {
    $this->logger->error('Failed to save payment', [
        'payment_id' => $payment->id,
        'error'      => $e->getMessage(),
    ]);
    throw new PaymentPersistenceException(
        message: 'Payment could not be saved',
        previous: $e
    );
}

VIOLATIONS:
- Empty catch block = HIGH
- Catch block with only a comment and no action = HIGH
- Exception caught and a new exception thrown without passing the original as previous = MEDIUM
- Exception logged without including the exception object or message in the context array = MEDIUM

### PHP-2.2 — Catch Specific Exception Types

RULE: catch (\Exception $e) and catch (\Throwable $e) are PROHIBITED except at the application boundary top-level handler. All other catch blocks MUST catch the most specific exception type applicable to the operation being performed.

VIOLATIONS:
- catch (\Exception $e) used outside the application boundary handler = MEDIUM
- catch (\Throwable $e) used outside the application boundary handler = MEDIUM
- Catch block that could be narrowed to a more specific exception type = LOW

### PHP-2.3 — Typed Exception Hierarchy

RULE: All application exceptions MUST extend either \RuntimeException for runtime errors that are not programming bugs, or \LogicException for errors that represent incorrect usage of an API or programming mistakes. Never throw the base \Exception class directly. Build a domain-specific exception hierarchy grouped by layer.

REQUIRED HIERARCHY:
Domain exceptions:
class PaymentException extends \RuntimeException
class InsufficientFundsException extends PaymentException
class PaymentNotFoundException extends PaymentException

Infrastructure exceptions:
class DatabaseException extends \RuntimeException

VIOLATIONS:
- throw new \Exception('message') used in application code = MEDIUM
- Exception class not extending RuntimeException or LogicException = MEDIUM
- Domain and infrastructure exceptions not separated into distinct hierarchies = LOW

### PHP-2.4 — Error Reporting Configuration

RULE: Production PHP configuration MUST set error_reporting to E_ALL and display_errors to Off. Errors MUST go to the server log only and MUST NEVER be displayed to the browser or included in API responses.

VIOLATIONS:
- display_errors set to On in production configuration = HIGH
- PHP errors rendered in HTTP response body = HIGH
- error_reporting set to a value that suppresses E_NOTICE or E_WARNING = MEDIUM

---

## SECTION PHP-3 — SECURITY

### PHP-3.1 — SQL Parameterized Queries Only

RULE: All SQL queries MUST use PDO prepared statements with named or positional placeholders. String concatenation or interpolation to build a SQL query is a CRITICAL violation regardless of whether the interpolated value comes from user input. mysqli_query with a concatenated string is also a CRITICAL violation.

VIOLATION PATTERN:
$result = $pdo->query(
    "SELECT * FROM accounts WHERE email = '$email'"
);

CORRECT PATTERN:
$stmt = $pdo->prepare(
    'SELECT id, email, status FROM accounts WHERE email = :email'
);
$stmt->execute(['email' => $email]);
$result = $stmt->fetch(PDO::FETCH_ASSOC);

VIOLATIONS:
- SQL query built with string concatenation = CRITICAL
- SQL query built with variable interpolation inside a double-quoted string = CRITICAL
- mysqli_query called with a concatenated SQL string = CRITICAL
- PDO::query() called with a SQL string containing any variable = CRITICAL

### PHP-3.2 — Password Hashing

RULE: All passwords MUST be hashed using password_hash() with PASSWORD_ARGON2ID as the preferred algorithm or PASSWORD_BCRYPT as an acceptable alternative. MD5, SHA1, SHA256, and all other non-purpose-built hashing functions are PROHIBITED for password storage.

VIOLATION PATTERN:
$hash = md5($password);
$hash = sha1($password);

CORRECT PATTERN:
$hash = password_hash($password, PASSWORD_ARGON2ID);

if (!password_verify($inputPassword, $storedHash)) {
    throw new AuthenticationException('Invalid credentials');
}

VIOLATIONS:
- md5() used for password hashing = CRITICAL
- sha1() used for password hashing = CRITICAL
- sha256() or any non-password-specific hash function used for passwords = CRITICAL
- password_hash() used without PASSWORD_BCRYPT or PASSWORD_ARGON2ID algorithm = HIGH
- password_verify() not used for verification, replaced with direct hash comparison = HIGH

### PHP-3.3 — Output Escaping

RULE: All user-supplied or database-sourced data rendered into HTML templates MUST be escaped using htmlspecialchars() with ENT_QUOTES and UTF-8 encoding. Use Twig or Blade templating engines with auto-escaping enabled as the preferred approach. Explicit | raw opt-out in Twig is only permitted for trusted, internally generated HTML content.

CORRECT PATTERNS:
In raw PHP templates:
echo htmlspecialchars($userInput, ENT_QUOTES, 'UTF-8');

In Twig with auto-escaping:
{{ user.name }}
{{ user.html | raw }}  — only for trusted internal content

VIOLATIONS:
- User-supplied data echoed in a template without htmlspecialchars() = HIGH
- Twig or Blade auto-escaping disabled globally = HIGH
- | raw used in Twig on user-supplied or database-sourced content = HIGH
- echo or print used with an unescaped variable in a PHP template = HIGH

### PHP-3.4 — File Upload Validation

RULE: All file uploads MUST be validated using the finfo extension to detect the actual MIME type from the file content. The client-supplied Content-Type header MUST NOT be trusted for file type validation. Files MUST be stored outside the webroot. Filenames MUST be generated server-side using a UUID or equivalent. The original client filename MUST NOT be used as the storage filename.

CORRECT PATTERN:
$finfo = new \finfo(FILEINFO_MIME_TYPE);
$mimeType = $finfo->file($_FILES['document']['tmp_name']);

$allowedMimes = ['application/pdf', 'image/jpeg', 'image/png'];
if (!in_array($mimeType, $allowedMimes, strict: true)) {
    throw new ValidationException('File type not permitted');
}

$destination = storage_path('uploads/' . Str::uuid() . '.pdf');

VIOLATIONS:
- File MIME type validated using the client-supplied Content-Type header = HIGH
- Uploaded file stored inside the webroot directory = HIGH
- Client-supplied filename used as the storage filename = HIGH
- File extension validated without also validating MIME type from content = HIGH
- in_array used for MIME type check without strict: true = MEDIUM

### PHP-3.5 — Prohibited Functions

RULE: The following functions are PROHIBITED in all application code. Their presence is a violation of the stated severity regardless of context.

PROHIBITED FUNCTION LIST:
- eval(): CRITICAL. Allows arbitrary code execution. No alternative exists; the design must be changed.
- unserialize() on untrusted data: CRITICAL. Allows object injection. Use json_decode() instead.
- md5() for passwords: CRITICAL. Cryptographically broken. Use password_hash().
- sha1() for passwords: CRITICAL. Cryptographically broken. Use password_hash().
- shell_exec(): HIGH. Shell injection risk. Use proc_open() with an explicit args array.
- exec() with user input: CRITICAL. Shell injection. Use proc_open() with args array.
- system() with user input: CRITICAL. Shell injection. Use proc_open() with args array.
- passthru() with user input: CRITICAL. Shell injection. Use proc_open() with args array.

VIOLATIONS:
- eval() present anywhere in application code = CRITICAL
- unserialize() called on any value that originates from user input, a database, or an external API = CRITICAL
- shell_exec() present in application code = HIGH
- exec(), system(), or passthru() called with any string containing a variable = CRITICAL

### PHP-3.6 — CSRF Protection

RULE: CSRF protection MUST be implemented on all state-changing HTTP requests (POST, PUT, PATCH, DELETE). In Laravel this is enforced by the VerifyCsrfToken middleware. In Symfony use the CSRF token component. Stateless API endpoints using token-based authentication MAY disable CSRF but MUST document the justification with an inline comment.

VIOLATIONS:
- State-changing endpoint with CSRF protection disabled and no justification comment = HIGH
- CSRF middleware excluded for a route group containing stateful session-based endpoints = HIGH

---

## SECTION PHP-4 — ARCHITECTURE (LARAVEL AND SYMFONY)

### PHP-4.1 — Layer Responsibilities

RULE: The application MUST follow a strict four-layer architecture. Each layer has a defined and exclusive responsibility. No layer may perform the responsibilities of another layer.

REQUIRED LAYER DEFINITIONS:
Controller — Receives the HTTP request, delegates validation to a FormRequest (Laravel) or DTO validator (Symfony), delegates business logic to a Service, returns an HTTP response. No business logic. No direct database calls.
Service — Orchestrates business logic. Uses Repository interfaces for data access. Fires domain events. No HTTP concerns.
Repository — Data access only. Returns domain objects or collections. No business logic. No HTTP concerns.
FormRequest or DTO Validator — Input validation and authorization rules. All validation logic defined here. Not in the controller or service.

VIOLATIONS:
- Business logic (conditional rules, calculations) present in a controller method = MEDIUM
- Direct ORM call (Payment::create(), Payment::find()) inside a controller = MEDIUM
- Direct database call inside a controller = MEDIUM
- Notification or email sending inside a controller = MEDIUM
- Validation rules defined inside a controller instead of a FormRequest = MEDIUM
- Business logic present in a repository method = MEDIUM

### PHP-4.2 — Controller Pattern

RULE: Controller methods MUST be thin. A controller method MUST only: receive the request via a typed FormRequest or validated DTO, call one service method, and return a typed HTTP response. Any logic beyond these three actions is a violation.

VIOLATION PATTERN:
class PaymentController extends Controller
{
    public function store(Request $request): JsonResponse
    {
        $amount = $request->input('amount');
        if ($amount <= 0) { ... }
        $payment = Payment::create([...]);
        Mail::to($user)->send(...);
        return response()->json($payment);
    }
}

CORRECT PATTERN:
class PaymentController extends Controller
{
    public function store(
        CreatePaymentRequest $request,
        PaymentService $service,
    ): JsonResponse {
        $result = $service->create($request->toDto());
        return response()->json(PaymentResource::make($result), 201);
    }
}

VIOLATIONS:
- Controller method receiving a plain Request instead of a typed FormRequest = MEDIUM
- Controller method containing if/else business logic = MEDIUM
- Controller method calling more than one service method for a single action = MEDIUM
- Controller returning an Eloquent model directly instead of a Resource = MEDIUM
- Controller method body longer than receiving, delegating, and returning = MEDIUM

### PHP-4.3 — Dependency Injection

RULE: All service dependencies MUST be injected via constructor using typed interface parameters. Creating a dependency with new ClassName() inside a service, repository, or controller method is PROHIBITED for any injected dependency. Bind concrete implementations to interfaces in the service container.

VIOLATION PATTERN:
class PaymentService
{
    public function process(PaymentDto $dto): Payment
    {
        $repo = new PaymentRepository();
        $repo->save(...);
    }
}

CORRECT PATTERN:
class PaymentService
{
    public function __construct(
        private readonly PaymentRepositoryInterface $payments,
        private readonly NotifierInterface $notifier,
        private readonly LoggerInterface $logger,
    ) {}
}

VIOLATIONS:
- new ClassName() used inside a service or controller to create an injectable dependency = MEDIUM
- Dependency not typed to an interface in the constructor = LOW
- Constructor parameter not declared readonly where the value is never reassigned = LOW

### PHP-4.4 — Database Migrations

RULE: All database schema changes MUST be implemented via versioned migration files. Running ALTER TABLE, CREATE TABLE, or DROP TABLE directly against a production or staging database without a migration is PROHIBITED.

VIOLATIONS:
- Schema change present in a deployment script instead of a migration file = HIGH
- Migration file missing a down() method = MEDIUM
- Migration that cannot be reversed without data loss and no documented justification = MEDIUM

---

## SECTION PHP-5 — STYLE AND TOOLING

### PHP-5.1 — PSR-12 Code Style

RULE: All PHP code MUST conform to the PSR-12 extended coding style standard. This is enforced by PHP-CS-Fixer or PHP_CodeSniffer with the PSR-12 standard. Unformatted code that does not pass the style check is a violation.

VIOLATIONS:
- Code not conforming to PSR-12 style = LOW
- Inconsistent brace placement, indentation, or blank line usage = LOW

### PHP-5.2 — Static Analysis

RULE: All code MUST pass PHPStan at level 8 or higher, or Psalm at level 3 or lower (Psalm levels are inverted). Zero errors are permitted. Static analysis MUST be run in CI as a required gate before merge.

REQUIRED COMMANDS:
./vendor/bin/phpcs --standard=PSR12 src/
./vendor/bin/phpstan analyse src/ --level=8
./vendor/bin/phpunit --coverage-min=80
composer audit

VIOLATIONS:
- PHPStan level 8 error present = MEDIUM
- Psalm level 3 error present = MEDIUM
- Static analysis not configured in CI = HIGH
- composer audit finding a HIGH or CRITICAL CVE in a direct dependency = HIGH
- composer audit finding a CRITICAL CVE in a direct dependency = CRITICAL

### PHP-5.3 — Autoloading and Dependency Management

RULE: All classes MUST be autoloaded via PSR-4 autoloading configured in composer.json. require_once or require used in application code is PROHIBITED. All dependencies MUST be managed via Composer. Manual inclusion of vendor files is PROHIBITED.

VIOLATIONS:
- require_once present in application code = MEDIUM
- require used to include a vendor or class file = MEDIUM
- Class not following PSR-4 namespace to directory mapping = MEDIUM

---

## SECTION PHP-6 — TESTING

### PHP-6.1 — Test Framework and Naming

RULE: PHPUnit is the required test framework. All test class names MUST end with Test. Test method names MUST follow the it_describes_the_scenario_and_expected_outcome pattern and MUST be annotated with @test. The name MUST be readable as a plain English sentence describing the behaviour being verified.

CORRECT PATTERN:
class PaymentServiceTest extends TestCase
{
    /** @test */
    public function it_throws_insufficient_funds_exception_when_balance_is_zero(): void
    { ... }

    /** @test */
    public function it_sends_confirmation_notification_after_successful_payment(): void
    { ... }
}

VIOLATIONS:
- Test method name does not describe the scenario = LOW
- Test method name does not describe the expected outcome = LOW
- @test annotation absent from a test method = LOW
- Test class name does not end with Test = LOW
- Test method name uses camelCase instead of snake_case = LOW

### PHP-6.2 — Unit Test Isolation

RULE: Unit tests MUST NOT hit the database, make real HTTP calls, or interact with the file system. All repository interfaces and external service interfaces MUST be mocked using Mockery or PHPUnit mocks. No concrete repository or service implementation that performs I/O may be used in a unit test.

VIOLATIONS:
- Unit test executing a real database query = MEDIUM
- Unit test making a real HTTP request = HIGH
- Concrete repository class used in a unit test without mocking = MEDIUM
- Mock not reset between test cases causing state leakage = MEDIUM

### PHP-6.3 — Integration Test Database Isolation

RULE: Integration tests that interact with a real database MUST use database transactions that are rolled back after each test. In Laravel use the RefreshDatabase or DatabaseTransactions trait. In Symfony use a transaction-based test setup. No integration test may leave data in the database after it completes.

VIOLATIONS:
- Integration test that modifies the database without rolling back changes = MEDIUM
- RefreshDatabase or DatabaseTransactions trait absent from an integration test class = MEDIUM
- Integration test relying on database state left by a previous test = HIGH

### PHP-6.4 — Test Data Factories

RULE: All test data MUST be created using model factories or builder patterns. Hardcoded entity creation with raw arrays or direct model constructors in test setup is PROHIBITED. Factories ensure consistency and make tests resilient to schema changes.

VIOLATIONS:
- Test data created with hardcoded raw array instead of a factory = LOW
- Direct model constructor called in test setup instead of a factory = LOW
- Factory not used for related model data (relationships created manually) = LOW

### PHP-6.5 — Coverage Targets

RULE: The following minimum coverage targets MUST be met and enforced in CI. Coverage is measured by line coverage.

REQUIRED TARGETS:
- Service and domain layer: 80% line coverage
- Controller layer: 75% line coverage
- Repository layer: 75% line coverage backed by integration tests

VIOLATIONS:
- Service or domain layer below 80% coverage = MEDIUM
- New business logic added with no corresponding tests = HIGH
- Test present but covering only the happy path with no error path coverage = MEDIUM

---

## SECTION PHP-7 — SEVERITY TABLE

CRITICAL — Security vulnerability including SQL injection, eval usage, shell injection, broken password hashing, or data loss risk. Action: Block merge immediately.
HIGH — Significant reliability, security posture, or correctness risk including empty catch blocks, missing CSRF protection, or static analysis gate failure. Action: Block merge. Fix required before approval.
MEDIUM — Meaningful deviation from standards with maintainability or correctness risk including missing type declarations, silent exception handling, or layer violations. Action: Fix within current sprint.
LOW — Style, readability, or minor advisory issue including PSR-12 violations, missing readonly, or test naming. Action: Add to backlog.
INFO — Observation or suggestion with no compliance impact. Action: Optional.

---

## SECTION PHP-8 — STANDARDS_SCORE RUBRIC

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

*Standards Version: 2.1 | Language: PHP 8.2+ | Framework: Laravel / Symfony | Last Reviewed: March 2026*
*Owner: Engineering Standards Committee*
*Amendments: Raise a PR against scripts/standards/php_standards.md*