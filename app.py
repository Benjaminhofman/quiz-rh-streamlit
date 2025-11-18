import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, timezone
import json
import random
import os
import streamlit as st


# =========================
# CONFIG GLOBALE
# =========================
SHEET_NAME = "QuizRH"  # nom du fichier Google Sheets

QUIZZES = {
    "Assistant": {
        "Q": "Questions",
        "R": "Resultats",
        "DUR": 5,   # minutes
        "title": "🧪 Quiz - Assistant",
        "cta": "🎯 Quiz Assistant",
        "color": "#2563eb",
    },
    "Collaborateurs": {
        "Q": "Questions_Collab",
        "R": "Resultats_Collab",
        "DUR": 5,   # minutes
        "title": "🧪 Quiz - Collaborateurs d'expertise comptable",
        "cta": "📘 Quiz Collaborateurs",
        "color": "#059669",
    },
}
TIMEZONE = timezone.utc

st.set_page_config(page_title="Quiz RH", page_icon="✅", layout="centered")

# =========================
# Connexion Google Sheets
# =========================
def get_gspread_client():
    """Connexion à Google Sheets : d'abord st.secrets (Cloud), sinon credentials.json (local)."""
    try:
        info = st.secrets.get("gcp_service_account", None)
    except Exception:
        info = None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    if info:  # mode Cloud
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    else:  # mode local
        if not os.path.exists("credentials.json"):
            st.error(
                "Fichier 'credentials.json' introuvable à côté de app.py.\n"
                "Télécharge la clé JSON du compte de service, place-la ici et "
                "partage la feuille Google avec l’e-mail du service account (Éditeur)."
            )
            st.stop()
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)

    return gspread.authorize(creds)

def get_sheet():
    gc = get_gspread_client()
    return gc.open(SHEET_NAME)

# =========================
# Chargement des questions (par onglet)
# =========================
@st.cache_data(ttl=30)
def load_questions_from_sheet(sheet_name: str, questions_tab: str):
    sh = get_gspread_client().open(sheet_name)
    ws = sh.worksheet(questions_tab)
    rows = ws.get_all_records()
    questions = []
    for r in rows:
        qid = str(r.get("id")).strip()
        qtype = (r.get("type") or "single").strip().lower()
        texte = str(r.get("texte")).strip()
        raw_choices = str(r.get("choix")).split("|")
        choices = [c.strip() for c in raw_choices if c.strip()]
        raw_correct = str(r.get("correct")).split("|")
        correct = [c.strip() for c in raw_correct if c.strip()]
        points = int(r.get("points") or 1)
        if not qid or not texte or not choices or not correct:
            continue
        questions.append({
            "id": qid,
            "type": "multi" if qtype == "multi" else "single",
            "texte": texte,
            "choices": choices,
            "correct": correct,
            "points": points
        })
    return questions

# =========================
# Gestion des tentatives (par onglet de résultats)
# =========================
def find_attempt_row(ws_results, user: str):
    """Retourne (row_index, record_dict) si l'utilisateur a déjà une ligne, sinon (None, None)."""
    records = ws_results.get_all_records()
    for i, rec in enumerate(records, start=2):  # ligne 1 = en-têtes
        if str(rec.get("user", "")).strip().lower() == user.lower():
            return i, rec
    return None, None

def start_or_resume_attempt(ws_results, user: str, duration_minutes: int):
    now = datetime.now(TIMEZONE)
    row_idx, rec = find_attempt_row(ws_results, user)
    if row_idx:
        finished = str(rec.get("finished_at", "")).strip()
        if finished:
            return row_idx, rec, "finished"
        return row_idx, rec, "ongoing"
    must_end = now + timedelta(minutes=duration_minutes)
    ws_results.append_row(
        [user, now.isoformat(), must_end.isoformat(), "", "", ""],
        value_input_option="RAW"
    )
    records = ws_results.get_all_records()
    new_idx = len(records) + 1  # +1 car en-têtes
    new_rec = {
        "user": user,
        "started_at": now.isoformat(),
        "must_end_at": must_end.isoformat(),
        "finished_at": "",
        "score": "",
        "details_json": ""
    }
    return new_idx, new_rec, "created"

def update_result(ws_results, row_idx: int, score_text: str, details_obj: dict):
    now = datetime.now(TIMEZONE).isoformat()
    ws_results.update_cell(row_idx, 4, now)                 # finished_at
    ws_results.update_cell(row_idx, 5, str(score_text))     # score (ex "7/10")
    ws_results.update_cell(row_idx, 6, json.dumps(details_obj, ensure_ascii=False))  # details_json

# =========================
# PAGE D’ACCUEIL (logo + 2 boutons)
# =========================
def landing():
    st.markdown("<h1 style='text-align:center;'>Bienvenue sur le Quiz technique </h1>", unsafe_allow_html=True)

    # Logo centré
    logo_path = None
    for file in ["logo.png", "OIP.webp", "logo.jpg", "logo.jpeg"]:
        if os.path.exists(file):
            logo_path = file
            break

    if logo_path:
        st.image(logo_path, width=180)
    else:
        st.info("⚠️ Logo non trouvé (ajoutez 'OIP.webp' ou 'logo.png' dans le dossier).")

    st.markdown("<p style='opacity:.8'>Choisissez votre questionnaire :</p>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button(QUIZZES["Assistant"]["cta"], use_container_width=True):
            st.session_state["quiz_name"] = "Assistant"
    with col2:
        if st.button(QUIZZES["Collaborateurs"]["cta"], use_container_width=True):
            st.session_state["quiz_name"] = "Collaborateurs"

# =========================
# APP
# =========================
if "quiz_name" not in st.session_state:
    landing()
    st.stop()

# Sinon, on est dans un quiz
quiz_name = st.session_state["quiz_name"]
cfg = QUIZZES[quiz_name]
QUESTIONS_TAB = cfg["Q"]
RESULTS_TAB   = cfg["R"]
DURATION_MINUTES = cfg["DUR"]

st.title(cfg.get("title", "🧪 Quiz"))

st.markdown("**Entrez votre e-mail** pour commencer. Une seule tentative est autorisée **par questionnaire**. Vous disposez de 5 min à compter du clic sur démarrer pour finir le questionnaire")
user_input = st.text_input("E-mail", placeholder="prenom.nom@entreprise.com")
start = st.button("Démarrer")

if start:
    if not user_input.strip():
        st.error("Veuillez saisir votre e-mail")
        st.stop()

    new_user = user_input.strip()
    prev_user = st.session_state.get("user")

    st.session_state["user"] = new_user

    if prev_user and prev_user != new_user:
        for k in list(st.session_state.keys()):
            if k.startswith("quiz_frozen::"):
                del st.session_state[k]
            if k.startswith(f"{quiz_name}__{prev_user}__q_"):
                del st.session_state[k]

if "user" not in st.session_state:
    st.stop()

# --- Anti-copie et anti-impression global ---
st.markdown("""
<style>
/* Empêche la sélection partout sauf dans les champs de saisie */
html, body, [data-testid="stAppViewContainer"] .block-container *:not(input):not(textarea):not([contenteditable="true"]) {
  -webkit-user-select: none !important;
  -ms-user-select: none !important;
  user-select: none !important;
}

/* Empêche le drag (copie par glisser) */
[data-testid="stAppViewContainer"] .block-container * {
  -webkit-user-drag: none !important;
  user-drag: none !important;
}

/* Autorise la sélection uniquement dans les champs utiles */
input, textarea, [contenteditable="true"] {
  -webkit-user-select: text !important;
  user-select: text !important;
}

/* --- Blocage de l'impression --- */
@media print {
  /* Cache tout le contenu Streamlit */
  body * {
    display: none !important;
    visibility: hidden !important;
  }
  /* Optionnel : message à la place */
  body::before {
    content: "⚠️ Impression désactivée pour ce quiz.";
    display: block;
    text-align: center;
    margin-top: 50vh;
    font-size: 24px;
    color: red;
    visibility: visible !important;
  }
}
</style>
""", unsafe_allow_html=True)


user = st.session_state["user"]

# Accès à la feuille
try:
    sh = get_sheet()
    ws_q = sh.worksheet(QUESTIONS_TAB)
    ws_r = sh.worksheet(RESULTS_TAB)
except Exception as e:
    st.error("Impossible d'accéder aux onglets Google Sheets (nom ou droits).")
    st.exception(e)
    st.stop()

# Démarre / reprend la tentative
try:
    row_idx, rec, status = start_or_resume_attempt(ws_r, user, DURATION_MINUTES)
except Exception as e:
    st.error("Erreur lors de l'initialisation de la tentative.")
    st.exception(e)
    st.stop()

if status == "finished":
    st.error("Vous avez déjà terminé ce test pour ce questionnaire. Une seule tentative autorisée.")
    st.stop()


# Sécurité : si temps écoulé → on bloque
must_end_raw = rec.get("must_end_at", "")
try:
    must_end = datetime.fromisoformat(must_end_raw)
except Exception:
    must_end = datetime.now(TIMEZONE)
if datetime.now(TIMEZONE) > must_end:
    st.error("⏰ Temps écoulé. Votre tentative est expirée.")
    st.stop()


import streamlit.components.v1 as components

# --- Compte à rebours / Sablier visuel ---
# Calcule le temps restant côté serveur (source de vérité)
now_utc = datetime.now(TIMEZONE)
remaining_ms = int(max(0, (must_end - now_utc).total_seconds()) * 1000)
total_ms = int(DURATION_MINUTES * 60 * 1000)

# Couleur du quiz courant (déjà dans cfg)
bar_color = cfg.get("color", "#2563eb")

components.html(f"""
<div style="margin: 8px 0 18px 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;">
  <div id="timer" style="font-size:28px; text-align:center; margin-bottom:8px;">
    ⏳ Calcul du temps…
  </div>

  <!-- Barre de progression façon “sablier” qui se vide -->
  <div style="height:14px; background:#eee; border-radius:8px; overflow:hidden;">
    <div id="bar" style="height:100%; width:100%; background:{bar_color}; transition: width 1s linear;"></div>
  </div>

  <div style="text-align:center; opacity:.75; font-size:12px; margin-top:6px;">
    Le sablier se vide au fil du temps restant.
  </div>
</div>

<script>
  const total = {total_ms};
  let remaining = {remaining_ms};

  const timerEl = document.getElementById('timer');
  const barEl = document.getElementById('bar');

  function fmt(ms) {{
    const s = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
  }}

  function hourglassEmoji(ms) {{
    // Alterne ⏳ / ⌛ pour donner l'effet “sablier”
    return Math.floor(ms / 1000) % 2 === 0 ? '⏳' : '⌛';
  }}

  function tick() {{
    const pct = Math.max(0, Math.min(100, (remaining / total) * 100));
    barEl.style.width = pct + '%';
    timerEl.textContent = hourglassEmoji(remaining) + ' Temps restant : ' + fmt(remaining);

    remaining -= 1000;
    if (remaining < 0) {{
      clearInterval(iv);
      barEl.style.width = '0%';
      timerEl.textContent = '⌛ Temps écoulé';
      // Optionnel : on désactive les inputs s'ils sont visibles côté client
      const btns = [...document.querySelectorAll('button')];
      btns.forEach(b => b.disabled = true);
    }}
  }}

  tick();
  const iv = setInterval(tick, 1000);
</script>
""", height=130)

# Charger & figer les questions
frozen_key = f"quiz_frozen::{quiz_name}::{user}"
if frozen_key not in st.session_state:
    try:
        base = load_questions_from_sheet(SHEET_NAME, QUESTIONS_TAB)
    except Exception as e:
        st.error("Erreur de chargement des questions.")
        st.exception(e)
        st.stop()

    frozen = []
    for q in base:
        ch = q["choices"][:]
        random.shuffle(ch)
        frozen.append({**q, "choices": ch})
    random.shuffle(frozen)
    st.session_state[frozen_key] = frozen

questions = st.session_state[frozen_key]
if not questions:
    st.warning("Aucune question trouvée dans l'onglet.")
    st.stop()

with st.form("quiz_form"):
    answers = {}
    for q in questions:
        st.markdown(f"**{q['texte']}**")
        widget_key = f"{quiz_name}__{user}__q_{q['id']}"
        if q["type"] == "single":
            sel = st.radio(
                label=f"{quiz_name} - q-{q['id']}",
                options=q["choices"],
                key=widget_key,
                index=None,
                help="Réponse requise"
            )
            answers[q["id"]] = [sel] if sel else []
        else:
            sel = st.multiselect(
                label=f"{quiz_name} - q-{q['id']}",
                options=q["choices"],
                key=widget_key,
                help="Réponse requise"
            )
            answers[q["id"]] = sel
    submitted = st.form_submit_button("✅ Soumettre")

if submitted:
    try:
        must_end = datetime.fromisoformat(must_end_raw)
    except Exception:
        must_end = datetime.now(TIMEZONE)
    if datetime.now(TIMEZONE) > must_end:
        st.error("⏰ Temps écoulé pendant la soumission. Réponses non enregistrées.")
        st.stop()

    unanswered = [q["id"] for q in questions if not answers.get(q["id"])]
    if unanswered:
        st.warning(f"Il reste {len(unanswered)} question(s) sans réponse : {', '.join(unanswered)}")
        st.stop()

    def norm(s: str) -> str:
        return (s or "").strip().casefold()

    total_points, score = 0, 0
    details = []
    for q in questions:
        total_points += q["points"]
        user_ans = [a for a in answers.get(q["id"], []) if a]
        user_norm = {norm(a) for a in user_ans}
        correct_norm = {norm(c) for c in q["correct"]}
        is_ok = user_norm == correct_norm
        if is_ok:
            score += q["points"]
        details.append({
            "id": q["id"],
            "user_answer": user_ans,
            "correct": q["correct"],
            "points": q["points"],
            "ok": is_ok
        })


    try:
        update_result(ws_r, row_idx, f"{score}/{total_points}", {"items": details})
    except Exception as e:
        st.error("Erreur lors de l'enregistrement du résultat.")
        st.exception(e)
        st.stop()

    st.success(f"🎉 Soumis ! Score : **{score}/{total_points}**")

    # 👉 Ajout du message demandé
    st.success("merci, votre test a bien été pris en compte")

    st.markdown("Merci. Votre tentative est maintenant **clôturée**.")
    st.stop()



