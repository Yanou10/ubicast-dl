"""Découverte : trouver les médias UbiCast mentionnés dans une page web.

Chemin **optionnel** de l'outil. Le chemin principal reste l'URL fournie
directement ; la découverte sert quand une page en agrège plusieurs.

Le parser d'origine connaissait la structure d'une page précise (titres de
langues, ancres `/iframe`). Ici, aucune hypothèse sur le balisage :

1. on récupère les attributs `href` (liens) et `src` (iframes d'embed), en
   résolvant les URLs relatives contre l'URL de la page ;
2. on balaie ensuite le document entier — y compris le JavaScript inline et
   les blocs JSON — pour rattraper les lecteurs injectés côté client ;
3. on dédoublonne sur (instance, oid).

Le libellé associé est le texte du lien, ou l'attribut `title`/`aria-label` de
l'iframe : de quoi nommer les fichiers sans rien deviner de la mise en page.
"""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin

from .errors import HttpStatusError, InstanceUnreachable, UbicastError
from .http import http_get
from .resolve import MediaRef, UnrecognizedURL, dedupe, resolve, sweep


class _MediaLinkParser(HTMLParser):
    """Collecte les <a href> et <iframe src> qui pointent vers un média."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.refs: list[MediaRef] = []
        self._open_link: MediaRef | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "iframe":
            ref = self._try(attrs.get("src"))
            if ref:
                label = attrs.get("title") or attrs.get("aria-label")
                self.refs.append(
                    MediaRef(ref.base, ref.oid, label=_clean(label), source=ref.source)
                )
            return

        if tag == "a":
            # Une ancre imbriquée close implicitement la précédente.
            self._flush()
            ref = self._try(attrs.get("href"))
            if ref:
                self._open_link = ref
                self._text = []

    def handle_data(self, data):
        if self._open_link is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self._flush()

    def close(self):
        super().close()
        self._flush()

    def _flush(self) -> None:
        if self._open_link is None:
            return
        ref, self._open_link = self._open_link, None
        label = _clean("".join(self._text))
        self.refs.append(MediaRef(ref.base, ref.oid, label=label, source=ref.source))
        self._text = []

    def _try(self, value) -> MediaRef | None:
        if not value:
            return None
        try:
            return resolve(value, base_url=self.base_url)
        except UnrecognizedURL:
            return None


def _clean(text) -> str | None:
    if not text:
        return None
    collapsed = " ".join(text.split())
    return collapsed or None


def find_in_html(html: str, base_url: str) -> list[MediaRef]:
    """Tous les médias référencés dans `html`, dédoublonnés, dans l'ordre."""
    parser = _MediaLinkParser(base_url)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - HTML malformé : on garde ce qui a été lu
        pass
    # Le balayage brut passe en second : les libellés du parser priment.
    return dedupe(parser.refs + sweep(html, base_url=base_url))


def discover(page_url: str, timeout: int = 60) -> list[MediaRef]:
    """Récupère une page et y cherche les médias UbiCast."""
    try:
        html = http_get(page_url, timeout=timeout)
    except HttpStatusError as e:
        raise UbicastError(
            f"Impossible de récupérer la page {page_url} : HTTP {e.status}"
        ) from None
    except InstanceUnreachable as e:
        raise UbicastError(f"Impossible de récupérer la page {page_url} : {e}") from None
    return find_in_html(html, page_url)
