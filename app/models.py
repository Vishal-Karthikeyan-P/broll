from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .errors import ApiError

Ratio = Literal["16:9", "9:16", "1:1"]


class SceneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    visual_hint: Optional[str] = None


class CaptionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    burn_in: bool = True
    srt: bool = True


class CreateJobRequest(BaseModel):
    """Provide exactly one of audio_url, script or scenes."""
    model_config = ConfigDict(extra="forbid")
    audio_url: Optional[str] = None
    script: Optional[str] = None
    scenes: Optional[list[SceneIn]] = None
    voice: str = "en-IN-female"
    aspect_ratios: list[Ratio] = Field(default_factory=lambda: ["16:9"])
    style: str = "bright, modern, real-world footage"
    avoid: list[str] = Field(default_factory=list)
    captions: CaptionOptions = Field(default_factory=CaptionOptions)
    callback_url: Optional[str] = None
    seed: Optional[int] = None

    def input_kind(self, has_upload: bool = False) -> str:
        provided = []
        if has_upload or (self.audio_url and self.audio_url.strip()):
            provided.append("audio")
        if self.script is not None:
            provided.append("script")
        if self.scenes is not None:
            provided.append("scenes")
        if not provided:
            raise ApiError("EMPTY_INPUT", "Provide audio_url, script or scenes.", 400)
        if len(provided) > 1:
            raise ApiError("INVALID_REQUEST", "Provide exactly one of audio_url, script or scenes.", 422,
                           details={"provided": provided})
        kind = provided[0]
        if kind == "script" and not (self.script or "").strip():
            raise ApiError("EMPTY_INPUT", "script is empty.", 400)
        if kind == "scenes" and (not self.scenes or not any(s.text.strip() for s in self.scenes)):
            raise ApiError("EMPTY_INPUT", "scenes is empty.", 400)
        if not self.aspect_ratios:
            raise ApiError("INVALID_REQUEST", "aspect_ratios must not be empty.", 422)
        return kind


class JobCreated(BaseModel):
    job_id: str
    status: str
    links: dict


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: int
    stage: Optional[str] = None
    created_at: str
    updated_at: str
    result: Optional[dict] = None
    error: Optional[dict] = None
