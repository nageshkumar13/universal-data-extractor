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
