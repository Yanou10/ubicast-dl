"""Reconnaissance d'URL : d'une chaîne quelconque vers un couple (instance, oid).

UbiCast/Nudgis expose le même média sous plusieurs formes d'URL. Toutes se
ramènent à deux informations : la racine de l'instance et l'oid du média.

Formes reconnues
----------------
    https://HOTE/permalink/v126e0f8b2c3d/                 permalien
    https://HOTE/permalink/v126e0f8b2c3d/iframe/          embed iframe
    https://HOTE/videos/mon-titre-v126e0f8b2c3d/          URL canonique
    https://HOTE/videos/v126e0f8b2c3d/                    idem, sans slug
    https://HOTE/n_importe_quoi/?oid=v126e0f8b2c3d        oid en query string
    https://HOTE/sous/chemin/permalink/v126.../           instance montée
                                                          sous un préfixe
    v126e0f8b2c3d                                         oid nu (+ --hote)

Le préfixe de chemin est conservé : une instance servie sur
``https://exemple.fr/mediaserver/`` verra ses appels API partir de
``https://exemple.fr/mediaserver/api/v2/...``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import parse_qs, urljoin, urlparse

from .errors import UnrecognizedURL

# Un oid UbiCast est une lettre de type suivie d'un identifiant alphanumérique.
# On ne retient que les types lisibles : v (vidéo) et l (live).
OID_PATTERN = r"[vl][0-9A-Za-z]{5,}"

_OID_ONLY_RE = re.compile(rf"^{OID_PATTERN}$")

# Chemin d'un média, tel qu'il apparaît dans une URL absolue ou relative.
# Le `.*-` est glouton : sur /videos/mon-titre-v126abc/ il consomme le slug
# jusqu'au dernier tiret, ce qui isole bien l'oid.
_MEDIA_PATH_RE = re.compile(
    rf"^(?P<prefix>.*?)/(?:permalink|videos)/(?:[^/]*-)?(?P<oid>{OID_PATTERN})(?:/|$)",
    re.IGNORECASE,
)

# Balayage d'un document entier (HTML, JS inline, JSON...) à la recherche
# d'URLs de médias. Le préfixe d'hôte est optionnel et non gourmand : il capte
# aussi bien les URLs absolues que les protocol-relative (//hote/...), et laisse
# les chemins nus être résolus contre l'URL de la page.
_SWEEP_RE = re.compile(
    rf"(?:(?:https?:)?//[^\s\"'<>\\)]+?)?/(?:permalink|videos)/"
    rf"(?:[^/\s\"'<>\\]*-)?{OID_PATTERN}/?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MediaRef:
    """Un média identifié : racine d'instance + oid."""

    base: str  # ex. "https://mediaserver.ip-paris.fr" — jamais de / final
    oid: str
    label: str | None = None
    source: str | None = None  # URL d'origine, pour les messages d'erreur

    @property
    def host(self) -> str:
        return urlparse(self.base).netloc

    @property
    def permalink(self) -> str:
        return f"{self.base}/permalink/{self.oid}/"

    @property
    def referer(self) -> str:
        """Valeur de l'en-tête Referer exigée par l'API et par le CDN."""
        return self.base + "/"

    @property
    def key(self) -> tuple[str, str]:
        return (self.base.lower(), self.oid)

    def __str__(self) -> str:
        return f"{self.oid} @ {self.host}"


def normalize_base(host: str) -> str:
    """Accepte « exemple.fr », « https://exemple.fr/ », « exemple.fr/mediaserver »."""
    host = host.strip()
    if not host:
        raise UnrecognizedURL("Hôte vide.")
    if "://" not in host:
        host = "https://" + host
    parsed = urlparse(host)
    if not parsed.netloc:
        raise UnrecognizedURL(f"Hôte invalide : {host!r}")
    scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
    return f"{scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


def resolve(
    raw: str,
    host: str | None = None,
    base_url: str | None = None,
    label: str | None = None,
) -> MediaRef:
    """Transforme une chaîne en `MediaRef`.

    `host` sert de repli quand l'entrée est un oid nu. `base_url` permet de
    résoudre une URL relative trouvée dans une page (voir discover.py).
    """
    raw = (raw or "").strip().strip("\"'")
    if not raw:
        raise UnrecognizedURL("Entrée vide.")

    # oid nu : il faut un hôte fourni par ailleurs.
    if _OID_ONLY_RE.match(raw):
        if not host:
            raise UnrecognizedURL(
                f"« {raw} » ressemble à un oid mais aucun hôte n'a été fourni. "
                "Ajoute --hote HOTE."
            )
        return MediaRef(normalize_base(host), raw, label=label, source=raw)

    url = raw
    if base_url and not urlparse(url).netloc:
        url = urljoin(base_url, url)

    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        raise UnrecognizedURL(f"Schéma non géré : {raw}")

    if parsed.netloc:
        root = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    elif host:
        root = normalize_base(host)
    else:
        raise UnrecognizedURL(f"URL sans hôte et aucun --hote fourni : {raw}")

    # 1. oid dans le chemin (/permalink/, /videos/, avec préfixe éventuel).
    m = _MEDIA_PATH_RE.match(parsed.path or "")
    if m:
        prefix = m.group("prefix").rstrip("/")
        base = root + ("/" + prefix.lstrip("/") if prefix else "")
        return MediaRef(base, m.group("oid"), label=label, source=raw)

    # 2. oid en query string (?oid=... — forme des appels API et de certains embeds).
    if parsed.query:
        values = parse_qs(parsed.query).get("oid") or []
        for value in values:
            if _OID_ONLY_RE.match(value.strip()):
                # Ici le chemin désigne la page appelante, pas l'instance :
                # on ne peut pas en déduire un préfixe, on retombe sur la racine.
                return MediaRef(root, value.strip(), label=label, source=raw)

    raise UnrecognizedURL(
        f"URL non reconnue comme un média UbiCast : {raw}\n"
        "    Formes acceptées : /permalink/vXXXX/, /videos/titre-vXXXX/, ?oid=vXXXX"
    )


def is_media_url(raw: str) -> bool:
    """Vrai si `raw` se résout sans hôte externe."""
    try:
        resolve(raw)
    except UnrecognizedURL:
        return False
    return True


def sweep(text: str, base_url: str | None = None) -> list[MediaRef]:
    """Extrait tous les médias mentionnés dans un document, sans dédoublonner."""
    found = []
    for match in _SWEEP_RE.finditer(text):
        try:
            found.append(resolve(match.group(0), base_url=base_url))
        except UnrecognizedURL:
            continue
    return found


def dedupe(refs: Iterable[MediaRef]) -> list[MediaRef]:
    """Dédoublonne sur (instance, oid) en conservant l'ordre et le meilleur libellé."""
    seen: dict[tuple[str, str], MediaRef] = {}
    for ref in refs:
        existing = seen.get(ref.key)
        if existing is None:
            seen[ref.key] = ref
        elif not existing.label and ref.label:
            seen[ref.key] = ref
    return list(seen.values())


def read_url_file(path: str | Path, host: str | None = None) -> Iterator[MediaRef]:
    """Lit un fichier texte, une URL par ligne.

    Les lignes vides et celles commençant par # sont ignorées. Une ligne
    invalide n'interrompt pas la lecture : elle lève au moment où on la
    consomme, ce que la CLI rattrape ligne par ligne.
    """
    path = Path(path)
    if not path.is_file():
        raise UnrecognizedURL(f"Fichier introuvable : {path}")
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            yield resolve(line, host=host)
        except UnrecognizedURL as e:
            raise UnrecognizedURL(f"{path}:{lineno} — {e}") from None
