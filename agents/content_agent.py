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
        title = "Top 10 ca sĩ giàu nhất thế giới năm 2026"
        hook = "Data comparison theo estimated net worth, dùng số liệu ước tính công khai."
        target_audience = (
            "Người xem Việt Nam thích video thống kê người nổi tiếng, ranking, "
            "so sánh tài sản và dữ liệu giải trí dễ xem."
        )
        ranking_items = [
            (10, "Celine Dion", 550, "catalog âm nhạc, tour diễn và thương hiệu Las Vegas"),
            (9, "Elton John", 650, "tour diễn toàn cầu, bản quyền âm nhạc và catalog kinh điển"),
            (8, "Dolly Parton", 700, "bản quyền sáng tác, kinh doanh giải trí và di sản âm nhạc"),
            (7, "Bono", 750, "U2, touring, bản quyền và các khoản đầu tư dài hạn"),
            (6, "Madonna", 850, "tour diễn, catalog pop và thương hiệu biểu diễn nhiều thập kỷ"),
            (5, "Taylor Swift", 1100, "tour Eras, catalog thu âm và quyền kiểm soát master"),
            (4, "Paul McCartney", 1300, "The Beatles, sáng tác, bản quyền và tour diễn"),
            (3, "Rihanna", 1400, "âm nhạc, Fenty Beauty và hệ sinh thái thương hiệu"),
            (2, "Beyonce", 1600, "tour diễn, catalog, thương hiệu và dự án giải trí"),
            (1, "Jay-Z", 2500, "âm nhạc, đầu tư, rượu champagne và danh mục kinh doanh"),
        ]

        scenes = [
            {
                "title": f"#{rank} {name}",
                "voiceover": (
                    f"#{rank} là {name}, với estimated net worth khoảng "
                    f"{value}M USD từ {reason}."
                ),
                "caption": f"{value}M USD",
                "image_prompt": (
                    f"editorial celebrity data comparison card for {name}, premium stage lighting, "
                    "clean ranking layout, no logo, respectful entertainment style"
                ),
                "statusText": f"#{rank} | {value}M USD",
            }
            for rank, name, value, reason in ranking_items
        ]

        return build_content_contract_v2(
            niche="celebrity",
            title=title,
            hook=hook,
            target_audience=target_audience,
            language=language,
            scenes=scenes,
            thumbnail_prompt=(
                "Top 10 richest singers 2026 YouTube thumbnail, gold numbers, celebrity silhouettes, "
                "bold ranking text area, red and white accents, high contrast"
            ),
            youtube_title=f"Top 10 {safe_subject} giàu nhất thế giới năm 2026",
            youtube_description=(
                "Video data comparison xếp hạng ca sĩ giàu nhất thế giới theo estimated net worth. "
                "Các con số là ước tính công khai và cần được fact-check trước khi xuất bản thật."
            ),
            youtube_tags=[
                "nguoi noi tieng",
                "data comparison",
                "richest singers",
                "top 10 celebrities",
                "giai tri",
                "thong ke so sanh",
            ],
            duration_target=60,
        )
