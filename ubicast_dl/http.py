"""Transport HTTP commun à api.py et discover.py.

Deux points non négociables, hérités du script d'origine :

* un User-Agent de navigateur — certaines instances renvoient une page
  d'erreur au User-Agent par défaut d'urllib ;
* un en-tête ``Referer`` pointant sur l'instance. L'endpoint modes et le CDN
  le vérifient. Sans lui la réponse est vide ou refusée. Ce même en-tête est
  repassé à ffmpeg au moment du téléchargement (voir download.py).
"""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request

from .errors import HttpStatusError, InstanceUnreachable

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 60


def http_get(url: str, referer: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """GET une URL et renvoie le corps décodé en texte.

    Lève `InstanceUnreachable` si la couche réseau échoue, `HttpStatusError`
    si le serveur répond avec un code d'erreur.
    """
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:  # noqa: BLE001 - le corps d'erreur est facultatif
            body = ""
        raise HttpStatusError(e.code, url, body) from None
    except urllib.error.URLError as e:
        raise InstanceUnreachable(f"Instance injoignable ({url}) : {e.reason}") from None
    except TimeoutError:
        raise InstanceUnreachable(
            f"Délai dépassé après {timeout}s en interrogeant {url}"
        ) from None
    # OSError couvre les coupures de connexion, les erreurs TLS et les échecs
    # de socket ; HTTPException les réponses malformées. Aucun de ces cas ne
    # mérite un traceback : ils disent tous « l'instance ne répond pas ».
    except (OSError, http.client.HTTPException) as e:
        raise InstanceUnreachable(
            f"Échec de la connexion à {url} : {e.__class__.__name__} — {e}"
        ) from None
