"""Build clean and teacher-compatible 22-muscle G-Exo models."""

from __future__ import annotations

import argparse
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_PHYSICAL_SOURCE_PATH = (
    WORKSPACE_ROOT
    / "third_party"
    / "myoassist"
    / "models"
    / "22muscle_2D"
    / "myoLeg22_2D_BASELINE.xml"
)
DEFAULT_COMPAT_SOURCE_PATH = (
    WORKSPACE_ROOT
    / "third_party"
    / "myoassist"
    / "models"
    / "22muscle_2D"
    / "myoLeg22_2D_TUTORIAL.xml"
)
DEFAULT_PHYSICAL_OUTPUT_PATH = (
    PROJECT_ROOT
    / "RL"
    / "assets"
    / "myoassist"
    / "myoLeg22_2D_GEXO.xml"
)
DEFAULT_COMPAT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "RL"
    / "assets"
    / "myoassist"
    / "myoLeg22_2D_GEXO_TEACHER_COMPAT.xml"
)

# The physical plant is the only default used by training/runtime code.
DEFAULT_SOURCE_PATH = DEFAULT_PHYSICAL_SOURCE_PATH
DEFAULT_OUTPUT_PATH = DEFAULT_PHYSICAL_OUTPUT_PATH

# Temporary aliases for route-B callers created before the variant split.
DEFAULT_CLEAN_SOURCE_PATH = DEFAULT_PHYSICAL_SOURCE_PATH
DEFAULT_CLEAN_OUTPUT_PATH = DEFAULT_PHYSICAL_OUTPUT_PATH

PHYSICAL_VARIANT = "physical"
TEACHER_COMPAT_VARIANT = "teacher_compatibility"

MUSCLE_ACTUATOR_COUNT = 22
TORQUE_LIMIT_NM = 17.0
OLD_ANKLE_ACTUATOR_NAMES = ("Exo_R", "Exo_L")
LEGACY_EXO_BODY_NAMES = (
    "shin_cuff_r",
    "actuator_r",
    "foot_attachment_r",
    "shin_cuff_l",
    "actuator_l",
    "foot_attachment_l",
)
LEGACY_EXO_MESH_NAMES = LEGACY_EXO_BODY_NAMES
TEACHER_INERTIA_PREFIX = "teacher_inertia_"


@dataclass(frozen=True)
class ExoActuatorSpec:
    """One actuator in the fixed deployment order."""

    name: str
    joint: str
    gear: float


@dataclass(frozen=True)
class ModelVariantSpec:
    """Paths and inertia policy for one explicit generated model."""

    source_path: Path
    output_path: Path
    model_name: str
    teacher_compatible: bool


@dataclass(frozen=True)
class ImuSpec:
    """One virtual IMU attached to a MyoAssist segment frame."""

    name: str
    body: str
    position: tuple[float, float, float]


# MyoAssist knee flexion is negative, while the G-Exo protocol is positive.
EXO_ACTUATORS = (
    ExoActuatorSpec("gexo_left_hip", "hip_flexion_l", 1.0),
    ExoActuatorSpec("gexo_left_knee", "knee_angle_l", -1.0),
    ExoActuatorSpec("gexo_right_hip", "hip_flexion_r", 1.0),
    ExoActuatorSpec("gexo_right_knee", "knee_angle_r", -1.0),
)

IMU_SPECS = (
    ImuSpec("left_thigh", "femur_l", (0.0, -0.20, 0.0)),
    ImuSpec("left_shank", "tibia_l", (0.0, -0.20, 0.0)),
    ImuSpec("right_thigh", "femur_r", (0.0, -0.20, 0.0)),
    ImuSpec("right_shank", "tibia_r", (0.0, -0.20, 0.0)),
)

MODEL_VARIANTS = {
    PHYSICAL_VARIANT: ModelVariantSpec(
        source_path=DEFAULT_PHYSICAL_SOURCE_PATH,
        output_path=DEFAULT_PHYSICAL_OUTPUT_PATH,
        model_name="myoLeg22_2D_GEXO",
        teacher_compatible=False,
    ),
    TEACHER_COMPAT_VARIANT: ModelVariantSpec(
        source_path=DEFAULT_COMPAT_SOURCE_PATH,
        output_path=DEFAULT_COMPAT_OUTPUT_PATH,
        model_name="myoLeg22_2D_GEXO_TEACHER_COMPAT",
        teacher_compatible=True,
    ),
}


def _parse_xml(path: Path) -> ET.ElementTree:
    parser = ET.XMLParser(
        target=ET.TreeBuilder(insert_comments=True),
    )
    return ET.parse(path, parser=parser)


def _actuator_elements(actuator: ET.Element) -> list[ET.Element]:
    return [
        child
        for child in actuator
        if isinstance(child.tag, str)
    ]


def _validate_source_actuators(
    actuator: ET.Element,
    *,
    teacher_compatible: bool,
) -> list[ET.Element]:
    elements = _actuator_elements(actuator)
    legacy_count = len(OLD_ANKLE_ACTUATOR_NAMES) if teacher_compatible else 0
    expected_count = MUSCLE_ACTUATOR_COUNT + legacy_count

    if len(elements) != expected_count:
        raise ValueError(
            f"Expected {expected_count} source actuators, found "
            f"{len(elements)} actuators."
        )

    muscles = elements[:MUSCLE_ACTUATOR_COUNT]
    if any(element.get("class") != "muscle" for element in muscles):
        raise ValueError("The first 22 source actuators must all be muscles.")

    muscle_names = [element.get("name") for element in muscles]
    if any(name is None for name in muscle_names):
        raise ValueError("Every source muscle actuator must have a name.")
    if len(set(muscle_names)) != MUSCLE_ACTUATOR_COUNT:
        raise ValueError("Source muscle actuator names must be unique.")

    old_names = tuple(element.get("name") for element in elements[22:])
    expected_old_names = OLD_ANKLE_ACTUATOR_NAMES if teacher_compatible else ()
    if old_names != expected_old_names:
        raise ValueError(
            "Legacy ankle actuator order changed: "
            f"expected {expected_old_names}, found {old_names}."
        )

    return elements


def _rewrite_file_paths(
    root: ET.Element,
    *,
    source_directory: Path,
    output_directory: Path,
) -> None:
    """Keep source assets referenced by paths relative to the generated XML."""

    for element in root.iter():
        file_value = element.get("file")
        if file_value is None:
            continue

        source_reference = Path(file_value)
        if not source_reference.is_absolute():
            source_reference = source_directory / source_reference

        resolved_reference = source_reference.resolve(strict=True)
        relative_reference = os.path.relpath(
            resolved_reference,
            start=output_directory,
        )
        element.set("file", Path(relative_reference).as_posix())


def _remove_named_elements(
    root: ET.Element,
    *,
    tag: str,
    names: tuple[str, ...],
) -> None:
    """Remove one known legacy element for every requested name."""

    removed: list[str] = []
    for parent in root.iter():
        for child in list(parent):
            name = child.get("name")
            if child.tag == tag and name in names:
                parent.remove(child)
                removed.append(name)

    if len(removed) != len(names) or set(removed) != set(names):
        raise ValueError(
            f"Expected one <{tag}> for each of {names}, found {removed}."
        )


def _convert_legacy_bodies_to_teacher_inertia(root: ET.Element) -> None:
    """Keep checkpoint-compatible inertia without legacy visuals or actuation."""

    converted: list[str] = []
    for body in root.iter("body"):
        name = body.get("name")
        if name not in LEGACY_EXO_BODY_NAMES:
            continue
        if body.find("inertial") is None:
            raise ValueError(f"Legacy body {name} has no explicit inertia.")
        for geometry in list(body.findall("geom")):
            body.remove(geometry)
        body.set("name", f"{TEACHER_INERTIA_PREFIX}{name}")
        converted.append(name)

    if len(converted) != len(LEGACY_EXO_BODY_NAMES) or set(converted) != set(
        LEGACY_EXO_BODY_NAMES
    ):
        raise ValueError(
            "Expected one legacy body for each compatibility inertia, "
            f"found {converted}."
        )


def _add_virtual_imus(root: ET.Element) -> None:
    """Attach noiseless IMU sites and sensors in the deployment order."""

    bodies = {
        body.get("name"): body
        for body in root.iter("body")
        if body.get("name") is not None
    }
    sensor = root.find("sensor")
    if sensor is None:
        sensor = ET.SubElement(root, "sensor")

    for spec in IMU_SPECS:
        try:
            body = bodies[spec.body]
        except KeyError as error:
            raise ValueError(f"Missing IMU body {spec.body!r}.") from error

        site_name = f"gexo_imu_{spec.name}"
        ET.SubElement(
            body,
            "site",
            {
                "name": site_name,
                "pos": " ".join(f"{value:g}" for value in spec.position),
                "size": "0.008",
                "group": "4",
                "rgba": "0.1 0.4 0.9 0.6",
            },
        )
        ET.SubElement(
            sensor,
            "gyro",
            {
                "name": f"{site_name}_gyro",
                "site": site_name,
            },
        )
        ET.SubElement(
            sensor,
            "accelerometer",
            {
                "name": f"{site_name}_accelerometer",
                "site": site_name,
            },
        )


def build_model(
    source_path: str | Path | None = None,
    output_path: str | Path | None = None,
    *,
    variant: str = PHYSICAL_VARIANT,
) -> Path:
    """Generate a deterministic 22-muscle + four-torque MuJoCo model.

    The default clean model contains no legacy ankle-exoskeleton inertia and is
    the only valid plant for new G-Exo training. The teacher-compatibility
    variant retains invisible legacy inertia solely for diagnostics.
    """

    try:
        variant_spec = MODEL_VARIANTS[variant]
    except KeyError as error:
        choices = ", ".join(sorted(MODEL_VARIANTS))
        raise ValueError(
            f"Unknown model variant {variant!r}; expected one of: {choices}."
        ) from error

    if source_path is None:
        source_path = variant_spec.source_path
    if output_path is None:
        output_path = variant_spec.output_path

    source = Path(source_path).expanduser().resolve(strict=True)
    output = Path(output_path).expanduser().resolve()
    if source == output:
        raise ValueError("The generated model must not overwrite its source.")

    tree = _parse_xml(source)
    root = tree.getroot()
    actuator = root.find("actuator")
    if actuator is None:
        raise ValueError("Source model has no <actuator> section.")

    source_actuators = _validate_source_actuators(
        actuator,
        teacher_compatible=variant_spec.teacher_compatible,
    )
    if variant_spec.teacher_compatible:
        for old_actuator in source_actuators[MUSCLE_ACTUATOR_COUNT:]:
            actuator.remove(old_actuator)

        # Diagnostic bridge only: never use these loads as the G-Exo plant.
        _convert_legacy_bodies_to_teacher_inertia(root)
        _remove_named_elements(
            root,
            tag="mesh",
            names=LEGACY_EXO_MESH_NAMES,
        )

    _add_virtual_imus(root)

    for spec in EXO_ACTUATORS:
        ET.SubElement(
            actuator,
            "motor",
            {
                "name": spec.name,
                "joint": spec.joint,
                "gear": f"{spec.gear:g}",
                "ctrllimited": "true",
                "ctrlrange": f"{-TORQUE_LIMIT_NM:g} {TORQUE_LIMIT_NM:g}",
            },
        )

    root.set("model", variant_spec.model_name)
    root.insert(
        0,
        ET.Comment(
            f" Generated by RL.env.myoassist.model_builder; "
            f"variant={variant}; do not edit manually. "
        ),
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    _rewrite_file_paths(
        root,
        source_directory=source.parent,
        output_directory=output.parent,
    )
    ET.indent(tree, space="    ")
    tree.write(
        output,
        encoding="utf-8",
        xml_declaration=True,
        short_empty_elements=True,
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the 22-muscle, four-joint G-Exo MuJoCo model.",
    )
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--variant",
        choices=sorted(MODEL_VARIANTS),
        default=PHYSICAL_VARIANT,
    )
    args = parser.parse_args()

    output = build_model(
        args.source,
        args.output,
        variant=args.variant,
    )
    print(f"generated {args.variant} model: {output}")


if __name__ == "__main__":
    main()
