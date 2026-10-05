from __future__ import annotations

from typing import Iterable, Protocol, TypeVar

from app.services.releases.github_release_service import (
    GitHubReleaseService,
    compare_release_versions,
)


class ReleaseSource(Protocol):
    key: str
    name: str
    version: str
    url: str

    def with_resolution(
        self,
        *,
        name: str,
        version: str,
        url: str,
    ) -> "ReleaseSource":
        ...


ReleaseSourceT = TypeVar("ReleaseSourceT", bound=ReleaseSource)


def compare_release_urls(reference_url: str, candidate_url: str) -> int | None:
    """Compara as tags de duas URLs comprovadamente do mesmo repositório.

    O retorno segue ``compare_release_versions``: -1 quando a candidata é
    superior, 0 quando a URL é idêntica ou a versão é igual, 1 quando ela é
    inferior e None quando não existe prova segura de ordem.
    """
    reference = str(reference_url or "").strip()
    candidate = str(candidate_url or "").strip()
    if not reference or not candidate:
        return None
    if reference == candidate:
        return 0

    parsed_reference = GitHubReleaseService.parse_download_url(reference)
    parsed_candidate = GitHubReleaseService.parse_download_url(candidate)
    if parsed_reference is None or parsed_candidate is None:
        return None

    if (
        parsed_reference.owner.lower() != parsed_candidate.owner.lower()
        or parsed_reference.repo.lower() != parsed_candidate.repo.lower()
    ):
        return None
    return compare_release_versions(parsed_reference.tag, parsed_candidate.tag)


def is_valid_automatic_release_resolution(reference_url: str, candidate_url: str) -> bool:
    """Aceita somente a URL inalterada ou uma evolução estritamente provada.

    Estado automático não é fonte autoritativa. Uma URL diferente cujo vínculo
    ou ordem não possa ser provado falha fechada e deve ser descartada.
    """
    reference = str(reference_url or "").strip()
    candidate = str(candidate_url or "").strip()
    if reference and reference == candidate:
        return True
    return compare_release_urls(reference, candidate) == -1


def is_proven_release_downgrade(reference_url: str, candidate_url: str) -> bool:
    """Indica somente rebaixamentos demonstráveis da mesma origem GitHub."""
    return compare_release_urls(reference_url, candidate_url) == 1


def enforce_automatic_source_floor(
    reference_sources: Iterable[ReleaseSourceT],
    candidate_sources: Iterable[ReleaseSourceT],
) -> tuple[ReleaseSourceT, ...]:
    """Mantém cada fonte atual quando a candidata não prova uma evolução.

    Os conjuntos de identidades precisam ser idênticos. A ordem de referência é
    preservada para que uma resolução automática nunca reordene o catálogo.
    """
    references = tuple(reference_sources)
    candidates = tuple(candidate_sources)
    reference_by_key = {source.key: source for source in references}
    candidate_by_key = {source.key: source for source in candidates}

    if (
        len(reference_by_key) != len(references)
        or len(candidate_by_key) != len(candidates)
        or set(reference_by_key) != set(candidate_by_key)
    ):
        raise ValueError("resolved_catalog_mismatch")

    protected = []
    for reference in references:
        candidate = candidate_by_key[reference.key]
        protected.append(
            candidate
            if is_valid_automatic_release_resolution(reference.url, candidate.url)
            else reference
        )
    return tuple(protected)


def enforce_catalog_source_floor(
    reference_sources: Iterable[ReleaseSourceT],
    catalog_sources: Iterable[ReleaseSourceT],
) -> tuple[ReleaseSourceT, ...]:
    """Impede que um catálogo externo rebaixe uma identidade já conhecida.

    Catálogos continuam podendo adicionar, remover, reordenar ou trocar itens.
    A referência prevalece apenas quando a mesma chave e o mesmo repositório
    permitem provar que a tag candidata é inferior. Metadados editoriais do
    catálogo, como ``name_override``, permanecem preservados.
    """
    reference_by_key = {source.key: source for source in reference_sources}
    protected = []
    for candidate in catalog_sources:
        reference = reference_by_key.get(candidate.key)
        if reference is not None and is_proven_release_downgrade(
            reference.url,
            candidate.url,
        ):
            candidate = candidate.with_resolution(
                name=reference.name,
                version=reference.version,
                url=reference.url,
            )
        protected.append(candidate)
    return tuple(protected)
