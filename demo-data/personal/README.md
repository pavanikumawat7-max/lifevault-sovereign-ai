# Personal documents demo set (synthetic)

The 15 documents used in the demo video (`docs/demo_script.md`): passport (plus a
duplicate in `scanned copies/`), Aadhaar, PAN, driving licence, insurance policies,
an HP laptop invoice and warranty, address proofs, certificates and an expired
rental agreement.

**Everything here is synthetic.** Every identifier starts with `SYNTH` or is
otherwise invalid by construction. Never put real documents in this folder.

Index it:

```bash
LIFEVAULT_USE_FIXTURES=false python scripts/index_folder.py demo-data/personal
```

`../personal_drop_in/police_clearance_certificate.pdf` is kept outside this folder
on purpose: drag it in during the demo to show the watcher indexing a new file.

Expiry dates were generated on 2026-09-28 relative to that day. To get fresh
dates relative to today, regenerate with `scripts/generate_demo_personal_docs.py --clean`
(writes to `~/LifeVaultDemo`).
