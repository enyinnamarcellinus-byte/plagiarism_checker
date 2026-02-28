from dataclasses import dataclass
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


@dataclass
class Fragment:
    text: str
    start_a: int
    end_a: int
    start_b: int
    end_b: int
    length: int  # token count


@dataclass
class SimilarityResult:
    score: float           # 0.0 – 1.0 cosine similarity
    fragments: list[Fragment]


def compare(text_a: str, text_b: str, shingle_size: int = 6, min_fragment_tokens: int = 8) -> SimilarityResult:
    score = _cosine_score(text_a, text_b)
    fragments = _extract_fragments(text_a, text_b, shingle_size, min_fragment_tokens)
    return SimilarityResult(score=round(score, 4), fragments=fragments)


def bulk_compare(texts: dict[int, str], min_score: float = 0.15) -> list[tuple[int, int, SimilarityResult]]:
    """
    Compare all pairs. texts is {submission_id: normalised_text}.
    Returns only pairs above min_score threshold.
    """
    ids = list(texts.keys())
    if len(ids) < 2:
        return []

    corpus = [texts[i] for i in ids]
    vec = TfidfVectorizer()
    matrix = vec.fit_transform(corpus)
    sim_matrix = cosine_similarity(matrix)

    results = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            score = float(sim_matrix[i, j])
            if score < min_score:
                continue
            fragments = _extract_fragments(corpus[i], corpus[j])
            results.append((ids[i], ids[j], SimilarityResult(score=round(score, 4), fragments=fragments)))

    return sorted(results, key=lambda x: x[2].score, reverse=True)


# --- internals ---

def _cosine_score(a: str, b: str) -> float:
    vec = TfidfVectorizer()
    try:
        matrix = vec.fit_transform([a, b])
        return float(cosine_similarity(matrix[0], matrix[1])[0, 0])
    except ValueError:
        return 0.0


def _shingles(tokens: list[str], k: int) -> dict[tuple, int]:
    """Map each k-gram to its first occurrence index."""
    return {tuple(tokens[i:i+k]): i for i in range(len(tokens) - k + 1)}


def _extract_fragments(
    text_a: str,
    text_b: str,
    shingle_size: int = 6,
    min_tokens: int = 8,
) -> list[Fragment]:
    tokens_a = text_a.split()
    tokens_b = text_b.split()

    shingles_b = _shingles(tokens_b, shingle_size)

    # Find all matching window start positions
    raw_matches: list[tuple[int, int]] = []  # (start_a, start_b)
    for i in range(len(tokens_a) - shingle_size + 1):
        key = tuple(tokens_a[i:i + shingle_size])
        if key in shingles_b:
            raw_matches.append((i, shingles_b[key]))

    if not raw_matches:
        return []

    # Extend each seed match as far as tokens agree
    fragments: list[Fragment] = []
    used_a: set[int] = set()

    for start_a, start_b in raw_matches:
        if start_a in used_a:
            continue

        end_a, end_b = start_a + shingle_size, start_b + shingle_size

        # extend right
        while (end_a < len(tokens_a) and end_b < len(tokens_b)
               and tokens_a[end_a] == tokens_b[end_b]):
            end_a += 1
            end_b += 1

        length = end_a - start_a
        if length < min_tokens:
            continue

        used_a.update(range(start_a, end_a))
        fragment_tokens = tokens_a[start_a:end_a]
        fragments.append(Fragment(
            text=" ".join(fragment_tokens),
            start_a=start_a, end_a=end_a,
            start_b=start_b, end_b=end_b,
            length=length,
        ))

    return _merge_overlapping(fragments)


def _merge_overlapping(fragments: list[Fragment]) -> list[Fragment]:
    """Merge fragments that are adjacent or overlapping in doc A."""
    if not fragments:
        return []
    sorted_frags = sorted(fragments, key=lambda f: f.start_a)
    merged = [sorted_frags[0]]
    for cur in sorted_frags[1:]:
        prev = merged[-1]
        if cur.start_a <= prev.end_a:  # overlap or adjacent
            new_end_a = max(prev.end_a, cur.end_a)
            new_end_b = max(prev.end_b, cur.end_b)
            tokens = cur.text.split() if cur.end_a > prev.end_a else []
            merged[-1] = Fragment(
                text=prev.text + (" " + " ".join(tokens) if tokens else ""),
                start_a=prev.start_a, end_a=new_end_a,
                start_b=prev.start_b, end_b=new_end_b,
                length=new_end_a - prev.start_a,
            )
        else:
            merged.append(cur)
    return merged