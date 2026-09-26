"""Local image validation, hashing, and deterministic preprocessing."""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from time import perf_counter

import numpy as np
from PIL import Image, UnidentifiedImageError

from app.ml.config import DEFAULT_IMAGE_ANALYSIS_CONFIG, ImageAnalysisConfig
from app.ml.contracts import ImageInput, ImageValidationError, ImageValidationResult

FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png"}


def byte_sha256(payload: bytes) -> str:
    """BYTE_HASH: exact identity of the original encoded bytes."""

    return hashlib.sha256(payload).hexdigest()


def perceptual_similarity_hash(payload: bytes, *, hash_size: int = 8) -> str:
    """PERCEPTUAL_SIMILARITY_HASH: deterministic average hash, not a model."""

    if hash_size <= 0:
        raise ValueError("hash_size must be positive")
    with Image.open(io.BytesIO(payload)) as image:
        grayscale = image.convert("L").resize(
            (hash_size, hash_size),
            resample=Image.Resampling.BILINEAR,
        )
        values = np.asarray(grayscale, dtype=np.float32)
    bits = values >= float(values.mean())
    bit_string = "".join("1" if value else "0" for value in bits.flat)
    width = (len(bit_string) + 3) // 4
    return f"{int(bit_string, 2):0{width}x}"


def perceptual_hash_hamming_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        raise ValueError("perceptual hashes must have equal length")
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _validation_error(
    code: str,
    message: str,
    **details,
) -> ImageValidationError:
    return ImageValidationError(code=code, message=message, details=details)


def validate_image_input(
    value: ImageInput,
    *,
    config: ImageAnalysisConfig | None = None,
) -> ImageValidationResult:
    """Verify encoded content rather than trusting extension or caller metadata."""

    config = config or DEFAULT_IMAGE_ANALYSIS_CONFIG
    errors: list[ImageValidationError] = []
    validation_warnings: list[ImageValidationError] = []
    payload = value.image_bytes
    digest = byte_sha256(payload)
    if not payload:
        errors.append(_validation_error("ZERO_BYTE_IMAGE", "Image payload is empty."))
    if value.file_size != len(payload):
        errors.append(
            _validation_error(
                "FILE_SIZE_MISMATCH",
                "Declared file size does not match loaded byte count.",
                declared=value.file_size,
                actual=len(payload),
            )
        )
    if len(payload) > config.max_file_size_bytes:
        errors.append(
            _validation_error(
                "FILE_SIZE_EXCEEDED",
                "Image exceeds configured byte limit.",
                actual=len(payload),
                maximum=config.max_file_size_bytes,
            )
        )
    if value.mime_type not in config.supported_mime_types:
        errors.append(
            _validation_error(
                "UNSUPPORTED_MIME_TYPE",
                "Declared MIME type is not supported.",
                mime_type=value.mime_type,
            )
        )
    if value.checksum is not None and digest is not None and value.checksum.casefold() != digest:
        errors.append(
            _validation_error(
                "CHECKSUM_MISMATCH",
                "Declared checksum does not match BYTE_HASH.",
            )
        )

    detected_format = None
    detected_mime = None
    detected_width = None
    detected_height = None
    detected_mode = None
    full_decode_rejected = len(payload) > config.max_file_size_bytes
    if payload:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(payload)) as header_image:
                    detected_format = header_image.format
                    detected_width, detected_height = header_image.size
                    detected_mode = header_image.mode
                    if detected_width <= 0 or detected_height <= 0:
                        errors.append(
                            _validation_error(
                                "INVALID_DIMENSIONS", "Decoded dimensions must be positive."
                            )
                        )
                        full_decode_rejected = True
                    if (
                        detected_width > config.max_width
                        or detected_height > config.max_height
                    ):
                        errors.append(
                            _validation_error(
                                "DIMENSION_LIMIT_EXCEEDED",
                                "Decoded dimensions exceed configured limits.",
                                width=detected_width,
                                height=detected_height,
                            )
                        )
                        full_decode_rejected = True
                    if detected_width * detected_height > config.max_pixels:
                        errors.append(
                            _validation_error(
                                "PIXEL_LIMIT_EXCEEDED",
                                "Decoded pixel count exceeds configured limit.",
                                pixels=detected_width * detected_height,
                            )
                        )
                        full_decode_rejected = True
                    header_image.verify()
                # Never allocate a full pixel buffer after the header has
                # already exceeded configured safety limits.
                if not full_decode_rejected:
                    with Image.open(io.BytesIO(payload)) as decoded_image:
                        decoded_image.load()
                        detected_width, detected_height = decoded_image.size
                        detected_mode = decoded_image.mode
            detected_mime = FORMAT_TO_MIME.get(detected_format or "")
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            errors.append(
                _validation_error(
                    "DIMENSION_LIMIT_EXCEEDED",
                    "Image dimensions exceed Pillow's safe local decode limit.",
                )
            )
        except UnidentifiedImageError:
            errors.append(
                _validation_error(
                    "MALFORMED_IMAGE_HEADER",
                    "Image content does not contain a recognized local image header.",
                )
            )
        except (OSError, SyntaxError, ValueError) as error:
            errors.append(
                _validation_error(
                    "CORRUPTED_IMAGE",
                    "Image content could not be decoded completely.",
                    error_type=type(error).__name__,
                )
            )

    if detected_format is not None:
        if detected_format not in config.supported_formats:
            errors.append(
                _validation_error(
                    "UNSUPPORTED_IMAGE_FORMAT",
                    "Decoded image format is not supported.",
                    detected_format=detected_format,
                )
            )
        if detected_mime is None or detected_mime != value.mime_type:
            errors.append(
                _validation_error(
                    "MIME_CONTENT_MISMATCH",
                    "Declared MIME type does not match decoded image content.",
                    declared=value.mime_type,
                    detected=detected_mime,
                )
            )
        if detected_mode not in config.supported_color_modes:
            errors.append(
                _validation_error(
                    "UNSUPPORTED_COLOR_MODE",
                    "Decoded color mode is not supported by preprocessing.",
                    detected_mode=detected_mode,
                )
            )
        if detected_width is not None and detected_height is not None:
            if value.width is not None and value.width != detected_width:
                errors.append(
                    _validation_error(
                        "WIDTH_MISMATCH",
                        "Declared width does not match decoded width.",
                        declared=value.width,
                        detected=detected_width,
                    )
                )
            if value.height is not None and value.height != detected_height:
                errors.append(
                    _validation_error(
                        "HEIGHT_MISMATCH",
                        "Declared height does not match decoded height.",
                        declared=value.height,
                        detected=detected_height,
                    )
                )
            if value.width is None or value.height is None:
                validation_warnings.append(
                    ImageValidationError(
                        code="DECLARED_DIMENSIONS_UNAVAILABLE",
                        message="Caller did not supply both declared dimensions; decoded values were used.",
                        severity="WARNING",
                    )
                )
    return ImageValidationResult(
        image_id=value.image_id,
        valid=not errors,
        byte_sha256=digest,
        detected_mime_type=detected_mime,
        detected_format=detected_format,
        detected_width=detected_width,
        detected_height=detected_height,
        detected_color_mode=detected_mode,
        errors=errors,
        warnings=validation_warnings,
    )


class ImageValidationException(ValueError):
    def __init__(self, result: ImageValidationResult) -> None:
        self.result = result
        super().__init__("image validation failed: " + ", ".join(item.code for item in result.errors))


@dataclass(frozen=True)
class PreprocessedImage:
    image_id: str
    pixel_values: np.ndarray
    source_file_size_bytes: int
    original_width: int
    original_height: int
    target_width: int
    target_height: int
    preprocessing_version: str
    color_space: str
    channel_order: str
    alpha_handling: str
    normalization: str
    aspect_ratio_policy: str
    interpolation: str
    preprocessing_seconds: float


def preprocess_image(
    value: ImageInput,
    *,
    config: ImageAnalysisConfig | None = None,
) -> PreprocessedImage:
    """Return deterministic CHW float32 RGB values in [0, 1]."""

    config = config or DEFAULT_IMAGE_ANALYSIS_CONFIG
    validation = validate_image_input(value, config=config)
    if not validation.valid:
        raise ImageValidationException(validation)
    started = perf_counter()
    with Image.open(io.BytesIO(value.image_bytes)) as source:
        original_width, original_height = source.size
        if source.mode == "RGBA":
            background = Image.new("RGB", source.size, config.alpha_background_rgb)
            background.paste(source, mask=source.getchannel("A"))
            image = background
        else:
            image = source.convert("RGB")
        scale = min(
            config.target_width / image.width,
            config.target_height / image.height,
        )
        resized_width = max(1, round(image.width * scale))
        resized_height = max(1, round(image.height * scale))
        resized = image.resize(
            (resized_width, resized_height),
            resample=Image.Resampling.BILINEAR,
        )
        canvas = Image.new(
            "RGB",
            (config.target_width, config.target_height),
            config.letterbox_fill_rgb,
        )
        offset = (
            (config.target_width - resized_width) // 2,
            (config.target_height - resized_height) // 2,
        )
        canvas.paste(resized, offset)
        values = np.asarray(canvas, dtype=np.float32) / np.float32(255.0)
        chw = np.ascontiguousarray(values.transpose(2, 0, 1))
    elapsed = perf_counter() - started
    return PreprocessedImage(
        image_id=value.image_id,
        pixel_values=chw,
        source_file_size_bytes=len(value.image_bytes),
        original_width=original_width,
        original_height=original_height,
        target_width=config.target_width,
        target_height=config.target_height,
        preprocessing_version=config.preprocessing_version,
        color_space=config.color_space,
        channel_order=config.channel_order,
        alpha_handling=config.alpha_handling,
        normalization=config.normalization,
        aspect_ratio_policy=config.aspect_ratio_policy,
        interpolation=config.interpolation,
        preprocessing_seconds=elapsed,
    )


__all__ = [
    "ImageValidationException",
    "PreprocessedImage",
    "byte_sha256",
    "perceptual_hash_hamming_distance",
    "perceptual_similarity_hash",
    "preprocess_image",
    "validate_image_input",
]
