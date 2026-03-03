from dataclasses import dataclass

from .similarity import Fragment


@dataclass
class ClassificationResult:
    predicted_type: str  # verbatim | near_copy | patchwork | structural
    score_verbatim: float
    score_near_copy: float
    score_patchwork: float
    score_structural: float


def classify(
    fragments: list[Fragment],
    similarity_score: float,
    doc_a_token_count: int,
    doc_b_token_count: int,
) -> ClassificationResult:
    if not fragments:
        # No fragments but moderate cosine → structural similarity
        scores = _structural_dominant(similarity_score)
        return _result(scores)

    avg_doc_len = (doc_a_token_count + doc_b_token_count) / 2
    total_matched = sum(f.length for f in fragments)
    overlap_ratio = total_matched / max(avg_doc_len, 1)
    longest = max(f.length for f in fragments)
    count = len(fragments)
    dispersion = _dispersion(fragments, doc_a_token_count)
    order_preserved = _order_preserved(fragments)

    scores = {
        "verbatim": _score_verbatim(longest, overlap_ratio, count),
        "near_copy": _score_near_copy(similarity_score, overlap_ratio, longest),
        "patchwork": _score_patchwork(count, dispersion, longest),
        "structural": _score_structural(similarity_score, overlap_ratio, order_preserved),
    }

    # normalise so all four sum to 1.0
    total = sum(scores.values()) or 1.0
    scores = {k: round(v / total, 4) for k, v in scores.items()}

    return _result(scores)


# --- scoring functions (each returns 0.0 – 1.0 raw signal) ---


def _score_verbatim(longest: int, overlap_ratio: float, count: int) -> float:
    # Large contiguous block, few fragments
    long_block = min(longest / 80, 1.0)  # saturates at 80 tokens (~60 words)
    sparse = max(0.0, 1.0 - count / 5)  # penalise if many fragments
    return long_block * 0.7 + overlap_ratio * 0.2 + sparse * 0.1


def _score_near_copy(similarity_score: float, overlap_ratio: float, longest: int) -> float:
    # High cosine but no single dominant fragment
    short_longest = max(0.0, 1.0 - longest / 40)
    return similarity_score * 0.5 + overlap_ratio * 0.3 + short_longest * 0.2


def _score_patchwork(count: int, dispersion: float, longest: int) -> float:
    # Many small fragments spread across both docs
    many_frags = min(count / 10, 1.0)  # saturates at 10 fragments
    short_frags = max(0.0, 1.0 - longest / 30)
    return many_frags * 0.4 + dispersion * 0.4 + short_frags * 0.2


def _score_structural(
    similarity_score: float, overlap_ratio: float, order_preserved: float
) -> float:
    # Order preserved but low raw overlap (different words, same structure)
    low_overlap = max(0.0, 1.0 - overlap_ratio * 2)
    return order_preserved * 0.5 + similarity_score * 0.3 + low_overlap * 0.2


def _structural_dominant(similarity_score: float) -> dict:
    base = similarity_score * 0.6
    return {"verbatim": 0.05, "near_copy": 0.15, "patchwork": 0.05, "structural": base}


# --- feature helpers ---


def _dispersion(fragments: list[Fragment], doc_len: int) -> float:
    """How spread are fragments across the document? 0=clustered, 1=evenly spread."""
    if len(fragments) < 2 or doc_len == 0:
        return 0.0
    positions = [f.start_a / doc_len for f in fragments]
    gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    # high variance in gaps = clustered; low variance = evenly spread
    import statistics

    ideal_gap = 1.0 / len(fragments)
    variance = statistics.variance(gaps) if len(gaps) > 1 else 0.0
    return max(0.0, 1.0 - variance / (ideal_gap + 1e-6))


def _order_preserved(fragments: list[Fragment]) -> float:
    """Are fragments in the same relative order in both docs? 1=fully preserved."""
    if len(fragments) < 2:
        return 1.0
    positions_b = [f.start_b for f in sorted(fragments, key=lambda f: f.start_a)]
    inversions = sum(
        1
        for i in range(len(positions_b))
        for j in range(i + 1, len(positions_b))
        if positions_b[i] > positions_b[j]
    )
    max_inversions = len(positions_b) * (len(positions_b) - 1) / 2
    return round(1.0 - inversions / max(max_inversions, 1), 4)


def _result(scores: dict) -> ClassificationResult:
    predicted = max(scores, key=scores.get)
    return ClassificationResult(
        predicted_type=predicted, **{f"score_{k}": v for k, v in scores.items()}
    )
