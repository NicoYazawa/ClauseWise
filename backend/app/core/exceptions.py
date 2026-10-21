"""Centralized application errors.

AppError raises a FastAPI HTTPException whose ``detail`` is a JSON object
``{"code": <stable code>, "message": <human message>}``. The frontend maps
``code`` to a localized string via vue-i18n and falls back to ``message``.
"""
from fastapi import HTTPException


class AppError(HTTPException):
    def __init__(self, code: str, status_code: int, message: str) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
