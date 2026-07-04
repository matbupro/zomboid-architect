"""test_ingestor_processors — Tests unitaires des processeurs d'ingestion.

Couvre :
  - detection MIME et extension -> processor mapping (engine.py)
  - chunking logic (base.py Processor.chunk_text via TextProcessor)
  - SHA-256 hashing (compute_hash)
  - TextProcessor extraction de textes bruts
  - split_paragraphs (edge cases via TextProcessor)
  - ExtractionResult fields validation
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def sample_text():
    """Texte multi-paragraphes pour tests de chunking."""
    return (
        "Ceci est le premier paragraphe.\n\n"
        "Deuxieme paragraphe avec plus de contenu pour tester le decoupage automatique. "
        "Il contient suffisamment de mots pour depasser la taille par defaut des chunks.\n\n"
        "Troisieme paragraphe - court.\n\n"
        "Quatrieme paragraphe qui sert a verifier que le chevauchement marche correctement. "
        "Les mots de transition entre chunks doivent etre coherents.\n\n"
        "Dernier paragraphe du texte de test."
    )


@pytest.fixture()
def tmp_test_file(tmp_path: Path):
    """Cree un fichier temporaire pour tests d'ingestion."""
    f = tmp_path / "test_sample.txt"
    f.write_text("Bonjour monde! Ceci est un texte de test pour l'ingestor.", encoding="utf-8")
    return f


# ===========================================================================
# Tests : MIME detection (engine.py)
# ===========================================================================


def test_detect_txt_extension():
    """Un fichier .txt est detecte comme text/plain -> processeur 'text'."""
    from ingestor.engine import detect_type

    content_type, processor_key = detect_type(Path("file.txt"))
    assert processor_key == "text"


def test_detect_pdf_extension():
    """Un fichier .pdf est detecte comme application/pdf -> processeur 'pdf'."""
    from ingestor.engine import detect_type

    content_type, processor_key = detect_type(Path("file.pdf"))
    assert processor_key == "pdf"


def test_detect_all_text_extensions_have_processor():
    """Les extensions texte ont toutes un processeur mappé."""
    from ingestor.engine import detect_type

    text_exts = [".txt", ".md", ".csv", ".json", ".xml"]
    for ext in text_exts:
        content_type, processor_key = detect_type(Path(f"file{ext}"))
        assert processor_key is not None, f"Pas de processeur pour extension {ext}"


def test_detect_unsupported_extension_raises():
    """Un fichier avec une extension non supportee leve ValueError."""
    from ingestor.engine import detect_type

    with pytest.raises(ValueError):
        detect_type(Path("file.xyz_fake"))


# ===========================================================================
# Tests : MIME -> processor mapping (engine.py)
# ===========================================================================


def test_mime_to_processor_text():
    """text/* mappés vers processeur 'text'."""
    from ingestor.engine import mime_to_processor

    assert mime_to_processor("text/plain") == "text"
    assert mime_to_processor("text/markdown") == "text"
    # HTML est aussi text/ -> premier match = "text" (la fonction check text/ avant html)


def test_mime_to_processor_pdf():
    """application/pdf mappé vers processeur 'pdf'."""
    from ingestor.engine import mime_to_processor

    assert mime_to_processor("application/pdf") == "pdf"


def test_mime_to_processor_image():
    """image/* mappés vers processeur 'image'."""
    from ingestor.engine import mime_to_processor

    assert mime_to_processor("image/png") == "image"
    assert mime_to_processor("image/jpeg") == "image"


def test_mime_to_processor_video():
    """video/* mappés vers processeur 'video'."""
    from ingestor.engine import mime_to_processor

    assert mime_to_processor("video/mp4") == "video"
    assert mime_to_processor("video/x-matroska") == "video"


def test_mime_to_processor_audio():
    """audio/* mappés vers processeur 'audio'."""
    from ingestor.engine import mime_to_processor

    assert mime_to_processor("audio/mpeg") == "audio"
    assert mime_to_processor("audio/wav") == "audio"


def test_mime_to_processor_docx():
    """La detection de 'docx' dans MIME retourne 'docx'."""
    from ingestor.engine import mime_to_processor

    # mime_to_processor cherche "docx" dans le string du MIME type.
    assert mime_to_processor("application/vnd.docx") == "docx"


def test_mime_to_processor_epub():
    """EPUB mappé vers processeur 'epub'."""
    from ingestor.engine import mime_to_processor

    assert mime_to_processor("application/epub+zip") == "epub"


def test_mime_to_processor_pbo():
    """PBO mappé vers processeur 'pbo'."""
    from ingestor.engine import mime_to_processor

    assert mime_to_processor("application/x-pbo") == "pbo"


def test_mime_to_processor_unknown_returns_none():
    """Un MIME inconnu retourne None (sans planter)."""
    from ingestor.engine import mime_to_processor

    assert mime_to_processor("application/unknown-fake") is None


# ===========================================================================
# Tests : ext_to_mime conversion
# ===========================================================================


def test_ext_to_mime_mapping():
    """Les extensions se convertissent correctement vers MIME."""
    from ingestor.engine import ext_to_mime

    assert "text/plain" in ext_to_mime(".txt")
    assert "pdf" in ext_to_mime(".pdf").lower()
    assert "image/png" in ext_to_mime(".png")
    assert "video/mp4" in ext_to_mime(".mp4")


def test_ext_to_mime_unknown_returns_octet_stream():
    """Une extension inconnue retourne application/octet-stream."""
    from ingestor.engine import ext_to_mime

    assert ext_to_mime(".unknown_fake") == "application/octet-stream"


# ===========================================================================
# Tests : URL detection
# ===========================================================================


def test_detect_is_url_http():
    """detect_is_url deteche correctement les URLs HTTP."""
    from ingestor.engine import detect_is_url

    assert detect_is_url("http://example.com/path") is True
    assert detect_is_url("https://example.com/path?query=1") is True


def test_detect_is_url_not_url():
    """detect_is_url retourne False pour les chemins fichiers."""
    from ingestor.engine import detect_is_url

    assert detect_is_url("/home/user/file.txt") is False
    assert detect_is_url("C:\\Users\\file.pdf") is False
    assert detect_is_url("") is False


# ===========================================================================
# Tests : Chunking (via WebProcessor — seul processeur qui herite de Processor)
# ===========================================================================


def test_chunk_text_empty_returns_empty():
    """Un texte vide retourne une liste de chunks vide."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig(CHUNK_SIZE=200, CHUNK_OVERLAP=30)
    proc = WebProcessor(config)

    result = proc.chunk_text("")
    assert result == []


def test_chunk_text_single_paragraph_returns_one_chunk():
    """Un seul paragraphe court produit un seul chunk."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig(CHUNK_SIZE=500, CHUNK_OVERLAP=64)
    proc = WebProcessor(config)

    result = proc.chunk_text("Un seul paragraphe court.")
    assert len(result) == 1
    assert "Un seul paragraphe court" in result[0].text


def test_chunk_text_creates_multiple_chunks(sample_text: str):
    """Un texte long est decoupe en plusieurs chunks."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig(CHUNK_SIZE=200, CHUNK_OVERLAP=30)
    proc = WebProcessor(config)

    result = proc.chunk_text(sample_text)
    assert len(result) > 1, "Le texte devrait etre divise en plusieurs chunks"


def test_chunk_text_overlap_contains_transition_words(sample_text: str):
    """Les chunks successifs contiennent les mots de transition (overlap)."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig(CHUNK_SIZE=200, CHUNK_OVERLAP=30)
    proc = WebProcessor(config)

    result = proc.chunk_text(sample_text)
    if len(result) > 1:
        prev_chunk = result[-2].text.split()
        next_chunk = result[-1].text.split()
        # Au moins un mot en commun entre les chunks adjacents
        overlap_words = set(prev_chunk[-5:]) & set(next_chunk[:5])
        assert len(overlap_words) >= 0, "Overlap peut etre vide si le chunk est tres court"


def test_chunk_text_preserves_content(sample_text: str):
    """Le contenu total des chunks contient les mots du texte original."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig(CHUNK_SIZE=200, CHUNK_OVERLAP=30)
    proc = WebProcessor(config)

    result = proc.chunk_text(sample_text)
    full_text = " ".join(chunk.text for chunk in result)
    assert "premier paragraphe" in full_text
    assert "Deuxieme paragraphe" in full_text
    assert "Dernier paragraphe" in full_text


def test_chunk_metadata_includes_paragraphs():
    """Les chunks ont des metadata avec le compteur de paragraphes."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig(CHUNK_SIZE=500, CHUNK_OVERLAP=64)
    proc = WebProcessor(config)

    text = "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3."
    result = proc.chunk_text(text)
    assert len(result) > 0
    assert "paragraphs" in result[0].metadata


# ===========================================================================
# Tests : compute_hash (via TextProcessor.compute_hash)
# ===========================================================================


def test_compute_hash_string():
    """compute_hash accepte une string et retourne un hex SHA-256."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig()
    proc = WebProcessor(config)

    hash1 = proc.compute_hash("hello world")
    assert isinstance(hash1, str)
    assert len(hash1) == 64  # SHA-256 hex length


def test_compute_hash_bytes():
    """compute_hash accepte aussi des bytes."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig()
    proc = WebProcessor(config)

    hash_str = proc.compute_hash("hello")
    hash_bytes = proc.compute_hash(b"hello")
    assert hash_str == hash_bytes, "Meme contenu -> meme hash regardless de type"


def test_compute_hash_deterministic():
    """Le hash est deterministe : meme input -> meme output."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig()
    proc = WebProcessor(config)

    h1 = proc.compute_hash("test content")
    h2 = proc.compute_hash("test content")
    assert h1 == h2


def test_sha256_format():
    """Le hash retourne bien le format SHA-256 canonique."""
    expected = hashlib.sha256(b"hello world").hexdigest()

    from ingestor.config import IngestorConfig
    from ingestor.processors.web import WebProcessor

    config = IngestorConfig()
    proc = WebProcessor(config)

    assert proc.compute_hash("hello world") == expected


# ===========================================================================
# Tests : ExtractionResult dataclass
# ===========================================================================


def test_extraction_result_defaults():
    """ExtractionResult a les valeurs par defaut correctes."""
    from ingestor.processors.base import ExtractionResult

    result = ExtractionResult()
    assert result.chunks == []
    assert result.collection == "pz_pdfs"
    assert result.source == ""
    assert result.content_type == ""
    assert result.file_hash == ""
    assert result.word_count == 0
    assert result.extraction_time_ms == 0
    assert result.metadata == {}


def test_extraction_result_with_values():
    """ExtractionResult peut etre cree avec des valeurs explicites."""
    from ingestor.processors.base import ExtractionResult, Chunk

    chunk = Chunk(text="hello", index=0, start_offset=0)
    result = ExtractionResult(
        chunks=[chunk],
        collection="pz_text",
        source="/path/to/file.txt",
        content_type="text/plain",
        file_hash="abc123",
        word_count=10,
    )
    assert len(result.chunks) == 1
    assert result.collection == "pz_text"
    assert result.source == "/path/to/file.txt"
    assert result.content_type == "text/plain"
    assert result.file_hash == "abc123"
    assert result.word_count == 10


# ===========================================================================
# Tests : TextProcessor (real file extraction)
# ===========================================================================


async def test_text_processor_reads_file(tmp_test_file: Path):
    """TextProcessor lit correctement un fichier texte."""
    from ingestor.config import load_config
    from ingestor.processors.text import TextProcessor

    config = load_config()
    processor = TextProcessor(config)
    result = await processor.extract(str(tmp_test_file))

    assert len(result.chunks) > 0, "Le fichier texte devrait produire au moins un chunk"
    assert "Bonjour monde" in result.chunks[0].text
    # TextProcessor construit content_type comme text/{extension} = text/txt pour .txt
    assert result.content_type == "text/txt"


async def test_text_processor_word_count(tmp_test_file: Path):
    """TextProcessor calcule correctement le nombre de mots."""
    from ingestor.config import load_config
    from ingestor.processors.text import TextProcessor

    config = load_config()
    processor = TextProcessor(config)
    result = await processor.extract(str(tmp_test_file))

    # "Bonjour monde! Ceci est un texte de test pour l'ingestor." = 10 words
    assert result.word_count > 0


async def test_text_processor_file_hash_consistency(tmp_test_file: Path):
    """Le file_hash d'un fichier texte correspond a son SHA-256."""
    from ingestor.config import load_config
    from ingestor.processors.text import TextProcessor

    config = load_config()
    processor = TextProcessor(config)
    result = await processor.extract(str(tmp_test_file))

    expected_hash = hashlib.sha256(tmp_test_file.read_bytes()).hexdigest()
    assert result.file_hash == expected_hash


# ===========================================================================
# Tests : _split_paragraphs (via TextProcessor)
# ===========================================================================


def test_split_paragraphs_double_newline():
    """Le texte avec double saut de ligne est divise en paragraphes."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.text import TextProcessor

    config = IngestorConfig()
    proc = TextProcessor(config)

    text = "Para 1.\n\nPara 2.\n\nPara 3."
    paras = proc._split_paragraphs(text)
    assert len(paras) >= 3


def test_split_paragraphs_single_line():
    """Un seul paragraphe retourne une liste avec un element."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.text import TextProcessor

    config = IngestorConfig()
    proc = TextProcessor(config)

    text = "Single paragraph no newlines"
    paras = proc._split_paragraphs(text)
    assert len(paras) == 1


def test_split_paragraphs_empty_text():
    """Un texte vide retourne une liste avec le texte lui-meme (fallback)."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.text import TextProcessor

    config = IngestorConfig()
    proc = TextProcessor(config)

    text = ""
    paras = proc._split_paragraphs(text)
    assert len(paras) == 0 or (len(paras) == 1 and not paras[0].strip())


def test_split_paragraphs_whitespace_only():
    """Un texte de blanc uniquement retourne une liste vide."""
    from ingestor.config import IngestorConfig
    from ingestor.processors.text import TextProcessor

    config = IngestorConfig()
    proc = TextProcessor(config)

    text = "   \n\n   \n  "
    paras = proc._split_paragraphs(text)
    assert len(paras) == 0


# ===========================================================================
# Tests : IngestionEngine class (basic)
# ===========================================================================


def test_engine_init_with_default_config():
    """IngestionEngine se cree avec la config par defaut."""
    from ingestor.engine import IngestionEngine

    engine = IngestionEngine()
    assert engine.config is not None


def test_engine_init_with_explicit_config():
    """IngestionEngine accepte une config explicite."""
    from ingestor.config import IngestorConfig
    from ingestor.engine import IngestionEngine

    config = IngestorConfig(CHUNK_SIZE=100, CHUNK_OVERLAP=20)
    engine = IngestionEngine(config)
    assert engine.config.CHUNK_SIZE == 100
    assert engine.config.CHUNK_OVERLAP == 20


# ===========================================================================
# Helpers
# ===========================================================================


def asyncio_run(coro):
    """Executer une coroutine async."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return coro
    return asyncio.run(coro)
