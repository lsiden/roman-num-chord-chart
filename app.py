"""
Chord Chart — a Roman-numeral chord chart writer.

Run locally:      streamlit run app.py
Deploy to iPad:    see README.md
"""

import html
import json
import re
import textwrap
from datetime import datetime
from io import BytesIO
from pathlib import Path

import streamlit as st
from reportlab.lib.pagesizes import letter as LETTER_SIZE
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

# --------------------------------------------------------------------------
# Persistence — a plain JSON file next to this script. No browser storage,
# no JavaScript permissions required, so it always works.
# --------------------------------------------------------------------------
DATA_FILE = Path(__file__).parent / "chord_chart_save.json"


def collect_data() -> dict:
    sections = []
    for i, sid in enumerate(st.session_state["section_order"]):
        n = st.session_state[f"mcount_{sid}"]
        sections.append(
            {
                "id": sid,
                "label": chr(65 + i),
                "name": st.session_state.get(f"name_{sid}", ""),
                "measure_count": n,
                "repeats": st.session_state.get(f"repeats_{sid}", 1),
                "measures": [st.session_state.get(f"m_{sid}_{i}", "") for i in range(n)],
                "key_changes": [get_key_change(sid, i) for i in range(n)],
            }
        )
    return {
        "title": st.session_state.get("title", "Untitled Chart"),
        "subtitle": st.session_state.get("subtitle", ""),
        "notes": st.session_state.get("notes", ""),
        "input_mode": st.session_state.get("input_mode", "roman"),
        "publish_display": st.session_state.get("publish_display", "Roman numerals"),
        "written_key": st.session_state.get("written_key", "C"),
        "publish_key": st.session_state.get("publish_key", "C"),
        "sections": sections,
    }


def save_to_disk():
    try:
        DATA_FILE.write_text(
            json.dumps(collect_data(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        st.session_state["save_status"] = "saved"
        st.session_state["save_time"] = datetime.now().strftime("%H:%M:%S")
    except Exception as e:
        st.session_state["save_status"] = "error"
        st.session_state["save_error"] = str(e)


def load_from_disk():
    if not DATA_FILE.exists():
        return
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return  # corrupted or unreadable — keep the defaults already in session_state

    st.session_state["title"] = data.get("title", "Untitled Chart")
    st.session_state["subtitle"] = data.get("subtitle", "")
    st.session_state["notes"] = data.get("notes", "")
    st.session_state["input_mode"] = data.get("input_mode", "roman")
    st.session_state["publish_display"] = data.get("publish_display", "Roman numerals")
    st.session_state["written_key"] = data.get("written_key", "C")
    st.session_state["publish_key"] = data.get("publish_key", "C")

    order = []
    max_id = 0
    for sec in data.get("sections", []):
        sid = sec.get("id") or (max_id + 1)
        max_id = max(max_id, sid)
        order.append(sid)
        st.session_state[f"name_{sid}"] = sec.get("name", "")
        st.session_state[f"repeats_{sid}"] = sec.get("repeats", 1)
        measures = sec.get("measures", [])
        mc = sec.get("measure_count", len(measures) or 8)
        st.session_state[f"mcount_{sid}"] = mc
        for i in range(mc):
            st.session_state[f"m_{sid}_{i}"] = measures[i] if i < len(measures) else ""

        key_changes = sec.get("key_changes")
        if key_changes is None:
            # migrate from the older whole-section key_shift, if present
            old_shift = sec.get("key_shift", 0)
            key_changes = [old_shift if (old_shift and idx == 0) else None for idx in range(mc)]
        for i in range(mc):
            v = key_changes[i] if i < len(key_changes) else None
            set_key_change(sid, i, v)
    if order:
        st.session_state["section_order"] = order
        st.session_state["next_id"] = max_id + 1


# --------------------------------------------------------------------------
# Chord parsing & music theory
#
#   "-7b5"  always becomes "ø"      (half-diminished)
#   "^"     always becomes "Δ"      (major seventh) — NOT a separator
#
# Everything after the root (roman numeral or note letter) is superscripted
# automatically, except a "/xyz" tail that names another chord/key/note
# (secondary dominants, slash-bass chords) — that stays normal-sized.
# --------------------------------------------------------------------------
NOTE_TO_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
LETTERS = "CDEFGAB"
MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11]  # semitones of scale degrees 1..7
FLAT_KEYS = {"F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"}
MAJOR_KEYS = ["C", "G", "D", "A", "E", "B", "F#", "C#", "F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"]
# Conventional single spelling per pitch class, used to name a modulation target.
KEY_BY_SEMITONE = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

ROMAN_TO_DEGREE = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}
_ROMAN_PATTERN = re.compile(r"^([#b]*)(VII|vii|III|iii|VI|vi|IV|iv|II|ii|V|v|I|i)")


def apply_chord_shorthand(text: str) -> str:
    text = text.replace("-7b5", "ø")
    text = text.replace("^", "Δ")
    return text


def split_slash_suffix(rest: str):
    """Separate a trailing '/something' from the superscriptable part.
    A '/' followed by a digit is a figured-bass inversion (e.g. 6/4) and
    stays fully superscripted; a '/' followed by a letter names another
    chord/note (secondary dominant, slash-bass) and is kept normal-sized."""
    if "/" not in rest:
        return rest, ""
    idx = rest.index("/")
    after = rest[idx + 1 :]
    if after[:1].isdigit():
        return rest, ""
    return rest[:idx], rest[idx:]


def parse_chord_token(token: str, mode: str):
    if mode == "roman":
        m = re.match(r"^[#b]*[nNivxIVX]+", token)
    else:
        m = re.match(r"^[A-Ga-g][#b]?", token)
    if not m or len(m.group(0)) == 0 or len(m.group(0)) == len(token):
        base, rest = token, ""
    else:
        base, rest = m.group(0), token[len(m.group(0)) :]
    sup, slash = split_slash_suffix(rest)
    return base, sup, slash


def chord_html(text: str, mode: str) -> str:
    if not text or not text.strip():
        return ""
    pieces = []
    for tok in text.strip().split():
        base, sup, slash = parse_chord_token(tok, mode)
        base, sup, slash = html.escape(base), html.escape(sup), html.escape(slash)
        piece = f"<span>{base}</span>"
        if sup:
            piece += f"<sup>{sup}</sup>"
        if slash:
            piece += f"<span>{slash}</span>"
        pieces.append(f'<span class="chord-token">{piece}</span>')
    return "".join(pieces)


# ---- note spelling helpers ------------------------------------------------
def note_semitone(note: str) -> int:
    letter = note[0].upper()
    acc = note[1:]
    return (NOTE_TO_SEMITONE[letter] + acc.count("#") - acc.count("b")) % 12


def spell_letter(letter: str, semitone: int) -> str:
    natural = NOTE_TO_SEMITONE[letter]
    diff = (semitone - natural) % 12
    if diff > 6:
        diff -= 12
    if diff == 0:
        return letter
    return letter + ("#" * diff if diff > 0 else "b" * (-diff))


def respell(semitone: int, prefer_flat: bool) -> str:
    best = None
    for L in LETTERS:
        diff = (semitone - NOTE_TO_SEMITONE[L]) % 12
        if diff > 6:
            diff -= 12
        cand = (abs(diff), L, diff)
        if best is None or cand[0] < best[0] or (
            cand[0] == best[0] and ((prefer_flat and cand[2] < best[2]) or (not prefer_flat and cand[2] > best[2]))
        ):
            best = cand
    _, L, diff = best
    return spell_letter(L, (NOTE_TO_SEMITONE[L] + diff) % 12)


def major_scale(tonic: str):
    letter = tonic[0].upper()
    acc = tonic[1:]
    tonic_semitone = note_semitone(letter + acc)
    start = LETTERS.index(letter)
    scale_letters = [LETTERS[(start + i) % 7] for i in range(7)]
    return [spell_letter(scale_letters[i], (tonic_semitone + MAJOR_INTERVALS[i]) % 12) for i in range(7)]


def shift_key(base_key: str, semitones: int) -> str:
    return KEY_BY_SEMITONE[(note_semitone(base_key) + semitones) % 12]


# ---- per-measure key changes (modulation) ----------------------------------
# A measure may carry an explicit semitone shift (clamped to -6..+6). Once
# set, it stays in effect for that measure and every later measure in the
# chart, until a different measure sets a new one.
NO_KEY_CHANGE = "–"
KEY_CHANGE_OPTIONS = [NO_KEY_CHANGE] + list(range(-6, 7))


def key_change_label(v) -> str:
    if v == NO_KEY_CHANGE:
        return NO_KEY_CHANGE
    return "0" if v == 0 else f"{v:+d}"


def get_key_change(sid: int, idx: int):
    v = st.session_state.get(f"mkey_{sid}_{idx}", NO_KEY_CHANGE)
    return None if v == NO_KEY_CHANGE else v


def set_key_change(sid: int, idx: int, v):
    v = NO_KEY_CHANGE if v is None else max(-6, min(6, int(v)))
    st.session_state[f"mkey_{sid}_{idx}"] = v


# ---- roman numeral -> chord name -------------------------------------------
def parse_roman_root(token: str):
    m = _ROMAN_PATTERN.match(token)
    if not m:
        return None
    prefix, numeral = m.group(1), m.group(2)
    shift = prefix.count("#") - prefix.count("b")
    degree = ROMAN_TO_DEGREE[numeral.upper()]
    is_upper = numeral[0].isupper()
    return shift, degree, is_upper, len(m.group(0))


_FIGURE_INFO = {"": (0, False), "6": (1, False), "6/4": (2, False), "7": (0, True),
                "6/5": (1, True), "4/3": (2, True), "4/2": (3, True), "2": (3, True)}


def resolve_figure(fig: str):
    """Returns (bass_index, has_seventh, seventh_kind, unrecognized_tail)."""
    if fig.startswith("Δ"):
        return 0, True, "maj7", fig[1:]
    if fig.lower().startswith("maj"):
        tail = fig[3:]
        return 0, True, "maj7", (tail[1:] if tail[:1] == "7" else tail)
    info = _FIGURE_INFO.get(fig)
    if info is not None:
        return info[0], info[1], None, ""
    return 0, False, None, fig  # unrecognized: root position, appended literally


def quality_to_suffix(quality: str, has7: bool, seventh_kind: str) -> str:
    if quality == "major":
        if not has7:
            return ""
        return "maj7" if seventh_kind == "maj7" else "7"
    if quality == "minor":
        if not has7:
            return "m"
        return "m(maj7)" if seventh_kind == "maj7" else "m7"
    if quality == "dim":
        return "°7" if has7 else "°"
    if quality == "halfdim":
        return "ø7" if has7 else "ø"
    if quality == "aug":
        return "+7" if has7 else "+"
    return ""


def seventh_interval(quality: str, seventh_kind: str) -> int:
    if seventh_kind == "maj7":
        return 11
    if quality == "dim":
        return 9
    return 10  # dominant / minor / half-diminished seventh


def roman_to_chord_name(token: str, key: str) -> str:
    try:
        parsed = parse_roman_root(token)
        if parsed is None:
            return token
        shift, degree, is_upper, consumed = parsed
        rest = token[consumed:]

        target_shift = target_degree = None
        if "/" in rest:
            idx = rest.index("/")
            after = rest[idx + 1 :]
            tgt = parse_roman_root(after)
            if tgt is not None and tgt[3] == len(after):
                target_shift, target_degree = tgt[0], tgt[1]
                rest = rest[:idx]

        quality = "major" if is_upper else "minor"
        if rest.startswith("°"):
            quality, rest = "dim", rest[1:]
        elif rest.startswith("ø"):
            quality, rest = "halfdim", rest[1:]
        elif rest.startswith("+"):
            quality, rest = "aug", rest[1:]

        scale = major_scale(key)
        if target_degree is not None:
            t_letter = scale[target_degree - 1][0]
            t_semitone = (note_semitone(scale[target_degree - 1]) + target_shift) % 12
            letter = LETTERS[(LETTERS.index(t_letter) + (degree - 1)) % 7]
            root_semitone = (t_semitone + MAJOR_INTERVALS[degree - 1] + shift) % 12
        else:
            letter = scale[degree - 1][0]
            root_semitone = (note_semitone(scale[degree - 1]) + shift) % 12
        root_spelled = spell_letter(letter, root_semitone)

        bass_index, has7, seventh_kind, tail = resolve_figure(rest)
        if quality == "halfdim":
            has7, seventh_kind = True, "min7"

        base_ivals = {"major": [0, 4, 7], "minor": [0, 3, 7], "dim": [0, 3, 6],
                      "aug": [0, 4, 8], "halfdim": [0, 3, 6]}[quality]
        ivals = list(base_ivals)
        if has7:
            ivals.append(seventh_interval(quality, seventh_kind))
        bass_index = min(bass_index, len(ivals) - 1)
        bass_semitone = (root_semitone + ivals[bass_index]) % 12
        bass_letter = LETTERS[(LETTERS.index(letter) + 2 * bass_index) % 7]
        bass_spelled = spell_letter(bass_letter, bass_semitone)

        chord_str = root_spelled + quality_to_suffix(quality, has7, seventh_kind) + tail
        if bass_index != 0:
            chord_str += "/" + bass_spelled
        return chord_str
    except Exception:
        return token  # anything we can't confidently parse is shown as-is


# ---- chord-name transposition ----------------------------------------------
def transpose_note(note: str, from_key: str, to_key: str) -> str:
    scale_from = major_scale(from_key)
    if note in scale_from:
        return major_scale(to_key)[scale_from.index(note)]
    shift = (note_semitone(to_key) - note_semitone(from_key)) % 12
    target_semitone = (note_semitone(note) + shift) % 12
    return respell(target_semitone, to_key in FLAT_KEYS)


def transpose_chord_token(token: str, from_key: str, to_key: str) -> str:
    if from_key == to_key:
        return token
    try:
        m = re.match(r"^[A-Ga-g][#b]?", token)
        if not m:
            return token
        root, rest = m.group(0), token[len(m.group(0)) :]
        new_root = transpose_note(root, from_key, to_key)
        if "/" in rest:
            idx = rest.index("/")
            pre, bass_part = rest[:idx], rest[idx + 1 :]
            bm = re.match(r"^[A-Ga-g][#b]?", bass_part)
            if bm:
                new_bass = transpose_note(bm.group(0), from_key, to_key)
                rest = pre + "/" + new_bass + bass_part[len(bm.group(0)) :]
        return new_root + rest
    except Exception:
        return token


# ---- what to actually display, given the current mode/publish settings ----
def current_display_parse_mode() -> str:
    if st.session_state["input_mode"] == "roman" and st.session_state.get("publish_display") == "Roman numerals":
        return "roman"
    return "name"


def resolve_display_text(raw_text: str, roman_key: str = None) -> str:
    if not raw_text or not raw_text.strip():
        return raw_text
    mode = st.session_state["input_mode"]
    out = []
    for tok in raw_text.strip().split():
        if mode == "roman" and st.session_state.get("publish_display") == "Chord names":
            key = roman_key if roman_key is not None else st.session_state.get("publish_key", "C")
            out.append(roman_to_chord_name(tok, key))
        elif mode == "name":
            wk, pk = st.session_state.get("written_key", "C"), st.session_state.get("publish_key", "C")
            out.append(transpose_chord_token(tok, wk, pk))
        else:
            out.append(tok)
    return " ".join(out)


# --------------------------------------------------------------------------
# Section helpers
# --------------------------------------------------------------------------
def new_section(measure_count: int = 8):
    sid = st.session_state["next_id"]
    st.session_state["next_id"] += 1
    st.session_state["section_order"].append(sid)
    st.session_state[f"name_{sid}"] = ""
    st.session_state[f"repeats_{sid}"] = 1
    st.session_state[f"mcount_{sid}"] = measure_count
    for i in range(measure_count):
        st.session_state[f"m_{sid}_{i}"] = ""
        set_key_change(sid, i, None)


def remove_section(sid: int):
    st.session_state["section_order"] = [s for s in st.session_state["section_order"] if s != sid]


def move_section(sid: int, direction: int):
    order = st.session_state["section_order"]
    idx = order.index(sid)
    target = idx + direction
    if 0 <= target < len(order):
        order[idx], order[target] = order[target], order[idx]


def on_measure_count_change(sid: int):
    n = st.session_state[f"mcount_{sid}"]
    n = max(1, min(64, n))
    st.session_state[f"mcount_{sid}"] = n
    for i in range(n):
        st.session_state.setdefault(f"m_{sid}_{i}", "")
        st.session_state.setdefault(f"mkey_{sid}_{i}", NO_KEY_CHANGE)


def on_measure_text_change(sid: int, idx: int):
    key = f"m_{sid}_{idx}"
    st.session_state[key] = apply_chord_shorthand(st.session_state[key])


# --------------------------------------------------------------------------
# Copy / paste — an in-app clipboard (session_state), since Streamlit has no
# direct access to the system clipboard. Holds either a range of measures
# or an entire section at a time.
# --------------------------------------------------------------------------
def copy_measures(sid: int, letter: str, start_1idx: int, end_1idx: int):
    n = st.session_state[f"mcount_{sid}"]
    start = max(1, min(start_1idx, n)) - 1
    end = max(1, min(end_1idx, n))
    if end <= start:
        return
    texts = [st.session_state.get(f"m_{sid}_{i}", "") for i in range(start, end)]
    key_changes = [get_key_change(sid, i) for i in range(start, end)]
    st.session_state["clipboard"] = {
        "type": "measures",
        "data": texts,
        "key_changes": key_changes,
        "desc": f"{len(texts)} measure{'s' if len(texts) != 1 else ''} from section {letter} (m.{start + 1}–{end})",
    }


def copy_section(sid: int, letter: str):
    n = st.session_state[f"mcount_{sid}"]
    st.session_state["clipboard"] = {
        "type": "section",
        "data": {
            "name": st.session_state.get(f"name_{sid}", ""),
            "repeats": st.session_state.get(f"repeats_{sid}", 1),
            "measures": [st.session_state.get(f"m_{sid}_{i}", "") for i in range(n)],
            "key_changes": [get_key_change(sid, i) for i in range(n)],
        },
        "desc": f"section {letter} ({n} measures)",
    }


def paste_measures_into(sid: int, at_1idx: int):
    clip = st.session_state.get("clipboard")
    if not clip or clip["type"] != "measures":
        return
    texts = clip["data"]
    kchanges = clip.get("key_changes", [None] * len(texts))
    n = st.session_state[f"mcount_{sid}"]
    old_texts = [st.session_state.get(f"m_{sid}_{i}", "") for i in range(n)]
    old_keys = [get_key_change(sid, i) for i in range(n)]
    at = max(0, min(at_1idx - 1, n))
    new_texts = (old_texts[:at] + list(texts) + old_texts[at:])[:64]
    new_keys = (old_keys[:at] + list(kchanges) + old_keys[at:])[:64]
    st.session_state[f"mcount_{sid}"] = len(new_texts)
    for i, v in enumerate(new_texts):
        st.session_state[f"m_{sid}_{i}"] = v
    for i, v in enumerate(new_keys):
        set_key_change(sid, i, v)


def paste_section_after(after_sid):
    clip = st.session_state.get("clipboard")
    if not clip or clip["type"] != "section":
        return
    data = clip["data"]
    new_sid = st.session_state["next_id"]
    st.session_state["next_id"] += 1
    st.session_state[f"name_{new_sid}"] = data["name"]
    st.session_state[f"repeats_{new_sid}"] = data["repeats"]
    measures = data["measures"]
    key_changes = data.get("key_changes", [None] * len(measures))
    st.session_state[f"mcount_{new_sid}"] = len(measures)
    for i, v in enumerate(measures):
        st.session_state[f"m_{new_sid}_{i}"] = v
    for i, v in enumerate(key_changes):
        set_key_change(new_sid, i, v)
    order = st.session_state["section_order"]
    if after_sid is None:
        order.append(new_sid)
    else:
        order.insert(order.index(after_sid) + 1, new_sid)


def replace_section(sid: int):
    clip = st.session_state.get("clipboard")
    if not clip or clip["type"] != "section":
        return
    data = clip["data"]
    st.session_state[f"name_{sid}"] = data["name"]
    st.session_state[f"repeats_{sid}"] = data["repeats"]
    measures = data["measures"]
    key_changes = data.get("key_changes", [None] * len(measures))
    st.session_state[f"mcount_{sid}"] = len(measures)
    for i, v in enumerate(measures):
        st.session_state[f"m_{sid}_{i}"] = v
    for i, v in enumerate(key_changes):
        set_key_change(sid, i, v)


def clear_clipboard():
    st.session_state["clipboard"] = None


# --------------------------------------------------------------------------
# Initial state
# --------------------------------------------------------------------------
if "initialized" not in st.session_state:
    st.session_state["initialized"] = True
    st.session_state["title"] = "Untitled Chart"
    st.session_state["subtitle"] = "Key of C · ♩ = 96"
    st.session_state["notes"] = ""
    st.session_state["input_mode"] = "roman"
    st.session_state["publish_display"] = "Roman numerals"
    st.session_state["written_key"] = "C"
    st.session_state["publish_key"] = "C"
    st.session_state["show_key_change_controls"] = True
    st.session_state["save_status"] = "idle"
    st.session_state["clipboard"] = None
    st.session_state["next_id"] = 2
    st.session_state["section_order"] = [1]
    st.session_state["name_1"] = ""
    st.session_state["repeats_1"] = 1
    st.session_state["mcount_1"] = 8
    for i in range(8):
        st.session_state[f"m_1_{i}"] = ""
        set_key_change(1, i, None)
    load_from_disk()  # pull in a previously saved chart, if one exists

# --------------------------------------------------------------------------
# Page setup + styling
# --------------------------------------------------------------------------
st.set_page_config(page_title="Chord Chart", layout="wide")

INK, ACCENT, PAPER, PAPER_CARD, RULE = "#2A241E", "#7A2E2E", "#EEEAE0", "#F6F3EA", "#C9C0AC"

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,500;0,600;1,500;1,600&family=JetBrains+Mono:wght@400;500;600&display=swap');
    .stApp {{ background: {PAPER}; }}
    .block-container {{ padding-top: 2rem; max-width: 1200px; }}

    .chart-paper {{ background: #FBF9F3; border: 1px solid {RULE}; padding: 24px 28px; }}
    .chart-title {{ font-family: 'EB Garamond', serif; font-weight: 600; font-size: 32px; color: {INK}; }}
    .chart-subtitle {{ font-family: 'EB Garamond', serif; font-style: italic; font-size: 15px; color: #6b6459; margin-bottom: 14px; }}

    .notes-box {{ margin-bottom: 26px; }}
    .notes-label {{ display:block; margin-bottom:4px; font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:0.08em; color:#9b9284; }}
    .notes-text {{ font-family:'EB Garamond', serif; font-style:italic; font-size:15px; color:{INK}; border:1px solid {RULE}; background:{PAPER_CARD}; padding:8px 12px; white-space:pre-wrap; min-height: 1.4em; }}

    .section-block {{ margin-bottom: 34px; }}
    .section-header {{ display:flex; align-items:baseline; gap:12px; margin-bottom:8px; }}
    .section-letter {{ font-family:'EB Garamond', serif; font-weight:600; font-size:24px; color:{INK}; }}
    .section-name {{ font-family:'JetBrains Mono',monospace; font-size:12px; color:#6b6459; letter-spacing:0.03em; }}
    .section-repeat-note {{ font-family:'JetBrains Mono',monospace; font-size:11px; color:{ACCENT}; }}
    .section-hr {{ flex:1; border-bottom:1px solid {RULE}; }}

    .system-row {{ display:flex; }}
    .measure-box {{ position:relative; flex:1; min-width:86px; min-height:60px; display:flex; align-items:center; justify-content:center;
                    border-top:1.5px solid {INK}; border-bottom:1.5px solid {INK}; }}
    .measure-index {{ position:absolute; top:3px; left:7px; font-family:'JetBrains Mono',monospace; font-size:9px; color:{RULE}; }}
    .key-change {{ position:absolute; top:3px; right:7px; font-family:'JetBrains Mono',monospace; font-size:9px; font-weight:600; color:{ACCENT}; }}
    .chord {{ font-family:'EB Garamond', serif; font-style:italic; font-size:21px; color:{INK}; }}
    .chord-token {{ margin: 0 6px; white-space: nowrap; }}
    .chord-token sup {{ font-size:0.6em; margin-left:1px; }}

    .repeat-start, .repeat-end {{ position:absolute; top:0; bottom:0; display:flex; align-items:center; }}
    .repeat-start {{ left:-2px; }}
    .repeat-end {{ right:-2px; }}
    .repeat-start .bar, .repeat-end .bar {{ width:4px; align-self:stretch; background:{ACCENT}; }}
    .repeat-start .dots, .repeat-end .dots {{ display:flex; flex-direction:column; gap:5px; }}
    .repeat-start .dots {{ margin-left:3px; }}
    .repeat-end .dots {{ margin-right:3px; }}
    .repeat-start .dots span, .repeat-end .dots span {{ width:5px; height:5px; border-radius:9999px; background:{ACCENT}; display:block; }}
    .repeat-end .count {{ position:absolute; top:-18px; right:0; font-family:'JetBrains Mono',monospace; font-weight:600; font-size:11px; color:{ACCENT}; }}

    .editor-card {{ background:{PAPER_CARD}; border:1px solid {RULE}; padding:14px; margin-bottom:14px; }}
    .editor-letter {{ display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; border:1.5px solid {INK};
                       font-family:'EB Garamond', serif; font-size:16px; color:{INK}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
col_title, col_actions = st.columns([3, 2])

with col_title:
    st.text_input("Title", key="title", label_visibility="collapsed", placeholder="Chart title")
    st.text_input("Subtitle", key="subtitle", label_visibility="collapsed", placeholder="Key, tempo…")

with col_actions:
    a, b, c1 = st.columns([1.3, 1, 1])
    with a:
        if st.session_state.get("save_status") == "error":
            st.error(f"Couldn't save: {st.session_state.get('save_error', '')}", icon="⚠️")
        elif st.session_state.get("save_status") == "saved":
            st.caption(f"💾 Saved to disk at {st.session_state.get('save_time', '')}")
        else:
            st.caption("💾 Saving…")
    with b:
        st.button("Save now", on_click=save_to_disk, use_container_width=True)
    with c1:
        pdf_placeholder = st.container()

# --------------------------------------------------------------------------
# Input mode + publish/transpose settings
# --------------------------------------------------------------------------
with st.expander("Input mode & publish settings", expanded=False):
    mode_col, settings_col = st.columns([1, 2])
    with mode_col:
        mode_label = st.radio(
            "Enter chords as",
            ["Roman numerals", "Chord names"],
            index=0 if st.session_state["input_mode"] == "roman" else 1,
            key="input_mode_radio",
        )
        st.session_state["input_mode"] = "roman" if mode_label == "Roman numerals" else "name"
        if st.session_state["input_mode"] == "roman":
            st.caption(
                "e.g. V7, ii6, vii°7, V7/V — type the numeral then anything else; "
                "it's superscripted automatically. \"^\" always means major 7th (Δ)."
            )
            st.toggle("Show key-change dropdowns on each measure", key="show_key_change_controls")
        else:
            st.caption(
                "e.g. E7, Ab^ (= Ab major 7), Dm7, C/E — type the root then anything else; "
                "it's superscripted automatically. \"^\" always means major 7th (Δ)."
            )

    with settings_col:
        if st.session_state["input_mode"] == "roman":
            st.radio(
                "Publish chart as",
                ["Roman numerals", "Chord names"],
                key="publish_display",
                horizontal=True,
            )
            if st.session_state["publish_display"] == "Chord names":
                st.selectbox("Key for chord names", MAJOR_KEYS, key="publish_key")
                st.caption(
                    "Converts triads, seventh chords, standard inversions (6, 6/4, 6/5, 4/3, 4/2), "
                    "and one level of secondary dominant (e.g. V7/V). Anything else is shown as typed."
                )
        else:
            k1, k2 = st.columns(2)
            with k1:
                st.selectbox("Chart is written in", MAJOR_KEYS, key="written_key")
            with k2:
                st.selectbox("Publish in key", MAJOR_KEYS, key="publish_key")
            if st.session_state["written_key"] != st.session_state["publish_key"]:
                st.caption(f"Transposing from {st.session_state['written_key']} to {st.session_state['publish_key']}.")

# --------------------------------------------------------------------------
# Editor + preview
# --------------------------------------------------------------------------
editor_col, preview_col = st.columns([2, 3])

with editor_col:
    st.text_area("Notes", key="notes", placeholder="Tempo, feel, dynamics, performance notes…", height=80)

    clip = st.session_state.get("clipboard")
    if clip:
        cc1, cc2 = st.columns([4, 1])
        with cc1:
            st.caption(f"📋 Copied: {clip['desc']}")
        with cc2:
            st.button("Clear", key="clear_clip", on_click=clear_clipboard, use_container_width=True)

    for idx, sid in enumerate(list(st.session_state["section_order"])):
        letter = chr(65 + idx)
        with st.container():
            st.markdown('<div class="editor-card">', unsafe_allow_html=True)
            top = st.columns([0.6, 3.2, 0.5, 0.5, 0.5])
            with top[0]:
                st.markdown(f'<span class="editor-letter">{letter}</span>', unsafe_allow_html=True)
            with top[1]:
                st.text_input(
                    "Section name",
                    key=f"name_{sid}",
                    label_visibility="collapsed",
                    placeholder="Section name (optional) — Verse, Chorus…",
                )
            with top[2]:
                st.button("↑", key=f"up_{sid}", disabled=idx == 0, on_click=move_section, args=(sid, -1))
            with top[3]:
                st.button("↓", key=f"down_{sid}", disabled=idx == len(st.session_state["section_order"]) - 1, on_click=move_section, args=(sid, 1))
            with top[4]:
                st.button("✕", key=f"del_{sid}", on_click=remove_section, args=(sid,))

            m1, m2 = st.columns(2)
            with m1:
                st.number_input(
                    "Measures", min_value=1, max_value=64, key=f"mcount_{sid}",
                    on_change=on_measure_count_change, args=(sid,),
                )
            with m2:
                st.number_input("Repeat ×", min_value=1, max_value=20, key=f"repeats_{sid}")

            if st.session_state["input_mode"] == "roman":
                st.caption("Roman-numeral mode: set a key change on any measure below to modulate from there on.")

            n = st.session_state[f"mcount_{sid}"]
            for row_start in range(0, n, 4):
                cols = st.columns(4)
                for c in range(4):
                    i = row_start + c
                    if i >= n:
                        continue
                    with cols[c]:
                        st.caption(f"m.{i + 1}")
                        st.text_input(
                            f"measure {i}", key=f"m_{sid}_{i}", label_visibility="collapsed",
                            placeholder=("V7" if st.session_state["input_mode"] == "roman" else "E7"),
                            on_change=on_measure_text_change, args=(sid, i),
                        )
                        if st.session_state["input_mode"] == "roman":
                            st.session_state.setdefault(f"mkey_{sid}_{i}", NO_KEY_CHANGE)
                            if st.session_state.get("show_key_change_controls", True):
                                st.selectbox(
                                    f"key change m.{i}", options=KEY_CHANGE_OPTIONS,
                                    format_func=key_change_label, key=f"mkey_{sid}_{i}",
                                    label_visibility="collapsed",
                                )

            with st.expander("Copy / paste"):
                st.session_state[f"copyfrom_{sid}"] = min(st.session_state.get(f"copyfrom_{sid}", 1), n)
                st.session_state[f"copyto_{sid}"] = min(st.session_state.get(f"copyto_{sid}", n), n)
                cp1, cp2, cp3 = st.columns([1, 1, 1.4])
                with cp1:
                    st.number_input("From m.", min_value=1, max_value=n, key=f"copyfrom_{sid}")
                with cp2:
                    st.number_input("To m.", min_value=1, max_value=n, key=f"copyto_{sid}")
                with cp3:
                    st.write("")
                    st.button(
                        "Copy measures",
                        key=f"copymeasures_{sid}",
                        use_container_width=True,
                        on_click=copy_measures,
                        args=(sid, letter, st.session_state[f"copyfrom_{sid}"], st.session_state[f"copyto_{sid}"]),
                    )
                st.button(
                    "Copy whole section",
                    key=f"copysection_{sid}",
                    use_container_width=True,
                    on_click=copy_section,
                    args=(sid, letter),
                )

                clip = st.session_state.get("clipboard")
                if clip and clip["type"] == "measures":
                    st.session_state[f"pasteat_{sid}"] = min(st.session_state.get(f"pasteat_{sid}", n + 1), n + 1)
                    pp1, pp2 = st.columns([1, 1.4])
                    with pp1:
                        st.number_input("Insert before m.", min_value=1, max_value=n + 1, key=f"pasteat_{sid}")
                    with pp2:
                        st.write("")
                        st.button(
                            "Paste measures",
                            key=f"pastemeasures_{sid}",
                            use_container_width=True,
                            on_click=paste_measures_into,
                            args=(sid, st.session_state[f"pasteat_{sid}"]),
                        )
                elif clip and clip["type"] == "section":
                    pp1, pp2 = st.columns(2)
                    with pp1:
                        st.button(
                            "Paste as new section after",
                            key=f"pasteafter_{sid}",
                            use_container_width=True,
                            on_click=paste_section_after,
                            args=(sid,),
                        )
                    with pp2:
                        st.button(
                            "Replace this section",
                            key=f"pastereplace_{sid}",
                            use_container_width=True,
                            on_click=replace_section,
                            args=(sid,),
                        )

            st.markdown("</div>", unsafe_allow_html=True)

    st.button("＋ Add section", on_click=new_section, use_container_width=True)
    clip = st.session_state.get("clipboard")
    if clip and clip["type"] == "section":
        st.button(
            "＋ Paste as new section",
            on_click=paste_section_after,
            args=(None,),
            use_container_width=True,
        )

with preview_col:
    data = collect_data()
    _parse_mode = current_display_parse_mode()
    _running_shift = 0  # persists across sections until a measure sets a new one

    parts = [f'<div class="chart-paper"><div class="chart-title">{html.escape(data["title"])}</div>']
    parts.append(f'<div class="chart-subtitle">{html.escape(data["subtitle"])}</div>')

    if data["notes"].strip():
        parts.append(
            '<div class="notes-box"><span class="notes-label">NOTES</span>'
            f'<div class="notes-text">{html.escape(data["notes"])}</div></div>'
        )

    for sec in data["sections"]:
        parts.append('<div class="section-block">')
        header = f'<span class="section-letter">{sec["label"]}</span>'
        if sec["name"]:
            header += f'<span class="section-name">{html.escape(sec["name"].upper())}</span>'
        if sec["repeats"] > 1:
            header += f'<span class="section-repeat-note">play ×{sec["repeats"]}</span>'
        header += '<span class="section-hr"></span>'
        parts.append(f'<div class="section-header">{header}</div>')

        measures = sec["measures"]
        key_changes = sec.get("key_changes", [None] * len(measures))
        n = len(measures)
        for row_start in range(0, n, 4):
            row = measures[row_start : row_start + 4]
            parts.append('<div class="system-row">')
            for c, text in enumerate(row):
                gi = row_start + c
                is_first = gi == 0
                is_last = gi == n - 1
                is_row_end = c == len(row) - 1
                border_right = ("3px" if is_last else "1.5px") + f" solid {INK}" if is_row_end else "none"
                pad_l = 14 if (is_first and sec["repeats"] > 1) else 10
                pad_r = 14 if (is_last and sec["repeats"] > 1) else 10
                marks = ""
                if is_first and sec["repeats"] > 1:
                    marks += '<div class="repeat-start"><div class="bar"></div><div class="dots"><span></span><span></span></div></div>'
                if is_last and sec["repeats"] > 1:
                    marks += (
                        f'<div class="repeat-end"><span class="count">×{sec["repeats"]}</span>'
                        '<div class="dots"><span></span><span></span></div><div class="bar"></div></div>'
                    )
                mod_key = None
                if data["input_mode"] == "roman":
                    kc = key_changes[gi] if gi < len(key_changes) else None
                    if kc is not None:
                        _running_shift = kc
                        mod_key = shift_key(data.get("publish_key", "C"), _running_shift)
                        marks += f'<div class="key-change">→ {mod_key} ({_running_shift:+d})</div>'
                effective_key = (
                    (data.get("publish_key", "C") if _running_shift == 0 else shift_key(data.get("publish_key", "C"), _running_shift))
                    if data["input_mode"] == "roman" else None
                )
                parts.append(
                    f'<div class="measure-box" style="border-left:1.5px solid {INK};border-right:{border_right};'
                    f'padding-left:{pad_l}px;padding-right:{pad_r}px;">'
                    f'<span class="measure-index">{gi + 1}</span>'
                    f'<span class="chord">{chord_html(resolve_display_text(text, effective_key), _parse_mode)}</span>{marks}</div>'
                )
            parts.append("</div>")
        parts.append("</div>")

    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)

# --------------------------------------------------------------------------
# PDF export (this replaces the browser print button — it always works
# because the file is generated in Python, not via the browser)
# --------------------------------------------------------------------------
def render_chord_pdf(c: canvas.Canvas, text: str, bx: float, by: float, bw: float, bh: float, mode: str):
    if not text or not text.strip():
        return
    pieces = [parse_chord_token(tok, mode) for tok in text.strip().split()]
    base_font, sup_font, base_size, sup_size = "Times-BoldItalic", "Times-BoldItalic", 15, 9
    seg_widths = []
    for base, sup, slash in pieces:
        w = stringWidth(base, base_font, base_size)
        if sup:
            w += stringWidth(sup, sup_font, sup_size) + 1
        if slash:
            w += stringWidth(slash, base_font, base_size)
        seg_widths.append(w)
    total = sum(seg_widths) + 8 * max(0, len(pieces) - 1)
    curx = bx + bw / 2 - total / 2
    cy = by + bh / 2 - 4
    for (base, sup, slash), w in zip(pieces, seg_widths):
        c.setFont(base_font, base_size)
        c.drawString(curx, cy, base)
        curx += stringWidth(base, base_font, base_size)
        if sup:
            c.setFont(sup_font, sup_size)
            c.drawString(curx + 1, cy + 6, sup)
            curx += stringWidth(sup, sup_font, sup_size) + 1
        if slash:
            c.setFont(base_font, base_size)
            c.drawString(curx, cy, slash)
            curx += stringWidth(slash, base_font, base_size)
        curx += 8


def build_pdf(data: dict, parse_mode: str) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER_SIZE)
    width, height = LETTER_SIZE
    margin = 0.6 * inch
    x, y = margin, height - margin

    c.setFont("Times-Bold", 20)
    c.drawString(x, y, data["title"] or "Untitled Chart")
    y -= 20
    if data["subtitle"]:
        c.setFont("Times-Italic", 11)
        c.drawString(x, y, data["subtitle"])
        y -= 18
    if data["notes"].strip():
        c.setFont("Times-Italic", 10)
        for line in textwrap.wrap(data["notes"], 95) or [""]:
            c.drawString(x, y, line)
            y -= 13
        y -= 6

    box_w = (width - 2 * margin) / 4
    box_h = 0.55 * inch
    running_shift = 0  # persists across sections, same as the on-screen preview

    for sec in data["sections"]:
        if y < margin + box_h * 2:
            c.showPage()
            y = height - margin
        c.setFont("Times-Bold", 13)
        label = sec["label"]
        if sec["name"]:
            label += "   " + sec["name"].upper()
        if sec["repeats"] > 1:
            label += f"   (play x{sec['repeats']})"
        c.drawString(x, y, label)
        y -= 6
        c.line(x, y, width - margin, y)
        y -= box_h

        measures = sec["measures"]
        key_changes = sec.get("key_changes", [None] * len(measures))
        n = len(measures)
        for row_start in range(0, n, 4):
            if y < margin:
                c.showPage()
                y = height - margin
            row = measures[row_start : row_start + 4]
            for i, text in enumerate(row):
                gi = row_start + i
                bx = x + i * box_w
                c.setLineWidth(1)
                c.rect(bx, y, box_w, box_h)
                if data["input_mode"] == "roman":
                    kc = key_changes[gi] if gi < len(key_changes) else None
                    if kc is not None:
                        running_shift = kc
                        mod_key = shift_key(data.get("publish_key", "C"), running_shift)
                        c.setFont("Helvetica-Bold", 7)
                        c.setFillColorRGB(0.48, 0.18, 0.18)
                        c.drawRightString(bx + box_w - 3, y + box_h - 9, f"\u2192 {mod_key} ({running_shift:+d})")
                        c.setFillColorRGB(0, 0, 0)
                    effective_key = data.get("publish_key", "C") if running_shift == 0 else shift_key(data.get("publish_key", "C"), running_shift)
                else:
                    effective_key = None
                render_chord_pdf(c, resolve_display_text(text, effective_key), bx, y, box_w, box_h, parse_mode)
            if sec["repeats"] > 1:
                is_first_row = row_start == 0
                is_last_row = row_start + 4 >= n
                c.setStrokeColorRGB(0.48, 0.18, 0.18)
                if is_first_row:
                    c.setLineWidth(3)
                    c.line(x, y, x, y + box_h)
                if is_last_row:
                    end_x = x + len(row) * box_w
                    c.setLineWidth(3)
                    c.line(end_x, y, end_x, y + box_h)
                    c.setFont("Helvetica-Bold", 9)
                    c.setFillColorRGB(0.48, 0.18, 0.18)
                    c.drawRightString(end_x, y + box_h + 4, f"x{sec['repeats']}")
                    c.setFillColorRGB(0, 0, 0)
                c.setLineWidth(1)
                c.setStrokeColorRGB(0, 0, 0)
            y -= box_h
        y -= 18

    c.save()
    buf.seek(0)
    return buf.getvalue()


with pdf_placeholder:
    st.download_button(
        "⬇ PDF",
        data=build_pdf(data, _parse_mode),
        file_name=f"{(data['title'] or 'chord-chart').strip().replace(' ', '-')}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
