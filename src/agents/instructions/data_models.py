"""Data models for agents."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ModelEnum(StrEnum):
    """Is there a human model in the image?"""

    YES = "yes"
    NO = "no"
    MULTIPLE = "multiple"


class YesNoEnum(StrEnum):
    """Yes or No answer."""

    YES = "yes"
    NO = "no"


class EnvironmentEnum(StrEnum):
    """Where was the image shot?"""

    OUTDOOR = "outdoor"
    INDOOR = "indoor"


class SmileEnum(StrEnum):
    """Is the model smiling, and if so, is the mouth open or closed?"""

    NO = "no"
    CLOSED = "closed mouth"
    OPEN = "open mouth"


class ColorEnum(StrEnum):
    """Is the image in color or black & white?"""

    BW = "b/w"
    COLORED = "colored"


class MovementEnum(StrEnum):
    """Does the model or clothing convey movement, or is it a static pose?"""

    STILL = "still"
    MOVING = "moving"


class EyesEnum(StrEnum):
    """How are the model's eyes captured?"""

    FULL = "full"
    PARTIAL = "partial"
    NOT_VISIBLE = "not visible"
    EYE_CONTACT = "eye contact"


class FramingEnum(StrEnum):
    """What is the crop/framing of the shot?"""

    CLOSE_UP = "close up"
    MID = "mid"
    FULL = "full"


class LightingEnum(StrEnum):
    """What is the color temperature or mood of the lighting?"""

    COOL = "cool"
    WARM = "warm"


class PoseEnum(StrEnum):
    """What is the model's primary pose/orientation?"""

    STANDING = "standing"
    BACK = "back"
    SIDE = "side"
    SITTING = "sitting"


class HandPlacementEnum(StrEnum):
    """Where are the model's hands primarily placed?"""

    LOW = "low"
    HIGH = "high"
    POCKET = "pocket"


class FashionImageAnnotation(BaseModel):
    """Data model representing the annotations of an image."""

    model: ModelEnum
    smile: SmileEnum | None = Field(default=None)
    eyes: EyesEnum | None = Field(default=None)
    face: YesNoEnum | None = Field(default=None)
    skin_reveal: YesNoEnum | None = Field(default=None)
    hand_placement: HandPlacementEnum | None = Field(default=None)
    pose: PoseEnum | None = Field(default=None)
    accessories: YesNoEnum
    movement: MovementEnum
    background: YesNoEnum
    environment: EnvironmentEnum
    color: ColorEnum
    framing: FramingEnum
    lighting: LightingEnum
    animal: YesNoEnum
