"""Compact typed callback payloads."""

from aiogram.filters.callback_data import CallbackData


class SetupCallback(CallbackData, prefix="s"):
    game_id: int
    revision: int
    action: str
    value: str


class RandomCallback(CallbackData, prefix="r"):
    action: str
    value: int

