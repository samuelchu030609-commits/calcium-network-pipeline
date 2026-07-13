"""Load and validate a recording's config.json.

Repo-native code — does NOT track the in-flight CASCADE/metrics rewrite, so it's
safe to rely on. See docs/DEV.md "Sync boundary".
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass

# route -> (CASCADE model family, downsample target Hz). None target = native rate.
ROUTES = {
    "cascade_gc8s": ("GC8s", 45),   # jGCaMP8s: GC8s model exists only at 45 Hz
    "cascade_gc8f": ("GC8f", 45),   # jGCaMP8f (future SS10)
    "dff": (None, None),            # Fluo-4 dye: no CASCADE model -> dF/F events
}


@dataclass
class RecordingConfig:
    indicator: str
    native_fps: float
    route: str
    neuropil_coeff: float = 0.7

    @property
    def uses_cascade(self) -> bool:
        return self.route.startswith("cascade")

    @property
    def cascade_family(self):
        return ROUTES[self.route][0]

    @property
    def cascade_target_hz(self):
        return ROUTES[self.route][1]


class ConfigError(Exception):
    """Raised with a user-facing message when config.json is missing/invalid."""


def load_config(folder: str) -> RecordingConfig:
    """Read <folder>/config.json into a validated RecordingConfig.

    `folder` is the recording folder (the one containing suite2p/ and config.json).
    Underscore-prefixed keys in the JSON are treated as comments and ignored.
    """
    path = os.path.join(folder, "config.json")
    if not os.path.isfile(path):
        raise ConfigError(
            f"No config.json in {folder}.\n"
            f"Copy config.example.json there and fill in indicator / native_fps / route."
        )

    with open(path) as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as e:
            raise ConfigError(f"config.json is not valid JSON: {e}")

    data = {k: v for k, v in raw.items() if not k.startswith("_")}

    missing = [k for k in ("indicator", "native_fps", "route") if k not in data]
    if missing:
        raise ConfigError(f"config.json is missing required keys: {', '.join(missing)}")

    if data["route"] not in ROUTES:
        raise ConfigError(
            f"Unknown route {data['route']!r}. Must be one of: {', '.join(ROUTES)}."
        )

    try:
        fps = float(data["native_fps"])
    except (TypeError, ValueError):
        raise ConfigError(f"native_fps must be a number, got {data['native_fps']!r}.")
    if fps <= 0:
        raise ConfigError(f"native_fps must be > 0, got {fps}.")

    # Soft sanity check: dye indicator should use dff, GECI should use cascade.
    ind = str(data["indicator"]).lower()
    if "fluo" in ind and data["route"] != "dff":
        raise ConfigError(
            f"Indicator {data['indicator']!r} looks like a dye but route is "
            f"{data['route']!r}; Fluo-4 has no CASCADE model. Use route 'dff'."
        )

    return RecordingConfig(
        indicator=str(data["indicator"]),
        native_fps=fps,
        route=str(data["route"]),
        neuropil_coeff=float(data.get("neuropil_coeff", 0.7)),
    )
