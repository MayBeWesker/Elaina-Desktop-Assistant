"""Voice-command mapping for Mili's photo character modes."""

from __future__ import annotations

import re


DEFAULT_EXPRESSIONS = {
    "0": "character/mili_daily_front_full_neutral.png",
    "1": "character/mili_daily_front_full_neutral.png",
    "2": "character/mili_daily_front_full_calm.png",
    "3": "character/mili_daily_front_full_calm.png",
    "4": "character/mili_daily_front_full_calm.png",
    "5": "character/mili_daily_front_full_neutral.png",
    "6": "character/mili_daily_front_full_calm.png",
}


CHARACTER_MODES = (
    {
        "id": "assistant",
        "name": "灵动助手",
        "url": DEFAULT_EXPRESSIONS["0"],
        "aliases": ("助手", "默认", "表情", "灵动"),
        "expressionFiles": DEFAULT_EXPRESSIONS,
    },
    {
        "id": "formal",
        "name": "正式礼服",
        "url": "character/mili_daily_front_full_neutral.png",
        "aliases": ("正式", "礼服", "正装", "工作"),
    },
    {
        "id": "cool_shortskirt",
        "name": "清凉短裙",
        "url": "character/mili_daily_cool_shortskirt_nobg_half.png",
        "aliases": ("清凉短裙", "清凉", "夏日短裙"),
    },
    {
        "id": "realistic_dress",
        "name": "写实连衣裙",
        "url": "character/mili_daily_realistic_dress_nobg_half.png",
        "aliases": ("写实连衣裙", "写实", "连衣裙"),
    },
    {
        "id": "tights_longskirt",
        "name": "长裙丝袜",
        "url": "character/mili_daily_tights_longskirt_nobg_half.png",
        "aliases": ("长裙丝袜", "丝袜长裙", "长裙"),
    },
    {
        "id": "tights_shortskirt",
        "name": "短裙丝袜",
        "url": "character/mili_daily_tights_shortskirt_nobg_half.png",
        "aliases": ("短裙丝袜", "丝袜短裙"),
    },
    {
        "id": "natural_shortskirt",
        "name": "自然短裙",
        "url": "character/mili_daily_tights_shortskirt_natural_nobg_half.png",
        "aliases": ("自然短裙", "自然风", "休闲短裙"),
    },
    {
        "id": "sports_basic",
        "name": "基础运动",
        "url": "character/mili_sports_basic_nobg_half_full.png",
        "aliases": ("基础运动", "运动基础", "普通运动", "运动装"),
    },
    {
        "id": "sports_refined",
        "name": "精致运动",
        "url": "character/mili_sports_refined_nobg_half_full.png",
        "aliases": ("精致运动", "高级运动", "运动精致"),
    },
    {
        "id": "sports_alluring",
        "name": "运动服装",
        "url": "character/mili_sports_alluring_nobg_half_full.png",
        "aliases": ("运动服装", "运动服", "魅力运动"),
    },
)


ACTION_WORDS = ("切换", "换成", "换上", "变成", "进入", "开启", "显示", "穿上", "恢复")


def match_character_mode(text: str) -> dict | None:
    """Return a serializable mode when text is an intentional switch command."""
    normalized = re.sub(r"[\s，。！？,.!?]", "", text or "").lower()
    if not normalized:
        return None

    has_action = any(word in normalized for word in ACTION_WORDS)
    for mode in CHARACTER_MODES:
        for alias in mode["aliases"]:
            alias = alias.lower()
            exact_mode_phrase = normalized in (alias, f"{alias}模式")
            if alias in normalized and (has_action or exact_mode_phrase):
                return {key: value for key, value in mode.items() if key != "aliases"}
    return None
