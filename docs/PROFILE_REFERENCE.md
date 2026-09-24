# Profile reference

[README](../README.md) | [Architecture](ARCHITECTURE.md)

Profiles are UTF-8 YAML mappings read by [ProfileLoader](../core/config.py). Duplicate keys, including nested duplicates, raise a configuration `ValueError` (`InvalidProfileError` is an alias). Validation/quality expansion precede client construction and network access. Runner construction can initialize the local cache first.

Unknown top-level keys are preserved but do not become supported features. Do not rely on them to configure authentication, retries, output directories or transformations.

## Top-level keys

Every supported key below affects the completion fingerprint when present. Quality expansion supplies its defaults before fingerprinting. Omitted and explicit runtime defaults can still have different identities.

| Key | Required / expected type | Default / accepted values | Validation and behavior |
|---|---|---|---|
| `site_name` | Required; string | No default | Loader checks presence only. Supply a meaningful non-empty string; runner derives output stem from it. |
| `engine` | Required; string | `static`, `browser` | Exact values; select Requests or Playwright. |
| `start_url` | Required; string | No default | Must start with lowercase http:// or https://; not full URL/host validation. |
| `fields` | Required; mapping | Output names to selectors/definitions | Names must be non-empty strings, not beginning with underscore. Order preserved. An empty mapping is not explicitly rejected; configure fields for meaningful extraction. |
| `record_selector` | Optional; string | Omitted: legacy inference | Present values must contain a non-whitespace character. Null, empty and non-string values fail. Content preserved; CSS syntax checked at parse time. |
| `max_pages` | Optional; integer expected | `1` | Logical page limit. No loader type/range check; use a positive integer. |
| `delay` | Optional; numeric seconds expected | `0` | Runtime float conversion; positive values sleep between pages, not before first. No loader type/range check; use non-negative finite seconds. Separate from retry waits. |
| `pagination` | Optional; mapping expected | Empty mapping | `next_button` is a CSS selector string for an element with href. No nested loader validation. Missing/empty selector disables pagination. |
| `wait_for` | Optional; string or null | Omitted/null: no wait | Non-null values must be non-empty strings. Browser waits after successful navigation/status check; static ignores it. No loader CSS syntax check. |
| `data_quality` | Optional; boolean | `false` | Must be boolean; exactly true enables quality. |
| `unique_key` | Optional; list of output names | `[]` | Requires quality enabled. Every name must be a string referencing a configured field. Order preserved; empty disables deduplication. |
| `duplicate_policy` | Optional; string | `keep_first` | Requires quality enabled; only keep_first or report_only. |
| `include_provenance` | Optional; boolean | `false` | Requires quality enabled; passes existing source metadata to clean records, does not generate it. |

Even an empty unique_key or explicitly false include_provenance requires `data_quality: true`. Quoted boolean strings are not booleans.

Entire fields and pagination mappings participate in fingerprinting. Unknown behavior-neutral metadata does not. The inert top-level names `transform`, `transformation` and `transformations` are conservatively fingerprinted but **do not configure transformations**. There are no supported profile keys for retry policy, headers, cookies or credentials.

## Output and cache controls

Output paths are not YAML settings. CLI uses `data/` relative to the working directory; `ScrapeRunner.run(..., output_dir=...)` supplies the programmatic destination. The runner lowercases alphanumeric characters in site_name, replaces other characters with spaces and joins words with underscores. Books to Scrape becomes `books_to_scrape.csv`, `.json` and `.xlsx`.

Quality adds `.quality.json` and `.rejected.json` beside them. Canonical resolved CSV destination participates in identity. Matching completed reruns skip only with all required files regular and non-empty. Changed profile/destination or incomplete files cause a full rebuild.

`--clear-cache` is a CLI flag, not a profile key. It clears all legacy URL and completion rows in the shared database, without deleting outputs. Disabled-quality runs leave existing audit sidecars untouched; those files are not evidence for that disabled run.

## Field definitions

Each mapping key is the output name. There is no separate output/name/source property or output-alias syntax.

Simple selector strings work in either mode. Quality expands them to selector plus `required: false` and `type: string`. Extended mappings require quality and accept exactly:

| Property | Required / type | Default / accepted values | Validation |
|---|---|---|---|
| `selector` | Required; string | No default | Non-empty after whitespace check; exactly one YAML key, no source alternative. |
| `required` | Optional; boolean | false | Non-booleans rejected. Determines record rejection for missing/null/conversion failure. |
| `type` | Optional; string | string | Exact values: string, int, float, bool, URL, date. |
| `format` | Optional; string | Absent | Allowed only for date; non-empty. Format directives are interpreted during conversion, not loader validation. |

All these properties influence the fingerprint. Unknown properties fail validation. Output names starting with underscore are reserved, including `_source_url` and `_page`.

## Selector and container behavior

Fields use CSS plus `::text` or `::attr(attribute_name)`. Bare CSS alone is unsupported. Loader checks non-emptiness; unsupported extraction suffixes and malformed CSS fail when parsed.

- `h2::text`: first matching element's text, including descendants. Fragments are space-joined, stripped and repeated whitespace collapsed.
- `a.details::attr(href)`: first match's attribute. Values stripped; list attributes such as class space-joined. Non-empty href/src values resolve against the current page URL.
- Missing element/attribute: `""` at parser stage, not null.
- Explicit containers: one record each in document order, fields in configured order, including all-missing records. Zero matches returns `[]`, without global fallback.
- Outside matches do not fill another container's missing fields. Nested matched containers each produce records; outer containers may find fields in nested descendants.
- Each field uses only its first match.

**Container self:** a field selects the container only when its CSS portion exactly equals record_selector. With `record_selector: a.card`, `a.card::attr(href)` reads its own href and `a.card::text` includes descendant text. `a::attr(href)` searches descendants, not the container. There is no special self alias, automatic fallback or added `:scope` semantics. Other CSS goes intact to the underlying library; equivalent selector strings are not canonicalized.

Without record_selector, legacy inference finds a common CSS prefix or common ancestor of the first field matches and makes prefixed fields relative to it. Missing first matches can prevent inference. It does not promise explicit mode's zero-match/all-missing behavior. All three bundled profiles retain inference.

Pagination selects next_button from the whole page, following its href relative to the current URL. It does not click JS-only buttons, load more or scroll infinitely. Browser mode supplies rendered HTML to the same paginator.

## Transformation before quality

The transformer always runs before quality, using output-name conventions:

| Name | Transformation |
|---|---|
| `price` | Strip supported pound-currency prefix, convert to float; empty becomes null; invalid input can raise before quality. |
| `rating` | Recognized One/Two/Three/Four/Five tokens become 1-5; otherwise null. |
| `availability` | In-stock/out-of-stock text becomes boolean; otherwise null. |
| Others | Preserve extracted value. |

No profile switch or custom expression controls these conversions. Choose other names when conventions are inappropriate. Quality for price receives the transformed value; raw rejection evidence cannot restore the original price text.

## Quality conversion and rejection

Quality processes the entire transformed list once, before exports. It deep-copies rejection evidence, strips surrounding string whitespace, converts empty strings to null, then converts and validates. It does **not** itself collapse internal string whitespace; parser text has already undergone that collapse.

| Type | Accepted after trimming | Invalid conversion examples |
|---|---|---|
| string | Strings only; internal whitespace preserved | Numbers/booleans are not stringified |
| int | Native int except bool; signed/unsigned ASCII digit strings | "1.0", "1,000", boolean |
| float | Finite int/float except bool; decimal/scientific strings such as "1.2e3" | "1,234.50", "$12", underscores, NaN, infinity |
| bool | Native bool; integers 0/1; case-insensitive strings true/yes/1 and false/no/0 | Other words/integers; floats 0.0/1.0 |
| URL | Absolute HTTP/HTTPS with hostname, no internal whitespace/control characters, valid port | Relative URL, internal space, malformed/out-of-range port |
| date | Native date/datetime; strings under rules below | Invalid calendar date or format mismatch |

Float has no locale/currency parsing. URL trims surrounding whitespace but does not canonicalize the accepted value, check reachability or verify host existence.

Without format, date strings must be exactly YYYY-MM-DD; ISO timestamp strings are not accepted. With format, that single Python strptime format **replaces** the default string parser, not supplements it. Native datetime retains only the date. Success yields an ISO YYYY-MM-DD string.

Required absence, null or conversion failure rejects the record. Optional nulls are allowed; optional conversion failure becomes null and increments invalid_values without itself rejecting the record.

Reasons are objects, not colon-delimited strings:

```json
[
  {"code": "missing_required", "field": "title"},
  {"code": "null_required", "field": "amount"},
  {"code": "invalid_type", "field": "website", "expected_type": "URL"}
]
```

Records can have multiple reasons. URL/date failures also use invalid_type with expected_type. Parser missing values usually become null_required because the parser emits configured keys with empty strings.

## Duplicates, provenance and counts

Deduplication operates within one run, after validation/normalization, using explicit unique_key fields rather than whole-record equality.

- keep_first preserves the first valid occurrence and removes later matching non-null keys.
- report_only retains all valid records and counts later matches as suspected duplicates.
- Any null key component keeps the valid record and increments unkeyed_records. Null keys are never collapsed together; required nulls are rejected first.
- No key means no deduplication and zero unkeyed_records.
- Rejections are preserved independently of deduplication.

Choose keys that identify actual source rows. For inspections, restaurant ID + date + violation code can legitimately repeat; prefer report_only unless a stronger identity is established.

Rejected entries contain raw, normalized, reasons, _source_url and _page. Raw means post-transformation processor input. Provided provenance remains in rejections regardless of clean export settings.

include_provenance copies existing _source_url/_page into clean records. **The runner does not currently attach these values**: enabling the flag does not generate them. Rejected slots are null when unavailable; client fields cannot use reserved names.

The report has exactly these eight fields:

| Field | Meaning |
|---|---|
| extracted | Transformed input record count received by quality |
| valid_before_deduplication | Records without required-field rejections |
| rejected | Rejected record count |
| invalid_values | Non-null conversion failures, including optional fields and later rejected/deduplicated records |
| duplicates_found | Valid non-null-key occurrences after the first |
| duplicates_removed | Duplicates removed by keep_first; zero for report_only |
| unkeyed_records | Valid records with a null key component |
| exported | Clean records returned for export, not proof of successful writes |

Runtime checks raise unless extracted = valid_before_deduplication + rejected and exported = valid_before_deduplication - duplicates_removed.

Both audit files are written for quality runs, even with no rejections/records. Cached skips leave them unchanged. A report may remain after a later exporter failure; only completion state indicates a fully written run.

## Complete examples

All examples below validate with the loader. Static/browser examples use public demonstration sites; quality uses a placeholder URL. Validation does not prove live selectors still match.

### Static, legacy inference

```yaml
site_name: Books to Scrape
engine: static
start_url: https://books.toscrape.com/catalogue/page-1.html
max_pages: 5
delay: 1
fields:
  title: "article.product_pod h3 a::attr(title)"
  price: "article.product_pod p.price_color::text"
  product_url: "article.product_pod h3 a::attr(href)"
pagination:
  next_button: "li.next a"
```

### Browser, explicit containers

```yaml
site_name: Quotes JavaScript
engine: browser
start_url: https://quotes.toscrape.com/js/
max_pages: 3
delay: 1
wait_for: "div.quote"
record_selector: "div.quote"
fields:
  quote: "span.text::text"
  author: "small.author::text"
pagination:
  next_button: "li.next a"
```

### Quality-enabled product listing

```yaml
site_name: Validated Products
engine: static
start_url: https://example.com/products
max_pages: 2
delay: 1
record_selector: "article.product"
pagination:
  next_button: "a.next"
data_quality: true
fields:
  title:
    selector: "h2::text"
    required: true
  sku: ".sku::text"
  amount:
    selector: ".amount::text"
    type: float
    required: true
  in_stock:
    selector: ".stock::attr(data-available)"
    type: bool
  product_url:
    selector: "a.details::attr(href)"
    type: URL
    required: true
  listed_on:
    selector: "time::attr(datetime)"
    type: date
    format: "%Y-%m-%d"
unique_key: [sku, product_url]
duplicate_policy: report_only
include_provenance: false
```

Amount must be plain numeric text. A missing optional SKU keeps the valid record unkeyed. Report-only preserves potential duplicates for review.

## Invalid configuration examples

These complete profiles deliberately fail during loading, before page fetching.

Extended definition without opt-in: `Extended field 'title' requires data_quality: true.`

```yaml
site_name: Invalid Extended Field
engine: static
start_url: https://example.com/
fields:
  title:
    selector: "h2::text"
```

Whitespace-only record selector: `Invalid record_selector. Expected a non-empty CSS selector.`

```yaml
site_name: Invalid Container
engine: static
start_url: https://example.com/
record_selector: "   "
fields:
  title: "h2::text"
```

Format on non-date field: `format is allowed only for type date in field 'amount'.`

```yaml
site_name: Invalid Format
engine: static
start_url: https://example.com/
data_quality: true
fields:
  amount:
    selector: ".amount::text"
    type: float
    format: "%Y-%m-%d"
```

Other loader errors include reserved names, duplicate YAML keys, unknown field properties, unsupported types, missing/empty selectors, non-boolean flags, unknown unique-key fields and invalid duplicate policies. Malformed non-empty CSS passes loading and retains the parser/library's runtime error behavior.
