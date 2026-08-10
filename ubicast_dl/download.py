"""Fusion des pistes par ffmpeg.

ffmpeg lit directement les deux playlists HLS (vidéo muette et audio séparé)
et les remultiplexe dans un MP4. Les choix d'appel, repris tels quels du script
d'origine parce qu'ils sont corrects :

* ``-c copy`` — remultiplexage sans réencodage. Aucune perte de qualité, un
  coût CPU nul, un téléchargement limité par le seul débit réseau.
* ``-bsf:a aac_adtstoasc`` — l'AAC issu de HLS arrive en conteneur ADTS ; le
  MP4 attend de l'ASC. Sans ce filtre de flux, la piste audio est illisible.
* ``-headers Referer:`` — répété **avant chaque -i**. En ffmpeg, les options
  d'entrée s'appliquent à l'entrée qui suit ; le CDN vérifie le Referer sur
  chacune des deux requêtes.
* ``-map 0:v:0 -map 1:a:0`` — on prend explicitement la vidéo de la première
  entrée et l'audio de la seconde, sans laisser ffmpeg choisir.

Le fichier est écrit sous ``.part`` puis renommé une fois ffmpeg sorti en
succès. Un téléchargement interrompu ne laisse donc jamais de MP4 tronqué qui
serait pris pour un fichier terminé au lancement suivant.
"""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from pathlib import Path
from shutil import which

from .api import Selection
from .errors import FfmpegFailed, FfmpegMissing
from .http import UA
from .resolve import MediaRef

FFMPEG_HINT = (
    "ffmpeg est introuvable dans le PATH. Installe-le :\n"
    "    Windows : winget install Gyan.FFmpeg   (ou : choco install ffmpeg)\n"
    "    macOS   : brew install ffmpeg\n"
    "    Linux   : sudo apt install ffmpeg"
)


def check_ffmpeg() -> str:
    """Renvoie le chemin de ffmpeg, ou lève `FfmpegMissing` avec la marche à suivre."""
    path = which("ffmpeg")
    if not path:
        raise FfmpegMissing(FFMPEG_HINT)
    return path


def slugify(text: str, fallback: str = "video") -> str:
    """Nom de fichier sûr : ASCII, sans espace ni caractère réservé."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^0-9A-Za-z_.\-]", "", text)
    text = text.strip("._-")
    return (text or fallback)[:120]


def output_path(outdir: Path, ref: MediaRef, title: str | None = None) -> Path:
    """Chemin de sortie : titre lisible suffixé de l'oid, qui garantit l'unicité."""
    name = slugify(title or ref.label or "", fallback="")
    stem = f"{name}_{ref.oid}" if name else ref.oid
    return Path(outdir) / f"{stem}.mp4"


def build_command(selection: Selection, ref: MediaRef, out: Path) -> list[str]:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "warning", "-stats",
        "-user_agent", UA,
        "-headers", f"Referer: {ref.referer}\r\n",
        "-i", selection.video.url,
    ]
    if selection.audio_url:
        cmd += [
            "-headers", f"Referer: {ref.referer}\r\n",
            "-i", selection.audio_url,
            "-map", "0:v:0", "-map", "1:a:0",
        ]
    # -f mp4 explicite : le fichier de travail s'appelle « .mp4.part », ffmpeg
    # ne peut donc pas déduire le conteneur de l'extension.
    cmd += ["-c", "copy", "-bsf:a", "aac_adtstoasc", "-f", "mp4", str(out)]
    return cmd


def download(selection: Selection, ref: MediaRef, out: Path) -> Path:
    """Télécharge et fusionne vers `out`. Lève `FfmpegFailed` en cas d'échec."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(out.suffix + ".part")

    cmd = build_command(selection, ref, part)
    try:
        code = subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        _cleanup(part)
        raise
    except OSError as e:
        _cleanup(part)
        raise FfmpegFailed(f"Impossible de lancer ffmpeg : {e}") from None

    if code != 0 or not part.exists() or part.stat().st_size == 0:
        _cleanup(part)
        if code > 2**31:  # Windows renvoie le code en non signé
            code -= 2**32
        raise FfmpegFailed(
            f"ffmpeg a échoué (code {code}) sur {ref}. Les URLs CDN sont signées "
            "et de courte durée : si l'échec persiste, relance — elles sont "
            "régénérées à chaque exécution."
        )

    os.replace(part, out)
    return out


def _cleanup(part: Path) -> None:
    try:
        if part.exists():
            part.unlink()
    except OSError:
        pass
