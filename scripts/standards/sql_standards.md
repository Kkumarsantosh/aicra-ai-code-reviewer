# SQL CODING STANDARDS
# Version: 2.1 | Database: PostgreSQL (primary), MySQL (secondary)
# Injected via CODING_STANDARDS_PLACEHOLDER into engine/prompt.txt
# This section is evaluated by the AI reviewer for all .sql files,
# inline SQL in any language file, ORM query definitions, and migration files

---

## AI AGENT INSTRUCTION — SQL SECTION

You are reviewing SQL code. This includes standalone .sql files, migration files, inline SQL strings embedded in any language, ORM query annotations, and stored procedure definitions. For every SQL artefact in the diff you MUST:

STEP 1 — Read every rule in this document before producing any finding.
STEP 2 — Check each rule against the code under review. Do not skip sections.
STEP 3 — For every violation produce a finding in this exact format:

FINDING:
  RULE: {rule ID, e.g. SQL-1.1}
  SEVERITY: {CRITICAL | HIGH | MEDIUM | LOW | INFO}
  FILE: {filename}
  LINE: {line number or range if available}
  VIOLATION: {what the code does that breaks the rule}
  REQUIRED FIX: {what the code must do instead}

STEP 4 — After all findings, output the STANDARDS_SCORE block defined at the end of this document.
STEP 5 — Never suppress a finding because the query appears to return correct results. Compliance and correctness are independent concerns.

---

## SECTION SQL-1 — SAFETY AND INJECTION PREVENTION

### SQL-1.1 — Parameterized Queries Are Mandatory

RULE: This is the single most critical SQL rule. All SQL queries executed from application code MUST use parameterized placeholders. String concatenation, string interpolation, and template literal construction of SQL query strings are CRITICAL violations regardless of whether the interpolated value originates from user input, a database field, or an internal variable. There are no exceptions to this rule.

REQUIRED PLACEHOLDERS BY DATABASE:
PostgreSQL: $1, $2, $3 positional parameters
MySQL: ? positional parameters
Named parameters where the driver supports them: :email, :accountId

VIOLATION PATTERN:
SELECT * FROM payments WHERE email = '<user_input>'
SELECT * FROM payments WHERE email = '" + email + "'
SELECT * FROM payments WHERE email = `${email}`

CORRECT PATTERNS:
PostgreSQL: SELECT id, amount, status FROM payments WHERE email = $1
MySQL: SELECT id, amount, status FROM payments WHERE email = ?

VIOLATIONS:
- SQL built with string concatenation containing any variable = CRITICAL
- SQL built with template literal interpolation containing any variable = CRITICAL
- SQL built with sprintf or equivalent string formatting containing any variable = CRITICAL
- Dynamic SQL in a stored procedure built from user-supplied input without parameterization = CRITICAL
- ORM raw query method called with string interpolation instead of bound parameters = CRITICAL

### SQL-1.2 — Database User Least Privilege

RULE: The application runtime database user MUST have only the minimum privileges required to execute application queries. Schema-level operations are PROHIBITED for the application user. A separate migration user with elevated privileges MUST be used exclusively during deployment migrations.

APPLICATION USER — PERMITTED PRIVILEGES ONLY:
- SELECT on required tables
- INSERT on required tables
- UPDATE on required tables
- DELETE on required tables
- EXECUTE on required functions and stored procedures

APPLICATION USER — PROHIBITED PRIVILEGES:
- DROP
- CREATE
- ALTER
- TRUNCATE
- GRANT
- REVOKE
- pg_dump or equivalent backup access

VIOLATIONS:
- Application database user granted ALTER privilege = HIGH
- Application database user granted DROP privilege = HIGH
- Application database user granted CREATE privilege = HIGH
- Application database user granted GRANT or REVOKE privilege = HIGH
- Single database user used for both application runtime and schema migrations = HIGH
- Application user granted SELECT on tables it does not query = MEDIUM

---

## SECTION SQL-2 — SCHEMA DESIGN STANDARDS

### SQL-2.1 — Primary Keys

RULE: Every table MUST have a primary key. For distributed systems and services that generate IDs independently, use a UUID primary key with gen_random_uuid() as the default. For simpler single-database cases where sequential IDs are acceptable, use BIGSERIAL. Never use a natural key (email, phone number, national ID) as a primary key.

CORRECT PATTERNS:
Distributed systems preferred:
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ...
);

Simpler sequential case:
CREATE TABLE payment_events (
    id BIGSERIAL PRIMARY KEY,
    ...
);

VIOLATIONS:
- Table defined without a primary key = HIGH
- Natural key such as email or phone used as the primary key = MEDIUM
- Integer primary key used in a table that will be accessed across distributed services = LOW

### SQL-2.2 — Timestamps

RULE: All timestamp columns MUST use TIMESTAMPTZ (timestamp with time zone) or the equivalent timezone-aware type for the target database. Storing timestamps without timezone information (plain TIMESTAMP) is PROHIBITED because it creates ambiguity when the application or database server timezone changes. All timestamps MUST default to NOW() which records in UTC when the database timezone is UTC.

REQUIRED STANDARD COLUMNS:
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
deleted_at TIMESTAMPTZ NULL

VIOLATION PATTERN:
created_at TIMESTAMP DEFAULT NOW()

VIOLATIONS:
- Timestamp column using TIMESTAMP without timezone = MEDIUM
- Timestamp column using DATE where time precision is needed = MEDIUM
- Timestamp stored as a VARCHAR or INTEGER unix epoch without justification = MEDIUM
- updated_at column absent from a table that records mutable state = LOW

### SQL-2.3 — Soft Deletes

RULE: Soft deletes MUST be implemented using a deleted_at TIMESTAMPTZ NULL column. A boolean is_deleted flag is PROHIBITED because it loses the deletion timestamp, preventing audit trail reconstruction. A NULL value in deleted_at means the record is active. A non-NULL value means the record is soft-deleted. All queries against tables with soft delete MUST filter WHERE deleted_at IS NULL unless the query is intentionally retrieving deleted records.

VIOLATION PATTERN:
is_deleted BOOLEAN DEFAULT FALSE

CORRECT PATTERN:
deleted_at TIMESTAMPTZ NULL DEFAULT NULL

VIOLATIONS:
- Soft delete implemented as a boolean is_deleted flag = LOW
- Query against a soft-delete-enabled table missing WHERE deleted_at IS NULL = HIGH
- Soft-delete column present but not of type TIMESTAMPTZ = MEDIUM
- Hard DELETE used on a table that requires an audit trail = HIGH

### SQL-2.4 — Nullability

RULE: NOT NULL is the default for all columns. NULL is only permitted when the absence of a value is semantically meaningful for the domain and the column is documented with an inline comment explaining why NULL is valid. A column that allows NULL without justification is a schema design violation.

CORRECT PATTERN:
email   VARCHAR(255) NOT NULL,
phone   VARCHAR(20)  NULL,  -- optional: user may not provide a phone number at registration

VIOLATION PATTERN:
user_id BIGINT NULL

VIOLATIONS:
- Column declared NULL without an inline comment justifying the nullability = LOW
- Foreign key column declared NULL where the relationship is mandatory = MEDIUM
- Primary key column that could theoretically be NULL = HIGH

### SQL-2.5 — Foreign Key Constraints

RULE: Foreign key relationships MUST be enforced at the database level with explicit FOREIGN KEY constraints. Application-level enforcement alone is insufficient. Use ON DELETE RESTRICT for all foreign keys in financial tables unless CASCADE or SET NULL behaviour is explicitly justified with a comment. RESTRICT prevents accidental deletion of referenced records.

CORRECT PATTERN:
ALTER TABLE payments
    ADD CONSTRAINT fk_payments_accounts
    FOREIGN KEY (account_id)
    REFERENCES accounts(id)
    ON DELETE RESTRICT;

VIOLATIONS:
- Foreign key column present with no corresponding FOREIGN KEY constraint = MEDIUM
- ON DELETE CASCADE used on a financial table without justification comment = MEDIUM
- Foreign key constraint named without following the fk_{table}_{referenced_table} convention = LOW

---

## SECTION SQL-3 — MIGRATION STANDARDS

### SQL-3.1 — File Naming Convention

RULE: Migration files MUST follow the naming convention of the migration tool in use. Both formats are acceptable. The description part MUST be meaningful and describe what the migration does, not when it was created.

ACCEPTED NAMING FORMATS:
Flyway: V{version}__{description}.sql
GORM or Goose: {timestamp}_{description}.sql

CORRECT EXAMPLES:
V20260301_001__add_refund_status_to_payments.sql
V20260301_002__create_payment_audit_log_table.sql
20260301120000_add_refund_status_to_payments.sql

VIOLATIONS:
- Migration file name does not follow the required convention = LOW
- Migration description is generic and does not describe the schema change = LOW
- Version or timestamp component missing from the filename = MEDIUM

### SQL-3.2 — Migration Reversibility

RULE: Every migration MUST include both an up direction and a down direction. The down migration MUST reverse the up migration completely. Migrations that cannot be reversed must be documented with a comment explaining why and must be approved by the Engineering Standards Committee before merge.

CORRECT PATTERN:
Up migration:
ALTER TABLE payments ADD COLUMN refunded_at TIMESTAMPTZ NULL;

Down migration:
ALTER TABLE payments DROP COLUMN refunded_at;

VIOLATIONS:
- Migration file with no down direction = MEDIUM
- Down migration that does not fully reverse the up migration = MEDIUM
- Irreversible migration with no explanatory comment and no approval documented = HIGH

### SQL-3.3 — Zero-Downtime Migration Rules

RULE: Migrations on production tables with more than 100,000 rows MUST follow zero-downtime patterns to avoid table locks and application outages. The following specific rules apply.

RULE — INDEX CREATION: Indexes MUST be created using CREATE INDEX CONCURRENTLY. Non-concurrent index creation locks the table for the duration of the build and is PROHIBITED on large tables.

VIOLATION PATTERN:
CREATE INDEX idx_payments_user_id ON payments(user_id);

CORRECT PATTERN:
CREATE INDEX CONCURRENTLY idx_payments_user_id ON payments(user_id);

RULE — ADDING COLUMNS WITH CONSTRAINTS: New NOT NULL columns with no default value lock the table while existing rows are rewritten. Add the column as NULLABLE first, backfill the data, then add the NOT NULL constraint in a subsequent migration.

RULE — COLUMN RENAMING: Never rename a column directly with ALTER TABLE ... RENAME COLUMN in a zero-downtime deployment. Add the new column, deploy code that writes to both, migrate data, deploy code that reads from the new column only, then drop the old column in a final migration.

RULE — STAGING VALIDATION: Migration execution time MUST be validated against production-scale data volume in a staging environment before the migration is run in production.

VIOLATIONS:
- CREATE INDEX without CONCURRENTLY on a table expected to be large = HIGH
- NOT NULL column added without a default value in a single migration on a large table = HIGH
- Column renamed directly with RENAME COLUMN without a multi-step process = HIGH
- Migration not validated against production-scale data in staging = MEDIUM

---

## SECTION SQL-4 — QUERY STANDARDS

### SQL-4.1 — No SELECT Star

RULE: SELECT * is PROHIBITED in all application queries. All queries MUST explicitly list the columns being selected. This prevents unintentional exposure of sensitive columns added to the table in future migrations and reduces data transfer overhead.

VIOLATION PATTERN:
SELECT * FROM accounts WHERE id = $1;

CORRECT PATTERN:
SELECT id, email, status, created_at
FROM accounts
WHERE id = $1
AND deleted_at IS NULL;

VIOLATIONS:
- SELECT * used in any application query = MEDIUM
- SELECT * used in a view definition where the column list matters = MEDIUM
- SELECT * used in a stored procedure that returns results to the application = MEDIUM

### SQL-4.2 — Pagination Required for Large Result Sets

RULE: Any query that may return more than 10,000 rows MUST implement pagination. Cursor-based pagination is preferred for large datasets because it performs consistently regardless of page depth. Offset-based pagination is acceptable for small bounded result sets only. Unbounded queries on large tables are PROHIBITED.

VIOLATION PATTERN:
SELECT id, amount FROM payments WHERE status = 'pending';

CORRECT PATTERNS:
Cursor-based (preferred for large datasets):
SELECT id, amount, created_at
FROM payments
WHERE status = 'pending'
AND created_at < $1
ORDER BY created_at DESC
LIMIT 50;

Offset-based (acceptable for small bounded sets):
SELECT id, amount FROM payments
ORDER BY created_at DESC
LIMIT $1 OFFSET $2;

VIOLATIONS:
- Query on a large table with no LIMIT clause = HIGH
- Offset pagination used on a table with unbounded growth where cursor pagination applies = MEDIUM
- LIMIT present but no ORDER BY to make the pagination deterministic = MEDIUM

### SQL-4.3 — N+1 Query Prevention

RULE: Issuing one query per row of a result set is PROHIBITED. This N+1 pattern causes quadratic growth in database load at production volumes. Use JOIN operations to fetch related data in a single query, or use batch loading where JOIN is not appropriate.

VIOLATION PATTERN:
SELECT id FROM payments WHERE status = 'pending';
-- then for each id in application code: SELECT * FROM accounts WHERE id = {payment.account_id}

CORRECT PATTERN:
SELECT p.id, p.amount, a.email, a.status AS account_status
FROM payments p
INNER JOIN accounts a ON a.id = p.account_id
WHERE p.status = 'pending'
AND p.deleted_at IS NULL
AND a.deleted_at IS NULL;

VIOLATIONS:
- Application code querying inside a loop over database results = HIGH
- Related data fetched with a separate query per parent row instead of a JOIN = HIGH
- ORM lazy loading used in a context where eager loading with JOIN would prevent N+1 = MEDIUM

### SQL-4.4 — Index Requirements

RULE: Columns used in WHERE clauses, JOIN ON conditions, and ORDER BY clauses in high-frequency queries MUST be indexed. Foreign key columns in PostgreSQL MUST be explicitly indexed because PostgreSQL does not create indexes on foreign key columns automatically. Partial indexes MUST be used where a condition filters a large portion of rows.

REQUIRED INDEX PATTERNS FOR FINANCIAL TABLES:
CREATE INDEX CONCURRENTLY idx_payments_account_id  ON payments(account_id);
CREATE INDEX CONCURRENTLY idx_payments_status      ON payments(status) WHERE deleted_at IS NULL;
CREATE INDEX CONCURRENTLY idx_payments_created_at  ON payments(created_at DESC);
CREATE UNIQUE INDEX       idx_payments_idempotency ON payments(idempotency_key);

VIOLATIONS:
- High-frequency WHERE clause column with no index = HIGH
- JOIN ON column with no index = HIGH
- ORDER BY column in a paginated query with no index = HIGH
- Foreign key column in PostgreSQL with no explicit index = MEDIUM
- New index created without CONCURRENTLY on a production table = HIGH
- EXPLAIN ANALYZE not reviewed for a new query on a large table = MEDIUM

---

## SECTION SQL-5 — NAMING CONVENTIONS

### SQL-5.1 — Object Naming Rules

RULE: All database object names MUST follow the naming conventions defined below. Inconsistent naming makes schema navigation and query writing error-prone and slows onboarding.

REQUIRED NAMING CONVENTIONS:
Table: snake_case, plural noun. Example: payment_transactions, account_balances
Column: snake_case. Example: created_at, account_id, idempotency_key
Primary key column: always named id unless a natural key is explicitly justified
Foreign key column: {referenced_table_singular}_id. Example: account_id, user_id
Index: idx_{table}_{column_or_columns}. Example: idx_payments_account_id
Unique index: uidx_{table}_{column_or_columns}. Example: uidx_payments_idempotency_key
Foreign key constraint: fk_{table}_{referenced_table}. Example: fk_payments_accounts
Check constraint: chk_{table}_{description}. Example: chk_payments_positive_amount
Stored procedure or function: snake_case verb phrase. Example: calculate_refund_amount

VIOLATIONS:
- Table name not snake_case = LOW
- Table name not plural = LOW
- Column name using camelCase = LOW
- Index name not following idx_ or uidx_ prefix convention = LOW
- Foreign key constraint unnamed or not following fk_ convention = LOW
- Check constraint unnamed or not following chk_ convention = LOW
- Primary key column named something other than id without documented justification = LOW

---

## SECTION SQL-6 — DATA INTEGRITY

### SQL-6.1 — CHECK Constraints for Domain Rules

RULE: Domain rules that can be expressed as column-level or table-level constraints MUST be enforced with CHECK constraints at the database level. Application-level validation alone is insufficient because it can be bypassed by direct database access, migrations, and scripts.

CORRECT PATTERNS:
ALTER TABLE payments
    ADD CONSTRAINT chk_payments_positive_amount
    CHECK (amount > 0);

ALTER TABLE payments
    ADD CONSTRAINT chk_payments_valid_currency
    CHECK (currency IN ('USD', 'EUR', 'GBP', 'SGD'));

VIOLATIONS:
- Business domain rule that could be expressed as a CHECK constraint but is not = MEDIUM
- CHECK constraint present but not named following the chk_ convention = LOW
- Amount or monetary value column with no CHECK constraint enforcing positive values = MEDIUM

### SQL-6.2 — UNIQUE Constraints for Business Keys

RULE: Business keys that must be unique across the table MUST be enforced with a UNIQUE constraint or a unique index at the database level. Idempotency keys MUST always have a UNIQUE constraint.

CORRECT PATTERN:
ALTER TABLE payments
    ADD CONSTRAINT uidx_payments_idempotency_key
    UNIQUE (idempotency_key);

VIOLATIONS:
- Idempotency key column with no UNIQUE constraint = HIGH
- Business key that must be unique enforced only at the application level = MEDIUM

---

## SECTION SQL-7 — SECURITY AND SENSITIVE DATA

### SQL-7.1 — Payment Card Data

RULE: Full Primary Account Numbers (PAN) MUST NEVER be stored in the database. Store only the last four digits for display purposes and a tokenized reference from a PCI-DSS compliant tokenization service. Any column that appears to store a full card number is a CRITICAL violation.

VIOLATIONS:
- Column storing a full 16-digit card number = CRITICAL
- Column named card_number, pan, full_pan, or equivalent that could store a full PAN = CRITICAL
- Card data stored without a corresponding tokenized reference column = HIGH

### SQL-7.2 — Password Storage

RULE: Passwords MUST NEVER be stored in plaintext in the database. Passwords MUST be stored as hashes produced by bcrypt or argon2. A column that stores a plaintext password or an unsalted MD5 or SHA1 hash is a CRITICAL violation.

VIOLATIONS:
- Column named password, pass, passwd storing a value that appears to be plaintext = CRITICAL
- Column storing an MD5 hash (32 hex characters) as a password hash = CRITICAL
- Column storing a SHA1 hash (40 hex characters) as a password hash = CRITICAL

### SQL-7.3 — PII Encryption at Rest

RULE: Columns containing Personally Identifiable Information including email addresses, phone numbers, full names, national identity numbers, and physical addresses SHOULD be encrypted at rest using column-level encryption where the data classification policy requires it. The encryption mechanism must be documented in the schema migration comment.

VIOLATIONS:
- PII column added with no comment addressing encryption classification = LOW
- PII column explicitly classified as requiring encryption but no encryption applied = HIGH

### SQL-7.4 — Audit Logging for Financial Tables

RULE: All INSERT, UPDATE, and DELETE operations on financial tables MUST be captured in a corresponding audit log table. The audit log table MUST record the timestamp, the identity of the user or service that made the change, the operation type, the old values, and the new values. The audit log table MUST be append-only. No UPDATE or DELETE is permitted on the audit log itself.

REQUIRED AUDIT LOG TABLE STRUCTURE:
CREATE TABLE payment_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    payment_id  UUID NOT NULL,
    operation   VARCHAR(10) NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    changed_by  VARCHAR(255) NOT NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    old_values  JSONB NULL,
    new_values  JSONB NULL
);

VIOLATIONS:
- Financial table with no corresponding audit log table = HIGH
- Audit log table missing operation, changed_by, changed_at, old_values, or new_values columns = MEDIUM
- Audit log table that allows UPDATE or DELETE on its own rows = HIGH
- Trigger or application logic for audit logging missing for INSERT, UPDATE, or DELETE = HIGH
- Audit log operation column without a CHECK constraint restricting to INSERT, UPDATE, DELETE = MEDIUM

---

## SECTION SQL-8 — SEVERITY TABLE

CRITICAL — SQL injection vector, full PAN storage, plaintext passwords, or data loss risk. Action: Block merge immediately.
HIGH — Unbounded query on a large table, missing soft-delete filter, missing audit log, table-locking index creation, or privilege escalation. Action: Block merge. Fix required before approval.
MEDIUM — Schema design violation, missing foreign key constraint, irreversible migration, nullability without justification, or N+1 pattern. Action: Fix within current sprint.
LOW — Naming convention violation, missing comment on nullable column, style issue, or advisory improvement. Action: Add to backlog.
INFO — Observation or suggestion with no compliance impact. Action: Optional.

---

## SECTION SQL-9 — STANDARDS_SCORE RUBRIC

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

*Standards Version: 2.1 | Database: PostgreSQL (primary), MySQL (secondary) | Last Reviewed: March 2026*
*Owner: Engineering Standards Committee*
*Amendments: Raise a PR against scripts/standards/sql_standards.md*