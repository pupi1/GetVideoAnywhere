from collections import Counter
import re


class AIService:
    def summarize(self, text: str) -> dict[str, str]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) <= 220:
            summary = cleaned
        else:
            summary = cleaned[:220] + "..."
        words = re.findall(r"[a-zA-Z]{3,}", cleaned.lower())
        top_keywords = [word for word, _ in Counter(words).most_common(5)]
        return {
            "summary": summary or "No content available.",
            "keywords": ", ".join(top_keywords) if top_keywords else "video, media",
            "model": "heuristic-v1",
        }

    def translate(self, text: str, target_language: str = "zh") -> dict[str, str]:
        lang = (target_language or "zh").lower()
        if lang.startswith("zh"):
            translated = f"[简体中文] {text}"
        elif lang.startswith("en"):
            translated = f"[English] {text}"
        else:
            translated = f"[{lang}] {text}"
        return {
            "translated_text": translated,
            "target_language": lang,
            "model": "heuristic-v1",
        }


ai_service = AIService()
