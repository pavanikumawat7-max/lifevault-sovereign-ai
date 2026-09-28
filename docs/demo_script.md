# LifeVault — 2:40 demo script

Every question in this script has been run against the real system and
works. **Do not improvise new questions on camera** — the failure modes are
known and listed at the bottom.

## The story

Everything is framed around one situation, because a feature list is
forgettable and a problem the judge has personally had is not.

> **It's 11pm. You're filling in a visa application. It wants your passport
> number and expiry date, an address proof, and a police clearance
> certificate. Your documents are 398 PDFs in your Downloads folder, and one
> of them is called `Adobe Scan 25 Feb 2025.pdf`.**

Each beat then answers the next thing the form asks for, so the demo has
forward motion instead of being a tour. The agent also spots something you
*weren't* looking for — an insurance policy about to lapse — which is what
turns it from a search box into an assistant.

**The one-line thesis:** an AI agent you can trust with your own files — it
cites, it refuses, it asks permission, and it proves what it did.

---

## Prep (do all of it, in order)

```bash
cd ~/lifevault-sovereign-ai

# 1. Warm the model. A cold first call takes ~60s and surfaces as
#    "could not verify" — this is the #1 way a demo goes wrong.
ollama run llama3.2 "ready"

# 2. Generate + index the synthetic personal documents
.venv/bin/python scripts/generate_demo_personal_docs.py --clean
LIFEVAULT_USE_FIXTURES=false .venv/bin/python scripts/index_folder.py ~/LifeVaultDemo

# 3. Clear the approval queue so exactly one proposal appears on camera
.venv/bin/python - <<'PY'
from db.connect import connect
c = connect(); c.execute("UPDATE proposals SET status='denied' WHERE status='pending'"); c.close()
print("queue cleared")
PY

# 4. Start everything (API + watcher + UI)
.venv/bin/python run.py
```

Then, off camera, create the one proposal you'll approve later:

```bash
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"When does my car insurance expire?"}' >/dev/null
```

**Windows to have open before recording:**

1. Browser at `http://localhost:5173`
2. Finder at `~/lifevault-sovereign-ai/vault/reminders/` (for the `.ics` reveal)
3. Finder at `~/LifeVaultDemo/`, and **`police_clearance_certificate.pdf`
   visible on your Desktop** — that's the file you drag in mid-story
   (already generated; regenerate with the snippet at the end of this file)
4. Wi-Fi menu reachable in the menu bar

**Check before you hit record:** ask "When does my passport expire?" once. If
it answers `March 15, 2027` in under 20 seconds, you're warm and ready.

---

## Shot list

### 0:00–0:14 — Cold open: the problem

**Do:** Start on your **Downloads folder in Finder**, scrolled so the mess is
visible. Then open the Wi-Fi menu and **turn Wi-Fi off**, leaving the menu bar
on screen for a beat.

> "It's 11pm and I'm filling in a visa application. It wants my passport
> number, my passport expiry date, an address proof, and a police clearance
> certificate."

*(scroll Downloads)*

> "This is where my documents live. Three hundred and ninety-eight PDFs. One
> of them is called 'Adobe Scan 25 Feb 2025'. I have no idea which."

*(turn Wi-Fi off)*

> "So — LifeVault. And I'm turning the Wi-Fi off first, because none of this
> needs the internet."

*Why open on the mess: the judge has this folder. You have their attention
before you've shown a single feature.*

---

### 0:14–0:34 — Question one from the form: passport

**Do:** Chat. Type **"When does my passport expire?"** When it answers, click
the citation chip to expand it.

> "First thing the form wants."

*(over the wait)*

> "Hybrid keyword-and-vector search over my own files, then a three-billion
> parameter model — all on this laptop."

**Expected:** `March 15, 2027`, citing `passport_scan.pdf` page 1, with
**also found at `passport_scan_copy.pdf`**.

> "March 15th, 2027. And it shows me where it got that — the file, the page,
> the sentence. I can click through to the original. It also noticed I'd saved
> a second copy in another folder, and collapsed them into one answer instead
> of making me compare duplicates."

---

### 0:34–0:50 — The thing that makes it trustworthy

**Do:** Type **"What is my credit card number?"**

**Expected:** `could not verify`, zero citations.

> "But here's what I actually need from something that reads my documents — I
> need to know when it *doesn't* know."

*(answer lands)*

> "Nothing in my files answers that, so it refuses. No citations, because
> there aren't any. Every date and every quoted phrase gets checked back
> against the source document before I ever see it — if it can't be verified,
> I get this instead of a confident guess."

*Linger here. Most demos cannot show this.*

---

### 0:50–1:08 — Question two from the form: the certificate I just downloaded

**Do:** Drag **`police_clearance_certificate.pdf`** from the Desktop into
`~/LifeVaultDemo/`. Switch to Chat and ask **"What is my police clearance
certificate number?"**

> "The form also wants a police clearance certificate. I downloaded that five
> minutes ago — it's still sitting on my Desktop."

*(drag it into the folder)*

> "I'll just put it where the rest of my documents are."

*(switch to Chat, ask)*

> "…and it's already searchable. There's a watcher running: new file, indexed
> in seconds, no restart, no 'rebuild index' button."

---

### 1:08–1:40 — The part I wasn't asking for

**Do:** Click **Approvals**. The car insurance reminder is waiting. Point out
the evidence link and the tier badge. **Change the due date** to about a week
before the expiry. Click **Edit & approve**.

> "And while it was reading all that, it noticed something I wasn't looking
> for. My car insurance expires in three weeks."

> "It hasn't done anything about it. It's asking. It shows me which document
> it got that from, and every field is editable — it wants to remind me
> *tomorrow*, and I'd rather have a week's notice."

*(edit the date, click Edit & approve)*

**Do:** Cut to Finder at `vault/reminders/`. The new `.ics` is there.

> "That's a real calendar file, in its own vault folder. My original documents
> were never touched — it only ever reads them. And nothing here can send an
> email or delete a file; there are exactly two actions it's allowed to take."

*Optional if you have a beat spare:*

> "It also remembers. Next time it'll default to a week, because that's what I
> chose."

---

### 1:40–2:02 — The receipt

**Do:** Click **Audit Log**. Expand the `Decision recorded` row so the edit
diff is visible. Then click **Verify chain**.

> "If something is going to act on my behalf, I want a receipt."

> "Every question and every action is appended to a hash-chained log. There's
> the proposal, there's what I changed — old date struck through, new one
> beside it — and there's my approval."

*(click Verify chain)*

> "Verify recomputes the entire chain. If anyone had quietly edited a single
> past row, this would say tampered."

---

### 2:02–2:20 — What else is about to lapse

**Do:** Click **Expiry & Facts**. Click through **30 → 60 → 90 → 1 year** and
let the list grow.

> "And now that it's read everything, I can see what's coming. Thirty days:
> car insurance. Sixty: my driving licence. Ninety: a laptop warranty. A year
> out: health insurance, and the passport I started with. At the top, already
> expired — my rental agreement."

> "Each row shows the exact sentence it came from. If it misreads a date, I fix
> it here, and that correction survives every future scan."

---

### 2:20–2:34 — One more, because it's a screenshot

**Do:** Ask **"Dell UltraSharp monitor order"**

**Expected:** answers, citing `order_email.png`.

> "Last thing. That order confirmation isn't a PDF — it's a screenshot. That
> text doesn't exist as text anywhere. OCR runs locally too."

---

### 2:34–2:42 — Close

**Do:** Pan back to the menu bar. Wi-Fi is still off.

> "Wi-Fi's been off the entire time. Python, SQLite, Ollama. No API keys,
> nothing uploaded. My documents never left this laptop — and I got my
> passport number in eleven seconds."

---

## Editing notes

- **Record the screen first, voice over afterwards.** Do not narrate live —
  you'll fill the ~10–15 second waits with "um, it's thinking."
- **Jump-cut or 4× every wait.** Judges expect it. Put the explanation in the
  voiceover *over* the cut so it reads as pacing, not a gap.
- Say **"3-billion parameter model on an 8 GB laptop"** out loud once. It
  reframes the latency from slow to impressively small, and it's true.
- Zoom the browser to ~125% so citation chips are legible on a phone screen.

## Do not say or do

| Avoid | Why |
|---|---|
| "My Dell screen is flickering. Am I still covered?" | **Returns `could not verify`.** The 3B won't infer that a flickering screen falls under a hardware warranty. It's in the original plan — do not use it. |
| "On what date was the Dell XPS 15 purchased?" | Also refuses. |
| "What is my passport number?" | This one *works* now (the demo passport has a number), so it is **not** a refusal example. Use the credit card question instead. |
| Asking it to collect documents into a folder | `collect_documents` does not exist. Only `create_reminder` and `draft_email` are implemented. |
| Dropping a `.docx` in to test the watcher | DOCX is skipped. Images and PDFs only. |
| Opening a real identity document on camera | The `~/LifeVaultDemo` files are synthetic — every identifier is invalid by construction. Keep real ones out of the indexed folder. |

## If something breaks mid-take

- **Answer is `could not verify` on a question that should work** → the model
  went cold. Run `ollama run llama3.2 "ready"` and re-take.
- **Approvals page is empty** → re-run the curl in the prep section.
- **UI won't start** → `cd ui && rm -rf node_modules && npm install`. The
  committed `node_modules` is a Windows build.
- **Everything is slow** → close other apps. 8 GB is tight with two models
  resident.

## Regenerating the drag-in document

`police_clearance_certificate.pdf` lives on the Desktop, not in the demo
folder, so the drag beat has something real to move. To recreate it:

```bash
cd ~/lifevault-sovereign-ai
.venv/bin/python - <<'PY'
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, '.')
from scripts.generate_demo_personal_docs import make_pdf
today = date.today()
def iso(d): return (today + timedelta(days=d)).strftime("%B %d, %Y")
make_pdf(
    Path.home() / "Desktop" / "police_clearance_certificate.pdf",
    "Police Clearance Certificate (Synthetic Copy)",
    [
        "Certificate Number: SYNTH-PCC-2026-40881.",
        "Name: Demo Holder. Passport Number: SYNTH-P0042198.",
        f"Date of Issue: {iso(-3)}. Valid Until: {iso(180)}.",
        "Issuing Authority: Commissioner of Police, Bengaluru City.",
        "Verification: no adverse record found against the applicant in the "
        "jurisdiction of this office.",
        "Required for visa and long-term residence applications.",
    ],
)
print("staged on Desktop")
PY
```

After a take, remove it from the demo folder so the next take starts clean:

```bash
rm -f ~/LifeVaultDemo/police_clearance_certificate.pdf
```
