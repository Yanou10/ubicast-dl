"""Interface en ligne de commande — point d'entrée unique de l'outil."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .api import QUALITIES, fetch_modes, fetch_title, pick_tracks
from .discover import discover
from .download import check_ffmpeg, download, output_path
from .errors import UbicastError, UnrecognizedURL
from .resolve import MediaRef, dedupe, read_url_file, resolve
from .transcribe import DEFAULT_MODEL, TranscriptionOptions, transcribe_all

EPILOG = """\
Exemples :
  ubicast-dl https://mediaserver.exemple.fr/permalink/v1260a1b2c3d/
  ubicast-dl https://exemple.fr/videos/mon-cours-v1260a1b2c3d/ --transcrire
  ubicast-dl --oid v1260a1b2c3d --hote mediaserver.exemple.fr
  ubicast-dl --page https://exemple.fr/page-avec-des-videos --lister
  ubicast-dl --fichier urls.txt --sortie ./cours --qualite 720

Les fichiers déjà présents sont sautés : l'outil est relançable après
interruption.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ubicast-dl",
        description="Télécharge et transcrit les vidéos hébergées sur une "
                    "instance UbiCast/Nudgis.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("urls", nargs="*", metavar="URL",
                   help="URL(s) de média UbiCast, ou chemin d'un fichier "
                        "contenant une URL par ligne.")
    p.add_argument("--page", metavar="URL",
                   help="Page web à analyser pour y découvrir des médias.")
    p.add_argument("--oid", metavar="OID",
                   help="oid explicite (à combiner avec --hote).")
    p.add_argument("--hote", metavar="HOTE",
                   help="Instance UbiCast, ex. mediaserver.exemple.fr.")
    p.add_argument("--fichier", "-f", action="append", metavar="CHEMIN",
                   default=[], help="Fichier texte : une URL par ligne.")

    p.add_argument("--lister", action="store_true",
                   help="Liste les médias trouvés sans rien télécharger.")
    p.add_argument("--transcrire", action="store_true",
                   help="Transcrit les vidéos après téléchargement.")

    p.add_argument("--sortie", "-o", default="videos", metavar="DOSSIER",
                   help="Dossier de sortie (défaut : videos/).")
    p.add_argument("--qualite", choices=QUALITIES, default="max",
                   help="Qualité vidéo visée (défaut : max).")

    p.add_argument("--modele", default=DEFAULT_MODEL, metavar="NOM",
                   help=f"Modèle Whisper : tiny, base, small, medium, large-v3 "
                        f"(défaut : {DEFAULT_MODEL}).")
    p.add_argument("--langue", metavar="CODE",
                   help="Force la langue de transcription (ex. fr, en). "
                        "Par défaut, détection automatique.")
    p.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu",
                   help="Matériel pour Whisper (défaut : cpu).")
    srt = p.add_mutually_exclusive_group()
    srt.add_argument("--srt", dest="srt", action="store_true", default=True,
                     help="Écrit aussi les sous-titres .srt (défaut).")
    srt.add_argument("--sans-srt", dest="srt", action="store_false",
                     help="N'écrit que le .txt.")

    p.add_argument("--verbeux", "-v", action="store_true",
                   help="Affiche les tracebacks complets (débogage).")
    p.add_argument("--version", action="version", version=f"ubicast-dl {__version__}")
    return p


def collect_refs(args, errors: list[str]) -> list[MediaRef]:
    """Rassemble les médias visés depuis toutes les formes d'entrée."""
    refs: list[MediaRef] = []

    for raw in args.urls:
        # Un argument positionnel qui désigne un fichier existant est traité
        # comme une liste d'URLs.
        if Path(raw).is_file():
            try:
                refs.extend(read_url_file(raw, host=args.hote))
            except UbicastError as e:
                errors.append(str(e))
            continue
        try:
            refs.append(resolve(raw, host=args.hote))
        except UbicastError as e:
            errors.append(str(e))

    for path in args.fichier:
        try:
            refs.extend(read_url_file(path, host=args.hote))
        except UbicastError as e:
            errors.append(str(e))

    if args.oid:
        if not args.hote:
            errors.append("--oid exige --hote (l'oid seul ne désigne aucune instance).")
        else:
            try:
                refs.append(resolve(args.oid, host=args.hote))
            except UbicastError as e:
                errors.append(str(e))

    if args.page:
        print(f"Analyse de la page : {args.page}")
        try:
            found = discover(args.page)
        except UbicastError as e:
            errors.append(str(e))
        else:
            print(f"  {len(found)} média(s) trouvé(s).")
            refs.extend(found)

    return dedupe(refs)


def download_one(ref: MediaRef, outdir: Path, quality: str) -> Path | None:
    """Télécharge un média. Renvoie le chemin, ou None si sauté ou échoué."""
    modes = fetch_modes(ref)
    title = ref.label or fetch_title(ref)
    out = output_path(outdir, ref, title)

    if out.exists():
        print(f"[=] {out.name} déjà présent, saut.")
        return out

    selection = pick_tracks(modes, ref, quality=quality)
    available = ", ".join(f"{t.height}p" for t in selection.available if t.height)
    print(f"[>] {out.name}")
    print(f"    vidéo : {selection.video.height or '?'}p"
          + (f"  (disponibles : {available})" if available else ""))
    print("    audio : "
          + ("piste séparée, fusionnée par ffmpeg" if selection.audio_is_separate
             else "intégré à la piste vidéo"))

    download(selection, ref, out)
    print(f"[ok] {out.name}\n")
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not (args.urls or args.page or args.oid or args.fichier):
        build_parser().print_help()
        return 2

    errors: list[str] = []
    refs = collect_refs(args, errors)

    for message in errors:
        print(f"[!] {message}", file=sys.stderr)

    if not refs:
        print("Aucun média à traiter.", file=sys.stderr)
        return 1 if errors else 0

    print(f"\n{len(refs)} média(s) :")
    for ref in refs:
        label = f" — {ref.label}" if ref.label else ""
        print(f"  - {ref.oid}  ({ref.host}){label}")
    print()

    if args.lister:
        return 1 if errors else 0

    # Contrôle unique au démarrage plutôt qu'un échec obscur au premier média.
    try:
        check_ffmpeg()
    except UbicastError as e:
        print(str(e), file=sys.stderr)
        return 1

    outdir = Path(args.sortie)
    outdir.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    failures = 0
    for ref in refs:
        try:
            path = download_one(ref, outdir, args.qualite)
        except UbicastError as e:
            failures += 1
            print(f"[ÉCHEC] {e}\n", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nInterrompu. Le fichier partiel a été supprimé ; relance la "
                  "commande pour reprendre les médias restants.", file=sys.stderr)
            return 130
        except Exception as e:  # noqa: BLE001 - un média fautif n'arrête pas le lot
            failures += 1
            if args.verbeux:
                raise
            print(f"[ÉCHEC] erreur inattendue sur {ref} : {e}\n", file=sys.stderr)
        else:
            if path:
                downloaded.append(path)

    print(f"Téléchargement terminé : {len(downloaded)}/{len(refs)} média(s) "
          f"dans {outdir}/")

    if args.transcrire and downloaded:
        options = TranscriptionOptions(
            model=args.modele,
            device=args.device,
            language=args.langue,
            write_srt=args.srt,
        )
        try:
            failures += transcribe_all(downloaded, options)
        except UbicastError as e:
            print(str(e), file=sys.stderr)
            return 1

    return 1 if (failures or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
