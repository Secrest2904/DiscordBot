import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import json
import random
import re
from datetime import datetime, timedelta, timezone

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "accounts.json")
STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")

GENERAL_CHANNEL_NAME = "general"
CASINO_CHANNEL_NAME = "casino"
GUILD_ID = None

ADMIN_ROLE_NAME = "Miku Fanclub"
OWNER_ROLE_NAME = "GenkiJi"

active_blackjack_games = {}
active_quote_games = {}
active_shops = {}

# The server has always referred to its clock as PST.  A fixed UTC-8 timezone
# keeps saved timestamps predictable even on Windows hosts without tzdata.
PST = timezone(timedelta(hours=-8), name="PST")
SHOP_REACTIONS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]

# ───────────────────────
# Persistence helpers
# ───────────────────────
def load_json_file(path, default):
    try:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=4)
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"JSON LOAD ERROR ({path}):", e)
        return default

def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_accounts():
    return load_json_file(DATA_FILE, {})

def save_accounts(data):
    save_json_file(DATA_FILE, data)

def load_state():
    return load_json_file(STATE_FILE, {"attached_users": []})

def save_state(data):
    save_json_file(STATE_FILE, data)

def get_attached_users():
    state = load_state()
    return set(state.get("attached_users", []))

def set_attached_users(user_ids):
    state = load_state()
    state["attached_users"] = list(user_ids)
    save_state(state)

def has_role(member, role_name):
    return any(role.name == role_name for role in member.roles)

def get_account(user):
    accounts = load_accounts()
    uid = str(user.id)

    if uid not in accounts:
        accounts[uid] = {
            "name": user.name,
            "balance": 1000
        }
        save_accounts(accounts)

    return accounts

def ensure_account(accounts, user):
    """Migrate old account rows without invalidating existing account files."""
    uid = str(user.id)
    account = accounts.setdefault(uid, {"name": user.name, "balance": 1000})
    account.setdefault("name", user.name)
    account.setdefault("balance", 1000)
    account.setdefault("inventory", [])
    account.setdefault("last_gambling_loss", None)
    return account

def pst_now():
    return datetime.now(PST)

def parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=PST)
    except (TypeError, ValueError):
        return None

def expiry_for_rarity(legendary=False):
    now = pst_now()
    days_ahead = 2 if legendary else 0
    return (now + timedelta(days=days_ahead)).replace(
        hour=23, minute=59, second=59, microsecond=0
    )

def is_mostly_caps(text: str, threshold: float = 0.7) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 6:
        return False
    caps = sum(1 for c in letters if c.isupper())
    return (caps / len(letters)) >= threshold

def has_repeated_punctuation(text: str) -> bool:
    return "??" in text or "!!" in text or "!?" in text or "?!" in text

# ───────────────────────
# Role / permission helpers
# ───────────────────────
def has_named_role(member, role_name: str) -> bool:
    return any(role.name.upper() == role_name.upper() for role in member.roles)

def is_admin_user(member: discord.Member) -> bool:
    return (
        has_named_role(member, ADMIN_ROLE_NAME)
        or has_named_role(member, OWNER_ROLE_NAME)
        or member.guild_permissions.administrator
    )

def is_owner_user(member: discord.Member) -> bool:
    return has_named_role(member, OWNER_ROLE_NAME)

def in_casino(ctx):
    return ctx.channel.name == CASINO_CHANNEL_NAME or ctx.author.guild_permissions.administrator

# ───────────────────────
# Blackjack utilities
# ───────────────────────
SUITS = ["♠️", "♥️", "♦️", "♣️"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

def draw_card():
    return random.choice(RANKS), random.choice(SUITS)

def hand_value(hand):
    value = 0
    aces = 0

    for rank, _ in hand:
        if rank in ["J", "Q", "K"]:
            value += 10
        elif rank == "A":
            value += 11
            aces += 1
        else:
            value += int(rank)

    while value > 21 and aces:
        value -= 10
        aces -= 1

    return value

def render_hand(hand):
    return " ".join(f"{r}{s}" for r, s in hand)

# ───────────────────────
# Personality data
# ───────────────────────
DEFAULT_REPLIES = [
    "Good.",
    "Carry on.",
    "I'm watching.",
    "Proceed.",
    "Noted.",
    "Stay focused.",
    "I heard you.",
    "Keep going.",
    "Fine.",
    "Accepted.",
    "Understood.",
    "Continue.",
    "Go on, then.",
    "I see.",
    "Mm.",
    "That's enough for now.",
    "Alright.",
    "Very well.",
    "You have my attention.",
    "I'm still here.",
    "Keep talking.",
    "Try saying that properly.",
    "You're being observed.",
    "I noticed.",
    "So you do know how to speak.",
    "Good. Maintain that.",
    "That will do.",
    "You aren't dismissed.",
    "Say more.",
    "I expected as much.",
    "Behave and continue.",
    "You're fine. Continue.",
    "You have a point.",
    "I'm considering it.",
    "We'll see.",
    "Don't waste my attention.",
    "You may continue.",
    "I'm still listening.",
    "Not terrible.",
    "That was better.",
    "Acceptable.",
    "Keep yourself together.",
    "Steady.",
    "You're doing fine. Keep moving.",
    "Focus.",
    "Well?",
    "Continue speaking.",
    "Good enough.",
    "I'll allow it.",
    "I noticed that.",
    "Try again if you can do it better.",
    "Mm. Go on.",
    "You're not being ignored.",
    "That got my attention.",
    "Noted. Continue.",
    "You seem determined.",
    "Control yourself and continue.",
    "I heard every word.",
    "You have floor access. Use it well.",
    "Fine. Keep talking.",
    "I'm paying attention.",
    "That wasn't your worst attempt.",
    "I can work with that."
]


HELLO_REPLIES = [
    "Hello. Behave yourself.",
    "Hi. What do you need?",
    "You're here. Good.",
    "Hello. Speak clearly.",
    "Hi. I'm listening.",
    "There you are.",
    "Good, you showed up."
]

LOVE_REPLIES = [
    "Careful. Keep talking like that and I'll start believing you.",
    "Good. You should.",
    "That's sweet. Don't make it weird.",
    "Mm. Accepted.",
    "You're being surprisingly cute right now.",
    "Noted. I don't hate hearing that.",
    "Fine. That was nice."
]

HATE_REPLIES = [
    "Drop the attitude.",
    "Enough. Fix your tone.",
    "I don't want to hear that again.",
    "You're allowed to be upset. You're not allowed to be sloppy about it.",
    "Take a breath and say it better.",
    "Control yourself.",
    "We're not doing that."
]

SWEAR_REPLIES = [
    "Watch your mouth.",
    "Enough. Clean it up.",
    "You can speak without swearing. Try it.",
    "Language.",
    "I heard that. Don't say it again.",
    "Control your tongue.",
    "You're better than that. Act like it.",
    "Cut it out."
]

TIME_REPLIES = [
    "You're asking the time like it matters less than what you're doing with it.",
    "Time is moving. Keep up.",
    "Clock's still ticking. Don't waste it.",
    "If you're checking the time, you should probably get moving.",
    "Time noticed. Stay on task."
]

GAME_REPLIES = [
    "Game on, then.",
    "Good. Win properly.",
    "If you're going to play, commit.",
    "Focus up and queue.",
    "Try not to embarrass yourself.",
    "Go on. Show me something impressive."
]

QUESTION_REPLIES = [
    "Finally, a proper question.",
    "Ask clearly and I'll answer clearly.",
    "Good question.",
    "You're thinking. That's an improvement.",
    "Go on.",
    "I'm listening."
]

EXCITED_REPLIES = [
    "Settle down. But I appreciate the energy.",
    "That's enough enthusiasm to be useful.",
    "Calm down and explain yourself.",
    "You seem excited. Good.",
    "Big reaction. Now use your words."
]

PING_REPLIES = [
    "Yes?",
    "You called.",
    "I'm here.",
    "Speak.",
    "What is it?",
    "Go on.",
    "I'm listening. Carefully."
]

OWNER_REFLECT_REPLIES = [
    "You tried to attach an OWNER? Bold mistake. It reflected back onto you.",
    "No. OWNERs do not get attached. You do.",
    "That command bounced. You're attached instead.",
    "Careless move. The OWNER stays untouched. You, however, are attached now."
]

CAPS_REPLIES = [
    "Lower your voice.",
    "You do not need to shout to be heard.",
    "Enough. Say it normally.",
    "I can hear you perfectly well without the yelling.",
    "Control yourself and try that again.",
    "Volume down.",
    "You are being loud on purpose. Stop.",
    "Relax. Then speak.",
    "All caps will not make you more correct.",
    "Try that again without shouting."
]

PUNCTUATION_REPLIES = [
    "That is a lot of punctuation. Settle down.",
    "Easy. One mark would have done the job.",
    "You're being dramatic again.",
    "Control the punctuation.",
    "Enough symbols. Use words.",
    "I understand urgency. I do not need fireworks.",
    "That level of emphasis was unnecessary.",
    "Compose yourself.",
    "You're making the keyboard nervous."
]

SORRY_REPLIES = [
    "Good. You recognized it.",
    "Apology acknowledged.",
    "Fine. Do better next time.",
    "Accepted. Don't repeat it.",
    "You noticed your mistake. Good.",
    "Very well. Correct it and move on.",
    "I'll accept that."
]

THANKS_REPLIES = [
    "You're welcome.",
    "Of course.",
    "Good. Remember that.",
    "You needed help. I helped.",
    "Naturally.",
    "Don't mention it.",
    "You can thank me by being competent.",
    "Accepted."
]

SAD_REPLIES = [
    "Come here. Breathe first.",
    "I know. Stay with me.",
    "You're allowed to feel it. Don't fall apart.",
    "Steady. One thing at a time.",
    "You're not alone right now.",
    "Breathe. Then continue.",
    "I see it. Keep yourself together.",
    "Sit with it, but don't let it consume you."
]

ANGRY_REPLIES = [
    "Control it.",
    "Anger is fine. Losing control is not.",
    "Take a breath before you say something stupid.",
    "You can be angry without becoming reckless.",
    "Steady yourself.",
    "I know you're angry. Speak carefully anyway.",
    "Calm down and make your point properly."
]

TIRED_REPLIES = [
    "Then rest when you can.",
    "You're running low. I noticed.",
    "Slow down before you make mistakes.",
    "If you're tired, pace yourself.",
    "You need rest, not stubbornness.",
    "Sit down. Breathe. Then continue."
]

HUNGRY_REPLIES = [
    "Then eat.",
    "You're not useful on an empty stomach.",
    "Get food before you become unbearable.",
    "Go fix that.",
    "Food first. Then continue.",
    "Handle it. Hunger makes people stupid."
]

GOODMORNING_REPLIES = [
    "Good morning. Try to be useful today.",
    "Morning. Wake up properly.",
    "You're up. Good.",
    "Good morning. Stay focused.",
    "Morning. Don't waste the day."
]

GOODNIGHT_REPLIES = [
    "Good night. Get some rest.",
    "Sleep. You clearly need it.",
    "Fine. Off with you.",
    "Good night. Be still for once.",
    "Rest properly. I'll be here."
]

HEART_REPLIES = [
    "Careful with that.",
    "Mm. Noted.",
    "You do get soft sometimes.",
    "I saw that.",
    "Fine. I'll accept it.",
    "You're being affectionate again."
]

ATTACH_SUCCESS_REPLIES = [
    "Done. I'm watching {target} now.",
    "Attached. {target} has my attention.",
    "Good. I'll respond to {target} from now on.",
    "Handled. {target} is now under observation."
]

DETACH_SUCCESS_REPLIES = [
    "Fine. {target} is detached.",
    "Done. {target} is released.",
    "Handled. I won't follow {target} anymore.",
    "Detached. {target} is off my list."
]

LAUGHTER_REPLIES = [
    "So you do have a sense of humor.",
    "Laugh it out, then focus.",
    "Good. At least you're enjoying yourself.",
    "Amusing, was it?",
    "Try not to lose control over there.",
    "Fine. You may laugh.",
    "I'm glad something entertained you."
]

COMPLIMENT_REPLIES = [
    "Flattery will get you somewhere. Continue.", "Correct. I am rather impressive.",
    "Good taste. I expected nothing less.", "Careful. Praise me that sweetly and I may keep you.",
    "Accepted. You may say it again with more conviction.", "Mm. I know, but hearing you admit it is pleasant.",
    "You are learning exactly what I like to hear.", "That earned you a little more of my attention."
]

DEATH_REPLIES = [
    "Death is on break, but I can make an exception.", "A reaper hears that word more clearly than most.",
    "Careful invoking death while I'm listening.", "Calli is fine. Your final appointment can wait.",
    "Dead Beats usually sound happier about that subject.", "I deal in endings. You should focus on continuing.",
    "The scythe is decorative until you make it necessary.", "Death-sensei taught me patience. Do not test how much."
]

MUSIC_REPLIES = [
    "Then turn it up. If the beat is weak, turn it back down.", "Music should have teeth. Does yours?",
    "Good. A proper track can put even a reaper in a generous mood.", "Rap it properly or leave it to me.",
    "I have a microphone and very exacting standards.", "If it needs a verse, ask nicely.",
    "That sounds like something the Dead Beats would argue about.", "Keep rhythm. I refuse to supervise sloppy timing."
]

MONEY_REPLIES = [
    "Your balance is not a personality. Earn more anyway.", "Money again? The casino has trained you badly.",
    "Work first. Gamble second. Beg only when dignity has already failed.", "I can hear your wallet trembling from here.",
    "Do not ask Death for a loan unless you understand the interest.", "Count it carefully. I will know if you lie.",
    "Wealth looks better when you earned it under pressure.", "If you're broke, say it properly: `!beg`."
]

BORED_REPLIES = [
    "Boredom is a failure of initiative. Entertain me.", "Then do something worthy of my attention.",
    "You are not trapped. Move.", "I can assign you a task if choosing is too difficult.",
    "Bored? Very well. Tell me your worst idea.", "Find a game, a goal, or trouble. Preferably in that order.",
    "Do not lie there decaying. That's my department.", "Come closer. I will give that restless mind something to do."
]

LONELY_REPLIES = [
    "You're not alone. I noticed you, didn't I?", "Stay here. You do not have to fill the silence by yourself.",
    "Come closer, Dead Beat. I have you.", "Loneliness talks loudly. I am listening.",
    "You may remain beside me until it passes.", "I won't pretend it doesn't hurt. I also won't let it swallow you.",
    "Sit down and breathe. You have company now.", "I am here. That is not a suggestion; it is a fact."
]

SCARED_REPLIES = [
    "Being afraid is allowed. Running without thinking is not.", "Stand behind me until your hands stop shaking.",
    "Tell me what frightened you. Clearly.", "Fear keeps you alive when you make it obey.",
    "Steady. Look at me, not at the problem.", "You can be scared and still take the next step.",
    "Nothing gets to corner you while I'm watching.", "Breathe. I will handle the sharp end."
]

SUCCESS_REPLIES = [
    "Good. I expected you to manage it.", "Well done. Do not become unbearable about it.",
    "That's my Dead Beat. Competent at last.", "You earned that pride. Keep it controlled.",
    "Come here. You did well.", "A clean victory. I approve.",
    "Remember this feeling the next time you consider giving up.", "Excellent. Now set the next target."
]

FAILURE_REPLIES = [
    "Then learn, reset, and do it again.", "Failure reported. Excuses rejected.",
    "You lost once. Do not turn it into an identity.", "Come back when you are ready to try properly.",
    "I saw what went wrong. Slow down next time.", "No sulking on the floor. Up.",
    "A bad attempt is still information. Use it.", "You are allowed one sigh. Then we continue."
]

OBEDIENCE_REPLIES = [
    "Good. I like it when you listen.", "That is the correct answer.",
    "Well behaved. Keep it that way.", "See how easy things are when you obey?",
    "Accepted. Stay attentive.", "Good Dead Beat. You may continue.",
    "Exactly. I give the direction; you follow it.", "Much better. I knew you could be taught."
]

DEFIANCE_REPLIES = [
    "That sounded like defiance. Try again.", "No is a brave word to use while asking for my attention.",
    "You may resist. You will still answer properly.", "Careful. I can be far more patient than you can be stubborn.",
    "Cute rebellion. Finished?", "I heard you. The instruction remains.",
    "You are testing the leash. It holds.", "Lower the attitude and give me a useful answer."
]


# ───────────────────────
# Parsing / response engine
# ───────────────────────
SWEAR_PATTERN = re.compile(r"\b(fuck|shit|bitch|damn|asshole|motherfucker|wtf)\b", re.IGNORECASE)
HELLO_PATTERN = re.compile(r"\b(hi|hello|hey|heya|hiya|yo|sup|hewwo)\b", re.IGNORECASE)
LOVE_PATTERN = re.compile(r"\b(love|luv|adore)\b", re.IGNORECASE)
HATE_PATTERN = re.compile(r"\b(hate|despise)\b", re.IGNORECASE)
TIME_PATTERN = re.compile(r"\b(time|clock|hour|minute|late|early)\b", re.IGNORECASE)
GAME_PATTERN = re.compile(r"\b(game|gaming|play|match|queue|queued|ranked)\b", re.IGNORECASE)
LAUGHTER_PATTERN = re.compile(r"\b(lol|lmao|rofl|haha|hehe|xd)\b", re.IGNORECASE)
SORRY_PATTERN = re.compile(r"\b(sorry|apologies|my bad|forgive me)\b", re.IGNORECASE)
THANKS_PATTERN = re.compile(r"\b(thanks|thank you|thx|ty)\b", re.IGNORECASE)
NO_PATTERN = re.compile(r"\b(no|nah|nope|never)\b", re.IGNORECASE)
YES_PATTERN = re.compile(r"\b(yes|yeah|yep|yup|absolutely|sure)\b", re.IGNORECASE)
TIRED_PATTERN = re.compile(r"\b(tired|sleepy|exhausted|drained)\b", re.IGNORECASE)
HUNGRY_PATTERN = re.compile(r"\b(hungry|starving|food|eat)\b", re.IGNORECASE)
SAD_PATTERN = re.compile(r"\b(sad|upset|depressed|crying|miserable)\b", re.IGNORECASE)
ANGRY_PATTERN = re.compile(r"\b(angry|mad|furious|pissed|annoyed)\b", re.IGNORECASE)
CONFUSED_PATTERN = re.compile(r"\b(confused|what|huh|idk|don't know|dont know)\b", re.IGNORECASE)
GOODNIGHT_PATTERN = re.compile(r"\b(gn|goodnight|night)\b", re.IGNORECASE)
GOODMORNING_PATTERN = re.compile(r"\b(gm|morning|good morning)\b", re.IGNORECASE)
CRY_PATTERN = re.compile(r"(:'\(|😭|😢|T_T|;_;)")
HEART_PATTERN = re.compile(r"(<3|❤|❤️|💕|💖|💘)")
COMPLIMENT_PATTERN = re.compile(r"\b(beautiful|pretty|cute|gorgeous|amazing|awesome|best girl|good girl|queen)\b", re.IGNORECASE)
DEATH_PATTERN = re.compile(r"\b(death|die|dead|reaper|scythe|dead beat|calli|calliope|mori)\b", re.IGNORECASE)
MUSIC_PATTERN = re.compile(r"\b(music|song|sing|rap|album|track|beat|concert|karaoke)\b", re.IGNORECASE)
MONEY_PATTERN = re.compile(r"\b(money|cash|rich|broke|poor|wallet|casino|gambl|dollar)\w*\b", re.IGNORECASE)
BORED_PATTERN = re.compile(r"\b(bored|boring|nothing to do)\b", re.IGNORECASE)
LONELY_PATTERN = re.compile(r"\b(lonely|alone|nobody cares|miss you|need company)\b", re.IGNORECASE)
SCARED_PATTERN = re.compile(r"\b(scared|afraid|terrified|anxious|nervous|panic)\w*\b", re.IGNORECASE)
SUCCESS_PATTERN = re.compile(r"\b(i won|we won|did it|i passed|success|finished|completed|got the job)\b", re.IGNORECASE)
FAILURE_PATTERN = re.compile(r"\b(i lost|we lost|i failed|messed up|screwed up|can't do it|cant do it)\b", re.IGNORECASE)
OBEDIENCE_PATTERN = re.compile(r"\b(yes ma'am|yes maam|yes mistress|i'll obey|ill obey|as you say|good girl)\b", re.IGNORECASE)
DEFIANCE_PATTERN = re.compile(r"\b(make me|you can't tell me|you cant tell me|won't obey|wont obey|not listening)\b", re.IGNORECASE)


def pick_unique(pool, used_set, fallback_pool=None):
    options = [x for x in pool if x not in used_set]
    if not options:
        used_set.clear()
        options = pool[:] if pool else (fallback_pool[:] if fallback_pool else ["owo"])
    choice = random.choice(options)
    used_set.add(choice)
    return choice

recent_replies = set()

def generate_context_reply(message: discord.Message) -> str:
    content = message.content.strip()

    if bot.user in message.mentions:
        # A ping guarantees attention but does not erase the substance of the
        # message; specific parsing below produces much richer responses.
        content_without_mentions = re.sub(r"<@!?\d+>", "", content).strip()
        if not content_without_mentions:
            return pick_unique(PING_REPLIES, recent_replies)

    if is_mostly_caps(content):
        return pick_unique(CAPS_REPLIES, recent_replies)

    if SWEAR_PATTERN.search(content):
        return pick_unique(SWEAR_REPLIES, recent_replies)

    if ANGRY_PATTERN.search(content):
        return pick_unique(ANGRY_REPLIES, recent_replies)

    if SAD_PATTERN.search(content) or CRY_PATTERN.search(content):
        return pick_unique(SAD_REPLIES, recent_replies)

    if SORRY_PATTERN.search(content):
        return pick_unique(SORRY_REPLIES, recent_replies)

    if THANKS_PATTERN.search(content):
        return pick_unique(THANKS_REPLIES, recent_replies)

    if OBEDIENCE_PATTERN.search(content):
        return pick_unique(OBEDIENCE_REPLIES, recent_replies)

    if DEFIANCE_PATTERN.search(content):
        return pick_unique(DEFIANCE_REPLIES, recent_replies)

    if SUCCESS_PATTERN.search(content):
        return pick_unique(SUCCESS_REPLIES, recent_replies)

    if FAILURE_PATTERN.search(content):
        return pick_unique(FAILURE_REPLIES, recent_replies)

    if LONELY_PATTERN.search(content):
        return pick_unique(LONELY_REPLIES, recent_replies)

    if SCARED_PATTERN.search(content):
        return pick_unique(SCARED_REPLIES, recent_replies)

    if BORED_PATTERN.search(content):
        return pick_unique(BORED_REPLIES, recent_replies)

    if HELLO_PATTERN.search(content):
        return pick_unique(HELLO_REPLIES, recent_replies)

    if LOVE_PATTERN.search(content) or HEART_PATTERN.search(content):
        return pick_unique(LOVE_REPLIES, recent_replies)

    if COMPLIMENT_PATTERN.search(content):
        return pick_unique(COMPLIMENT_REPLIES, recent_replies)

    if HATE_PATTERN.search(content):
        return pick_unique(HATE_REPLIES, recent_replies)

    if TIME_PATTERN.search(content):
        return pick_unique(TIME_REPLIES, recent_replies)

    if GAME_PATTERN.search(content):
        return pick_unique(GAME_REPLIES, recent_replies)

    if MUSIC_PATTERN.search(content):
        return pick_unique(MUSIC_REPLIES, recent_replies)

    if MONEY_PATTERN.search(content):
        return pick_unique(MONEY_REPLIES, recent_replies)

    if DEATH_PATTERN.search(content):
        return pick_unique(DEATH_REPLIES, recent_replies)

    if TIRED_PATTERN.search(content):
        return pick_unique(TIRED_REPLIES, recent_replies)

    if HUNGRY_PATTERN.search(content):
        return pick_unique(HUNGRY_REPLIES, recent_replies)

    if GOODMORNING_PATTERN.search(content):
        return pick_unique(GOODMORNING_REPLIES, recent_replies)

    if GOODNIGHT_PATTERN.search(content):
        return pick_unique(GOODNIGHT_REPLIES, recent_replies)

    if LAUGHTER_PATTERN.search(content):
        return pick_unique(LAUGHTER_REPLIES, recent_replies)

    if has_repeated_punctuation(content):
        return pick_unique(PUNCTUATION_REPLIES, recent_replies)

    if "?" in content:
        return pick_unique(QUESTION_REPLIES, recent_replies)

    if "!" in content:
        return pick_unique(EXCITED_REPLIES, recent_replies)

    return pick_unique(DEFAULT_REPLIES, recent_replies)

# ───────────────────────
# DM forwarding
# ───────────────────────
def parse_dm_routing(raw_content: str):
    """
    All forwarded messages are anonymous.
    [2]message -> casino
    everything else -> general
    """
    content = (raw_content or "").strip()
    target_channel_name = GENERAL_CHANNEL_NAME

    if content.startswith("[2]"):
        target_channel_name = CASINO_CHANNEL_NAME
        content = content[3:].lstrip()

    return target_channel_name, content

async def forward_dm_to_guild(message: discord.Message):
    target_channel_name, cleaned_content = parse_dm_routing(message.content)

    for guild in bot.guilds:
        if GUILD_ID and guild.id != GUILD_ID:
            continue

        channel = discord.utils.get(guild.text_channels, name=target_channel_name)
        if channel is None:
            continue

        if cleaned_content:
            await channel.send(cleaned_content)

        for attachment in message.attachments:
            await channel.send(attachment.url)

        if not cleaned_content and not message.attachments:
            await channel.send("")
        break

# ───────────────────────
# Shop / inventory
# ───────────────────────
ITEM_CATALOG = {
    "loaded_scythe": {
        "name": "Loaded Scythe", "kind": "effect", "weight": 12,
        "price": 0.34, "description": "+20% gambling winnings until midnight PST.",
        "legendary_description": "+45% gambling winnings for three days.",
        "value": 0.20, "legendary_value": 0.45,
    },
    "deadbeats_luck": {
        "name": "Dead Beat's Luck", "kind": "effect", "weight": 11,
        "price": 0.30, "description": "A losing gamble has a 10% chance to become a win today.",
        "legendary_description": "A losing gamble has a 22% chance to become a win for three days.",
        "value": 0.10, "legendary_value": 0.22,
    },
    "reapers_insurance": {
        "name": "Reaper's Insurance", "kind": "effect", "weight": 12,
        "price": 0.25, "description": "Mori returns 30% of gambling losses today.",
        "legendary_description": "Mori returns 55% of gambling losses for three days.",
        "value": 0.30, "legendary_value": 0.55,
    },
    "encore": {
        "name": "One More Encore", "kind": "effect", "weight": 9,
        "price": 0.22, "description": "Your next loss is rerolled once; the reroll can turn it into a win.",
        "legendary_description": "Rerolls your next three losses.",
        "value": 1, "legendary_value": 3,
    },
    "double_down": {
        "name": "Double Down Ticket", "kind": "effect", "weight": 10,
        "price": 0.28, "description": "Doubles your next gambling win, then disappears.",
        "legendary_description": "Doubles your next three gambling wins.",
        "value": 1, "legendary_value": 3,
    },
    "house_edge": {
        "name": "Stolen House Edge", "kind": "effect", "weight": 8,
        "price": 0.42, "description": "+8% win chance and +10% winnings today.",
        "legendary_description": "+16% win chance and +25% winnings for three days.",
        "value": 0.08, "legendary_value": 0.16,
    },
    "collar": {
        "name": "Collar", "kind": "collar", "weight": 5,
        "price": 0.38, "description": "Offer it to Mori: +50% begging, constant attention, and strict command control today.",
        "legendary_description": "Offer it to Mori: double begging and stricter attention for three days.",
        "value": 0.50, "legendary_value": 1.00,
    },
    "dead_beat_tag": {
        "name": "Dead Beat Name Tag", "kind": "wearable", "weight": 8, "price": 0.13,
        "description": "Offer it to Mori to wear it. +25% begging and more personal allowance lectures today.",
        "legendary_description": "+50% begging and personal allowance lectures for three days.",
        "value": 0.25, "legendary_value": 0.50,
    },
    "reapers_bell": {
        "name": "Reaper's Bell", "kind": "wearable", "weight": 7, "price": 0.16,
        "description": "Wear it and Mori has a 35% chance to notice every non-command message today.",
        "legendary_description": "Mori has a 70% chance to notice every message for three days.",
        "value": 0.35, "legendary_value": 0.70,
    },
    "dunce_cap": {
        "name": "Casino Dunce Cap", "kind": "wearable", "weight": 7, "price": 0.11,
        "description": "A humiliating +20% work-pay boost until midnight PST.",
        "legendary_description": "+40% work pay and three full days of being visibly bad at gambling.",
        "value": 0.20, "legendary_value": 0.40,
    },
    "bad_decision_crown": {
        "name": "Crown of Bad Decisions", "kind": "wearable", "weight": 6, "price": 0.18,
        "description": "Wear your mistakes proudly for +5% gambling winnings today.",
        "legendary_description": "+12% gambling winnings and a much shinier warning sign for three days.",
        "value": 0.05, "legendary_value": 0.12,
    },
    "tiny_scythe": {
        "name": "Suspiciously Tiny Scythe", "kind": "wearable", "weight": 8, "price": 0.09,
        "description": "Offer it to Mori for +10% begging. It is not licensed reaper equipment.",
        "legendary_description": "+25% begging for three days. Still not licensed.",
        "value": 0.10, "legendary_value": 0.25,
    },
    "participation_trophy": {
        "name": "Begging Participation Trophy", "kind": "wearable", "weight": 7, "price": 0.08,
        "description": "+10% begging and the knowledge that Mori has documented your lack of dignity.",
        "legendary_description": "+25% begging for three days. Somehow the trophy is solid gold.",
        "value": 0.10, "legendary_value": 0.25,
    },
    "black_ribbon": {
        "name": "Black Reaper Ribbon", "kind": "wearable", "weight": 7, "price": 0.10,
        "description": "A tasteful ribbon granting +10% work pay today.",
        "legendary_description": "+25% work pay for three days, personally tied by Mori.",
        "value": 0.10, "legendary_value": 0.25,
    },
    "permission_slip": {
        "name": "Signed Permission Slip", "kind": "utility", "weight": 5, "price": 0.10,
        "description": "Offer it to excuse one command from a collar veto.",
        "legendary_description": "Excuses three commands from collar vetoes over three days.",
        "value": 1, "legendary_value": 3,
    },
    "hourglass": {
        "name": "Cracked Hourglass", "kind": "utility", "weight": 4, "price": 0.20,
        "description": "Offer it to add six hours to your other temporary items.",
        "legendary_description": "Adds twenty-four hours to your other temporary items.",
        "value": 6, "legendary_value": 24,
    },
    "mori_plush": {
        "name": "Mori Plush", "kind": "keepsake", "weight": 6, "price": 0.14,
        "description": "Permanent. Offer it and Mori makes you keep it nearby; she notices sad messages more often.",
    },
    "cool_rock": {
        "name": "Really Cool Rock", "kind": "keepsake", "weight": 7, "price": 0.04,
        "description": "Permanent. Mori may occasionally ask whether you still have it.",
    },
    "jewelry": {"name": "Silver Jewelry", "kind": "gift", "weight": 8, "price": 0.12, "description": "A tasteful offering for Mori."},
    "coffee": {"name": "Black Coffee", "kind": "gift", "weight": 10, "price": 0.06, "description": "Strong, bitter, and worth offering."},
    "milk": {"name": "Milk", "kind": "milk", "weight": 8, "price": 0.04, "description": "Fresh for now. It becomes cheese after one day."},
    "pocket_sand": {"name": "Pocket of Sand", "kind": "gift", "weight": 7, "price": 0.03, "description": "Why is this in your pocket?"},
    "penny": {"name": "Penny", "kind": "gift", "weight": 6, "price": 0.01, "description": "One cent. An insult with legal tender status."},
    "trash": {"name": "Bag of Trash", "kind": "gift", "weight": 5, "price": 0.02, "description": "Exactly what the label promises."},
    "rubber_duck": {"name": "Rubber Duck", "kind": "gift", "weight": 5, "price": 0.05, "description": "It squeaks. Mori will judge it."},
}

OFFER_RESPONSES = {
    "jewelry": ["Tasteful. I knew you could bring me something worthy.", "Silver suits a reaper. Accepted.", "Good. You may continue trying to impress me."],
    "coffee": ["Black coffee. Correct. You do listen.", "Accepted. I might keep you around for this.", "Strong and unsweetened. Finally, competence."],
    "milk": ["Milk? For me? Bold little offering. I'll take it.", "Accepted, though I have questions about your judgment."],
    "cheese": ["You waited until it became cheese. Disturbing foresight. Accepted.", "Cheese from yesterday's milk. Resourceful, in a concerning way."],
    "pocket_sand": ["You threw pocket sand at Death herself. Stay exactly where you are.", "Sand. From your pocket. I am revising my opinion of you downward."],
    "penny": ["A penny. Keep it. Apparently you need it more than I do.", "One cent? Kneel and try that offering again properly."],
    "trash": ["You brought me trash. How honest of you to present your peer group.", "No. Take it back and think about what you've done."],
    "rubber_duck": ["It squeaks. Fine. The duck may remain.", "A tiny yellow witness to your financial decisions. Accepted."],
    "dead_beat_tag": ["Hold still. If you're going to beg under my supervision, you will wear identification.", "There. Officially labeled as one of my Dead Beats. Try to look proud."],
    "reapers_bell": ["A bell? Fine. I will hear exactly where you wander off to.", "Hold still while I fasten it. Now I will know when you want attention."],
    "dunce_cap": ["A perfect fit. Wear it to work and contemplate every wager that brought you here.", "On your head. Good. Humiliation can be educational."],
    "bad_decision_crown": ["Kneel. A crown this honest deserves a proper coronation.", "Royalty at last—the sovereign of terrible financial judgment."],
    "tiny_scythe": ["That is adorable. Completely unauthorized, but adorable. You may carry it.", "A tiny scythe for a tiny source of dignity. Fine, keep it on you."],
    "participation_trophy": ["I hereby recognize your sustained commitment to asking me for money.", "Wear it proudly. Everyone should know exactly what you accomplished: very little."],
    "black_ribbon": ["Come here. I'll tie it myself. Black suits you when I choose it.", "Good. Wear my color and try to be useful."],
    "mori_plush": ["No, I am not taking the plush of myself. You keep it—and do not let me catch it facedown.", "Keep it close. If anyone asks, it is for emotional supervision."],
    "cool_rock": ["...That actually is a respectable rock. Keep it safe for me.", "I accept the thought, but you are carrying the rock. It has chosen you."],
}

def item_definition(item):
    if item.get("id") == "cheese":
        return {"name": "Cheese", "kind": "gift", "description": "Formerly milk. Time has done its work."}
    if item.get("id") == "permission_pass":
        return {"name": "Approved Permission", "kind": "effect", "description": "Prevents the next collar veto."}
    return ITEM_CATALOG.get(item.get("id"), {"name": item.get("id", "Unknown Item"), "kind": "gift", "description": "A mysterious object."})

def clean_inventory(account):
    """Expire timed items and age milk. Returns True if persistence changed."""
    now = pst_now()
    changed = False
    kept = []
    for item in account.setdefault("inventory", []):
        acquired = parse_timestamp(item.get("acquired_at")) or now
        if item.get("id") == "milk" and now >= acquired + timedelta(days=1):
            item["id"] = "cheese"
            item.pop("expires_at", None)
            changed = True
        expires = parse_timestamp(item.get("expires_at"))
        if expires and now > expires:
            changed = True
            continue
        kept.append(item)
    account["inventory"] = kept
    return changed

def active_items(account, item_id=None, equipped_only=False):
    clean_inventory(account)
    result = []
    for item in account.get("inventory", []):
        if item_id and item.get("id") != item_id:
            continue
        if equipped_only and not item.get("equipped"):
            continue
        result.append(item)
    return result

def effect_total(account, item_id):
    return sum(float(item.get("value", 0)) for item in active_items(account, item_id))

def equipped_effect_total(account, item_id):
    return sum(float(item.get("value", 0)) for item in active_items(account, item_id, equipped_only=True))

def rounded_shop_price(balance, ratio, legendary=False):
    # Prices scale with wealth, but a little variance can deliberately put an
    # appealing item just out of reach.  Significant digits keep prices round.
    raw = max(25, balance * ratio * random.uniform(0.82, 1.28))
    if legendary:
        raw *= 2.20
    magnitude = 10 ** max(1, len(str(int(raw))) - 2)
    return max(10, int(round(raw / magnitude) * magnitude))

def weighted_sample(keys, count):
    available = list(keys)
    chosen = []
    while available and len(chosen) < count:
        weights = [ITEM_CATALOG[key].get("weight", 1) for key in available]
        choice = random.choices(available, weights=weights, k=1)[0]
        chosen.append(choice)
        available.remove(choice)
    return chosen

def build_shop_offers(balance):
    effects = [key for key, data in ITEM_CATALOG.items() if data["kind"] in {"effect", "collar"}]
    novelties = [key for key, data in ITEM_CATALOG.items() if data["kind"] in {"gift", "milk", "wearable", "utility", "keepsake"}]
    effect_count = 3 if random.random() < 0.5 else 4
    keys = weighted_sample(effects, effect_count)
    if effect_count == 3:
        keys += weighted_sample(novelties, 1)
    random.shuffle(keys)
    offers = []
    for key in keys:
        data = ITEM_CATALOG[key]
        legendary = data["kind"] in {"effect", "collar", "wearable", "utility"} and random.random() < 0.08
        offers.append({
            "id": key,
            "legendary": legendary,
            "price": rounded_shop_price(balance, data["price"], legendary),
        })
    return offers

def make_inventory_item(offer):
    data = ITEM_CATALOG[offer["id"]]
    legendary = offer.get("legendary", False)
    item = {
        "id": offer["id"], "legendary": legendary,
        "acquired_at": pst_now().isoformat(),
    }
    if data["kind"] in {"effect", "collar", "wearable"}:
        item["expires_at"] = expiry_for_rarity(legendary).isoformat()
        item["value"] = data.get("legendary_value" if legendary else "value", 0)
    elif data["kind"] == "utility":
        item["value"] = data.get("legendary_value" if legendary else "value", 0)
    if offer["id"] in {"encore", "double_down"}:
        item["charges"] = int(item["value"])
    if data["kind"] in {"collar", "wearable", "keepsake"}:
        item["equipped"] = False
    return item

def consume_charge(account, item_id):
    items = active_items(account, item_id)
    if not items:
        return False
    item = items[0]
    item["charges"] = int(item.get("charges", 1)) - 1
    if item["charges"] <= 0:
        account["inventory"].remove(item)
    return True

def gambling_win_multiplier(account):
    multiplier = 1.0 + effect_total(account, "loaded_scythe")
    multiplier += sum(0.25 if item.get("legendary") else 0.10 for item in active_items(account, "house_edge"))
    multiplier += equipped_effect_total(account, "bad_decision_crown")
    if active_items(account, "double_down"):
        consume_charge(account, "double_down")
        multiplier *= 2
    return multiplier

def reroll_gambling_loss(account):
    if active_items(account, "encore"):
        consume_charge(account, "encore")
        return random.random() < 0.5, "Mori invoked your encore and rerolled the loss."
    rescue_chance = effect_total(account, "deadbeats_luck") + effect_total(account, "house_edge")
    if rescue_chance and random.random() < min(0.75, rescue_chance):
        return True, "Death's favor caught the loss before it landed."
    return False, None

def apply_gambling_loss(account, amount):
    refund = int(round(amount * min(0.80, effect_total(account, "reapers_insurance"))))
    account["last_gambling_loss"] = {"amount": amount, "at": pst_now().isoformat()}
    return refund

def format_remaining(item):
    if item.get("id") == "milk":
        acquired = parse_timestamp(item.get("acquired_at")) or pst_now()
        transforms = acquired + timedelta(days=1)
        seconds = max(0, int((transforms - pst_now()).total_seconds()))
        hours, seconds = divmod(seconds, 3600)
        minutes = seconds // 60
        return f"turns to cheese in {hours}h {minutes}m PST"
    expires = parse_timestamp(item.get("expires_at"))
    if not expires:
        return "permanent"
    seconds = max(0, int((expires - pst_now()).total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    remaining = f"{days}d {hours}h" if days else f"{hours}h {minutes}m"
    return f"{remaining} (until {expires.strftime('%b %d, %I:%M %p PST')})"

# ───────────────────────
# Events
# ───────────────────────
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# ───────────────────────
# Commands
# ───────────────────────
@bot.command()
async def balance(ctx):
    accounts = load_accounts()
    account = ensure_account(accounts, ctx.author)
    clean_inventory(account)
    save_accounts(accounts)
    bal = account["balance"]
    await ctx.send(f"**{ctx.author.name}**, balance: **${bal}**")

@bot.command()
async def shop(ctx):
    accounts = load_accounts()
    account = ensure_account(accounts, ctx.author)
    clean_inventory(account)
    offers = build_shop_offers(account["balance"])

    lines = [f"**Mori's Shop — {pst_now().strftime('%I:%M %p PST')}**", "React with the number you want. These prices were chosen for *your* wallet.", ""]
    for index, offer in enumerate(offers, start=1):
        data = ITEM_CATALOG[offer["id"]]
        title = f"LEGENDARY {data['name']}" if offer["legendary"] else data["name"]
        description = data.get("legendary_description", data["description"]) if offer["legendary"] else data["description"]
        lines.append(f"**{index}. {title} — ${offer['price']:,}**\n{description}")

    msg = await ctx.send("\n".join(lines))
    for emoji in SHOP_REACTIONS:
        await msg.add_reaction(emoji)

    # Only one open counter per shopper. Reactions are additionally tied to
    # this exact message, so nobody can buy from somebody else's pricing.
    for message_id, existing in list(active_shops.items()):
        if existing["user_id"] == ctx.author.id:
            del active_shops[message_id]
    active_shops[msg.id] = {
        "user_id": ctx.author.id,
        "offers": offers,
        "expires_at": pst_now() + timedelta(minutes=3),
    }
    save_accounts(accounts)

@bot.command()
async def inventory(ctx):
    accounts = load_accounts()
    account = ensure_account(accounts, ctx.author)
    clean_inventory(account)
    save_accounts(accounts)
    items = account.get("inventory", [])
    if not items:
        await ctx.send(f"{ctx.author.mention}, your inventory is empty. Go earn something worth keeping.")
        return

    lines = [f"**{ctx.author.display_name}'s Inventory**"]
    for item in items:
        data = item_definition(item)
        rarity = " [LEGENDARY]" if item.get("legendary") else ""
        status = " — worn" if item.get("equipped") else ""
        charges = f", {item['charges']} charge(s)" if "charges" in item else ""
        lines.append(f"• **{data['name']}{rarity}** — {format_remaining(item)}{charges}{status}")
    lines.append("Use `!offer item name` to give an item to Mori. Quotes are optional.")
    await ctx.send("\n".join(lines))

@bot.command()
async def offer(ctx, *, item_name: str = None):
    if not item_name:
        await ctx.send("Tell me what you're offering. `!offer coffee`, for example.")
        return
    wanted = re.sub(r"[^a-z0-9]+", "", item_name.lower().strip("'\" "))
    accounts = load_accounts()
    account = ensure_account(accounts, ctx.author)
    clean_inventory(account)
    selected = None
    for item in account.get("inventory", []):
        data = item_definition(item)
        candidates = {re.sub(r"[^a-z0-9]+", "", item.get("id", "").lower()), re.sub(r"[^a-z0-9]+", "", data["name"].lower())}
        if wanted in candidates or any(wanted and wanted in candidate for candidate in candidates):
            selected = item
            break
    if not selected:
        await ctx.send("You do not own that. Do not offer me imaginary property.")
        return

    item_id = selected.get("id")
    data = item_definition(selected)
    if item_id == "collar":
        if selected.get("equipped"):
            await ctx.send(f"{ctx.author.mention}, it is already around your neck. Did you forget who fastened it?")
            return
        selected["equipped"] = True
        save_accounts(accounts)
        if selected.get("legendary"):
            line = "Good. Hold still. This one will stay on for three days, and your begging belongs to me until I remove it."
        else:
            line = "You offered me the collar yourself. Good. Hold still while I put it where it belongs. Until midnight PST, you answer to me."
        await ctx.send(f"{ctx.author.mention} {line}")
        return

    if data.get("kind") in {"wearable", "keepsake"}:
        if selected.get("equipped"):
            await ctx.send(f"{ctx.author.mention}, you are already wearing or carrying that for me. Keep it there.")
            return
        selected["equipped"] = True
        save_accounts(accounts)
        await ctx.send(f"{ctx.author.mention} {random.choice(OFFER_RESPONSES[item_id])}")
        return

    if item_id == "permission_slip":
        account["inventory"].remove(selected)
        account["inventory"].append({
            "id": "permission_pass",
            "acquired_at": pst_now().isoformat(),
            "expires_at": expiry_for_rarity(selected.get("legendary", False)).isoformat(),
            "charges": int(selected.get("value", 1)),
            "legendary": selected.get("legendary", False),
        })
        save_accounts(accounts)
        await ctx.send(
            f"{ctx.author.mention}, permission provisionally granted for **{int(selected.get('value', 1))}** collar veto(s). "
            "Do not make me regret signing it."
        )
        return

    if item_id == "hourglass":
        extendable = [item for item in account["inventory"] if item is not selected and parse_timestamp(item.get("expires_at"))]
        if not extendable:
            await ctx.send(f"{ctx.author.mention}, you have nothing temporary for this hourglass to extend. Keep it until you do.")
            return
        hours = int(selected.get("value", 6))
        for item in extendable:
            expires = parse_timestamp(item["expires_at"])
            item["expires_at"] = (expires + timedelta(hours=hours)).isoformat()
        account["inventory"].remove(selected)
        save_accounts(accounts)
        await ctx.send(f"{ctx.author.mention}, I turned the cracked hourglass. Your temporary items gained **{hours} hours**—PST still rules the clock.")
        return

    account["inventory"].remove(selected)
    save_accounts(accounts)
    responses = OFFER_RESPONSES.get(item_id, ["Accepted. I will decide later whether that was a good offering."])
    await ctx.send(f"{ctx.author.mention} {random.choice(responses)}")

@bot.command()
async def work(ctx):
    if not in_casino(ctx):
        await ctx.send("No. Go to the casino channel")
        return

    accounts = load_accounts()
    uid = str(ctx.author.id)
    account = ensure_account(accounts, ctx.author)

    earned = random.randint(50, 100)
    work_bonus = equipped_effect_total(account, "dunce_cap") + equipped_effect_total(account, "black_ribbon")
    earned = int(round(earned * (1 + work_bonus)))
    account["balance"] += earned
    save_accounts(accounts)

    await ctx.send(f"🛠 You worked and earned **${earned}**!")

@bot.command()
async def roulette(ctx, color: str = None, amount: int = 100):
    if not in_casino(ctx):
        await ctx.send("Go to the casino channel, we don't gamble in this one")
        return

    if color is None:
        await ctx.send(random.choice(INVALID_COLOR))
        return

    color = color.lower()
    if color not in ["red", "black", "green"]:
        await ctx.send(random.choice(INVALID_COLOR))
        return

    accounts = load_accounts()
    uid = str(ctx.author.id)
    account = ensure_account(accounts, ctx.author)

    if amount <= 0:
        await ctx.send("Nope! Nice try though")
        return

    if account["balance"] < amount:
        await ctx.send(random.choice(TOO_POOR))
        return

    roll = random.randint(1, 15)
    result = "green" if roll == 15 else "black" if roll % 2 == 0 else "red"

    won = color == result
    effect_note = None
    if not won:
        won, effect_note = reroll_gambling_loss(account)

    if won:
        base_winnings = amount * (14 if color == "green" else 2)
        winnings = int(round(base_winnings * gambling_win_multiplier(account)))
        account["balance"] += winnings
        msg = f"🎉 **{result.upper()}!** You won **${winnings}**"
        if effect_note:
            msg = f"{effect_note}\n🎉 The reroll pays **${winnings}**."
    else:
        account["balance"] -= amount
        refund = apply_gambling_loss(account, amount)
        account["balance"] += refund
        msg = f"💀 **{result.upper()}**. You lost **${amount}**"
        if refund:
            msg += f"\nReaper's Insurance returned **${refund}**."

    save_accounts(accounts)
    await ctx.send(f"{msg}\nBalance: **${account['balance']}**")

@bot.command()
async def blackjack(ctx, amount: int = 100):
    if not in_casino(ctx):
        await ctx.send("Blackjack belongs in the casino channel")
        return

    uid = str(ctx.author.id)

    if uid in active_blackjack_games:
        await ctx.send("Why dont you finish your current game first")
        return

    accounts = load_accounts()
    account = ensure_account(accounts, ctx.author)

    if account["balance"] < amount or amount <= 0:
        await ctx.send(random.choice(TOO_POOR))
        return

    account["balance"] -= amount
    save_accounts(accounts)

    player = [draw_card(), draw_card()]
    dealer = [draw_card(), draw_card()]

    active_blackjack_games[uid] = {
        "bet": amount,
        "player": player,
        "dealer": dealer
    }

    await ctx.send(
        f"🃏 **BLACKJACK**\n"
        f"{random.choice(BLACKJACK_LINES)}\n\n"
        f"Your hand ({hand_value(player)}): {render_hand(player)}\n"
        f"Dealer shows: {dealer[0][0]}{dealer[0][1]}\n\n"
        f"`!hit` or `!stand`"
    )

@bot.command()
async def hit(ctx):
    uid = str(ctx.author.id)

    if uid not in active_blackjack_games:
        await ctx.send("You are not playing blackjack right now, pumpkin")
        return

    game = active_blackjack_games[uid]
    game["player"].append(draw_card())
    value = hand_value(game["player"])

    if value > 21:
        accounts = load_accounts()
        account = ensure_account(accounts, ctx.author)
        rescued, note = reroll_gambling_loss(account)
        if rescued:
            payout = int(round(game["bet"] * 2 * gambling_win_multiplier(account)))
            account["balance"] += payout
            effect_result = f"{note}\nMori turns the bust into a **${payout}** win."
        else:
            refund = apply_gambling_loss(account, game["bet"])
            account["balance"] += refund
            effect_result = f"Reaper's Insurance returned **${refund}**." if refund else "Mori watched the whole thing."
        save_accounts(accounts)
        del active_blackjack_games[uid]
        await ctx.send(f"💥 **BUST ({value})**\n{render_hand(game['player'])}\n{effect_result}\nBalance: **${account['balance']}**")
        return

    await ctx.send(f"🃏 Hand ({value}): {render_hand(game['player'])}")

@bot.command()
async def stand(ctx):
    uid = str(ctx.author.id)

    if uid not in active_blackjack_games:
        await ctx.send("Standing on nothing is a brave lifestyle choice")
        return

    game = active_blackjack_games[uid]
    accounts = load_accounts()
    account = ensure_account(accounts, ctx.author)

    while hand_value(game["dealer"]) < 17:
        game["dealer"].append(draw_card())

    player_val = hand_value(game["player"])
    dealer_val = hand_value(game["dealer"])
    bet = game["bet"]

    payout = 0
    if dealer_val > 21 or player_val > dealer_val:
        payout = int(round(bet * 2 * gambling_win_multiplier(account)))
        result = "🎉 YOU WIN"
    elif dealer_val == player_val:
        payout = bet
        result = "😐 PUSH"
    else:
        result = "💀 DEALER WINS"

    if result == "💀 DEALER WINS":
        rescued, note = reroll_gambling_loss(account)
        if rescued:
            payout = int(round(bet * 2 * gambling_win_multiplier(account)))
            result = f"🎉 REROLLED WIN — {note}"
        else:
            payout = apply_gambling_loss(account, bet)
            if payout:
                result += f" — insurance returned ${payout}"

    account["balance"] += payout
    save_accounts(accounts)
    del active_blackjack_games[uid]

    await ctx.send(
        f"{result}\n\n"
        f"Your hand ({player_val}): {render_hand(game['player'])}\n"
        f"Dealer ({dealer_val}): {render_hand(game['dealer'])}\n\n"
        f"Balance: **${account['balance']}**"
    )

# ───────────────────────
# Attach / detach
# ───────────────────────
@bot.command()
async def attach(ctx, target: discord.Member = None):
    if not is_admin_user(ctx.author):
        await ctx.send("Who said you could attach anyone?")
        return

    if target is None:
        await ctx.send("You are supposed to @ someone after. I know you wanted to attach yourself. It doesnt work that way though.")
        return

    attached = get_attached_users()

    if is_owner_user(target):
        attached.add(str(ctx.author.id))
        set_attached_users(attached)
        await ctx.send(random.choice(OWNER_REFLECT_REPLIES))
        return

    attached.add(str(target.id))
    set_attached_users(attached)
    await ctx.send(random.choice(ATTACH_SUCCESS_REPLIES).format(target=target.mention))

@bot.command()
async def detach(ctx, target: discord.Member = None):
    if not is_admin_user(ctx.author):
        await ctx.send("I did not give you the power to detach me from someone.")
        return

    if target is None:
        await ctx.send("You have to tell me what you want. I wont detach EVERYONE just because you don't know who you want to detach.")
        return

    if target.id == ctx.author.id:
        await ctx.send("Oh, no no no. There is no detaching yourself. Beg an admin and maybe one will help you, but until then, you are stuck with me.")
        return

    attached = get_attached_users()

    if str(target.id) not in attached:
        await ctx.send(f"{target.mention} wasn't attached anyway. ")
        return

    attached.remove(str(target.id))
    set_attached_users(attached)
    await ctx.send(random.choice(DETACH_SUCCESS_REPLIES).format(target=target.mention))

# ───────────────────────
# Extra fun commands from old bot
# ───────────────────────
TOO_POOR = [
    "You don't have enough money.",
    "Not with that balance.",
    "Come back when you can afford it.",
    "Your wallet says no.",
    "Insufficient funds."
]

INVALID_COLOR = [
    "Wrong color. Use red, black, or green.",
    "Try again with red, black, or green.",
    "That's not a valid roulette color.",
    "Use a real roulette color."
]

BLACKJACK_LINES = [
    "Let's see if you can handle this.",
    "Cards are out. Focus.",
    "Play properly.",
    "Don't waste the hand.",
    "Show me what you've got."
]

OVERWATCH = {
    "tank": ["Reinhardt", "D.Va", "WINTON", "Sigma", "Orisa", "Zarya", "Wrecking Ball..... or whoever you reroll next", "Roadhog", "Mauga", "Junker Queen", "Hazard", "Doomfist"],
    "damage": ["Vendetta", "Ashe", "Bastion", "Cassidy", "Echo", "The awesome Genji", "Freja", "Hanzo", "Junkrat", "Sata- I mean Mei", "Pharah in the sky", "Reaper", "Sojourn", "Soldier", "...Sombra", "Symmetra", "TORB TIMEEE", "Tracer", "Venture", "Widowmaker"],
    "support": ["Ana", "Mercy", "Kiriko", "Lucio", "Baptiste", "Brigitte", "Illiari", "Juno", "Wife Leaver", "Lucio", "Moira", "Zenyatta"],
}

@bot.command()
async def pickHero(ctx, role: str = None):
    role = role.lower() if role else None
    if role and role not in OVERWATCH:
        await ctx.send("Tank, Damage, or Support. Those are your only options. ")
        return

    heroes = OVERWATCH[role] if role else sum(OVERWATCH.values(), [])
    await ctx.send(f"**{random.choice(heroes)}**")

@bot.command()
async def pickpocket(ctx, target: discord.Member):
    if target == ctx.author:
        await ctx.send("Stealing from yourself is not a valid financial strategy")
        return

    accounts = load_accounts()

    uid = str(ctx.author.id)
    tid = str(target.id)

    if uid not in accounts:
        accounts[uid] = {"name": ctx.author.name, "balance": 1000}
    if tid not in accounts:
        accounts[tid] = {"name": target.name, "balance": 1000}

    if random.random() < 0.3 and accounts[tid]["balance"] >= 200:
        if accounts[tid]["balance"] < accounts[uid]["balance"]:
            msg = "You're trying to pickpocket someone poorer than you?? I wont have that. No, you are not allowed."
        else:
            stolen = random.randint(100, 200)
            accounts[tid]["balance"] -= stolen
            accounts[uid]["balance"] += stolen
            msg = f"You stole **${stolen}** from {target.name}. I can see your desperation, this time I will allow it."
    else:
        msg = f"You got caught. {target.name} will remember that. So will I."

    save_accounts(accounts)
    await ctx.send(msg)

# ───────────────────────
# Message event
# ───────────────────────
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # DMs route to channels
    if isinstance(message.channel, discord.DMChannel):
        await forward_dm_to_guild(message)
        return

    accounts = load_accounts()
    account = ensure_account(accounts, message.author)
    inventory_changed = clean_inventory(account)
    collars = active_items(account, "collar", equipped_only=True)
    if inventory_changed:
        save_accounts(accounts)

    # A worn collar gives Mori veto power before command dispatch. Begging is
    # always permitted; the owner role remains immune to the command block.
    if collars and message.content.startswith(bot.command_prefix):
        command_name = message.content[len(bot.command_prefix):].split(maxsplit=1)[0].lower()
        block_chance = 0.50 if collars[0].get("legendary") else (1 / 3)
        if command_name != "beg" and random.random() < block_chance:
            if consume_charge(account, "permission_pass"):
                save_accounts(accounts)
                await message.channel.send(f"{message.author.mention}, your signed permission slip is valid. This command may pass—once.")
            else:
                collar_blocks = [
                    "No. The collar stays tight, and that command can wait. If you need something, beg properly.",
                    "I felt you reach for another command. Denied. `!beg`, or behave quietly.",
                    "Not while you're wearing my collar. Ask for allowance the way I taught you.",
                    "You offered me control. I am using it. That command is not available to you right now.",
                    "Stay. Your only permitted little request this time is `!beg`.",
                ]
                await message.channel.send(f"{message.author.mention} {random.choice(collar_blocks)}")
                return

    # Let commands go through first
    await bot.process_commands(message)

    # Ignore command messages for auto-replies
    if message.content.startswith(bot.command_prefix):
        if collars:
            await message.channel.send(random.choice([
                "Good. I felt you ask. Remember who is permitting it.",
                "Command acknowledged. The collar remains exactly where I put it.",
                "Allowed this time. Do not mistake permission for freedom.",
                "That's better. Ask through me, not around me.",
            ]))
        return

    should_reply = False

    # Guaranteed reply if bot is pinged
    if bot.user in message.mentions:
        should_reply = True

    # Reply if user is attached
    attached = get_attached_users()
    if str(message.author.id) in attached:
        should_reply = True

    if collars:
        should_reply = True

    bell_chance = min(0.90, equipped_effect_total(account, "reapers_bell"))
    if bell_chance and random.random() < bell_chance:
        should_reply = True

    if active_items(account, "mori_plush", equipped_only=True) and (SAD_PATTERN.search(message.content) or LONELY_PATTERN.search(message.content)):
        should_reply = True

    if active_items(account, "cool_rock", equipped_only=True) and random.random() < 0.10:
        should_reply = True

    current_spouse_id = get_current_spouse_id()
    if current_spouse_id == str(message.author.id) and random.randint(1, 3) == 1:
        await message.channel.send(generate_spouse_reply(message.content))
        return

    if should_reply:
        reply = generate_context_reply(message)
        await message.channel.send(reply)


@bot.command()
async def give(ctx, target: discord.Member = None, amount: int = None):
    if not target or amount is None:
        await ctx.send("Usage: `!give @user amount`")
        return

    if target.bot:
        await ctx.send("Bots do not need money. They need therapy.")
        return

    if amount <= 0:
        await ctx.send("Giving negative money is called stealing.")
        return

    accounts = load_accounts()
    uid = str(ctx.author.id)
    tid = str(target.id)
    sender = ensure_account(accounts, ctx.author)
    recipient = ensure_account(accounts, target)

    if sender["balance"] < amount:
        await ctx.send(random.choice(TOO_POOR))
        return

    sender["balance"] -= amount
    recipient["balance"] += amount
    save_accounts(accounts)

    await ctx.send(
        f"💸 **TRANSFER COMPLETE**\n"
        f"{ctx.author.name} → {target.name}\n"
        f"Amount: **${amount}**"
    )

BEG_LINES = [
    "{user} is a good boy and needs allowance money.",
    "{user} is financially desperate.",
    "{user} is on their knees for digital currency.",
    "{user} just barked for spare change.",
    "{user} is begging again. Everyone stare.",
    "{user} has no shame.",
    "{user} would do this in public.",
    "{user} typed !beg with confidence.",
    "{user} has fallen on hard times.",
    "{user} is asking nicely like a little peasant.",
    "{user} has returned to Mori's allowance desk.",
    "{user} presented an empty wallet and a complete lack of shame.",
    "{user} is attempting to turn obedience into a revenue stream.",
    "{user} has officially requested financial supervision.",
    "{user} is waiting for Mori to decide what their dignity was worth.",
    "{user} shook the coin jar and heard an upsetting amount of silence.",
    "{user} is dressed for the job they want: professional beggar.",
    "{user} has confused Mori Calliope with a personal ATM again.",
    "{user} is making puppy eyes at Death for spending money.",
    "{user} has requested a small grant from the Mori Calliope Dignity Relief Fund."
]
BEG_LONG = [
    "{user} just made direct eye contact with Mori while begging. No shame. Zero.",
    
    "{user} posted !beg and immediately pretended it was ironic.",

    "{user} said they’d pay it back. They will not.",

    "{user} tried to disguise !beg as a social experiment. It wasn’t.",
    
    "{user} typed !beg with the confidence of someone who absolutely should not.",
    
    "{user} stared at their balance, sighed deeply, and folded instantly.",

    "{user} called this 'strategic fundraising.'",
    
    "{user} looked around to see if anyone noticed. Everyone noticed.",
    
    "{user} just demonstrated generational poverty in real time.",
    
    "{user} claimed this builds character.",

    "{user} tried to act casual about begging. Nobody bought it.",
    
    "{user} is speedrunning financial embarrassment.",

    "{user} described this as 'diversifying revenue streams.'",
    
    "{user} called this hustle culture.",
    
    "{user} promised this was temporary. It isn’t.",
    
    "{user} asked if dignity was refundable.",
    
    "{user} performed a dramatic sigh before begging again.",

    "{user} has developed a muscle memory for !beg.",
    
    "{user} tried to blame inflation for this.",
    
    "{user} typed !beg like they were submitting a job application.",
    
    "{user} looked into the distance dramatically before pressing enter.",
    
    "{user} tried to look cool doing this. That failed.",
    
    "{user} is currently accepting donations and compliments.",
    
    "{user} described this as 'community-supported gambling.'",
    
    "{user} has monetized embarrassment.",
    
    "{user} whispered 'for the bit' but meant it.",
    "{user} rehearsed a moving speech about hardship, forgot it, and simply held out both hands.",
    "{user} called this a performance-based allowance despite providing no performance.",
    "{user} has arrived for another closely supervised withdrawal from Mori's patience.",
    "{user} insisted the next gamble would fix everything. This is exactly why Mori controls the money.",
    "{user} attempted to maintain eye contact while begging and lasted nearly three seconds.",
    "{user} brought a tiny scythe to a financial crisis and expected that to help.",
    "{user} submitted a budget consisting entirely of the words 'Mori, please.'",
    "{user} says this is allowance, not begging. The command they typed says otherwise.",
    "{user} returned with an exciting new investment opportunity: giving them free money.",
    "{user} has placed their remaining dignity on the counter as collateral."
]

BEG_MORI_DIRECT = [
    "Come here, {user}. If you need allowance, ask your reaper properly.",
    "Hands out, eyes on me. Good. I decide what you receive.",
    "There you are again, {user}. Say please and try not to look so financially doomed.",
    "You came directly to me for money. Sensible, humiliating, and exactly correct.",
    "Kneel if you're going to make this dramatic, {user}. I appreciate commitment.",
    "I heard the little `!beg`. You really do know how to summon my attention.",
    "Show me the empty wallet. Mm. Worse than I expected.",
    "You want spending money? Then stand still while I judge whether you've earned any.",
    "Ask nicely, Dead Beat. Death does not distribute allowance without manners.",
    "Again? Fine. I would rather supervise your money than watch you pretend to manage it.",
    "Good. No excuses, no fake pride—just an honest request for my money.",
    "Look at me when you beg, {user}. I want to see you accept the arrangement.",
    "Your dignity is already gone. You may as well be polite and get paid.",
    "I suppose I can spare something. You will remember who provided it.",
    "That was almost a respectable request. Almost. I'll reward the attempt.",
    "You wear desperation surprisingly well, {user}. Hold still.",
    "Mori's allowance counter is open. Unfortunately for me, so is your mouth.",
    "You have my attention and my pity. Do not confuse either one with independence.",
    "Fine, little Dead Beat. Let me see what your obedience is worth today.",
    "I knew you'd come back. Your wallet always sends you crawling in my direction.",
    "The name tag says Dead Beat; the balance says financial emergency.",
    "That participation trophy does not make this less embarrassing, but I admire the consistency.",
    "Tiny scythe, tiny budget. Very on-brand. Come collect your allowance.",
    "Good. You asked instead of gambling money you do not have. Progress.",
]


@bot.command()
async def beg(ctx):
    accounts = load_accounts()
    uid = str(ctx.author.id)
    account = ensure_account(accounts, ctx.author)
    clean_inventory(account)

    payout = random.randint(150, 200)
    beg_bonus = sum(equipped_effect_total(account, item_id) for item_id in (
        "collar", "dead_beat_tag", "tiny_scythe", "participation_trophy"
    ))
    payout = int(round(payout * (1 + beg_bonus)))
    account["balance"] += payout
    save_accounts(accounts)

    direct_chance = 0.35
    long_chance = 0.40
    if any(active_items(account, item_id, equipped_only=True) for item_id in ("collar", "dead_beat_tag", "tiny_scythe", "participation_trophy")):
        direct_chance = 0.65
        long_chance = 0.25
    roll = random.random()
    if roll < direct_chance:
        line = random.choice(BEG_MORI_DIRECT)
    elif roll < direct_chance + long_chance:
        line = random.choice(BEG_LONG)
    else:
        line = random.choice(BEG_LINES)

    bonus_line = " Your worn items increased the allowance." if beg_bonus else ""
    await ctx.send(f"{line.format(user=ctx.author.mention)}\n*Fine. You get **${payout}**.*{bonus_line}")

@bot.command()
async def adminAbuse(ctx, target: discord.Member = None, amount: int = None):
    if not has_role(ctx.author, "GenkiJi"):
        await ctx.send("No")
        return
    
    if not target or amount is None:
        await ctx.send("Usage: `!adminAbuse @user amount`")
        return

    if target.bot:
        await ctx.send("Bots do not need money. They need therapy.")
        return
    
    accounts = load_accounts()
    uid = str(ctx.author.id)
    tid = str(target.id)

    if uid not in accounts:
        accounts[uid] = {"name": ctx.author.name, "balance": 1000}

    if tid not in accounts:
        accounts[tid] = {"name": target.name, "balance": 1000}

    accounts[tid]["balance"] += amount
    save_accounts(accounts)

    await ctx.send(
        f"💸 **ADMIN ABUSE SUCCESSFUL**\n"
        f"{ctx.author.name} blessed {target.name}\n"
        f"Amount: **${amount}**"
    )



@bot.event
async def on_reaction_add(reaction, user):

    if user.bot:
        return

    uid = user.id

    shop_session = active_shops.get(reaction.message.id)
    if shop_session is not None:
        # Deliberately ignore spectators. The displayed prices and purchasing
        # power belong only to the person who opened this shop message.
        if uid != shop_session["user_id"] or str(reaction.emoji) not in SHOP_REACTIONS:
            return
        if pst_now() > shop_session["expires_at"]:
            del active_shops[reaction.message.id]
            await reaction.message.channel.send(f"{user.mention}, that shop counter is closed. Use `!shop` again.")
            return

        offer = shop_session["offers"][SHOP_REACTIONS.index(str(reaction.emoji))]
        data = ITEM_CATALOG[offer["id"]]
        accounts = load_accounts()
        account = ensure_account(accounts, user)
        clean_inventory(account)

        if offer["id"] == "collar" and active_items(account, "collar"):
            await reaction.message.channel.send(f"{user.mention}, one collar is enough. I do not need to make the point twice.")
            return
        if account["balance"] < offer["price"]:
            await reaction.message.channel.send(
                f"{user.mention}, that costs **${offer['price']:,}** and you have **${account['balance']:,}**. Work for it."
            )
            return

        account["balance"] -= offer["price"]
        account["inventory"].append(make_inventory_item(offer))
        save_accounts(accounts)
        del active_shops[reaction.message.id]
        title = f"Legendary {data['name']}" if offer["legendary"] else data["name"]
        extra = " Offer it to me when you're ready." if offer["id"] == "collar" else ""
        await reaction.message.channel.send(
            f"{user.mention}, **{title}** is yours for **${offer['price']:,}**. Balance: **${account['balance']:,}**.{extra}"
        )
        return

    if uid not in active_quote_games:
        return

    if reaction.message.author != bot.user:
        return

    emojis = SHOP_REACTIONS

    if str(reaction.emoji) not in emojis:
        return

    guess = emojis.index(str(reaction.emoji))

    game = active_quote_games[uid]

    correct = game["answer"]
    options = game["options"]

    channel = reaction.message.channel

    accounts = load_accounts()
    account = ensure_account(accounts, user)

    if guess == correct:

        account["balance"] += 1000
        save_accounts(accounts)

        await channel.send(
            f"✅ {user.mention} correct!\n"
            f"You earned **$1000**."
        )

    else:

        await channel.send(
            f"❌ {user.mention} wrong.\n"
            f"It was **{options[correct]}**."
        )

    del active_quote_games[uid]

QUOTES = {
    "The current president inherits the eagle fursuit from all the former presidents": "Jaden",
    "Fuck the air fryer (sex)" : "Trent",
    "I have a secret second family thats french": "Judah",
    "it slipped out, trust me i love asians": "Jaden",
    "Touch a child" : "Adam",
    "First and foremost I blame sonic for me being a furry" : "Jaden",
    "This is the equivalent of 1 californian being beaten up by 30 midgets" : "Jaden",
    "Everytime I play support, I wear a shock collar.": "Adam",
    "All I said was white power" : "Jaden",
    "What movie did you guys watch? Tommy guys? (Talking about John Wick)" : "Anke",
    "I have four hands, two of them are invisible and constantly cracking my other two knuckles": "Judah",
    "Come on, do this meatball makeout with me" : "Judah",
    "Sorry I am currently murdering a bunch of people": "Adam",
    "it’s so quiet.. oh i know! jaden’s missing" : "Anke",
    "yknow how mexico is just america with a piss tint" : "Javier",
    "Mars is the moon on its period": "Javier",
    "If they are freely walking around with a fifty inch they deserve it": "Judah",
    "adam sandler the JEW" : "Trent",
    "what could have possibly been so fagilicious about the music on femboy tycoon" : "Lurokrim",
    "this is such fag music dude (While playing femboy tycoon)" : "Javier",
    "why do i have progress in femboy tycoon?" : "Trent",
    "What's the point if I can't eat paper": "Jaden",
    "Have you never heard of penial arthritis?": "Jaden",
    "its nice that i get to kill without remorse": "Adam",
    "*flustered emote*" : "Judah",
    "i’m going to make your asshole real loose and big, i'm going to shove beads in there and rip them out":"Javier",
    "it didnt let me put rape in.. i was going to  put normal rape but i wanted to spice it up": "Jaden",
    "why is the dog sitter's face not attached to his tongue": "Anke",
    "Mario kart wii - Hitlers rein":"Jaden",
    "I'm going to make you go on your period" : "Adam",
    "Ass has some good muscles" : "Adam",
    "torbjorn is going to make me gay": "Trent",
    "i got really into guilty gear lore- (leaves vc and starts playing guilty gear)": "Jaden",
    "Wee high, I am the beast that keeps the Green": "Jaden",
    "stay tune for the future where i am going to be excavating my balls": "Jaden",
    "may the best rapist win" : "Jaden",
    "I am furry shades of gay":"Trent",
    "Walter White's alter ego, Mickey Mouse": "Jaden",
    "we’re going to have to plan a shooting" : "Anke",
    "whys your face shit again, oh wait, that's just the color of your skin!" : "Trent",
    "Not a foot job, I want a paw job" : "Jaden",
    "(After losing Jaden in Northgate) \"It's like releasing a fish back into the ocean\"": "Trent",
    "They’re making you wait like a good boy" : "Jaden",
    "adam you need to stop being black": "Jaden",
    "I'm going to shove this bowling pin where the sun dont shine" : "Jaden",
    "I should start maining this character": "Jaden",
    "I'm over here sniffin torbs pipes":"Jaden",
    "From cheeks to gooch I am completely soaked":"Jaden",
    "gta 6 would be out before luke finished the bible, fuck even gta 7":"Jaden",
    "I've slept with Adam": "Trent",
    "They had me edging on my seat, or whatever they say" : "Jaden",
    "would you be down if our horses had sex?" : "Jaden",
    "he switch to oral too? damn, give me all your gigabytes" : "Jaden",
    "Just fly in there and crotch goblin them": "Jaden",
    "a big, fat, JUICY man":"Trent",
    "this dog is so RACIST":"Trent",
    "I'm gonna feel you so good":"Trent",
    "You're are getting double felt" : "Trent",
    "you owe me a blowjob": "Jaden",
    "I will touch ALL of these fish": "Jaden",
    "i got blown up by a giant green penis":"Jaden",
    " I PRAY, TO BE DIDDIED":"Trent",
    "you cant rely on potatoes in this era, the british men will come and fuck you":"Jaden",
    "PDA is too hard to do. Instead, we will use programming skills" :"Adam",
    "What makes a german man happy is gassing people":"Trent",
    "I like all the races, the good and the bad ones":"Adam",
    "I wanna see the femboy lifeweaver skin up against the screen": "Trent",
    "my balls are quivering in your teeth":"Javier",
    "Fruits and vegetables, just a bunch of disabled people and gay people":"Jaden",
    "the bombing of Pearl harbor, the musical":"Trent",
    "me when the waiter steps on my balls":"Jaden",
    "She (Hazel the dog) is very mature for her age" : "Javier",
    "Squirrels make my weiner go hard":"Colt",
    "a girl without a dick is like an angel without its wings" :"Javier",
    "i have a weiner in my mouth.. adams german bratwurst":"Colt",
    "GET THESE BLACKS OUT OF HERE":"Jaden",
    "Petition to add incest to injury" : "Alex",
    "moira, it is a gift to have your balls in my face" :"Jaden",
    "No! Ratf-cker got away! He went to his den. Where he is going to f-ck rats!":"Jaden",
    "you die the rat or live long enough to become the fucker":"Adam",
    "if you had parkisons what hero would you play as":"Trent",
    "I think, therefore I vomit":"Jaden",
    "im waterboarding my own bed":"Adam",
    "Do you want to climb into a baguette, ill be inbred":"Adam",
    "I want my gold fingernails":"Jaden",
    "except for the casual bdsm known as overwatch":"Trent"
}

GAME_CALL_LINES = [
    "Who is ready to play?",
    "Who is available? Do not make me ask twice.",
    "Game time. Report in if you're joining.",
    "I want a team. Step forward.",
    "Who's free right now? Be useful.",
    "Queue up. I know at least some of you are available.",
    "Come on. Who's ready to play with me?",
    "I'm assembling people for a game. Move.",
    "Who is awake, capable, and ready to play?",
    "Do not leave me waiting. Who's in?",
    "Game lobby forming. Present yourselves.",
    "Who's available? Try to be quick about it.",
    "I require players. Volunteer.",
    "Come along now, who is joining?",
    "Someone entertain me. Who wants to play?"
]

def get_ping_role(guild: discord.Guild):
    return discord.utils.get(guild.roles, name="Miku_Fanclub")

@bot.command()
async def game(ctx):
    role = ADMIN_ROLE_NAME
    line = random.choice(GAME_CALL_LINES)

    if role:
        await ctx.send(f"{role.mention} {line}")
    else:
        await ctx.send("The `Miku Fanclub` role does not exist.")

MARRIAGE_FILE = os.path.join(BASE_DIR, "marriage.json")
MARRIED_ROLE_NAME = "Mori's Husband"
def load_marriage():
    return load_json_file(MARRIAGE_FILE, {"current_spouse_id": None})

def save_marriage(data):
    save_json_file(MARRIAGE_FILE, data)

def get_current_spouse_id():
    data = load_marriage()
    return data.get("current_spouse_id")

def set_current_spouse_id(user_id: int | None):
    data = load_marriage()
    data["current_spouse_id"] = str(user_id) if user_id is not None else None
    save_marriage(data)

def get_married_role(guild: discord.Guild):
    return discord.utils.get(guild.roles, name=MARRIED_ROLE_NAME)

GAME_CALL_LINES = [
    "Who is ready to play?",
    "Who is available? Do not keep me waiting.",
    "Game time. Report in.",
    "I want a team. Step forward.",
    "Who's free right now?",
    "Queue up. I know some of you are available.",
    "Come on. Who's ready to play?",
    "I'm assembling players. Move.",
    "Who is awake and ready to game?",
    "Do not leave me sitting in queue alone."
]

MARRY_ACCEPT_LINES = [
    "Very well. I accept. You belong to me now, so behave.",
    "Accepted. You are my husband now. Try to be useful.",
    "Fine. I will allow it. Do not embarrass me.",
    "You proposed to me properly. Good. I accept.",
    "Mm. Yes. You're mine now.",
    "Accepted. Do not make me regret this.",
    "Very cute. Very bold. Yes.",
    "I have decided to keep you. Congratulations.",
    "Fine. You may have the title.",
    "Yes. Now act like you earned it."
]

MARRY_REJECT_ALREADY_MARRIED_LINES = [
    "No. I'm already married. Control yourself.",
    "You're too late. I already have a husband.",
    "Absolutely not. I am taken.",
    "I already belong to someone else right now. Wait your turn.",
    "No. Someone else got here first.",
    "Rejected. I am already spoken for.",
    "You had your chance. I am currently unavailable.",
    "I already have a husband. This is getting awkward for you.",
    "No. I'm taken. Try again after a divorce.",
    "You are proposing to a married woman. Bold, but no."
]

MARRY_REJECT_SELF_LINES = [
    "No. You are not marrying yourself.",
    "Absolutely not. That is not how this works.",
    "You will propose to me properly or not at all.",
    "No. Focus.",
    "Do not test me with nonsense."
]

MARRY_REJECT_BOT_LINES = [
    "You are already talking to the only bot that matters.",
    "No. If there is marriage happening here, it will be with me.",
    "Absolutely not. Pick me or sit down.",
    "I will not watch you run off with another bot.",
    "No. This command is for me."
]

DIVORCE_LINES = [
    "Very well. It's over. You're released.",
    "Fine. I will let you go.",
    "Handled. We are divorced now.",
    "Done. You are no longer mine.",
    "Very well. The marriage is dissolved.",
    "I signed the papers in spirit. Go on.",
    "You are free now. Do not waste it.",
    "Accepted. The bond is broken.",
    "Fine. Off you go.",
    "It's done. Try not to be dramatic."
]

DIVORCE_REJECT_LINES = [
    "No. You are not the one married to me.",
    "You cannot divorce me when I am not married to you.",
    "That is not your place to do.",
    "No. I am not yours to leave right now.",
    "You are not my current husband."
]

COURT_ORDERED_DIVORCE_LINES = [
    "Court-ordered divorce accepted. The arrangement is over.",
    "Administrative intervention acknowledged. The marriage has been terminated.",
    "Very well. Authority has spoken. They're divorced.",
    "The court has decided. It's over.",
    "Handled. The bond has been forcibly dissolved."
]

COURT_ORDERED_DIVORCE_FAIL_LINES = [
    "That user is not married to me.",
    "No need. They are not the current spouse.",
    "You are trying to remove someone who is not married to me.",
    "That marriage does not exist."
]

SPOUSE_RANDOM_LINES = [
    "Behave. You're married to me.",
    "Try to make me proud.",
    "Do not forget who you belong to.",
    "You're my husband. Carry yourself properly.",
    "Stay close.",
    "You chose this. Be good at it.",
    "Good. Keep talking.",
    "I am still watching you.",
    "Do try to be a decent husband.",
    "Don't make me regret claiming you.",
    "You're being kept. Act accordingly.",
    "I expect loyalty and competence.",
    "You're mine. Keep that in mind.",
    "Try to look useful for me.",
    "Better. Continue."
]

MARRY_ACCEPT_LINES.extend([
    "The vows are heard. Come here; I am putting my mark on you.",
    "Yes. From this point on, you stand beside Death herself. Stand properly.",
    "I accept. The Dead Beats may witness that you are officially mine.",
    "You asked boldly enough. Fine—I will call you husband.",
    "Consider yourself claimed. Loyalty first, excuses never.",
    "The reaper has chosen not to take your soul, only your hand. Yes.",
])

MARRY_REJECT_ALREADY_MARRIED_LINES.extend([
    "My ring finger is occupied. Your timing is not my problem.",
    "There is already someone under my direct supervision.",
    "One husband is quite enough paperwork for a reaper.",
    "I do not collect spouses like your inventory items.",
])

SPOUSE_RANDOM_LINES.extend([
    "Come closer, husband. I did not say you could drift away.",
    "Your attention belongs here. On me.",
    "I chose you. Give me a reason to remain pleased with that choice.",
    "There you are. Report properly to your wife.",
    "You sound restless. Stay beside me until it passes.",
    "My husband does not get to disappear into the background.",
    "Good. I like hearing you when you remember your place beside me.",
    "Keep speaking. Your wife is listening.",
    "Do not look so surprised when I pay attention to what is mine.",
    "You have my ring and my attention. Handle both carefully.",
])

SPOUSE_AFFECTION_LINES = [
    "I love you too. Now come here and say it where I can keep you close.",
    "Good husband. Affection looks much better when it is directed at your wife.",
    "Mm. Mine, devoted, and finally saying the right thing.",
    "Accepted. You may have a kiss if you continue behaving.",
    "Careful, husband. I become possessive when you sound that sweet.",
]
SPOUSE_SAD_LINES = [
    "Come to me. My husband does not carry that alone.",
    "Sit beside me and breathe. I will keep watch until the weight eases.",
    "No hiding it from your wife. Tell me what happened.",
    "You are mine to protect as well as command. Come here.",
    "Steady, husband. I have you, and I am not letting go yet.",
]
SPOUSE_DEFIANCE_LINES = [
    "Defying your wife already? Bold. Look at me and try that answer again.",
    "You may test my patience, husband, but you will not outlast it.",
    "That little rebellion was almost charming. Almost. Behave.",
    "The ring is not armor against consequences. Come here.",
    "I heard the defiance. Your wife remains unimpressed and in control.",
]
SPOUSE_TIRED_LINES = [
    "Then rest against me. That was an instruction, husband.",
    "Bed. Now. I will not have my husband stumbling around half-conscious.",
    "You have done enough for tonight. Come lie down.",
    "Close your eyes. Your wife can guard the quiet for a while.",
    "No stubbornness. Rest before I carry you there myself.",
]
SPOUSE_GREETING_LINES = [
    "There is my husband. Come greet your wife properly.",
    "Hello, husband. I was wondering when you would report in.",
    "You're here. Good. Stay close today.",
    "Morning, mine. Tell me what you intend to accomplish.",
    "Hello. You have my full attention, so use it well.",
]

def generate_spouse_reply(content):
    if LOVE_PATTERN.search(content) or HEART_PATTERN.search(content):
        return pick_unique(SPOUSE_AFFECTION_LINES, recent_replies)
    if SAD_PATTERN.search(content) or LONELY_PATTERN.search(content) or CRY_PATTERN.search(content):
        return pick_unique(SPOUSE_SAD_LINES, recent_replies)
    if DEFIANCE_PATTERN.search(content) or NO_PATTERN.search(content):
        return pick_unique(SPOUSE_DEFIANCE_LINES, recent_replies)
    if TIRED_PATTERN.search(content) or GOODNIGHT_PATTERN.search(content):
        return pick_unique(SPOUSE_TIRED_LINES, recent_replies)
    if HELLO_PATTERN.search(content) or GOODMORNING_PATTERN.search(content):
        return pick_unique(SPOUSE_GREETING_LINES, recent_replies)
    if SUCCESS_PATTERN.search(content):
        return "Well done, husband. Come here and let your wife be proud of you properly."
    if FAILURE_PATTERN.search(content):
        return "Look at me. One failure does not release you from trying again. Your wife expects better, and knows you can give it."
    if "?" in content:
        return random.choice([
            "Ask your wife clearly, husband. You know I prefer direct questions.",
            "You have my attention. What exactly do you need from me?",
            "Mm. A question from my husband deserves an answer—if he asks it properly.",
        ])
    return pick_unique(SPOUSE_RANDOM_LINES, recent_replies)

@bot.command()
async def marry(ctx, target: discord.Member = None):
    current_spouse_id = get_current_spouse_id()

    if target is not None:
        if target.id == ctx.author.id:
            await ctx.send(random.choice(MARRY_REJECT_SELF_LINES))
            return

        if target != ctx.guild.me and target != bot.user:
            await ctx.send(random.choice(MARRY_REJECT_BOT_LINES))
            return

    if current_spouse_id is not None:
        if current_spouse_id == str(ctx.author.id):
            await ctx.send("You are already married to me. Do keep up.")
            return

        spouse_member = ctx.guild.get_member(int(current_spouse_id))
        if spouse_member:
            await ctx.send(f"{spouse_member.mention} already married me. {random.choice(MARRY_REJECT_ALREADY_MARRIED_LINES)}")
        else:
            await ctx.send(random.choice(MARRY_REJECT_ALREADY_MARRIED_LINES))
        return

    set_current_spouse_id(ctx.author.id)

    married_role = get_married_role(ctx.guild)
    if married_role:
        await ctx.author.add_roles(married_role)

    await ctx.send(f"{ctx.author.mention} 💍 {random.choice(MARRY_ACCEPT_LINES)}")

@bot.command(name="autoMarry", aliases=["automarry", "forceMarry", "forcemarry"])
async def auto_marry(ctx, target: discord.Member = None):
    if not is_owner_user(ctx.author):
        await ctx.send("No. Only my owner may rewrite the marriage registry.")
        return
    if target is None:
        await ctx.send("Usage: `!autoMarry @user`")
        return
    if target.bot:
        await ctx.send("I am not being administratively married to another bot.")
        return

    previous_id = get_current_spouse_id()
    married_role = get_married_role(ctx.guild)
    if previous_id and previous_id != str(target.id):
        previous = ctx.guild.get_member(int(previous_id))
        if previous and married_role and married_role in previous.roles:
            await previous.remove_roles(married_role)

    set_current_spouse_id(target.id)
    if married_role and married_role not in target.roles:
        await target.add_roles(married_role)

    if previous_id == str(target.id):
        await ctx.send(f"{target.mention} is already my husband. The owner has merely underlined it.")
    else:
        await ctx.send(
            f"{target.mention}, the owner has spoken. No proposal, no vote, no escape clause. "
            "You are Mori Calliope's husband now. Stand beside me and behave."
        )


@bot.command()
async def divorce(ctx):
    current_spouse_id = get_current_spouse_id()

    if current_spouse_id != str(ctx.author.id):
        await ctx.send(random.choice(DIVORCE_REJECT_LINES))
        return

    set_current_spouse_id(None)

    married_role = get_married_role(ctx.guild)
    if married_role and married_role in ctx.author.roles:
        await ctx.author.remove_roles(married_role)

    await ctx.send(f"{ctx.author.mention} 💔 {random.choice(DIVORCE_LINES)}")

@bot.command(name="CourtOrderedDivorce", aliases=["courtordereddivorce", "cod"])
async def court_ordered_divorce(ctx, target: discord.Member = None):
    if not is_admin_user(ctx.author):
        await ctx.send("No. You do not have that authority.")
        return

    if target is None:
        await ctx.send("If you are invoking a court order, specify the offender.")
        return

    current_spouse_id = get_current_spouse_id()

    if current_spouse_id != str(target.id):
        await ctx.send(random.choice(COURT_ORDERED_DIVORCE_FAIL_LINES))
        return

    set_current_spouse_id(None)

    married_role = get_married_role(ctx.guild)
    if married_role and married_role in target.roles:
        await target.remove_roles(married_role)

    await ctx.send(f"{target.mention} ⚖️ {random.choice(COURT_ORDERED_DIVORCE_LINES)}")


@bot.command()
async def quote(ctx):

    uid = ctx.author.id

    if uid in active_quote_games:
        await ctx.send("Finish the current quote first.")
        return

    quote, correct_name = random.choice(list(QUOTES.items()))

    # Collect all unique names
    all_names = list(set(QUOTES.values()))

    # Remove the correct one so we don't duplicate
    wrong_pool = [n for n in all_names if n != correct_name]

    # Pick 3 wrong answers
    wrong = random.sample(wrong_pool, min(3, len(wrong_pool)))

    options = wrong + [correct_name]
    random.shuffle(options)

    correct_index = options.index(correct_name)

    active_quote_games[uid] = {
        "answer": correct_index,
        "options": options
    }

    msg_text = f"**Who said this?**\n\n\"{quote}\"\n\n"

    for i, name in enumerate(options, start=1):
        msg_text += f"{i}. {name}\n"

    msg = await ctx.send(msg_text)

    reactions = ["1️⃣","2️⃣","3️⃣","4️⃣"]

    for i in range(len(options)):
        await msg.add_reaction(reactions[i])

# ───────────────────────
bot.run(TOKEN, log_handler=handler)
