# ubicast-dl

Télécharge et transcrit les vidéos hébergées sur une instance UbiCast / Nudgis.

## Prérequis

Python ≥ 3.9 et ffmpeg dans le `PATH`.

```bash
winget install Gyan.FFmpeg     # Windows
brew install ffmpeg            # macOS
sudo apt install ffmpeg        # Debian / Ubuntu
```

## Installation

```bash
pip install .                    # téléchargement seul
pip install ".[transcription]"   # + transcription Whisper
```

Sans installation : `python -m ubicast_dl`.

## Utilisation

```
ubicast-dl URL [URL...]        télécharge
ubicast-dl URL --transcrire    télécharge puis transcrit
ubicast-dl --page URL          découvre les médias d'une page, puis télécharge
ubicast-dl URL --lister        liste sans télécharger
```

`URL` accepte un permalien, une URL `/videos/titre-oid/`, un embed iframe ou un
lien `?oid=`. Autres entrées : `--oid OID --hote HOTE`, ou `--fichier urls.txt`
(une URL par ligne).

| Option | Description | Défaut |
| --- | --- | --- |
| `--sortie`, `-o` | Dossier de sortie | `videos/` |
| `--qualite` | `max`, `720`, `480` | `max` |
| `--transcrire` | Transcrit après téléchargement | — |
| `--lister` | Liste sans télécharger | — |
| `--modele` | Modèle Whisper : `tiny`, `base`, `small`, `medium`, `large-v3` | `small` |
| `--langue` | Force la langue (`fr`, `en`, …) | auto |
| `--srt` / `--sans-srt` | Écrit ou non les sous-titres `.srt` | `--srt` |
| `--device` | `cpu`, `cuda`, `auto` | `cpu` |

Les fichiers déjà téléchargés ou transcrits sont sautés : la commande est
relançable après interruption.

## Licence

MIT — voir [LICENSE](LICENSE).
