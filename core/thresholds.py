"""
Central configuration for all heuristic thresholds used across the OCR pipeline.

Each threshold is grouped by domain and documented with:
  - purpose (what it controls)
  - typical value range
  - tuning context (which control sheets / subjects it was tuned for)

Usage:
    from core.thresholds import OcrThresholds, cell_shape, digit_vote, ...

    thresholds = OcrThresholds()
    if ink_ratio > thresholds.cell_shape.max_ink_ratio_for_minus:
        ...
"""

from dataclasses import dataclass, field


# ── Shape / component analysis ──────────────────────────────────────────

@dataclass(frozen=True)
class CellShapeThresholds:
    """Heuristic thresholds for component-based shape analysis in CellShapeRules."""

    # -- Crossed-out detection --
    min_component_area_ratio: float = 0.07          # components >= this * cell_area → "major"
    min_major_components_cross: int = 2              # at least this many major components to flag crossed
    min_significant_components_cross: int = 8        # total significant components threshold
    min_foreground_ratio_cross: float = 0.16         # ink / cell area for crossed pattern
    alt_largest_area_ratio: float = 0.28             # alternative: largest component must exceed this
    alt_significant_components_cross: int = 10       # alternative: significant components
    alt_foreground_ratio_cross: float = 0.24         # alternative: ink ratio

    # -- Dotted frame removal (cell) --
    min_largest_area_cell: int = 220                 # pixels; if largest component < this → return empty
    min_largest_area_cell_ratio: float = 0.035       # alternative: largest < this * cell_area → empty
    keep_area_factor: float = 0.08                   # keep components area >= largest * this
    middle_x_low: float = 0.18                       # middle zone: cx > w * this
    middle_x_high: float = 0.82                      # middle zone: cx < w * this
    middle_y_low: float = 0.18                       # middle zone: cy > h * this
    middle_y_high: float = 0.90                      # middle zone: cy < h * this
    min_mark_area: int = 25                          # min component area to be a "mark"
    min_mark_w: int = 2                              # min component width for mark
    min_mark_h: int = 2                              # min component height for mark

    # -- Dotted frame removal (row) --
    border_x_low: float = 0.12                       # near-border: cx < w * this
    border_x_high: float = 0.88                      # near-border: cx > w * this
    border_y_low: float = 0.10                       # near-border: cy < h * this
    border_y_high: float = 0.94                      # near-border: cy > h * this
    central_x_low: float = 0.14                      # central zone bound
    central_x_high: float = 0.86
    central_y_low: float = 0.12
    central_y_high: float = 0.92
    punct_x_low: float = 0.20                        # punctuation zone bound
    punct_x_high: float = 0.80
    punct_y_low: float = 0.30
    punct_y_high: float = 0.94
    min_area_central: int = 85                       # min area for central components
    min_area_punct: int = 10                         # min area for punctuation-zone components

    # -- Minus detection --
    max_ink_ratio_for_minus: float = 0.15
    alt_ink_ratio_for_minus_ceiling: float = 0.35       # alternative: allow up to this ink_ratio if component is tall enough
    alt_min_height_px: int = 40                          # component height must be at least this for alt minus branch
    min_comma_like_area: int = 20
    min_aspect_for_minus: float = 1.8
    max_minus_height_ratio: float = 0.20             # component height <= h * this
    minus_y_low: float = 0.22                        # cy > h * this
    minus_y_high: float = 0.70

    # -- Comma detection --
    min_component_area_comma: int = 10
    max_comma_area_base: float = 220.0               # pixels base
    max_comma_area_ratio: float = 0.08               # max area = max(base, cell_area * this)
    max_comma_w_ratio: float = 0.38                  # primary width <= w * this
    max_comma_h_ratio: float = 0.55                  # primary height <= h * this (two-component)
    min_comma_cy_ratio: float = 0.58                 # primary cy > h * this
    max_secondary_area_ratio: float = 0.25           # secondary area <= primary * this
    max_secondary_cx_dist: float = 0.35              # |cx2 - cx1| <= w * this
    max_comma_h_ratio_single: float = 0.52           # primary height <= w * this (single-component)
    comma_single_x_low: float = 0.18
    comma_single_x_high: float = 0.82
    min_comma_cy_ratio_single: float = 0.63

    # -- Shape-based digit guess --
    min_shape_ink_pixels: int = 120
    min_hole_area_ratio: float = 0.02                # hole / roi >= this → counts as hole
    mid_density_8: float = 0.40                      # density thresholds for digit 8/6/0 rules
    left_density_6: float = 0.50
    bot_density_6: float = 0.52
    aspect_1: float = 0.5                            # w/h <= this → candidate "1"
    min_center_right_1: float = 0.55                 # max(center_d, right_d) >= this
    right_density_4: float = 0.55
    center_density_4_max: float = 0.22
    top_density_4: float = 0.30
    top_density_7: float = 0.35
    bot_density_7_max: float = 0.22
    center_density_7: float = 0.42
    left_density_7_max: float = 0.25
    top_density_3a: float = 0.35
    mid_density_3a: float = 0.35
    bot_density_3a: float = 0.45
    center_density_3a: float = 0.50
    right_density_3a: float = 0.40
    top_density_3b: float = 0.35
    mid_density_3b_low: float = 0.45
    bot_density_3b_low: float = 0.20
    bot_density_3b_high: float = 0.35
    left_density_3b: float = 0.28
    center_density_3b: float = 0.40
    right_density_3b: float = 0.25
    top_density_2: float = 0.22
    bot_density_2: float = 0.25
    center_density_2: float = 0.40
    left_density_2_max: float = 0.25
    right_density_2_max: float = 0.20
    top_density_5: float = 0.40
    mid_density_5_low: float = 0.24
    mid_density_5_high: float = 0.38
    bot_density_5_low: float = 0.20
    bot_density_5_high: float = 0.36
    left_density_5: float = 0.35
    center_density_5: float = 0.40
    right_density_5_max: float = 0.24

    # -- School-style 7 vs 1 disambiguation --
    seven_crossbar_y_low: float = 0.36              # middle-leg band start inside symbol bbox
    seven_crossbar_y_high: float = 0.76             # middle-leg band end inside symbol bbox
    seven_crossbar_min_run_ratio: float = 0.35      # horizontal run >= bbox width * this
    seven_crossbar_min_run_px: int = 7              # absolute minimum horizontal run in px
    one_plain_aspect_max: float = 0.70              # no crossbar + narrow bbox -> likely 1

    # -- Mark detection --
    min_ink_ratio_mark: float = 0.05
    max_ink_ratio_mark: float = 0.60
    min_comp_area_mark_ratio: float = 0.04           # component area >= total_pixels * this
    mark_zone_w_low: float = 0.15
    mark_zone_w_high: float = 0.85
    mark_zone_h_low: float = 0.15
    mark_zone_h_high: float = 0.85
    min_comp_w_mark_ratio: float = 0.15              # comp_w > w * this
    min_comp_h_mark_ratio: float = 0.15              # comp_h > h * this


# ── Digit vote weights ──────────────────────────────────────────────────

@dataclass(frozen=True)
class DigitVoteThresholds:
    """Vote weights and confidence thresholds for digit classification."""

    # Source vote weights
    paddleocr_weight: float = 1.08
    hog_svm_weight: float = 1.18
    digit_engine_weight: float = 1.06
    shape_agree_weight: float = 2.80
    shape_row_weight: float = 1.45
    shape_standard_weight: float = 1.50
    tesseract_psm8_13_weight: float = 0.40
    tesseract_psm10_weight: float = 0.26
    tesseract_cell_weight: float = 0.55
    default_weight: float = 0.78

    # PSM candidate confidence levels
    psm8_confidence: float = 0.60
    psm13_confidence: float = 0.58
    psm10_confidence: float = 0.52

    # Shape candidate confidence levels
    shape_row_confidence: float = 0.62
    shape_standard_confidence: float = 0.56
    shape_agree_confidence: float = 0.22

    # Vote selection thresholds
    alt_score_min_ratio: float = 0.68                # alt_score >= best_score * this
    alt_conf_min: float = 0.55                       # max_confidences[alt] >= this
    low_score_threshold: float = 0.50                # best_score < this → empty
    low_conf_threshold: float = 0.60                 # best_conf < this → empty (with low score)
    close_vote_diff: float = 0.08                    # best - second < this → doubtful
    close_conf_threshold: float = 0.70               # best_conf < this (with close vote)


# ── Cell classifier flow ────────────────────────────────────────────────

@dataclass(frozen=True)
class CellFlowThresholds:
    """Thresholds used in CellClassifierFlow during single-cell classification."""

    marked_cell_confidence: float = 0.95
    marked_cell_empty_confidence: float = 0.99
    empty_cell_confidence: float = 0.99
    empty_early_break_confidence: float = 0.95       # if top hypothesis is "" with conf > this
    hybrid_digit_confidence: float = 0.72
    top_candidates_count: int = 3
    close_candidate_diff: float = 0.15               # if difference < this → doubtful


# ── Answer resolver ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResolverThresholds:
    """Scoring and decision thresholds for AnswerResolver."""

    # Scoring penalties
    skip_cell_penalty_signal: float = -0.10
    skip_cell_penalty_no_signal: float = -0.02
    match_base_score: float = 0.55                   # + score_map[token]
    mismatch_penalty_signal: float = -0.35
    mismatch_penalty_no_signal: float = -0.12
    skip_token_penalty_comma_dash: float = -0.16
    skip_token_penalty_other: float = -0.32

    # Bias-to-key
    key_bias_score_min: float = 0.50                 # variant score must be >= this
    key_bias_score_delta: float = 0.05               # variant score >= current_score - this

    # Math healing
    comma_confidence_threshold: float = 0.55         # comma entries with conf < this → low conf

    # DP / edit distance
    lev_distance_max: int = 1                        # max edit distance for bias-to-key


# ── Image preprocessor ──────────────────────────────────────────────────

@dataclass(frozen=True)
class PreprocessorThresholds:
    """Thresholds used in ImagePreprocessor for image enhancement."""

    upscale_min_h: int = 64                           # if cell h < this → upscale
    upscale_min_w: int = 32
    upscale_min_scale: float = 2.0
    upscale_target_ratio: float = 0.7                 # if short_side < target * this → upscale
    clahe_clip_limit: float = 2.0
    clahe_grid_size: int = 8
    skew_max_angle: float = 5.0                       # degrees
    skew_min_angle: float = 0.3                       # ignore if |angle| < this
    denoise_kernel_size: int = 3
    adaptive_block_size_divisor: int = 4              # block_size = max(11, h // this | 1)
    adaptive_c_constant: int = 8
    morph_kernel_size: int = 2


# ── Top-level bundle ────────────────────────────────────────────────────

@dataclass(frozen=True)
class OcrThresholds:
    """Single point of access for all OCR heuristics thresholds."""

    cell_shape: CellShapeThresholds = field(default_factory=CellShapeThresholds)
    digit_vote: DigitVoteThresholds = field(default_factory=DigitVoteThresholds)
    cell_flow: CellFlowThresholds = field(default_factory=CellFlowThresholds)
    resolver: ResolverThresholds = field(default_factory=ResolverThresholds)
    preprocessor: PreprocessorThresholds = field(default_factory=PreprocessorThresholds)


# ── Convenience singleton ───────────────────────────────────────────────

_DEFAULT: OcrThresholds | None = None


def get_thresholds() -> OcrThresholds:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = OcrThresholds()
    return _DEFAULT
