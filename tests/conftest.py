"""Shared pytest fixtures for all test suites."""

import pytest

from agents.instructions.data_models import (
    ColorEnum,
    EnvironmentEnum,
    FashionImageAnnotation,
    FramingEnum,
    LightingEnum,
    ModelEnum,
    MovementEnum,
    YesNoEnum,
)


@pytest.fixture(scope="session", name="annotation")
def _annotation() -> FashionImageAnnotation:
    """Return a fully-populated FashionImageAnnotation shared across all test suites."""
    return FashionImageAnnotation(
        model=ModelEnum.YES,
        accessories=YesNoEnum.NO,
        movement=MovementEnum.STILL,
        background=YesNoEnum.YES,
        environment=EnvironmentEnum.INDOOR,
        color=ColorEnum.COLORED,
        framing=FramingEnum.FULL,
        lighting=LightingEnum.COOL,
        animal=YesNoEnum.NO,
    )
