"""Content planning agent for MVP video scripts and metadata."""

from __future__ import annotations

from typing import Any

from agents.base_agent import BaseAgent
from core.video_contract import build_content_contract_v2, validate_content_contract_v2


class ContentAgent(BaseAgent):
    """Build a production-shaped content contract without external side effects."""

    def __init__(self) -> None:
        super().__init__(name="content_agent")

    async def run(
        self,
        *,
        niche: str,
        language: str = "vi",
        subject: str = "người nổi tiếng",
    ) -> dict[str, Any]:
        """Return a complete content contract for the requested niche."""
        normalized_niche = niche.strip().lower() or "celebrity"
        if normalized_niche not in {"celebrity", "nguoi_noi_tieng", "người nổi tiếng"}:
            normalized_niche = "celebrity"

        contract = self._build_celebrity_contract(language=language, subject=subject)
        validate_content_contract_v2(contract)
        return contract

    @staticmethod
    def _build_celebrity_contract(*, language: str, subject: str) -> dict[str, Any]:
        safe_subject = subject.strip() or "người nổi tiếng"
        title = f"5 điều khiến {safe_subject} giữ được sự chú ý"
        hook = "Sự nổi tiếng không chỉ đến từ một khoảnh khắc may mắn."
        target_audience = (
            "Người xem Việt Nam quan tâm chuyện hậu trường, giải trí, "
            "thương hiệu cá nhân và bài học phát triển bản thân."
        )
        scenes = [
            {
                "title": "Dấu ấn đầu tiên phải thật rõ",
                "voiceover": (
                    "Một người nổi tiếng thường được nhớ đến nhờ một hình ảnh, "
                    "một phong cách hoặc một câu chuyện rất dễ nhận ra."
                ),
                "caption": "Dấu ấn cá nhân",
                "image_prompt": (
                    "Vietnamese celebrity-inspired stage spotlight, editorial portrait, "
                    "no real logo, respectful entertainment documentary style"
                ),
                "statusText": "BÀI HỌC 1",
            },
            {
                "title": "Khán giả theo dõi hành trình",
                "voiceover": (
                    "Thành tích giúp họ được chú ý, nhưng hành trình vượt áp lực "
                    "mới khiến khán giả muốn tiếp tục theo dõi."
                ),
                "caption": "Câu chuyện",
                "image_prompt": (
                    "behind the scenes celebrity preparation, microphone, camera crew, "
                    "cinematic Vietnamese entertainment mood"
                ),
                "statusText": "BÀI HỌC 2",
            },
            {
                "title": "Kỷ luật nằm sau ánh đèn",
                "voiceover": (
                    "Phía sau vài phút xuất hiện là lịch tập, lịch quay, luyện giọng, "
                    "thử trang phục và rất nhiều lần làm lại."
                ),
                "caption": "Kỷ luật",
                "image_prompt": (
                    "practice room with notes, microphone, stage outfit, professional lighting, "
                    "documentary realism"
                ),
                "statusText": "BÀI HỌC 3",
            },
            {
                "title": "Hình ảnh công chúng cần nhất quán",
                "voiceover": (
                    "Nếu hôm nay họ nói một kiểu và ngày mai làm một kiểu khác, "
                    "niềm tin của khán giả sẽ giảm rất nhanh."
                ),
                "caption": "Nhất quán",
                "image_prompt": (
                    "public image planning board, social media posts, press photos, "
                    "clean editorial composition"
                ),
                "statusText": "BÀI HỌC 4",
            },
            {
                "title": "Sự chú ý phải biến thành giá trị",
                "voiceover": (
                    "Người giữ được sức hút lâu dài thường không chỉ xuất hiện nhiều, "
                    "mà còn tạo ra sản phẩm, câu chuyện hoặc cảm hứng rõ ràng."
                ),
                "caption": "Giá trị",
                "image_prompt": (
                    "bright studio desk, creative planning, spotlight fading into audience, "
                    "premium YouTube documentary style"
                ),
                "statusText": "BÀI HỌC 5",
            },
        ]

        return build_content_contract_v2(
            niche="celebrity",
            title=title,
            hook=hook,
            target_audience=target_audience,
            language=language,
            scenes=scenes,
            thumbnail_prompt=(
                "Vietnamese celebrity analysis YouTube thumbnail, expressive face silhouette, "
                "spotlight, bold empty text area, red and white accents, high contrast"
            ),
            youtube_title=f"5 điều khiến {safe_subject} giữ được sự chú ý",
            youtube_description=(
                "Video phân tích cách người nổi tiếng xây dựng dấu ấn, giữ niềm tin "
                "và biến sự chú ý thành giá trị lâu dài."
            ),
            youtube_tags=[
                "nguoi noi tieng",
                "giai tri",
                "thuong hieu ca nhan",
                "hau truong showbiz",
                "bai hoc thanh cong",
            ],
            duration_target=60,
        )
