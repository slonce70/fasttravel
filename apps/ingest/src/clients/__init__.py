"""HTTP/scraping clients. Each client returns RAW payloads; normalization
happens in `apps.ingest.src.normalizers`. This separation lets us record
a VCR cassette of the raw payload once and replay it against an evolving
normalizer without re-recording."""
