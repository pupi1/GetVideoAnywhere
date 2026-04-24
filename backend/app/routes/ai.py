from fastapi import APIRouter

from app.models.schemas import AITextRequest, APIResponse
from app.services.ai_service import ai_service


router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/summarize", response_model=APIResponse)
def summarize(payload: AITextRequest) -> APIResponse:
    data = ai_service.summarize(payload.text)
    return APIResponse(data=data)


@router.post("/translate", response_model=APIResponse)
def translate(payload: AITextRequest) -> APIResponse:
    data = ai_service.translate(payload.text, payload.target_language or "zh")
    return APIResponse(data=data)
