"""Appels à l'endpoint « modes » et sélection des pistes.

L'endpoint
----------
    GET {instance}/api/v2/medias/modes/?oid=OID
        &html5=webm_ogg_ogv_oga_mp4_m4a_mp3_m3u8&yt=yt&embed=embed

C'est cet endpoint, non documenté, que le lecteur web interroge au chargement.
Il renvoie les URLs CDN signées du média :

    {
      "success": true,
      "names": ["360p", "720p", "audio"],
      "360p":  {"resource": {"url": ".../media_360_....m3u8", "height": 360}},
      "720p":  {"resource": {"url": ".../media_720_....m3u8", "height": 720}},
      "audio": {"tracks":   [{"url": ".../audio_0_....m3u8"}]}
    }

Deux détails décident du succès ou de l'échec de l'appel :

* le paramètre `html5` **verbeux**. Il annonce les formats que le client sait
  lire. Sans lui — ou avec une valeur courte — la réponse ne contient pas les
  URLs CDN et devient inutilisable. Ce n'est pas un ornement recopié du
  lecteur : c'est ce qui déclenche la génération des URLs.
* l'en-tête `Referer` (posé par http.py), vérifié côté serveur.

Les URLs renvoyées sont **signées et éphémères**. On les régénère à chaque
exécution ; elles ne sont ni mises en cache, ni stockées, ni devinables.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import quote

from .errors import (
    HttpStatusError,
    InstanceUnreachable,
    MediaNotFound,
    MediaProtected,
    NoVideoTrack,
    UbicastError,
)
from .http import http_get
from .resolve import MediaRef

# Le paramètre html5 verbeux : c'est lui qui fait renvoyer les URLs CDN.
MODES_QS = "html5=webm_ogg_ogv_oga_mp4_m4a_mp3_m3u8&yt=yt&embed=embed"

QUALITIES = ("max", "720", "480")

_HEIGHT_IN_NAME_RE = re.compile(r"(\d{3,4})\s*p", re.IGNORECASE)

_PROTECTED_HINTS = ("password", "mot de passe", "not authorized", "unauthorized",
                    "permission", "access denied", "authentication")
_NOTFOUND_HINTS = ("does not exist", "not found", "no object", "invalid oid",
                   "introuvable")


@dataclass(frozen=True)
class Track:
    name: str
    url: str
    height: int


@dataclass(frozen=True)
class Selection:
    """Résultat de la sélection : une piste vidéo, éventuellement une piste audio."""

    video: Track
    audio_url: str | None
    available: tuple[Track, ...]

    @property
    def audio_is_separate(self) -> bool:
        return self.audio_url is not None


def modes_url(ref: MediaRef) -> str:
    return f"{ref.base}/api/v2/medias/modes/?oid={quote(ref.oid)}&{MODES_QS}"


def _looks_like_json(body: str) -> bool:
    return (body or "").lstrip().startswith(("{", "["))


def _classify_error(message: str, ref: MediaRef) -> UbicastError:
    low = (message or "").lower()
    if any(h in low for h in _PROTECTED_HINTS):
        return MediaProtected(
            f"Média protégé ({ref}) : l'instance exige un mot de passe ou une "
            f"authentification. Réponse de l'API : {message.strip()}"
        )
    if any(h in low for h in _NOTFOUND_HINTS):
        return MediaNotFound(
            f"Média inexistant : aucun média d'oid « {ref.oid} » sur {ref.host}."
        )
    return UbicastError(f"L'API de {ref.host} a refusé la requête : {message.strip()}")


def fetch_modes(ref: MediaRef, timeout: int = 60) -> dict:
    """Interroge l'endpoint modes et renvoie le JSON décodé."""
    url = modes_url(ref)
    try:
        body = http_get(url, referer=ref.referer, timeout=timeout)
    except HttpStatusError as e:
        if e.status == 404:
            # Un 404 en JSON vient de l'API : l'oid n'existe pas. Un 404 en HTML
            # vient du serveur web : l'endpoint lui-même est absent, donc l'hôte
            # n'est pas une instance UbiCast.
            if _looks_like_json(e.body):
                raise MediaNotFound(
                    f"Média inexistant : aucun média d'oid « {ref.oid} » sur "
                    f"{ref.host} (HTTP 404)."
                ) from None
            raise InstanceUnreachable(
                f"{ref.host} ne sert pas /api/v2/medias/modes/ (HTTP 404). "
                "Cet hôte n'est probablement pas une instance UbiCast/Nudgis."
            ) from None
        if e.status in (401, 403):
            raise MediaProtected(
                f"Accès refusé à {ref} (HTTP {e.status}). Le média est protégé "
                "par mot de passe, ou l'instance exige une authentification — "
                "cas non géré par cet outil."
            ) from None
        if e.status >= 500:
            raise InstanceUnreachable(
                f"L'instance {ref.host} a renvoyé une erreur serveur (HTTP {e.status})."
            ) from None
        raise UbicastError(f"Réponse inattendue de {ref.host} : HTTP {e.status}") from None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise InstanceUnreachable(
            f"{ref.host} n'a pas répondu du JSON sur /api/v2/medias/modes/. "
            "Cet hôte n'est probablement pas une instance UbiCast/Nudgis."
        ) from None

    if not isinstance(data, dict):
        raise InstanceUnreachable(
            f"Réponse inattendue de {ref.host} : JSON de type "
            f"{type(data).__name__}, objet attendu."
        )

    if data.get("success") is False:
        raise _classify_error(
            str(data.get("error") or data.get("message") or "sans détail"), ref
        )
    return data


def fetch_title(ref: MediaRef, timeout: int = 20) -> str | None:
    """Titre du média, au mieux.

    `/api/v2/medias/get/` est souvent réservé aux clients authentifiés. L'échec
    est normal et silencieux : on retombe alors sur l'oid pour nommer le fichier.
    """
    url = f"{ref.base}/api/v2/medias/get/?oid={quote(ref.oid)}"
    try:
        data = json.loads(http_get(url, referer=ref.referer, timeout=timeout))
    except Exception:  # noqa: BLE001 - purement opportuniste
        return None
    info = data.get("info") if isinstance(data, dict) else None
    if isinstance(info, dict):
        title = info.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


def _height_of(name: str, node_height) -> int:
    if isinstance(node_height, int) and node_height > 0:
        return node_height
    m = _HEIGHT_IN_NAME_RE.search(name or "")
    return int(m.group(1)) if m else 0


def pick_tracks(modes: dict, ref: MediaRef, quality: str = "max") -> Selection:
    """Choisit une piste vidéo et la piste audio associée.

    Les modes vidéo portent une clé `resource` (url + height), le mode audio
    une liste `tracks`. Quand une piste audio séparée existe, la piste vidéo
    est muette : les deux doivent être fusionnées.

    `quality` vaut "max" (plus haute définition disponible) ou une hauteur
    cible ("720", "480") — on prend alors la meilleure piste qui ne la dépasse
    pas, et à défaut la plus petite disponible.
    """
    names = modes.get("names") or [
        k for k, v in modes.items() if isinstance(v, dict)
    ]

    videos: list[Track] = []
    audio_url: str | None = None

    for name in names:
        node = modes.get(name)
        if not isinstance(node, dict):
            continue

        # Mode vidéo : une « resource » avec son URL m3u8.
        res = node.get("resource")
        if isinstance(res, dict) and res.get("url"):
            videos.append(Track(str(name), res["url"], _height_of(str(name), res.get("height"))))

        # Mode audio : une liste « tracks ». On prend la première.
        tracks = node.get("tracks")
        if isinstance(tracks, list) and tracks and audio_url is None:
            first = tracks[0]
            if isinstance(first, dict) and first.get("url"):
                audio_url = first["url"]

    if not videos:
        if audio_url:
            raise NoVideoTrack(
                f"Aucune piste vidéo pour {ref} : l'API ne propose qu'une piste "
                "audio. Média audio seul, ou vidéo encore en cours d'encodage."
            )
        raise NoVideoTrack(
            f"Aucune piste vidéo pour {ref}. L'API a répondu, mais sans aucune "
            f"URL de média (modes annoncés : {', '.join(map(str, names)) or 'aucun'})."
        )

    videos.sort(key=lambda t: t.height, reverse=True)

    if quality == "max":
        chosen = videos[0]
    else:
        target = int(quality)
        eligible = [t for t in videos if t.height and t.height <= target]
        chosen = eligible[0] if eligible else videos[-1]

    return Selection(video=chosen, audio_url=audio_url, available=tuple(videos))
