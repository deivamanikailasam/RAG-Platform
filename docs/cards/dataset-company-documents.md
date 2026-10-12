# Company documents (the source corpus)

<!-- generated from cards/ by `just cards docs`: do not edit -->

| | |
|---|---|
| **Id** | `dataset:company-documents` |
| **Status** | approved |
| **Owner** | knowledge-management |
| **Last reviewed** | 2026-10-12 (every 90 days) |
| **Role** | source |
| **Highest classification** | restricted |
| **Personal data** | yes |
| **Retention** | Follows the source system; deleted or expired files are removed within 7 days (Step 36). |

## Summary

The original files the assistant answers from: policies, handbooks, procedures and reports, each with its classification and access groups. Everything else is derived from this.

## Where it lives

- s3://rag-raw-docs (originals, versioned, Step 14)
- Postgres rag.documents (metadata, ACL groups, classification, object-version lineage, Step 11/14)

## Provenance

Exported from the company's document systems by the ingestion worker (Step 31); every row records the exact object version it came from, so any answer can be traced to a file version.

## Personal data

Names, roles and contact details of staff appear in documents; some HR documents contain more. No special-category data should be ingested without a separate assessment.

## Legal basis

Legitimate interest of the employer in making internal documents findable (to be confirmed by the data protection officer in a DPIA before production use).

## Deletion

Deleting a document soft-deletes its row, removes its chunks from every index and expires its object versions (Step 36 deletion flow); derived datasets inherit the deletion.

## Access

ACL groups per document, enforced by the policy (Step 18) before anything is retrieved.

## Known limitations

- Coverage depends on which systems are connected; absence of a document isn't proof it doesn't exist
- Classifications are only as good as the people who set them

## Lineage

Built from:

- (none)

Affects if changed:

- dataset:company-chunks (input)
- dataset:rag-answer-golden (input)
  - system:rag-api (input)
    - dataset:audit-log (input)
    - dataset:llm-traces (input)

## Approvals

- 2026-10-12 · you · data owner sign-off pending in a real company
