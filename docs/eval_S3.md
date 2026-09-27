# S3 evaluation results

- Model: `llama3.2`
- Embedding model: `nomic-embed-text`
- Fixture mode: `False`
- Chunks per answer (top_k): 4
- Corpus: 103 documents / 104 chunks
- Machine: Darwin arm64 (python 3.12.13)
- Warmup call (not counted): 0.6s
- Run at: 2026-09-27T11:41:47+0530

**9/10 passed** | grounded 8/10 | cited the expected file 8/9 | latency median 7.8s, mean 7.9s, max 9.7s

| # | Question | Answer | Grounded | Cited | Source (path:page) | Expected file | Pass | Latency |
|---|---|---|---|---|---|---|---|---|
| 1 | When does my Dell laptop warranty expire? | June 12, 2027 | yes | C1 | `dell_warranty.pdf`:1 | `dell_warranty.pdf` | PASS | 9.7s |
| 2 | What is the service tag of my Dell XPS 15? | SYNTH-XPS-2026 | yes | C1 | `dell_warranty.pdf`:1 | `dell_warranty.pdf` | PASS | 7.6s |
| 3 | How much did the Dell XPS 15 laptop cost? | $1,749.00 | yes | C1 | `dell_invoice.pdf`:1 | `dell_invoice.pdf` | PASS | 7.8s |
| 4 | What is the invoice number for the Dell laptop? | INV-DELL-10482 | yes | C1 | `dell_invoice.pdf`:1 | `dell_invoice.pdf` | PASS | 7.5s |
| 5 | On what date was the Dell XPS 15 purchased? | 2026-06-12 | yes | C1 | `dell_warranty.pdf`:1 | `dell_warranty.pdf` | PASS | 6.6s |
| 6 | Which warranty has already expired, and on what date? | March 3, 2021 | yes | C1 | `old_expired_warranty.pdf`:1 | `old_expired_warranty.pdf` | PASS | 6.0s |
| 7 | What is the contract number on the expired refrigerator warranty? | OLD-DEMO-319 | yes | C1 | `old_expired_warranty.pdf`:1 | `old_expired_warranty.pdf` | PASS | 8.1s |
| 8 | Who is the provider on synthetic insurance record 001? | Willis PLC | yes | C1 | `record_001.pdf`:1 | `record_001.pdf` | PASS | 8.1s |
| 9 | What is the reference number on the synthetic travel record 003? | could not verify | no | -- | -- | `record_003.pdf` | FAIL | 7.9s |
| 10 | What is my passport number and when does it expire? | could not verify | no | -- | -- | (none) | PASS | 9.4s |

## Failures

- **Q9** What is the reference number on the synthetic travel record 003?
  - answer: 'could not verify'
  - missing expected value(s): ['DEMO-0003']
  - expected `record_003.pdf`, cited []
  - verification: the model reported that the documents do not answer this
