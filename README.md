# ubicast-dl

Downloads and transcribes videos hosted on a UbiCast / Nudgis instance.

Lecture recordings on these platforms are streamed, not offered as files, and there is no public API. `ubicast-dl` reconstructs the endpoints from the player's own network traffic, reassembles the streams with FFmpeg, and optionally transcribes them with Whisper — turning a two-hour recording you have to scrub through into text you can search.

## Requirements

Python ≥ 3.9 and `ffmpeg` on your `PATH`.

```bash
winget install Gyan.FFmpeg     # Windows
brew install ffmpeg            # macOS
sudo apt install ffmpeg        # Debian / Ubuntu
```

## Install

```bash
pip install .                    # download only
pip install ".[transcription]"   # + Whisper transcription
```

Without installing: `python -m ubicast_dl`.

## Usage

```bash
ubicast-dl URL [URL...]        download
ubicast-dl URL --transcrire    download, then transcribe
ubicast-dl --page URL          discover the media on a page, then download
ubicast-dl URL --lister        list without downloading
```

`URL` accepts a permalink, a `/videos/title-oid/` URL, an iframe embed, or an
`?oid=` link. Other inputs: `--oid OID --hote HOST`, or `--fichier urls.txt`
(one URL per line).

| Option | Description | Default |
|---|---|---|
| `--sortie`, `-o` | Output directory | `videos/` |
| `--qualite` | `max`, `720`, `480` | `max` |
| `--transcrire` | Transcribe after downloading | — |
| `--lister` | List without downloading | — |
| `--modele` | Whisper model: `tiny`, `base`, `small`, `medium`, `large-v3` | `small` |
| `--langue` | Force the language (`fr`, `en`, …) | auto |
| `--srt` / `--sans-srt` | Write `.srt` subtitles or not | `--srt` |
| `--device` | `cpu`, `cuda`, `auto` | `cpu` |

Files already downloaded or transcribed are skipped, so the command is safe to
re-run after an interruption.

> **Note.** Flag names are currently in French. They are kept as-is here so the
> documentation matches the code; English aliases are on the roadmap.

## How it finds the streams

The player fetches its manifest through an undocumented endpoint. `ubicast-dl`
resolves an `oid` from whichever URL form you give it, requests the manifest the
same way the player does, picks the rendition matching `--qualite`, and hands the
segment URLs to FFmpeg for reassembly. No browser automation and no scraping of
rendered HTML — it speaks to the same endpoints the player does.

## Licence

MIT — see [LICENSE](LICENSE).
