"""Deterministic project-authored procedural images for Phase 22.

The generator writes two physically separate views of every sample.  Model
records contain only a local image path and target labels.  Hidden records
contain the scene description and domain-randomization controls used to derive
those labels.  Training code is required to consume only model records.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.config import file_sha256, local_only_path
from app.ml.data.image_annotations import IMAGE_ANNOTATION_SCHEMA_VERSION

GENERATOR_VERSION: Final[str] = "synthetic-image-generator-v1"
DEFAULT_DATASET_ID: Final[str] = "indra-synthetic-image-v1"
DEFAULT_DATASET_VERSION: Final[str] = "1.0.0"
DEFAULT_SEED: Final[int] = 220022
DEFAULT_CREATION_TIMESTAMP: Final[datetime] = datetime(
    2026, 9, 24, 6, 0, tzinfo=timezone.utc
)
SPLITS: Final[tuple[str, ...]] = ("train", "validation", "test")
IMAGE_LABELS: Final[tuple[str, ...]] = (
    "FLOODED_SCENE",
    "HEAVY_RAIN_VISUAL",
    "STANDING_WATER",
    "STORM_DAMAGE",
    "NORMAL_SCENE",
)
SCENE_CLASSES: Final[tuple[str, ...]] = (
    "NORMAL_DRY",
    "NORMAL_WET_SURFACE",
    "NORMAL_DARK",
    "STANDING_WATER_ONLY",
    "FLOOD_WITHOUT_HEAVY_RAIN",
    "HEAVY_RAIN_WITHOUT_FLOODING",
    "STORM_DAMAGE_WITHOUT_FLOODING",
    "FLOOD_RAIN_STANDING_WATER",
    "FLOOD_AND_STANDING_WATER",
    "RAIN_AND_STANDING_WATER",
    "RAIN_AND_STORM_DAMAGE",
    "FLOOD_AND_STORM_DAMAGE",
)
SCENE_CLASS_LABELS: Final[dict[str, tuple[str, ...]]] = {
    "NORMAL_DRY": ("NORMAL_SCENE",),
    "NORMAL_WET_SURFACE": ("NORMAL_SCENE",),
    "NORMAL_DARK": ("NORMAL_SCENE",),
    "STANDING_WATER_ONLY": ("STANDING_WATER",),
    "FLOOD_WITHOUT_HEAVY_RAIN": ("FLOODED_SCENE", "STANDING_WATER"),
    "HEAVY_RAIN_WITHOUT_FLOODING": ("HEAVY_RAIN_VISUAL",),
    "STORM_DAMAGE_WITHOUT_FLOODING": ("STORM_DAMAGE",),
    "FLOOD_RAIN_STANDING_WATER": (
        "FLOODED_SCENE",
        "HEAVY_RAIN_VISUAL",
        "STANDING_WATER",
    ),
    "FLOOD_AND_STANDING_WATER": ("FLOODED_SCENE", "STANDING_WATER"),
    "RAIN_AND_STANDING_WATER": ("HEAVY_RAIN_VISUAL", "STANDING_WATER"),
    "RAIN_AND_STORM_DAMAGE": ("HEAVY_RAIN_VISUAL", "STORM_DAMAGE"),
    "FLOOD_AND_STORM_DAMAGE": (
        "FLOODED_SCENE",
        "STANDING_WATER",
        "STORM_DAMAGE",
    ),
}
HARD_NEGATIVE_SCENES: Final[tuple[str, ...]] = (
    "NORMAL_WET_SURFACE",
    "NORMAL_DARK",
    "STANDING_WATER_ONLY",
    "FLOOD_WITHOUT_HEAVY_RAIN",
    "HEAVY_RAIN_WITHOUT_FLOODING",
    "STORM_DAMAGE_WITHOUT_FLOODING",
)

SPLIT_SCENE_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "train": (
        "metro_crossing",
        "residential_lane",
        "market_corridor",
        "apartment_court",
        "village_link",
        "bus_depot",
        "canal_service_road",
        "suburban_curve",
    ),
    "validation": (
        "campus_spine",
        "warehouse_arc",
        "civic_plaza",
        "orchard_connector",
    ),
    "test": (
        "riverside_embankment",
        "hill_town_switchback",
        "harbor_access",
        "railway_underpass",
    ),
}
SPLIT_BACKGROUND_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "train": (
        "warm_dense_urban",
        "cool_residential",
        "green_village",
        "neutral_commercial",
        "brick_industrial",
        "concrete_suburban",
    ),
    "validation": (
        "pale_institutional",
        "rust_warehouse",
        "tree_lined_civic",
    ),
    "test": (
        "blue_riverside",
        "stone_hillside",
        "salt_harbor",
        "steel_railway",
    ),
}
SPLIT_PARAMETER_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "train": (
        "train_soft_wide",
        "train_crisp_narrow",
        "train_noisy_oblique",
        "train_hazy_centered",
        "train_occluded_low",
    ),
    "validation": (
        "validation_desaturated_high",
        "validation_warm_offset",
        "validation_blurred_low",
    ),
    "test": (
        "test_cool_compressed",
        "test_backlit_oblique",
        "test_high_occlusion",
        "test_mixed_visibility",
    ),
}
CAMERA_VIEWS: Final[tuple[str, ...]] = (
    "STREET_LOW",
    "EYE_LEVEL",
    "ELEVATED",
    "OBLIQUE_LEFT",
    "OBLIQUE_RIGHT",
)
LIGHTING_VALUES: Final[tuple[str, ...]] = (
    "DAYLIGHT",
    "OVERCAST",
    "TWILIGHT",
    "LOW_LIGHT",
)


class SyntheticImageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyntheticImageGeneratorConfig(SyntheticImageModel):
    dataset_id: str = DEFAULT_DATASET_ID
    dataset_version: str = DEFAULT_DATASET_VERSION
    seed: int = DEFAULT_SEED
    train_images: int = Field(default=70_000, ge=12)
    validation_images: int = Field(default=15_000, ge=12)
    test_images: int = Field(default=15_000, ge=12)
    image_width: int = Field(default=64, ge=32, le=512)
    image_height: int = Field(default=64, ge=32, le=512)
    png_compress_level: int = Field(default=1, ge=0, le=9)
    generator_workers: int = Field(default=8, ge=1, le=32)
    creation_timestamp: datetime = DEFAULT_CREATION_TIMESTAMP

    @model_validator(mode="after")
    def validate_configuration(self) -> "SyntheticImageGeneratorConfig":
        if self.creation_timestamp.tzinfo is None:
            raise ValueError("creation_timestamp must be timezone-aware")
        return self

    @property
    def split_counts(self) -> dict[str, int]:
        return {
            "train": self.train_images,
            "validation": self.validation_images,
            "test": self.test_images,
        }

    @property
    def image_count(self) -> int:
        return sum(self.split_counts.values())


class DomainRandomization(SyntheticImageModel):
    brightness: float
    contrast: float
    blur_radius: float
    sensor_noise_std: float
    jpeg_quality: int
    compression_applied: bool
    rain_streak_count: int
    occlusion_fraction: float
    crop_scale: float
    horizontal_flip: bool


class SyntheticImageGroundTruth(SyntheticImageModel):
    scenario_id: str
    image_id: str
    image_path: str
    split: Literal["train", "validation", "test"]
    ordinal: int = Field(ge=0)
    scene_class: str
    labels: list[str]
    water_level: float = Field(ge=0.0, le=1.0)
    rain_intensity: float = Field(ge=0.0, le=1.0)
    damage_level: float = Field(ge=0.0, le=1.0)
    lighting: str
    camera_view: str
    background_family: str
    weather_context: str
    scene_family: str
    template_id: str
    parameter_family: str
    parameter_combination_id: str
    hard_negative_category: str | None = None
    surface_wet: bool
    domain_randomization: DomainRandomization
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    detected_format: Literal["PNG"] = "PNG"
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_version: str = GENERATOR_VERSION

    @model_validator(mode="after")
    def validate_scene_labels(self) -> "SyntheticImageGroundTruth":
        if tuple(self.labels) != SCENE_CLASS_LABELS.get(self.scene_class):
            raise ValueError("labels must be derived directly from scene_class")
        if "NORMAL_SCENE" in self.labels and len(self.labels) != 1:
            raise ValueError("NORMAL_SCENE must remain exclusive")
        if set(self.labels) - set(IMAGE_LABELS):
            raise ValueError("unknown image target label")
        return self


class SyntheticImageModelRecord(SyntheticImageModel):
    """Only fields made available to the dataset loader used by the CNN."""

    image_id: str
    image_path: str
    labels: list[str]
    split: Literal["train", "validation", "test"]
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SyntheticImageQualityReport(SyntheticImageModel):
    schema_version: Literal["1.0"] = "1.0"
    valid: bool
    generator_version: str
    dataset_id: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_sha256: dict[str, str]
    annotation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_count: int = Field(ge=0)
    split_counts: dict[str, int]
    label_counts: dict[str, int]
    split_label_counts: dict[str, dict[str, int]]
    scene_class_counts: dict[str, int]
    hard_negative_counts: dict[str, int]
    leakage_checks: dict[str, Any]
    holdout_checks: dict[str, Any]
    image_integrity: dict[str, Any]
    hidden_metadata_isolation: dict[str, Any]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    production_validation: Literal["NOT_VALIDATED"] = "NOT_VALIDATED"


class SyntheticImageArtifacts(SyntheticImageModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    output_directory: Path
    annotation_path: Path
    model_input_paths: dict[str, Path]
    ground_truth_paths: dict[str, Path]
    manifest_path: Path
    quality_report_path: Path
    dataset_hash: str
    split_hashes: dict[str, str]
    annotation_hash: str
    manifest_hash: str
    quality_report_hash: str
    report: SyntheticImageQualityReport


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _rng(seed: int, *parts: Any) -> np.random.Generator:
    payload = "|".join([str(seed), *(str(part) for part in parts)]).encode("utf-8")
    derived = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return np.random.default_rng(derived)


def _clamp_color(values: np.ndarray | tuple[float, ...]) -> tuple[int, int, int]:
    array = np.clip(np.asarray(values, dtype=np.float32), 0, 255)
    return tuple(int(round(item)) for item in array[:3])


def _scene_parameters(
    config: SyntheticImageGeneratorConfig,
    split: str,
    ordinal: int,
) -> dict[str, Any]:
    random = _rng(config.seed, split, ordinal, "scene")
    # Exact cycling gives every split reproducible class coverage.  All visual
    # parameters remain independently randomized, so this is not a pixel cue.
    scene_class = SCENE_CLASSES[ordinal % len(SCENE_CLASSES)]
    labels = list(SCENE_CLASS_LABELS[scene_class])
    scene_families = SPLIT_SCENE_FAMILIES[split]
    backgrounds = SPLIT_BACKGROUND_FAMILIES[split]
    parameter_families = SPLIT_PARAMETER_FAMILIES[split]
    scene_family = scene_families[(ordinal * 5 + 1) % len(scene_families)]
    background_family = backgrounds[(ordinal * 3 + 2) % len(backgrounds)]
    parameter_family = parameter_families[(ordinal * 7 + 1) % len(parameter_families)]
    camera_view = CAMERA_VIEWS[(ordinal * 3 + int(random.integers(0, 5))) % 5]
    lighting = LIGHTING_VALUES[(ordinal * 5 + int(random.integers(0, 4))) % 4]
    if scene_class == "NORMAL_DARK":
        lighting = "LOW_LIGHT"

    flooded = "FLOODED_SCENE" in labels
    standing = "STANDING_WATER" in labels
    heavy_rain = "HEAVY_RAIN_VISUAL" in labels
    damaged = "STORM_DAMAGE" in labels
    water_level = (
        float(random.uniform(0.66, 0.98))
        if flooded
        else float(random.uniform(0.22, 0.46))
        if standing
        else 0.0
    )
    rain_intensity = (
        float(random.uniform(0.67, 1.0))
        if heavy_rain
        else float(random.uniform(0.0, 0.14))
    )
    damage_level = float(random.uniform(0.62, 1.0)) if damaged else 0.0
    surface_wet = scene_class == "NORMAL_WET_SURFACE" or heavy_rain or flooded or standing
    weather_context = (
        "ACTIVE_SEVERE_RAIN"
        if heavy_rain
        else "POST_STORM"
        if damaged
        else "POST_RAIN_ACCUMULATION"
        if flooded or standing
        else "RECENT_RAIN_WET_SURFACE"
        if surface_wet
        else "DRY_STABLE_WEATHER"
    )
    template_variant = (ordinal // len(SCENE_CLASSES)) % 7
    template_id = f"{split}:{scene_family}:layout-{template_variant}"
    parameter_payload = {
        "split": split,
        "family": parameter_family,
        "scene_class": scene_class,
        "camera": camera_view,
        "lighting": lighting,
        "water_bin": round(water_level, 1),
        "rain_bin": round(rain_intensity, 1),
        "damage_bin": round(damage_level, 1),
    }
    parameter_combination_id = f"{split}:{_payload_sha256(parameter_payload)[:20]}"
    scenario_id = f"synimg-{split}-{ordinal:06d}-{_payload_sha256(parameter_payload | {'ordinal': ordinal})[:10]}"
    return {
        "scenario_id": scenario_id,
        "image_id": scenario_id,
        "scene_class": scene_class,
        "labels": labels,
        "water_level": water_level,
        "rain_intensity": rain_intensity,
        "damage_level": damage_level,
        "lighting": lighting,
        "camera_view": camera_view,
        "background_family": background_family,
        "weather_context": weather_context,
        "scene_family": scene_family,
        "template_id": template_id,
        "parameter_family": parameter_family,
        "parameter_combination_id": parameter_combination_id,
        "hard_negative_category": (
            scene_class if scene_class in HARD_NEGATIVE_SCENES else None
        ),
        "surface_wet": surface_wet,
    }


def _base_palette(random: np.random.Generator, background_family: str) -> dict[str, tuple[int, int, int]]:
    family_seed = int.from_bytes(hashlib.sha256(background_family.encode()).digest()[:2], "big")
    base_hue = family_seed % 90
    jitter = random.integers(-24, 25, size=3)
    sky = _clamp_color(np.array((110 + base_hue, 145 + base_hue // 3, 175)) + jitter)
    ground = _clamp_color(np.array((82, 78 + base_hue // 5, 72)) + jitter / 2)
    road = _clamp_color(np.array((67, 69, 72)) + jitter / 3)
    building = _clamp_color(np.array((135 + base_hue // 4, 120, 105)) + jitter)
    vegetation = _clamp_color(np.array((58, 105 + base_hue // 6, 62)) + jitter / 2)
    return {
        "sky": sky,
        "ground": ground,
        "road": road,
        "building": building,
        "vegetation": vegetation,
    }


def _draw_scene(
    width: int,
    height: int,
    parameters: dict[str, Any],
    random: np.random.Generator,
) -> Image.Image:
    scale = 1.25
    canvas_width = max(width + 8, round(width * scale))
    canvas_height = max(height + 8, round(height * scale))
    palette = _base_palette(random, parameters["background_family"])
    sky = np.empty((canvas_height, canvas_width, 3), dtype=np.uint8)
    horizon = int(canvas_height * random.uniform(0.37, 0.53))
    for y in range(canvas_height):
        if y < horizon:
            factor = y / max(horizon, 1)
            sky[y, :, :] = _clamp_color(
                np.asarray(palette["sky"]) * (0.78 + 0.24 * factor)
            )
        else:
            sky[y, :, :] = palette["ground"]
    image = Image.fromarray(sky, mode="RGB")
    draw = ImageDraw.Draw(image, "RGBA")

    camera = parameters["camera_view"]
    vanishing_shift = {
        "OBLIQUE_LEFT": -0.18,
        "OBLIQUE_RIGHT": 0.18,
        "STREET_LOW": 0.04,
        "ELEVATED": -0.03,
        "EYE_LEVEL": 0.0,
    }[camera]
    vanishing_x = int(canvas_width * (0.5 + vanishing_shift))
    road_top_half = int(canvas_width * random.uniform(0.07, 0.15))
    road_bottom_margin = int(canvas_width * random.uniform(0.02, 0.12))
    road = [
        (vanishing_x - road_top_half, horizon),
        (vanishing_x + road_top_half, horizon),
        (canvas_width - road_bottom_margin, canvas_height),
        (road_bottom_margin, canvas_height),
    ]
    draw.polygon(road, fill=(*palette["road"], 255))

    building_count = int(random.integers(4, 9))
    for index in range(building_count):
        side = -1 if index % 2 == 0 else 1
        depth = (index // 2 + 1) / (building_count // 2 + 2)
        building_width = int(canvas_width * random.uniform(0.10, 0.23) * (0.55 + depth))
        building_height = int(canvas_height * random.uniform(0.16, 0.43) * (0.55 + depth))
        edge_x = int(
            vanishing_x
            + side * canvas_width * (0.13 + depth * random.uniform(0.28, 0.46))
        )
        left = edge_x - building_width if side < 0 else edge_x
        top = max(1, horizon - building_height)
        color = _clamp_color(
            np.asarray(palette["building"]) + random.integers(-34, 35, size=3)
        )
        draw.rectangle((left, top, left + building_width, horizon + 2), fill=(*color, 255))
        window_color = _clamp_color(np.asarray(palette["sky"]) * random.uniform(0.45, 0.9))
        for row in range(2):
            for column in range(2):
                wx = left + 3 + column * max(4, building_width // 2)
                wy = top + 4 + row * max(4, building_height // 3)
                if wx + 2 < left + building_width and wy + 2 < horizon:
                    draw.rectangle((wx, wy, wx + 2, wy + 2), fill=(*window_color, 190))

    tree_count = int(random.integers(2, 7))
    for _ in range(tree_count):
        x = int(random.choice([random.uniform(1, canvas_width * 0.3), random.uniform(canvas_width * 0.7, canvas_width - 1)]))
        y = int(random.uniform(horizon - 2, canvas_height * 0.82))
        radius = int(random.uniform(2, 6))
        draw.line((x, y, x, y + radius * 2), fill=(75, 55, 40, 255), width=max(1, radius // 2))
        vegetation = _clamp_color(
            np.asarray(palette["vegetation"]) + random.integers(-25, 26, size=3)
        )
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*vegetation, 230))

    if parameters["surface_wet"]:
        for _ in range(int(random.integers(4, 10))):
            y = int(random.uniform(horizon + 2, canvas_height - 2))
            x = int(random.uniform(3, canvas_width - 3))
            length = int(random.uniform(3, 14))
            sheen = _clamp_color(np.asarray(palette["sky"]) * random.uniform(0.55, 0.9))
            draw.line((x, y, min(canvas_width - 1, x + length), y), fill=(*sheen, 75), width=1)

    labels = set(parameters["labels"])
    water_colors = (
        (58, 92, 108),
        (92, 88, 69),
        (72, 98, 112),
        (105, 91, 67),
        (69, 83, 94),
    )
    water_color = _clamp_color(
        np.asarray(water_colors[int(random.integers(0, len(water_colors)))])
        + random.integers(-18, 19, size=3)
    )
    if "FLOODED_SCENE" in labels:
        top = int(
            canvas_height
            * (0.76 - 0.26 * float(parameters["water_level"]) + random.uniform(-0.03, 0.03))
        )
        water_polygon = [
            (0, max(horizon + 1, top + int(random.integers(-3, 4)))),
            (canvas_width, max(horizon + 1, top + int(random.integers(-3, 4)))),
            (canvas_width, canvas_height),
            (0, canvas_height),
        ]
        draw.polygon(water_polygon, fill=(*water_color, int(random.integers(165, 226))))
        for _ in range(int(random.integers(8, 18))):
            y = int(random.uniform(max(horizon + 2, top), canvas_height - 1))
            x = int(random.uniform(0, canvas_width - 4))
            length = int(random.uniform(3, 18))
            draw.line((x, y, min(canvas_width - 1, x + length), y), fill=(220, 230, 225, 85), width=1)
    if "STANDING_WATER" in labels:
        puddles = int(random.integers(3, 8))
        for _ in range(puddles):
            cx = int(random.uniform(canvas_width * 0.15, canvas_width * 0.85))
            cy = int(random.uniform(horizon + 5, canvas_height - 4))
            rx = int(random.uniform(7, 20))
            ry = max(2, int(rx * random.uniform(0.25, 0.50)))
            draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(*water_color, int(random.integers(135, 211))))
            draw.arc((cx - rx, cy - ry, cx + rx, cy + ry), 185, 350, fill=(225, 235, 235, 120), width=1)
            if rx >= 10:
                draw.line(
                    (cx - rx // 2, cy, cx + rx // 2, cy),
                    fill=(225, 235, 235, 90),
                    width=1,
                )

    if "STORM_DAMAGE" in labels:
        damage = float(parameters["damage_level"])
        trunk_color = _clamp_color(
            np.asarray((82, 58, 38)) + random.integers(-20, 21, size=3)
        )
        for trunk_index in range(int(random.integers(2, 4))):
            trunk_y = int(canvas_height * random.uniform(0.58, 0.87))
            trunk_start = int(canvas_width * random.uniform(0.03, 0.32))
            trunk_end = int(canvas_width * random.uniform(0.62, 0.98))
            end_y = trunk_y + int(random.uniform(-15, 10))
            draw.line(
                (trunk_start, trunk_y, trunk_end, end_y),
                fill=(*trunk_color, 255),
                width=max(2, int(2 + damage * 4)),
            )
            branch_x = int((trunk_start + trunk_end) / 2)
            branch_y = int((trunk_y + end_y) / 2)
            branch_direction = -1 if trunk_index % 2 else 1
            draw.line(
                (
                    branch_x,
                    branch_y,
                    branch_x + branch_direction * int(random.uniform(7, 17)),
                    branch_y - int(random.uniform(5, 14)),
                ),
                fill=(*trunk_color, 240),
                width=max(1, int(1 + damage * 2)),
            )
        for _ in range(int(7 + damage * 11)):
            x = int(random.uniform(canvas_width * 0.12, canvas_width * 0.9))
            y = int(random.uniform(horizon + 2, canvas_height - 2))
            size = int(random.uniform(2, 7))
            debris = _clamp_color(np.asarray(palette["building"]) + random.integers(-45, 46, size=3))
            draw.polygon(
                ((x, y), (x + size, y + int(random.integers(-2, 3))), (x + int(random.integers(-2, 3)), y + size)),
                fill=(*debris, 235),
            )
        pole_x = int(random.uniform(canvas_width * 0.15, canvas_width * 0.85))
        draw.line((pole_x, horizon - 12, pole_x + 9, canvas_height - 5), fill=(47, 47, 43, 255), width=2)
        # An irregular collapsed-roof silhouette varies in position and color;
        # it is semantic damage evidence rather than a fixed class marker.
        roof_x = int(random.uniform(canvas_width * 0.06, canvas_width * 0.70))
        roof_y = int(random.uniform(max(4, horizon - 20), max(5, horizon - 8)))
        roof_width = int(random.uniform(13, 26))
        roof_color = _clamp_color(
            np.asarray(palette["building"]) + random.integers(-35, 36, size=3)
        )
        draw.polygon(
            (
                (roof_x, roof_y + 8),
                (roof_x + roof_width // 3, roof_y),
                (roof_x + roof_width // 2, roof_y + 7),
                (roof_x + roof_width * 2 // 3, roof_y + 2),
                (roof_x + roof_width, roof_y + 9),
            ),
            fill=(*roof_color, 245),
        )

    rain_streak_count = 0
    if "HEAVY_RAIN_VISUAL" in labels:
        rain_streak_count = int(55 + 125 * float(parameters["rain_intensity"]))
        rain = Image.new("RGBA", image.size, (0, 0, 0, 0))
        rain_draw = ImageDraw.Draw(rain, "RGBA")
        for _ in range(rain_streak_count):
            x = int(random.uniform(-6, canvas_width + 6))
            y = int(random.uniform(-8, canvas_height + 4))
            length = int(random.uniform(4, 12))
            slant = int(random.uniform(-3, 4))
            rain_draw.line(
                (x, y, x + slant, y + length),
                fill=(215, 228, 235, int(random.integers(95, 191))),
                width=1,
            )
        haze = Image.new("RGBA", image.size, (185, 195, 202, int(random.integers(28, 71))))
        image = Image.alpha_composite(image.convert("RGBA"), haze)
        image = Image.alpha_composite(image, rain).convert("RGB")

    parameters["rain_streak_count"] = rain_streak_count
    return image


def _domain_randomize(
    image: Image.Image,
    parameters: dict[str, Any],
    random: np.random.Generator,
    *,
    width: int,
    height: int,
) -> tuple[Image.Image, DomainRandomization]:
    brightness = float(random.uniform(0.68, 1.34))
    contrast = float(random.uniform(0.72, 1.32))
    if parameters["lighting"] == "LOW_LIGHT":
        brightness *= float(random.uniform(0.43, 0.68))
    elif parameters["lighting"] == "TWILIGHT":
        brightness *= float(random.uniform(0.68, 0.86))
    elif parameters["lighting"] == "OVERCAST":
        contrast *= float(random.uniform(0.72, 0.92))
    image = ImageEnhance.Brightness(image).enhance(brightness)
    image = ImageEnhance.Contrast(image).enhance(contrast)

    crop_scale = float(random.uniform(0.86, 1.0))
    crop_width = max(width, int(image.width * crop_scale))
    crop_height = max(height, int(image.height * crop_scale))
    max_left = max(0, image.width - crop_width)
    max_top = max(0, image.height - crop_height)
    left = int(random.integers(0, max_left + 1)) if max_left else 0
    top = int(random.integers(0, max_top + 1)) if max_top else 0
    image = image.crop((left, top, left + crop_width, top + crop_height)).resize(
        (width, height), Image.Resampling.BILINEAR
    )

    horizontal_flip = bool(random.integers(0, 2))
    if horizontal_flip:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    blur_radius = float(random.choice((0.0, 0.0, 0.25, 0.5, 0.8, 1.1)))
    if blur_radius:
        image = image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    sensor_noise_std = float(random.choice((0.0, 1.5, 3.0, 5.0, 7.5)))
    if sensor_noise_std:
        values = np.asarray(image, dtype=np.float32)
        noise = random.normal(0.0, sensor_noise_std, size=values.shape)
        image = Image.fromarray(np.clip(values + noise, 0, 255).astype(np.uint8), "RGB")

    compression_applied = bool(random.random() < 0.45)
    jpeg_quality = int(random.integers(45, 96))
    if compression_applied:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=False)
        buffer.seek(0)
        with Image.open(buffer) as compressed:
            image = compressed.convert("RGB").copy()

    occlusion_fraction = float(random.uniform(0.0, 0.10))
    if occlusion_fraction > 0.025:
        draw = ImageDraw.Draw(image, "RGBA")
        area = width * height * occlusion_fraction
        object_width = max(2, int(np.sqrt(area) * random.uniform(0.7, 1.4)))
        object_height = max(2, int(area / object_width))
        object_width = min(object_width, width // 2)
        object_height = min(object_height, height // 2)
        x = int(random.integers(0, max(1, width - object_width + 1)))
        y = int(random.integers(0, max(1, height - object_height + 1)))
        color = tuple(int(item) for item in random.integers(20, 220, size=3))
        if random.random() < 0.5:
            draw.ellipse((x, y, x + object_width, y + object_height), fill=(*color, 165))
        else:
            draw.rectangle((x, y, x + object_width, y + object_height), fill=(*color, 165))

    domain = DomainRandomization(
        brightness=round(brightness, 6),
        contrast=round(contrast, 6),
        blur_radius=blur_radius,
        sensor_noise_std=sensor_noise_std,
        jpeg_quality=jpeg_quality,
        compression_applied=compression_applied,
        rain_streak_count=int(parameters.get("rain_streak_count", 0)),
        occlusion_fraction=round(occlusion_fraction, 6),
        crop_scale=round(crop_scale, 6),
        horizontal_flip=horizontal_flip,
    )
    return image, domain


def generate_synthetic_scene(
    config: SyntheticImageGeneratorConfig,
    *,
    split: Literal["train", "validation", "test"],
    ordinal: int,
) -> tuple[bytes, SyntheticImageGroundTruth, SyntheticImageModelRecord, dict[str, Any]]:
    """Generate one PNG and its separated hidden/model annotation views."""

    if split not in SPLITS:
        raise ValueError(f"unsupported split: {split}")
    if ordinal < 0:
        raise ValueError("ordinal cannot be negative")
    parameters = _scene_parameters(config, split, ordinal)
    random = _rng(config.seed, split, ordinal, "pixels")
    image = _draw_scene(config.image_width, config.image_height, parameters, random)
    image, domain = _domain_randomize(
        image,
        parameters,
        random,
        width=config.image_width,
        height=config.image_height,
    )
    parameters.pop("rain_streak_count", None)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=config.png_compress_level)
    payload = buffer.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    # Basenames are globally unique because the common image validator also
    # indexes filename and stem in addition to the relative path.
    relative_path = f"images/{split}/{split}-{ordinal:06d}.png"
    truth = SyntheticImageGroundTruth(
        **parameters,
        image_path=relative_path,
        split=split,
        ordinal=ordinal,
        domain_randomization=domain,
        width=config.image_width,
        height=config.image_height,
        byte_sha256=digest,
    )
    model_record = SyntheticImageModelRecord(
        image_id=truth.image_id,
        image_path=relative_path,
        labels=truth.labels,
        split=split,
        byte_sha256=digest,
    )
    annotation = {
        "annotation_id": f"synthetic-generator:{truth.image_id}",
        "image_id": truth.image_id,
        "image_path": relative_path,
        "labels": truth.labels,
        "annotator_id": "PROJECT_SYNTHETIC_SCENE_GENERATOR",
        "annotation_timestamp": config.creation_timestamp.isoformat(),
        "annotator_confidence": 1.0,
        "reason": "Ground truth is derived directly from the explicit procedural scene description.",
        "notes": "SYNTHETIC / DEVELOPMENT_ONLY / NOT HUMAN ADJUDICATED",
        "uncertain": False,
        "byte_sha256": digest,
        "perceptual_similarity_hash": None,
        "width": config.image_width,
        "height": config.image_height,
        "detected_format": "PNG",
        "event_id": f"scene-family:{truth.scene_family}",
        "incident_id": f"background-family:{truth.background_family}",
        "report_id": truth.scenario_id,
        "capture_session_id": f"parameter-family:{truth.parameter_family}",
        "split": split,
        "schema_version": IMAGE_ANNOTATION_SCHEMA_VERSION,
    }
    return payload, truth, model_record, annotation


def _write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return file_sha256(path)


def _materialize_one(args: tuple[Path, SyntheticImageGeneratorConfig, str, int]):
    output, config, split, ordinal = args
    payload, truth, model_record, annotation = generate_synthetic_scene(
        config,
        split=split,  # type: ignore[arg-type]
        ordinal=ordinal,
    )
    image_path = output / model_record.image_path
    image_path.write_bytes(payload)
    return truth, model_record, annotation


def _read_jsonl(path: Path, model: type[SyntheticImageModel]) -> list[Any]:
    return [
        model.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _dataset_digest(
    config: SyntheticImageGeneratorConfig,
    split_hashes: dict[str, str],
    hidden_hashes: dict[str, str],
    annotation_hash: str,
) -> str:
    return _payload_sha256(
        {
            "generator_version": GENERATOR_VERSION,
            "config": config.model_dump(mode="json"),
            "model_split_hashes": split_hashes,
            "hidden_split_hashes": hidden_hashes,
            "annotation_hash": annotation_hash,
        }
    )


def validate_synthetic_image_dataset(
    output_directory: Path | str,
    *,
    config: SyntheticImageGeneratorConfig,
    verify_image_bytes: bool = True,
) -> SyntheticImageQualityReport:
    """Run scalable identity, label, holdout, and byte-integrity checks."""

    output = local_only_path(output_directory, description="synthetic image datasets").resolve()
    errors: list[str] = []
    warnings: list[str] = []
    model_paths = {split: output / "model_inputs" / f"{split}.jsonl" for split in SPLITS}
    truth_paths = {split: output / "hidden_generator_metadata" / f"{split}.jsonl" for split in SPLITS}
    annotation_path = output / "annotations.jsonl"
    if any(not path.is_file() for path in (*model_paths.values(), *truth_paths.values(), annotation_path)):
        raise ValueError("synthetic image dataset is incomplete")

    split_hashes = {split: file_sha256(path) for split, path in model_paths.items()}
    hidden_hashes = {split: file_sha256(path) for split, path in truth_paths.items()}
    annotation_hash = file_sha256(annotation_path)
    dataset_hash = _dataset_digest(config, split_hashes, hidden_hashes, annotation_hash)

    seen_ids: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}
    identity_leaks: list[str] = []
    byte_leaks: list[str] = []
    split_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    split_label_counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    scene_counts: Counter[str] = Counter()
    hard_counts: Counter[str] = Counter()
    scene_families: defaultdict[str, set[str]] = defaultdict(set)
    backgrounds: defaultdict[str, set[str]] = defaultdict(set)
    parameter_families: defaultdict[str, set[str]] = defaultdict(set)
    parameter_combinations: defaultdict[str, set[str]] = defaultdict(set)
    templates: defaultdict[str, set[str]] = defaultdict(set)
    actual_hash_mismatches: list[str] = []
    malformed_images: list[str] = []
    model_hidden_mismatches: list[str] = []

    for split in SPLITS:
        models = _read_jsonl(model_paths[split], SyntheticImageModelRecord)
        truths = _read_jsonl(truth_paths[split], SyntheticImageGroundTruth)
        if len(models) != len(truths):
            errors.append(f"{split} model/hidden row count mismatch")
        if len(models) != config.split_counts[split]:
            errors.append(f"{split} row count differs from frozen generator config")
        for model_record, truth in zip(models, truths):
            split_counts[split] += 1
            label_counts.update(model_record.labels)
            split_label_counts[split].update(model_record.labels)
            scene_counts[truth.scene_class] += 1
            if truth.hard_negative_category:
                hard_counts[truth.hard_negative_category] += 1
            if (
                model_record.image_id != truth.image_id
                or model_record.image_path != truth.image_path
                or model_record.labels != truth.labels
                or model_record.byte_sha256 != truth.byte_sha256
                or model_record.split != truth.split
            ):
                model_hidden_mismatches.append(truth.image_id)
            previous_split = seen_ids.setdefault(truth.image_id, split)
            if previous_split != split:
                identity_leaks.append(truth.image_id)
            previous_hash_split = seen_hashes.setdefault(truth.byte_sha256, split)
            if previous_hash_split != split:
                byte_leaks.append(truth.byte_sha256)
            scene_families[split].add(truth.scene_family)
            backgrounds[split].add(truth.background_family)
            parameter_families[split].add(truth.parameter_family)
            parameter_combinations[split].add(truth.parameter_combination_id)
            templates[split].add(truth.template_id)
            if tuple(truth.labels) != SCENE_CLASS_LABELS[truth.scene_class]:
                errors.append(f"scene-label mismatch: {truth.image_id}")
            if verify_image_bytes:
                image_path = output / truth.image_path
                if not image_path.is_file():
                    malformed_images.append(truth.image_path)
                    continue
                payload = image_path.read_bytes()
                if hashlib.sha256(payload).hexdigest() != truth.byte_sha256:
                    actual_hash_mismatches.append(truth.image_id)
                    continue
                try:
                    with Image.open(io.BytesIO(payload)) as image:
                        image.verify()
                    with Image.open(io.BytesIO(payload)) as image:
                        if image.size != (truth.width, truth.height) or image.format != "PNG":
                            malformed_images.append(truth.image_path)
                except Exception:
                    malformed_images.append(truth.image_path)

    def overlap(mapping: dict[str, set[str]]) -> list[str]:
        return sorted(
            (mapping["train"] & mapping["validation"])
            | (mapping["train"] & mapping["test"])
            | (mapping["validation"] & mapping["test"])
        )

    family_overlap = overlap(scene_families)
    background_overlap = overlap(backgrounds)
    parameter_family_overlap = overlap(parameter_families)
    parameter_overlap = overlap(parameter_combinations)
    template_overlap = overlap(templates)
    if identity_leaks:
        errors.append("image identity leakage exists across splits")
    if byte_leaks:
        errors.append("byte-hash leakage exists across splits")
    if family_overlap:
        errors.append("scene-family leakage exists across splits")
    if background_overlap:
        errors.append("background-family leakage exists across splits")
    if parameter_family_overlap or parameter_overlap:
        errors.append("parameter-family or parameter-combination leakage exists")
    if template_overlap:
        errors.append("direct template leakage exists across splits")
    if model_hidden_mismatches:
        errors.append("model records do not match hidden generator truth")
    if actual_hash_mismatches:
        errors.append("stored image bytes do not match recorded hashes")
    if malformed_images:
        errors.append("missing, malformed, or dimension-mismatched images exist")
    if set(label_counts) != set(IMAGE_LABELS):
        errors.append("one or more target labels are absent")
    if set(scene_counts) != set(SCENE_CLASSES):
        errors.append("one or more scene classes are absent")
    if set(hard_counts) != set(HARD_NEGATIVE_SCENES):
        errors.append("one or more hard-negative categories are absent")

    return SyntheticImageQualityReport(
        valid=not errors,
        generator_version=GENERATOR_VERSION,
        dataset_id=config.dataset_id,
        dataset_version=config.dataset_version,
        dataset_sha256=dataset_hash,
        split_sha256=split_hashes,
        annotation_sha256=annotation_hash,
        image_count=sum(split_counts.values()),
        split_counts=dict(sorted(split_counts.items())),
        label_counts=dict(sorted(label_counts.items())),
        split_label_counts={
            split: dict(sorted(split_label_counts[split].items())) for split in SPLITS
        },
        scene_class_counts=dict(sorted(scene_counts.items())),
        hard_negative_counts=dict(sorted(hard_counts.items())),
        leakage_checks={
            "status": "PASS" if not any((identity_leaks, byte_leaks, family_overlap, background_overlap, parameter_family_overlap, parameter_overlap, template_overlap)) else "FAIL",
            "exact_image_identity_cross_split": len(identity_leaks),
            "byte_hash_cross_split": len(byte_leaks),
            "scene_family_cross_split": len(family_overlap),
            "background_family_cross_split": len(background_overlap),
            "parameter_family_cross_split": len(parameter_family_overlap),
            "parameter_combination_cross_split": len(parameter_overlap),
            "direct_template_cross_split": len(template_overlap),
            "grouped_split": True,
            "random_image_split": False,
            "method": "EXACT_HASH_AND_EXPLICIT_GENERATOR_IDENTITY_SETS",
        },
        holdout_checks={
            "test_scene_families_held_out": not bool(scene_families["test"] & (scene_families["train"] | scene_families["validation"])),
            "test_backgrounds_held_out": not bool(backgrounds["test"] & (backgrounds["train"] | backgrounds["validation"])),
            "test_parameter_families_held_out": not bool(parameter_families["test"] & (parameter_families["train"] | parameter_families["validation"])),
            "test_parameter_combinations_held_out": not bool(parameter_combinations["test"] & (parameter_combinations["train"] | parameter_combinations["validation"])),
        },
        image_integrity={
            "verification_performed": verify_image_bytes,
            "hash_mismatches": len(actual_hash_mismatches),
            "malformed_or_missing": len(malformed_images),
            "unique_byte_hashes": len(seen_hashes),
        },
        hidden_metadata_isolation={
            "physically_separate": True,
            "model_record_fields": list(SyntheticImageModelRecord.model_fields),
            "hidden_fields_not_in_model_record": sorted(
                set(SyntheticImageGroundTruth.model_fields)
                - set(SyntheticImageModelRecord.model_fields)
            ),
            "mismatched_rows": len(model_hidden_mismatches),
            "cnn_receives_hidden_metadata": False,
        },
        errors=sorted(set(errors)),
        warnings=warnings,
    )


def write_synthetic_image_dataset(
    output_directory: Path | str,
    *,
    config: SyntheticImageGeneratorConfig | None = None,
    overwrite: bool = False,
) -> SyntheticImageArtifacts:
    """Materialize deterministic PNGs plus isolated model/hidden records."""

    config = config or SyntheticImageGeneratorConfig()
    output = local_only_path(output_directory, description="synthetic image datasets").resolve()
    if output.exists() and any(output.iterdir()):
        if not overwrite:
            raise FileExistsError(f"synthetic image output is not empty: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
    (output / "model_inputs").mkdir(parents=True, exist_ok=True)
    (output / "hidden_generator_metadata").mkdir(parents=True, exist_ok=True)

    annotation_path = output / "annotations.jsonl"
    model_paths = {split: output / "model_inputs" / f"{split}.jsonl" for split in SPLITS}
    truth_paths = {split: output / "hidden_generator_metadata" / f"{split}.jsonl" for split in SPLITS}
    with annotation_path.open("w", encoding="utf-8", newline="\n") as annotation_handle:
        for split in SPLITS:
            with (
                model_paths[split].open("w", encoding="utf-8", newline="\n") as model_handle,
                truth_paths[split].open("w", encoding="utf-8", newline="\n") as truth_handle,
                ThreadPoolExecutor(max_workers=config.generator_workers) as executor,
            ):
                count = config.split_counts[split]
                for start in range(0, count, 512):
                    stop = min(count, start + 512)
                    arguments = ((output, config, split, ordinal) for ordinal in range(start, stop))
                    for truth, model_record, annotation in executor.map(_materialize_one, arguments):
                        truth_handle.write(truth.model_dump_json() + "\n")
                        model_handle.write(model_record.model_dump_json() + "\n")
                        annotation_handle.write(
                            json.dumps(annotation, ensure_ascii=False, separators=(",", ":")) + "\n"
                        )

    report = validate_synthetic_image_dataset(output, config=config, verify_image_bytes=True)
    if not report.valid:
        raise ValueError("generated synthetic image dataset failed validation: " + "; ".join(report.errors))
    quality_path = output / "quality_report.json"
    quality_hash = _write_json(quality_path, report.model_dump(mode="json"))
    manifest = {
        "schema_version": "1.0",
        "dataset_id": config.dataset_id,
        "dataset_version": config.dataset_version,
        "classification": "DEVELOPMENT_ONLY",
        "data_origin": "PROJECT_AUTHORED_SYNTHETIC",
        "generator_version": GENERATOR_VERSION,
        "seed": config.seed,
        "creation_timestamp": config.creation_timestamp.isoformat(),
        "image_count": report.image_count,
        "split_counts": report.split_counts,
        "label_distribution": report.label_counts,
        "split_label_distribution": report.split_label_counts,
        "dataset_sha256": report.dataset_sha256,
        "split_sha256": report.split_sha256,
        "annotation_sha256": report.annotation_sha256,
        "quality_report_sha256": quality_hash,
        "image_shape": [config.image_height, config.image_width, 3],
        "image_format": "PNG",
        "taxonomy": list(IMAGE_LABELS),
        "task_type": "MULTI_LABEL",
        "normal_scene_exclusive": True,
        "ground_truth_source": "EXPLICIT_PROCEDURAL_SCENE_DESCRIPTION",
        "split_strategy": "SCENE_BACKGROUND_TEMPLATE_PARAMETER_FAMILY_GROUPED",
        "holdout_test": "HELD_OUT_SCENE_FAMILIES_BACKGROUNDS_AND_PARAMETER_COMBINATIONS",
        "domain_randomization": [
            "brightness",
            "contrast",
            "blur",
            "sensor_noise",
            "local_jpeg_recompression",
            "rain_density",
            "partial_occlusion",
            "crop",
            "horizontal_flip",
        ],
        "policy": {
            "project_authored": True,
            "synthetic": True,
            "development_only": True,
            "production_validation": "NOT_VALIDATED",
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "cnn_receives_hidden_generator_metadata": False,
            "live_backend_modified": False,
        },
    }
    manifest_path = output / "manifest.json"
    manifest_hash = _write_json(manifest_path, manifest)
    return SyntheticImageArtifacts(
        output_directory=output,
        annotation_path=annotation_path,
        model_input_paths=model_paths,
        ground_truth_paths=truth_paths,
        manifest_path=manifest_path,
        quality_report_path=quality_path,
        dataset_hash=report.dataset_sha256,
        split_hashes=report.split_sha256,
        annotation_hash=report.annotation_sha256,
        manifest_hash=manifest_hash,
        quality_report_hash=quality_hash,
        report=report,
    )


def _registry_relative(path: Path, registry_path: Path) -> str:
    return Path(os.path.relpath(path, registry_path.parent)).as_posix()


def register_synthetic_image_dataset(
    artifacts: SyntheticImageArtifacts,
    *,
    config: SyntheticImageGeneratorConfig,
    registry_path: Path | str,
    replace_existing: bool = False,
):
    """Register the directory and run the common fail-closed image validator."""

    from app.ml.data.dataset_validation import validate_registered_dataset
    from app.ml.data.registry import (
        DatasetClassification,
        DatasetComponent,
        DatasetFormat,
        DatasetProvenance,
        DatasetRegistryRecord,
        DatasetStatus,
        find_dataset,
        hash_dataset_path,
        load_dataset_registry,
        register_dataset,
    )

    selected_registry = local_only_path(registry_path, description="dataset registries").resolve()
    directory_hash = hash_dataset_path(artifacts.output_directory)
    record = DatasetRegistryRecord(
        dataset_id=config.dataset_id,
        dataset_version=config.dataset_version,
        component=DatasetComponent.IMAGE,
        local_path=_registry_relative(artifacts.output_directory, selected_registry),
        format=DatasetFormat.DIRECTORY,
        content_sha256=directory_hash.content_sha256,
        schema_version="synthetic-image-dataset-v1",
        label_schema_version=IMAGE_ANNOTATION_SCHEMA_VERSION,
        creation_timestamp=config.creation_timestamp,
        source_description=(
            "Reproducible project-authored procedural weather and infrastructure images; "
            "labels derive only from explicit hidden scene descriptions."
        ),
        provenance=DatasetProvenance.PROJECT_AUTHORED,
        license_or_usage_note=(
            "Internal synthetic development and regression use only; not field visual-performance "
            "or production-validation evidence."
        ),
        grouping_field="capture_session_id",
        split_field="split",
        label_count=sum(artifacts.report.label_counts.values()),
        row_or_image_count=artifacts.report.image_count,
        status=DatasetStatus.DISCOVERED,
        data_classification=DatasetClassification.DEVELOPMENT_ONLY,
        human_adjudicated=False,
        label_source="PROJECT_GENERATED_SYNTHETIC_SCENE_DESCRIPTION",
        metadata={
            "synthetic": True,
            "project_authored": True,
            "production_validation": "NOT_VALIDATED",
            "dataset_hash": artifacts.dataset_hash,
            "directory_hash": directory_hash.content_sha256,
            "split_hashes": artifacts.split_hashes,
            "annotation_hash": artifacts.annotation_hash,
            "generator_version": GENERATOR_VERSION,
            "seed": config.seed,
            "manifest_path": _registry_relative(artifacts.manifest_path, selected_registry),
            "manifest_sha256": artifacts.manifest_hash,
            "quality_report_path": _registry_relative(artifacts.quality_report_path, selected_registry),
            "quality_report_sha256": artifacts.quality_report_hash,
            "hidden_metadata_isolated": True,
            "pretrained_models": [],
            "open_weight_models": [],
            "external_apis": [],
            "network_access": False,
            "live_backend_modified": False,
        },
    )
    register_dataset(
        record,
        registry_path=selected_registry,
        replace_existing=replace_existing,
        modified_at=config.creation_timestamp,
    )
    validation = validate_registered_dataset(
        config.dataset_id,
        registry_path=selected_registry,
        dataset_version=config.dataset_version,
        generated_at=config.creation_timestamp,
    )
    if not validation.valid:
        raise ValueError(
            "registered synthetic image dataset failed structural validation: "
            + "; ".join(validation.errors[:20])
        )
    return find_dataset(
        load_dataset_registry(selected_registry),
        config.dataset_id,
        config.dataset_version,
    )


__all__ = [
    "DEFAULT_CREATION_TIMESTAMP",
    "DEFAULT_DATASET_ID",
    "DEFAULT_DATASET_VERSION",
    "DEFAULT_SEED",
    "GENERATOR_VERSION",
    "HARD_NEGATIVE_SCENES",
    "IMAGE_LABELS",
    "SCENE_CLASS_LABELS",
    "SCENE_CLASSES",
    "SPLITS",
    "SyntheticImageArtifacts",
    "SyntheticImageGeneratorConfig",
    "SyntheticImageGroundTruth",
    "SyntheticImageModelRecord",
    "SyntheticImageQualityReport",
    "generate_synthetic_scene",
    "register_synthetic_image_dataset",
    "validate_synthetic_image_dataset",
    "write_synthetic_image_dataset",
]
