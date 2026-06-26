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
        if normalized_niche in {
            "country_comparison_comedy",
            "country_comparison",
            "world_differences",
            "so_sanh_quoc_gia_hai_huoc",
        }:
            contract = self._build_country_comparison_comedy_contract(
                language=language,
                subject=subject,
            )
            validate_content_contract_v2(contract)
            return contract

        contract = self._build_celebrity_contract(language=language, subject=subject)
        validate_content_contract_v2(contract)
        return contract

    @staticmethod
    def _build_country_comparison_comedy_contract(
        *,
        language: str,
        subject: str,
    ) -> dict[str, Any]:
        scenario = subject.strip() or "parents reward good grades"
        title = "How Parents Reward Good Grades in Different Countries"
        hook = "Same school moment, wildly different country reactions."
        target_audience = (
            "Người xem thích country comparison, school life comedy, family humor, "
            "cultural memes và video hoạt hình ngắn dễ xem."
        )
        country_items = [
            ("JP", "JAPAN", "Silent Nod", "Mom just nods. Somehow, that feels like fireworks."),
            ("US", "UNITED STATES", "Pizza Night", "Good grades unlock pizza, games, and one proud selfie."),
            ("MX", "MEXICO", "La Fiesta", "The whole family hears about that A before dinner."),
            ("PH", "PHILIPPINES", "Jollibee Feast", "One high score can turn into a crispy chicken celebration."),
            ("KR", "SOUTH KOREA", "Study Upgrade", "Great score? Nice. Now prepare for the next academy."),
            ("BR", "BRAZIL", "Big Hug", "Mom celebrates loudly enough for the neighbors to join."),
            ("IN", "INDIA", "Family Broadcast", "Your report card reaches every auntie before you sit down."),
            ("GB", "UNITED KINGDOM", "Calm Praise", "A quiet well done, then tea like nothing happened."),
            ("VN", "VIETNAM", "Proud But Strict", "Mom smiles first, then asks why it was not higher."),
            ("AE", "UNITED ARAB EMIRATES", "Luxury Reward", "In the fantasy version, even the reward looks expensive."),
        ]

        scenes = [
            {
                "title": reaction,
                "voiceover": voiceover,
                "caption": reaction,
                "image_prompt": (
                    "2D animated country comparison comedy scene, school report card, "
                    f"{country_label} family reaction to good grades, expressive characters, "
                    "bright YouTube animation, respectful cultural humor, no real person"
                ),
                "statusText": f"{country_label} | {reaction}",
                "countryCode": country_code,
                "countryLabel": country_label,
                "metricLabel": "REACTION",
                "metricValue": reaction,
            }
            for country_code, country_label, reaction, voiceover in country_items
        ]

        return build_content_contract_v2(
            niche="country_comparison_comedy",
            title=title,
            hook=hook,
            target_audience=target_audience,
            language=language,
            scenes=scenes,
            thumbnail_prompt=(
                "Funny country comparison thumbnail, school report card, flags, shocked parents, "
                "bold text, colorful 2D animation style"
            ),
            youtube_title=f"{title} 🌍",
            youtube_description=(
                "Entertainment and edutainment country comparison video inspired by school life, "
                "family comedy, cultural memes, and common stereotypes. This is not a factual "
                "claim about every family in each country."
            ),
            youtube_tags=[
                "country comparison",
                "different countries",
                "school life",
                "family comedy",
                "world differences",
                "animation",
                "funny parents",
                "good grades",
            ],
            duration_target=60,
            cardLayout="flag_hero",
        )

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
            (
                10,
                "Celine Dion",
                550,
                "catalog âm nhạc, tour diễn và thương hiệu Las Vegas",
                "CA",
                "CANADA",
            ),
            (
                9,
                "Elton John",
                650,
                "tour diễn toàn cầu, bản quyền âm nhạc và catalog kinh điển",
                "GB",
                "UNITED KINGDOM",
            ),
            (
                8,
                "Dolly Parton",
                700,
                "bản quyền sáng tác, kinh doanh giải trí và di sản âm nhạc",
                "US",
                "UNITED STATES",
            ),
            (
                7,
                "Bono",
                750,
                "U2, touring, bản quyền và các khoản đầu tư dài hạn",
                "IE",
                "IRELAND",
            ),
            (
                6,
                "Madonna",
                850,
                "tour diễn, catalog pop và thương hiệu biểu diễn nhiều thập kỷ",
                "US",
                "UNITED STATES",
            ),
            (
                5,
                "Taylor Swift",
                1100,
                "tour Eras, catalog thu âm và quyền kiểm soát master",
                "US",
                "UNITED STATES",
            ),
            (
                4,
                "Paul McCartney",
                1300,
                "The Beatles, sáng tác, bản quyền và tour diễn",
                "GB",
                "UNITED KINGDOM",
            ),
            (
                3,
                "Rihanna",
                1400,
                "âm nhạc, Fenty Beauty và hệ sinh thái thương hiệu",
                "BB",
                "BARBADOS",
            ),
            (
                2,
                "Beyonce",
                1600,
                "tour diễn, catalog, thương hiệu và dự án giải trí",
                "US",
                "UNITED STATES",
            ),
            (
                1,
                "Jay-Z",
                2500,
                "âm nhạc, đầu tư, rượu champagne và danh mục kinh doanh",
                "US",
                "UNITED STATES",
            ),
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
                "countryCode": country_code,
                "countryLabel": country_label,
                "metricLabel": "NET WORTH",
                "metricValue": f"{value}M USD",
            }
            for rank, name, value, reason, country_code, country_label in ranking_items
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
