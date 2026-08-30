# Chord Chart

A Roman-numeral (or chord-name) chart writer: superscripted extensions, four
measures per system, lettered sections (A, B, C…) with repeats, copy/paste
for measures and sections, a notes box, key transposition, and Roman-numeral
→ chord-name publishing — plus a "Save to disk" that's a plain JSON file, no
browser storage involved, so it can't silently fail the way it did as a web
artifact. Printing is a real downloadable PDF, generated in Python, instead
of the browser's print button.

## Entering chords

Open **Input mode & publish settings** at the top to switch between:

- **Roman numerals** — `V7`, `ii6`, `vii°7`, `V7/V`. Type the numeral, then
  anything else; it's superscripted automatically.
- **Chord names** — `E7`, `Ab^` (Ab major 7), `Dm7`, `C/E`. Type the root
  note, then anything else; same auto-superscript rule.

`^` always means **major 7th** (Δ) in either mode — it's not a separator.
`-7b5` always becomes **ø** (half-diminished).

## Publishing

The same panel controls what actually gets shown in the chart and in the
exported PDF:

- **Written in Roman numerals** → choose to publish as Roman numerals (as
  typed) or as **chord names in a key you pick**. Handles triads, seventh
  chords, standard inversions (6, 6/4, 6/5, 4/3, 4/2), and one level of
  secondary dominant (e.g. `V7/V`). Anything unusual is shown as typed
  rather than guessed at. Any measure can carry a **key change**, a
  semitone shift from ±0 to ±6 relative to your chart's original key. Once
  set, it takes effect for that measure and every later measure — across
  section boundaries — until a different measure sets a new key change. A
  small "→ Eb (+3)" label marks the exact measure where each modulation
  starts, in both the on-screen chart and the PDF.
- **Written as chord names** → set the key the chart is written in and the
  key you want to publish in; the app transposes every chord (including
  slash-chord bass notes) automatically. Diatonic chords transpose exactly;
  chromatic/borrowed chords use the closest simple spelling for the target
  key, which occasionally differs by enharmonic spelling from a strict
  interval-preserving transposition.

## Saving named chart files

Beyond the automatic session save, open **Save / load chart files** to:

- **Save** the current chart under a name and folder you choose. Leave off
  an extension and it's saved as `.chord` (e.g. "My Song" → `My Song.chord`);
  typing your own extension is respected as-is.
- **Load** any `.chord` file back — pick one from a dropdown of files found
  in the folder you specified, or paste a full file path to load from
  anywhere else on disk.
- **Download** the current chart, or any listed file, straight to your own
  device's browser downloads — this works over the network even when the
  app is deployed remotely, since it's a normal browser download rather
  than a server-disk operation.

The folder is wherever this app is actually running: your own computer if
you run it locally, or the host's storage if you've deployed it (see
"Getting this onto your iPad" below for what that means for persistence).

## Why Python instead of the in-browser version

The chat artifact ran inside a sandboxed webpage that doesn't grant full
`localStorage`/`window.print()` permissions — that's what caused "Couldn't
save" and the dead print button. This version is a normal Python web app
(built with [Streamlit](https://streamlit.io)) that you run yourself, so it
has full access to your filesystem for saving and to `reportlab` for PDF
generation. Both problems go away because neither depends on browser
permissions anymore.

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

This starts a local web server (by default at `http://localhost:8501`) and
opens it in your browser. Your chart is saved to `chord_chart_save.json` in
the same folder — it reloads automatically the next time you start the app.

## Getting this onto your iPad

An iPad can't run a Python web server natively, so "standalone app" in
practice means one of these:

**Option A — host it once, then just open it in Safari (recommended)**
Deploy `app.py` to a free host that runs Python for you, for example
[Streamlit Community Cloud](https://streamlit.io/cloud):
1. Push this folder to a GitHub repo.
2. Sign in at share.streamlit.io, point it at the repo, and deploy.
3. You'll get a URL like `https://yourname-chordchart.streamlit.app`.
4. Open that URL in Safari on your iPad, tap the Share icon, then
   **Add to Home Screen**. It now behaves like a standalone app icon,
   launches full-screen, and is reachable from anywhere (not just your
   home network).

**Option B — run it on a computer you own, reach it from the iPad**
Run `streamlit run app.py` on a Mac/PC on the same Wi-Fi network as your
iPad, then on the iPad open Safari to `http://<that-computer's-IP>:8501`
and **Add to Home Screen** the same way. This only works while that
computer is on and the app is running.

Either way, note that "Add to Home Screen" gives you an app-like icon and
full-screen window, but the app itself is still served over the network —
true offline-only operation isn't possible for a Python web app on iPadOS
without a native app wrapper, which is a much bigger project than this.

## Files

- `app.py` — the whole app.
- `requirements.txt` — `streamlit` and `reportlab`.
- `chord_chart_save.json` — created automatically on first save; this is
  your chart's persistent storage.
