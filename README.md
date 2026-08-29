Chord Chart
A Roman-numeral (or chord-name) chart writer: superscripted extensions, four
measures per system, lettered sections (A, B, C…) with repeats, copy/paste
for measures and sections, a notes box, key transposition, and Roman-numeral
→ chord-name publishing — plus a “Save to disk” that’s a plain JSON file, no
browser storage involved, so it can’t silently fail the way it did as a web
artifact. Printing is a real downloadable PDF, generated in Python, instead
of the browser’s print button.
Entering chords
Open Input mode & publish settings at the top to switch between:
	•	Roman numerals — V7, ii6, vii°7, V7/V. Type the numeral, then
anything else; it’s superscripted automatically.
	•	Chord names — E7, Ab^ (Ab major 7), Dm7, C/E. Type the root
note, then anything else; same auto-superscript rule.
^ always means major 7th (Δ) in either mode — it’s not a separator.
-7b5 always becomes ø (half-diminished).
Publishing
The same panel controls what actually gets shown in the chart and in the
exported PDF:
	•	Written in Roman numerals → choose to publish as Roman numerals (as
typed) or as chord names in a key you pick. Handles triads, seventh
chords, standard inversions (6, 6/4, 6/5, 4/3, 4/2), and one level of
secondary dominant (e.g. V7/V). Anything unusual is shown as typed
rather than guessed at.
	•	Written as chord names → set the key the chart is written in and the
key you want to publish in; the app transposes every chord (including
slash-chord bass notes) automatically. Diatonic chords transpose exactly;
chromatic/borrowed chords use the closest simple spelling for the target
key, which occasionally differs by enharmonic spelling from a strict
interval-preserving transposition.
Why Python instead of the in-browser version
The chat artifact ran inside a sandboxed webpage that doesn’t grant full
localStorage/window.print() permissions — that’s what caused “Couldn’t
save” and the dead print button. This version is a normal Python web app
(built with Streamlit) that you run yourself, so it
has full access to your filesystem for saving and to reportlab for PDF
generation. Both problems go away because neither depends on browser
permissions anymore.
Running it