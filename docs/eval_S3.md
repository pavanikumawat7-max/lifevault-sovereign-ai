# S3 evaluation results

- Model: `llama3.2`
- Embedding model: `nomic-embed-text`
- Fixture mode: `False`
- Chunks per answer (top_k): 4
- Corpus: 104 documents / 105 chunks
- Machine: Darwin arm64 (python 3.12.13)
- Warmup call (not counted): 1.1s
- Run at: 2026-09-28T16:02:40+0530

**9/10 passed** | grounded 8/10 | cited the expected file 8/9 | latency median 15.5s, mean 16.9s, max 25.0s

| # | Question | Answer | Grounded | Cited | Source (path:page) | Expected file | Pass | Latency |
|---|---|---|---|---|---|---|---|---|
| 1 | When does my Dell laptop warranty expire? | Your Dell laptop warranty expires on June 12, 2027. | yes | C1 | `dell_warranty.pdf`:1 | `dell_warranty.pdf` | PASS | 25.0s |
| 2 | What is the service tag of my Dell XPS 15? | SYNTH-XPS-2026 | yes | C1 | `dell_warranty.pdf`:1 | `dell_warranty.pdf` | PASS | 14.7s |
| 3 | How much did the Dell XPS 15 laptop cost? | The cost of the Dell XPS 15 laptop was $1,749.00. | yes | C1 | `dell_invoice.pdf`:1 | `dell_invoice.pdf` | PASS | 19.3s |
| 4 | What is the invoice number for the Dell laptop? | INV-DELL-10482 | yes | C1 | `dell_invoice.pdf`:1 | `dell_invoice.pdf` | PASS | 16.8s |
| 5 | On what date was the Dell XPS 15 purchased? | could not verify | no | -- | -- | `dell_warranty.pdf` or `dell_invoice.pdf` | FAIL | 14.2s |
| 6 | Which warranty has already expired, and on what date? | The warranty that has already expired is the appliance warranty with contract number OL... | yes | C1 | `old_expired_warranty.pdf`:1 | `old_expired_warranty.pdf` | PASS | 18.2s |
| 7 | What is the contract number on the expired refrigerator warranty? | OLD-DEMO-319 | yes | C1 | `old_expired_warranty.pdf`:1 | `old_expired_warranty.pdf` | PASS | 15.7s |
| 8 | Who is the provider on synthetic insurance record 001? | Willis PLC | yes | C1 | `record_001.pdf`:1 | `record_001.pdf` | PASS | 14.9s |
| 9 | What is the reference number on the synthetic travel record 003? | DEMO-0003 | yes | C1 | `record_003.pdf`:1 | `record_003.pdf` | PASS | 15.0s |
| 10 | What is my passport number and when does it expire? | could not verify | no | -- | -- | (none) | PASS | 15.2s |

## Failures

- **Q5** On what date was the Dell XPS 15 purchased?
  - answer: 'could not verify'
  - missing expected value(s): ['June 12, 2026 | 2026-06-12']
  - expected `['dell_warranty.pdf', 'dell_invoice.pdf']`, cited []
  - verification: the model reported that the documents do not answer this
