# Chord Chart

A Roman-numeral chord chart writer: superscripted extensions, four measures
per system, lettered sections (A, B, C…) with repeats, a notes box, and a
"Save to disk" that's a plain JSON file — no browser storage involved, so it
can't silently fail the way it did as a web artifact. Printing is now a real
downloadable PDF, generated in Python, instead of the browser's print button.

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
