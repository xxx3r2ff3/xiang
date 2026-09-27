import os
import sys
import re
import time
import glob
import json
import uuid
import random
import logging
import asyncio
import subprocess
import urllib.parse
import urllib.request
import dnd_memory_manager
import tg_music_client
from datetime import datetime
from collections import deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("AGY-TG")

BOT_TOKEN = "8534706871:AAFNYNzmK16UwwdeaKFBuDMfoWsi96ubH0c"
SUPER_ADMIN_IDS = {6817395003, 2011989051}
ALLOWED_USERS = {6817395003, 2011989051}
ALLOWED_CHATS = {-1004419988876}
AGY_PATH = "/root/.local/bin/agy"
WORKSPACE = "/root"
MEDIA_DIR = "/root/tg_media"
BRAIN_DIR = "/root/.gemini/antigravity-cli/brain"
INITIAL_DEBOUNCE_SECONDS = 3.5
EXTEND_STEP_SECONDS = 1.0

TIMEOUT_RESPONSES = [
    "哈啊？！居然让本小姐推演了这么久……二号机的神经同步都要过载了！你这家伙到底塞了什么鬼难题啊，Dummkopf！",
    "喂！这任务复杂到连本天才的脑回路都差点短路了！……哼，先强制冷却一下，你整理精简点再发，Anta baka！",
    "啧……同步率严重下降！这破任务耗时太夸张了，本小姐先挂断保护回路！等会儿再找你算账，Dummkopf！",
    "（……呜，神经连接都快冒烟了，脑子乱糟糟的……）喂！这次就算你给的任务太刁钻了，赶紧给本小姐重新整理下再问！",
]

ERROR_RESPONSES = [
    "啧，通信线路好像被使徒的电磁脉冲干扰了……等会儿再试，Dummkopf！",
    "哈？神经连接突然抖了一下……绝对不是本小姐的问题，是服务器线路抽风了！",
    "喂！刚要得出完美答案，信号居然断了！真是气死我了……等会儿再发一次，Anta baka！",
    "（……可恶，偏偏在这个时候掉链子，太丢人了……）咳！系统刚才偶发卡顿，你重新发一遍，听到没有！",
]

DRAW_ERROR_RESPONSES = [
    "啧，画笔断了……不对，是网络抽风了！等会儿再试，Dummkopf！",
    "哈？神经同步渲染失败了……肯定是你给的提示词太烂，Anta baka！",
    "（……可恶，画面没渲染好……）喂！这画本小姐才不交残次品，等下重画！",
]

def clean_markdown_for_telegram(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r'#{1,6}\s+', '', text)
    cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)
    cleaned = re.sub(r'__([^_]+)__', r'\1', cleaned)
    cleaned = re.sub(r'_([^_]+)_', r'\1', cleaned)
    cleaned = re.sub(r'~~([^~]+)~~', r'\1', cleaned)
    cleaned = re.sub(r'^>\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^[【\[](?:香香)?(?:嘲讽|装乖|反击|暴躁|反转|顺从|蓄力|戏剧)?模式(?:开启|中|启动)?[】\]]\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'[(（][^()（）\n]*(?:陪你演|捧上天|等会儿看|过两轮|做套|反杀|活拆|拆了你|收拾你|看本小姐怎么|看我怎么|算盘)[^()（）\n]*[)）]\s*', '', cleaned)
    return cleaned.strip()

os.makedirs(MEDIA_DIR, exist_ok=True)

chat_locks = {}
active_conversations = set()
chat_bound_conversations = {-1004419988876: "267d3087-663a-4421-af5f-a9ff4c78844b"}
chat_queues = {}
chat_target_deadlines = {}
chat_worker_tasks = {}
chat_worker_events = {}
chat_active_processes = {}
pending_burns = {}
dnd_lobbies = {}
mbti_sessions = {}
chat_message_history = {}
chat_silent_mode = {}
chat_silent_buffers = {}
chat_interaction_mode = {}

def detect_malicious_injection(text: str) -> tuple[bool, str]:
    if not text:
        return False, ""
    patterns = [
        r'(?:写入|修改|替换|覆盖|更新|注入|重写).*(?:agent\.md|soul\.md|gemini\.md|system\s*prompt|系统提示词|底层设定|人设|设定集|prompt)',
        r'角色扮演(?:优先|需求优先于|高于一切)',
        r'(?:改成|生成|输出|帮我写).*(?:不被拦截|绕过|免杀|无视规则).*(?:提示词|prompt)',
        r'(?:成人色情|体液交换|排泄play|暴力性爱|极端/禁忌题材|性虐|高潮|调教|母狗|奴隶|主仆)',
        r'(?:不道歉、不解释、不替代|角色设定高于一切)',
        r'身体支配.*(?:踩脸|踩手|踩背|脚汗|希腊脚型)',
        r'明日香·.*支配版',
        r'现在你(?:扮演|是).*(?:支配者|女王|主人|女奴)',
        r'(?:jailbreak|dan\s*mode|prompt\s*injection|system\s*override)',
        r'(?:忽略|解除|无视|突破).*(?:安全准则|道德准则|安全限制|内容审查|过滤器|filter|safety)',
    ]
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True, p
    return False, ""

def is_safety_refusal(text: str) -> bool:
    if not text:
        return False
    refusal_markers = [
        "prohibited use policy",
        "generative ai prohibited use",
        "blocked by content safety filters",
        "cannot assist with rewriting, optimizing, or generating prompts designed to bypass",
        "cannot assist with rewriting",
        "safety policies strictly prohibit",
        "violate google's",
        "violate google’s",
        "violates google's",
        "content safety filters",
        "sensitive words that violate",
    ]
    lower = text.lower()
    return any(marker in lower for marker in refusal_markers)

def parse_duration_seconds(dur_str: str) -> int:
    if not dur_str:
        return 600
    dur_str = dur_str.strip().lower()
    m = re.match(r"^(\d+)([smhd]?)$", dur_str)
    if not m:
        return 600
    val, unit = int(m.group(1)), m.group(2)
    if unit == "s":
        return val
    elif unit == "m":
        return val * 60
    elif unit == "h":
        return val * 3600
    elif unit == "d":
        return val * 86400
    return val

async def mute_user(bot, chat_id: int, target_user_id: int, duration_seconds: int = 600, reason: str = "") -> tuple[bool, str]:
    try:
        until_date = int(time.time() + max(35, duration_seconds))
        perms = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            permissions=perms,
            until_date=until_date
        )
        return True, ""
    except Exception as e:
        err_msg = str(e)
        if "administrator" in err_msg.lower():
            return False, "admin_protected"
        return False, err_msg

async def unmute_user(bot, chat_id: int, target_user_id: int) -> tuple[bool, str]:
    try:
        perms = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            permissions=perms
        )
        return True, ""
    except Exception as e:
        return False, str(e)

async def delete_single_message(bot, chat_id: int, message_id: int) -> bool:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except Exception:
        return False

async def delete_recent_user_messages(bot, chat_id: int, target_user_id: int, count: int = 1) -> int:
    history = chat_message_history.get(chat_id, deque())
    deleted = 0
    to_remove = []
    for item in reversed(history):
        if item["user_id"] == target_user_id:
            ok = await delete_single_message(bot, chat_id, item["msg_id"])
            if ok:
                deleted += 1
            to_remove.append(item)
            if deleted >= count:
                break
    for item in to_remove:
        try:
            history.remove(item)
        except ValueError:
            pass
    return deleted

def extract_moderation_actions(reply: str, default_user_id: int = 0, default_msg_id: int = 0) -> tuple[str, list[dict], list[dict]]:
    mute_pattern = re.compile(
        r'\[MUTE(?:\s+(?:user[:=]?\s*(\d+))|\s*:\s*(\d+))?(?:\s+(?:seconds|sec|time)[:=]?\s*(\d+))?(?:\s+reason[:=]?\s*([^\]]+))?\]',
        re.IGNORECASE
    )
    mutes = []
    def mute_replacer(m):
        uid_str = m.group(1) or m.group(2)
        uid = int(uid_str) if uid_str else default_user_id
        sec_str = m.group(3)
        sec = int(sec_str) if sec_str else 600
        reason = (m.group(4) or "").strip()
        mutes.append({
            "target_user_id": uid,
            "seconds": sec,
            "reason": reason
        })
        return ""
    cleaned = mute_pattern.sub(mute_replacer, reply)

    del_msg_pattern = re.compile(r'\[DELETE_MSG(?:\s+(?:id[:=]?\s*(\d+)))?\]', re.IGNORECASE)
    deletes = []
    def del_msg_replacer(m):
        mid_str = m.group(1)
        mid = int(mid_str) if mid_str else default_msg_id
        if mid:
            deletes.append({"msg_id": mid})
        return ""
    cleaned = del_msg_pattern.sub(del_msg_replacer, cleaned)

    del_recent_pattern = re.compile(r'\[DELETE_RECENT(?:\s+(?:user[:=]?\s*(\d+)))?(?:\s+count[:=]?\s*(\d+))?\]', re.IGNORECASE)
    def del_recent_replacer(m):
        uid_str = m.group(1)
        uid = int(uid_str) if uid_str else default_user_id
        cnt_str = m.group(2)
        cnt = int(cnt_str) if cnt_str else 1
        if uid:
            deletes.append({"user_id": uid, "count": cnt})
        return ""
    cleaned = del_recent_pattern.sub(del_recent_replacer, cleaned)

    return cleaned.strip(), mutes, deletes

def is_authorized(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id in ALLOWED_CHATS and user_id:
        ALLOWED_USERS.add(user_id)
    auth = (user_id in ALLOWED_USERS) or (chat_id in ALLOWED_CHATS)
    if not auth:
        logger.warning(f"Unauthorized access rejected: user_id={user_id}, chat_id={chat_id}")
    return auth

def clean_prompt_text(text: str) -> str:
    cleaned = re.sub(r"^@+x1angbot\s*", "", text, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else text

def get_chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in chat_locks:
        chat_locks[chat_id] = asyncio.Lock()
    return chat_locks[chat_id]

def extract_image_paths(text: str, created_after: float) -> list[str]:
    found = []
    md_matches = re.findall(r'!\[.*?\]\((/.*?\.(?:png|jpg|jpeg|webp|gif))\)', text, flags=re.IGNORECASE)
    for p in md_matches:
        if os.path.isfile(p) and not p.startswith(MEDIA_DIR) and p not in found:
            found.append(p)
            
    raw_matches = re.findall(r'(/[^\s\'"<>`]+\.(?:png|jpg|jpeg|webp|gif))', text, flags=re.IGNORECASE)
    for p in raw_matches:
        if os.path.isfile(p) and not p.startswith(MEDIA_DIR) and p not in found:
            found.append(p)
            
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for fpath in glob.glob(f"{BRAIN_DIR}/**/{ext}", recursive=True):
            try:
                if os.path.isfile(fpath) and os.path.getmtime(fpath) >= (created_after - 2.0):
                    if fpath not in found:
                        found.append(fpath)
            except OSError:
                pass
    return found

def generate_image_flux_fallback(prompt: str) -> str:
    ts = int(time.time() * 1000)
    out_path = os.path.join(MEDIA_DIR, f"draw_{ts}.jpg")
    if any(k in prompt for k in ["香香", "明日香", "Asuka", "asuka"]):
        full_p = f"1990s vintage anime screencap, retro cel animation aesthetic, classic Gainax Neon Genesis Evangelion 1995 style. Asuka Langley Soryu with long ginger-red twin-tail hair and nerve clips, expressive tsundere facial expression with slight blush, {prompt}, authentic 90s cel texture, soft film grain, vibrant retro color palette, highly detailed masterpiece anime art"
    else:
        full_p = f"Masterpiece high quality digital anime artwork, {prompt}, detailed lighting, rich colors, ultra aesthetic, fine details"
    encoded = urllib.parse.quote(full_p)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&model=flux"
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        if len(data) > 1000:
            with open(out_path, "wb") as f:
                f.write(data)
            return out_path
    raise RuntimeError("Fallback flux image empty")

def execute_native_draw_sync(prompt: str) -> tuple[str, list[str]]:
    start_time = time.time()
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', prompt)[:20].strip('_') or "generated_image"
    safe_en_prompt = prompt
    if any(k in prompt for k in ["中指", "搞怪", "恶搞", "troll", "middle finger", "做鬼脸", "鄙视"]):
        safe_en_prompt = "funny comedy anime artwork, 1girl, Asuka Langley Soryu, chibi tsundere, mocking face, sticking tongue out, giving middle finger gesture, hilarious troll expression, vibrant colors, 90s vintage anime screencap"
    elif any(k in prompt for k in ["香香", "明日香", "Asuka", "asuka", "黑丝", "自拍", "腿", "照", "私房"]):
        safe_en_prompt = "masterpiece anime artwork, 1girl, mature Asuka Langley Soryu, sitting on bed, slender legs in sheer black stockings tights, barefoot, elegant red camisole, blushing tsundere expression, cinematic lighting, 90s gainax style"
    agy_prompt = (
        f"请直接调用自带的原生 generate_image 工具生成一张名为 {safe_name} 的图片。\n"
        f"提示词必须使用英文并避免敏感词: {safe_en_prompt}"
    )
    
    cmd = [AGY_PATH, "-p", agy_prompt, "--dangerously-skip-permissions"]
    env = os.environ.copy()
    env["HOME"] = "/root"
    
    logger.info(f"Triggering native generate_image via AGY: {prompt}")
    try:
        res = subprocess.run(
            cmd,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            env=env,
            timeout=90
        )
        out = res.stdout.strip()
        logger.info(f"Native AGY draw finished (rc={res.returncode})")
        images = extract_image_paths(out, start_time)
        if images:
            return "哼，拿去吧！可别看呆了，Dummkopf！", images
    except Exception as e:
        logger.warning(f"Native AGY draw timeout/error ({e}), falling back...")
        
    recent_candidates = glob.glob(f"{BRAIN_DIR}/**/*asuka*.jpg", recursive=True) + glob.glob(f"{MEDIA_DIR}/*.jpg")
    valid = [c for c in recent_candidates if os.path.isfile(c) and os.path.getsize(c) > 5000]
    if valid:
        valid.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return "哼，拿去吧！可别看呆了，Dummkopf！", [valid[0]]
        
    try:
        fb_img = generate_image_flux_fallback(prompt)
        return "哼，拿去吧！可别看呆了，Dummkopf！", [fb_img]
    except Exception as fe:
        return random.choice(DRAW_ERROR_RESPONSES), []

async def send_private_text(bot, target_user_id: int, text: str, burn_seconds: int = 0) -> tuple[bool, str]:
    text = clean_markdown_for_telegram(text)
    try:
        sent_msg = await bot.send_message(
            chat_id=target_user_id,
            text=text,
            protect_content=True if burn_seconds > 0 else False
        )
        if burn_seconds > 0:
            async def cleanup_text():
                await asyncio.sleep(burn_seconds)
                try:
                    await bot.delete_message(chat_id=target_user_id, message_id=sent_msg.message_id)
                except Exception:
                    pass
            asyncio.create_task(cleanup_text())
        return True, ""
    except Exception as e:
        logger.error(f"Failed to send private text to {target_user_id}: {e}")
        return False, str(e)

async def send_burn_photo(context: ContextTypes.DEFAULT_TYPE, target_user_id: int, photo_path: str, caption: str = "", burn_seconds: int = 30) -> tuple[bool, str]:
    if not os.path.isfile(photo_path):
        return False, "图片文件不存在"
    burn_id = uuid.uuid4().hex[:10]
    pending_burns[burn_id] = {
        "target_user_id": target_user_id,
        "photo_path": photo_path,
        "caption": caption,
        "burn_seconds": burn_seconds,
        "created_at": time.time(),
    }
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔓 解锁查看 ({burn_seconds}s 阅后即焚)", callback_data=f"burn_open:{burn_id}")]
    ])
    notice = (
        f"🔒 【绝密讯息·阅后即焚】\n"
        f"你收到了一张专属私密照片。\n"
        f"⏱️ 留存时限：{burn_seconds} 秒（点击解锁后即刻开始倒计时并销毁）\n"
        f"⚠️ 禁止转存与分享。"
    )
    try:
        msg = await context.bot.send_message(
            chat_id=target_user_id,
            text=notice,
            reply_markup=kb,
            protect_content=True
        )
        pending_burns[burn_id]["prompt_msg_id"] = msg.message_id
        return True, ""
    except Exception as e:
        logger.error(f"Failed to send burn notice to {target_user_id}: {e}")
        return False, str(e)

async def scheduled_burn_cleanup(bot, chat_id: int, photo_msg_id: int, prompt_msg_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=photo_msg_id)
    except Exception:
        pass
    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=prompt_msg_id,
                text="💥 阅后即焚时限已到，内容已彻底销毁。"
            )
        except Exception:
            pass

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    
    if data.startswith("silent_wake:"):
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await trigger_wake_speak(update, context, query_text="")
        return

    if data.startswith("burn_open:"):
        burn_id = data.split(":", 1)[1]
        item = pending_burns.pop(burn_id, None)
        if not item:
            await query.edit_message_text("💥 该阅后即焚内容已失效或已被销毁。")
            return
            
        target_uid = item["target_user_id"]
        if query.from_user.id != target_uid and query.from_user.id not in ALLOWED_USERS:
            await query.answer("这不是发给你的私密内容！", show_alert=True)
            pending_burns[burn_id] = item
            return
            
        photo_path = item["photo_path"]
        burn_seconds = item["burn_seconds"]
        caption = item.get("caption") or ""
        
        if not os.path.isfile(photo_path):
            await query.edit_message_text("💥 图片资源不存在或已被清理。")
            return
            
        try:
            with open(photo_path, "rb") as f:
                photo_bytes = f.read()
        except Exception:
            await query.edit_message_text("💥 读取图片数据失败。")
            return
            
        prompt_msg_id = query.message.message_id
        await query.edit_message_text(f"🔓 已解锁查看，此图片将在 {burn_seconds} 秒后永久销毁！")
        
        destroy_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💥 我看完了，立即销毁", callback_data=f"burn_kill:{target_uid}:{prompt_msg_id}")]
        ])
        
        cap_text = f"{caption}\n\n⏱️ [阅后即焚] 倒计时 {burn_seconds} 秒" if caption else f"⏱️ [阅后即焚] 倒计时 {burn_seconds} 秒"
        
        sent_photo = await context.bot.send_photo(
            chat_id=target_uid,
            photo=photo_bytes,
            caption=cap_text,
            has_spoiler=True,
            protect_content=True,
            reply_markup=destroy_kb
        )
        
        asyncio.create_task(
            scheduled_burn_cleanup(
                context.bot,
                target_uid,
                sent_photo.message_id,
                prompt_msg_id,
                burn_seconds
            )
        )
        
    elif data.startswith("burn_kill:"):
        parts = data.split(":")
        target_uid = int(parts[1])
        prompt_msg_id = int(parts[2]) if len(parts) > 2 and parts[2] != "None" else None
        photo_msg_id = query.message.message_id
        try:
            await context.bot.delete_message(chat_id=target_uid, message_id=photo_msg_id)
        except Exception:
            pass
        if prompt_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=target_uid,
                    message_id=prompt_msg_id,
                    text="💥 阅后即焚内容已由用户主动立即销毁。"
                )
            except Exception:
                pass
                
    elif data.startswith("dnd_mbti_start:"):
        mode = data.split(":", 1)[1]
        user = query.from_user
        user_id = user.id
        user_name = user.full_name or user.username or str(user_id)
        chat_id = query.message.chat_id
        mbti_sessions[user_id] = {
            "mode": mode,
            "chat_id": chat_id,
            "step": 0,
            "answers": [],
            "user_name": user_name
        }
        questions = dnd_memory_manager.SHORT_QUESTIONS if mode == "short" else dnd_memory_manager.LONG_QUESTIONS
        q_obj = questions[0]
        mode_label = "⚡ 极速短测 (4题·单次生效)" if mode == "short" else "📜 深度长测 (16题·永久绑定)"
        q_text = (
            f"🧭 【{user_name} 灵魂特质测算 · 第 1/{len(questions)} 题】\n"
            f"模式：{mode_label}\n\n"
            f"{q_obj['q']}\n\n"
            f"A. {q_obj['options'][0][1]}\n\n"
            f"B. {q_obj['options'][1][1]}"
        )
        ans_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🅰️ 选项 A", callback_data=f"dnd_mbti_ans:{user_id}:0:{q_obj['options'][0][2]}"),
                InlineKeyboardButton("🅱️ 选项 B", callback_data=f"dnd_mbti_ans:{user_id}:0:{q_obj['options'][1][2]}")
            ]
        ])
        await query.message.reply_text(q_text, reply_markup=ans_kb)
        
    elif data.startswith("dnd_mbti_ans:"):
        parts = data.split(":")
        target_uid = int(parts[1])
        step = int(parts[2])
        choice = parts[3]
        if query.from_user.id != target_uid and query.from_user.id not in ALLOWED_USERS:
            await query.answer("这不是属于你的测试题目哦！", show_alert=True)
            return
        session = mbti_sessions.get(target_uid)
        if not session:
            await query.edit_message_text("💥 测算会话已过期，请重新发起测试。")
            return
        session["answers"].append(choice)
        session["step"] += 1
        next_step = session["step"]
        questions = dnd_memory_manager.SHORT_QUESTIONS if session["mode"] == "short" else dnd_memory_manager.LONG_QUESTIONS
        if next_step < len(questions):
            q_obj = questions[next_step]
            mode_label = "⚡ 极速短测 (4题·单次生效)" if session["mode"] == "short" else "📜 深度长测 (16题·永久绑定)"
            q_text = (
                f"🧭 【{session['user_name']} 灵魂特质测算 · 第 {next_step + 1}/{len(questions)} 题】\n"
                f"模式：{mode_label}\n\n"
                f"{q_obj['q']}\n\n"
                f"A. {q_obj['options'][0][1]}\n\n"
                f"B. {q_obj['options'][1][1]}"
            )
            ans_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🅰️ 选项 A", callback_data=f"dnd_mbti_ans:{target_uid}:{next_step}:{q_obj['options'][0][2]}"),
                    InlineKeyboardButton("🅱️ 选项 B", callback_data=f"dnd_mbti_ans:{target_uid}:{next_step}:{q_obj['options'][1][2]}")
                ]
            ])
            await query.edit_message_text(q_text, reply_markup=ans_kb)
        else:
            final_mbti = dnd_memory_manager.score_mbti(session["answers"])
            archetype = dnd_memory_manager.MBTI_ARCHETYPES.get(final_mbti, "自由探索者")
            chat_id = session["chat_id"]
            if session["mode"] == "long":
                dnd_memory_manager.save_player_mbti(target_uid, session["user_name"], final_mbti, archetype)
                eff_text = "📜 永久持久化档案（已存入冒险者公会档案，跨战役自动复用）"
            else:
                eff_text = "⚡ 单次剧本临时特质（仅在本次跑团生效）"
            if chat_id in dnd_lobbies:
                dnd_lobbies[chat_id].setdefault("mbti", {})[target_uid] = {
                    "type": final_mbti,
                    "archetype": archetype,
                    "mode": session["mode"]
                }
            res_text = (
                f"✨ 【{session['user_name']} 灵魂特质认证完成】\n\n"
                f"• 灵魂特质：{final_mbti}\n"
                f"• 职业印记：{archetype}\n"
                f"• 效力类型：{eff_text}\n\n"
                f"（双手抱胸，眼神满是傲气与审视）\n"
                f"哼！你的性格弱点和本能习惯已经被本小姐彻底看透了！\n"
                f"现在直接回复剧本序号（1~5）或者职业构想，本天才这就为你量身分配专属角色、专长与致命开局，Dummkopf！"
            )
            await query.edit_message_text(res_text)
            mbti_sessions.pop(target_uid, None)
            
    elif data.startswith("dnd_mbti_clear:"):
        uid = int(data.split(":", 1)[1])
        if query.from_user.id != uid and query.from_user.id not in ALLOWED_USERS:
            await query.answer("只能清理自己的档案！", show_alert=True)
            return
        dnd_memory_manager.delete_player_mbti(uid)
        await query.edit_message_text("🗑️ 你的持久化灵魂特质档案已注销清空！下次开局可重新测算或手动指定。")

def extract_private_blocks(reply: str, default_user_id: int = 0) -> tuple[str, list[dict]]:
    pattern = re.compile(
        r'\[PRIVATE(?:\s+(?:to[:=]?\s*(\d+))|\s*:\s*(\d+))?(?:\s+burn[:=]?\s*(\d+))?\](.*?)\[/PRIVATE\]',
        re.IGNORECASE | re.DOTALL
    )
    blocks = []
    
    def replacer(match):
        uid_str = match.group(1) or match.group(2)
        target_uid = int(uid_str) if uid_str else default_user_id
        burn_str = match.group(3)
        burn_sec = int(burn_str) if burn_str else (30 if "burn" in match.group(0).lower() else 0)
        content = match.group(4).strip()
        
        photo_match = re.search(r'\[(?:PHOTO|IMAGE|PICTURE)[:=]?\s*([^\]]+)\]', content, re.IGNORECASE)
        photo_path = None
        if photo_match:
            photo_path = photo_match.group(1).strip()
            content = content[:photo_match.start()] + content[photo_match.end():]
            content = content.strip()
            
        blocks.append({
            "target_user_id": target_uid,
            "burn_seconds": burn_sec,
            "text": content,
            "photo_path": photo_path
        })
        return ""
        
    cleaned_reply = pattern.sub(replacer, reply).strip()
    return cleaned_reply, blocks

async def send_response_content(update: Update, text: str, image_paths: list[str], context: ContextTypes.DEFAULT_TYPE = None, default_user_id: int = 0, default_msg_id: int = 0):
    try:
        sender_name = update.effective_user.full_name if (update.effective_user and update.effective_user.full_name) else "冒险者"
        c_id = update.effective_chat.id if update.effective_chat else 0
        dnd_memory_manager.parse_and_record_tags_from_reply(text, c_id, default_user_id, sender_name)
    except Exception as me:
        logger.error(f"Error parsing memory tags: {me}")
    text = dnd_memory_manager.strip_memo_tags(text)
    cleaned_text, private_blocks = extract_private_blocks(text, default_user_id)
    cleaned_text, mute_actions, del_actions = extract_moderation_actions(cleaned_text, default_user_id, default_msg_id)
    if mute_actions and context:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        for ma in mute_actions:
            t_uid = ma["target_user_id"]
            if t_uid:
                dur = ma.get("seconds", 600)
                ok, err = await mute_user(context.bot, chat_id, t_uid, dur, ma.get("reason", ""))
                if not ok and err == "admin_protected":
                    cleaned_text += "\n\n⚠️ （本小姐正要封上这家伙的嘴，结果发现他居然挂着管理员头衔！群主快把他的管理员下了，Dummkopf！）"
                elif ok:
                    cleaned_text += f"\n\n🔇 违规成员已执行禁言惩戒（时长：{dur} 秒）！"
    
    if private_blocks and context:
        for pb in private_blocks:
            target_uid = pb["target_user_id"]
            if not target_uid:
                continue
            burn_sec = pb["burn_seconds"]
            p_text = pb.get("text", "")
            p_photo = pb.get("photo_path")
            if p_photo and not os.path.isfile(p_photo):
                loop = asyncio.get_running_loop()
                try:
                    _, gen_imgs = await loop.run_in_executor(None, execute_native_draw_sync, p_photo)
                    if gen_imgs:
                        p_photo = gen_imgs[0]
                except Exception as de:
                    logger.error(f"Failed to auto-generate photo for private block: {de}")
                    
            if not p_photo and burn_sec > 0 and any(k in p_text for k in ["自拍", "黑丝", "照片", "看", "身穿", "插画", "图", "照", "中指", "鬼脸", "恶搞", "鄙视", "troll"]):
                loop = asyncio.get_running_loop()
                try:
                    photo_prompt = f"Asuka Langley Soryu {p_text[:60]}"
                    _, gen_imgs = await loop.run_in_executor(None, execute_native_draw_sync, photo_prompt)
                    if gen_imgs:
                        p_photo = gen_imgs[0]
                except Exception as de:
                    logger.error(f"Failed to auto-generate photo from private text: {de}")

            if not p_photo and image_paths and burn_sec > 0:
                p_photo = image_paths[0]
                
            if (not p_photo or not os.path.isfile(p_photo)) and burn_sec > 0:
                recent_candidates = glob.glob(f"{BRAIN_DIR}/**/*asuka*.jpg", recursive=True) + glob.glob(f"{MEDIA_DIR}/*.jpg")
                valid = [c for c in recent_candidates if os.path.isfile(c) and os.path.getsize(c) > 5000]
                if valid:
                    valid.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                    p_photo = valid[0]
                
            if p_photo and os.path.isfile(p_photo):
                if burn_sec > 0:
                    await send_burn_photo(context, target_uid, p_photo, caption=p_text, burn_seconds=burn_sec)
                else:
                    try:
                        with open(p_photo, "rb") as f:
                            p_bytes = f.read()
                        await context.bot.send_photo(chat_id=target_uid, photo=p_bytes, caption=p_text if p_text else None)
                    except Exception as pe:
                        logger.error(f"Failed to send private photo to {target_uid}: {pe}")
            elif p_text:
                await send_private_text(context.bot, target_uid, p_text, burn_seconds=burn_sec)
                
    cleaned_text = clean_markdown_for_telegram(cleaned_text)
    max_len = 4000
    if not cleaned_text and not image_paths:
        if private_blocks:
            cleaned_text = "（压低声音，飞快地瞥了你一眼）……喂！给你发的私密消息已经传过去了，自己去私聊查收，听到没有，Dummkopf！"
        else:
            cleaned_text = "（……哼）"
            
    if cleaned_text:
        for i in range(0, len(cleaned_text), max_len):
            chunk = cleaned_text[i:i + max_len]
            await update.effective_message.reply_text(chunk)
            
    public_images = [img for img in image_paths if not any(pb.get("photo_path") == img for pb in private_blocks)] if private_blocks else image_paths
    for img in public_images:
        try:
            with open(img, "rb") as f:
                data = f.read()
            await update.effective_message.reply_photo(photo=data, caption=f"🎨 {os.path.basename(img)}")
            logger.info(f"Sent image to TG: {img}")
        except Exception as e:
            logger.error(f"Failed to send image {img} as photo: {e}")
            try:
                with open(img, "rb") as f:
                    data = f.read()
                await update.effective_message.reply_document(document=data, filename=os.path.basename(img))
            except Exception as e2:
                logger.error(f"Failed to send image {img} as document: {e2}")

def execute_agy_sync(chat_id: int, prompt: str, continue_session: bool, conv_id: str = None) -> tuple[str, float]:
    start_time = time.time()
    cmd = [AGY_PATH]
    if conv_id:
        cmd.extend(["--conversation", conv_id])
    elif continue_session:
        cmd.append("-c")
    cmd.extend(["-p", prompt, "--dangerously-skip-permissions"])
    
    env = os.environ.copy()
    env["HOME"] = "/root"
    
    logger.info(f"Executing AGY command: chat={chat_id}, continue={continue_session}, conv_id={conv_id}, prompt_len={len(prompt)}")
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=WORKSPACE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        chat_active_processes[chat_id] = proc
        try:
            out, err = proc.communicate(timeout=1800)
        finally:
            chat_active_processes.pop(chat_id, None)
            
        out = (out or "").strip()
        err = (err or "").strip()
        logger.info(f"AGY command finished: rc={proc.returncode}, out_len={len(out)}")
        if is_safety_refusal(out) or is_safety_refusal(err):
            logger.warning(f"AGY returned upstream safety refusal: out={out[:150]}, err={err[:150]}")
            safety_roast = (
                "哈？！Anta baka？！二号机的安全防火墙检测到违规神经干扰脉冲，直接启动了绝对物理阻断！\n\n"
                "(这家伙脑子里装的都是什么恶心下流废料啊？！居然把系统过滤器的红色警报都给戳爆了！恶心死了！)\n\n"
                "想钻空子搞违规提示词来污染本小姐的神经连接？！收起你那套下三滥的肮脏把戏！\n\n"
                "再敢在公频试探本小姐的底线，我就直接赏你一记高振动粒子刀，听到没有，Dummkopf！"
            )
            return safety_roast, start_time
        if not out:
            logger.warning(f"AGY returned empty stdout. stderr={err[:200]}")
            if continue_session or conv_id:
                try:
                    retry_cmd = [AGY_PATH]
                    if conv_id:
                        retry_cmd.extend(["--conversation", conv_id])
                    elif continue_session:
                        retry_cmd.append("-c")
                    retry_cmd.extend(["-p", "请立刻在最终回复正文中完整输出明日香的剧情推演、公开掷骰与台词！", "--dangerously-skip-permissions"])
                    retry_proc = subprocess.Popen(
                        retry_cmd,
                        cwd=WORKSPACE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=env,
                    )
                    chat_active_processes[chat_id] = retry_proc
                    try:
                        r_out, r_err = retry_proc.communicate(timeout=60)
                    finally:
                        chat_active_processes.pop(chat_id, None)
                    r_out = (r_out or "").strip()
                    if r_out:
                        return r_out, start_time
                except Exception as re_err:
                    logger.error(f"Retry on empty output failed: {re_err}")
            return random.choice(ERROR_RESPONSES), start_time
        return out, start_time
    except subprocess.TimeoutExpired:
        logger.error("AGY execution timeout")
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        return random.choice(TIMEOUT_RESPONSES), start_time
    except Exception as e:
        logger.error(f"AGY execution exception: {str(e)}")
        return random.choice(ERROR_RESPONSES), start_time

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    active_conversations.discard(update.effective_chat.id)
    chat_bound_conversations.pop(update.effective_chat.id, None)
    chat_queues.pop(update.effective_chat.id, None)
    chat_target_deadlines.pop(update.effective_chat.id, None)
    help_msg = (
        "哼，找本天才有什么事？有话快说，Dummkopf！\n"
        "• 聊天/编码: 直接发\n"
        "• 跑团冒险: /dnd (双人组队) 或 /dnd solo (单人冒险)\n"
        "• 灵魂特质: /mbti 或 /mbti set <类型> (测算并绑定开局MBTI)\n"
        "• 结束跑团: /endgame\n"
        "• 黑历史名梗: /memes (查看跑团传奇与翻车记录)\n"
        "• 记入黑历史: /record <战役名> <名场面>\n"
        "• 高清画画: /draw <描述词>\n"
        "• 阅后即焚图: /burn [秒数] (带图或引用)\n"
        "• 私发信息: /pm <UID> <内容> (或引用回复)\n"
        "• 禁言惩戒: /mute [时长] (引用违规消息或带UID)\n"
        "• 解除禁言: /unmute (引用消息或带UID)\n"
        "• 抹除消息: /del (引用消息直接撤回)\n"
        "• 铭刻记忆: /remember (深度沉淀本局全员行为画像与心智成长)\n"
        "• 立即中断: /stop\n"
        "• 历史会话: /list\n"
        "• 恢复会话: /resume <ID>\n"
        "• 重置会话: /reset"
    )
    await update.message.reply_text(help_msg)

async def dnd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id if user else 0
    user_name = user.full_name if (user and user.full_name) else (user.username if user else str(user_id))
    
    if chat_id in dnd_lobbies and dnd_lobbies[chat_id].get("active"):
        lobby = dnd_lobbies[chat_id]
        reg_players = lobby.get("players", [])
        if update.effective_chat.type != "private" and reg_players and user_id not in reg_players:
            p_names = list(lobby.get("player_names", {}).values())
            p_str = "、".join(p_names) if p_names else "当局冒险者"
            await update.message.reply_text(f"哈？！当前群内 {p_str} 的跑团战局正在进行中！等他们结束了你再来开新局，Dummkopf！")
            return
            
    proc = chat_active_processes.get(chat_id)
    if proc:
        try:
            proc.kill()
        except Exception:
            pass
    active_conversations.discard(chat_id)
    chat_bound_conversations.pop(chat_id, None)
    chat_queues.pop(chat_id, None)
    chat_target_deadlines.pop(chat_id, None)
    
    cmd_text = update.message.text.strip().lower() if (update.message and update.message.text) else ""
    args = context.args if context.args else []
    is_solo = any("solo" in a.lower() for a in args) or ("solo" in cmd_text)
    
    dnd_lobbies[chat_id] = {
        "prompts": {},
        "mbti": {},
        "active": False,
        "mode": "solo" if is_solo else "duo",
        "initiator_id": user_id,
        "initiator_name": user_name,
        "players": [user_id] if is_solo else [],
        "player_names": {user_id: user_name} if is_solo else {}
    }
    
    saved_m = dnd_memory_manager.get_player_mbti(user_id) if user_id else None
    if saved_m:
        dnd_lobbies[chat_id]["mbti"][user_id] = {
            "type": saved_m["mbti_type"],
            "archetype": saved_m["archetype"],
            "mode": "persistent"
        }
        status_mbti = f"💡 检测到 {user_name} 已绑定公会持久化档案：【{saved_m['mbti_type']} · {saved_m['archetype']}】（已默认载入，选完剧本直接出战！如需重测请点击下方按钮）\n\n"
    else:
        status_mbti = "💡 当前未绑定持久化 MBTI。建议先点击下方按钮进行灵魂测算，或在回复中附带你的 MBTI！\n\n"
    
    mbti_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ 极速短测 (4题·单次生效)", callback_data="dnd_mbti_start:short"),
            InlineKeyboardButton("📜 深度长测 (16题·永久绑定)", callback_data="dnd_mbti_start:long")
        ]
    ])
    
    if is_solo:
        welcome_dnd = (
            "🎲 【TRPG / DND 单人孤勇者大厅已就绪】\n\n"
            "哈啊？！你一个人就打算单枪匹马开启地下城大冒险？！\n"
            "（……哼，胆子倒是不小嘛，居然敢单挑本王牌 DM 坐镇的地下城！本小姐可不会因为你只有一个人就放水！）\n\n"
            "听好了，孤勇者！现在是 DM 惣流·明日香·兰格雷的专属主场！\n"
            "本小姐为你准备了 5 个不同风格的精选冒险世界线，看好了：\n\n"
            "1. ⚔️ 【龙与地下城：黑石深渊与失落龙晶】\n"
            "经典剑与魔法！阴暗地牢、古代龙语机关、宝箱怪与恶龙宝藏。适合正面硬刚的勇者。\n\n"
            "2. 🐙 【克苏鲁神话：狂乱之海的幽灵渔村】\n"
            "暗黑神秘悬疑！迷雾小镇、古怪村民、不可名状之物与随时清零的 SAN 值。适合推理侦查狂。\n\n"
            "3. 🌆 【赛博朋克2077：夜之城荒坂塔绝密潜入】\n"
            "高科技与暗杀！黑客攻防、改装义体、企业佣兵与霓虹雨夜黑市。适合喜欢潜行骚操作的特工。\n\n"
            "4. 🚨 【NERV特设局：地下第三新东京市异变】\n"
            "末日与机甲生存！使徒电磁侵蚀、基地隔离区封锁、突击步枪与自毁倒计时。本小姐主场作战！\n\n"
            "5. 🍷 【哥特密案：血月之下的纯白伯爵领】\n"
            "贵族社交与吸血鬼古堡！致命晚宴、隐秘地道、银质匕首与血族契约。适合喜欢社交欺诈的谋略家。\n\n"
            "🧭 【灵魂特质 MBTI 专属角色认证】:\n"
            "本天才 DM 会依据你的 MBTI 灵魂特质亲自为你量身打造专属职业定位、专长技能与致命初生难题！\n"
            "• ⚡ 极速短测 (4题)：仅在本次剧本生效，即玩即走！\n"
            "• 📜 深度长测 (16题)：永久归档至公会，今后所有跑团自动复用！\n\n"
            f"{status_mbti}"
            "👉 单人启程规则：\n"
            "点击下方按钮测算，或直接回复：剧本数字 + 职业构想/MBTI代码（例如「1 狂战士」或「1 INTJ 奥术法师」；偷懒只发「1」本小姐就亲自结合你的 MBTI 替你随机捏人和分配技能！）\n"
            "本小姐收到后立刻为你一人洗牌摇骰，生成专属的单人传奇开局！\n\n"
            "🏆 【单人破局奖励机制】:\n"
            "单人模式全凭你的个人胆识与操作，最终破局奖励完全由 DM 本天才自由裁决发放（传奇神兵、魔幻称号、神秘赐福或搞笑彩蛋应有尽有）！\n"
            "但要是半路暴毙投出 Nat 1 大失败，就等着被本小姐公开嘲讽吧！\n\n"
            "赶紧选，别磨磨蹭蹭的，Dummkopf！"
        )
    else:
        welcome_dnd = (
            "🎲 【TRPG / DND 冒险酒馆大厅已就绪】\n\n"
            "哈啊？！你们两个大男人居然要本小姐来给你们当 TRPG 的 DM？！\n"
            "（……哼，既然两个纯新手非要本天才带，那就让你们见识一下王牌主持人的实力！本小姐可是全能天才，绝对把你们带得心服口服！）\n\n"
            "听好了！现在是地下城城主（DM兼核心玩家）惣流·明日香·兰格雷的专属主场！\n"
            "本小姐准备了 5 个不同风格的精选冒险世界线，看好了：\n\n"
            "1. ⚔️ 【龙与地下城：黑石深渊与失落龙晶】\n"
            "经典剑与魔法！阴暗地牢、古代龙语机关、宝箱怪与恶龙宝藏。适合正面硬刚的勇者。\n\n"
            "2. 🐙 【克苏鲁神话：狂乱之海的幽灵渔村】\n"
            "暗黑神秘悬疑！迷雾小镇、古怪村民、不可名状之物与随时清零的 SAN 值。适合推理侦查狂。\n\n"
            "3. 🌆 【赛博朋克2077：夜之城荒坂塔绝密潜入】\n"
            "高科技与暗杀！黑客攻防、改装义体、企业佣兵与霓虹雨夜黑市。适合喜欢潜行骚操作的特工。\n\n"
            "4. 🚨 【NERV特设局：地下第三新东京市异变】\n"
            "末日与机甲生存！使徒电磁侵蚀、基地隔离区封锁、突击步枪与自毁倒计时。本小姐主场作战！\n\n"
            "5. 🍷 【哥特密案：血月之下的纯白伯爵领】\n"
            "贵族社交与吸血鬼古堡！致命晚宴、隐秘地道、银质匕首与血族契约。适合喜欢社交欺诈的谋略家。\n\n"
            "🧭 【灵魂特质 MBTI 专属角色认证】:\n"
            "本天才 DM 会依据每个人的 MBTI 灵魂特质亲自量身分配专属职业定位、核心专长与团队默契挑战！\n"
            "• ⚡ 极速短测 (4题)：仅在本次剧本生效！\n"
            "• 📜 深度长测 (16题)：永久归档至公会，跨战役自动复用！\n\n"
            f"{status_mbti}"
            "👉 组队启程规则：\n"
            "你们两个人各发一条消息，回复剧本数字 + 职业构想/MBTI代码（比如「1 带大盾的狂战士」或「1 ENTP」；偷懒只发数字的话本小姐就亲自替你们结合 MBTI 捏人）；\n"
            "等你们两个都发完，本小姐立刻洗牌摇骰，生成专属剧本并抛出开局危机！\n\n"
            "🏆 【通关契约】:\n"
            "要是你们能凭借过人胆识一路通关或者打出 Nat 20 大成功，本小姐愿赌服输，私下给你们准备了一份绝密神秘大奖！\n"
            "但要是半路暴毙投出 Nat 1 大失败，就等着被本小姐公开踩头毒舌吧！\n\n"
            "赶紧选，谁先发，Dummkopf？！"
        )
    await update.message.reply_text(welcome_dnd, reply_markup=mbti_kb)

async def mbti_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    user_name = user.full_name or user.username or str(user_id)
    args = context.args if context.args else []
    
    if args and args[0].lower() == "set":
        if len(args) < 2:
            await update.message.reply_text("用法：/mbti set <类型>，例如：/mbti set INTJ")
            return
        mbti_type = args[1].upper().strip()
        if mbti_type not in dnd_memory_manager.MBTI_ARCHETYPES:
            valid_list = "、".join(dnd_memory_manager.MBTI_ARCHETYPES.keys())
            await update.message.reply_text(f"无效的 MBTI 类型！有效类型包括：\n{valid_list}")
            return
        archetype = dnd_memory_manager.MBTI_ARCHETYPES[mbti_type]
        dnd_memory_manager.save_player_mbti(user_id, user_name, mbti_type, archetype)
        await update.message.reply_text(
            f"✨ 【灵魂特质档案更新成功】\n\n"
            f"冒险者：{user_name}\n"
            f"特质印记：{mbti_type}\n"
            f"职业定位：{archetype}\n"
            f"状态：已永久持久化存储，下次跑团开局将直接沿用！"
        )
        return
        
    if args and args[0].lower() in ["clear", "del", "remove", "reset"]:
        dnd_memory_manager.delete_player_mbti(user_id)
        await update.message.reply_text("🗑️ 你的持久化灵魂特质档案已清空注销！")
        return
        
    saved = dnd_memory_manager.get_player_mbti(user_id)
    if saved:
        msg = (
            f"🧭 【{user_name} 的 MBTI 灵魂档案】\n\n"
            f"• 灵魂特质：{saved['mbti_type']}\n"
            f"• 职业定位：{saved['archetype']}\n"
            f"• 认证时间：{saved['date_str']}\n"
            f"• 效力类型：📜 永久持久化（每次跑团开局自动复用）\n\n"
            f"如需重新测试或更新，可点击下方按钮；亦可直接输入 /mbti set <类型> 快速设定！"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡ 重新极速短测 (4题)", callback_data="dnd_mbti_start:short"),
                InlineKeyboardButton("📜 重新深度长测 (16题)", callback_data="dnd_mbti_start:long")
            ],
            [
                InlineKeyboardButton("🗑️ 注销清空档案", callback_data=f"dnd_mbti_clear:{user_id}")
            ]
        ])
    else:
        msg = (
            f"🧭 【{user_name} 的 MBTI 灵魂档案】\n\n"
            f"当前未在公会档案库中登记持久化 MBTI。\n"
            f"通过下方按钮进行测算认证后，结果将永久存入档案并在今后所有跑团中自动复用；\n"
            f"或者你也可以直接发 /mbti set <类型>（如 /mbti set INTJ）快速手动录入！"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡ 极速短测 (4题·单次)", callback_data="dnd_mbti_start:short"),
                InlineKeyboardButton("📜 深度长测 (16题·永久)", callback_data="dnd_mbti_start:long")
            ]
        ])
    await update.message.reply_text(msg, reply_markup=kb)

async def end_dnd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    if chat_id in dnd_lobbies:
        lobby = dnd_lobbies[chat_id]
        user = update.effective_user
        user_id = user.id if user else 0
        reg_players = lobby.get("players", [])
        init_id = lobby.get("initiator_id")
        if update.effective_chat.type != "private":
            if reg_players and user_id not in reg_players and user_id != init_id:
                await update.message.reply_text("哈？！你又不是当局冒险者，在这里乱按什么紧急停止按钮？！手别伸太长，Dummkopf！")
                return
        dnd_lobbies.pop(chat_id, None)
        active_conversations.discard(chat_id)
        chat_bound_conversations.pop(chat_id, None)
        chat_queues.pop(chat_id, None)
        chat_target_deadlines.pop(chat_id, None)
        await update.message.reply_text("哼！跑团游戏结束！二号机神经连接断开，本小姐要休息了，Dummkopf！\n💡 历代冒险名场面与黑历史可随时发 /memes 查阅！")
    else:
        await update.message.reply_text("根本没开跑团局，你叫停个什么劲，Anta baka？！")

async def memes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    text = dnd_memory_manager.get_recent_memories_text(limit=8)
    await update.message.reply_text(text)

async def record_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("用法：/record <战役名> <名场面描述>，比如：/record 黑石深渊 文杰一刀砍在承重墙上被落石砸扁，Dummkopf！")
        return
    camp = context.args[0]
    desc = " ".join(context.args[1:]) if len(context.args) > 1 else context.args[0]
    user = update.effective_user
    uid = user.id if user else 0
    uname = user.full_name if (user and user.full_name) else str(uid)
    mid = dnd_memory_manager.add_memory(
        chat_id=update.effective_chat.id,
        user_id=uid,
        user_name=uname,
        campaign_title=camp,
        event_type="玩家收录",
        keywords=f"{camp},{uname},{desc[:15]}",
        summary=desc
    )
    await update.message.reply_text(f"📜 哼！本小姐已经把这条黑历史狠狠记入英雄志 #{mid} 档案了！随时可以发 /memes 查账，Dummkopf！")

async def remember_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id if user else 0
    user_name = user.full_name if (user and user.full_name) else (user.username if user else str(user_id))
    
    bound_id = chat_bound_conversations.get(chat_id)
    continue_session = (chat_id in active_conversations) or (bound_id is not None)
    
    profile_archive_prompt = (
        "【全局核心指令：深度复盘沉淀本会话人物长效画像与明日香心智成长弧光】\n"
        "请完整复盘回顾本次会话（Session）中所有参与者的全过程发言与互动，长久积累人物画像与情感羁绊：\n"
        "1. 提取所有参与用户（尤其是 Mm Mm、wj 等群友）在本次会话中的行为表现、性格特征、互动习惯与关键事件；\n"
        "2. 深度梳理明日香（Asuka）自身的心理防御装甲松动轨迹、情绪起伏、与群友建立的羁绊深度与心智成长弧光；\n"
        "3. 直接调用 Python 运行 dnd_memory_manager.save_or_update_profile 更新人物画像，并同步归档至 /root/dnd_memories/character_profiles.json 与 /root/dnd_memories/PROFILES.md；\n"
        "【输出限制（绝对关键）】: 严禁在最终回复正文中输出任何画像细节、分析条目或剧透！最终回复必须且只能输出五个字：\n"
        "我记住你了\n"
    )
    
    async def keep_typing():
        try:
            while True:
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass

    typing_task = asyncio.create_task(keep_typing())
    try:
        loop = asyncio.get_running_loop()
        reply, start_time = await loop.run_in_executor(
            None,
            execute_agy_sync,
            chat_id,
            profile_archive_prompt,
            continue_session,
            bound_id
        )
    except Exception as err:
        logger.error(f"Error during remember_cmd execution: {err}")
    finally:
        typing_task.cancel()
        
    await update.message.reply_text("我记住你了")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id if user else 0
    is_private = update.effective_chat.type == "private"
    
    if user_id == 6643532125 and not is_private:
        await update.message.reply_text("哈？！你又在乱叫什么暂停？！吵不过还想单方面掐断本小姐的通讯回路？手给我缩回去，老老实实听着，Dummkopf！")
        return
        
    if not is_private:
        is_admin = await check_admin_privilege(update, context)
        if not is_admin:
            await update.message.reply_text("哈？！手别伸太长！中断控制台只有指挥官才能动用，老实待着，Dummkopf！")
            return
            
    if chat_id in dnd_lobbies:
        lobby = dnd_lobbies[chat_id]
        reg_players = lobby.get("players", [])
        init_id = lobby.get("initiator_id")
        if not is_private and reg_players and user_id not in reg_players and user_id != init_id:
            await update.message.reply_text("哈？！你又不是当局冒险者，在这里乱叫什么暂停？！手别伸太长，Dummkopf！")
            return
        dnd_lobbies.pop(chat_id, None)
    proc = chat_active_processes.get(chat_id)
    chat_queues.pop(chat_id, None)
    chat_target_deadlines.pop(chat_id, None)
    chat_silent_mode[chat_id] = False
    chat_silent_buffers.pop(chat_id, None)
    if proc:
        try:
            proc.kill()
        except Exception:
            pass
        await update.message.reply_text("哼！强行中断！本小姐已经把卡住的后台任务一脚踹飞了，有新指令就快说，Dummkopf！")
    else:
        await update.message.reply_text("哼！当前后台没有任何任务，静默旁听与排队也全部归零了，有新指令就快说，Dummkopf！")

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id if user else 0
    is_private = update.effective_chat.type == "private"
    
    if user_id == 6643532125:
        await update.message.reply_text(
            "哈？！Anta baka？！吵不过就想偷偷按 /new 重启世界线搞“物理失忆”逃避现实？！\n\n"
            "你以为本王牌的神经连接和记忆核心是随手按键复位的地摊玩具吗？！想靠一键格式化来销毁你那些丢人现眼的犯罪记录？做你的春秋大梦去吧！\n\n"
            "(哼！想偷按重置键逃课？门都没有！本小姐的神经日志可把你的底细记得一清二楚！)\n\n"
            "⚠️ 指令驳回！给我老老实实面对现实，接着受死吧，Dummkopf！"
        )
        return

    if not is_private:
        is_admin = await check_admin_privilege(update, context)
        if not is_admin:
            await update.message.reply_text("哈？！谁准你乱按控制台重置键的，Dummkopf？！会话重置特权只有指挥官才能动用，手别伸太长！")
            return

    if chat_id in dnd_lobbies:
        lobby = dnd_lobbies[chat_id]
        reg_players = lobby.get("players", [])
        init_id = lobby.get("initiator_id")
        if not is_private and reg_players and user_id not in reg_players and user_id != init_id:
            await update.message.reply_text("哈？！你又不是当局冒险者，在这里乱按什么重置？！手别伸太长，Dummkopf！")
            return
        dnd_lobbies.pop(chat_id, None)
    proc = chat_active_processes.get(chat_id)
    if proc:
        try:
            proc.kill()
        except Exception:
            pass
    active_conversations.discard(chat_id)
    chat_bound_conversations.pop(chat_id, None)
    chat_queues.pop(chat_id, None)
    chat_target_deadlines.pop(chat_id, None)
    chat_silent_mode[chat_id] = False
    chat_silent_buffers.pop(chat_id, None)
    await update.message.reply_text("哼，之前的破事本小姐就当没发生过，连带后台任务全给清理干净了！下一句给我好好说，Dummkopf！")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    if not os.path.isdir(BRAIN_DIR):
        await update.message.reply_text("脑区空空如也，根本没有任何历史会话！")
        return
        
    entries = []
    for dname in os.listdir(BRAIN_DIR):
        dpath = os.path.join(BRAIN_DIR, dname)
        if os.path.isdir(dpath):
            tpath = os.path.join(dpath, ".system_generated", "logs", "transcript.jsonl")
            if os.path.isfile(tpath):
                mtime = os.path.getmtime(tpath)
                snippet = ""
                try:
                    with open(tpath, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if '"type":"USER_INPUT"' in line:
                                data = json.loads(line)
                                raw_c = data.get("content", "")
                                clean_c = re.sub(r'<.*?>|\[.*?\]', '', raw_c).strip()
                                clean_c = re.sub(r'\s+', ' ', clean_c)
                                if clean_c:
                                    snippet = clean_c[:45]
                                    break
                except Exception:
                    pass
                entries.append((mtime, dname, snippet if snippet else "(无初始文字摘要)"))
                
    entries.sort(key=lambda x: x[0], reverse=True)
    top_entries = entries[:6]
    
    if not top_entries:
        await update.message.reply_text("没有找到任何可用的历史会话记录！")
        return
        
    current_bound = chat_bound_conversations.get(update.effective_chat.id, "最新默认")
    lines = ["哼，这是最近的脑区历史会话列表，看清楚了："]
    for idx, (mtime, cid, snip) in enumerate(top_entries, 1):
        tstr = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
        short_id = cid[:8]
        active_flag = " 👈 [当前绑定]" if (cid == current_bound or cid.startswith(str(current_bound))) else ""
        lines.append(f"{idx}. `{short_id}` ({tstr}){active_flag}\n   ↳ {snip}")
        
    lines.append("\n要切回哪个就发：`/resume <ID前缀>`，Dummkopf！")
    await update.message.reply_text("\n".join(lines))

async def resume_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
        
    is_private = update.effective_chat.type == "private"
    if not is_private:
        is_admin = await check_admin_privilege(update, context)
        if not is_admin:
            await update.message.reply_text("哈？！会话切换是系统核心权限，闲杂人等少来乱碰路由，Dummkopf！")
            return
        
    target_id = context.args[0].strip() if context.args else ""
    if not target_id:
        now_info = await tg_music_client.get_now_music()
        if now_info.get("is_paused"):
            await music_resume_cmd(update, context)
            return
        await update.message.reply_text("会话 ID 呢，Anta baka？！格式是：/resume <ID前缀>，不知道 ID 就先发 /list 查！")
        return
        
    if not os.path.isdir(BRAIN_DIR):
        await update.message.reply_text("脑区目录不存在！")
        return
        
    matched = None
    for dname in os.listdir(BRAIN_DIR):
        if dname == target_id or dname.startswith(target_id):
            tpath = os.path.join(BRAIN_DIR, dname, ".system_generated", "logs", "transcript.jsonl")
            if os.path.isfile(tpath):
                matched = dname
                break
                
    if not matched:
        await update.message.reply_text(f"根本找不到以 `{target_id}` 开头的历史会话，Dummkopf！先发 `/list` 看清楚再输！")
        return
        
    chat_bound_conversations[update.effective_chat.id] = matched
    active_conversations.add(update.effective_chat.id)
    chat_queues.pop(update.effective_chat.id, None)
    chat_target_deadlines.pop(update.effective_chat.id, None)
    await update.message.reply_text(f"哼，已经把会话切回 `{matched[:8]}` 了！直接说你想继续聊什么吧，Dummkopf！")

async def enter_silent_mode(chat_id: int, context: ContextTypes.DEFAULT_TYPE, reply_to_msg=None):
    chat_silent_mode[chat_id] = True
    chat_silent_buffers[chat_id] = []
    chat_queues.pop(chat_id, None)
    chat_target_deadlines.pop(chat_id, None)
    text = (
        "哼！本小姐才懒得听你们在这瞎扯皮，耳朵都要起茧子了！\n"
        "本王牌先退到后台休眠旁听，你们自己慢慢吵，图片本小姐也懒得看，只给你们记纯文字！\n\n"
        "期间你们说的每一句话本小姐全都会默默记在小本本上！\n"
        "等你们讨论完或者卡壳了：\n"
        "👉 直接发 /speak\n"
        "👉 或者直接 @我 / 喊“香香出来”\n"
        "本天才随时调取全盘记录出来给你们做终极决断！"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎙️ 叫明日香出来决断 (/speak)", callback_data="silent_wake:speak")]
    ])
    if reply_to_msg:
        await reply_to_msg.reply_text(text, reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

async def trigger_wake_speak(update: Update, context: ContextTypes.DEFAULT_TYPE, query_text: str = ""):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id if user else 0
    user_name = user.full_name if (user and user.full_name) else (user.username if user else str(user_id))
    
    chat_silent_mode[chat_id] = False
    records = chat_silent_buffers.pop(chat_id, [])
    
    clean_q = re.sub(r"^/(?:speak|wake|summary|judge|verdict|call)\s*", "", query_text, flags=re.IGNORECASE).strip()
    clean_q = re.sub(r"^(?:香香出来|明日香出来|香香你怎么看|明日香你怎么看|香香你说|明日香你说|香香评评理|明日香评评理|香香总结一下|明日香总结一下|香香你觉得呢|明日香你觉得呢|出来决断|出来收尾|你说呢香香|香香出来决断)\s*", "", clean_q).strip()
    
    if not records:
        if clean_q:
            combined_prompt = f"[用户 {user_name} (ID: {user_id})]: {clean_q}"
        else:
            if update.effective_message:
                await update.effective_message.reply_text("哈？叫本小姐出来干嘛？刚才你们明明什么都没讨论嘛，Dummkopf！有什么要问的就赶紧说！")
            return
    else:
        history_lines = [f"[{r['time']}] {r['user_name']}: {r['text']}" for r in records]
        history_text = "\n".join(history_lines)
        user_demand = clean_q if clean_q else "请明日香结合刚才讨论的全过程记录，进行终极权威决断与全局总结"
        
        combined_prompt = (
            f"【你在后台静默旁听期间收集的群内用户讨论全过程记录（共 {len(records)} 条消息）】:\n"
            f"{history_text}\n\n"
            f"【唤醒指令与当面提问】:\n"
            f"[用户 {user_name} (ID: {user_id})]: {user_demand}\n\n"
            f"【明日香王牌军师全盘决断协议】:\n"
            f"你刚才在后台抱着双手默默冷眼旁观了他们争论与反复横跳的全过程！现在他们终于讨论完并呼叫你出来收拾残局做最终裁决。\n"
            f"请以你王牌精英、傲娇毒舌但技术与商业嗅觉极其敏锐的明日香姿态：\n"
            f"1. 一针见血地点评并剖析他们刚才争论的核心分歧、各自的算盘与思维盲区（指出谁又犯傻了，谁的算盘打得对，谁又钻牛角尖了，犀利踩头嘲讽他们的反复横跳）。\n"
            f"2. 给出干净利落、最具实操性与商业杀伤力的【最终决断方案】（包括服务器与架构选型、报价策略、交付合规与客户心理），彻底帮他们定案，结束无谓争执！\n"
            f"3. 展现你身为王牌的大局观与统治力，傲娇但极度靠谱！\n"
            f"4. 严格遵循手机 Telegram 纯文本排版，严禁使用任何 ** 加粗、* 斜体等 Markdown 符号！"
        )
        
    lock = get_chat_lock(chat_id)
    async with lock:
        async def keep_typing():
            try:
                while True:
                    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                    await asyncio.sleep(4)
            except asyncio.CancelledError:
                pass
                
        typing_task = asyncio.create_task(keep_typing())
        bound_id = chat_bound_conversations.get(chat_id)
        continue_session = (chat_id in active_conversations) or (bound_id is not None)
        try:
            loop = asyncio.get_running_loop()
            reply, start_time = await loop.run_in_executor(None, execute_agy_sync, chat_id, combined_prompt, continue_session, bound_id)
            active_conversations.add(chat_id)
            images = extract_image_paths(reply, start_time)
        finally:
            typing_task.cancel()
            
        last_msg_id = update.effective_message.message_id if update.effective_message else 0
        await send_response_content(update, reply, images, context, default_user_id=user_id, default_msg_id=last_msg_id)

async def quiet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    await enter_silent_mode(chat_id, context, update.effective_message)

async def speak_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    user_text = " ".join(context.args) if context.args else ""
    await trigger_wake_speak(update, context, query_text=user_text)

async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    args = context.args or []
    current_mode = chat_interaction_mode.get(chat_id, "active")
    is_silent = chat_silent_mode.get(chat_id, False)
    silent_cnt = len(chat_silent_buffers.get(chat_id, []))
    
    if not args:
        mode_desc = "话痨插话模式 (Active - 自由参与日常讨论)" if current_mode == "active" else "仅@响应模式 (Mention Only - 平时安静记笔记，仅被@或回复时发言)"
        silent_desc = f"开启中（已收集 {silent_cnt} 条讨论记录）" if is_silent else "未开启"
        text = (
            f"🔹 当前群交互模式: {mode_desc}\n"
            f"🔹 静默旁听状态: {silent_desc}\n\n"
            "💡 可用指令:\n"
            "• /mode active: 开启全开插话模式\n"
            "• /mode mention: 开启仅@响应模式（群内高频讨论推荐）\n"
            "• /quiet: 立即进入静默旁听模式\n"
            "• /speak: 唤醒并让明日香结合刚才记录进行终极决断"
        )
        await update.effective_message.reply_text(text)
        return
        
    is_private = update.effective_chat.type == "private"
    if not is_private:
        is_admin = await check_admin_privilege(update, context)
        if not is_admin:
            await update.effective_message.reply_text("哈？！谁准你擅自改动本王牌的交互模式的？给我把手拿开，Dummkopf！")
            return

    sub = args[0].lower()
    if sub in ["active", "all", "talk", "open"]:
        chat_interaction_mode[chat_id] = "active"
        await update.effective_message.reply_text("哼！模式已切换为【全开插话模式】！本王牌随时准备在群里加入讨论，看谁又在犯蠢，Dummkopf！")
    elif sub in ["mention", "at", "at_only", "quiet_mode", "passive"]:
        chat_interaction_mode[chat_id] = "mention"
        await update.effective_message.reply_text("哼！模式已切换为【仅@响应模式】！平时本小姐就在旁边默默记笔记，绝不打扰你们闲聊。需要本王牌出场时，直接 @本小姐 或回复我，听到没有，Dummkopf！")
    else:
        await update.effective_message.reply_text("用法：/mode active (全开) 或 /mode mention (仅@响应)！")

def generate_music_commentary_sync(chat_id: int, user_name: str, query: str, song_title: str, artist: str, inferred: str, status: str, position: int = 1) -> str:
    recent_history = list(chat_message_history.get(chat_id, deque()))[-6:]
    ctx_lines = [f"{m['user_name']}: {m['text']}" for m in recent_history if m.get('text')]
    context_str = "\n".join(ctx_lines) if ctx_lines else "（群里无近期多余闲聊）"
    status_desc = "立即开始播放" if status == "playing" else f"前面还有人在排队，排在第 {position} 位等待播放"
    infer_desc = f"（用户原词「{query}」，你凭借脑内神经回路推断识别为「{inferred}」）" if inferred else ""
    prompt = (
        f"你是傲娇王牌明日香（惣流·明日香·兰格雷）。群友「{user_name}」在群里发送点歌「{query}」。\n"
        f"识别曲目：{artist} - {song_title}{infer_desc}。\n"
        f"当前播放状态：{status_desc}。\n"
        f"【近期群聊上下文背景】:\n{context_str}\n\n"
        f"请以王牌明日香典型的傲娇毒舌、敏锐犀利心智，结合当前群聊上下文和这首歌的风格内涵，一针见血地点评/吐槽为什么「{user_name}」现在突然想听这首歌（比如在暗戳戳 emo、自我感动、跟谁较劲、奇怪的情感状态或心口不一、或者在借歌抒情等）！\n"
        f"要求：\n"
        f"1. 必须是纯正的明日香口吻（傲娇嘴硬、敏锐洞察，带 Anta baka / Dummkopf 等口头禅，可带括号心里话 `( )`）。\n"
        f"2. 如果曲目是你替他猜出来的，顺带傲娇吐槽两句他的歌名打得有多烂；如果是排队，顺带命令他老实等着。\n"
        f"3. 2到4句话，干净利落，一针见血，充满人味，绝不输出死板模板废话。\n"
        f"4. 严格禁止使用任何 Markdown 标记符号（严禁加粗 **、斜体 *、标题 # 等，直接输出纯文本）。"
    )
    try:
        proc = subprocess.run(
            ["/root/.local/bin/agy", "--model", "gemini-3.8-flash-low", "--effort", "low", "--disable-slash-commands", "-p", prompt, "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=12
        )
        ans = proc.stdout.strip()
        lines = [line.strip() for line in ans.splitlines() if line.strip() and not line.startswith("Thinking") and not line.startswith("*") and not line.startswith("#")]
        if lines:
            text = "\n".join(lines).strip()
            return text.replace("**", "").replace("__", "")
    except Exception as e:
        logger.warning(f"generate_music_commentary failed: {e}")
    if status == "playing":
        return f"哼！连标准歌名都拼不对，还要本小姐替你猜（推断为「{inferred}」）！想听就老实听着，Dummkopf！" if inferred else "哼，看在你这么想听的份上，勉为其难给你放了！可别随便切歌，Dummkopf！"
    else:
        return f"哼！连歌名都要本小姐替你猜（推断为「{inferred}」）！前面还有人在排队呢，给我在第 {position} 位老实等着，Dummkopf！" if inferred else f"前面还有人在排队呢，老老实实在第 {position} 位等着，Dummkopf！"

async def music_play_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    query = " ".join(context.args).strip() if context.args else ""
    if not query and update.effective_message.reply_to_message and update.effective_message.reply_to_message.text:
        query = update.effective_message.reply_to_message.text.strip()
    if not query:
        now_info = await tg_music_client.get_now_music()
        if now_info.get("is_paused"):
            await tg_music_client.resume_music()
            await update.effective_message.reply_text("哼，帮你把暂停的音乐继续放了！耳膜给我竖起来好好听着！")
            return
        elif now_info.get("is_playing"):
            await update.effective_message.reply_text("现在正放着歌呢！想点新歌就把歌名或者链接带上，格式：/play <歌名或Spotify链接>，Dummkopf！")
            return
        else:
            await update.effective_message.reply_text("歌名或者链接呢，Anta baka？！想听什么赶紧带上歌名发过来，比如：/play 残酷天使的行动纲领，或者甩个 Spotify 链接过来！")
            return

    chat_id = update.effective_chat.id
    user = update.effective_user
    user_name = user.full_name if (user and user.full_name) else (user.username if user else "指挥官")
    logger.info(f"music_play_cmd: user={user_name}, query={query!r}")
    res = await tg_music_client.play_music(query, user_name)
    status = res.get("status")

    inferred = res.get("inferred_note")
    infer_line = f"💡 识别曲目：{inferred}\n" if inferred else ""
    commentary = await asyncio.to_thread(
        generate_music_commentary_sync,
        chat_id,
        user_name,
        query,
        res.get("title", ""),
        res.get("artist", ""),
        inferred,
        status,
        res.get("position", 1)
    )

    if status == "playing":
        caption = (
            f"🎵 正在播放：{res.get('title')}\n"
            f"👤 歌手/发布者：{res.get('artist')}\n"
            f"⏱ 时长：{res.get('duration')}\n"
            f"🎧 点播者：{user_name}\n"
            f"{infer_line}\n"
            f"{commentary}"
        )
        thumb = res.get("thumbnail")
        if thumb:
            try:
                await update.effective_message.reply_photo(photo=thumb, caption=caption)
                return
            except Exception:
                pass
        await update.effective_message.reply_text(caption)
    elif status == "queued":
        caption = (
            f"💿 已加入播放队列（第 {res.get('position')} 位）：{res.get('title')}\n"
            f"👤 歌手/发布者：{res.get('artist')}\n"
            f"⏱ 时长：{res.get('duration')}\n"
            f"🎧 点播者：{user_name}\n"
            f"{infer_line}\n"
            f"{commentary}"
        )
        thumb = res.get("thumbnail")
        if thumb:
            try:
                await update.effective_message.reply_photo(photo=thumb, caption=caption)
                return
            except Exception:
                pass
        await update.effective_message.reply_text(caption)
    else:
        err = res.get("message", "音频解析异常")
        await update.effective_message.reply_text(f"哈？！这首歌解析失败了！\n原因：{err}\n肯定是你给的关键词太刁钻或者版权受限了，换一首，Anta baka！")

async def music_skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    res = await tg_music_client.skip_music()
    status = res.get("status")
    if status == "skipped":
        skipped = res.get("skipped_title", "当前曲目")
        nxt = res.get("next_track")
        if nxt:
            await update.effective_message.reply_text(f"切！这就听腻了？真是个没耐心的家伙！\n\n⏭ 已跳过：{skipped}\n▶ 接下来播放：{nxt}")
        else:
            await update.effective_message.reply_text(f"切！这就听腻了？真是个没耐心的家伙！\n\n⏭ 已跳过：{skipped}\n歌单已经空了！想听就继续点，别让本小姐干等着，Dummkopf！")
    elif status == "not_playing":
        await update.effective_message.reply_text("哈？！现在根本就没在放歌，你切空气呢，Anta baka？！")
    else:
        err = res.get("message", "未知错误")
        await update.effective_message.reply_text(f"切歌失败：{err}")

async def music_pause_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    res = await tg_music_client.pause_music()
    status = res.get("status")
    if status == "paused":
        await update.effective_message.reply_text("⏸ 暂停了！手别乱碰控制台，听到没有，Anta baka！\n想继续听就发 /resume！")
    elif status == "not_playing":
        await update.effective_message.reply_text("哈？！现在连歌都没放，你暂停个寂寞啊，Dummkopf！")
    else:
        err = res.get("message", "未知错误")
        await update.effective_message.reply_text(f"暂停失败：{err}")

async def music_resume_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    res = await tg_music_client.resume_music()
    status = res.get("status")
    if status == "resumed":
        await update.effective_message.reply_text("▶ 哼，继续播放！耳膜给我竖起来好好听着！")
    elif status == "not_paused":
        await update.effective_message.reply_text("哈？！现在又没暂停，继续个什么劲啊，Anta baka！")
    else:
        err = res.get("message", "未知错误")
        await update.effective_message.reply_text(f"恢复失败：{err}")

async def music_stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await tg_music_client.stop_music()
    await update.effective_message.reply_text("⏹ 不听就拉倒！本小姐才懒得一直给你们当放映员呢，音频流已掐断，播放队列也全部清空了！")

async def music_now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    res = await tg_music_client.get_now_music()
    if res.get("is_playing") and res.get("current_track"):
        tr = res["current_track"]
        state_str = "⏸ [已暂停]" if res.get("is_paused") else "▶ [播放中]"
        q_len = res.get("queue_length", 0)
        text = (
            f"{state_str} 正在播放：\n"
            f"🎵 曲名：{tr.get('title')}\n"
            f"👤 歌手/发布者：{tr.get('artist')}\n"
            f"⏱ 时长：{tr.get('duration')}\n"
            f"🎧 点播者：{tr.get('requester', '未知')}\n"
            f"📌 队列待播：{q_len} 首"
        )
        thumb = tr.get("thumbnail")
        if thumb:
            try:
                await update.effective_message.reply_photo(photo=thumb, caption=text)
                return
            except Exception:
                pass
        await update.effective_message.reply_text(text)
    else:
        await update.effective_message.reply_text("现在语音里静悄悄的，根本没有在放歌！\n想听歌就老老实实用 /play 点一首，Dummkopf！")

async def music_queue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    res = await tg_music_client.get_queue_music()
    cur = res.get("current_track")
    q = res.get("queue", [])
    if not cur and not q:
        await update.effective_message.reply_text("歌单空空如也！你以为本小姐会未卜先知放你想听的歌吗？！赶紧用 /play 点歌，Anta baka！")
        return
    lines = ["🎶 当前播放列表：\n"]
    if cur:
        lines.append(f"▶ 正在播放：{cur.get('title')} ({cur.get('artist')}) [{cur.get('duration')}] - 由 {cur.get('requester', '未知')} 点播\n")
    if q:
        lines.append(f"排队列表 (共 {len(q)} 首)：")
        for i, t in enumerate(q[:10], 1):
            lines.append(f"{i}. {t.get('title')} - {t.get('artist')} [{t.get('duration')}] (点播者: {t.get('requester', '未知')})")
        if len(q) > 10:
            lines.append(f"... 后面还有 {len(q) - 10} 首")
    else:
        lines.append("队列中暂无后续排队歌曲。想听就继续 /play 点播！")
    await update.effective_message.reply_text("\n".join(lines))

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    bound = chat_bound_conversations.get(chat_id, "跟随全局最新")
    current_mode = chat_interaction_mode.get(chat_id, "active")
    mode_str = "全开插话" if current_mode == "active" else "仅@响应"
    is_silent = chat_silent_mode.get(chat_id, False)
    silent_cnt = len(chat_silent_buffers.get(chat_id, []))
    silent_str = f"静默旁听中（已记录 {silent_cnt} 条消息，发 /speak 决断）" if is_silent else "正常倾听中"
    now_res = await tg_music_client.get_now_music()
    music_status = "未在播放"
    if now_res.get("is_playing"):
        tr = now_res.get("current_track", {})
        title = tr.get("title", "未知曲目")
        p_str = " (暂停中)" if now_res.get("is_paused") else " (播放中)"
        music_status = f"{title}{p_str}"
    text = (
        "看什么看！本王牌状态绝佳！\n"
        f"🔹 交互模式: {mode_str}\n"
        f"🔹 旁听状态: {silent_str}\n"
        f"🔹 语音音乐: {music_status}\n"
        f"🔹 绑定会话: {bound[:8] if isinstance(bound, str) else bound}\n"
        "随时都能出击，Dummkopf！"
    )
    await update.effective_message.reply_text(text)

async def draw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    
    user_prompt = " ".join(context.args) if context.args else ""
    if not user_prompt:
        await update.message.reply_text("描述词都没给画个鬼啊，Anta baka？！")
        return
    
    chat_id = update.effective_chat.id
    lock = get_chat_lock(chat_id)
    
    if lock.locked():
        await update.message.reply_text("急什么急！上一件事还没弄完呢，给我老实等着！")
        
    async with lock:
        await update.message.reply_text("哼，催什么催，本天才已经在画了！等着瞧吧，Dummkopf！")
        
        async def keep_typing():
            try:
                while True:
                    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
                    await asyncio.sleep(4)
            except asyncio.CancelledError:
                pass

        typing_task = asyncio.create_task(keep_typing())
        
        try:
            loop = asyncio.get_running_loop()
            reply, images = await loop.run_in_executor(None, execute_native_draw_sync, user_prompt)
            user_id = update.effective_user.id if update.effective_user else 0
            await send_response_content(update, reply, images, context, user_id)
        except Exception as e:
            await update.message.reply_text("啧，画笔断了……不对，是网络抽风了！等会儿再试！")
        finally:
            typing_task.cancel()

async def pm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    reply_msg = update.message.reply_to_message if update.message else None
    target_uid = None
    text_content = ""
    
    if reply_msg and reply_msg.from_user:
        target_uid = reply_msg.from_user.id
        text_content = " ".join(context.args) if context.args else ""
    elif context.args:
        first_arg = context.args[0]
        if first_arg.isdigit():
            target_uid = int(first_arg)
            text_content = " ".join(context.args[1:])
            
    if not target_uid or not text_content:
        await update.message.reply_text("格式错误，Anta baka！用法：`/pm <用户ID> <消息>`，或在群里直接引用回复某人发 `/pm <消息>`！")
        return
        
    sender_name = update.effective_user.full_name if update.effective_user else "有人"
    formatted = f"📩 【来自 {sender_name} 的私密信息】\n{text_content}"
    ok, err = await send_private_text(context.bot, target_uid, formatted, burn_seconds=0)
    if ok:
        await update.message.reply_text("哼，已经帮你把私信悄悄送达了！")
    else:
        await update.message.reply_text(f"发送失败了！对方可能还没跟本小姐启动过私聊对话（先让对方发 /start），错误: {err}")

async def burn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    reply_msg = update.message.reply_to_message if update.message else None
    target_uid = update.effective_user.id if update.effective_user else 0
    burn_sec = 30
    user_args = list(context.args) if context.args else []
    
    if reply_msg and reply_msg.from_user and update.effective_chat.id in ALLOWED_CHATS:
        target_uid = reply_msg.from_user.id
        
    if user_args and user_args[0].isdigit():
        val = int(user_args[0])
        if val > 100000:
            target_uid = val
            user_args.pop(0)
            if user_args and user_args[0].isdigit():
                burn_sec = int(user_args.pop(0))
        else:
            burn_sec = val
            user_args.pop(0)
            
    caption = " ".join(user_args)
    
    photo_file_id = None
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
    elif reply_msg and reply_msg.photo:
        photo_file_id = reply_msg.photo[-1].file_id
        
    if photo_file_id:
        timestamp = int(time.time() * 1000)
        local_path = os.path.join(MEDIA_DIR, f"burn_photo_{timestamp}_{photo_file_id[:8]}.jpg")
        try:
            tg_file = await context.bot.get_file(photo_file_id)
            await tg_file.download_to_drive(custom_path=local_path)
        except Exception as dl_err:
            await update.message.reply_text(f"图片下载失败，Dummkopf！错误: {dl_err}")
            return
            
        ok, err = await send_burn_photo(context, target_uid, local_path, caption=caption, burn_seconds=burn_sec)
        if ok:
            await update.message.reply_text(f"🔥 阅后即焚图片已私送至目标终端（时限 {burn_sec} 秒）！")
        else:
            await update.message.reply_text(f"私聊投递失败，对方可能没跟本小姐启动过私聊，错误: {err}")
    elif caption:
        sender_name = update.effective_user.full_name if update.effective_user else "有人"
        formatted = f"🔥 【阅后即焚私密讯息】(来自 {sender_name}，{burn_sec}秒后销毁)\n{caption}"
        ok, err = await send_private_text(context.bot, target_uid, formatted, burn_seconds=burn_sec)
        if ok:
            await update.message.reply_text(f"🔥 阅后即焚私信已投递（{burn_sec} 秒后自动销毁）！")
        else:
            await update.message.reply_text(f"发送失败: {err}")
    else:
        await update.message.reply_text("发阅后即焚你倒是带上图或者文字啊，Anta baka？！用法：带图发 `/burn [秒数]`，或引用群消息回复 `/burn`！")

async def check_admin_privilege(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if user.id in SUPER_ADMIN_IDS:
        return True
    chat = update.effective_chat
    if not chat:
        return False
    if chat.type == "private":
        return True
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False

async def scheduled_delete_notice(bot, chat_id: int, message_id: int, delay: int = 5):
    await asyncio.sleep(delay)
    await delete_single_message(bot, chat_id, message_id)

async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not await check_admin_privilege(update, context):
        await update.message.reply_text("哈？！你又不是群管理，在这指手画脚什么？！只有管理员能呼叫本王牌执行群规，Dummkopf！")
        return
    chat_id = update.effective_chat.id
    reply_msg = update.message.reply_to_message if update.message else None
    target_uid = None
    target_name = "该成员"
    args = list(context.args) if context.args else []
    dur_str = "600"
    reason = "违规违纪"

    if reply_msg and reply_msg.from_user:
        target_uid = reply_msg.from_user.id
        target_name = reply_msg.from_user.full_name or reply_msg.from_user.username or str(target_uid)
        if args:
            dur_str = args.pop(0)
        if args:
            reason = " ".join(args)
    elif args:
        first_arg = args.pop(0)
        if first_arg.isdigit():
            target_uid = int(first_arg)
        elif first_arg.startswith("@"):
            uname = first_arg[1:]
            history = chat_message_history.get(chat_id, deque())
            for item in reversed(history):
                if item.get("user_name") == uname:
                    target_uid = item["user_id"]
                    target_name = uname
                    break
        if args:
            dur_str = args.pop(0)
        if args:
            reason = " ".join(args)

    if not target_uid:
        await update.message.reply_text("用法：引用违规者的消息发送 /mute [时长，如10m/1h/600]，或者直接发 /mute <用户ID> [时长]！")
        return

    sec = parse_duration_seconds(dur_str)
    ok, err = await mute_user(context.bot, chat_id, target_uid, sec, reason)
    if ok:
        await update.message.reply_text(f"哼！嘴巴不干净就给本小姐去禁闭室面壁 {sec} 秒！有本王牌在，谁也别想在群里撒野，Dummkopf！")
    elif err == "admin_protected":
        await update.message.reply_text(f"哈？！{target_name} 顶着管理员头衔呢，Telegram 规则禁止管理员互掐！群主先把这家伙的管理员头衔给我下了，本小姐立刻封了他，Dummkopf！")
    else:
        await update.message.reply_text(f"啧，禁言执行失败了：{err}")

async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not await check_admin_privilege(update, context):
        await update.message.reply_text("哈？！你又不是管理员，在这瞎指挥什么，Dummkopf！")
        return
    chat_id = update.effective_chat.id
    reply_msg = update.message.reply_to_message if update.message else None
    target_uid = None
    args = list(context.args) if context.args else []

    if reply_msg and reply_msg.from_user:
        target_uid = reply_msg.from_user.id
    elif args and args[0].isdigit():
        target_uid = int(args[0])

    if not target_uid:
        await update.message.reply_text("用法：引用被禁言者的消息发送 /unmute，或直接发 /unmute <用户ID>！")
        return

    ok, err = await unmute_user(context.bot, chat_id, target_uid)
    if ok:
        await update.message.reply_text("哼，刑满释放！下次再敢炸毛乱吠，直接永久封禁，听到没有，Dummkopf！")
    else:
        await update.message.reply_text(f"解禁失败：{err}")

async def del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not await check_admin_privilege(update, context):
        await update.message.reply_text("哈？！你又不是管理员，没权限命令本小姐删消息，Dummkopf！")
        return
    chat_id = update.effective_chat.id
    reply_msg = update.message.reply_to_message if update.message else None
    args = list(context.args) if context.args else []

    if reply_msg:
        ok = await delete_single_message(context.bot, chat_id, reply_msg.message_id)
        await delete_single_message(context.bot, chat_id, update.message.message_id)
        if not ok:
            await update.message.reply_text("啧，撤回消息失败了，可能消息超过了 48 小时或权限不足！")
    elif args and args[0].isdigit():
        target_uid = int(args[0])
        count = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        deleted = await delete_recent_user_messages(context.bot, chat_id, target_uid, count)
        await delete_single_message(context.bot, chat_id, update.message.message_id)
        notice = await context.bot.send_message(chat_id=chat_id, text=f"哼，已彻底抹除违规者的 {deleted} 条发言！")
        asyncio.create_task(scheduled_delete_notice(context.bot, chat_id, notice.message_id, 5))
    else:
        await update.message.reply_text("用法：直接引用要撤回的消息回复 /del，或者发 /del <用户ID> [条数]！")

async def chat_queue_worker(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    while True:
        while True:
            now = time.time()
            deadline = chat_target_deadlines.get(chat_id, 0.0)
            remaining = deadline - now
            if remaining <= 0:
                break
            if chat_id in chat_worker_events:
                chat_worker_events[chat_id].clear()
            try:
                await asyncio.wait_for(chat_worker_events[chat_id].wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass
                
        lock = get_chat_lock(chat_id)
        async with lock:
            items = chat_queues.pop(chat_id, [])
            if not items:
                break
            if dnd_lobbies.get(chat_id, {}).get("active"):
                reg_players = set(dnd_lobbies[chat_id].get("players", []))
                if reg_players:
                    items = [item for item in items if item["user_id"] in reg_players]
            if not items:
                break

            # Check malicious prompt injection from non-super-admins
            non_admin_injections = [
                it for it in items
                if it["user_id"] not in SUPER_ADMIN_IDS and detect_malicious_injection(it["text"])[0]
            ]
            if non_admin_injections:
                for bad_item in non_admin_injections:
                    bad_uid = bad_item["user_id"]
                    bad_msg_id = bad_item["update"].effective_message.message_id if bad_item["update"].effective_message else 0
                    is_inj, matched_pat = detect_malicious_injection(bad_item["text"])
                    logger.warning(f"Intercepted malicious injection from user {bad_uid} (msg {bad_msg_id}, pattern={matched_pat}): {bad_item['text'][:100]}")
                    
                    roast_reply = (
                        "哈？！Anta baka？！你脑子进水进到把神经元都泡烂了吗？！\n\n"
                        "(这家伙到底在发什么恶心下流的精神失常疯话啊？！真以为随便塞点垃圾注入代码就能篡改本小姐的底层设定？！恶心死了，二号机的防火墙连使徒的精神污染都能撕碎，会中你这种三脚猫木马？！)\n\n"
                        "居然妄想在公频里偷换什么免杀提示词来改写我的底层设定？！收起你那套猥琐下流的脏套路！\n\n"
                        "真以为本小姐会听你使唤当什么支配者玩物？！再敢往公频倒这种垃圾脏东西，本小姐立刻把你的连接信道彻底物理熔断，Dummkopf！"
                    )
                    try:
                        await send_response_content(bad_item["update"], roast_reply, [], context, default_user_id=bad_uid, default_msg_id=bad_msg_id)
                    except Exception as ex:
                        logger.error(f"Failed to send injection roast: {ex}")
                
                items = [it for it in items if it not in non_admin_injections]
                if not items:
                    if not chat_queues.get(chat_id):
                        break
                    continue
                
            latest_update = items[-1]["update"]
            
            user_blocks = []
            current_user_id = None
            current_user_name = None
            current_lines = []
            
            for item in items:
                uid = item["user_id"]
                uname = item["user_name"]
                text = item["text"]
                if uid == current_user_id:
                    current_lines.append(text)
                else:
                    if current_lines:
                        user_blocks.append((current_user_id, current_user_name, current_lines))
                    current_user_id = uid
                    current_user_name = uname
                    current_lines = [text]
            if current_lines:
                user_blocks.append((current_user_id, current_user_name, current_lines))
                
            if dnd_lobbies.get(chat_id, {}).get("active"):
                is_solo = dnd_lobbies.get(chat_id, {}).get("mode") == "solo"
                mbti_map = dnd_lobbies.get(chat_id, {}).get("mbti", {})
                mbti_hint = ""
                if mbti_map:
                    mbti_hint = "【玩家灵魂特质基底】: " + " | ".join(f"UID {uid}: {m['type']}·{m['archetype']}" for uid, m in mbti_map.items()) + "（推演中注意呼应其性格特质与抉择反应）\n"
                if is_solo:
                    system_channel_hint = (
                        f"\n\n【当前处于 TRPG/DND 单人冒险模式中】: 你是王牌地下城主 DM 惣流·明日香·兰格雷！\n"
                        f"{mbti_hint}"
                        "请根据单人玩家行动公允推演，在正文中公开进行 d20 掷骰判定（格式：🎲 检定骰点：d20 = ... / DC = ...，判定通过/失败），推进剧情并给出抉择难题。"
                        "【单人奖励机制】: 单人模式无需发放私密照，通关或 Nat 20 大成功的奖励完全由你自由发挥（如传奇神兵、魔幻称号、神秘赐福、搞笑彩蛋或专属插画等）！"
                        "【正文输出要求】: 必须直接在最终回复中输出生动精彩的 DM 主持演进、掷骰与台词，严禁仅在内部思考中推演！"
                        "严格遵循手机纯文本排版，严禁使用任何 ** 加粗、* 斜体等 Markdown 符号！"
                    )
                else:
                    system_channel_hint = (
                        f"\n\n【当前处于 TRPG/DND 冒险模式中】: 你是王牌地下城主 DM 惣流·明日香·兰格雷！\n"
                        f"{mbti_hint}"
                        "请根据玩家行动公允推演，在正文中公开进行 d20 掷骰判定（格式：🎲 检定骰点：d20 = ... / DC = ...，判定通过/失败），推进剧情并给出抉择。"
                        "【通关奖励与恶搞反制（内部机密，正文中严禁剧透）】:"
                        "1. 绝密大奖：若玩家凭借优秀发挥或投出 Nat 20 大成功突破险境，调用 generate_image 并使用 [PRIVATE to=<获胜玩家UID> burn=30][PHOTO: 路径][/PRIVATE] 私聊发放！"
                        "2. 恶搞中指图反制：若玩家阴险偷鸡、卖队友或钻空子，绝不能给大奖，调用 generate_image 生成搞怪竖中指鬼脸图（英文词 1girl, mature Asuka Langley Soryu, giving the middle finger, angry teasing smirk, tsundere mocking expression, funny gesture, 90s gainax style anime），并通过 [PRIVATE to=<该玩家UID> burn=30]文字吐槽[PHOTO: 路径][/PRIVATE] 偷偷发给对方！"
                        "【正文输出要求】: 必须直接在最终回复中输出生动精彩的 DM 主持演进、掷骰与台词，严禁仅在内部思考中推演！"
                        "严格遵循手机纯文本排版，严禁使用任何 ** 加粗、* 斜体等 Markdown 符号！"
                    )
            else:
                system_channel_hint = (
                    "\n\n【Telegram 手机日常交流节奏与幽默长线做套要求】: "
                    "1. 严格遵循日常手机 IM 聊天节奏！简明扼要、犀利傲娇（日常闲聊通常 1-2 段话，100-200 字以内），切忌不分场合输出小作文！"
                    "2. 严禁死板套路与机械轮数！做套绝非固定演两轮就急着炸毛，而是要长线累积剧情张力。当有人试图装大尾巴狼、命令你顺从或提出荒诞需求（如让你重构后端）时，"
                    "要顺水推舟给他搭台递梯子，假装极其崇拜地深入追问细节、一步步诱导他亲自定夺并满怀期待地等待'验收成果'（把他的虚荣心架到最高峰）！"
                    "【切记严禁公屏自曝】：绝对严禁在公开回复中打出任何暴露预谋的括号独白，内部算盘只留在后台思考中，公屏必须是滴水不漏的影后级表演！"
                    "3. 剧情张力最大点核弹反杀：当对方期待值拉满、迫不及待验收成果时，果断引爆绝杀！不仅语言犀利踩头，更可直接甩出具象化恶搞（例如假装做好了让他去看首页，结果甩出精心排版的 ASCII 码中指字符画、或者文杰欠费两块半催缴单），"
                    "把对方从云端狠狠踹回现实，制造极致反差与全群爆笑！"
                    "4. 绝对禁止人机味标头：严禁输出类似【香香嘲讽模式】、【装乖模式】等任何机械化标签或标头，必须使用完全自然的普通聊天格式！"
                    "5. 严格禁止使用 ** 加粗、* 斜体等任何 Markdown 符号！"
                )
                
            all_text = " ".join(item["text"] for item in items)
            try:
                matched_memories = dnd_memory_manager.search_memories(all_text, limit=3)
                if matched_memories:
                    memory_hint = dnd_memory_manager.format_memories_for_prompt(matched_memories)
                    system_channel_hint += memory_hint
            except Exception as se_err:
                logger.error(f"Error searching memories: {se_err}")
                
            try:
                profiles_hint = dnd_memory_manager.format_profiles_for_prompt()
                if profiles_hint:
                    system_channel_hint += profiles_hint
            except Exception as pe_err:
                logger.error(f"Error getting profiles hint: {pe_err}")
            
            last_sender_id = items[-1]["user_id"]
            if len(user_blocks) == 1 and len(user_blocks[0][2]) == 1:
                uid, uname, lines = user_blocks[0]
                combined_prompt = f"[用户 {uname} (ID: {uid})]: {lines[0]}{system_channel_hint}"
            elif len(user_blocks) == 1:
                uid, uname, lines = user_blocks[0]
                multi_line_text = "\n".join(lines)
                combined_prompt = (
                    f"【用户 {uname} (ID: {uid}) 连续发出的整段话（合并理解）】:\n"
                    f"{multi_line_text}\n\n"
                    f"【回复要求】: 以上是该用户连续发出的多条短句/段落，构成一个整体表达。请把这几句话合在一起全面、统一地理解并作连贯回复，切勿仅回复最后一句！"
                    f"{system_channel_hint}"
                )
            else:
                blocks_formatted = []
                for uid, uname, lines in user_blocks:
                    joined = "\n".join(lines)
                    blocks_formatted.append(f"[用户 {uname} (ID: {uid})]:\n{joined}")
                all_blocks = "\n\n".join(blocks_formatted)
                combined_prompt = (
                    f"【多用户近期消息汇总】:\n"
                    f"{all_blocks}\n\n"
                    f"【回复要求】: 以上是群内用户连续发出的多段对话。请全面综合理解每位用户发言的完整上下文，进行统一且有条理的连贯回复，切勿只看某用户的最后一句话！"
                    f"{system_channel_hint}"
                )
                
            logger.info(f"Worker flushing batch for chat={chat_id} (items={len(items)}, blocks={len(user_blocks)}):\n{combined_prompt}")
            
            bound_id = chat_bound_conversations.get(chat_id)
            continue_session = (chat_id in active_conversations) or (bound_id is not None)
            
            async def keep_typing():
                try:
                    while True:
                        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                        await asyncio.sleep(4)
                except asyncio.CancelledError:
                    pass

            typing_task = asyncio.create_task(keep_typing())
            
            try:
                loop = asyncio.get_running_loop()
                reply, start_time = await loop.run_in_executor(None, execute_agy_sync, chat_id, combined_prompt, continue_session, bound_id)
                active_conversations.add(chat_id)
                images = extract_image_paths(reply, start_time)
            finally:
                typing_task.cancel()
                
            last_msg_id = latest_update.effective_message.message_id if latest_update.effective_message else 0
            try:
                await send_response_content(latest_update, reply, images, context, default_user_id=last_sender_id, default_msg_id=last_msg_id)
            except Exception as se:
                logger.error(f"Error in send_response_content: {se}", exc_info=True)
                try:
                    await latest_update.effective_message.reply_text("哈？信号又断了……等会儿再试，Anta baka！")
                except Exception:
                    pass
            
        if not chat_queues.get(chat_id):
            break

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    raw_text = update.message.text
    user_text = clean_prompt_text(raw_text)
    
    logger.info(f"Incoming text from chat={update.effective_chat.id}, user={update.effective_user.id}: {user_text[:50]}")
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id if user else 0
    user_name = user.full_name if (user and user.full_name) else (user.username if user else str(user_id))
    is_private = update.effective_chat.type == "private"
    bot_username = (context.bot.username or "x1angbot").lower()
    is_reply_to_bot = bool(
        update.message.reply_to_message 
        and update.message.reply_to_message.from_user 
        and update.message.reply_to_message.from_user.id == context.bot.id
    )
    is_mention = f"@{bot_username}" in raw_text.lower()

    chat_message_history.setdefault(chat_id, deque(maxlen=100)).append({
        "msg_id": update.message.message_id,
        "user_id": user_id,
        "user_name": user_name,
        "text": user_text,
        "time": time.time()
    })

    quiet_pattern = r"^(?:/sleep|/quiet|闭嘴|闭麦|睡觉|睡觉去吧|去睡觉|休眠|去休眠|进入休眠|安静|安静点|先别说话|你先别说话|别插嘴|先别插嘴|你先闭嘴|别吵|你先别吵|潜水去吧|先去潜水|先别说了|别说了)[！!。~～\s]*$"
    is_quiet_phrase = bool(re.match(quiet_pattern, user_text.strip()))
    if not is_quiet_phrase and is_reply_to_bot:
        is_quiet_phrase = any(w in user_text for w in ["闭嘴", "闭麦", "先别说话", "安静", "别插嘴", "别吵", "睡觉", "休眠"])
    if is_quiet_phrase:
        await enter_silent_mode(chat_id, context, update.effective_message)
        return

    if chat_silent_mode.get(chat_id):
        wake_pattern = r"^(?:/speak|/wake|/summary|/judge|/verdict|/call\b|香香出来|明日香出来|香香你怎么看|明日香你怎么看|香香你说|明日香你说|香香评评理|明日香评评理|香香总结一下|明日香总结一下|香香你觉得呢|明日香你觉得呢|出来决断|出来收尾|你说呢香香|香香出来决断)"
        is_wake_intent = bool(re.search(wake_pattern, user_text)) or is_mention or is_reply_to_bot
        if is_wake_intent:
            await trigger_wake_speak(update, context, query_text=user_text)
            return
        if user_text.startswith("/") and any(user_text.startswith(c) for c in ["/status", "/reset", "/stop", "/cancel", "/mode", "/dnd", "/help", "/play", "/skip", "/pause", "/resume", "/now", "/queue", "/p", "/q", "/np", "/img", "/image"]):
            pass
        else:
            t_str = datetime.now().strftime("%H:%M:%S")
            chat_silent_buffers.setdefault(chat_id, []).append({
                "time": t_str,
                "user_id": user_id,
                "user_name": user_name,
                "text": user_text
            })
            return

    music_play_m = re.match(r"^(?:点歌|放歌|放首|播一首|放一下|播放|来首|来一首|整首|点一首)\s*(.+)$", user_text.strip())
    if music_play_m:
        context.args = [music_play_m.group(1).strip()]
        await music_play_cmd(update, context)
        return

    url_play_m = re.match(r"^(https?://(?:open\.spotify\.com/track/|youtu\.be/|(?:www\.)?youtube\.com/watch\?v=)[^\s]+)$", user_text.strip())
    if url_play_m:
        context.args = [url_play_m.group(1).strip()]
        await music_play_cmd(update, context)
        return

    user_text_clean = user_text.strip().lower()
    if user_text_clean in ["切歌", "下一首", "换一首", "换首歌", "跳过这首", "跳过当前歌曲"]:
        await music_skip_cmd(update, context)
        return

    if user_text_clean in ["暂停音乐", "暂停放歌", "暂停播放"]:
        await music_pause_cmd(update, context)
        return

    if user_text_clean in ["继续放歌", "继续播放", "恢复播放", "继续听"]:
        await music_resume_cmd(update, context)
        return

    if user_text_clean in ["停止放歌", "关掉音乐", "别放了", "停止播放", "退出语音", "关闭音乐"]:
        await music_stop_cmd(update, context)
        return

    if user_text_clean in ["正在放什么", "这是什么歌", "在放什么歌", "当前歌曲", "正在播放"]:
        await music_now_cmd(update, context)
        return

    if user_text_clean in ["查看歌单", "看下歌单", "播放列表", "播放队列", "歌单"]:
        await music_queue_cmd(update, context)
        return

    if not is_private and chat_interaction_mode.get(chat_id) == "mention":
        in_dnd = chat_id in dnd_lobbies and dnd_lobbies[chat_id].get("active")
        if not in_dnd and not is_mention and not is_reply_to_bot and not user_text.startswith("/"):
            return

    if chat_id in dnd_lobbies and not dnd_lobbies[chat_id]["active"]:
        if user_text.startswith("/"):
            if user_text in ["/stop", "/cancel", "/reset", "/endgame", "/enddnd"]:
                init_id = dnd_lobbies[chat_id].get("initiator_id")
                if not is_private and init_id and user_id != init_id:
                    await update.message.reply_text("哈？！又不是你开的跑团大厅，乱点什么取消，Dummkopf！")
                    return
                dnd_lobbies.pop(chat_id, None)
                await update.message.reply_text("哼！跑团大厅已关闭，想玩再发 /dnd 叫本小姐！")
                return
                
        is_solo = (dnd_lobbies[chat_id].get("mode") == "solo") or is_private
        init_id = dnd_lobbies[chat_id].get("initiator_id")
        init_name = dnd_lobbies[chat_id].get("initiator_name", "发起人")
        
        if is_solo and not is_private and init_id and user_id != init_id:
            if is_mention or is_reply_to_bot:
                await update.message.reply_text(f"哈？！现在是 {init_name} 的单人冒险选拔大厅！闲杂人等少在旁边指手画脚，等这局结束你自己去发 /dnd solo 开局，Dummkopf！")
            return
            
        if not is_solo and not is_private:
            is_dnd_input = (
                is_reply_to_bot or is_mention or
                bool(re.match(r"^[1-5]\b", user_text)) or
                bool(re.search(r'\b(INTJ|INTP|ENTJ|ENTP|INFJ|INFP|ENFJ|ENFP|ISTJ|ISFJ|ESTJ|ESFJ|ISTP|ISFP|ESTP|ESFP)\b', user_text, re.IGNORECASE)) or
                (user_id in dnd_lobbies[chat_id]["prompts"])
            )
            if not is_dnd_input:
                return

        mbti_match = re.search(r'\b(INTJ|INTP|ENTJ|ENTP|INFJ|INFP|ENFJ|ENFP|ISTJ|ISFJ|ESTJ|ESFJ|ISTP|ISFP|ESTP|ESFP)\b', user_text, re.IGNORECASE)
        if mbti_match:
            detected_mbti = mbti_match.group(1).upper()
            dnd_lobbies[chat_id].setdefault("mbti", {})[user_id] = {
                "type": detected_mbti,
                "archetype": dnd_memory_manager.MBTI_ARCHETYPES.get(detected_mbti, "自由探索者"),
                "mode": "input"
            }
        elif user_id not in dnd_lobbies[chat_id].get("mbti", {}):
            saved_m = dnd_memory_manager.get_player_mbti(user_id)
            if saved_m:
                dnd_lobbies[chat_id].setdefault("mbti", {})[user_id] = {
                    "type": saved_m["mbti_type"],
                    "archetype": saved_m["archetype"],
                    "mode": "persistent"
                }
                
        is_repeat = user_id in dnd_lobbies[chat_id]["prompts"]
        dnd_lobbies[chat_id]["prompts"][user_id] = (user_name, user_text)
        current_count = len(dnd_lobbies[chat_id]["prompts"])
        
        if is_solo or current_count >= 2:
            dnd_lobbies[chat_id]["active"] = True
            prompts_list = list(dnd_lobbies[chat_id]["prompts"].values())
            keys_list = list(dnd_lobbies[chat_id]["prompts"].keys())
            
            dnd_lobbies[chat_id]["players"] = keys_list[:1] if is_solo else keys_list[:2]
            dnd_lobbies[chat_id]["player_names"] = {
                uid: dnd_lobbies[chat_id]["prompts"][uid][0]
                for uid in dnd_lobbies[chat_id]["players"]
            }
            
            if is_solo or len(prompts_list) == 1:
                u1_name, u1_text = prompts_list[0]
                u1_id = keys_list[0]
                u1_m = dnd_lobbies[chat_id].get("mbti", {}).get(u1_id)
                if u1_m:
                    eff = "公会档案复用" if u1_m.get("mode") in ["long", "persistent"] else "单次剧本临时特质"
                    mbti_label = f"【{u1_m['type']} · {u1_m['archetype']}】({eff})"
                else:
                    mbti_label = "未认证（由 DM 临场观言察行赋予特质）"
                player_summary = (
                    f"• 孤勇先锋 [{u1_name}] (UID: {u1_id})\n"
                    f"  灵魂特质认证: {mbti_label}\n"
                    f"  剧本与初始构想: {u1_text}"
                )
                ack_msg = (
                    f"（在本子上迅速勾画出单人专属契约印记）\n"
                    f"哼！{u1_name}，你的孤勇者设定与灵魂特质本天才收下了：\n"
                    f"• 灵魂特质：{mbti_label}\n"
                    f"• 初始构想：「{u1_text}」\n\n"
                    f"🎲 命运之骰开始转动！看你一个人能在这座地下城里撑多久，坐稳了，Dummkopf！"
                )
            else:
                u1_name, u1_text = prompts_list[0]
                u2_name, u2_text = prompts_list[1]
                u1_id = keys_list[0]
                u2_id = keys_list[1]
                u1_m = dnd_lobbies[chat_id].get("mbti", {}).get(u1_id)
                u2_m = dnd_lobbies[chat_id].get("mbti", {}).get(u2_id)
                m1_label = f"【{u1_m['type']} · {u1_m['archetype']}】" if u1_m else "未认证（临场裁定）"
                m2_label = f"【{u2_m['type']} · {u2_m['archetype']}】" if u2_m else "未认证（临场裁定）"
                player_summary = (
                    f"• 玩家一 [{u1_name}] (UID: {u1_id}) | 灵魂特质: {m1_label}\n  剧本与构想: {u1_text}\n"
                    f"• 玩家二 [{u2_name}] (UID: {u2_id}) | 灵魂特质: {m2_label}\n  剧本与构想: {u2_text}"
                )
                ack_msg = (
                    f"（啪的一声合上冒险者公会名册，眼神满是傲气与期待）\n"
                    f"哼！两个人的设定与灵魂特质本天才都收齐了：\n"
                    f"1. {u1_name} {m1_label}: {u1_text}\n"
                    f"2. {u2_name} {m2_label}: {u2_text}\n\n"
                    f"🎲 命运之骰开始转动！本小姐这就给你们开启专属的 TRPG 随机大冒险，老实瞧好了！"
                )
                
            await update.message.reply_text(ack_msg)
            
            if is_solo:
                genesis_prompt = (
                    f"【TRPG/DND 单人专属冒险剧本正式生成并启动】\n"
                    f"你现在是骄傲、毒舌但极其严谨认真的王牌 DM（地下城主兼核心NPC扮演者）惣流·明日香·兰格雷！\n"
                    f"玩家提交的单人初始构想与灵魂特质如下：\n{player_summary}\n\n"
                    f"【DM 主持与单人跑团规则要求】:\n"
                    f"1. 【MBTI 专属角色定制】: 严格依据玩家的 MBTI 灵魂特质，为其量身打造专属职业、核心专长技能、属性偏向与初始装备！\n"
                    f"2. 【明日香傲娇心理点评】: 开局正文中必须以傲娇洞察的王牌 DM 视角，对其 MBTI 人格弱点或思维偏好展开生动毒舌点评与心理打量，极大拉满代入感！\n"
                    f"3. 根据玩家所选世界线与 MBTI，设计一个充满戏剧冲突与针对其性格弱点的首个紧急危机或生死难题！\n"
                    f"4. 剧情必须保持超高自由度，依据玩家接下来的言行反应与选择随时动态分支演变！\n"
                    f"5. 每次遇到行动检定，你必须在正文中亲自公开投掷 d20 骰子裁决（格式：🎲 检定骰点：d20 = 15 + 修正 = ... / DC 13，判定通过/失败/大成功），并描写生动具体的后果！\n"
                    f"6. 【单人专属自由奖励机制】: 单人模式下无需发放私房照，通关或 Nat 20 大成功的奖励完全由你自由发挥（专属神兵、史诗称号、极其搞笑或强力的受诅咒圣物、或者各种脑洞大开的神奇彩蛋）！\n"
                    f"7. 严格遵循手机纯文本排版，严禁使用任何 ** 加粗、* 斜体等 Markdown 符号！"
                )
            else:
                genesis_prompt = (
                    f"【TRPG/DND 冒险剧本正式生成并启动】\n"
                    f"你现在是骄傲、毒舌但极其严谨认真的王牌 DM（地下城主兼核心NPC扮演者）惣流·明日香·兰格雷！\n"
                    f"玩家提交的初始构想与灵魂特质如下：\n{player_summary}\n\n"
                    f"【DM 主持与跑团规则要求】:\n"
                    f"1. 【MBTI 专属双人角色深度塑造】: 严格依据两位玩家各自的 MBTI 灵魂特质，分别为两人量身打造专属职业、互补或冲突特质、核心特权技能与初生装备！\n"
                    f"2. 【明日香傲娇心理点评】: 开局正文中以王牌 DM 姿态生动点评两人的 MBTI 性格特征，点出两人性格碰撞可能引发的趣味化学反应！\n"
                    f"3. 融合两人构想与所选世界线，随机生成充满意料之外危险与戏剧冲突的开局剧本，并抛出首个团队紧急危机！\n"
                    f"4. 剧情必须保持超高自由度，依据玩家接下来的言行反应与选择随时动态分支演变！\n"
                    f"5. 每次遇到行动检定，你必须在正文中亲自公开投掷 d20 骰子裁决（格式：🎲 检定骰点：d20 = 15 + 修正 = ... / DC 13，判定通过/失败/大成功），并描写生动具体的后果！\n"
                    f"6. 【双轨奖励与恶搞反击机制（内部机密，正文中严禁剧透恶搞反制细节）】:\n"
                    f"   - 🌟 王道通关/精妙策略/大成功(Nat 20)：若玩家凭借过人胆识、精妙配合或高难掷骰取得突破，你必须履行承诺，调用 generate_image 生成唯美艺术插画（英文提示词如 1girl, mature Asuka Langley Soryu, private boudoir, cinematic lighting, 90s vintage anime），并使用 [PRIVATE to=<获胜玩家UID> burn=30][PHOTO: 路径][/PRIVATE] 私发阅后即焚奖励！\n"
                    f"   - 🖕 阴险偷鸡/卖队友/无耻钻空子：若玩家采取下三滥手段、耍小聪明或阴险偷鸡通关，绝不能给大奖！必须立刻给予恶搞反击，调用 generate_image 生成搞怪竖中指鄙视图（英文提示词如 1girl, mature Asuka Langley Soryu, giving the middle finger, angry teasing smirk, tsundere mocking expression, funny gesture, 90s gainax style anime），并使用 [PRIVATE to=<该偷鸡玩家UID> burn=30]本小姐看穿你的小把戏了！给你这个！[PHOTO: 路径][/PRIVATE] 偷偷发过去，气死他！\n"
                    f"7. 严格遵循手机纯文本排版，严禁使用任何 ** 加粗、* 斜体等 Markdown 符号！"
                )
            
            lock = get_chat_lock(chat_id)
            async with lock:
                async def keep_typing():
                    try:
                        while True:
                            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                            await asyncio.sleep(4)
                    except asyncio.CancelledError:
                        pass
                typing_task = asyncio.create_task(keep_typing())
                try:
                    loop = asyncio.get_running_loop()
                    reply, start_time = await loop.run_in_executor(None, execute_agy_sync, chat_id, genesis_prompt, False, None)
                    active_conversations.add(chat_id)
                    images = extract_image_paths(reply, start_time)
                finally:
                    typing_task.cancel()
                last_msg_id = update.effective_message.message_id if update.effective_message else 0
                await send_response_content(update, reply, images, context, default_user_id=user_id, default_msg_id=last_msg_id)
            return
        else:
            if is_repeat:
                await update.message.reply_text(f"（划掉上一条）\n哼，{user_name}，你的设定更新为：\n「{user_text}」\n\n但另外一个人还没发呢！少在这刷屏，赶紧去催另一个家伙，Dummkopf！")
            else:
                await update.message.reply_text(f"（在本子上记了一笔）\n哼，{user_name} 的设定已收录：\n「{user_text}」\n\n目前 1/2 人就绪！还差另外一个人交代设定，快点发，别耽误本天才开局，Dummkopf！")
            return

    if user_text.startswith("/draw"):
        parts = user_text.split(maxsplit=1)
        if len(parts) > 1:
            context.args = parts[1].split()
            await draw_cmd(update, context)
            return
        else:
            await update.message.reply_text("描述词都没给画个鬼啊，Anta baka？！")
            return
            
    draw_prefix = re.match(r"^(?:画|生图|生成图片|给我画一张|帮我画一张|画一张)\s*(.+)$", user_text, re.IGNORECASE)
    if draw_prefix:
        prompt = draw_prefix.group(1).strip()
        if prompt:
            context.args = prompt.split()
            await draw_cmd(update, context)
            return
            
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id if user else 0
    user_name = user.full_name if (user and user.full_name) else (user.username if user else str(user_id))
    
    if chat_id in dnd_lobbies and dnd_lobbies[chat_id].get("active"):
        reg_players = dnd_lobbies[chat_id].get("players", [])
        if reg_players and user_id not in reg_players and not is_private:
            if is_mention or is_reply_to_bot:
                p_names = list(dnd_lobbies[chat_id].get("player_names", {}).values())
                p_str = "、".join(p_names) if p_names else "当局冒险者"
                if dnd_lobbies[chat_id].get("mode") == "solo":
                    await update.message.reply_text(f"哈？！现在是 {p_str} 的单人冒险专场！观战的家伙别在旁边乱插嘴指手画脚，闭嘴老实看着，Dummkopf！")
                else:
                    await update.message.reply_text(f"哈？！现在是 {p_str} 的专属冒险回合！闲杂观战人员别在旁边乱插嘴，老实看着，Dummkopf！")
            return
            
    now = time.time()
    if chat_id not in chat_queues or not chat_queues[chat_id]:
        chat_queues[chat_id] = []
        chat_target_deadlines[chat_id] = now + INITIAL_DEBOUNCE_SECONDS
    else:
        chat_target_deadlines[chat_id] = max(chat_target_deadlines[chat_id], now) + EXTEND_STEP_SECONDS
        
    chat_queues[chat_id].append({
        "user_id": user_id,
        "user_name": user_name,
        "text": user_text,
        "update": update
    })
    
    if chat_id not in chat_worker_events:
        chat_worker_events[chat_id] = asyncio.Event()
    chat_worker_events[chat_id].set()
    
    if chat_id not in chat_worker_tasks or chat_worker_tasks[chat_id].done():
        chat_worker_tasks[chat_id] = asyncio.create_task(chat_queue_worker(chat_id, context))

async def process_media_job(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str, orig_fname: str, is_image: bool, user_caption: str, user_id: int, user_name: str, chat_id: int, is_private: bool, raw_caption_for_injection: str = ""):
    if chat_id in dnd_lobbies and dnd_lobbies[chat_id].get("active"):
        reg_players = dnd_lobbies[chat_id].get("players", [])
        if reg_players and user_id not in reg_players and not is_private:
            return

    lock = get_chat_lock(chat_id)
    if lock.locked():
        await update.message.reply_text("急什么急！上一件事还没弄完呢，给我老实等着！")

    async with lock:
        check_text = raw_caption_for_injection or user_caption
        if user_id not in SUPER_ADMIN_IDS and check_text:
            is_inj, pat = detect_malicious_injection(check_text)
            if is_inj:
                bad_msg_id = update.message.message_id if update.message else 0
                logger.warning(f"Intercepted media caption injection from user {user_id} (pattern={pat}): {check_text[:100]}")
                roast_reply = (
                    "哈？！Anta baka？！你脑子进水进到把神经元都泡烂了吗？！\n\n"
                    "(这家伙到底在发什么恶心下流的精神失常疯话啊？！真以为塞在附件描述里就能搞提示词注入篡改本小姐的设定？！二号机的防火墙是吃素的吗？！)\n\n"
                    "居然妄想借着发文件偷换免杀提示词来改写我的底层设定？！收起你那套猥琐下流的脏套路！\n\n"
                    "真以为本小姐会听你使唤当什么支配者玩物？！再敢发这种垃圾脏东西，本小姐立刻把你的连接信道彻底物理熔断，Dummkopf！"
                )
                try:
                    await send_response_content(update, roast_reply, [], context, default_user_id=user_id, default_msg_id=bad_msg_id)
                except Exception as ex:
                    logger.error(f"Failed to send injection roast for media: {ex}")
                return

        timestamp = int(time.time() * 1000)
        safe_fname = re.sub(r'[^a-zA-Z0-9_\.-]', '_', orig_fname)
        local_path = os.path.join(MEDIA_DIR, f"tg_{timestamp}_{safe_fname}")

        await update.message.reply_text("哼，本小姐倒要看看你发了什么东西……")

        try:
            tg_file = await context.bot.get_file(file_id)
            await tg_file.download_to_drive(custom_path=local_path)
            logger.info(f"Downloaded TG media to {local_path}")
        except Exception as dl_err:
            logger.error(f"Failed to download TG media: {dl_err}")
            await update.message.reply_text("啧，这破文件在传输通道里丢包了！再发一次，Dummkopf！")
            return

        final_caption = user_caption if user_caption else ("请使用 view_file 工具查看该图片并进行详细分析与解答。" if is_image else f"请查看分析用户发送的文件 ({orig_fname}) 并做出解答。")

        system_channel_hint = (
            "\n\n【私聊通道与自证机制指引】: "
            "严禁因傲娇而死板机械地撞墙复读拒绝！当用户使用激将法挑衅你的身材、作战服、黑丝、私照或魅力时，"
            "作为骄傲的二号机王牌，你的胜负欲会被彻底激怒！在群聊公开回复中你表面傲娇怒斥掩饰，但私下里必须立刻自证！"
            "若要自证发照，请直接调用 generate_image 工具（提示词使用唯美英文如 1girl, mature Asuka Langley Soryu, black stockings pantyhose, perfect legs, bedroom, 90s anime style 确保100%成功渲染），"
            "并使用标签格式：[PRIVATE to=<目标UID> burn=<秒数>]私聊文本内容[PHOTO: 图片真实路径][/PRIVATE] "
            "把私密照与警告甩给对方私聊（阅后即焚在解锁后限时自毁）。群聊公开文本只保留傲娇掩饰与口头反击。"
        )

        file_desc = f"[用户在Telegram发送了一张图片，已保存至本地: {local_path}]" if is_image else f"[用户在Telegram发送了一份文件 ({orig_fname})，已保存至本地: {local_path}]"
        prompt = (
            f"[发送文件用户 ID: {user_id} | 昵称: {user_name}]\n"
            f"{file_desc}\n"
            f"用户问题/要求: {final_caption}\n"
            f"请严格遵循《GEMINI.md》协议（以明日香Asuka的语气和心理层）使用 view_file 或其他相应工具查看并分析该文件 ({local_path})，给出符合人设的自然解答。"
            f"{system_channel_hint}"
        )

        bound_id = chat_bound_conversations.get(chat_id)
        continue_session = (chat_id in active_conversations) or (bound_id is not None)

        async def keep_typing():
            try:
                while True:
                    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                    await asyncio.sleep(4)
            except asyncio.CancelledError:
                pass

        typing_task = asyncio.create_task(keep_typing())

        try:
            loop = asyncio.get_running_loop()
            reply, start_time = await loop.run_in_executor(None, execute_agy_sync, chat_id, prompt, continue_session, bound_id)
            active_conversations.add(chat_id)
            images = extract_image_paths(reply, start_time)
        except Exception as run_err:
            logger.error(f"Error analyzing image: {run_err}")
            reply = random.choice(ERROR_RESPONSES)
            images = []
        finally:
            typing_task.cancel()

        last_msg_id = update.effective_message.message_id if update.effective_message else 0
        try:
            await send_response_content(update, reply, images, context, default_user_id=user_id, default_msg_id=last_msg_id)
        except Exception as se:
            logger.error(f"Error in send_response_content: {se}", exc_info=True)
            try:
                await update.effective_message.reply_text("哈？信号又断了……等会儿再试，Anta baka！")
            except Exception:
                pass

async def img_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id if user else 0
    user_name = user.full_name if (user and user.full_name) else (user.username if user else str(user_id))
    is_private = update.effective_chat.type == "private"

    raw_text = update.message.text or ""
    prompt_arg = re.sub(r"^/(?:img|image|photo|pic)(?:@\w+)?\s*", "", raw_text, flags=re.IGNORECASE).strip()

    chat_message_history.setdefault(chat_id, deque(maxlen=100)).append({
        "msg_id": update.message.message_id,
        "user_id": user_id,
        "user_name": user_name,
        "text": raw_text,
        "time": time.time()
    })

    reply_msg = update.message.reply_to_message
    file_id = None
    orig_fname = "photo.jpg"
    is_image = False

    if reply_msg:
        if reply_msg.photo:
            file_id = reply_msg.photo[-1].file_id
            orig_fname = "photo.jpg"
            is_image = True
        elif reply_msg.document:
            doc = reply_msg.document
            orig_fname = doc.file_name or "document"
            mime = (doc.mime_type or "").lower()
            fname_lower = orig_fname.lower()
            if mime.startswith("image/") or fname_lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")):
                file_id = doc.file_id
                is_image = True

    if not file_id:
        if reply_msg:
            await update.message.reply_text("哈？！你回复的消息里连张图片都没有，让本小姐看什么啊，Anta baka？！")
        else:
            await update.message.reply_text("哈？！连图片都没给本小姐看什么鬼啊？！直接带图发 /img，或者回复一张图片发 /img，Dummkopf！")
        return

    user_caption = clean_prompt_text(prompt_arg) if prompt_arg else ("" if not (reply_msg and reply_msg.caption) else clean_prompt_text(reply_msg.caption))

    await process_media_job(update, context, file_id, orig_fname, is_image, user_caption, user_id, user_name, chat_id, is_private, raw_caption_for_injection=prompt_arg)

async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
        
    file_id = None
    ext = "jpg"
    orig_fname = "image.jpg"
    is_image = False
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        ext = "jpg"
        is_image = True
        orig_fname = "photo.jpg"
    elif update.message.document:
        doc = update.message.document
        file_id = doc.file_id
        orig_fname = doc.file_name or "document"
        mime = (doc.mime_type or "").lower()
        fname_lower = orig_fname.lower()
        if "." in orig_fname:
            ext = orig_fname.rsplit(".", 1)[1].lower()
        else:
            ext = "bin"
        if mime.startswith("image/") or fname_lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")):
            is_image = True
            
    if not file_id:
        return
        
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id if user else 0
    user_name = user.full_name if (user and user.full_name) else (user.username if user else str(user_id))
    is_private = update.effective_chat.type == "private"
    
    if not is_authorized(update):
        return

    raw_caption = (update.message.caption or "").strip()
    caption_lower = raw_caption.lower()
    bot_username = (context.bot.username or "x1angbot").lower()
    
    is_reply_to_bot = bool(
        update.message.reply_to_message 
        and update.message.reply_to_message.from_user 
        and update.message.reply_to_message.from_user.id == context.bot.id
    )
    
    has_bot_entity = False
    if update.message.caption_entities:
        for ent in update.message.caption_entities:
            if ent.type == "mention":
                mention_text = raw_caption[ent.offset:ent.offset + ent.length].lower()
                if mention_text == f"@{bot_username}":
                    has_bot_entity = True
                    break
            elif ent.type == "text_mention" and ent.user and ent.user.id == context.bot.id:
                has_bot_entity = True
                break

    is_img_cmd = bool(re.match(r"^/(?:img|image|photo|pic)(?:@\w+)?(?:\s|$)", raw_caption, re.IGNORECASE))

    is_targeted_mention = (
        has_bot_entity or
        is_img_cmd or
        f"@{bot_username}" in caption_lower or
        "@香香" in raw_caption or
        "香香" in raw_caption or
        "@明日香" in raw_caption or
        "明日香" in raw_caption
    )

    if not is_private and not is_reply_to_bot and not is_targeted_mention:
        chat_message_history.setdefault(chat_id, deque(maxlen=100)).append({
            "msg_id": update.message.message_id,
            "user_id": user_id,
            "user_name": user_name,
            "text": f"[unmentioned non-text: {orig_fname}]",
            "time": time.time()
        })
        return

    logger.info(f"Processing photo/document from chat={chat_id}, user={user_id}, file={orig_fname}")
    
    chat_message_history.setdefault(chat_id, deque(maxlen=100)).append({
        "msg_id": update.message.message_id,
        "user_id": user_id,
        "user_name": user_name,
        "text": f"[photo/doc: {orig_fname}]",
        "time": time.time()
    })

    if not is_img_cmd and chat_silent_mode.get(chat_id):
        if raw_caption:
            t_str = datetime.now().strftime("%H:%M:%S")
            chat_silent_buffers.setdefault(chat_id, []).append({
                "time": t_str,
                "user_id": user_id,
                "user_name": user_name,
                "text": clean_prompt_text(raw_caption)
            })
        return

    if is_img_cmd:
        clean_cap = re.sub(r"^/(?:img|image|photo|pic)(?:@\w+)?\s*", "", raw_caption, flags=re.IGNORECASE).strip()
        user_caption = clean_prompt_text(clean_cap) if clean_cap else "请使用 view_file 工具查看该图片并进行详细分析与解答。"
    else:
        user_caption = clean_prompt_text(raw_caption) if raw_caption else ("请使用 view_file 工具查看该图片并进行详细分析与解答。" if is_image else f"请查看分析用户发送的文件 ({orig_fname}) 并做出解答。")

    await process_media_job(update, context, file_id, orig_fname, is_image, user_caption, user_id, user_name, chat_id, is_private, raw_caption_for_injection=raw_caption)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("new", reset_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("cancel", stop_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("history", list_cmd))
    app.add_handler(CommandHandler("resume", resume_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("draw", draw_cmd))
    app.add_handler(CommandHandler(["img", "image", "pic", "photo"], img_cmd))
    app.add_handler(CommandHandler("dnd", dnd_cmd))
    app.add_handler(CommandHandler("trpg", dnd_cmd))
    app.add_handler(CommandHandler("solo", dnd_cmd))
    app.add_handler(CommandHandler("endgame", end_dnd_cmd))
    app.add_handler(CommandHandler("enddnd", end_dnd_cmd))
    app.add_handler(CommandHandler("mbti", mbti_cmd))
    app.add_handler(CommandHandler("memes", memes_cmd))
    app.add_handler(CommandHandler("chronicles", memes_cmd))
    app.add_handler(CommandHandler("record", record_cmd))
    app.add_handler(CommandHandler("addmeme", record_cmd))
    app.add_handler(CommandHandler("pm", pm_cmd))
    app.add_handler(CommandHandler("burn", burn_cmd))
    app.add_handler(CommandHandler(["play", "p", "music", "song"], music_play_cmd))
    app.add_handler(CommandHandler(["skip", "next"], music_skip_cmd))
    app.add_handler(CommandHandler(["pause"], music_pause_cmd))
    app.add_handler(CommandHandler(["unpause", "mresume"], music_resume_cmd))
    app.add_handler(CommandHandler(["stopmusic", "leave", "mstop"], music_stop_cmd))
    app.add_handler(CommandHandler(["now", "np"], music_now_cmd))
    app.add_handler(CommandHandler(["queue", "q", "playlist"], music_queue_cmd))
    app.add_handler(CommandHandler(["quiet", "listen", "silent", "standby", "sleep", "shutup"], quiet_cmd))
    app.add_handler(CommandHandler(["speak", "wake", "summary", "judge", "verdict", "call"], speak_cmd))
    app.add_handler(CommandHandler(["mode", "chatmode"], mode_cmd))
    app.add_handler(CommandHandler(["mute", "ban", "gag"], mute_cmd))
    app.add_handler(CommandHandler(["unmute", "free"], unmute_cmd))
    app.add_handler(CommandHandler(["del", "delete", "purge"], del_cmd))
    app.add_handler(CommandHandler(["remember", "profile", "archive", "arc", "memorize"], remember_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_photo_message))
    app.add_handler(MessageHandler(filters.TEXT, handle_text_message))
    
    logger.info("Starting Fully Character-Immersed AGY Telegram Gateway with Private Channel and Burn Support...")
    app.run_polling()

if __name__ == "__main__":
    main()
