# Requirements Document

## Introduction

The `math-ai-graduation-project` engine currently represents each Korean SAT (수능) math problem as a monolithic image plus a handful of monolithic text fields (`raw_text`, `raw_ocr_text`, `latex_text`). In reality a single problem mixes several distinct region types: a shared passage (지문), question text, a `<보기>` statement box (ㄱ/ㄴ/ㄷ), answer choices (①~⑤), and diagram/graph images. The monolithic structure prevents passage sharing, per-item handling, diagram-only queries, and per-region confidence or re-processing. The OCR, LaTeX, and Vision-classifier services are also stubs that return fixed values and never call a real AI model.

This feature introduces (A) a Claude Vision–backed service that decomposes a single problem image into typed regions and extracts OCR + LaTeX text and labeled items in a single structured call, and (B) a relational schema (`passages`, `problem_regions`, `problem_region_items`, plus a `problems.passage_id` foreign key) that stores a problem as an ordered set of regions while preserving the existing monolithic fields as an assembled cache for backward compatibility.

The scope is limited to region decomposition, the new schema, Claude Vision integration, and their tests. Out-of-scope stub services (classification, generation, verification) must not be modified.

## Glossary

- **Region_Extraction_Service**: New service (e.g., `ProblemRegionExtractionService`) responsible for decomposing a problem image into typed regions and extracting their contents. Source of truth for regions.
- **Claude_Vision_Client**: Component that calls the Anthropic Claude vision-capable model via the official `anthropic` Python SDK and returns structured JSON.
- **Region_Type**: One of `QUESTION_TEXT`, `DIAGRAM`, `CHOICE_BOX`, `STATEMENT_BOX`, `TABLE`, `OTHER`.
- **Text_Region**: A region whose `Region_Type` is one of `QUESTION_TEXT`, `CHOICE_BOX`, `STATEMENT_BOX`, or `TABLE`. Subject to OCR + LaTeX extraction.
- **Diagram_Region**: A region whose `Region_Type` is `DIAGRAM`. Cropped and stored as an image, never OCR'd.
- **Labeled_Item**: An individual entry inside a `CHOICE_BOX` or `STATEMENT_BOX`, carrying a label such as "①" or "ㄱ", stored in `problem_region_items`.
- **Passage**: Shared reading material (지문) that one or more problems reference, stored in the `passages` table.
- **Bounding_Box**: A JSON object `{x, y, width, height}` describing a region's location relative to the full problem image.
- **Assembled_Cache**: The existing `problems.raw_text` / `raw_ocr_text` / `latex_text` fields, repopulated by assembling region contents, retained for API compatibility.
- **Create_Tables_Registry**: The manually maintained model list inside `create_tables()` in `app/core/database.py`.
- **PDF_Import_Pipeline**: The existing upstream ingestion flow that imports PDFs and produces problem images.
- **Schema_Migration_Strategy**: The chosen approach for applying the schema change, either (a) dropping and recreating the local dev DB via `create_tables()`, or (b) initializing Alembic and writing the change as the first migration.

## Requirements

### Requirement 1: Region Detection via Claude Vision

**User Story:** As a data pipeline engineer, I want a problem image decomposed into typed regions with locations, so that each part of a problem can be handled according to its kind.

#### Acceptance Criteria

1. WHEN a problem image path is provided, THE Region_Extraction_Service SHALL invoke the Claude_Vision_Client to detect all regions within the image within 60 seconds.
2. IF the provided problem image path does not reference a readable image file, THEN THE Region_Extraction_Service SHALL abort region detection, return an error result indicating the image could not be loaded, and produce no regions.
3. IF the Claude_Vision_Client does not return a successful response within 60 seconds or returns an unparseable response, THEN THE Region_Extraction_Service SHALL abort region detection, return an error result indicating the detection failure, and produce no partial regions.
4. WHEN region detection completes successfully, THE Region_Extraction_Service SHALL assign each detected region exactly one Region_Type from the set {QUESTION_TEXT, DIAGRAM, CHOICE_BOX, STATEMENT_BOX, TABLE, OTHER}.
5. WHEN region detection completes successfully, THE Region_Extraction_Service SHALL record a Bounding_Box for each detected region as four values (left, top, right, bottom) expressed in pixels relative to the top-left origin of the full problem image, where 0 ≤ left < right ≤ image width and 0 ≤ top < bottom ≤ image height.
6. WHEN region detection completes successfully, THE Region_Extraction_Service SHALL assign each region an integer order_index that is unique, contiguous starting at 0, and ordered by ascending Bounding_Box top value so that a smaller order_index corresponds to a higher position in the image.
7. IF two or more detected regions share the same Bounding_Box top value, THEN THE Region_Extraction_Service SHALL order those regions by ascending Bounding_Box left value when assigning order_index.
8. WHEN region detection completes successfully and no regions are found, THE Region_Extraction_Service SHALL return an empty region collection without raising an error.

### Requirement 2: Text Region OCR and LaTeX Extraction

**User Story:** As a content reviewer, I want text regions transcribed with math converted to LaTeX, so that problem text is machine-readable and editable per region.

#### Acceptance Criteria

1. WHEN a detected region is a Text_Region, THE Region_Extraction_Service SHALL extract the region text within 30 seconds and store it in the region `ocr_text` field.
2. WHEN a Text_Region contains mathematical expressions, THE Region_Extraction_Service SHALL convert each mathematical expression to LaTeX and store the mixed text with math delimited by `$...$` in the region `latex_text` field.
3. WHEN a Text_Region contains no mathematical expression, THE Region_Extraction_Service SHALL store the plain extracted text in the region `latex_text` field with no `$...$` delimiters added.
4. WHERE the Claude_Vision_Client returns a confidence value for a region, THE Region_Extraction_Service SHALL store that value, constrained to the inclusive range 0.0 to 1.0, in the region `confidence` field.
5. WHERE the Claude_Vision_Client returns no confidence value for a region, THE Region_Extraction_Service SHALL leave the region `confidence` field unset (null).
6. IF text extraction for a Text_Region fails or returns an empty result, THEN THE Region_Extraction_Service SHALL leave the region `ocr_text` and `latex_text` fields unset (null) and produce an error indication identifying the affected region without terminating processing of remaining regions.

### Requirement 3: Diagram Region Cropping

**User Story:** As a data pipeline engineer, I want diagram regions preserved as images, so that figures and graphs remain intact rather than being mistranscribed.

#### Acceptance Criteria

1. WHEN a detected region is a Diagram_Region, THE Region_Extraction_Service SHALL skip OCR and LaTeX extraction for that region.
2. WHEN a detected region is a Diagram_Region, THE Region_Extraction_Service SHALL crop the region from the original problem image using the region Bounding_Box and save the crop to a separate image file.
3. WHEN a Diagram_Region crop is saved, THE Region_Extraction_Service SHALL store the saved file path in the region `image_path` field.
4. IF the region Bounding_Box extends beyond the boundaries of the original problem image, THEN THE Region_Extraction_Service SHALL clamp the Bounding_Box coordinates to the image boundaries before cropping.
5. IF the region Bounding_Box is invalid, defined as having a width or height less than 1 pixel or a non-positive area after clamping to the image boundaries, THEN THE Region_Extraction_Service SHALL skip the crop operation, leave the region `image_path` field empty, and produce an error indication identifying the affected region.
6. IF saving the Diagram_Region crop to an image file fails, THEN THE Region_Extraction_Service SHALL leave the region `image_path` field empty and produce an error indication identifying the affected region without terminating processing of remaining regions.

### Requirement 4: Labeled Item Structuring

**User Story:** As a content reviewer, I want choices and statement items stored individually with labels, so that a single choice or statement can be edited, graded, or referenced on its own.

#### Acceptance Criteria

1. WHEN a region is classified as CHOICE_BOX, THE Region_Extraction_Service SHALL structure each inner choice into a separate Labeled_Item with its label preserved exactly as it appears in the source (for example "①" through "⑤"), supporting between 1 and 10 choices per region.
2. WHEN a region is classified as STATEMENT_BOX, THE Region_Extraction_Service SHALL structure each inner statement into a separate Labeled_Item with its label preserved exactly as it appears in the source (for example "ㄱ", "ㄴ", "ㄷ"), supporting between 1 and 10 statements per region.
3. WHEN Labeled_Items are created for a region, THE Region_Extraction_Service SHALL assign a zero-based, contiguous integer order_index to each Labeled_Item that reflects the original reading order (top-to-bottom, then left-to-right), with no duplicate and no skipped values.
4. WHEN a Labeled_Item contains text, THE Region_Extraction_Service SHALL store the extracted text in the Labeled_Item `text` field and store any mathematical expressions converted to LaTeX in the `latex` field.
5. IF a Labeled_Item contains text but no mathematical expression is present, THEN THE Region_Extraction_Service SHALL store the extracted text in the `text` field and leave the `latex` field empty.
6. WHERE a Labeled_Item is itself an image rather than text, THE Region_Extraction_Service SHALL store the item crop path in the Labeled_Item `image_path` field and leave the `text` and `latex` fields empty.
7. IF no inner label can be detected within a CHOICE_BOX or STATEMENT_BOX region, THEN THE Region_Extraction_Service SHALL create no Labeled_Items for that region and produce an error indication reporting that no labeled items were detected, while preserving the original region record.

### Requirement 5: Passage Reuse

**User Story:** As a cost-conscious operator, I want a shared passage stored once and reused, so that duplicate OCR calls are avoided when several problems share the same passage.

#### Acceptance Criteria

1. WHEN a passage is detected for a problem, THE Region_Extraction_Service SHALL search for an existing Passage record having the same source_pdf_id, the same page_number, and a crop_box whose four coordinate values each differ from the detected passage crop_box by no more than 5 pixels.
2. IF a matching Passage record exists, THEN THE Region_Extraction_Service SHALL reference the existing Passage record and SHALL NOT invoke OCR for that passage.
3. IF no matching Passage record exists, THEN THE Region_Extraction_Service SHALL create exactly one new Passage record populated with its passage_image_path, crop_box, ocr_text, and latex_text.
4. WHEN a problem references a passage, THE Region_Extraction_Service SHALL set the `problems.passage_id` foreign key to the referenced Passage record identifier.
5. IF OCR fails while creating a new Passage record, THEN THE Region_Extraction_Service SHALL not persist a Passage record, SHALL leave `problems.passage_id` unset, and SHALL return an error indication identifying the failed passage.
6. IF two or more problems on the same source_pdf_id and page_number are detected with matching crop_boxes as defined in criterion 1, THEN THE Region_Extraction_Service SHALL create only one Passage record and SHALL set the `problems.passage_id` of each such problem to that single record.

### Requirement 6: Safe Fallback When API Key Is Absent

**User Story:** As a developer running the project locally, I want the system to keep working without a Claude API key, so that the pipeline still runs during development and testing.

#### Acceptance Criteria

1. IF neither the ANTHROPIC_API_KEY nor the CLAUDE_API_KEY environment variable is set to a non-empty value at the time a region extraction request is received, THEN THE Region_Extraction_Service SHALL complete the request using the existing stub behavior and return a successful response without raising an exception.
2. WHERE the CLAUDE_API_KEY environment variable is set to a non-empty value and the ANTHROPIC_API_KEY environment variable is not set to a non-empty value, THE Configuration SHALL use the CLAUDE_API_KEY value as the Claude credential.
3. WHERE both the ANTHROPIC_API_KEY and the CLAUDE_API_KEY environment variables are set to non-empty values, THE Configuration SHALL use the ANTHROPIC_API_KEY value as the Claude credential.
4. WHEN the Region_Extraction_Service falls back to stub behavior because no non-empty Claude credential was found, THE Region_Extraction_Service SHALL emit a single log entry at warning level indicating that the Claude credential was not found.

### Requirement 7: Resilient Handling of API Failures

**User Story:** As a pipeline operator, I want a failed Claude call to be contained, so that one problem image failure does not abort an entire PDF import.

#### Acceptance Criteria

1. IF a Claude_Vision_Client call fails with a timeout, a 429 response, or a 5xx response, THEN THE Region_Extraction_Service SHALL record a log entry containing the failure type (timeout, rate-limited, or server-error) and the identifier of the problem image being processed.
2. IF a Claude_Vision_Client call fails with a timeout, a 429 response, or a 5xx response, THEN THE Region_Extraction_Service SHALL retry the call at most 2 times before giving up, applying a wait of at least 1 second and at most 30 seconds before each retry.
3. IF all retries for a problem image are exhausted, THEN THE Region_Extraction_Service SHALL mark that problem image with a failed status and return control to the PDF_Import_Pipeline without raising an error that halts the pipeline.
4. WHEN the Region_Extraction_Service returns control after exhausting all retries for one problem image, THE PDF_Import_Pipeline SHALL continue processing every remaining unprocessed problem image in the same PDF import.
5. THE Region_Extraction_Service SHALL issue at most 1 Claude_Vision_Client call per problem image under normal (non-retry) operation.

### Requirement 8: Backward-Compatible Service Interfaces

**User Story:** As a maintainer, I want existing service interfaces preserved, so that current callers keep working while new capability is added.

#### Acceptance Criteria

1. THE Region_Extraction_Service SHALL be introduced as a new service that does not remove, rename, or modify the existing OCRServiceInterface, LaTeXServiceInterface, or CropClassifier definitions.
2. WHERE the OCRServiceInterface, LaTeXServiceInterface, or CropClassifier interfaces are extended with new methods, THE extension SHALL preserve every existing method's name, parameter list, parameter order, and return type unchanged.
3. IF an extension to the OCRServiceInterface, LaTeXServiceInterface, or CropClassifier interfaces adds a new method, THEN THE extension SHALL provide that method with a default or optional behavior such that existing callers invoking only the original methods continue to execute without modification.
4. THE classification_service, generation_service, and verification_service modules SHALL retain their existing method signatures and observable behavior unchanged by this feature.
5. IF a caller invokes any existing method of the OCRServiceInterface, LaTeXServiceInterface, or CropClassifier interfaces using the original signature, THEN THE System SHALL return a result equivalent in type and structure to the result produced before this feature was introduced.

### Requirement 9: New Persistence Models

**User Story:** As a maintainer, I want the new tables created reliably, so that region data has a durable home consistent with the existing schema.

#### Acceptance Criteria

1. THE Data_Model SHALL define a `passages` table with fields id (primary key), source_pdf_id (foreign key referencing `source_pdfs.id`), page_number, passage_image_path, crop_box (JSON), ocr_text, latex_text, created_at, and updated_at.
2. IF a `passages` record is inserted or updated with a null value in any of the fields id, source_pdf_id, page_number, or passage_image_path, THEN THE Data_Model SHALL reject the operation and preserve the prior stored state, while permitting null values in crop_box, ocr_text, and latex_text.
3. THE Data_Model SHALL define a `problem_regions` table with fields id (primary key), problem_id (foreign key referencing `problems.id`), region_type, order_index, image_path, bounding_box (JSON), ocr_text (nullable), latex_text (nullable), confidence (nullable float), created_at, and updated_at.
4. THE Data_Model SHALL define a `problem_region_items` table with fields id (primary key), region_id (foreign key referencing `problem_regions.id`), label, order_index, text (nullable), latex (nullable), image_path (nullable), created_at, and updated_at.
5. THE Data_Model SHALL add a nullable `passage_id` foreign key referencing `passages.id` to the existing `problems` table.
6. WHEN a new model is added to the codebase, THE Create_Tables_Registry SHALL include that model in its table list such that a subsequent invocation of `create_tables()` creates the corresponding table.
7. IF `create_tables()` is invoked and any of the tables `passages`, `problem_regions`, or `problem_region_items` cannot be created, THEN THE feature SHALL halt the operation and produce an error indication identifying the failing table, without leaving a partially created target table in place.
8. THE Base declarative class SHALL remain defined in `app/core/db_base.py`, and all of the models `passages`, `problem_regions`, and `problem_region_items` SHALL inherit from that Base declarative class.
9. WHERE the Schema_Migration_Strategy requires applying the `problems.passage_id` column to an existing database, THE feature SHALL apply exactly one of the following two strategies: recreating the local development database via `create_tables()`, or initializing Alembic and writing the change as the first migration, such that after application the `problems` table contains the nullable `passage_id` column and all existing `problems` rows have `passage_id` set to null.

### Requirement 10: Consistent Image Path Convention

**User Story:** As a maintainer, I want region and item images stored under a predictable path, so that files stay organized alongside existing problem uploads.

#### Acceptance Criteria

1. WHEN a region image is saved, THE Region_Extraction_Service SHALL store it at the path `uploads/problems/{source_pdf_id}/{problem_id}/regions/{region_id}.png`, where source_pdf_id, problem_id, and region_id are non-empty identifiers of the associated source PDF, problem, and region.
2. WHEN a Labeled_Item image is saved, THE Region_Extraction_Service SHALL store it at the path `uploads/problems/{source_pdf_id}/{problem_id}/items/{item_id}.png`, where source_pdf_id, problem_id, and item_id are non-empty identifiers of the associated source PDF, problem, and labeled item.
3. IF any required identifier (source_pdf_id, problem_id, region_id, or item_id) is missing or empty when constructing an image storage path, THEN THE Region_Extraction_Service SHALL abort the save operation without writing any file and return an error indicating the missing identifier.
4. IF a file already exists at the target storage path when saving a region or Labeled_Item image, THEN THE Region_Extraction_Service SHALL overwrite the existing file and retain only the most recently saved image at that path.

### Requirement 11: Assembled Cache Preservation

**User Story:** As an API consumer, I want existing problem text fields to keep working, so that current clients and downstream pipelines are unaffected.

#### Acceptance Criteria

1. THE feature SHALL retain the existing `problems.raw_text`, `problems.raw_ocr_text`, and `problems.latex_text` fields with their existing data types and existing values unchanged.
2. WHEN regions for a problem are extracted, THE Region_Extraction_Service SHALL populate the Assembled_Cache by concatenating the region contents in ascending order_index order.
3. THE `problem_regions` and `problem_region_items` tables SHALL be treated as the source of truth for region content, and the Assembled_Cache SHALL be treated as a derived cache.
4. IF two or more regions for the same problem share an identical order_index value, THEN THE Region_Extraction_Service SHALL assemble those regions in ascending region identifier order and SHALL complete assembly without error.
5. IF the Assembled_Cache population fails during region extraction, THEN THE Region_Extraction_Service SHALL retain the existing values of `problems.raw_text`, `problems.raw_ocr_text`, and `problems.latex_text` unchanged and SHALL return an error response indicating that cache assembly failed.
6. WHEN no regions exist for a problem, THE Region_Extraction_Service SHALL populate the Assembled_Cache with an empty value and SHALL complete without error.

### Requirement 12: Region Retrieval API

**User Story:** As an API consumer, I want to retrieve a problem's regions and items, so that a client can display or edit the decomposed structure.

#### Acceptance Criteria

1. WHEN a client requests a problem's regions, THE Problem_API SHALL return the list of regions for that problem sorted by ascending order_index, each including its Labeled_Items, following existing routing conventions (a dedicated `GET /api/problems/{id}/regions` endpoint or nested fields on the problem response).
2. WHERE the problem response schema exposes regions, THE Problem_Schema SHALL include for each region its region type, order_index, ocr_text, latex_text, image path, and any Labeled_Items.
3. WHERE a region or Labeled_Item field has no value, THE Problem_Schema SHALL represent that field with an explicit null rather than omitting the field.
4. IF a client requests regions for a problem identifier that does not exist, THEN THE Problem_API SHALL return a not-found response and no region data.
5. WHEN a client requests regions for an existing problem that has no regions, THE Problem_API SHALL return a successful response with an empty region list.

### Requirement 13: Claude Vision Configuration

**User Story:** As an operator, I want the Claude credential and model configurable, so that keys are managed safely and the model can be changed without code edits.

#### Acceptance Criteria

1. THE Configuration SHALL expose an ANTHROPIC_API_KEY property in `app/core/config.py` that reads its value from an environment variable of the same name, following the existing OPENAI_API_KEY property pattern, and SHALL default to an unset (null/None) value when the environment variable is not present.
2. WHERE a CLAUDE_API_KEY environment variable is set and ANTHROPIC_API_KEY is not set, THE Configuration SHALL resolve the Claude credential from CLAUDE_API_KEY; WHERE both are set, THE Configuration SHALL use ANTHROPIC_API_KEY.
3. THE Configuration SHALL expose the Claude vision model name as a property in `app/core/config.py` that reads from an environment variable, and SHALL return a non-empty vision-capable model name as its default value when the environment variable is not set.
4. IF a Claude vision request is attempted while no Claude credential (neither ANTHROPIC_API_KEY nor CLAUDE_API_KEY) is configured, THEN THE feature SHALL reject the request and return an error indicating that the Claude credential is missing, without transmitting any request to the external service.
5. THE feature SHALL add the `anthropic` SDK dependency to `requirements.txt` with a pinned version specifier (exact or minimum version, not an unbounded entry).
6. THE feature SHALL document the ANTHROPIC_API_KEY variable and the optional CLAUDE_API_KEY variable in `.env.example`, each with a placeholder value and no real credential.

### Requirement 14: Single-Call Structured Extraction

**User Story:** As a cost-conscious operator, I want region detection, OCR, and item parsing returned together, so that per-problem API call count stays low.

#### Acceptance Criteria

1. WHEN the Region_Extraction_Service processes a single problem image, THE Region_Extraction_Service SHALL request region detection, text/LaTeX extraction, and Labeled_Item parsing within exactly one Claude_Vision_Client call that returns a single structured JSON output.
2. THE Region_Extraction_Service SHALL issue no more than 1 Claude_Vision_Client call per problem image for the combined region detection, text/LaTeX extraction, and Labeled_Item parsing task.
3. THE feature SHALL place the Claude Vision prompt template in `app/prompts/` as a separate file consistent with the existing prompt module style.
4. WHEN the Claude_Vision_Client returns output conforming to the expected JSON structure, THE Region_Extraction_Service SHALL persist the extracted regions, text/LaTeX content, and Labeled_Item entries as a single unit.
5. IF the Claude_Vision_Client returns output that does not conform to the expected JSON structure, THEN THE Region_Extraction_Service SHALL log the malformed output, return a failure result indicating malformed extraction output, and persist no partial data from that call.
6. IF the Claude_Vision_Client does not return a response within 60 seconds, THEN THE Region_Extraction_Service SHALL abort the call, log a timeout condition, and persist no partial data from that call.

### Requirement 15: Test Coverage Without Live Network Calls

**User Story:** As a maintainer, I want tests that mock the Claude API, so that the suite passes offline and existing tests keep passing.

#### Acceptance Criteria

1. THE feature SHALL add unit tests under the `tests/` directory covering the new models and the Region_Extraction_Service, achieving a minimum statement coverage of 80% for each of those components.
2. WHEN the test suite runs, THE feature SHALL replace all Claude_Vision_Client calls with mock objects such that zero outbound network requests are made during the entire run.
3. IF any test causes the Claude_Vision_Client to attempt a real network request, THEN THE feature SHALL fail that test with an error indicating that an unmocked network call was detected.
4. WHEN the full test suite runs, THE feature SHALL execute all pre-existing tests together with the newly added tests, and all executed tests SHALL report a passing result with zero failures and zero errors.
5. WHEN the full test suite runs with no network connectivity available, THE feature SHALL complete execution and report the same pass/fail results as a run with network connectivity available.

### Requirement 16: Documentation Update

**User Story:** As a future contributor, I want the project docs updated, so that the implemented behavior and remaining limits are recorded.

#### Acceptance Criteria

1. WHEN the feature implementation is completed, THE feature SHALL update `CLAUDE.md` to include a section describing the implemented region decomposition behavior, covering the input consumed, the decomposition output produced, and the ordering of decomposed regions.
2. WHEN the feature implementation is completed, THE feature SHALL update `CLAUDE.md` to document each schema addition, recording for every added field its name, data type, and whether it is required or optional.
3. WHEN the feature implementation is completed, THE feature SHALL record in `CLAUDE.md` a list of remaining known limitations, where each entry states the limitation and its observable effect on system behavior (for example, simplified passage deduplication that retains near-duplicate passages).
4. IF the feature implementation is completed but region decomposition behavior, schema additions, or known limitations are not all present in `CLAUDE.md`, THEN THE feature SHALL treat the documentation update as incomplete and indicate which of the three sections are missing.
