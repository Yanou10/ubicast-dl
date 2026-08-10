"""Transcription par faster-whisper.

Reprend la logique du script d'origine — filtre VAD, sortie .txt + .srt,
fichiers déjà transcrits sautés — en la rendant paramétrable et réutilisable
depuis la CLI.

L'import de `faster_whisper` est différé : le téléchargement seul ne doit
dépendre que de la bibliothèque standard et de ffmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import TranscriptionUnavailable, UbicastError

MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".wmv",
    ".mpg", ".mpeg", ".m4a", ".mp3", ".wav",
}

DEFAULT_MODEL = "small"

# Précision par défaut selon le matériel : int8 sur CPU (rapide, peu de
# mémoire), float16 sur GPU NVIDIA. "auto" laisse ctranslate2 décider.
_COMPUTE_TYPES = {"cpu": "int8", "cuda": "float16", "auto": "default"}


@dataclass
class TranscriptionOptions:
    model: str = DEFAULT_MODEL
    device: str = "cpu"
    compute_type: str | None = None
    language: str | None = None
    write_srt: bool = True
    vad_filter: bool = True

    def resolved_compute_type(self) -> str:
        return self.compute_type or _COMPUTE_TYPES.get(self.device, "default")


def format_timestamp(seconds: float) -> str:
    """Secondes -> horodatage SRT : HH:MM:SS,mmm."""
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(segments, srt_path: Path) -> None:
    with Path(srt_path).open("w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")


def load_model(options: TranscriptionOptions):
    """Charge le modèle Whisper. Le premier appel le télécharge et le met en cache."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise TranscriptionUnavailable(
            "faster-whisper n'est pas installé. Installe-le pour transcrire :\n"
            "    pip install faster-whisper"
        ) from None

    try:
        return WhisperModel(
            options.model,
            device=options.device,
            compute_type=options.resolved_compute_type(),
        )
    except Exception as e:  # noqa: BLE001 - message utile plutôt que traceback
        raise UbicastError(
            f"Chargement du modèle « {options.model} » impossible sur "
            f"{options.device} ({options.resolved_compute_type()}) : {e}"
        ) from None


def transcribe_file(model, path: Path, options: TranscriptionOptions) -> dict:
    """Transcrit un fichier. Renvoie un compte rendu du travail effectué.

    Les fichiers déjà transcrits sont sautés : l'outil reste relançable.
    """
    path = Path(path)
    txt_path = path.with_suffix(".txt")
    srt_path = path.with_suffix(".srt")

    if txt_path.exists():
        return {"path": path, "skipped": True, "txt": txt_path}

    segments_gen, info = model.transcribe(
        str(path),
        language=options.language,
        vad_filter=options.vad_filter,  # coupe les silences : plus rapide, plus propre
    )
    segments = list(segments_gen)  # générateur consommé une fois, réutilisé deux fois

    full_text = "".join(seg.text for seg in segments).strip()
    txt_path.write_text(full_text + "\n", encoding="utf-8")

    if options.write_srt:
        write_srt(segments, srt_path)

    return {
        "path": path,
        "skipped": False,
        "txt": txt_path,
        "srt": srt_path if options.write_srt else None,
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
    }


def find_media(folder: Path) -> list[Path]:
    """Fichiers transcriptibles d'un dossier, sans récursion."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS
    )


def transcribe_all(paths: Iterable[Path], options: TranscriptionOptions, log=print) -> int:
    """Transcrit une série de fichiers. Renvoie le nombre d'échecs."""
    paths = [Path(p) for p in paths]
    todo = [p for p in paths if not p.with_suffix(".txt").exists()]

    for p in paths:
        if p not in todo:
            log(f"[=] transcription déjà présente, saut : {p.name}")

    if not todo:
        return 0

    log(
        f"\nChargement du modèle Whisper « {options.model} » sur {options.device} "
        f"({options.resolved_compute_type()}) — long au premier lancement.\n"
    )
    model = load_model(options)

    failures = 0
    for i, path in enumerate(todo, start=1):
        log(f"[{i}/{len(todo)}] transcription : {path.name}")
        try:
            result = transcribe_file(model, path, options)
        except Exception as e:  # noqa: BLE001 - un fichier fautif n'arrête pas le lot
            failures += 1
            log(f"    [ÉCHEC] {path.name} : {e}")
            continue
        if result.get("language"):
            log(
                f"    langue détectée : {result['language']} "
                f"({result['language_probability']:.2f})"
            )
        log(f"    écrit : {result['txt'].name}"
            + (f" + {result['srt'].name}" if result.get("srt") else ""))
    return failures
