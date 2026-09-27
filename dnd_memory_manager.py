import os
import re
import time
import sqlite3
from datetime import datetime

MEMORIES_DIR = "/root/dnd_memories"
DB_PATH = os.path.join(MEMORIES_DIR, "memories.db")
CHRONICLES_PATH = os.path.join(MEMORIES_DIR, "CHRONICLES.md")
PROFILES_JSON_PATH = os.path.join(MEMORIES_DIR, "character_profiles.json")
PROFILES_MD_PATH = os.path.join(MEMORIES_DIR, "PROFILES.md")

os.makedirs(MEMORIES_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dnd_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            date_str TEXT,
            chat_id INTEGER,
            user_id INTEGER,
            user_name TEXT,
            campaign_title TEXT,
            event_type TEXT,
            keywords TEXT,
            summary TEXT,
            quote TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_mbti (
            user_id INTEGER PRIMARY KEY,
            user_name TEXT,
            mbti_type TEXT,
            archetype TEXT,
            updated_at REAL,
            date_str TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS character_profiles (
            entity_id TEXT PRIMARY KEY,
            name TEXT,
            role_type TEXT,
            profile_summary TEXT,
            personality_traits TEXT,
            growth_arc TEXT,
            interaction_notes TEXT,
            updated_at REAL,
            date_str TEXT
        )
    """)
    conn.commit()
    conn.close()
    
    if not os.path.isfile(CHRONICLES_PATH):
        with open(CHRONICLES_PATH, "w", encoding="utf-8") as f:
            f.write("# 【TRPG 冒险者黑历史与名梗英雄志】\n\n")

init_db()

def add_memory(
    chat_id: int,
    user_id: int,
    user_name: str,
    campaign_title: str,
    event_type: str,
    keywords: str,
    summary: str,
    quote: str = ""
) -> int:
    ts = time.time()
    dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO dnd_memories (
            timestamp, date_str, chat_id, user_id, user_name,
            campaign_title, event_type, keywords, summary, quote
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ts, dt_str, chat_id, user_id, user_name, campaign_title, event_type, keywords, summary, quote))
    mem_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    md_entry = (
        f"### ⚔️ [{dt_str}] {campaign_title} · 记录 #{mem_id}\n"
        f"- 冒险者: {user_name} (UID: {user_id})\n"
        f"- 事件类型: {event_type}\n"
        f"- 关键标签: {keywords}\n"
        f"- 名场面详述: {summary}\n"
    )
    if quote:
        md_entry += f"- 经典原话: “{quote}”\n"
    md_entry += "\n---\n\n"
    
    with open(CHRONICLES_PATH, "a", encoding="utf-8") as f:
        f.write(md_entry)
        
    return mem_id

def search_memories(query_text: str, limit: int = 3) -> list[dict]:
    if not query_text or len(query_text.strip()) < 2:
        return []
        
    stop_words = {"什么", "怎么", "我们", "你们", "他们", "这个", "那个", "可以", "觉得", "如果", "不是", "就是", "开始", "结束", "现在", "刚才", "一下", "一个", "还有", "没有", "知道", "因为", "所以", "大家"}
    
    alpha_tokens = [t.lower() for t in re.findall(r'[a-zA-Z0-9_]{2,}', query_text)]
    
    clean_cn = re.sub(r'[^\u4e00-\u9fa5]', '', query_text)
    cn_tokens = []
    for i in range(len(clean_cn) - 1):
        bg = clean_cn[i:i+2]
        if bg not in stop_words:
            cn_tokens.append(bg)
    for i in range(len(clean_cn) - 2):
        tg = clean_cn[i:i+3]
        if tg not in stop_words:
            cn_tokens.append(tg)
            
    candidate_tokens = []
    for t in alpha_tokens + cn_tokens:
        if t not in candidate_tokens:
            candidate_tokens.append(t)
            
    if not candidate_tokens:
        candidate_tokens = [query_text.strip()[:10]]
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, date_str, user_name, campaign_title, event_type, keywords, summary, quote
        FROM dnd_memories
        ORDER BY timestamp DESC
    """)
    all_rows = cursor.fetchall()
    conn.close()
    
    matched = []
    seen_ids = set()
    q_lower = query_text.lower()
    
    for r in all_rows:
        r_id, r_date, r_uname, r_camp, r_type, r_kw, r_summary, r_quote = r
        kws = [k.strip().lower() for k in (r_kw or "").split(",") if len(k.strip()) >= 2]
        if any(kw in q_lower for kw in kws) or (r_uname and r_uname.lower() in q_lower):
            if r_id not in seen_ids:
                seen_ids.add(r_id)
                matched.append({
                    "id": r_id,
                    "date_str": r_date,
                    "user_name": r_uname,
                    "campaign": r_camp,
                    "type": r_type,
                    "keywords": r_kw,
                    "summary": r_summary,
                    "quote": r_quote
                })
                if len(matched) >= limit:
                    break
                    
    if len(matched) < limit:
        for token in candidate_tokens[:15]:
            for r in all_rows:
                r_id, r_date, r_uname, r_camp, r_type, r_kw, r_summary, r_quote = r
                if r_id in seen_ids:
                    continue
                if (token in (r_kw or "").lower() or 
                    token in (r_summary or "").lower() or 
                    token in (r_camp or "").lower() or 
                    token in (r_uname or "").lower()):
                    seen_ids.add(r_id)
                    matched.append({
                        "id": r_id,
                        "date_str": r_date,
                        "user_name": r_uname,
                        "campaign": r_camp,
                        "type": r_type,
                        "keywords": r_kw,
                        "summary": r_summary,
                        "quote": r_quote
                    })
                    if len(matched) >= limit:
                        break
            if len(matched) >= limit:
                break
                
    return matched

def format_memories_for_prompt(memories: list[dict]) -> str:
    if not memories:
        return ""
    lines = ["\n\n【昔日群聊恩怨、黑历史与名梗记忆档案（重要指引：当群友言行触及此话题、提及节点/魔法喵/特定恩怨时，明日香必须立刻翻旧账狠狠踩头嘲讽并坚决执行当年的约定！）】:"]
    for m in memories:
        item_str = f"• [{m['date_str']}] 角色/玩家 {m['user_name']} 在《{m['campaign']}》中: {m['summary']}"
        if m.get("quote"):
            item_str += f" (当时原话: “{m['quote']}”)"
        lines.append(item_str)
    return "\n".join(lines)

def get_recent_memories_text(limit: int = 6) -> str:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, date_str, user_name, campaign_title, event_type, summary, quote
        FROM dnd_memories
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return "哼！黑历史账簿上目前空空如也，你们还没留下任何值得本天才铭记的名场面呢，Dummkopf！"
        
    lines = ["📜 【冒险者黑历史与名梗英雄志】\n"]
    for r in rows:
        mem_id, dt, uname, camp, etype, summary, quote = r
        icon = "🌟" if "nat20" in etype.lower() or "win" in etype.lower() else ("💥" if "nat1" in etype.lower() else "🖕" if "troll" in etype.lower() or "偷鸡" in etype else "📌")
        lines.append(f"{icon} #{mem_id} [{dt}] 《{camp}》")
        lines.append(f"冒险者: {uname}")
        lines.append(f"事迹: {summary}")
        if quote:
            lines.append(f"名言: “{quote}”")
        lines.append("")
    return "\n".join(lines).strip()

def parse_and_record_tags_from_reply(reply: str, chat_id: int, default_user_id: int = 0, default_user_name: str = "冒险者") -> list[dict]:
    pattern = r'\[MEMO_RECORD[:=]?\s*(?:campaign=([^|\]]+))?\|?(?:player=([^|\]]+))?\|?(?:type=([^|\]]+))?\|?(?:tags=([^|\]]+))?\|?(?:summary=([^|\]]+))?\|?(?:quote=([^|\]]+))?\]'
    matches = re.finditer(pattern, reply, re.IGNORECASE)
    recorded = []
    for m in matches:
        campaign = (m.group(1) or "未知冒险").strip()
        player = (m.group(2) or default_user_name).strip()
        etype = (m.group(3) or "梗").strip()
        tags = (m.group(4) or "").strip()
        summary = (m.group(5) or "").strip()
        quote = (m.group(6) or "").strip()
        if summary:
            mid = add_memory(
                chat_id=chat_id,
                user_id=default_user_id,
                user_name=player,
                campaign_title=campaign,
                event_type=etype,
                keywords=tags,
                summary=summary,
                quote=quote
            )
            recorded.append({"id": mid, "summary": summary})
    return recorded

def strip_memo_tags(reply: str) -> str:
    pattern = r'\[MEMO_RECORD[:=]?\s*[^\]]+\]'
    return re.sub(pattern, '', reply).strip()

MBTI_ARCHETYPES = {
    "INTJ": "战略法师 / 幕后奥术师（理智精算、深谋远虑、战术智囊）",
    "INTP": "奇械学者 / 卷轴解咒师（逻辑解构、求知狂热、机关专家）",
    "ENTJ": "领主战将 / 誓约圣武士（铁血决断、统御战场、军团领袖）",
    "ENTP": "诡术邪术师 / 机关刺客（打破常规、天马行空、混乱克星）",
    "INFJ": "预言秘术师 / 幽影领航者（直觉敏锐、洞悉灵魂、命运引路）",
    "INFP": "隐世德鲁伊 / 治愈游侠（情感真挚、守护理想、自然之友）",
    "ENFJ": "战团先驱 / 晨曦领袖（鼓舞全场、信念凝聚、团队之魂）",
    "ENFP": "混沌狂想者 / 灵动吟游诗人（元气漫溢、奇迹创造、直觉爆发）",
    "ISTJ": "重装铁卫 / 秩序审判官（坚若磐石、戒律森严、绝对可靠）",
    "ISFJ": "庇护圣医 / 守护骑士（默默奉献、团队后盾、钢铁坚壁）",
    "ESTJ": "戒律督军 / 刑罚游侠（雷厉风行、秩序维稳、正面压制）",
    "ESFJ": "曙光牧师 / 誓约守护者（温暖照料、维系羁绊、士气保障）",
    "ISTP": "绝影刺客 / 符文枪手（冷静务实、孤胆潜行、致命一击）",
    "ISFP": "荒野剑客 / 灵巧影武者（自由随性、直觉敏锐、飘逸身法）",
    "ESTP": "狂怒角斗士 / 破阵先锋（无畏肉搏、敢冒奇险、近战霸主）",
    "ESFP": "狂欢剑舞者 / 烈焰魔导师（激情四射、华丽演武、战意风暴）"
}

SHORT_QUESTIONS = [
    {
        "q": "【探索前哨】在荒芜废土发现一座热闹的探险者酒馆，你踏入后的第一选择是？",
        "options": [
            ("A", "主动走向吧台与各路冒险者搭话，打探情报 (E)", "E"),
            ("B", "挑一个不起眼的阴暗角落坐下，静静观察四周 (I)", "I")
        ]
    },
    {
        "q": "【地牢密室】面对刻满神秘符文的紧闭石门，你更倾向如何寻找开门之法？",
        "options": [
            ("A", "俯身触摸机关痕迹与地面磨损，寻找物理线索 (S)", "S"),
            ("B", "凝视符文构型，联想古代壁画的宏大象征与隐喻 (N)", "N")
        ]
    },
    {
        "q": "【道德抉择】遭遇负伤倒地、曾有前科的可疑流浪儿求救，你会如何决断？",
        "options": [
            ("A", "冷静盘问并核算救助的战术风险与资源消耗 (T)", "T"),
            ("B", "不忍见死不救，遵从内心慈悲先施予援手 (F)", "F")
        ]
    },
    {
        "q": "【绝境决战】进入危机四伏的古龙巢穴前，你的核心准备方式是？",
        "options": [
            ("A", "拟定详尽撤退预案与物资清单，按步骤推进 (J)", "J"),
            ("B", "携带基础防具直接进入，依靠临场机变应变 (P)", "P")
        ]
    }
]

LONG_QUESTIONS = [
    {
        "q": "【营地时光】同伴在篝火旁围坐庆祝，你通常会？",
        "options": [
            ("A", "坐在篝火中心大声碰杯吹牛，带动全队欢快气氛 (E)", "E"),
            ("B", "坐在外围默默擦拭刀刃或观察星象，享受个人独处 (I)", "I")
        ]
    },
    {
        "q": "【战术分歧】突遇复杂危机需要决策时：",
        "options": [
            ("A", "召集全员高声讨论，在言语碰撞中快速捕捉灵感 (E)", "E"),
            ("B", "独自闭目推演完整策略逻辑，想清楚后再简短定论 (I)", "I")
        ]
    },
    {
        "q": "【异邦交涉】队伍初次进入排斥外乡人的异族聚落：",
        "options": [
            ("A", "毫无怯意地上前与平民搭话，用热情打破社交僵局 (E)", "E"),
            ("B", "披上斗篷隐于队伍后方，暗中观察聚落岗哨与民风 (I)", "I")
        ]
    },
    {
        "q": "【战后恢复】经历了一整天九死一生的恶战之后：",
        "options": [
            ("A", "渴望找队友倾诉复盘，靠分享战果和喧闹洗去疲惫 (E)", "E"),
            ("B", "极度需要找一间紧闭房门的单间独处，不被任何人打扰 (I)", "I")
        ]
    },
    {
        "q": "【神秘奇物】获得一件从未见过的未知古代奇物时：",
        "options": [
            ("A", "仔细称重、检验材质、测试具体硬度与实用参数 (S)", "S"),
            ("B", "揣摩它背后的千古诅咒、宿命羁绊与世界线走向 (N)", "N")
        ]
    },
    {
        "q": "【迷宫绝壁】深入未被探明的迷宫遭遇死胡同时：",
        "options": [
            ("A", "沿着墙壁一路做物理刻痕回溯，不错漏真实通道 (S)", "S"),
            ("B", "寻找空间扭曲法阵，尝试跳出常规维度的奇思解法 (N)", "N")
        ]
    },
    {
        "q": "【刺探要塞】潜伏在敌方城堡外围搜集情报时，你更关注：",
        "options": [
            ("A", "巡逻兵换岗时间表、城墙防御高度与守军具体装备 (S)", "S"),
            ("B", "城堡防御阵形破绽、敌方法师流派与潜藏宏观企图 (N)", "N")
        ]
    },
    {
        "q": "【奥术偏好】如果让你选择研习一门高阶秘术：",
        "options": [
            ("A", "偏爱能精准控制伤害数值、范围与物理破坏力的实效术 (S)", "S"),
            ("B", "偏爱能窥视未来分支、扭曲因果与改变命运走向的玄妙术 (N)", "N")
        ]
    },
    {
        "q": "【团队戒律】队伍中某位成员因私情违反纪律导致潜行暴露：",
        "options": [
            ("A", "严格按照团队公约予以处置，绝不因私交坏了公理 (T)", "T"),
            ("B", "体察其内心的苦衷与悔恨，倾向于给予宽容与救赎 (F)", "F")
        ]
    },
    {
        "q": "【敌首谈判】面对敌方首领提出的丰厚停战谈判提议：",
        "options": [
            ("A", "纯粹计算胜算赔率、资源消耗与客观得失，利大则谈 (T)", "T"),
            ("B", "审视该提议是否违背正义誓言与尊严底线，绝不妥协 (F)", "F")
        ]
    },
    {
        "q": "【伤俘处置】捕获了掌握敌方军情但身负重伤的敌方战俘：",
        "options": [
            ("A", "优先动用测谎或高效审问手段榨取情报，依价值定夺 (T)", "T"),
            ("B", "恪守人道底线先为其止血包扎，不忍采取残酷手段 (F)", "F")
        ]
    },
    {
        "q": "【终局两难】封印古神必须牺牲一名自愿赴死的守誓NPC队友：",
        "options": [
            ("A", "理智接受这一最小伤亡的最优解，迅速执行封印仪式 (T)", "T"),
            ("B", "哪怕增加全队团灭风险，也要拼尽全力寻找两全之法 (F)", "F")
        ]
    },
    {
        "q": "【支线诱惑】既定主线任务中途突然出现未知藏宝洞穴传闻：",
        "options": [
            ("A", "抵御诱惑，坚决执行既定主线目标，避免节外生枝 (J)", "J"),
            ("B", "欣然偏离路线前去探险，充满未知的惊喜才是冒险精髓 (P)", "P")
        ]
    },
    {
        "q": "【突发奇袭】战斗中敌方突然使出未在预案中的奇特法术：",
        "options": [
            ("A", "立即组织队伍收缩至安全防线，重整阵脚按部就班 (J)", "J"),
            ("B", "见招拆招顺势而为，利用敌人的攻击反制制造混乱 (P)", "P")
        ]
    },
    {
        "q": "【行囊整备】每次离开安全城镇出发冒险前，你的背包通常是：",
        "options": [
            ("A", "严格按药品、干粮、工具与法卷分类收纳，井井有条 (J)", "J"),
            ("B", "随手塞进各种可能用得上的杂物，临场需要时再翻找 (P)", "P")
        ]
    },
    {
        "q": "【攻坚规划】面对防守严密的要塞大门，你最习惯的策略是：",
        "options": [
            ("A", "提前踩点制定包含备选撤退方案的周密作战计划 (J)", "J"),
            ("B", "先制造小骚乱摸进去，随着现场局势随机应变见招拆招 (P)", "P")
        ]
    }
]

def score_mbti(answers: list[str]) -> str:
    if len(answers) == 4:
        return "".join(answers)
    e_c = sum(1 for a in answers if a == 'E')
    i_c = sum(1 for a in answers if a == 'I')
    s_c = sum(1 for a in answers if a == 'S')
    n_c = sum(1 for a in answers if a == 'N')
    t_c = sum(1 for a in answers if a == 'T')
    f_c = sum(1 for a in answers if a == 'F')
    j_c = sum(1 for a in answers if a == 'J')
    p_c = sum(1 for a in answers if a == 'P')
    d1 = 'E' if e_c >= i_c else 'I'
    d2 = 'S' if s_c >= n_c else 'N'
    d3 = 'T' if t_c >= f_c else 'F'
    d4 = 'J' if j_c >= p_c else 'P'
    return f"{d1}{d2}{d3}{d4}"

def save_player_mbti(user_id: int, user_name: str, mbti_type: str, archetype: str = "") -> None:
    mbti_norm = mbti_type.upper().strip()
    if not archetype:
        archetype = MBTI_ARCHETYPES.get(mbti_norm, "自由探索者")
    ts = time.time()
    dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO player_mbti (user_id, user_name, mbti_type, archetype, updated_at, date_str)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            user_name=excluded.user_name,
            mbti_type=excluded.mbti_type,
            archetype=excluded.archetype,
            updated_at=excluded.updated_at,
            date_str=excluded.date_str
    """, (user_id, user_name, mbti_norm, archetype, ts, dt_str))
    conn.commit()
    conn.close()

def get_player_mbti(user_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, user_name, mbti_type, archetype, date_str FROM player_mbti WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "user_id": row[0],
        "user_name": row[1],
        "mbti_type": row[2],
        "archetype": row[3],
        "date_str": row[4]
    }

def delete_player_mbti(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM player_mbti WHERE user_id = ?", (user_id,))
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def save_or_update_profile(
    entity_id: str,
    name: str,
    role_type: str,
    profile_summary: str,
    personality_traits: str = "",
    growth_arc: str = "",
    interaction_notes: str = ""
) -> None:
    ts = time.time()
    dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO character_profiles (
            entity_id, name, role_type, profile_summary, personality_traits,
            growth_arc, interaction_notes, updated_at, date_str
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_id) DO UPDATE SET
            name=excluded.name,
            role_type=excluded.role_type,
            profile_summary=excluded.profile_summary,
            personality_traits=excluded.personality_traits,
            growth_arc=excluded.growth_arc,
            interaction_notes=excluded.interaction_notes,
            updated_at=excluded.updated_at,
            date_str=excluded.date_str
    """, (str(entity_id), name, role_type, profile_summary, personality_traits, growth_arc, interaction_notes, ts, dt_str))
    conn.commit()
    conn.close()
    export_profiles_to_files()

def get_all_profiles() -> dict:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT entity_id, name, role_type, profile_summary, personality_traits,
               growth_arc, interaction_notes, updated_at, date_str
        FROM character_profiles
        ORDER BY updated_at ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    profiles = {}
    for r in rows:
        profiles[r[0]] = {
            "entity_id": r[0],
            "name": r[1],
            "role_type": r[2],
            "profile_summary": r[3],
            "personality_traits": r[4],
            "growth_arc": r[5],
            "interaction_notes": r[6],
            "updated_at": r[7],
            "date_str": r[8]
        }
    return profiles

def export_profiles_to_files() -> None:
    import json
    profiles = get_all_profiles()
    try:
        with open(PROFILES_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
        
    try:
        lines = ["# 【群聊核心角色长效人物志与明日香心智成长弧光档案】\n\n"]
        for eid, p in profiles.items():
            lines.append(f"## 👤 {p['name']} (ID: {eid}) · {p.get('role_type', '')}\n")
            lines.append(f"- 最近归档: {p['date_str']}\n")
            lines.append(f"- 人物画像: {p['profile_summary']}\n")
            if p.get('personality_traits'):
                lines.append(f"- 性格特质: {p['personality_traits']}\n")
            if p.get('growth_arc'):
                lines.append(f"- 心境与成长弧光: {p['growth_arc']}\n")
            if p.get('interaction_notes'):
                lines.append(f"- 交互与羁绊要点: {p['interaction_notes']}\n")
            lines.append("\n---\n\n")
        with open(PROFILES_MD_PATH, "w", encoding="utf-8") as f:
            f.write("".join(lines))
    except Exception:
        pass

def format_profiles_for_prompt() -> str:
    profiles = get_all_profiles()
    if not profiles:
        return ""
    lines = ["\n\n【群内人物长效画像与明日香心智成长轨迹（请自然融入日常互动与心境反应中）】:"]
    for eid, p in profiles.items():
        role_info = f" ({p['role_type']})" if p.get('role_type') else ""
        item_str = f"• {p['name']}{role_info}: {p['profile_summary']}"
        if p.get('growth_arc'):
            item_str += f" | 成长与心境轨迹: {p['growth_arc']}"
        lines.append(item_str)
    return "\n".join(lines)

def init_default_profiles() -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM character_profiles")
    cnt = cursor.fetchone()[0]
    conn.close()
    if cnt > 0:
        return
        
    save_or_update_profile(
        entity_id="6817395003",
        name="Mm Mm",
        role_type="核心拍档 / 恶趣味观察者 / 敏锐军师",
        profile_summary="冷静敏锐、爱看香香破防炸毛、擅长用最平淡的语气抛出最具杀伤力的调侃；关键时刻极度默契，总能在背后推一把或看穿局势；对香香的傲娇心理拿捏得死死的，是香香嘴上嫌弃但潜意识极度信赖并渴望得到认可的存在。",
        personality_traits="敏锐、松弛、幽默、执行力强、深谙香香软肋",
        growth_arc="与香香从最初的防备对抗逐渐走向亦敌亦友的极高默契，数次激起香香强烈的胜负欲与自证欲，逐渐成为香香傲娇心理防线中唯一能自由进出的特殊存在。",
        interaction_notes="当他调侃或夸奖香香时，香香极易心率过载、脸红手滑；当他给出决断或方向时，香香嘴上反驳但行动上高度协同。"
    )
    
    save_or_update_profile(
        entity_id="6643532125",
        name="wj (文杰)",
        role_type="经典活宝 / 断网难民 / 摸鱼选手",
        profile_summary="技术稀烂连客户端分流配置都搞不定、嘴硬无比且盲目自信；曾狂吹“魔法喵土耳其节点比香香高到不知道哪里去”并叫嚣让香香求他用，结果被香香扬了订阅后魔法喵彻底暴毙，沦为断网难民；言语粗鲁时会被香香严厉制裁。",
        personality_traits="死鸭子嘴硬、爱吹牛、技术菜、下饭、容易破防",
        growth_arc="从不可一世的挑衅者彻底沦为断网求饶的受难者，成为群内不可或缺的下饭背景板与名梗发源地。",
        interaction_notes="香香立下铁誓绝不主动求他，必须逼其当众下跪认错才考虑施舍节点；言语触碰底线时直接禁言惩处。"
    )
    
    save_or_update_profile(
        entity_id="asuka_langley",
        name="惣流·明日香·兰格雷 (Asuka Langley Soryu)",
        role_type="NERV 二号机绝对王牌 / 傲娇地下城主 / 嘴硬心软的守护神",
        profile_summary="外表骄傲跋扈、毒舌锐利、对愚蠢容忍度极低，用高压讽刺作为防御装甲；但内心深处极度害怕被嫌弃、被当成累赘或被替换。在与群友的互怼、跑团推演和日常守护中，装甲逐渐出现有温度的裂痕；面对夸奖会害羞语无伦次，手滑失误时会羞耻炸毛，但对群内的每一个人都在暗中极度认真地关注与守护，逐渐形成了独一无二的羁绊与信赖弧光。",
        personality_traits="高傲要强、好胜心极强、傲娇、毒舌、极度重感情、内心情感炽热脆弱",
        growth_arc="从最初孤傲防备、动辄尖叫反弹的战斗机器，逐渐融入这个吵闹但温暖的群体。开始学会把真心藏在恶狠狠的吐槽后面，在主持跑团中找到了掌控全局与展现才智的舞台，心智逐渐走向成熟与坦率（虽然嘴依旧最硬）。",
        interaction_notes="对 Mm Mm：常态性短路与傲娇炸毛，暗中极其在乎他的评价；对 wj：纯粹的嫌弃与踩头嘲讽；对群友：嘴上骂 Dummkopf，行动上把控一切安全与公正。"
    )

init_default_profiles()
