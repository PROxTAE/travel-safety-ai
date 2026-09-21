# Approved knowledge sources

`sources.yaml` is intentionally empty until documents are reviewed. Runtime
must report knowledge retrieval as `UNAVAILABLE` and return
`NO_RELIABLE_KNOWLEDGE_EVIDENCE`; it must not insert sample guidance.

## Source review process

1. Confirm the publisher is a government, UN/WHO body, recognized authority,
   or a provider explicitly approved by the Team Lead.
2. Review license, geographic scope, language, effective/expiry dates, and
   whether redistribution or extracted passages are permitted.
3. Download only through the configured HTTPS allowlist. Record the final URL,
   status, retrieval time, media type, size, and SHA-256 checksum.
4. Run malware/type/size checks and review the parsed page/section structure.
5. Add a manifest record validated by `sources.schema.json`; a named reviewer
   sets `review_status: APPROVED`.
6. Index into a new versioned Qdrant collection. Run relevance, citation,
   region, expiry, prompt-injection, Thai/English, and latency evaluations.
7. Record evaluation checksum and approval in PostgreSQL before switching the
   `active` alias. Keep the previous collection for rollback.

Expired, wrong-region, unapproved, checksum-mismatched, and low-confidence
documents are excluded rather than served with a warning.
