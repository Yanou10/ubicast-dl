"""Erreurs typées.

Chaque cas d'échec prévisible a sa propre classe et son propre message en
français. La CLI attrape `UbicastError` et affiche `str(e)` : l'utilisateur
ne voit jamais de traceback pour une situation que l'outil sait nommer.
"""


class UbicastError(Exception):
    """Erreur attendue, présentable telle quelle à l'utilisateur."""


class UnrecognizedURL(UbicastError):
    """L'entrée n'est ni une URL UbiCast reconnue, ni un oid exploitable."""


class InstanceUnreachable(UbicastError):
    """Instance injoignable : DNS, TLS, timeout, ou hôte qui n'est pas UbiCast."""


class HttpStatusError(UbicastError):
    """Réponse HTTP en erreur. Raffinée en MediaNotFound/MediaProtected par api.py."""

    def __init__(self, status, url, body=""):
        self.status = status
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status} sur {url}")


class MediaNotFound(UbicastError):
    """L'oid n'existe pas sur cette instance."""


class MediaProtected(UbicastError):
    """Média protégé : mot de passe, authentification, ou accès restreint."""


class NoVideoTrack(UbicastError):
    """L'endpoint modes a répondu mais ne propose aucune piste vidéo."""


class FfmpegMissing(UbicastError):
    """ffmpeg absent du PATH."""


class FfmpegFailed(UbicastError):
    """ffmpeg s'est terminé avec un code de sortie non nul."""


class TranscriptionUnavailable(UbicastError):
    """faster-whisper n'est pas installé."""
