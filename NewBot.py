import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import json
import random
import re

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

ADMIN_ROLE_NAME = "GenkiJi"
OWNER_ROLE_NAME = "Miku Fanclub"

active_blackjack_games = {}
active_quote_games = {}

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

    if HELLO_PATTERN.search(content):
        return pick_unique(HELLO_REPLIES, recent_replies)

    if LOVE_PATTERN.search(content) or HEART_PATTERN.search(content):
        return pick_unique(LOVE_REPLIES, recent_replies)

    if HATE_PATTERN.search(content):
        return pick_unique(HATE_REPLIES, recent_replies)

    if TIME_PATTERN.search(content):
        return pick_unique(TIME_REPLIES, recent_replies)

    if GAME_PATTERN.search(content):
        return pick_unique(GAME_REPLIES, recent_replies)

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
    Rules:
    [2]message      -> casino, non-anon
    --message       -> general, anon
    [2]--message    -> casino, anon
    everything else -> general, non-anon
    """
    content = (raw_content or "").strip()
    target_channel_name = GENERAL_CHANNEL_NAME
    if random.randint(1,15) == 5:
        anonymous = False
    else:
        anonymous = True

    if content.startswith("[2]"):
        target_channel_name = CASINO_CHANNEL_NAME
        content = content[3:].lstrip()

    if content.startswith("--"):
        anonymous = True
        content = content[2:].lstrip()

    return target_channel_name, anonymous, content

async def forward_dm_to_guild(message: discord.Message):
    target_channel_name, anonymous, cleaned_content = parse_dm_routing(message.content)

    for guild in bot.guilds:
        if GUILD_ID and guild.id != GUILD_ID:
            continue

        channel = discord.utils.get(guild.text_channels, name=target_channel_name)
        if channel is None:
            continue

        if cleaned_content:
            if anonymous:
                await channel.send(cleaned_content)
            else:
                await channel.send(f"**DM from {message.author.display_name}:** {cleaned_content}")

        for attachment in message.attachments:
            if anonymous:
                await channel.send(attachment.url)
            else:
                await channel.send(f"**Attachment from {message.author.display_name}:** {attachment.url}")

        if not cleaned_content and not message.attachments:
            if anonymous:
                await channel.send("")
            else:
                await channel.send("")
        break

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
    accounts = get_account(ctx.author)
    bal = accounts[str(ctx.author.id)]["balance"]
    await ctx.send(f"**{ctx.author.name}**, balance: **${bal}**")

@bot.command()
async def work(ctx):
    if not in_casino(ctx):
        await ctx.send("No. Go to the casino channel")
        return

    accounts = get_account(ctx.author)
    uid = str(ctx.author.id)

    earned = random.randint(50, 100)
    accounts[uid]["balance"] += earned
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

    accounts = get_account(ctx.author)
    uid = str(ctx.author.id)

    if amount <= 0:
        await ctx.send("Nope! Nice try though")
        return

    if accounts[uid]["balance"] < amount:
        await ctx.send(random.choice(TOO_POOR))
        return

    roll = random.randint(1, 15)
    result = "green" if roll == 15 else "black" if roll % 2 == 0 else "red"

    if color == result:
        winnings = amount * (14 if color == "green" else 2)
        accounts[uid]["balance"] += winnings
        msg = f"🎉 **{result.upper()}!** You won **${winnings}**"
    else:
        accounts[uid]["balance"] -= amount
        msg = f"💀 **{result.upper()}**. You lost **${amount}**"

    save_accounts(accounts)
    await ctx.send(f"{msg}\nBalance: **${accounts[uid]['balance']}**")

@bot.command()
async def blackjack(ctx, amount: int = 100):
    if not in_casino(ctx):
        await ctx.send("Blackjack belongs in the casino channel")
        return

    uid = str(ctx.author.id)

    if uid in active_blackjack_games:
        await ctx.send("Why dont you finish your current game first")
        return

    accounts = get_account(ctx.author)

    if accounts[uid]["balance"] < amount or amount <= 0:
        await ctx.send(random.choice(TOO_POOR))
        return

    accounts[uid]["balance"] -= amount
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
        del active_blackjack_games[uid]
        await ctx.send(f"💥 **BUST ({value})**\n{render_hand(game['player'])}")
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

    while hand_value(game["dealer"]) < 17:
        game["dealer"].append(draw_card())

    player_val = hand_value(game["player"])
    dealer_val = hand_value(game["dealer"])
    bet = game["bet"]

    payout = 0
    if dealer_val > 21 or player_val > dealer_val:
        payout = bet * 2
        result = "🎉 YOU WIN"
    elif dealer_val == player_val:
        payout = bet
        result = "😐 PUSH"
    else:
        result = "💀 DEALER WINS"

    accounts[uid]["balance"] += payout
    save_accounts(accounts)
    del active_blackjack_games[uid]

    await ctx.send(
        f"{result}\n\n"
        f"Your hand ({player_val}): {render_hand(game['player'])}\n"
        f"Dealer ({dealer_val}): {render_hand(game['dealer'])}\n\n"
        f"Balance: **${accounts[uid]['balance']}**"
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

    # Let commands go through first
    await bot.process_commands(message)

    # Ignore command messages for auto-replies
    if message.content.startswith(bot.command_prefix):
        return

    should_reply = False

    # Guaranteed reply if bot is pinged
    if bot.user in message.mentions:
        should_reply = True

    # Reply if user is attached
    attached = get_attached_users()
    if str(message.author.id) in attached:
        should_reply = True

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

    accounts = get_account(ctx.author)
    uid = str(ctx.author.id)
    tid = str(target.id)

    if accounts[uid]["balance"] < amount:
        await ctx.send(random.choice(TOO_POOR))
        return

    accounts[uid]["balance"] -= amount
    accounts[tid]["balance"] += amount
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
    "{user} is asking nicely like a little peasant."
]
BEG_LONG = [
    "{user} just made direct eye contact with Teto while begging. No shame. Zero.",
    
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
    
    "{user} whispered 'for the bit' but meant it."
]


@bot.command()
async def beg(ctx):
    accounts = load_accounts()
    uid = str(ctx.author.id)

    if uid not in accounts:
        accounts[uid] = {"balance": 1000, "attitude": 0}

    payout = random.randint(150, 200)
    accounts[uid]["balance"] += payout
    save_accounts(accounts)

    # 20% chance for long humiliation
    if random.random() < 0.6:
        line = random.choice(BEG_LONG)
    else:
        line = random.choice(BEG_LINES)

    await ctx.send(
        f"{line.format(user=ctx.author.mention)}\n"
        f"*Fine, I'll give ${ctx.author} ${payout}*"
    )

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

    if uid not in active_quote_games:
        return

    if reaction.message.author != bot.user:
        return

    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣"]

    if str(reaction.emoji) not in emojis:
        return

    guess = emojis.index(str(reaction.emoji))

    game = active_quote_games[uid]

    correct = game["answer"]
    options = game["options"]

    channel = reaction.message.channel

    accounts = get_account(user)

    if guess == correct:

        accounts[str(uid)]["balance"] += 1000
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