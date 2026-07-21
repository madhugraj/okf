# Discovery, adversarial QA and corpus storage

## Runtime roles

The production role is **Discovery/Crawler Agent**, not Developer Agent. A developer builds this
software; the runtime crawler discovers and stores web evidence.

| Boundary | Discovery/Crawler Agent | Coverage QA Agent |
|---|---|---|
| Goal | Maximise in-scope discovery and preserve raw content | Find blind spots and challenge completeness evidence |
| Primary method | Recursive HTTP, sitemaps, links and asset downloads | Browser-first rendered DOM/network reconciliation |
| Secondary method | Playwright dynamic discovery | Direct comparison against crawler URLs, outcomes and asset types |
| Corpus write permission | Append immutable raw objects and provenance | None; strictly read-only |
| May repair baseline | Yes, only by a new crawler run | No; reports findings only |
| Output | Candidate typed corpus and crawl evidence | Findings with severity and pass/fail verdict |
| Approval authority | None | None; human approval remains mandatory |

Two tools are intentional. The HTTP/sitemap crawler is deterministic, efficient and strong for
static pages and direct files. Playwright observes JavaScript-rendered links, lazy-loaded media and
browser network responses. Agreement increases confidence; disagreement becomes evidence to
investigate. They remain adapters behind bounded policies, so either can be upgraded without
changing corpus or QA contracts.

The stability run repeats the crawler and detects nondeterminism. It is not independent QA because
it may repeat the same defect. The UI therefore exposes Stability and Adversarial QA separately.

## QA critic rules

QA blocks approval when:

- an independent tool fails or cannot execute;
- QA discovers an in-scope URL absent from the crawler inventory;
- the crawler retains invalid or unresolved outcomes;
- the crawl budget was exhausted;
- no raw assets were stored; or
- another explicit blocker is raised.

Unknown asset types are high-severity review findings. QA has no corpus-store handle and cannot hide
a discrepancy by adding it to the baseline.

## Mandatory corpus storage

The crawler stores the unmodified response bytes before any parsing, OCR, chunking, embedding or
OKF transformation. SHA-256 is the object identity. Identical bytes are stored once, while every
URL, final URL, referrer, run and discovery method remains an independent provenance observation.

```text
.okf-data/
  corpus/
    metadata.sqlite3
    objects/
      pdf/<hash-prefix>/<sha256>.pdf
      image/<hash-prefix>/<sha256>.<ext>
      video/<hash-prefix>/<sha256>.<ext>
      html/<hash-prefix>/<sha256>.html
      code/<hash-prefix>/<sha256>.<ext>
      office/<hash-prefix>/<sha256>.<ext>
      audio/<hash-prefix>/<sha256>.<ext>
      archive/<hash-prefix>/<sha256>.<ext>
      structured_data/<hash-prefix>/<sha256>.<ext>
      other/<hash-prefix>/<sha256>.<ext>
  runs/
  approvals/
```

SQLite is the local operational metadata registry. The object-key layout is deliberately compatible
with later S3/MinIO storage; production deployment will replace local bytes with object storage and
SQLite with PostgreSQL without changing `AssetRecord` or downstream corpus contracts.

Every asset record distinguishes declared MIME from detected MIME and includes filename, extension,
byte size, SHA-256, storage URI, discovery tool and referrer. Directly hosted video/audio is stored.
An external embed outside the approved domain is retained as an excluded URL observation, not
silently downloaded across policy boundaries.
