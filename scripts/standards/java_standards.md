# JAVA CODING STANDARDS
# Version: 2.1 | Language: Java 21 LTS | Framework: Spring Boot 3.x
# Injected via CODING_STANDARDS_PLACEHOLDER into engine/prompt.txt
# This section is evaluated by the AI reviewer for all .java files

---

## AI AGENT INSTRUCTION — JAVA SECTION

You are reviewing Java source code written for Spring Boot 3.x on Java 21 LTS. For every .java file in the diff you MUST:

STEP 1 — Read every rule in this document before producing any finding.
STEP 2 — Check each rule against the code under review. Do not skip sections.
STEP 3 — For every violation produce a finding in this exact format:

FINDING:
  RULE: {rule ID, e.g. JAVA-1.1}
  SEVERITY: {CRITICAL | HIGH | MEDIUM | LOW | INFO}
  FILE: {filename}
  LINE: {line number or range if available}
  VIOLATION: {what the code does that breaks the rule}
  REQUIRED FIX: {what the code must do instead}

STEP 4 — After all findings, output the STANDARDS_SCORE block defined at the end of this document.
STEP 5 — Never suppress a finding because the code appears to work. Compliance and correctness are independent concerns.

---

## SECTION JAVA-1 — MODERN JAVA USAGE

### JAVA-1.1 — Language Version Baseline

RULE: Java 21 LTS is the minimum version for all new code. All Java 21 LTS language features are available and preferred over older idioms. Do not use deprecated APIs or pre-Java 16 patterns where a modern equivalent exists.

VIOLATIONS:
- Code written targeting Java 8 or Java 11 idioms where a Java 21 feature applies = LOW
- Deprecated API used without a migration comment and linked ticket = MEDIUM

### JAVA-1.2 — Records for Immutable Data

RULE: Use record types for all immutable data carriers including DTOs, value objects, and request or response models. Records provide canonical constructors, accessors, equals, hashCode, and toString automatically. Do not create a plain class with all-final fields and manual boilerplate when a record would serve the same purpose.

CORRECT PATTERN:
public record CreatePaymentRequest(
    @NotNull Long userId,
    @Positive Long amount,
    @NotBlank String currency,
    @NotBlank String idempotencyKey
) {}

VIOLATIONS:
- Plain class with all-final fields and manual equals, hashCode, toString used as a DTO where record applies = LOW
- Mutable fields inside a record = MEDIUM
- record used for a type that requires inheritance (records are implicitly final) without justification = LOW

### JAVA-1.3 — Sealed Types for Closed Hierarchies

RULE: Use sealed interfaces or sealed classes to model domain result types and any closed set of variants that must be exhaustively handled. This enables exhaustive pattern matching and makes illegal states unrepresentable.

CORRECT PATTERN:
public sealed interface PaymentResult
    permits PaymentResult.Success, PaymentResult.Failure {

    record Success(Payment payment) implements PaymentResult {}
    record Failure(String reason, ErrorCode code) implements PaymentResult {}
}

VIOLATIONS:
- Unconstrained interface used to model a closed domain hierarchy where sealed would apply = LOW
- Sealed type with a permitted subtype in a different package without justification = LOW

### JAVA-1.4 — Pattern Matching for instanceof

RULE: Use pattern matching for instanceof introduced in Java 16. Never perform an explicit cast on the same type immediately after an instanceof check. The old two-step pattern is a violation.

VIOLATION PATTERN:
if (result instanceof PaymentResult.Failure) {
    PaymentResult.Failure failure = (PaymentResult.Failure) result;
}

CORRECT PATTERN:
if (result instanceof PaymentResult.Failure failure) {
    log.warn("Payment failed: {}", failure.reason());
}

VIOLATIONS:
- Explicit cast immediately following instanceof check on the same type = LOW
- instanceof check without pattern binding where the bound variable would be used immediately = LOW

### JAVA-1.5 — Optional for Absent Values

RULE: Use Optional<T> as the return type for any public method that may legitimately return an absent value. Never return null from a public method. Optional MUST NOT be used as a field type, constructor parameter, or method parameter.

VIOLATIONS:
- null returned from a public method where Optional would express absence = MEDIUM
- Optional used as a field type = MEDIUM
- Optional used as a method or constructor parameter = MEDIUM
- Optional.get() called without a preceding isPresent() check or orElse/orElseThrow = HIGH

### JAVA-1.6 — Immutable Collections

RULE: Use List.of(), Map.of(), and Set.of() for collections that are not modified after construction. Never return a mutable collection from a public method when an unmodifiable view would serve the same purpose.

VIOLATIONS:
- new ArrayList<>() used to create a collection that is immediately returned and never modified = LOW
- Mutable collection returned from a public API method when immutability is sufficient = LOW

---

## SECTION JAVA-2 — ERROR AND EXCEPTION HANDLING

### JAVA-2.1 — No Silent Exception Swallowing

RULE: Empty catch blocks are PROHIBITED. Every caught exception MUST be either logged with the full exception object as the last argument to preserve the stack trace, or rethrown wrapped in a typed domain exception with the original as the cause. A catch block containing only a comment is also a violation.

VIOLATION PATTERN:
try {
    paymentStore.save(payment);
} catch (Exception e) {
    // nothing
}

CORRECT PATTERN:
try {
    paymentStore.save(payment);
} catch (DataAccessException e) {
    log.error("Failed to persist payment id={}", payment.getId(), e);
    throw new PaymentPersistenceException(
        "Payment could not be saved: " + payment.getId(), e
    );
}

VIOLATIONS:
- Empty catch block = HIGH
- Catch block with only a comment and no action = HIGH
- Exception logged without passing the exception object as the last argument (stack trace lost) = MEDIUM
- Exception caught and a new exception thrown without preserving the original cause = MEDIUM

### JAVA-2.2 — Typed Exception Hierarchy

RULE: Never throw the raw java.lang.Exception or java.lang.Throwable from application code. Use typed exception classes that extend RuntimeException for domain and infrastructure errors. Build a clear exception hierarchy so callers can catch at the appropriate level of specificity.

REQUIRED HIERARCHY PATTERN:
Domain layer:
public class PaymentException extends RuntimeException
public class InsufficientFundsException extends PaymentException
public class PaymentNotFoundException extends PaymentException

Infrastructure layer:
public class StoreException extends RuntimeException

VIOLATIONS:
- throw new Exception("message") used in application code = MEDIUM
- throw new RuntimeException("message") used directly without a typed subclass = MEDIUM
- Exception hierarchy flat with no domain grouping = LOW

### JAVA-2.3 — Global Exception Handler

RULE: All Spring Boot services MUST have a @RestControllerAdvice class that maps domain exceptions to HTTP responses. This class is the only place where exceptions are translated to HTTP status codes and response bodies. It MUST log internally and return a safe public-facing response. Stack traces and internal messages MUST NEVER appear in HTTP response bodies.

CORRECT PATTERN:
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(PaymentNotFoundException.class)
    public ResponseEntity<ErrorResponse> handleNotFound(
        PaymentNotFoundException ex, HttpServletRequest request
    ) {
        log.warn("Payment not found: {}", ex.getMessage());
        return ResponseEntity.status(404).body(
            new ErrorResponse("Payment not found", correlationId(request))
        );
    }
}

VIOLATIONS:
- No @RestControllerAdvice present in the service = HIGH
- Stack trace included in the HTTP response body = HIGH
- Internal exception message returned directly to the client = HIGH
- @ExceptionHandler catching Exception or Throwable as the only handler with no specific handlers = MEDIUM
- HTTP error response body does not include a correlation ID = MEDIUM

### JAVA-2.4 — No Exceptions for Control Flow

RULE: Exceptions MUST NOT be used for expected conditional logic or flow control. Throwing an exception for a condition that is a normal application state (e.g., checking if a record exists) is a violation.

VIOLATIONS:
- Exception thrown and caught within the same method to branch logic = MEDIUM
- Exception used to signal an expected business condition that should be modelled as a return value = MEDIUM

---

## SECTION JAVA-3 — ARCHITECTURE (SPRING BOOT)

### JAVA-3.1 — Strict Layer Enforcement

RULE: The application MUST follow a strict three-layer architecture: Controller to Service to Repository. No layer may import or reference types from a non-adjacent layer. Controllers MUST NOT contain @Entity references, @Repository injections, or any business logic. Repositories MUST NOT contain business logic.

REQUIRED FLOW:
@RestController → @Service → @Repository → Database

PROHIBITED:
- @Entity or @Repository imported in a @Controller class
- Business logic (conditional rules, calculations, orchestration) inside a @Controller method
- @RestController imported or referenced in a @Service class
- Direct database calls from a @Controller

VIOLATIONS:
- @Entity type imported or used in a @Controller = MEDIUM
- @Repository injected into a @Controller = MEDIUM
- Business logic present in a @Controller method body = MEDIUM
- Controller method body longer than receiving, delegating, and returning = MEDIUM

### JAVA-3.2 — Constructor Injection Only

RULE: All Spring-managed dependencies MUST be injected via constructor injection. @Autowired field injection is PROHIBITED. Field injection couples the class to the Spring container and makes unit testing impossible without loading the full context.

VIOLATION PATTERN:
@Service
public class PaymentService {
    @Autowired
    private PaymentRepository paymentRepository;
}

CORRECT PATTERN:
@Service
public class PaymentService {
    private final PaymentRepository paymentRepository;
    private final NotificationService notificationService;

    public PaymentService(
        PaymentRepository paymentRepository,
        NotificationService notificationService
    ) {
        this.paymentRepository = paymentRepository;
        this.notificationService = notificationService;
    }
}

VIOLATIONS:
- @Autowired on a field = HIGH
- @Inject on a field = HIGH
- Spring bean dependency not declared final = LOW
- Constructor not validating null dependencies for critical collaborators = LOW

### JAVA-3.3 — DTOs at the API Surface

RULE: @Entity objects MUST NEVER be returned directly from @Controller methods or @RestController endpoints. Returning an entity leaks the database schema, risks infinite recursion on bidirectional relationships, and couples the API contract to the persistence model. Always map to a dedicated response DTO.

VIOLATION PATTERN:
@GetMapping("/{id}")
public Payment getPayment(@PathVariable Long id) {
    return paymentRepository.findById(id).orElseThrow();
}

CORRECT PATTERN:
@GetMapping("/{id}")
public ResponseEntity<PaymentResponse> getPayment(@PathVariable Long id) {
    return paymentService.findById(id)
        .map(PaymentResponse::from)
        .map(ResponseEntity::ok)
        .orElseThrow(() -> new PaymentNotFoundException(id));
}

VIOLATIONS:
- @Entity returned directly from a @RestController or @Controller method = HIGH
- @Entity used as a @RequestBody parameter in a controller = HIGH
- Response DTO exposing fields not intended for external consumption = MEDIUM

### JAVA-3.4 — Transactional Boundaries

RULE: @Transactional MUST be placed at the service layer only. Placing it on a controller couples the HTTP layer to transaction management. Placing it broadly on repository methods defeats the purpose of service-layer transaction orchestration. Use @Transactional(readOnly = true) on read-only service methods to signal intent and enable optimizations.

VIOLATIONS:
- @Transactional on a @Controller or @RestController method = MEDIUM
- @Transactional absent on a service method that performs multiple related writes = MEDIUM
- @Transactional without readOnly = true on a service method that only reads = LOW

### JAVA-3.5 — Cross-Domain Communication

RULE: Direct @Service to @Service calls that cross domain boundaries are PROHIBITED. Use Spring ApplicationEventPublisher and @EventListener to decouple domain interactions. This preserves transactional integrity and prevents circular dependencies.

VIOLATIONS:
- @Service from one domain (e.g., payment) directly injecting and calling a @Service from another domain (e.g., notification) without an event = MEDIUM
- Circular @Service dependency = HIGH

---

## SECTION JAVA-4 — SECURITY (SPRING BOOT)

### JAVA-4.1 — Input Validation with @Valid

RULE: All @RequestBody parameters and path or query parameters in @Controller and @RestController methods MUST be annotated with @Valid or @Validated. Manual field-by-field null and range checking inside the controller method body is PROHIBITED. Validation annotations (@NotNull, @Positive, @NotBlank, @Size) MUST be declared on the DTO or record fields.

VIOLATION PATTERN:
@PostMapping
public ResponseEntity<PaymentResponse> create(@RequestBody Map<String, Object> body) {
    if (body.get("amount") == null) { ... }
}

CORRECT PATTERN:
@PostMapping
public ResponseEntity<PaymentResponse> create(
    @Valid @RequestBody CreatePaymentRequest request
) {
    return ResponseEntity.status(201).body(paymentService.create(request));
}

VIOLATIONS:
- @Valid or @Validated absent from @RequestBody parameter = HIGH
- Manual null or range check for a field inside a controller method = HIGH
- @RequestBody accepted as Map or raw Object without schema validation = HIGH
- Validation annotations missing from DTO fields = MEDIUM

### JAVA-4.2 — SQL Parameterization

RULE: All SQL and JPQL queries MUST use named parameters or positional placeholders. String concatenation or interpolation to build a query is a CRITICAL violation regardless of whether the concatenated value originates from user input.

VIOLATION PATTERN:
@Query("SELECT p FROM Payment p WHERE p.email = '" + email + "'")

CORRECT PATTERNS:
@Query("SELECT p FROM Payment p WHERE p.email = :email")
Optional<Payment> findByEmail(@Param("email") String email);

jdbcTemplate.queryForObject(
    "SELECT id FROM payments WHERE email = ?",
    Long.class,
    email
);

VIOLATIONS:
- String concatenation used to build a JPQL or SQL query = CRITICAL
- String.format or formatted string used to interpolate values into a query = CRITICAL
- Named parameter declared in @Query but binding annotation @Param missing = MEDIUM

### JAVA-4.3 — Secret Management

RULE: No real credentials, passwords, API keys, tokens, or DSN values may appear in application.properties, application.yml, or any file committed to version control. All secrets MUST be referenced via environment variable placeholders or externalised to a secret manager.

VIOLATION PATTERN in application.properties:
spring.datasource.password=MyRealPassword123

CORRECT PATTERN:
spring.datasource.password=${DATABASE_PASSWORD}

VIOLATIONS:
- Real credential value in application.properties or application.yml = CRITICAL
- Real credential value in any test configuration file = CRITICAL
- Secret referenced as a hardcoded string literal in Java source = CRITICAL
- Placeholder present but environment variable has no documented injection mechanism = MEDIUM

### JAVA-4.4 — CSRF and Security Configuration

RULE: Spring Security CSRF protection MUST be enabled for all stateful (session-based) endpoints. Stateless REST APIs using JWT or API keys MAY disable CSRF but MUST explicitly document and justify the decision in the security configuration class with a comment.

VIOLATIONS:
- CSRF disabled for a stateful session-based endpoint = HIGH
- CSRF disabled in security config with no explanatory comment = MEDIUM
- Spring Security not configured at all in a web-facing service = HIGH

### JAVA-4.5 — No Stack Traces in HTTP Responses

RULE: Stack traces, exception class names, internal file paths, and database error messages MUST NEVER appear in HTTP response bodies. The @RestControllerAdvice global handler is responsible for intercepting all unhandled exceptions and returning a safe structured error response containing only a public message and a correlation ID.

VIOLATIONS:
- Stack trace present in an HTTP response body = HIGH
- Exception class name or internal message present in an HTTP response body = HIGH
- Default Spring Boot error response (/error endpoint) exposed without customisation = MEDIUM

---

## SECTION JAVA-5 — CONCURRENCY

### JAVA-5.1 — No Raw Thread Usage

RULE: Never instantiate raw Thread objects to execute asynchronous work in production code. Use CompletableFuture with a named bounded ExecutorService, Spring @Async with a configured ThreadPoolTaskExecutor, or a reactive stream library (Project Reactor or RxJava) depending on the use case.

VIOLATION PATTERN:
new Thread(() -> processAsync(payment)).start();

CORRECT PATTERN:
CompletableFuture.supplyAsync(
    () -> paymentService.process(payment),
    paymentExecutor
).thenAccept(result -> notifier.send(result))
 .exceptionally(ex -> { log.error("Async payment failed", ex); return null; });

VIOLATIONS:
- Raw Thread instantiated and started in production code = MEDIUM
- Runnable submitted to an unnamed or unbounded thread pool = MEDIUM
- CompletableFuture used without specifying an explicit executor (defaults to ForkJoinPool.commonPool which is shared) = LOW

### JAVA-5.2 — No Thread.sleep for Timing

RULE: Thread.sleep() MUST NOT be used in production code for scheduling, throttling, or retry timing. Use ScheduledExecutorService, Spring @Scheduled, or a retry library such as Resilience4j.

VIOLATION PATTERN:
Thread.sleep(5000);

CORRECT PATTERN:
scheduledExecutor.scheduleAtFixedRate(
    this::reconcilePayments, 0, 1, TimeUnit.HOURS
);

VIOLATIONS:
- Thread.sleep() present in production service code = MEDIUM
- Thread.sleep() used inside a retry loop = MEDIUM

### JAVA-5.3 — Shared Mutable State Protection

RULE: All shared mutable state accessed from multiple threads MUST be protected by explicit synchronization, use java.util.concurrent thread-safe collections, or be redesigned as immutable. Prefer immutability and java.util.concurrent types over manual synchronization.

REQUIRED TYPES:
- Use ConcurrentHashMap instead of HashMap for concurrent access
- Use CopyOnWriteArrayList instead of ArrayList for concurrent iteration with infrequent writes
- Use AtomicLong, AtomicInteger, AtomicReference for single-variable counters and flags

VIOLATIONS:
- HashMap accessed from multiple threads without synchronization = CRITICAL
- Shared mutable field written from multiple threads without a lock or atomic type = CRITICAL
- synchronized block used where a ConcurrentHashMap would eliminate the need = LOW

### JAVA-5.4 — Exception Handling in Async Code

RULE: Exceptions thrown inside CompletableFuture stages MUST be handled via exceptionally(), handle(), or whenComplete(). Unhandled exceptions in async chains are silently swallowed by the JVM.

VIOLATIONS:
- CompletableFuture chain with no exceptionally() or handle() stage = HIGH
- Exception logged in exceptionally() but not rethrown or signalled when the caller needs to know = MEDIUM

---

## SECTION JAVA-6 — STYLE AND TOOLING

### JAVA-6.1 — Code Formatting

RULE: All Java code MUST conform to the Google Java Style Guide enforced by google-java-format or a Checkstyle configuration using the Google profile. Unformatted code is a violation and MUST be corrected before merge.

VIOLATIONS:
- Code not conforming to Google Java Style Guide = LOW
- Inconsistent indentation or brace style within a file = LOW

### JAVA-6.2 — Immutability by Default

RULE: Declare all fields final wherever the value is assigned once and never reassigned. This applies to instance fields, local variables, and method parameters where reassignment does not occur.

VIOLATIONS:
- Non-final instance field in a Spring bean where the value is set only in the constructor = LOW
- Local variable not declared final when it is never reassigned = INFO

### JAVA-6.3 — Static Analysis Gates

RULE: All of the following static analysis tools MUST pass with zero blocking findings before a merge is approved.

REQUIRED TOOLS AND PURPOSE:
- google-java-format or Checkstyle with Google profile: formatting and style
- SpotBugs: zero HIGH or CRITICAL findings
- PMD: cognitive complexity per method must not exceed 15
- JaCoCo: coverage gate enforcement
- OWASP Dependency Check: zero CRITICAL or HIGH CVE findings in direct dependencies

REQUIRED COMMANDS:
./mvnw checkstyle:check
./mvnw spotbugs:check
./mvnw pmd:check
./mvnw test jacoco:report
./mvnw dependency-check:check

VIOLATIONS:
- SpotBugs HIGH or CRITICAL finding = HIGH
- PMD cognitive complexity above 15 for any method = MEDIUM
- OWASP Dependency Check CRITICAL CVE in direct dependency = CRITICAL
- OWASP Dependency Check HIGH CVE in direct dependency = HIGH
- JaCoCo coverage gate failing = MEDIUM

### JAVA-6.4 — SonarQube Quality Gate

RULE: The SonarQube quality gate MUST be green for every pull request before merge. A red quality gate is a merge blocker regardless of the category of finding.

VIOLATIONS:
- SonarQube quality gate red = HIGH
- New SonarQube bug finding = HIGH
- New SonarQube vulnerability finding = CRITICAL
- New SonarQube security hotspot not reviewed = MEDIUM

---

## SECTION JAVA-7 — TESTING

### JAVA-7.1 — Test Framework Requirements

RULE: All new tests MUST use JUnit 5 with AssertJ for assertions. JUnit 4 is PROHIBITED in new code. Use Mockito with @ExtendWith(MockitoExtension.class) for mocking. Never use PowerMock or other bytecode-manipulation mocking libraries for new code.

VIOLATIONS:
- JUnit 4 @Test or @RunWith annotation present in new test code = MEDIUM
- AssertJ not used for assertions where it would replace assertTrue or assertEquals = LOW
- Mockito used without @ExtendWith(MockitoExtension.class) = LOW
- PowerMock or bytecode-manipulation library used = MEDIUM

### JAVA-7.2 — Test Naming

RULE: Test method names MUST follow the BDD-style pattern describing the scenario and expected outcome. Use @DisplayName for human-readable descriptions. The method name MUST follow the pattern: unitUnderTest_scenarioDescription_expectedOutcome.

CORRECT PATTERN:
@Test
@DisplayName("should throw InsufficientFundsException when account balance is zero")
void refund_whenBalanceIsZero_throwsInsufficientFundsException() {}

VIOLATIONS:
- Test method named testRefund or test1 with no scenario or outcome = LOW
- @DisplayName absent from test method = LOW
- Test name does not describe the expected outcome = LOW

### JAVA-7.3 — Layer-Specific Test Slices

RULE: Use the narrowest Spring test slice annotation that covers the layer under test. @SpringBootTest loads the full application context and is expensive. Prefer @WebMvcTest for controller layer tests, @DataJpaTest for repository layer tests, and plain JUnit 5 with Mockito for service layer unit tests.

REQUIRED MAPPING:
- Controller layer: @WebMvcTest(ControllerClass.class)
- Repository layer: @DataJpaTest
- Service layer unit test: plain JUnit 5 with Mockito, no Spring context
- Full integration test: @SpringBootTest (use sparingly with justification comment)

VIOLATIONS:
- @SpringBootTest used for a test that only exercises the controller layer = MEDIUM
- @SpringBootTest used for a test that only exercises the repository layer = MEDIUM
- Service layer test loading the Spring context when Mockito would suffice = MEDIUM

### JAVA-7.4 — Testcontainers for Infrastructure

RULE: Tests that require a real database, message broker, or other external infrastructure MUST use Testcontainers. In-memory H2 or SQLite MUST NOT be used as a substitute for PostgreSQL integration tests. Financial logic MUST be tested against the real database engine.

CORRECT PATTERN:
@Testcontainers
class PaymentRepositoryIT {
    @Container
    static PostgreSQLContainer<?> postgres =
        new PostgreSQLContainer<>("postgres:16-alpine");
}

VIOLATIONS:
- H2 in-memory database used for PostgreSQL integration tests = MEDIUM
- Real external database or broker accessed in tests without Testcontainers = MEDIUM
- Testcontainers image version unpinned (using latest tag) = LOW

### JAVA-7.5 — Coverage Targets

RULE: The following minimum coverage targets MUST be met and enforced via JaCoCo in CI. Coverage is measured by line coverage. These are floors, not goals.

REQUIRED TARGETS:
- Service layer: 85% line coverage
- Controller layer: 80% line coverage
- Repository layer: 75% line coverage (backed by Testcontainers integration tests)

VIOLATIONS:
- Service layer below 85% line coverage = MEDIUM
- Controller layer below 80% line coverage = MEDIUM
- New business logic added with no corresponding tests = HIGH
- Test present but only covering the happy path with no error path coverage = MEDIUM

---

## SECTION JAVA-8 — SEVERITY TABLE

CRITICAL — Security vulnerability, data loss risk, production crash risk, or hardcoded credential. Action: Block merge immediately.
HIGH — Significant reliability, correctness, security posture, or testability risk. Action: Block merge. Fix required before approval.
MEDIUM — Meaningful deviation from standards with maintainability or correctness risk. Action: Fix within current sprint.
LOW — Style, readability, or minor advisory issue. Action: Add to backlog.
INFO — Observation or suggestion with no compliance impact. Action: Optional.

---

## SECTION JAVA-9 — STANDARDS_SCORE RUBRIC

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

*Standards Version: 2.1 | Language: Java 21 LTS | Framework: Spring Boot 3.x | Last Reviewed: March 2026*
*Owner: Engineering Standards Committee*
*Amendments: Raise a PR against scripts/standards/java_standards.md*