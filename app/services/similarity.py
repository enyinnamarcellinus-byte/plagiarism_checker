from dataclasses import dataclass
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Fragment:
    text: str
    start_a: int
    end_a: int
    start_b: int
    end_b: int
    length: int


@dataclass
class SimilarityResult:
    cosine_score: float       # TF-IDF cosine
    jaccard_score: float      # shingle-set Jaccard
    originality_score: float  # 1 - max(cosine, jaccard)
    fragments: list[Fragment]


def compare(text_a: str, text_b: str, shingle_size: int = 6, min_fragment_tokens: int = 8) -> SimilarityResult:
    cosine  = _cosine_score(text_a, text_b)
    jaccard = _jaccard_score(text_a, text_b, shingle_size)
    frags   = _extract_fragments(text_a, text_b, shingle_size, min_fragment_tokens)
    return SimilarityResult(
        cosine_score=round(cosine, 4),
        jaccard_score=round(jaccard, 4),
        originality_score=round(1.0 - max(cosine, jaccard), 4),
        fragments=frags,
    )


def bulk_compare(texts: dict[int, str], min_score: float = 0.15) -> list[tuple[int, int, SimilarityResult]]:
    ids = list(texts.keys())
    if len(ids) < 2:
        return []

    corpus = [texts[i] for i in ids]
    vec    = TfidfVectorizer()
    matrix = vec.fit_transform(corpus)
    cos_matrix = cosine_similarity(matrix)

    results = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            cosine  = float(cos_matrix[i, j])
            jaccard = _jaccard_score(corpus[i], corpus[j])
            if max(cosine, jaccard) < min_score:
                continue
            frags = _extract_fragments(corpus[i], corpus[j])
            results.append((ids[i], ids[j], SimilarityResult(
                cosine_score=round(cosine, 4),
                jaccard_score=round(jaccard, 4),
                originality_score=round(1.0 - max(cosine, jaccard), 4),
                fragments=frags,
            )))

    return sorted(results, key=lambda x: x[2].cosine_score, reverse=True)


# --- internals ---

def _cosine_score(a: str, b: str) -> float:
    try:
        m = TfidfVectorizer().fit_transform([a, b])
        return float(cosine_similarity(m[0], m[1])[0, 0])
    except ValueError:
        return 0.0


def _jaccard_score(a: str, b: str, k: int = 6) -> float:
    """Jaccard similarity on k-shingle sets."""
    tokens_a, tokens_b = a.split(), b.split()
    set_a = {tuple(tokens_a[i:i+k]) for i in range(max(1, len(tokens_a) - k + 1))}
    set_b = {tuple(tokens_b[i:i+k]) for i in range(max(1, len(tokens_b) - k + 1))}
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 0.0


def _shingles(tokens: list[str], k: int) -> dict[tuple, int]:
    return {tuple(tokens[i:i+k]): i for i in range(len(tokens) - k + 1)}


def _extract_fragments(text_a: str, text_b: str, shingle_size: int = 6, min_tokens: int = 8) -> list[Fragment]:
    tokens_a = text_a.split()
    tokens_b = text_b.split()
    shingles_b = _shingles(tokens_b, shingle_size)

    fragments: list[Fragment] = []
    used_a: set[int] = set()

    for i in range(len(tokens_a) - shingle_size + 1):
        if i in used_a:
            continue
        key = tuple(tokens_a[i:i + shingle_size])
        if key not in shingles_b:
            continue

        start_b = shingles_b[key]
        end_a, end_b = i + shingle_size, start_b + shingle_size

        while end_a < len(tokens_a) and end_b < len(tokens_b) and tokens_a[end_a] == tokens_b[end_b]:
            end_a += 1
            end_b += 1

        length = end_a - i
        if length < min_tokens:
            continue

        used_a.update(range(i, end_a))
        fragments.append(Fragment(
            text=" ".join(tokens_a[i:end_a]),
            start_a=i, end_a=end_a,
            start_b=start_b, end_b=end_b,
            length=length,
        ))

    return _merge_overlapping(fragments)


def _merge_overlapping(fragments: list[Fragment]) -> list[Fragment]:
    if not fragments:
        return []
    out = [sorted(fragments, key=lambda f: f.start_a)[0]]
    for cur in sorted(fragments, key=lambda f: f.start_a)[1:]:
        prev = out[-1]
        if cur.start_a <= prev.end_a:
            extra = cur.text.split()[prev.end_a - cur.start_a:] if cur.end_a > prev.end_a else []
            out[-1] = Fragment(
                text=prev.text + (" " + " ".join(extra) if extra else ""),
                start_a=prev.start_a, end_a=max(prev.end_a, cur.end_a),
                start_b=prev.start_b, end_b=max(prev.end_b, cur.end_b),
                length=max(prev.end_a, cur.end_a) - prev.start_a,
            )
        else:
            out.append(cur)
    return out
