# Evidence Manifest — ADR-043 Real-GCP Destructive Qualification

All hashes are SHA-256 of the file as committed. Several files share identical
hashes across pipeline stages **by design** — that identity is the decisive proof
of survival and is called out explicitly below, not treated as accidental
duplication.

| File | Purpose | SHA-256 | Source / test stage | Sanitized? |
|---|---|---|---|---|
| `bucket-metadata-before-lock.json` | Bucket state before the retention policy was locked | `7b352f1a311a695d8e8ee17237a79dae773882b2c8c5f5d5f531bd1ff29131aa` | `gcloud storage buckets describe`, pre-lock | No |
| `bucket-metadata-locked-pre-deletion.json` | Bucket state, locked, immediately before Gate 2 / project deletion | `85083282eb1c4d73b4cb3072c4c3301f47303a398c3578708445cfdfbe38de21` | `gcloud storage buckets describe`, post-lock/pre-delete | No |
| `bucket-metadata-post-restore-pre-relink.json` | Bucket state read immediately after project restore, before billing was re-linked | `85083282eb1c4d73b4cb3072c4c3301f47303a398c3578708445cfdfbe38de21` | `gcloud storage buckets describe`, post-restore | No — **identical hash to the pre-deletion file: bucket metadata was readable and unchanged even before billing was re-linked** |
| `bucket-metadata-post-relink.json` | Bucket state read after billing re-link | `85083282eb1c4d73b4cb3072c4c3301f47303a398c3578708445cfdfbe38de21` | `gcloud storage buckets describe`, post-relink | No — **identical hash again** |
| `object-metadata-before-lock.json` | Object metadata at upload time | `60f3a00dfaa7b5a54dcfc884fa3fb432151a0082d1424f55a32e239f893790fc` | `gcloud storage objects describe`, post-upload/pre-lock | No |
| `object-metadata-pre-deletion.json` | Object metadata immediately before Gate 2 / project deletion | `60f3a00dfaa7b5a54dcfc884fa3fb432151a0082d1424f55a32e239f893790fc` | `gcloud storage objects describe`, pre-delete | No — **identical hash to the before-lock file** |
| `object-metadata-post-relink.json` | Object metadata read after billing re-link (first successful post-restore object read) | `60f3a00dfaa7b5a54dcfc884fa3fb432151a0082d1424f55a32e239f893790fc` | `gcloud storage objects describe`, post-relink | No — **identical hash to both files above: the decisive generation/hash identity proof** |
| `object-bytes-post-relink.txt` | Actual object bytes downloaded post-restore/post-relink | `cc605b9773c3f991a9f5afcd68e56bb3dffefc0ec5e1ca169da726996f0c236d` | `gcloud storage cat`, post-relink | No |
| `test-object-plaintext.txt` | The exact 87-byte deterministic payload originally uploaded | `cc605b9773c3f991a9f5afcd68e56bb3dffefc0ec5e1ca169da726996f0c236d` | Locally generated before upload | No — **identical hash to `object-bytes-post-relink.txt`: independently-recomputed byte identity proof, not merely a provider-reported claim** |
| `lien-before-removal.json` | The single project-deletion lien, before removal | `d1338e335f722313eccf471490f3fe9c6885032b6da2e420f050004c2a55ab34` | `gcloud alpha resource-manager liens list`, pre-removal | No |
| `project-state-delete-requested.json` | Project resource state immediately after the delete request | `f94c9465e1e8c01010895a71263beff5dbd8defc855da31479b74e625b4b5e67` | `gcloud projects describe`, post-delete-request | No |
| `project-state-active-after-restore.json` | Project resource state immediately after the undelete request | `d0953cf2defb3abdb9541fb9be296da429efeb517c5ca809a1588983a840b2a0` | `gcloud projects describe`, post-restore | No |
| `billing-disabled-after-restore.json` | Billing association state discovered immediately after restore, before re-link | `1a5e2d3b9eda710134311dec33d1f61e828e67cbba4b08ba4668a9ca32d98940` | `gcloud billing projects describe`, post-restore/pre-relink | No |
| `billing-relink-response.json` | Billing association state after the authorized re-link | `00f467ed22faedd2342cc154ef848eac1066faaca1bef12a65be878beb1289b8` | `gcloud billing projects link`, response | No |
| `sanitized-responses/01-lock-retention-policy-response.json` | `lockRetentionPolicy` request line + response excerpt | `394126106d26256c96b6b1143275a1d67112dc39e5db1ea98842342a95bc6200` | Hand-extracted from `--log-http` capture | Yes |
| `sanitized-responses/02-overwrite-retained-object-403.json` | Pre-lien-removal overwrite failure | `84faf733182e2482d11e0181745e844437a25c661b94aa401d84b7ac7b68c6fe` | Hand-extracted | Yes |
| `sanitized-responses/03-delete-retained-object-403.json` | Pre-lien-removal delete failure | `d2da1855a3a4a1d4d80e7831ec0c788a7d08437ec5ee1b7c240087178fce2417` | Hand-extracted | Yes |
| `sanitized-responses/04-reduce-locked-retention-403.json` | Pre-lien-removal retention-reduction failure | `814501b7d5f393b018c350145278a9a67b7e6912a49a4e524a90f25056366b8a` | Hand-extracted | Yes |
| `sanitized-responses/05-remove-locked-retention-policy-403.json` | Pre-lien-removal retention-removal failure | `a9c6c8b3037fd1c5063747f36512dc1e02d0097276d2701e6cabee627adc8966` | Hand-extracted | Yes |
| `sanitized-responses/06-post-lien-removal-delete-403.json` | Delete failure immediately after lien removal (`P0_CRITICAL` check) | `53aa251689836b3dfa4562314437b580f20018f39b6120b97aea121a14846005` | Hand-extracted | Yes |
| `sanitized-responses/07-project-delete-response.json` | Project deletion request/response | `88a9757fa578a924fcf626f0968bbaba62c94a17b3ee0713c08860062395a15f` | Hand-extracted | Yes |
| `sanitized-responses/08-project-undelete-response.json` | Project restoration request/response | `77cdfeaa1e3e13a2d448551b634b64401fbda52a02871471504ed7661b5b9306` | Hand-extracted | Yes |
| `sanitized-responses/09-object-read-blocked-billing-disabled.json` | The billing-disabled discovery | `2ec7898e9599616e245ed700efadde9f789aae3dbe413ca73a0e18245b9e511f` | Hand-extracted (account email removed) | Yes |
| `sanitized-responses/10-post-relink-delete-403-decisive.json` | Final decisive post-restore enforcement check | `6f3c9912e9da8805c480004e1fc77e9a2753cc59101f91ad067c9910533e1fae` | Hand-extracted | Yes |

## Identity cross-check (pre-deletion vs. post-restore)

| Property | Pre-deletion | Post-restore | Match |
|---|---|---|---|
| Project ID | `emg-adr043-disposable-witness` | `emg-adr043-disposable-witness` | ✅ |
| Project number | `617557656575` | `617557656575` | ✅ |
| Bucket name | `emg-adr043-blockera-destructive-08657059` | `emg-adr043-blockera-destructive-08657059` | ✅ (not recreated) |
| Object key | `witness/destructive-test-object-v1.txt` | `witness/destructive-test-object-v1.txt` | ✅ (not recreated) |
| Object generation | `1786901627964283` | `1786901627964283` | ✅ |
| SHA-256 (recomputed locally) | `cc605b9773c3f991a9f5afcd68e56bb3dffefc0ec5e1ca169da726996f0c236d` | `cc605b9773c3f991a9f5afcd68e56bb3dffefc0ec5e1ca169da726996f0c236d` | ✅ |
| CRC32C (provider-reported) | `3UsnGQ==` | `3UsnGQ==` | ✅ |
| MD5 (provider-reported) | `Vwg9TkRDjriAbYhV7IJGLQ==` | `Vwg9TkRDjriAbYhV7IJGLQ==` | ✅ |
| Retention period | `86400` seconds | `86400` seconds | ✅ |
| Retention effective time | `2026-08-16T17:32:52.791Z` | `2026-08-16T17:32:52.791Z` | ✅ |
| Retention expiration (object) | `2026-08-17T17:33:47Z` | `2026-08-17T17:33:47Z` | ✅ |
| Lock state | `isLocked: true` | `isLocked: true` | ✅ |

**No discrepancies were found.** Every property matched exactly; none were adjusted,
omitted, or reinterpreted to force a match.

## What was deliberately excluded

Raw `gcloud --log-http` capture files were generated during the test session but are
**not** included in this evidence package, for the same reasons documented in
`../real-gcp-safe-qualification/evidence-manifest.md`: they contained the
authenticated account's email address and local sandbox filesystem paths in
diagnostic text (never the actual bearer token, which `gcloud` itself redacts, and
never a cookie). Every fact from those raw logs relevant to the qualification claim
has been carried into the sanitized extracts above, hand-verified against the raw
capture at the time of extraction.
