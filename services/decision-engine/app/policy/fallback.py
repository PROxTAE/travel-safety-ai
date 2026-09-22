from __future__ import annotations

from app.domain.models import ActionCode, DecisionReason


def localized_summary(action: ActionCode, locale: str) -> str:
    if locale.lower().startswith("th"):
        return {
            ActionCode.NORMAL: "หลักฐานที่ตรวจสอบแล้วสนับสนุนให้เดินทางตามเส้นทางที่วางไว้",
            ActionCode.CHANGE_ROUTE: "พบเส้นทางทางเลือกที่มีความเสี่ยงต่ำกว่าอย่างมีนัยสำคัญ",
            ActionCode.DELAY: "การเลื่อนเวลาเดินทางภายในช่วงที่กำหนดอาจลดความเสี่ยงได้",
            ActionCode.AVOID: "หลีกเลี่ยงเส้นทางที่ได้รับผลกระทบตราบเท่าที่เงื่อนไขความปลอดภัยยังคงอยู่",
        }[action]
    return {
        ActionCode.NORMAL: "The validated evidence supports continuing the planned route.",
        ActionCode.CHANGE_ROUTE: "A materially safer validated route is available.",
        ActionCode.DELAY: "Delaying within the approved window may reduce the assessed risk.",
        ActionCode.AVOID: (
            "Do not use the affected route while the safety condition remains active."
        ),
    }[action]


def localized_reason(reason: DecisionReason, locale: str) -> DecisionReason:
    if locale.lower().startswith("th"):
        translations = {
            "OFFICIAL_CLOSURE": "มีประกาศทางการให้ปิดเส้นทางที่ตัดผ่านพื้นที่เดินทาง",
            "CONFLICTING_EVIDENCE": "หลักฐานไม่สอดคล้องกัน จึงใช้ผลลัพธ์แบบระมัดระวัง",
            "INSUFFICIENT_EVIDENCE": "ไม่มีการประเมินความเสี่ยงของเส้นทางที่ใช้งานได้เพียงพอ",
        }
        return reason.model_copy(update={"text": translations.get(reason.code, reason.text)})
    return reason
