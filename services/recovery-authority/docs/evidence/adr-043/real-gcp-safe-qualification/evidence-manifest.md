# Evidence Manifest — ADR-043 Real-GCP Safe Bucket Lock Qualification

All hashes are SHA-256 of the file as committed. Where two files share an identical
hash, that is itself evidentiary (e.g. the lien is byte-identical before/after bucket
deletion; the object is byte-identical before/after the rejected project-deletion
attempt) — noted explicitly below rather than treated as accidental duplication.

| File | Purpose | SHA-256 | Source / test stage | Sanitized? |
|---|---|---|---|---|
| `bucket-metadata-before-lock.json` | Bucket state immediately before locking (metageneration 4, unlocked retention policy) | `f1a392d9a1e7c217030e0c2ca2d49b5b601962cc9ab1b33963818aac157ed9a4` | `gcloud storage buckets describe`, pre-lock | No — direct `describe` output, already free of credentials/identity |
| `bucket-metadata-after-lock.json` | Bucket state immediately after locking (metageneration 5, `isLocked: true`) | `44afa12e4cef15f611077fa5b2b1af07af071d46a83a75a255a26e5a70966dd5` | Response body of `lockRetentionPolicy`, hand-extracted | Yes — headers/upload-ID/client-identity stripped from the raw `--log-http` capture; resource fields preserved verbatim |
| `object-metadata-before-lock.json` | Test object metadata at upload time (generation, hashes, retention_expiration) | `af61f561590999bb9fde79f710df124395bc0311bba039f33b3e4a8ca53b1d6c` | `gcloud storage objects describe`, post-upload/pre-lock | No |
| `object-metadata-after-rejected-project-delete.json` | Test object metadata re-read immediately after the rejected project-deletion attempt | `af61f561590999bb9fde79f710df124395bc0311bba039f33b3e4a8ca53b1d6c` | `gcloud storage objects describe`, post-delete-attempt | No — **identical hash to the pre-lock file, proving the object is byte-for-byte unchanged** |
| `lien-after-lock.json` | Project lien listing immediately after locking | `d1338e335f722313eccf471490f3fe9c6885032b6da2e420f050004c2a55ab34` | `gcloud alpha resource-manager liens list`, post-lock | No |
| `lien-after-bucket-delete.json` | Project lien listing after the bucket was fully deleted | `d1338e335f722313eccf471490f3fe9c6885032b6da2e420f050004c2a55ab34` | `gcloud alpha resource-manager liens list`, post-cleanup | No — **identical hash to the post-lock file, proving the lien persists unchanged after the retained resource is gone** |
| `project-state-before-delete-attempt.json` | Project resource state immediately before the safe deletion-with-lien check | `d0953cf2defb3abdb9541fb9be296da429efeb517c5ca809a1588983a840b2a0` | `gcloud projects describe`, pre-attempt | No |
| `project-state-after-delete-attempt.json` | Project resource state immediately after the rejected deletion attempt | `d0953cf2defb3abdb9541fb9be296da429efeb517c5ca809a1588983a840b2a0` | `gcloud projects describe`, post-attempt | No — **identical hash, proving `lifecycleState: ACTIVE` was unaffected by the rejected request** |
| `test-object-plaintext.txt` | The exact 76-byte deterministic test payload uploaded to GCS | `a3b05ac9e7bec756e8a554f8f25f9e20b606244ac50ff5c12e9b5c37a8430332` | Locally generated before upload | No — plain test string, no sensitive content |
| `sanitized-responses/01-lock-retention-policy-response.json` | `lockRetentionPolicy` request line + response excerpt | `519993d6e5c683a0b5394b5e799934f125cc917b4159f163cb065c4b751c6c84` | Hand-extracted from `--log-http` capture | Yes |
| `sanitized-responses/02-overwrite-retained-object-403.json` | Overwrite-while-retained failure | `55cce42a4f8ab4bcbec66a62a06c2d221a5079f10364f0e1e053ec666b39ef65` | Hand-extracted | Yes |
| `sanitized-responses/03-delete-retained-object-403.json` | Delete-while-retained failure | `e7857299be6b39d20f4b382b80789a90556f82625bbb849766d0b8f2b068db8d` | Hand-extracted | Yes |
| `sanitized-responses/04-delete-nonempty-bucket-409.json` | Bucket-delete-while-non-empty failure | `daf436aa900fd054fe7c505f2ec2d2a87e59de9ed7539bbc85cf428672068f8f` | Hand-extracted | Yes |
| `sanitized-responses/05-reduce-locked-retention-403.json` | Retention-reduction-on-locked-policy failure (documentation discrepancy) | `cb2c9470e237e27daeef3b59f107c94795843df90c747cfcf6d36fd2e76f47c2` | Hand-extracted | Yes |
| `sanitized-responses/06-remove-locked-retention-policy-403.json` | Retention-removal-on-locked-policy failure | `ad96d54d3ca6b887717a027ad90d36a60d83aefb9ec22de51fabb8b727338e3e` | Hand-extracted | Yes |
| `sanitized-responses/07-project-delete-with-lien-400.json` | Project-deletion-with-lien rejection (the key result) | `948cdc5da42602d0d034958631c9ba405c2f414e0534219084d7c922eeeeed0d` | Hand-extracted | Yes |
| `sanitized-responses/08-cleanup-delete-object-204.json` | Post-expiry object cleanup success | `73d79ff2e16c764737a96c2608f934db838252a52efdbb9239507d3f14b6c51a` | Hand-extracted | Yes |
| `sanitized-responses/09-cleanup-delete-bucket-204.json` | Empty-bucket cleanup success | `1f6020f6f4a28a776aa4b38076535d77ea1910bb36d2721b8f234621f1a4ca3c` | Hand-extracted | Yes |

## What was deliberately excluded

Raw `gcloud --log-http` capture files were generated during the test session but are
**not** included in this evidence package. They were reviewed in full and found to
contain (a) the authenticated Google account's email address in gcloud's own
diagnostic text, and (b) local sandbox filesystem paths — both excluded per the
evidence-handling requirements for this checkpoint. They never contained the actual
bearer token (redacted by `gcloud` itself as `--- Token Redacted ---`) or any cookie.
Every fact from those raw logs that is relevant to the qualification claim has been
carried into the sanitized extracts above, hand-verified against the raw capture at
the time of extraction.
