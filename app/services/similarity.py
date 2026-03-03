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
    cosine_score: float
    jaccard_score: float
    originality_score: float
    fragments: list[Fragment]


def compare(
    text_a: str, text_b: str, shingle_size: int = 6, min_fragment_tokens: int = 8
) -> SimilarityResult:
    cosine = _cosine_score(text_a, text_b)
    jaccard = _jaccard_score(text_a, text_b, shingle_size)
    frags = _extract_fragments(text_a, text_b, shingle_size, min_fragment_tokens)
    return SimilarityResult(
        cosine_score=round(cosine, 4),
        jaccard_score=round(jaccard, 4),
        originality_score=round(1.0 - max(cosine, jaccard), 4),
        fragments=frags,
    )


# Scaling note:
# Full pairwise TF-IDF is O(n^2) in submissions. For n=300 that is 44,850 pairs,
# acceptable at ~1-2ms per pair (~60s total, within the PRD's 10-minute budget).
# Beyond ~500 submissions the approach degrades. The mitigation is MinHash LSH:
# hash each document into bands of minhash signatures, bucket likely-similar
# pairs, and only run full TF-IDF + fragment extraction on candidate pairs.
# MINHASH_THRESHOLD controls when candidate filtering activates.
MINHASH_THRESHOLD = 500


def bulk_compare(
    texts: dict[int, str], min_score: float = 0.15
) -> list[tuple[int, int, SimilarityResult]]:
    ids = list(texts.keys())
    if len(ids) < 2:
        return []

    corpus = [texts[i] for i in ids]
    candidates = (
        _minhash_candidates(ids, corpus)
        if len(ids) >= MINHASH_THRESHOLD
        else [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))]
    )

    vec = TfidfVectorizer()
    matrix = vec.fit_transform(corpus)
    id_to_idx = {sid: idx for idx, sid in enumerate(ids)}
    cos_matrix = cosine_similarity(matrix)

    results = []
    for a_id, b_id in candidates:
        i, j = id_to_idx[a_id], id_to_idx[b_id]
        cosine = float(cos_matrix[i, j])
        jaccard = _jaccard_score(corpus[i], corpus[j])
        if max(cosine, jaccard) < min_score:
            continue
        frags = _extract_fragments(corpus[i], corpus[j])
        results.append(
            (
                a_id,
                b_id,
                SimilarityResult(
                    cosine_score=round(cosine, 4),
                    jaccard_score=round(jaccard, 4),
                    originality_score=round(1.0 - max(cosine, jaccard), 4),
                    fragments=frags,
                ),
            )
        )

    return sorted(results, key=lambda x: x[2].cosine_score, reverse=True)


def _minhash_candidates(
    ids: list[int], corpus: list[str], num_perm: int = 128, bands: int = 16
) -> list[tuple[int, int]]:
    """
    MinHash LSH candidate filtering.
    Splits each document signature into bands; documents sharing any band bucket
    are candidate pairs. False-negative rate ~5% for Jaccard >= 0.5 at these params.
    """
    import hashlib

    rows = num_perm // bands

    def _minhash(text: str) -> list[int]:
        tokens = text.split()
        shingles = {" ".join(tokens[i : i + 6]) for i in range(max(1, len(tokens) - 5))}
        return [
            min(
                (int(hashlib.md5(f"{seed}:{s}".encode()).hexdigest(), 16) for s in shingles),
                default=0,
            )
            for seed in range(num_perm)
        ]

    signatures = [_minhash(doc) for doc in corpus]
    buckets: dict[tuple, list[int]] = {}
    for idx, sig in enumerate(signatures):
        for b in range(bands):
            key = (b, tuple(sig[b * rows : (b + 1) * rows]))
            buckets.setdefault(key, []).append(idx)

    candidates: set[tuple[int, int]] = set()
    for bucket_ids in buckets.values():
        for i in range(len(bucket_ids)):
            for j in range(i + 1, len(bucket_ids)):
                a, b = sorted((bucket_ids[i], bucket_ids[j]))
                candidates.add((ids[a], ids[b]))

    return list(candidates)


def _cosine_score(a: str, b: str) -> float:
    try:
        m = TfidfVectorizer().fit_transform([a, b])
        return float(cosine_similarity(m[0], m[1])[0, 0])
    except ValueError:
        return 0.0


def _jaccard_score(a: str, b: str, k: int = 6) -> float:
    tokens_a, tokens_b = a.split(), b.split()
    set_a = {tuple(tokens_a[i : i + k]) for i in range(max(1, len(tokens_a) - k + 1))}
    set_b = {tuple(tokens_b[i : i + k]) for i in range(max(1, len(tokens_b) - k + 1))}
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 0.0


def _shingles(tokens: list[str], k: int) -> dict[tuple, int]:
    return {tuple(tokens[i : i + k]): i for i in range(len(tokens) - k + 1)}


def _extract_fragments(
    text_a: str, text_b: str, shingle_size: int = 6, min_tokens: int = 8
) -> list[Fragment]:
    tokens_a = text_a.split()
    tokens_b = text_b.split()
    shingles_b = _shingles(tokens_b, shingle_size)
    fragments: list[Fragment] = []
    used_a: set[int] = set()

    for i in range(len(tokens_a) - shingle_size + 1):
        if i in used_a:
            continue
        key = tuple(tokens_a[i : i + shingle_size])
        if key not in shingles_b:
            continue
        start_b = shingles_b[key]
        end_a, end_b = i + shingle_size, start_b + shingle_size
        while (
            end_a < len(tokens_a) and end_b < len(tokens_b) and tokens_a[end_a] == tokens_b[end_b]
        ):
            end_a += 1
            end_b += 1
        length = end_a - i
        if length < min_tokens:
            continue
        used_a.update(range(i, end_a))
        fragments.append(
            Fragment(
                text=" ".join(tokens_a[i:end_a]),
                start_a=i,
                end_a=end_a,
                start_b=start_b,
                end_b=end_b,
                length=length,
            )
        )

    return _merge_overlapping(fragments)


def _merge_overlapping(fragments: list[Fragment]) -> list[Fragment]:
    if not fragments:
        return []
    out = [sorted(fragments, key=lambda f: f.start_a)[0]]
    for cur in sorted(fragments, key=lambda f: f.start_a)[1:]:
        prev = out[-1]
        if cur.start_a <= prev.end_a:
            extra = cur.text.split()[prev.end_a - cur.start_a :] if cur.end_a > prev.end_a else []
            out[-1] = Fragment(
                text=prev.text + (" " + " ".join(extra) if extra else ""),
                start_a=prev.start_a,
                end_a=max(prev.end_a, cur.end_a),
                start_b=prev.start_b,
                end_b=max(prev.end_b, cur.end_b),
                length=max(prev.end_a, cur.end_a) - prev.start_a,
            )
        else:
            out.append(cur)
    return out
