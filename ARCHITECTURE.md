# ReelHarbor architecture

ReelHarbor is a Docker-first web application with a React/TypeScript frontend, a FastAPI service, PostgreSQL persistence, Redis coordination, Playwright for rendered crawling, and `ffprobe`/`yt-dlp`/`ffmpeg` for metadata and permitted downloads.

## Service boundaries

- `frontend`: responsive application shell, setup, scans, detected-video selection, downloads, library, schedules, logs, and settings.
- `api`: authentication, validation, crawl orchestration, detector plugins, analysis, download execution, exports, and server-sent progress events.
- `postgres`: durable users, scans, pages, candidates, downloads, schedules, settings, and library records.
- `redis`: shared event stream and coordination surface (the API degrades to an in-process event bus in development).
- Persistent `videos`, `thumbnails`, and `postgres_data` volumes keep user data outside containers.

## Crawl and detection flow

1. Validate the target at submission and before every request/redirect. DNS results are checked against loopback, private, link-local, reserved, multicast, and metadata ranges.
2. Fast mode fetches HTML with bounded response sizes and extracts links and media.
3. Browser mode uses Playwright and observes DOM plus media-related network responses.
4. Detector plugins normalize discoveries into `VideoCandidate` records. Duplicate fingerprints are unique per site.
5. `ffprobe` enriches direct, accessible media. Failure leaves metadata unknown instead of fabricating values.
6. The user reviews and selects results; no scan automatically downloads by default.
7. Downloads use `yt-dlp` with safe argument arrays and `ffmpeg` stream-copy merging. Completed files are fingerprinted and placed in the library.

## Detector interface

`HtmlVideoDetector`, `OpenGraphDetector`, `JsonLdDetector`, `HlsDetector`, `DashDetector`, `IframeDetector`, `ScriptMediaDetector`, `NetworkMediaDetector`, and `YtDlpMetadataDetector` return one normalized `VideoCandidate` model. The registry deduplicates by canonical media URL and merges richer metadata.

## Data model

Tables: `users`, `sites`, `scan_jobs`, `crawl_pages`, `detected_videos`, `video_variants`, `downloads`, `download_attempts`, `video_library`, `video_thumbnails`, `schedules`, `application_settings`, and `audit_logs`. Search and status indexes cover scan history, candidate filtering, downloads, and library queries.

## UI inventory

The design system uses near-black navy (`#071018`), slate surfaces (`#0e1a24`), pale text, muted blue-gray, cyan actions, green success, amber warnings, and red destructive states. Components include `AppShell`, sidebar navigation, metric strip, scan progress, media rows/cards, status tags, selection toolbar, filters, queue rows, details drawer, modal preview, setup steps, and responsive bottom navigation.

Primary screens: Overview, New Scan, Scan Progress, Detected Videos, Download Manager, Library, Scan History, Schedules, Network Inspector, Logs, Settings, and First-run Setup. Desktop uses list/table density; widths below 760px switch media results and queues to stacked cards.

## Security posture

Passwords use Argon2/Bcrypt-compatible hashing; sessions are signed, HTTP-only, SameSite cookies. Mutations require a matching CSRF header/cookie. API inputs are typed and length-bounded. The crawler strips credentials, blocks internal networks by default, revalidates redirects, limits content and crawl breadth, and never logs cookies, authorization headers, or passwords. Rate limits cover authentication, scans, and downloads.

