#!/usr/bin/env python3
"""Build the question + answer + lecture-notes bundle.

The script is intentionally dependency-free. It creates intermediate files under
``lecture_work/`` so automatic matching, manual review, rendering, and checking
are repeatable.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SOURCE_MD = ROOT / "2026刷题班_题目与答案合并版.md"
OUTPUT_MD = ROOT / "2026刷题班_题目+答案+讲解合并版.md"
AUDIO_DIR = ROOT / "audio"
TRANSCRIPTS_DIR = ROOT / "transcripts"
WORK_DIR = ROOT / "lecture_work"

QUESTIONS_JSON = WORK_DIR / "questions.json"
TRANSCRIPTS_JSON = WORK_DIR / "transcripts.json"
ALIGNMENT_JSON = WORK_DIR / "alignment_candidates.json"
REVIEW_JSON = WORK_DIR / "review_summaries.json"
REVIEW_MD = WORK_DIR / "alignment_review.md"
STUDENT_REPORT_MD = WORK_DIR / "student_quality_report.md"


R_ID_RE = re.compile(r"(R\d{8}-\d{6})")
META_PAGE_RE = re.compile(r"题目所在页\*\*：第\s*(\d+)\s*页")
QUESTION_HEADING_RE = re.compile(r"^##\s+(.+)$")
CHAPTER_HEADING_RE = re.compile(r"^#\s+(?!#)(.+)$")
SPEAKER_RE = re.compile(r"^\s*\d+号讲话人\s+\d{2}:\d{2}:\d{2}\s*$")
TIMESTAMP_RE = re.compile(r"\d+号讲话人\s+\d{2}:\d{2}:\d{2}")
PUNCT_RE = re.compile(r"[\s，。、“”‘’：:；;！？!?（）()\[\]【】《》<>—\-_.|/\\,`~@#$%^&*+=]+")
SECTION_RE = re.compile(r"^#")


CHINESE_NUMS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
}

STOP_TERMS = {
    "给定资料",
    "给定材料",
    "请结合",
    "请根据",
    "谈谈",
    "理解",
    "认识",
    "分析",
    "进行",
    "归纳概括",
    "提出",
    "建议",
    "对策",
    "参考答案",
    "材料",
    "题目",
    "要求",
    "分",
    "第",
    "页",
}

ASR_NOISE_TERMS = {
    "好多人",
    "感觉我",
    "一天天",
    "同学会问",
    "屏蔽掉",
    "新疆",
    "上厕所",
    "吃饭",
    "休息",
    "管理员",
    "刷视频",
    "哈哈",
    "我先去",
    "不好过",
}

LECTURE_PREFIXES = ("审题定位", "材料拆解", "采点思路", "答案组织", "易错提醒")


MANUAL_SELECTED_IDS: dict[str, list[str]] = {
    "R20240626-173024": ["S5-Q02", "S7-Q08"],
    "R20240626-183025": ["S5-Q02", "S6-Q03"],
    "R20240627-063353": ["S2-Q02", "S2-Q08"],
    "R20240627-073354": ["S2-Q08", "S2-Q09"],
    "R20240627-123341": ["S2-Q12", "S2-Q13"],
    "R20240627-163207": ["S5-Q08", "S6-Q04"],
    "R20240627-193210": ["S6-Q06", "S7-Q10", "S5-Q09"],
    "R20251004-081004": ["S6-Q06", "S5-Q09", "S7-Q10"],
    "R20251004-101006": ["S5-Q07", "S7-Q03", "S6-Q07"],
}


MANUAL_UNCONFIRMED: dict[str, str] = {
    "R20240625-001117": "转写过短且主要是闲聊/收尾，缺少可提炼的有效讲解。",
    "R20240626-193026": "转写过短且夹杂课间闲聊，相关 S7-Q08 讲解已由 R20240626-173024 覆盖。",
    "R20240627-153344": "转写仅为过渡句，无法形成题目讲解。",
    "R20251005-225915": "课后问答跨多个题目，话题频繁切换，无法可靠切分为单题讲解。",
    "R20251006-222617": "课后问答跨应用文、大作文和多道执法主题题，无法可靠切分为单题讲解。",
}


MANUAL_BULLETS: dict[tuple[str, str], list[str]] = {
    ("R20240626-173024", "S5-Q02"): [
        "审题定位：宣讲稿的核心目的是吸引大学毕业生到乡村干事创业，不能写成一般乡村振兴材料摘抄。",
        "材料拆解：刘胜、小丽、小许分别对应干事立业、投资创业、发展事业，可用三个“业”形成清晰分类。",
        "采点思路：乡村优势可概括为发展事业的第一站、干事立业的大舞台、投资创业的新天地。",
        "答案组织：先写乡村振兴背景和宣讲目的，再分写政策前景、机遇未来、环境乡愁，最后发出报名号召。",
        "易错提醒：不要逐段照抄材料，应围绕“农村有什么优势、对大学生有什么好处”重组材料顺序。",
    ],
    ("R20240626-173024", "S7-Q08"): [
        "审题定位：主题是行政执法与良性互动，重点不是泛谈法治，而是说明执法者和被执法者如何相向而行。",
        "材料拆解：良性互动可解释为从管理到服务、从对立到并行、从纸上法治到行动法治。",
        "采点思路：从“怎么办”破题，围绕精细化执法、柔性化执法、规范化执法组织分论点。",
        "答案组织：分论点可写创新执法方式、凝聚执法力量、提升执法效能，再落到开创善管善治新局面。",
        "易错提醒：落脚点要回到良法善治、社会共治和群众法治获得感，避免只写执法技术或一般治理口号。",
    ],
    ("R20240626-183025", "S5-Q02"): [
        "审题定位：宣讲稿要服务“吸引大学毕业生来乡村干事创业”这一目的，结构上应有背景、主体理由和呼吁号召。",
        "材料拆解：主体理由可按有政策有前景、有机遇有未来、有环境有乡愁三层展开。",
        "采点思路：小许对应政策待遇和发展前景，刘胜对应干事立业和晋升机遇，小丽对应产业创业和技术资金支持。",
        "答案组织：材料顺序可以重组，不必照抄；先交代乡村振兴和人才需求，再穿插三个人物事例支撑三个分标题。",
        "易错提醒：结尾要回到“农村机会吸引人、农村环境留住人、来乡村大显身手”的号召，避免只写材料复述。",
    ],
    ("R20240626-183025", "S6-Q03"): [
        "审题定位：文章主题是文化创新赋能新质生产力、文化创造助力奋进新征程，分类点要前后对应。",
        "材料拆解：开头可用文化创新创造、文旅新赛道、群众智慧和力量等材料金句组合成排比。",
        "采点思路：可从跨界融合、科技赋能、文化企业创新创造等角度提炼分论点。",
        "答案组织：论证时用苏州博物馆文创跨界融合、江苏文化企业数字技术赋能等材料作例证。",
        "易错提醒：分论点字数和句式要尽量一致，不要只堆素材而缺少“新质生产力”的主题牵引。",
    ],
    ("R20240627-063353", "S2-Q02"): [
        "审题定位：这是原因分析题，核心评价“砍香樟树被罚”为何引发热议，不能只判断处罚对错。",
        "材料拆解：老师将争议归结为“合法但不够合理”，先说明执法有法律依据和程序依据，再分析不合理之处。",
        "采点思路：按主体分类更稳，包括有关部门、执法部门、居民网友和案件本身四类原因。",
        "答案组织：有关部门回应不清、监管不早、相关部门不作为；执法部门平时普法和事后以案释法不足；居民网友不了解或误解法律。",
        "易错提醒：不要从材料第一段一路平铺，容易漏主体；先拎主体再回材料找证据，能减少漏点。",
    ],
    ("R20240627-063353", "S2-Q08"): [
        "审题定位：这题考语句理解，“每位居民也是依靠的力量”是递进重点，不能把服务对象和依靠对象平均拆分。",
        "材料拆解：全文都围绕居民参与治理展开，依靠力量的本质是引导居民主动参与社区治理。",
        "采点思路：分析顺序是往前看背景问题、往中看措施表现、往后看治理效果。",
        "答案组织：背景写环境与空间难以满足居民多元需求；做法写百姓提案师、规划师、营造师等社区工作法。",
        "易错提醒：对策不是重点，但可以在结尾补完善、规范、推广社区工作法等建议。",
    ],
    ("R20240627-073354", "S2-Q08"): [
        "审题定位：续讲重点仍是社区工作法的理解，答案主体应突出居民参与治理。",
        "材料拆解：百姓提案师强调居民提建议、建立常态机制、积极回应；百姓规划师强调征求建议、采纳合理建议、激发参与热情。",
        "采点思路：效果可写解决社区难题、改善硬件设施、改变生活环境、提高居民参与积极性。",
        "答案组织：在分析后补少量对策，如完善规范推广百姓系列社区工作法、匹配居民多元服务需求。",
        "易错提醒：综合分析题中对策不能喧宾夺主，分析才是主要得分层。",
    ],
    ("R20240627-073354", "S2-Q09"): [
        "审题定位：“知识的力量”重点在传播，尤其是科普知识传播的深度和广度。",
        "材料拆解：先分析背景问题，如伪科普、直播带货欺诈、误导公众；再分析真科普的表现。",
        "采点思路：科普做法包括专家主动触网答疑、用通俗易懂方式传递科学知识、科普达人用实验工具和短视频科普。",
        "答案组织：意义写打动观众、获得好评、让科学理念被更多人接受、激发好奇心和探索能力。",
        "易错提醒：不要只解释“知识本身价值”，要回到传播价值，并在结尾提出丰富内容、创新形式、长期发展科普教育。",
    ],
    ("R20240627-123341", "S2-Q12"): [
        "审题定位：比较“不见面办公”和“不见面治理”，不能只评价线上化好坏。",
        "材料拆解：两者共同背景是信息化时代新技术新手段应用成为常态。",
        "采点思路：比较角度可抓行为方式、实际效果和社会评价；前者正面，后者需要改进。",
        "答案组织：不见面办公写线上受理、绿色通道、容缺受理，效果是解困并获称赞；不见面治理写上网代替下基层，导致通知不到位、不符合实际、问题未解决。",
        "易错提醒：后者不是完全否定，而是要线上线下结合、深入基层、加强监督。",
    ],
    ("R20240627-123341", "S2-Q13"): [
        "审题定位：粉丝文化是双观点现象分析题，要评析不同观点，而不是简单站队。",
        "材料拆解：先概括支持和反对两种观点并表态，两种观点都只看到一面，因而片面。",
        "采点思路：正面分析粉丝文化提供信仰动力、揭露问题、推动社会关注；反面分析占用新闻资源、发布虚假内容、传播不良文化等问题。",
        "答案组织：最后按主体提对策，偶像要自律并传播正能量，粉丝要理性表达并发挥监督作用，政府和平台要宣传规则并监管打击违规行为。",
        "易错提醒：材料中的长句很多是论据，不是观点本身；先提炼观点再分析现象。",
    ],
    ("R20240627-163207", "S5-Q08"): [
        "审题定位：这题是宣传戴窑稻米产业特色，不是单纯卖产品，要写产业发展经验。",
        "材料拆解：总做法是注重品牌建设，探索优质大米种植、加工、销售全产业链发展之路。",
        "采点思路：可按科技创新、设施完善、标准制定、网络销售、文化传承等特色分层。",
        "答案组织：主体适合用“突出某字+与某方面结合+推动特色产业某成效”的并列结构。",
        "易错提醒：应用文主体要偏务实，围绕产业特色和成功经验，不要写成空泛议论文。",
    ],
    ("R20240627-163207", "S6-Q04"): [
        "审题定位：主题两句话中，“科普孕育科创”是重点，“科创领航未来”是辅助落脚。",
        "材料拆解：总书记指示中涉及科学家、青少年、全民族三个主体，要从科普对象和科创主体两头理解。",
        "采点思路：推进科普可写投身科普事业、优化科普内容、拓展科普形式。",
        "答案组织：落脚到激发青少年科学兴趣、提高全民族科学素质、推动创新发展和高水平科技自立自强。",
        "易错提醒：不能只写科技创新，应突出科学普及对科技创新的基础性作用。",
    ],
    ("R20240627-193210", "S6-Q06"): [
        "审题定位：这是对策性文章，重点在“新作为”，不是单纯描述新职业、新业态。",
        "材料拆解：新作为可分为加强政府管理力度、拓展政府服务宽度、提升政府保障温度。",
        "采点思路：具体对策分别对应与时俱进、适度引导、关心关爱。",
        "答案组织：三段可写新时代危机并存需加强管理，新业态野蛮生长需拓展服务，新职业面临窘境需提升保障。",
        "易错提醒：“拓展政府服务宽度”比“拓宽政府服务宽度”更顺，且服务、管理、保障不能混为一谈。",
    ],
    ("R20240627-193210", "S7-Q10"): [
        "审题定位：核心不是泛谈公平正义，而是用“近人、达情、善治”解释如何促进严格规范公正文明执法。",
        "材料拆解：“近人”指深入基层、走进百姓；“达情”指换位思考、通达民情；“善治”指依靠法治追求善治。",
        "采点思路：分论点可围绕深入基层、换位思考、依靠法治三条展开。",
        "答案组织：论证中要结合群众办事、社区治理、虚假保健品监管等材料，最后落到公平正义就在身边。",
        "易错提醒：主题太长时不要硬拆成严格、规范、公正、文明四段，可用三段式承接古语逻辑。",
    ],
    ("R20240627-193210", "S5-Q09"): [
        "审题定位：发言稿主题不是“四个字”培训要点，而是培训后如何发挥驻村第一书记带头人作用。",
        "材料拆解：培训学习内容可归纳为政策学习、产业发展、美丽乡村和乡村协作。",
        "采点思路：三个带头人分别是政策落实的带头人、产业发展的带头人、村民致富的带头人。",
        "答案组织：开头交代培训背景和学习收获，主体分写加强学习提升能力、明确方向突出特色、因地制宜优势互补。",
        "易错提醒：只围绕“找准路子、用好点子”等四个要点会跑偏，应回到“发挥带头人作用”。",
    ],
    ("R20251004-081004", "S6-Q06"): [
        "审题定位：文章要围绕“新时代潮涌新职业，新业态呼唤新作为”，把重点放在政府如何作为。",
        "材料拆解：开头可用从外卖骑手到网络监督师、从云办公到云娱乐等排比引出新职业新业态。",
        "采点思路：三段分别写政府管理与时俱进、政府服务适度引导、政府保障关心关爱。",
        "答案组织：每段先分析问题或背景，再写具体对策，体现对策性文章特征。",
        "易错提醒：新职业、新业态既是落脚点也是问题背景，不要只写成材料现象罗列。",
    ],
    ("R20251004-081004", "S5-Q09"): [
        "审题定位：这是村两委联席会发言稿，主题应提炼为发挥带头人作用。",
        "材料拆解：培训背景、学习收获和回村打算要自然衔接，不能只列培训日程。",
        "采点思路：主体可写做政策落实、产业发展、村民致富三个带头人。",
        "答案组织：每段用材料中的培训内容支撑回村后的行动计划，结尾号召基层干部长见识、换脑子、带群众干。",
        "易错提醒：发言稿要有开场白和呼吁号召，但不要写空泛客套话。",
    ],
    ("R20251004-081004", "S7-Q10"): [
        "审题定位：围绕“善治须达情，达情始近人”写执法文章，先解释古语，再落到执法实践。",
        "材料拆解：近人是执法前提，达情是执法关键，善治是执法目标。",
        "采点思路：可用从被群众骂到怕听不到骂声、从闭门羹到敲开门等对比句写开头。",
        "答案组织：主体围绕深入基层、通达民情、依靠法治展开，材料案例要服务分论点。",
        "易错提醒：不要把古语解释和总书记讲话割裂，要落到严格规范公正文明执法和群众公平正义。",
    ],
    ("R20251004-101006", "S5-Q07"): [
        "审题定位：工作简报围绕“土特”文章和特色产业新动能，核心是如何做。",
        "材料拆解：材料可归纳为转变生产结构、合作研发、优化人才环境等做法。",
        "采点思路：新动能可对应新格局、新品牌、新业态，形成三个分论点。",
        "答案组织：突出“创”字转变结构，围绕“精”字推进合作研发，坚持“引”字优化人才环境。",
        "易错提醒：不要只写产业现状，应写具体工作措施和带来的新动能。",
    ],
    ("R20251004-101006", "S7-Q03"): [
        "审题定位：“用智慧给执法加分，以创新促执法乘效”指向提升行政执法质量和效能。",
        "材料拆解：智慧对应执法质量，创新对应执法效能，落脚仍是行政执法。",
        "采点思路：提升路径可写科技赋能、能力建设、宽严相济。",
        "答案组织：分论点可表述为以智慧执法加分、以创新执法乘效、以为民执法护航。",
        "易错提醒：不要只解释“加分”“乘效”字面含义，要回答提升什么、如何提升、为谁提升。",
    ],
    ("R20251004-101006", "S6-Q07"): [
        "审题定位：主题重点是“网追正能量”，不是泛泛批判网络问题。",
        "材料拆解：网络正能量具有及时到达、无处不在、放大主流价值的特点。",
        "采点思路：推广正能量可从创新治理、坚守责任、服务社会三个角度展开。",
        "答案组织：结合“网络语言即网络生活”，把正能量落到美好生活、真实生活、和谐生活、安全生活。",
        "易错提醒：材料里的网络问题只有在服务正能量主题时才写，不能把文章写成网络乱象治理。",
    ],
}


@dataclass(frozen=True)
class Question:
    id: str
    chapter_index: int
    chapter_title: str
    question_index: int
    title: str
    page: int | None
    start_line: int
    end_line: int
    block: str
    question_text: str
    answer_text: str
    match_text: str
    keywords: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chapter_index": self.chapter_index,
            "chapter_title": self.chapter_title,
            "question_index": self.question_index,
            "title": self.title,
            "page": self.page,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "question_text": self.question_text,
            "answer_text": self.answer_text,
            "match_text": self.match_text,
            "keywords": self.keywords,
        }


def rel(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def chinese_num_to_int(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    total = 0
    current = 0
    seen = False
    for char in raw:
        if char not in CHINESE_NUMS:
            return None
        value = CHINESE_NUMS[char]
        seen = True
        if value == 100:
            current = max(current, 1) * 100
            total += current
            current = 0
        elif value == 10:
            current = max(current, 1) * 10
            total += current
            current = 0
        else:
            current = value
    if seen:
        total += current
        return total
    return None


def int_to_chinese(num: int) -> str:
    digits = "零一二三四五六七八九"
    if num <= 10:
        return "十" if num == 10 else digits[num]
    if num < 20:
        return "十" + digits[num - 10]
    if num < 100:
        tens, ones = divmod(num, 10)
        return digits[tens] + "十" + (digits[ones] if ones else "")
    return str(num)


def compact_text(text: str, limit: int | None = None) -> str:
    text = TIMESTAMP_RE.sub("", text)
    text = re.sub(r"R\d{8}-\d{6}[^\n]*", "", text)
    text = PUNCT_RE.sub("", text)
    if limit is not None:
        return text[:limit]
    return text


def display_excerpt(text: str, limit: int = 220) -> str:
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or SPEAKER_RE.match(line):
            continue
        cleaned_lines.append(line)
    cleaned = " ".join(cleaned_lines)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def clean_transcript_text(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or SPEAKER_RE.match(line):
            continue
        if R_ID_RE.search(line) and line.upper().endswith(".WAV"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def split_sentences(text: str) -> list[str]:
    text = clean_transcript_text(text)
    parts = re.split(r"(?<=[。！？!?])\s*|\n+", text)
    sentences = [re.sub(r"\s+", "", part).strip() for part in parts]
    return [sentence for sentence in sentences if len(sentence) >= 8]


def make_ngrams(text: str, limit: int | None = None) -> set[str]:
    compact = compact_text(text, limit=limit)
    grams: set[str] = set()
    for size in (2, 3, 4):
        if len(compact) <= size:
            continue
        grams.update(compact[i : i + size] for i in range(len(compact) - size + 1))
    return grams


def cosineish_score(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def extract_keywords(text: str, *, limit: int = 20) -> list[str]:
    keywords: list[str] = []
    for pattern in (r"“([^”]{2,18})”", r"《([^》]{2,18})》", r"[A-Za-z][A-Za-z0-9+\-.]{1,18}"):
        for match in re.findall(pattern, text):
            if match not in keywords:
                keywords.append(match)

    compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", text)
    chunks = [chunk for chunk in compact.split() if 2 <= len(chunk) <= 12]
    counts = Counter(chunks)
    for chunk, _ in counts.most_common(80):
        if any(stop in chunk for stop in STOP_TERMS):
            continue
        if chunk.isdigit():
            continue
        if chunk not in keywords:
            keywords.append(chunk)
        if len(keywords) >= limit:
            break
    return keywords[:limit]


def extract_sections(block: str) -> tuple[str, str]:
    question_marker = "### 📘 题目与材料"
    answer_marker = "### ✍️ 参考答案"
    question_text = ""
    answer_text = ""
    if question_marker in block and answer_marker in block:
        before_answer, answer_part = block.split(answer_marker, 1)
        question_text = before_answer.split(question_marker, 1)[1].strip()
        answer_text = answer_part.strip()
    elif answer_marker in block:
        before_answer, answer_part = block.split(answer_marker, 1)
        question_text = before_answer.strip()
        answer_text = answer_part.strip()
    else:
        question_text = block.strip()
    answer_text = re.sub(r"\n---\s*$", "", answer_text).strip()
    return question_text, answer_text


def parse_questions() -> list[Question]:
    if not SOURCE_MD.exists():
        raise FileNotFoundError(f"Missing source Markdown: {SOURCE_MD}")

    lines = read_text(SOURCE_MD).splitlines()
    chapter_by_line: dict[int, tuple[int, str]] = {}
    chapter_index = 0
    chapter_title = ""
    for idx, line in enumerate(lines):
        match = CHAPTER_HEADING_RE.match(line)
        if match:
            chapter_index += 1
            chapter_title = match.group(1).strip()
        chapter_by_line[idx] = (chapter_index, chapter_title)

    starts = [idx for idx, line in enumerate(lines) if QUESTION_HEADING_RE.match(line)]
    questions: list[Question] = []
    q_counts: Counter[int] = Counter()
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        title_match = QUESTION_HEADING_RE.match(lines[start])
        if not title_match:
            continue
        title = title_match.group(1).strip()
        chapter_idx, chapter = chapter_by_line[start]
        q_counts[chapter_idx] += 1
        question_idx = q_counts[chapter_idx]
        block = "\n".join(lines[start:end]).rstrip()
        page_match = META_PAGE_RE.search(block)
        page = int(page_match.group(1)) if page_match else None
        question_text, answer_text = extract_sections(block)
        match_text = "\n".join(
            [
                title,
                question_text[:6000],
                answer_text[:2000],
            ]
        )
        keywords = extract_keywords("\n".join([title, question_text[:1500], answer_text[:1000]]))
        questions.append(
            Question(
                id=f"S{chapter_idx}-Q{question_idx:02d}",
                chapter_index=chapter_idx,
                chapter_title=chapter,
                question_index=question_idx,
                title=title,
                page=page,
                start_line=start + 1,
                end_line=end,
                block=block,
                question_text=question_text,
                answer_text=answer_text,
                match_text=match_text,
                keywords=keywords,
            )
        )
    return questions


def parse_hints(name: str) -> tuple[list[int], list[int], list[str]]:
    page_hints: set[int] = set()
    question_hints: set[int] = set()

    for raw in re.findall(r"P(\d{1,3})", name, flags=re.IGNORECASE):
        page_hints.add(int(raw))
    for raw in re.findall(r"第\s*(\d{1,3})\s*页", name):
        page_hints.add(int(raw))
    for raw in re.findall(r"第\s*([一二三四五六七八九十百两\d]{1,6})\s*题", name):
        value = chinese_num_to_int(raw)
        if value is not None:
            question_hints.add(value)
    for raw in re.findall(r"([一二三四五六七八九十百两]{1,6})、", name):
        value = chinese_num_to_int(raw)
        if value is not None:
            question_hints.add(value)

    cleaned = re.sub(r"\.[A-Za-z0-9]+", " ", name)
    cleaned = R_ID_RE.sub("", cleaned)
    cleaned = re.sub(r"P\d{1,3}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"第[一二三四五六七八九十百两\d]{1,6}[页题]", "", cleaned)
    name_terms = extract_keywords(cleaned, limit=12)
    return sorted(page_hints), sorted(question_hints), name_terms


def scan_transcripts() -> dict[str, Any]:
    audio_by_id: dict[str, Path] = {}
    for path in sorted(AUDIO_DIR.glob("*")):
        if not path.is_file():
            continue
        match = R_ID_RE.search(path.name)
        if match:
            audio_by_id[match.group(1)] = path

    transcript_by_id: dict[str, Path] = {}
    for path in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        match = R_ID_RE.search(path.name)
        if match:
            transcript_by_id[match.group(1)] = path

    records: list[dict[str, Any]] = []
    for r_id, transcript_path in sorted(transcript_by_id.items()):
        audio_path = audio_by_id.get(r_id)
        transcript_text = read_text(transcript_path)
        joined_names = transcript_path.name + " " + (audio_path.name if audio_path else "")
        page_hints, question_hints, name_terms = parse_hints(joined_names)
        records.append(
            {
                "r_id": r_id,
                "transcript_path": rel(transcript_path),
                "audio_path": rel(audio_path),
                "transcript_name": transcript_path.name,
                "audio_name": audio_path.name if audio_path else "",
                "transcript_length": transcript_path.stat().st_size,
                "audio_length": audio_path.stat().st_size if audio_path else None,
                "page_hints": page_hints,
                "question_hints": question_hints,
                "name_terms": name_terms,
                "excerpt": display_excerpt(transcript_text),
                "is_short": transcript_path.stat().st_size < 2000,
            }
        )

    missing_transcripts = []
    for r_id, audio_path in sorted(audio_by_id.items()):
        if r_id not in transcript_by_id:
            page_hints, question_hints, name_terms = parse_hints(audio_path.name)
            missing_transcripts.append(
                {
                    "r_id": r_id,
                    "audio_path": rel(audio_path),
                    "audio_name": audio_path.name,
                    "audio_length": audio_path.stat().st_size,
                    "page_hints": page_hints,
                    "question_hints": question_hints,
                    "name_terms": name_terms,
                }
            )

    return {
        "source": {
            "audio_dir": rel(AUDIO_DIR),
            "transcripts_dir": rel(TRANSCRIPTS_DIR),
        },
        "audio_count": len(audio_by_id),
        "transcript_count": len(transcript_by_id),
        "records": records,
        "audio_without_transcript": missing_transcripts,
    }


def keyword_hits(terms: list[str], text: str) -> list[str]:
    return [term for term in terms if term and term in text]


def build_alignment(questions: list[Question], transcript_data: dict[str, Any]) -> dict[str, Any]:
    q_by_id = {question.id: question for question in questions}
    page_to_questions: dict[int, list[Question]] = defaultdict(list)
    question_no_to_questions: dict[int, list[Question]] = defaultdict(list)
    q_grams = {question.id: make_ngrams(question.match_text, limit=9000) for question in questions}
    q_text_compact = {question.id: compact_text(question.match_text) for question in questions}

    alignments: list[dict[str, Any]] = []
    for record in transcript_data["records"]:
        transcript_path = ROOT / record["transcript_path"]
        transcript_text = read_text(transcript_path)
        transcript_clean = clean_transcript_text(transcript_text)
        transcript_grams = make_ngrams(transcript_clean, limit=16000)

        candidate_scores: dict[str, float] = defaultdict(float)
        candidate_reasons: dict[str, list[str]] = defaultdict(list)

        for page in record["page_hints"]:
            matches = [question for question in questions if question.page == page]
            for question in matches:
                candidate_scores[question.id] += 1.8 if len(matches) == 1 else 1.2
                candidate_reasons[question.id].append(
                    f"filename page hint P{page:03d} matched {len(matches)} question(s)"
                )

        for q_no in record["question_hints"]:
            matches = [question for question in questions if question.question_index == q_no]
            if record["page_hints"]:
                page_set = set(record["page_hints"])
                matches = [question for question in matches if question.page in page_set] or matches
            for question in matches:
                candidate_scores[question.id] += 0.9
                candidate_reasons[question.id].append(f"filename question hint Q{q_no}")

        name_hits_by_q: list[tuple[str, list[str]]] = []
        for question in questions:
            hits = keyword_hits(record["name_terms"], q_text_compact[question.id])
            if hits:
                name_hits_by_q.append((question.id, hits))
        for qid, hits in name_hits_by_q:
            candidate_scores[qid] += min(0.8, 0.18 * len(hits))
            candidate_reasons[qid].append("filename keyword hit: " + "、".join(hits[:5]))

        similarity_rows: list[tuple[str, float]] = []
        for qid, grams in q_grams.items():
            score = cosineish_score(transcript_grams, grams)
            similarity_rows.append((qid, score))
        similarity_rows.sort(key=lambda item: item[1], reverse=True)
        for rank, (qid, score) in enumerate(similarity_rows[:8], start=1):
            if score <= 0:
                continue
            candidate_scores[qid] += score * 2.6
            candidate_reasons[qid].append(f"text similarity rank {rank}: {score:.3f}")

        candidate_rows = []
        for qid, score in candidate_scores.items():
            question = q_by_id[qid]
            candidate_rows.append(
                {
                    "question_id": qid,
                    "score": round(score, 4),
                    "chapter": question.chapter_title,
                    "question_index": question.question_index,
                    "page": question.page,
                    "title": question.title,
                    "reasons": candidate_reasons[qid],
                    "question_keywords": question.keywords[:10],
                }
            )
        candidate_rows.sort(key=lambda row: row["score"], reverse=True)
        candidate_rows = candidate_rows[:8]

        selected_ids = select_questions_for_record(candidate_rows, record)
        confidence, review_required, confidence_reason = classify_alignment(
            candidate_rows,
            selected_ids,
            record,
        )
        alignments.append(
            {
                "r_id": record["r_id"],
                "transcript_path": record["transcript_path"],
                "audio_path": record["audio_path"],
                "transcript_name": record["transcript_name"],
                "audio_name": record["audio_name"],
                "transcript_length": record["transcript_length"],
                "is_short": record["is_short"],
                "page_hints": record["page_hints"],
                "question_hints": record["question_hints"],
                "name_terms": record["name_terms"],
                "selected_question_ids": selected_ids,
                "confidence": confidence,
                "review_required": review_required,
                "confidence_reason": confidence_reason,
                "candidates": candidate_rows,
                "excerpt": display_excerpt(transcript_text, limit=360),
            }
        )

    return {
        "alignments": alignments,
        "confidence_counts": dict(Counter(row["confidence"] for row in alignments)),
    }


def select_questions_for_record(candidate_rows: list[dict[str, Any]], record: dict[str, Any]) -> list[str]:
    if not candidate_rows:
        return []
    top_score = candidate_rows[0]["score"]
    selected: list[str] = []

    # If the filename explicitly names multiple pages, keep every top candidate
    # backed by those page hints.
    if len(record["page_hints"]) > 1:
        page_set = set(record["page_hints"])
        selected = [row["question_id"] for row in candidate_rows if row["page"] in page_set]
    elif record["page_hints"]:
        page_set = set(record["page_hints"])
        page_matches = [row for row in candidate_rows if row["page"] in page_set]
        if page_matches:
            best = max(row["score"] for row in page_matches)
            selected = [
                row["question_id"]
                for row in page_matches
                if row["score"] >= best - 0.5 or row["score"] >= top_score - 0.35
            ]

    if not selected and len(record["question_hints"]) > 1:
        q_set = set(record["question_hints"])
        selected = [row["question_id"] for row in candidate_rows if row["question_index"] in q_set]

    if not selected:
        selected = [candidate_rows[0]["question_id"]]
        for row in candidate_rows[1:4]:
            if row["score"] >= max(1.0, top_score * 0.94):
                selected.append(row["question_id"])

    return list(dict.fromkeys(selected))


def classify_alignment(
    candidate_rows: list[dict[str, Any]],
    selected_ids: list[str],
    record: dict[str, Any],
) -> tuple[str, bool, str]:
    if not candidate_rows or not selected_ids:
        return "low", True, "no candidate"

    top = candidate_rows[0]
    second_score = candidate_rows[1]["score"] if len(candidate_rows) > 1 else 0.0
    has_page = bool(record["page_hints"])
    has_question = bool(record["question_hints"])
    is_cross = len(selected_ids) > 1

    if record["is_short"]:
        return "low", True, "short transcript"

    if has_page and has_question and len(selected_ids) == 1 and top["score"] >= 2.0:
        return "high", False, "page and question hints converge"
    if has_page and len(selected_ids) == 1 and top["score"] >= 2.2 and top["score"] - second_score >= 0.25:
        return "high", False, "unique page-backed candidate"
    if has_page or has_question or is_cross:
        return "medium", True, "filename hint needs review"
    if top["score"] >= 1.05 and top["score"] - second_score >= 0.3:
        return "medium", True, "text similarity lead"
    return "low", True, "weak or ambiguous evidence"


def clean_inline(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" ：:；;，,。.\n\t")


def short_clause(text: str, limit: int = 58) -> str:
    text = clean_inline(text)
    text = re.sub(r"^【参考答案】", "", text).strip()
    if len(text) <= limit:
        return text
    cut_positions = [pos for token in "。；;，," if 14 <= (pos := text.find(token)) <= limit]
    if cut_positions:
        return text[: min(cut_positions)].strip(" ：:；;，,。.")
    return text[:limit].rstrip(" ：:；;，,。.") + "等"


def clean_question_title(title: str) -> str:
    title = re.sub(r"^第[一二三四五六七八九十百零两\d]+题[:：]?", "", title)
    title = re.sub(r"（\d+\s*分）", "", title)
    return short_clause(title, limit=74)


def meaningful_prompt(text: str) -> bool:
    compact = compact_text(text)
    return len(compact) >= 8 and "材料" not in compact[:4]


def question_prompt(question: Question) -> str:
    title = clean_question_title(question.title)
    prompt_lines: list[str] = []
    for line in question.question_text.splitlines():
        line = clean_inline(line)
        if not line:
            continue
        if line.startswith("要求") or line.startswith("材料"):
            break
        prompt_lines.append(line)
        if len("".join(prompt_lines)) >= 120:
            break

    prompt = title
    if prompt_lines:
        first = " ".join(prompt_lines)
        if not meaningful_prompt(prompt):
            prompt = first
        elif first.startswith("．．．") or prompt.endswith("请用一段话") or prompt.endswith("请你以"):
            prompt = prompt + first

    prompt = prompt.replace("．．．", "")
    prompt = re.sub(r"（\d+\s*分）", "", prompt)
    prompt = clean_inline(prompt)
    return short_clause(prompt, limit=96) if meaningful_prompt(prompt) else "本题设问"


def clean_reference_answer(answer_text: str) -> str:
    answer = re.sub(r"^【参考答案】", "", answer_text.strip())
    answer = re.sub(r"\n+", " ", answer)
    return clean_inline(answer)


def split_answer_points(answer_text: str) -> tuple[str, list[str]]:
    answer = clean_reference_answer(answer_text)
    if not answer:
        return "", []
    pieces = [piece.strip() for piece in re.split(r"\s*\d+[.．、]\s*", answer) if piece.strip()]
    if len(pieces) <= 1:
        sentences = [sentence.strip() for sentence in re.split(r"[。；;]", answer) if sentence.strip()]
        return "", sentences[:4]
    intro = pieces[0]
    return intro, pieces[1:5]


def chapter_method_hint(chapter_title: str) -> str:
    if "归纳概括" in chapter_title:
        return "这类题重在归纳共性，按题干限定对象提炼要点，不展开议论。"
    if "综合分析" in chapter_title:
        return "这类题要先明确理解或判断，再围绕材料分析原因、表现、影响或对策。"
    if "提出对策" in chapter_title:
        return "这类题要从材料问题反推建议，突出针对性和可操作性。"
    if "应用文" in chapter_title:
        return "这类题要同时照顾身份、对象、文种和行文目的，不能只堆材料点。"
    if "议论文" in chapter_title or "大作文" in chapter_title:
        return "这类题要先稳住立意，再用材料支撑分论点和文章结构。"
    if "行政执法" in chapter_title:
        return "这类题要围绕执法理念、执法方式和群众感受组织材料。"
    return "审题时先锁定作答对象，再决定按原因、做法、效果或对策分层。"


def point_label(point: str) -> str:
    point = clean_inline(point)
    for token in "，,；;。":
        pos = point.find(token)
        if 2 <= pos <= 24:
            return point[:pos].strip(" ：:；;，,。.")
    return short_clause(point, limit=24)


def summarize_points(points: list[str], limit: int = 3) -> str:
    clauses = [point_label(point) for point in points[:limit]]
    return "；".join(clause for clause in clauses if clause)


def transcript_focus_sentence(transcript_text: str, question: Question) -> str:
    cue_terms = {
        "注意",
        "不能",
        "不要",
        "核心",
        "关键",
        "重点",
        "主题",
        "分类",
        "主体",
        "开头",
        "结尾",
        "分论点",
        "答题思路",
    }
    question_terms = set(question.keywords[:12])
    rows: list[tuple[float, int, str]] = []
    for idx, sentence in enumerate(split_sentences(transcript_text)):
        sentence = clean_inline(sentence)
        compact = compact_text(sentence)
        if not 18 <= len(compact) <= 120:
            continue
        if "..." in sentence or any(term in sentence for term in ASR_NOISE_TERMS):
            continue
        score = 0.0
        score += 0.9 * len([term for term in cue_terms if term in sentence])
        score += 0.5 * len([term for term in question_terms if term and term in sentence])
        if "这道题" in sentence or "这篇文章" in sentence:
            score += 0.5
        if score:
            rows.append((score, idx, sentence))
    if not rows:
        return ""
    rows.sort(key=lambda item: (-item[0], item[1]))
    return short_clause(rows[0][2], limit=62)


def extractive_bullets(transcript_text: str, question: Question, *, max_bullets: int = 5) -> list[str]:
    del transcript_text
    intro, points = split_answer_points(question.answer_text)
    title = question_prompt(question)
    point_summary = summarize_points(points)
    bullets: list[str] = [
        f"审题定位：{chapter_method_hint(question.chapter_title)}本题要处理的是：{title}。",
    ]

    if intro:
        bullets.append(f"材料拆解：参考答案的总括判断是“{short_clause(intro)}”，后续要点都应围绕这个判断展开。")
    elif points:
        bullets.append(f"材料拆解：参考答案把材料拆成“{point_summary}”等层次，可据此回到材料定位采分点。")

    if points:
        bullets.append(f"采点思路：可按“{point_summary}”的顺序采点，先抓关键词，再补充材料中的原因、做法或效果。")
    else:
        keywords = "、".join(question.keywords[:4])
        bullets.append(f"采点思路：围绕“{keywords}”等题干关键词筛选材料，避免把无关背景写进答案。")

    if len(points) >= 3:
        bullets.append("答案组织：采用“总括句+分点展开”的结构，每个分点尽量保持同一颗粒度，方便阅卷定位。")
    else:
        bullets.append("答案组织：先回应设问，再用材料依据展开说明，必要时在结尾回到题干要求。")

    bullets.append(f"易错提醒：不要脱离“{title}”泛泛作答，也不要把材料现象原样堆叠成答案。")

    return bullets[:max_bullets]


def make_review_summaries(
    questions: list[Question],
    transcript_data: dict[str, Any],
    alignment_data: dict[str, Any],
) -> dict[str, Any]:
    q_by_id = {question.id: question for question in questions}
    entries: list[dict[str, Any]] = []
    for alignment in alignment_data["alignments"]:
        transcript_text = read_text(ROOT / alignment["transcript_path"])
        question_notes: list[dict[str, Any]] = []
        for qid in alignment["selected_question_ids"]:
            question = q_by_id.get(qid)
            if not question:
                continue
            question_notes.append(
                {
                    "question_id": qid,
                    "status": "needs_review" if alignment["review_required"] else "confirmed",
                    "summary_bullets": extractive_bullets(transcript_text, question),
                    "review_notes": "",
                }
            )
        entries.append(
            {
                "r_id": alignment["r_id"],
                "transcript_path": alignment["transcript_path"],
                "audio_path": alignment["audio_path"],
                "confidence": alignment["confidence"],
                "review_required": alignment["review_required"],
                "status": "needs_review" if alignment["review_required"] else "confirmed",
                "selected_question_ids": alignment["selected_question_ids"],
                "question_notes": question_notes,
                "unconfirmed_reason": "" if not alignment["review_required"] else alignment["confidence_reason"],
            }
        )

    return {
        "schema_version": 1,
        "summary_style": "讲义式要点，每题约3-6条；只根据题目、答案、转写整理。",
        "entries": entries,
        "audio_without_transcript": transcript_data["audio_without_transcript"],
    }


def write_alignment_review(questions: list[Question], alignment_data: dict[str, Any]) -> None:
    q_by_id = {question.id: question for question in questions}
    lines: list[str] = [
        "# 讲解转写对齐复核清单",
        "",
        "说明：重点复核 low / medium、跨题、极短转写。确认后修改 review_summaries.json。",
        "",
    ]
    for alignment in alignment_data["alignments"]:
        if (
            alignment["confidence"] == "high"
            and not alignment["is_short"]
            and len(alignment["selected_question_ids"]) == 1
        ):
            continue
        lines.append(f"## {alignment['r_id']} ({alignment['confidence']})")
        lines.append("")
        lines.append(f"- 转写：`{alignment['transcript_path']}`")
        lines.append(f"- 录音：`{alignment['audio_path'] or '缺失'}`")
        lines.append(f"- 原因：{alignment['confidence_reason']}")
        lines.append(f"- 页码提示：{alignment['page_hints'] or '无'}；题号提示：{alignment['question_hints'] or '无'}")
        lines.append(f"- 摘录：{alignment['excerpt']}")
        lines.append("")
        lines.append("候选题：")
        for candidate in alignment["candidates"][:5]:
            question = q_by_id.get(candidate["question_id"])
            title = question.title if question else candidate["title"]
            lines.append(
                f"- `{candidate['question_id']}` P{candidate['page']} "
                f"{candidate['chapter']} 第{candidate['question_index']}题 "
                f"score={candidate['score']}: {title}"
            )
            lines.append(f"  - 证据：{'; '.join(candidate['reasons'][:3])}")
        lines.append("")
    REVIEW_MD.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def prepare(args: argparse.Namespace) -> int:
    WORK_DIR.mkdir(exist_ok=True)
    questions = parse_questions()
    transcript_data = scan_transcripts()
    alignment_data = build_alignment(questions, transcript_data)

    write_json(
        QUESTIONS_JSON,
        {
            "source": rel(SOURCE_MD),
            "question_count": len(questions),
            "questions": [question.to_json() for question in questions],
        },
    )
    write_json(TRANSCRIPTS_JSON, transcript_data)
    write_json(ALIGNMENT_JSON, alignment_data)
    if args.force_review or not REVIEW_JSON.exists():
        write_json(REVIEW_JSON, make_review_summaries(questions, transcript_data, alignment_data))
    else:
        print(f"Keeping existing manual review file: {rel(REVIEW_JSON)}")
    write_alignment_review(questions, alignment_data)

    print(f"Questions: {len(questions)}")
    print(f"Audio files: {transcript_data['audio_count']}")
    print(f"Transcript files: {transcript_data['transcript_count']}")
    print(f"Confidence: {alignment_data['confidence_counts']}")
    print(f"Wrote {rel(WORK_DIR)}")
    return 0


def load_questions_from_work() -> list[Question]:
    data = read_json(QUESTIONS_JSON)
    questions = []
    for row in data["questions"]:
        questions.append(
            Question(
                id=row["id"],
                chapter_index=row["chapter_index"],
                chapter_title=row["chapter_title"],
                question_index=row["question_index"],
                title=row["title"],
                page=row["page"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                block="",
                question_text=row["question_text"],
                answer_text=row["answer_text"],
                match_text=row["match_text"],
                keywords=row["keywords"],
            )
        )
    return questions


def apply_manual_review(args: argparse.Namespace) -> int:
    del args
    ensure_work_files()
    review_data = read_json(REVIEW_JSON)
    questions = load_questions_from_work()
    q_by_id = {question.id: question for question in questions}

    confirmed_count = 0
    unconfirmed_count = 0
    for entry in review_data["entries"]:
        r_id = entry["r_id"]
        if r_id in MANUAL_UNCONFIRMED:
            entry["status"] = "unconfirmed"
            entry["review_required"] = True
            entry["unconfirmed_reason"] = MANUAL_UNCONFIRMED[r_id]
            entry["student_ready_status"] = "skipped"
            entry["student_not_ready_reason"] = MANUAL_UNCONFIRMED[r_id]
            for note in entry.get("question_notes", []):
                note["status"] = "unconfirmed"
                note["review_notes"] = MANUAL_UNCONFIRMED[r_id]
                note["student_ready_status"] = "skipped"
                note["student_not_ready_reason"] = MANUAL_UNCONFIRMED[r_id]
            unconfirmed_count += 1
            continue

        selected_ids = MANUAL_SELECTED_IDS.get(r_id, entry.get("selected_question_ids", []))
        transcript_text = read_text(ROOT / entry["transcript_path"])
        question_notes: list[dict[str, Any]] = []
        for qid in selected_ids:
            question = q_by_id.get(qid)
            if question is None:
                raise ValueError(f"{r_id} references unknown question id: {qid}")
            manual_bullets = MANUAL_BULLETS.get((r_id, qid))
            bullets = manual_bullets or extractive_bullets(transcript_text, question)
            if not bullets:
                continue
            review_note = "人工复核：转写主题、题干关键词或文件名线索与本题一致。"
            student_ready_status = "skipped"
            student_ready_reason = ""
            if manual_bullets:
                review_note = "人工复核：跨题转写已按题干和主题词切分。"
                student_ready_status = "ready"
                student_ready_reason = "手工复核讲义要点，已按题干和主题词切分。"
            elif entry.get("confidence") == "high":
                student_ready_status = "ready"
                student_ready_reason = "高置信度来源，正文采用安全讲义模板生成。"
            else:
                student_ready_reason = "严格可靠策略：非高置信度且无手工讲义要点，移入附录供追溯。"
            question_notes.append(
                {
                    "question_id": qid,
                    "status": "confirmed",
                    "summary_bullets": bullets,
                    "review_notes": review_note,
                    "student_ready_status": student_ready_status,
                    "student_ready_reason": student_ready_reason,
                }
            )

        if question_notes:
            entry["status"] = "confirmed"
            entry["review_required"] = False
            entry["selected_question_ids"] = selected_ids
            entry["question_notes"] = question_notes
            entry["unconfirmed_reason"] = ""
            if any(note["student_ready_status"] == "ready" for note in question_notes):
                entry["student_ready_status"] = "ready"
                entry["student_not_ready_reason"] = ""
            else:
                entry["student_ready_status"] = "skipped"
                entry["student_not_ready_reason"] = "严格可靠策略：没有可进入正文的可靠讲解。"
            confirmed_count += 1
        else:
            entry["status"] = "unconfirmed"
            entry["review_required"] = True
            entry["question_notes"] = []
            entry["unconfirmed_reason"] = "人工复核后未生成可用讲解要点。"
            entry["student_ready_status"] = "skipped"
            entry["student_not_ready_reason"] = entry["unconfirmed_reason"]
            unconfirmed_count += 1

    notes_by_q, unconfirmed_entries, _ = build_notes_by_question(review_data)
    review_data["manual_review"] = {
        "status": "applied",
        "confirmed_entries": confirmed_count,
        "unconfirmed_entries": unconfirmed_count,
        "confirmed_question_count": len(notes_by_q),
        "unconfirmed_r_ids": [entry["r_id"] for entry in unconfirmed_entries],
    }
    write_json(REVIEW_JSON, review_data)

    print(f"Wrote {rel(REVIEW_JSON)}")
    print(f"Confirmed transcript entries: {confirmed_count}")
    print(f"Unconfirmed transcript entries: {unconfirmed_count}")
    print(f"Questions with confirmed lecture notes: {len(notes_by_q)}")
    return 0


def build_notes_by_question(
    review_data: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    notes_by_q: dict[str, list[dict[str, Any]]] = defaultdict(list)
    appendix_entries: list[dict[str, Any]] = []
    skipped_by_q: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in review_data["entries"]:
        entry_status = entry.get("status", "needs_review")
        if entry_status != "confirmed":
            appendix_entries.append(entry)
            for qid in entry.get("selected_question_ids", []):
                skipped_by_q[qid].append(entry)
            continue
        confirmed_any = False
        skipped_any = False
        for note in entry.get("question_notes", []):
            if note.get("status", entry_status) != "confirmed":
                skipped_any = True
                skipped_by_q[note.get("question_id", "")].append(entry)
                continue
            if note.get("student_ready_status") != "ready":
                skipped_any = True
                skipped_by_q[note.get("question_id", "")].append(entry)
                continue
            bullets = [bullet.strip() for bullet in note.get("summary_bullets", []) if bullet.strip()]
            if not bullets:
                skipped_any = True
                skipped_by_q[note.get("question_id", "")].append(entry)
                continue
            confirmed_any = True
            notes_by_q[note["question_id"]].append(
                {
                    "r_id": entry["r_id"],
                    "transcript_path": entry["transcript_path"],
                    "audio_path": entry.get("audio_path", ""),
                    "confidence": entry.get("confidence", ""),
                    "review_notes": note.get("review_notes", ""),
                    "student_ready_reason": note.get("student_ready_reason", ""),
                    "bullets": bullets,
                }
            )
        if not confirmed_any:
            appendix_entries.append(entry)
        elif skipped_any:
            entry_copy = dict(entry)
            entry_copy["student_not_ready_reason"] = "部分讲解片段未达到学生版正文采用标准。"
            appendix_entries.append(entry_copy)
    skipped_by_q.pop("", None)
    return notes_by_q, appendix_entries, skipped_by_q


def merged_bullets(notes: list[dict[str, Any]]) -> list[str]:
    by_prefix: dict[str, str] = {}
    extras: list[str] = []
    for note in notes:
        for bullet in note["bullets"]:
            bullet = bullet.strip()
            if not bullet:
                continue
            prefix = bullet.split("：", 1)[0] if "：" in bullet else ""
            if prefix in LECTURE_PREFIXES:
                by_prefix.setdefault(prefix, bullet)
            elif bullet not in extras:
                extras.append(bullet)
    merged = [by_prefix[prefix] for prefix in LECTURE_PREFIXES if prefix in by_prefix]
    for bullet in extras:
        if len(merged) >= 6:
            break
        merged.append(bullet)
    return merged


def render_source_summary(notes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for note in notes:
        transcript_name = Path(note["transcript_path"]).name
        audio_name = Path(note["audio_path"]).name if note.get("audio_path") else "缺失录音"
        confidence = note.get("confidence", "")
        parts.append(f"`{transcript_name}`（录音：`{audio_name}`，置信度：{confidence}）")
    return "；".join(parts)


def render_lecture_section(
    question: Question,
    notes: list[dict[str, Any]],
    skipped_sources: list[dict[str, Any]],
) -> str:
    lines = ["### 🎧 讲解"]
    if not notes:
        lines.append("")
        if skipped_sources:
            lines.append("*暂无可靠讲解来源；已有转写因匹配或可读性风险移入文末附录。*")
        else:
            lines.append("*暂无可靠讲解来源。*")
        return "\n".join(lines)

    lines.append("")
    lines.append(
        f"> 来源：{render_source_summary(notes)}；复核状态：学生版已采用；整理方式：讲义式提炼。"
    )
    reasons = sorted({note.get("student_ready_reason", "") for note in notes if note.get("student_ready_reason")})
    if reasons:
        lines.append(f"> 采用依据：{'；'.join(reasons)}")
    lines.append("")
    for bullet in merged_bullets(notes):
        lines.append(f"- {bullet}")
    return "\n".join(lines)


def insert_lecture_sections(
    notes_by_q: dict[str, list[dict[str, Any]]],
    skipped_by_q: dict[str, list[dict[str, Any]]],
) -> str:
    questions = parse_questions()
    qid_by_start = {question.start_line: question.id for question in questions}
    question_by_id = {question.id: question for question in questions}
    source_lines = read_text(SOURCE_MD).splitlines()
    output: list[str] = []
    i = 0
    while i < len(source_lines):
        line_no = i + 1
        if line_no not in qid_by_start:
            output.append(source_lines[i])
            i += 1
            continue

        qid = qid_by_start[line_no]
        question = question_by_id[qid]
        block_lines = source_lines[question.start_line - 1 : question.end_line]
        insert_at = len(block_lines)
        for idx, block_line in enumerate(block_lines):
            if block_line.strip() == "---":
                insert_at = idx
                break
        before = block_lines[:insert_at]
        after = block_lines[insert_at:]
        while before and not before[-1].strip():
            before.pop()
        output.extend(before)
        output.append("")
        output.extend(
            render_lecture_section(
                question,
                notes_by_q.get(qid, []),
                skipped_by_q.get(qid, []),
            ).splitlines()
        )
        output.append("")
        output.extend(after)
        i = question.end_line
    return "\n".join(output).rstrip() + "\n"


def render_appendix(appendix_entries: list[dict[str, Any]], review_data: dict[str, Any]) -> str:
    lines = [
        "",
        "---",
        "",
        "# 附录：未采用讲解来源",
        "",
        "以下转写未插入题目正文，原因是匹配证据不足、内容过短、跨题无法可靠切分，或按学生版严格可靠策略不宜作为正文讲解。",
        "",
    ]
    if not appendix_entries:
        lines.append("无。")
    else:
        seen_r_ids: set[str] = set()
        for entry in appendix_entries:
            if entry["r_id"] in seen_r_ids:
                continue
            seen_r_ids.add(entry["r_id"])
            selected = "、".join(entry.get("selected_question_ids", [])) or "无"
            reason = (
                entry.get("student_not_ready_reason")
                or entry.get("unconfirmed_reason")
                or entry.get("status", "未确认")
            )
            lines.append(f"## {entry['r_id']}")
            lines.append("")
            lines.append(f"- 转写：`{entry['transcript_path']}`")
            lines.append(f"- 录音：`{entry.get('audio_path') or '缺失'}`")
            lines.append(f"- 自动候选：{selected}")
            lines.append(f"- 未插入原因：{reason}")
            lines.append("")

    missing = review_data.get("audio_without_transcript", [])
    lines.extend(["", "# 附录：缺少转写的录音", ""])
    if not missing:
        lines.append("无。")
    else:
        for item in missing:
            lines.append(f"- `{item['audio_path']}`：未发现对应 R 编号转写。")
    return "\n".join(lines).rstrip() + "\n"


def write_student_quality_report(
    review_data: dict[str, Any],
    notes_by_q: dict[str, list[dict[str, Any]]],
    appendix_entries: list[dict[str, Any]],
    skipped_by_q: dict[str, list[dict[str, Any]]],
) -> None:
    questions = load_questions_from_work()
    ready_source_count = sum(len(notes) for notes in notes_by_q.values())
    appendix_r_ids = list(dict.fromkeys(entry["r_id"] for entry in appendix_entries))
    lines = [
        "# 学生版讲解质量报告",
        "",
        "## 汇总",
        "",
        f"- 正文采用讲解来源：{ready_source_count}",
        f"- 正文覆盖题目：{len(notes_by_q)} / {len(questions)}",
        f"- 移入附录转写：{len(appendix_r_ids)}",
        f"- 原始复核条目：{len(review_data.get('entries', []))}",
        "",
        "## 移入附录的转写",
        "",
    ]
    if appendix_entries:
        for entry in appendix_entries:
            reason = (
                entry.get("student_not_ready_reason")
                or entry.get("unconfirmed_reason")
                or entry.get("status", "未确认")
            )
            selected = "、".join(entry.get("selected_question_ids", [])) or "无"
            lines.append(f"- `{entry['r_id']}` -> {selected}：{reason}")
    else:
        lines.append("- 无。")

    lines.extend(["", "## 暂无可靠讲解的题目", ""])
    missing = [question for question in questions if question.id not in notes_by_q]
    if not missing:
        lines.append("- 无。")
    else:
        current_chapter = ""
        for question in missing:
            if question.chapter_title != current_chapter:
                current_chapter = question.chapter_title
                lines.append(f"### {current_chapter}")
                lines.append("")
            skipped_count = len(skipped_by_q.get(question.id, []))
            suffix = "；有转写移入附录" if skipped_count else "；未匹配到可靠转写"
            lines.append(f"- `{question.id}` 第{question.question_index}题：{question_prompt(question)}{suffix}")

    STUDENT_REPORT_MD.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def render(args: argparse.Namespace) -> int:
    del args
    ensure_work_files()
    review_data = read_json(REVIEW_JSON)
    notes_by_q, appendix_entries, skipped_by_q = build_notes_by_question(review_data)
    body = insert_lecture_sections(notes_by_q, skipped_by_q)
    body += render_appendix(appendix_entries, review_data)
    OUTPUT_MD.write_text(body, encoding="utf-8")
    write_student_quality_report(review_data, notes_by_q, appendix_entries, skipped_by_q)
    print(f"Wrote {rel(OUTPUT_MD)}")
    print(f"Wrote {rel(STUDENT_REPORT_MD)}")
    print(f"Questions with reliable lecture notes: {len(notes_by_q)}")
    print(f"Transcript entries in appendix: {len(dict.fromkeys(entry['r_id'] for entry in appendix_entries))}")
    return 0


def ensure_work_files() -> None:
    missing = [path for path in (QUESTIONS_JSON, TRANSCRIPTS_JSON, ALIGNMENT_JSON, REVIEW_JSON) if not path.exists()]
    if missing:
        names = ", ".join(rel(path) for path in missing)
        raise FileNotFoundError(f"Missing work files: {names}. Run prepare first.")


def check(args: argparse.Namespace) -> int:
    del args
    ensure_work_files()
    if not OUTPUT_MD.exists():
        raise FileNotFoundError(f"Missing output Markdown: {rel(OUTPUT_MD)}. Run render first.")

    questions = parse_questions()
    review_data = read_json(REVIEW_JSON)
    notes_by_q, appendix_entries, _ = build_notes_by_question(review_data)
    output = read_text(OUTPUT_MD)
    errors: list[str] = []
    lecture_blocks = re.findall(r"### 🎧 讲解\n(.*?)(?=\n---\n|\Z)", output, flags=re.S)
    lecture_text = "\n".join(lecture_blocks)

    if len(questions) != 115:
        errors.append(f"source question count expected 115, got {len(questions)}")
    if output.count("### 🎧 讲解") != 115:
        errors.append(f"lecture section count expected 115, got {output.count('### 🎧 讲解')}")
    if output.count("### 📘 题目与材料") != 115:
        errors.append("question/material section count changed")
    if output.count("### ✍️ 参考答案") != 115:
        errors.append("answer section count changed")
    if "TODO" in output:
        errors.append("output contains TODO")
    if re.search(r"来源：``|录音：``", output):
        errors.append("output contains empty source code span")
    if "暂无确认讲解" in lecture_text:
        errors.append("lecture placeholder still uses old unconfirmed wording")
    if "本题要处理的是：。" in lecture_text:
        errors.append("lecture contains empty question prompt")
    if "转写中特别提示" in lecture_text:
        errors.append("lecture contains raw transcript prompt wording")
    if "..." in lecture_text:
        errors.append("lecture contains ASCII truncation ellipsis")
    for term in ASR_NOISE_TERMS:
        if term in lecture_text:
            errors.append(f"lecture contains likely ASR noise term: {term}")

    seen_entries: set[str] = set()
    for entry in review_data["entries"]:
        r_id = entry["r_id"]
        if r_id in seen_entries:
            errors.append(f"duplicate review entry: {r_id}")
        seen_entries.add(r_id)
        transcript_path = ROOT / entry["transcript_path"]
        if not transcript_path.exists():
            errors.append(f"missing transcript source: {entry['transcript_path']}")
        audio_path = entry.get("audio_path")
        if audio_path and not (ROOT / audio_path).exists():
            errors.append(f"missing audio source: {audio_path}")

    for qid, notes in notes_by_q.items():
        if not notes:
            continue
        if qid not in {question.id for question in questions}:
            errors.append(f"review references unknown question id: {qid}")
        for note in notes:
            if note.get("confidence") != "high" and not note.get("student_ready_reason", "").startswith("手工复核"):
                errors.append(f"non-high source used without manual review: {note['r_id']} -> {qid}")

    for entry in appendix_entries:
        if entry["r_id"] not in output:
            errors.append(f"appendix transcript missing from output: {entry['r_id']}")

    known_missing = {item["r_id"] for item in review_data.get("audio_without_transcript", [])}
    expected_missing = {"R20240625-014512", "R20240626-064536"}
    unexpected_missing = known_missing - expected_missing
    if unexpected_missing:
        errors.append(f"unexpected missing transcript audio ids: {sorted(unexpected_missing)}")

    if errors:
        print("Check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Check passed.")
    print(f"Reliable lecture questions: {len(notes_by_q)}")
    print(f"Transcript entries in appendix: {len(dict.fromkeys(entry['r_id'] for entry in appendix_entries))}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="generate work files")
    prepare_parser.add_argument(
        "--force-review",
        action="store_true",
        help="overwrite review_summaries.json with a fresh scaffold",
    )
    prepare_parser.set_defaults(func=prepare)

    review_parser = subparsers.add_parser("apply-review", help="apply built-in manual review decisions")
    review_parser.set_defaults(func=apply_manual_review)

    render_parser = subparsers.add_parser("render", help="render final Markdown")
    render_parser.set_defaults(func=render)

    check_parser = subparsers.add_parser("check", help="validate final Markdown")
    check_parser.set_defaults(func=check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - CLI should show concise failures.
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
