# Issues Analysis

## Summary

| Type | Critical | High | Medium | Low | Total |
|------|----------|------|--------|-----|-------|
| Product Issues | 1 | 2 | 0 | 0 | 3 |
| Code Issues | 1 | 2 | 0 | 0 | 3 |

---

## Product Issues

> Product issues are user-facing problems: broken functionality, missing validation, poor UX, data integrity risks visible to users.

### [P1] Test Case Data Corruption & Silent Truncation to 260 Bytes

**Severity**: Critical

**Location**: `problems/views.py:556-563`

**Description**:
When migrating test cases to the local database via the "Migrate Test Description to Database" action (`migrate_test_cases_to_db`), test case input and output strings are arbitrarily truncated to 260 bytes:
```python
truncated_input = input_data[:260]
truncated_output = output_data[:260]
```
Additionally, line 555 checks `if input_data and output_data:`, which completely drops valid test cases whose expected output is an empty string, whitespace-only, or whose input is empty.

**Impact**:
- Real programming problems frequently feature test inputs and outputs with hundreds or thousands of characters (e.g., large arrays, graphs, long strings, matrices). Truncating them after 260 bytes corrupts test case data in the database.
- Any submission judging, offline testing, or user preview that relies on database test cases will fail with parse errors, unexpected EOF, or false wrong-answer verdicts.
- Staff users are given a false success notification ("Test cases description migrated to database Successfully.") without any warning that data was permanently truncated or that empty/whitespace test cases were skipped.

**Suggested Fix**:
Remove the 260-byte slicing and store the full input and output strings directly in `ProblemTestCase.input` and `ProblemTestCase.output` (both are `TextField` fields capable of storing large text). Remove the `if input_data and output_data:` check so test cases with empty inputs or outputs are preserved.

---

### [P2] Duplicate Problem Titles Cause Complete Migration Failure (Slug Collision)

**Severity**: High

**Location**: `problems/views.py:315`, `problems/models.py:58`

**Description**:
The `Problem` model defines `slug` with a database unique constraint:
```python
slug = models.SlugField(unique=True, max_length=255)
```
In `views.py`, the slug is generated directly from the problem title:
```python
slug = slugify(title)
```
When a staff user attempts to migrate a Polygon problem whose title is identical to an already migrated problem (e.g., common titles like "Two Sum", "Palindrome", or "Graph Connectivity" across different contests or revisions), `Problem.objects.create(...)` violates the unique constraint, raising an `IntegrityError` (`UNIQUE constraint failed: problems_problem.slug`).

**Impact**:
- The migration process completely halts and rolls back all database changes.
- Staff users cannot migrate valid problems that happen to share titles with existing problems.
- The user is presented with a confusing technical error: `Migration failed and all changes have been rolled back. Reason: UNIQUE constraint failed: problems_problem.slug`.

**Suggested Fix**:
Implement slug collision resolution that ensures uniqueness before saving. If a problem with the same slug already exists for a different Polygon ID, append an incremental suffix or the Polygon ID (e.g., `two-sum-1` or `two-sum-69927`):
```python
base_slug = slugify(title) or f"polygon-{polygon_id}"
slug = base_slug
counter = 1
while Problem.objects.filter(slug=slug).exclude(polygon_id=polygon_id).exists():
    slug = f"{base_slug}-{counter}"
    counter += 1
```

---

### [P3] Stale / Ghost Test Cases Retained on Re-migration (Storage Desynchronization)

**Severity**: High

**Location**: `problems/views.py:472-495`, `problems/views.py:547-580`

**Description**:
When a problem is updated or re-migrated, both sample test cases (`SampleTestCase`) and regular test cases (`ProblemTestCase`) are updated by iterating over the existing test cases:
```python
if idx < len(existing_test_cases):
    ptc = existing_test_cases[idx]
    # update fields
    ptc.save()
else:
    ProblemTestCase.objects.create(...)
```
If test cases were removed from the problem on Polygon (e.g., test suite trimmed from 20 to 12 tests), the code updates the first 12 records, but leaves records `13` through `20` completely untouched in the database.

**Impact**:
- The database retains stale, deleted test cases indefinitely.
- Meanwhile, Azure Blob Storage migration calls `blob_manager.empty_blob(...)` before uploading, resulting in Azure having 12 test cases while the database retains 20 test cases.
- The problem model field `test_case_count` reports 12, but `problem.problem_test_cases.count()` returns 20.
- This discrepancy corrupts grading, causes mismatched test indices, and leads to inconsistent judging results.

**Suggested Fix**:
Clean up obsolete records after the update loop:
```python
if len(existing_test_cases) > len(test_cases):
    for stale_test in existing_test_cases[len(test_cases):]:
        stale_test.delete()
```
Apply the identical deletion logic for `SampleTestCase`.

---

## Code Issues

> Code issues are technical problems: bugs, security vulnerabilities, performance problems, code quality concerns, architectural issues.

### [C1] Missing Database Migrations for `notes` and `genie_chat` Fields (Fatal OperationalError)

**Severity**: Critical

**Location**: `problems/models.py:79-80`, `problems/migrations/`

**Description**:
The fields `notes = models.TextField(...)` and `genie_chat = models.BooleanField(...)` were added to the `Problem` model in `problems/models.py`, and referenced in `problems/views.py` and `problems/admin.py`. However, the corresponding migration was never generated or executed. Any database operation referencing `Problem.objects` crashed immediately with:
```
sqlite3.OperationalError: no such column: problems_problem.notes
django.db.utils.OperationalError: no such column: problems_problem.notes
```

**Impact**:
- System completely broken on initial run: querying any problem or loading the problem interface when a problem exists in the database fails with a 500 error / unhandled exception.
- Staff users could not migrate or view any problem until database schema migration was generated and applied.

**Suggested Fix**:
Run `python manage.py makemigrations problems` to create migration `0002_problem_genie_chat_problem_notes.py` and apply it with `python manage.py migrate`.

---

### [C2] Undefined Method `delete_azure_blob` Called in Error Compensation Handler

**Severity**: High

**Location**: `problems/views.py:588-589`

**Description**:
In `problems/views.py`, the top-level exception handler attempts to roll back Azure Blob Storage changes:
```python
if azure_blob_uploaded and azure_blob_problem_id:
    api.delete_azure_blob(azure_blob_problem_id)
```
However, the `PolygonAPI` class defined in `problems/polygon_api.py` did not implement any method named `delete_azure_blob`. (In `AzureTestcase.py`, the corresponding method is named `empty_blob` on `AzureBlobManager`).

**Impact**:
- If an error occurs after Azure blobs are uploaded (e.g. network failure while fetching problem package, database failure, or invalid tags), the rollback attempt crashes with `AttributeError: 'PolygonAPI' object has no attribute 'delete_azure_blob'`.
- This unhandled `AttributeError` masks the original root exception, breaks error reporting, and leaves dangling uploaded test cases in Azure without proper rollback.

**Suggested Fix**:
Implement `delete_azure_blob(self, db_problem_id)` on `PolygonAPI` using `AzureBlobManager.empty_blob`, properly checking configuration settings and safely catching any cleanup errors.

---

### [C3] Redundant N+1 Synchronous HTTP Requests & Blocking Redis Timeouts Causing 429 Rate Limiting

**Severity**: High

**Location**: `problems/polygon_api.py:351-407, 888-942`, `problems/views.py:277-292, 456-465, 535-545`

**Description**:
`PolygonAPI.get_all_test_cases()` makes two synchronous, sequential HTTP requests per test case (one for `problem.testInput` and one for `problem.testAnswer`). For a problem with 50 test cases, this requires 101 synchronous roundtrips to Polygon.
Furthermore, in `views.py`, when a form was submitted, test cases were fetched once at the top of `index()`, and then if `migrate_to_db` or `migrate_test_cases_to_db` was active, `api.get_test_cases_from_redis()` failed when Redis was offline, causing `api.get_all_test_cases()` to be called a second (and even third) time in the same HTTP request.
Additionally, Redis connection calls had no connection timeout, each hanging for ~4 seconds waiting for connection timeout when Redis was not running locally.

**Impact**:
- Repeatedly hammering Polygon API within seconds triggers HTTP 429 (`Too Many Requests`), aborting the migration.
- Requests took up to 3-4 minutes to complete, risking HTTP gateway timeouts (504 Gateway Timeout) on production servers.

**Suggested Fix**:
1. In `views.py`, reuse the in-memory `all_test_cases` variable already fetched earlier in the view rather than calling `get_test_cases_from_redis()` or `get_all_test_cases()` repeatedly in the same request.
2. Configure Redis client with a short socket timeout (`socket_connect_timeout=0.5, socket_timeout=0.5`) so absent Redis instances do not delay execution.
3. Cache test cases in local memory or extract test inputs directly from the downloaded package archive.

---

## Edge Case Analysis

### Q1

> A Polygon problem has 0 sample test cases but 15 regular test cases. What happens when you migrate this problem?

**Answer**:
1. **Problem Statement & Metadata**: The problem record itself is saved successfully in the `Problem` table with `test_case_count = 15`.
2. **Sample Test Cases (`SampleTestCase`)**:
   - In `views.py:470`, `sample_tests = [test for test in test_cases if test.get('is_sample', False)]` evaluates to an empty list `[]`.
   - The loop `for idx, test in enumerate(sample_tests):` does not execute.
   - Zero rows are created in `SampleTestCase`.
   - *Bug in original code*: If the problem had previously been migrated with sample test cases and the setter removed them on Polygon, the old records in `SampleTestCase` were not deleted and remained stale. With our fix, any preexisting sample test cases are deleted.
3. **Regular Test Cases (`ProblemTestCase`)**:
   - When "Migrate Test Description to Database" is executed, all 15 test cases are inserted into `ProblemTestCase` with `is_sample=False`.
4. **User Interface Impact**:
   - In the frontend problem preview table, all 15 test cases display `No` under the "Sample Test Case" column.
   - Any external platform (such as Algopath) rendering the problem description will display no sample test examples to students, because no sample test case records exist.

---

### Q2

> A problem is migrated with 20 test cases. Later, the problem setter removes 8 test cases on Polygon (now 12 remain). The problem is re-migrated. What happens?

**Answer**:
1. **In the Original Code**:
   - In `views.py:547`, `existing_test_cases = list(ProblemTestCase.objects.filter(problem=problem_obj).order_by('order'))` loads all 20 existing records.
   - The loop runs for `idx` from `0` to `11` (the 12 new test cases). Indices 0 through 11 are updated with the new test data.
   - Indices 12 through 19 (the remaining 8 obsolete test cases) are **never deleted**.
   - As a result, the database retains all 20 test cases: 12 updated ones and 8 ghost test cases that no longer exist on Polygon.
   - In Azure Blob Storage, `blob_manager.empty_blob()` clears the entire prefix before uploading, leaving only 12 test cases in Azure.
   - Consequently, Azure has 12 test cases, `Problem.test_case_count` says 12, but `ProblemTestCase.objects.filter(problem=problem_obj).count()` returns 20. This creates total desynchronization between storage, the database, and the judge.
2. **With Our Fix**:
   - After the loop updates the first 12 records, the code checks `if len(existing_test_cases) > len(test_cases):` and deletes the remaining 8 stale records (`existing_test_cases[12:]`).
   - The database, Azure, and model metadata remain in sync with 12 test cases.

---

### Q3

> Two different Polygon problems have the exact same title: "Two Sum". You migrate the first one successfully. Then you try to migrate the second one. What happens?

**Answer**:
1. **In the Original Code**:
   - When the first problem (Polygon ID A) is migrated, `slugify("Two Sum")` yields `"two-sum"`. It saves cleanly in `Problem` where `slug` has `unique=True`.
   - When the second problem (Polygon ID B) is migrated, `slugify("Two Sum")` also produces `"two-sum"`.
   - In `views.py:399`, `Problem.objects.create(polygon_id=polygon_id, title=title, slug="two-sum", ...)` attempts to insert the duplicate slug into the database.
   - The database throws an `IntegrityError` (`UNIQUE constraint failed: problems_problem.slug`).
   - The atomic transaction rolls back all changes, and the user receives an error banner stating migration failed. Problem B cannot be migrated.
2. **With Our Fix**:
   - Slugs are verified against existing database entries excluding the current Polygon ID. If `"two-sum"` already belongs to another problem, it is automatically disambiguated to `"two-sum-1"`, `"two-sum-2"`, etc.
   - Both problems are successfully saved with distinct, unique URLs.

---

### Q4

> When test cases are saved to the database via "Migrate Test Cases to DB", some data is intentionally discarded. What data is lost? Why might this cause problems?

**Answer**:
1. **What Data is Lost**:
   - **Data Beyond 260 Bytes**: `truncated_input = input_data[:260]` and `truncated_output = output_data[:260]` deliberately discard all bytes/characters after index 260 for both input and output.
   - **Trailing Whitespace**: `input_data = test.get('input', '').rstrip()` strips trailing newlines and spaces.
   - **Empty or Whitespace-Only Test Cases**: `if input_data and output_data:` completely discards test cases where either the input or the expected output is empty.
2. **Why This Causes Problems**:
   - **Truncation Breaks Execution & Validation**: Most competitive programming problems feature inputs larger than 260 characters (e.g. arrays with thousands of integers, graph edge lists, strings). Code run against truncated inputs crashes with `EOFError`, JSON parse errors, or produces incorrect calculations.
   - **Judging False Verdicts**: Expected answers larger than 260 characters cannot be matched against student solutions, causing valid submissions to be marked as Wrong Answer.
   - **Loss of Edge Case Tests**: In many problems (e.g. printing empty output for empty collections, or problems with no input), an empty string is the exact expected answer. Discarding these test cases removes critical edge case testing.
   - **Whitespace-Sensitive Checkers**: In problems evaluated with strict token or line checkers (like `fcmp` or `wcmp`), stripping trailing newlines/spaces alters the checker's evaluation.

---

## Severity Guidelines

Use these definitions when assigning severity:

| Severity | Definition | Examples |
|----------|------------|----------|
| **Critical** | System broken, security vulnerability, data loss | SQL injection, authentication bypass, data corruption |
| **High** | Major functionality broken, significant data integrity risk | Feature doesn't work, orphaned records, race conditions |
| **Medium** | Feature partially broken, poor UX, code maintainability | Missing validation, confusing errors, code duplication |
| **Low** | Minor issues, cosmetic, best practice violations | Unused imports, inconsistent formatting, missing logs |

---

## Notes

- **Migration State Fixed**: Generated migration `0002_problem_genie_chat_problem_notes.py` in the `problems` app and applied it via `manage.py migrate`.
- **Authentication Improvements**: Enhanced `users/backends.py` with case-insensitive email authentication (`email__iexact`) and fixed `users/views.py` so authenticated staff users visiting `/users/login/` are not involuntarily logged out and `next` redirection parameters are respected.
- **Destructive Action Protections**: Added JavaScript confirmation dialogs (`confirm(...)`) on the "Migrate Test Cases to Azure" and "Migrate Test Description to Database" actions in `problems/templates/problems/index.html`.
- **Test Suite**: Added 11 automated unit and integration tests across `problems/tests.py` and `users/tests.py` verifying all edge cases, authentication, and migrations. All 11 tests pass with 100% success.
