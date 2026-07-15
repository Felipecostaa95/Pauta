"""Extracción de entidades.

Por qué entidades y no clusters: para detectar un pico necesitás comparar HOY
contra el mismo tema AYER. Si reagrupás los titulares con clustering cada día,
los IDs de cluster no son estables entre días y no hay serie temporal posible.
Las entidades normalizadas sí son claves estables. El clustering viene después,
solo para redactar la pauta.

spaCy es opcional. Si está instalado se usa NER (mucho mejor). Si no, cae a una
heurística de mayúsculas + n-gramas que funciona razonable en titulares.
"""
import re
import unicodedata
from collections import Counter, defaultdict

# ── stopwords compactas por idioma ──────────────────────────
_ES = """el la los las un una unos unas de del al a ante bajo con contra desde durante en entre hacia
hasta mediante para por segun sin sobre tras y o u e ni que se su sus le les lo mi tu es son fue fueron
ser estar esta este esto estos estas ese esa eso mas pero como cuando donde quien cual todo toda todos
todas otro otra hay habia tiene tienen tras muy ya no si asi tambien solo puede pueden hace hacen dice
dicen dijo tras anos ano dia dias vez veces nuevo nueva gran primer primera mejor peor sera seran"""
_EN = """the a an of to in for on with at by from as is are was were be been being and or but not this
that these those it its his her their our your my he she they we you who what when where which how all
any some more most other another new news said says say will would can could should may might have has
had do does did get gets got make makes made after before over under about into out up down off very
just now than then out first last best worst top why one two three years year day days time"""
_FR = """le la les un une des du de a au aux en dans sur sous pour par avec sans vers chez entre depuis
pendant contre et ou ni que qui quoi dont ou est sont etait etaient etre avoir ce cet cette ces son sa
ses leur leurs mon ma mes ton ta tes notre nos votre vos il elle ils elles nous vous je tu on plus moins
tres bien tout tous toute toutes autre autres apres avant nouveau nouvelle premier premiere dernier
grand grande fait faire dit dire ans an jour jours fois"""

STOP = {
    "es": set(_ES.split()),
    "en": set(_EN.split()),
    "fr": set(_FR.split()),
}
# Un titular en un idioma trae ruido de los otros. Filtramos con todos.
ALL_STOP = STOP["es"] | STOP["en"] | STOP["fr"]

# Conectores que pueden ir EN MEDIO de un nombre propio: "Ministerio de Salud"
CONNECTORS = {"de", "del", "la", "las", "los", "el", "y", "of", "the", "and",
              "du", "des", "le", "les", "et", "da", "van", "von", "bin", "al"}

_TOKEN = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’&.-]*")


def norm_key(s):
    """Clave canónica: sin acentos, minúscula, sin puntuación. 'México' y
    'Mexico' tienen que caer en la misma serie o la detección se parte."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(text):
    return _TOKEN.findall(text)


def _is_titlecase(tokens):
    content = [t for t in tokens if len(t) > 3]
    if len(content) < 3:
        return False
    caps = sum(1 for t in content if t[0].isupper())
    return caps / len(content) > 0.6


# ── prior de mayúsculas ─────────────────────────────────────
def build_caps_prior(titles):
    """Un titular en 'sentence case' delata los nombres propios: van en
    mayúscula en medio de la frase. Los titulares en Title Case (típico en
    inglés) no delatan nada, así que no los usamos para construir el prior —
    pero sí lo aplicamos sobre ellos después. Así 'Trump Says New Tariffs'
    resuelve Trump=propio, Says/New=común."""
    mid_cap, mid_total = Counter(), Counter()
    for t in titles:
        toks = _tokens(t)
        if _is_titlecase(toks):
            continue
        for i, tok in enumerate(toks[1:], start=1):
            k = tok.lower()
            mid_total[k] += 1
            if tok[0].isupper():
                mid_cap[k] += 1
    return {k: mid_cap[k] / v for k, v in mid_total.items() if v >= 2}


def _proper_runs(tokens, prior, titlecase):
    """Secuencias contiguas de nombres propios."""
    def is_proper(i, tok):
        low = tok.lower()
        if low in ALL_STOP:
            return False
        if not tok[0].isupper():
            return False
        if titlecase or i == 0:
            # No podemos confiar en la mayúscula: preguntamos al prior.
            return prior.get(low, 0.0) > 0.5
        return True

    runs, cur = [], []
    for i, tok in enumerate(tokens):
        if is_proper(i, tok):
            cur.append(tok)
        elif (cur and tok.lower() in CONNECTORS and i + 1 < len(tokens)
              and is_proper(i + 1, tokens[i + 1])):
            cur.append(tok)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [" ".join(r) for r in runs if not (len(r) == 1 and len(r[0]) < 3)]


def _ngrams(tokens, nmax=3):
    """Solo n>=2. Un token suelto en minúscula nunca es un tema: 'statement',
    'addresses', 'club' pasaban el filtro y ensuciaban toda la pauta. Los
    nombres propios de una sola palabra (Popocatépetl, Mbappé) no dependen de
    esto — entran por _proper_runs."""
    lows = [t.lower() for t in tokens]
    out = []
    for n in range(2, nmax + 1):
        for i in range(len(lows) - n + 1):
            g = lows[i:i + n]
            if g[0] in ALL_STOP or g[-1] in ALL_STOP:
                continue
            if any(len(x) < 4 for x in g):
                continue
            out.append(" ".join(tokens[i:i + n]))
    return out


# ── spaCy opcional ──────────────────────────────────────────
_NLP = {}
_SPACY_MODELS = {"es": "es_core_news_sm", "en": "en_core_web_sm", "fr": "fr_core_news_sm"}
_KEEP_LABELS = {"PER", "PERSON", "ORG", "LOC", "GPE", "EVENT", "PRODUCT", "WORK_OF_ART",
                "FAC", "NORP", "MISC"}


def _spacy(lang):
    if lang in _NLP:
        return _NLP[lang]
    try:
        import spacy
        _NLP[lang] = spacy.load(_SPACY_MODELS[lang], disable=["lemmatizer", "textcat"])
    except Exception:
        _NLP[lang] = None
    return _NLP[lang]


def _extract_one(item, prior):
    """Candidatos crudos (superficie, sin normalizar) de un item."""
    title = item["title"]
    extra = item.get("extra") or {}

    # Google Trends ya te da la entidad servida: el query ES el tema.
    if extra.get("is_query"):
        return [title]

    cands = []
    nlp = _spacy(item.get("lang", "es")[:2])
    if nlp is not None:
        doc = nlp(title)
        cands += [e.text for e in doc.ents if e.label_ in _KEEP_LABELS]
    else:
        toks = _tokens(title)
        cands += _proper_runs(toks, prior, _is_titlecase(toks))
        cands += _ngrams(toks)

    # tags de YouTube: el creador ya te dijo de qué habla
    cands += [t for t in extra.get("tags", []) if 3 < len(t) < 40]
    return cands


# ── pipeline ────────────────────────────────────────────────
def extract(items, cfg):
    """Devuelve (pairs, display_map).
    pairs: [(item_id, entity_key)]  |  display_map: {key: 'Forma Bonita'}"""
    min_chars = cfg.get("min_chars", 3)
    stoplist = {norm_key(s) for s in cfg.get("stoplist", [])}
    manual = {norm_key(k): norm_key(v) for k, v in (cfg.get("aliases") or {}).items()}

    prior = build_caps_prior([i["title"] for i in items])

    raw = defaultdict(set)      # item_id -> {key}
    surfaces = defaultdict(Counter)   # key -> Counter(superficie)

    for item in items:
        for c in _extract_one(item, prior):
            k = norm_key(c)
            if len(k) < min_chars or k in stoplist or k in ALL_STOP:
                continue
            if k.isdigit():
                continue
            k = manual.get(k, k)
            raw[item["id"]].add(k)
            surfaces[k][c.strip()] += 1

    # ── filtro de frecuencia documental ─────────────────────
    # Un término que aparece en el 40% de los titulares no es un tema, es ruido.
    df = Counter()
    for keys in raw.values():
        df.update(keys)
    n_docs = max(1, len(raw))
    max_df = cfg.get("max_doc_freq", 0.25) * n_docs
    banned = {k for k, c in df.items() if c > max_df}

    # ── alias automático por co-ocurrencia ──────────────────
    # "trump" ⊂ "donald trump": si el 60%+ de las veces que aparece "trump"
    # también aparece "donald trump", son la misma cosa.
    if cfg.get("auto_alias", True):
        auto = _auto_alias(raw, df, cfg.get("alias_cooc", 0.6))
        manual.update(auto)

    def resolve(k):
        seen = set()
        while k in manual and k not in seen:
            seen.add(k)
            k = manual[k]
        return k

    pairs, display = set(), {}
    for item_id, keys in raw.items():
        for k in keys:
            k2 = resolve(k)
            if k2 in banned or k2 in stoplist:
                continue
            pairs.add((item_id, k2))
            if k2 not in display:
                merged = Counter()
                for src in (k, k2):
                    merged.update(surfaces.get(src, {}))
                display[k2] = merged.most_common(1)[0][0] if merged else k2

    return sorted(pairs), display


def _auto_alias(raw, df, thresh):
    inv = defaultdict(set)
    for item_id, keys in raw.items():
        for k in keys:
            inv[k].add(item_id)

    by_tokens = {k: frozenset(k.split()) for k in df}
    shorts = [k for k in df if len(by_tokens[k]) == 1 and df[k] >= 3]
    longs = [k for k in df if len(by_tokens[k]) > 1 and df[k] >= 2]

    alias = {}
    for s in shorts:
        best, best_r = None, 0.0
        for l in longs:
            if not by_tokens[s] <= by_tokens[l]:
                continue
            r = len(inv[s] & inv[l]) / max(1, len(inv[s]))
            if r > best_r:
                best, best_r = l, r
        if best and best_r >= thresh:
            alias[s] = best
    return alias
