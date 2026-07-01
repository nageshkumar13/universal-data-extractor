# Universal Data Extractor

A modular Python framework for extracting, cleaning, and exporting structured data from public websites.

> 🚧 Project Status: Under active development.

## Vision

Universal Data Extractor is a configurable Python framework designed to extract structured data from public websites using reusable extraction profiles.

The project is being developed incrementally, with each milestone adding new capabilities while keeping the codebase clean, testable, and easy to extend.

## Current Features

- YAML-based extraction profiles
- Static HTML fetching
- CSS selector-based field extraction
- Relative URL normalization
- Pagination support
- CSV and JSON export
- SQLite URL cache
- robots.txt awareness
- Compact CLI run summary

## Sample Output

```json
{
  "title": "A Light in the Attic",
  "price": 51.77,
  "rating": 3,
  "availability": true,
  "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
}
```

## Release Milestones

| Version | Focus |
|---|---|
| v0.1.0 | End-to-end static extraction pipeline |
| v0.2.0 | SQLite cache and robots.txt awareness |
| v0.3.0 | Structured data transformation layer |
| v0.4.0 | Core unit test coverage |
| v0.5.0 | Multi-profile extraction support |
| v0.6.0 | Business-friendly Excel exports |
| v0.7.0 | Automated GitHub Actions test workflow |

## Planned Roadmap

### v1.0

- Static HTML scraping (Requests + BeautifulSoup)
- YAML extraction profiles
- CSV & JSON export
- SQLite URL cache
- robots.txt awareness
- Command-line interface

### v1.1

- Playwright browser automation
- Pagination improvements
- Data validation pipeline
- Excel export

### v1.2

- Docker support
- GitHub Actions
- Unit tests
- Performance statistics

### v2.0

- Provider-agnostic AI extraction
- CSS → XPath → LLM fallback architecture

## License

MIT

