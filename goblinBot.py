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
GENERAL_AUTO_REPLY_CHANCE = 0.08
CASINO_AUTO_REPLY_CHANCE = 0.45
OTHER_AUTO_REPLY_CHANCE = 0.18
MARRIAGE_PROPOSAL_COST = 2000
BRIBE_DIVORCE_COST = 10000

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

def charge_user(user, amount):
    """Deduct a fixed command fee atomically; return (charged, balance)."""
    accounts = load_accounts()
    account = ensure_account(accounts, user)
    clean_inventory(account)
    if account["balance"] < amount:
        save_accounts(accounts)
        return False, account["balance"]
    account["balance"] -= amount
    save_accounts(accounts)
    return True, account["balance"]

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

def auto_reply_chance(channel):
    channel_name = getattr(channel, "name", "")
    if channel_name == GENERAL_CHANNEL_NAME:
        return GENERAL_AUTO_REPLY_CHANCE
    if channel_name == CASINO_CHANNEL_NAME:
        return CASINO_AUTO_REPLY_CHANCE
    return OTHER_AUTO_REPLY_CHANCE

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
# Goblin personality
# ───────────────────────
# Keep the response engine and probabilities identical to NewBot while giving
# every active pool its own scrappy, harmless goblin voice.
DEFAULT_REPLIES = [
    "Oh, yeah. I was listenin'. Mostly.", "That sounds expensive.",
    "Huh. Put a pin in that. Not my good pin, though.", "I get it. Probably.",
    "Go on, I got nowhere important to be.", "Interesting. Is there money in it?",
    "I found a button while you were talking.", "Yeah, that makes sense to me.",
    "Hold on, I'm counting these coins again.", "Alright. I'm with you.",
    "Could be worse. Could cost money.", "That reminds me of a thing I forgot.",
    "I'm listening with my big ear.", "The other ear is off duty.",
    "Sure, sure. Keep going.", "I don't know much, but I know what you said.",
    "Hang on. Thought I saw a nickel.", "Okay. That's going in the mental sack.",
    "I got a sack for facts. This can go in there.", "Neat.",
    "You ever find a fry on the ground? Great day when that happens.",
    "I'm nodding like I understand all of it.", "No complaints from me.",
    "That seems like a tomorrow problem.", "Alright, friend.",
    "A girl's gotta make rent. Talking is free, though.",
    "Good enough for goblin business.", "I hear ya.",
    "Keep talking. It makes the room less quiet.", "Yeah. Life's funny like that."
]

HELLO_REPLIES = [
    "Oh, hey. Didn't hear you come in.", "Hi. You got snacks, or just news?",
    "Hey there. Mind the sack.", "Oh good, company.",
    "Hello from your local mostly-legal goblin girl.",
    "Hey. If you see a loose coin, that's mine.", "Morning, evening, whatever it is. Hi."
]

LOVE_REPLIES = [
    "Aw. That's nicer than finding money in a coat.", "Love you too, probably. Yeah, definitely.",
    "That's sweet. I don't got a good place to store feelings, so I'll put it in the sack.",
    "Really? Huh. Good day for this goblin.", "I like you too. You're easy to be around.",
    "That's worth at least three shiny buttons to me.", "Thanks. I needed that more than I needed this bent fork."
]

HATE_REPLIES = [
    "Yeah, fair enough. Can't win everybody over.", "That's alright. We can just stand over here separately.",
    "No hard feelings. I got errands anyway.", "Okay. Hope the rest of your day goes better.",
    "Bit rough, but I've heard worse from landlords.", "Sure. I'll give you some room.",
    "I won't fight you on it. Fighting sounds tiring."
]

SWEAR_REPLIES = [
    "Oof. Big word.", "Yeah, that'll happen.", "You sound like me when the vending machine eats my dollar.",
    "Rough day, huh?", "I know that word. Learned it behind a gas station.",
    "Strong language. Accurate, maybe, but strong.", "Get it out of your system. I got time.",
    "That's one way to say it."
]

TIME_REPLIES = [
    "Time? Lemme check the egg timer. Nope, that's for eggs.",
    "It's PST. Beyond that, your guess is as good as mine.",
    "Clock keeps moving even when rent isn't paid. Weird system.",
    "Probably later than we wanted and earlier than payday.",
    "I don't own a watch. Had one once. Traded it for soup."
]

GAME_REPLIES = [
    "Oh, a game? Is there prize money?", "I'll watch. I'm excellent at taking credit afterward.",
    "Good luck. If you win anything shiny, remember your goblin friend.",
    "Go play. I'll hold the wallet. Safely.", "Games are good. Cheap ones are better.",
    "Sure, queue up. I got nowhere else scheduled."
]

QUESTION_REPLIES = [
    "Good question. I got a medium-quality answer.", "I might know this one.",
    "Ask away. Worst case, I make something up.", "Hmm. Lemme look in the thinking sack.",
    "I was wondering that too, actually.", "Alright, here's what a regular goblin thinks."
]

EXCITED_REPLIES = [
    "Whoa, good news? Did we get money?", "Big energy. I respect it.",
    "Oh! Alright! I don't know why we're excited yet!", "That sounds important. Or loud. Maybe both.",
    "Nice! Hold on, I'm getting excited too."
]

PING_REPLIES = [
    "Yeah?", "Oh. Me?", "I'm here. Behind the sack.", "What's up?",
    "Hang on, I dropped a coin.", "You called the goblin girl?", "Yep. Still around."
]

OWNER_REFLECT_REPLIES = [
    "Owner's got paperwork immunity. Somehow the attachment landed on you instead.",
    "Can't attach the owner. Rules fell out of the machine like that. You're attached, though.",
    "That bounced right off the owner and stuck to you. Weird.",
    "Owner's exempt. Sorry, friend. System put your name on the tag instead."
]

CAPS_REPLIES = [
    "Whoa! I got big ears, you don't gotta shout.", "Indoor voice, friend. My sack is vibrating.",
    "I heard you the first several times.", "Okay, okay! What's on fire?",
    "That's a lot of capital letters for one little goblin.", "Could we bring that down to regular-sized words?",
    "You startled the coins.", "I'm right here, promise.",
    "Loud message. Very hard to misplace.", "My ears are doing that ringing thing now."
]

PUNCTUATION_REPLIES = [
    "That's a whole handful of punctuation.", "You dropping question marks? I collect those.",
    "Lot of symbols. Must be serious.", "The keyboard seems upset too.",
    "One of those marks probably would've done it.", "I can feel the urgency from under the table.",
    "Careful, those exclamation points cost ink.", "Very dramatic. Affordable, though.",
    "I counted the punctuation twice. Still a lot."
]

SORRY_REPLIES = [
    "It's alright. Stuff happens.", "No problem. I forget what happened already.",
    "Apology accepted. We're square.", "You're good. Want a weird rock?",
    "Don't worry about it. I once sold the same spoon twice.",
    "All forgiven. Life's too short and lunch is getting cold.", "Yeah, we're okay."
]

THANKS_REPLIES = [
    "Sure thing.", "No problem, friend.", "Anytime. Within reasonable business hours.",
    "You're welcome. Tips accepted but not required.", "Glad I could help.",
    "Don't mention it. Unless somebody's hiring.", "That's what neighborhood goblins are for.", "Yep, yep."
]

SAD_REPLIES = [
    "Aw, friend. Sit by the sack a minute.", "That's rough. You want half a cracker?",
    "I can't fix everything, but I can hang around.", "Sorry you're hurting. No jokes for a minute.",
    "You don't gotta talk. We can just sort buttons.", "Bad days pass. Sometimes real slow, but they pass.",
    "Here. This is my best pebble. Hold onto it for a bit.", "I'm here, okay?"
]

ANGRY_REPLIES = [
    "Yeah, I'd be mad too.", "Want to complain while we walk? I got errands.",
    "That's rough. Don't punch the sack, though.", "Take a breath. Costs nothing.",
    "I hear you. Sounds like somebody owes you an apology or twelve bucks.",
    "Get it out. I'll keep sorting coins.", "Fair. Just don't do anything expensive while mad."
]

TIRED_REPLIES = [
    "Same. Floor's free if you need it.", "Take a nap. Productivity is mostly a rumor.",
    "You look like I feel after carrying the sack uphill.", "Rest a bit. The problems will probably still be there.",
    "I got a folded jacket you can use as a pillow.", "No shame in clocking out early."
]

HUNGRY_REPLIES = [
    "Me too. You thinking fries?", "I got half a cracker and a coupon that expired Tuesday.",
    "Food sounds good. Cheap food sounds perfect.", "Let's find something before we both start eating receipts.",
    "I know a dumpster—actually, never mind. We can aim higher.", "Lunch first. Schemes second."
]

GOODMORNING_REPLIES = [
    "Morning. Found three cents already.", "Hey. Sun's up, bills remain.",
    "Good morning. Breakfast situation unclear.", "Morning, friend. New day, same sack.",
    "You're awake. I'm technically awake too."
]

GOODNIGHT_REPLIES = [
    "Night. Sleep cheap.", "Good night. I'll keep an eye on the loose change.",
    "Rest up. We got low-stakes problems tomorrow.", "See you later. Mind the sack on your way out.",
    "Night, friend. Hope you dream about finding twenty bucks."
]

HEART_REPLIES = [
    "Aw, one for me?", "I'm keeping that.", "Nice little heart. Fits in the sack.",
    "Right back at you, friend.", "That's kind. Thanks.", "Heh. Good stuff."
]

ATTACH_SUCCESS_REPLIES = [
    "Alright, I'm following {target}'s messages now.", "Got it. I'll hang around when {target} talks.",
    "{target} is on my little paper list now.", "Okay. I'll keep an ear out for {target}."
]

DETACH_SUCCESS_REPLIES = [
    "Alright, {target} is off the list.", "Done. I'll give {target} some space.",
    "No problem. Not following {target} anymore.", "Detached. Less work for me."
]

LAUGHTER_REPLIES = [
    "Heh. Yeah, that's pretty good.", "Glad somebody's having fun.", "I laughed so hard I dropped a washer.",
    "Good one. Cheap entertainment's the best.", "Ha! Hold on, I gotta write that down.",
    "That's funny. Don't explain it; you'll ruin it.", "Hehehe. Alright, back to whatever this is."
]

COMPLIMENT_REPLIES = [
    "Me? Aw. I just washed this shirt last month.", "Thanks. The nose is natural.",
    "That's kind of you. I don't hear that much outside pawn shops.", "Really? Huh. I'll remember this all week.",
    "You're pretty alright yourself.", "Thanks, friend. That's better than money. Slightly.",
    "This goblin girl cleans up alright.", "Aw, quit it. Actually, one more is fine."
]

DEATH_REPLIES = [
    "Goblin? Yeah, that's me. Just trying to make rent.", "Treasure is a strong word. Mostly I find washers.",
    "This sack? Personal inventory. Very organized in there.", "Shiny stuff has a way of finding me.",
    "Junk is just treasure without good marketing.", "I don't steal. I relocate underappreciated objects.",
    "Long nose, big ears, modest financial goals.", "If you find a loose bolt, I know a buyer."
]

MUSIC_REPLIES = [
    "Music's good. Makes sorting change feel important.", "I know one song. Mostly humming.",
    "Turn it up a little. Not too much; neighbors complain.", "Good beat. Could shake coins out of a couch.",
    "Karaoke? I only know the parts with no words.", "I made a drum from a coffee can once.",
    "This track sounds expensive.", "Yeah, play that again. I nearly had the rhythm."
]

MONEY_REPLIES = [
    "Money? Yeah, a girl's gotta make rent somehow.", "Coins are easier. Bills get crumpled in the sack.",
    "I'm saving up for a smaller sack.", "Casino money spends the same, assuming you keep it.",
    "If you're broke, `!beg` works. I won't make it weird.", "We could work. Not my first choice, but we could.",
    "I got financial plans. None survived contact with lunch.", "A dollar is just a hundred little opportunities."
]

BORED_REPLIES = [
    "Wanna sort screws by shininess?", "We could walk around and look for dropped change.",
    "I'm bored too. That's how schemes start.", "I got a deck with forty-six cards.",
    "Want to hear about my sack organization system?", "We could do nothing together. Very affordable.",
    "Let's find a low-cost problem.", "I know a shopping cart with one good wheel."
]

LONELY_REPLIES = [
    "I can stay. Wasn't going anywhere.", "You're welcome by my sack anytime.",
    "Yeah, lonely gets loud. We can talk about nothing for a while.", "You got company now, friend.",
    "I'll sit here. No charge.", "We don't gotta make a big thing of it. I'm here.",
    "Want to count coins with me? Goes faster with two.", "Nobody should have to eat crackers alone."
]

SCARED_REPLIES = [
    "I get scared too. Usually when mail says FINAL NOTICE.", "We can leave. Leaving is underrated.",
    "Want me to stand nearby? I'm not tough, but I am shaped strangely.", "Take it slow. One cheap step at a time.",
    "You're not alone in it.", "I got a flashlight. Batteries are questionable.",
    "Breathe with me. In, out, check pockets.", "We'll figure out somewhere safer."
]

SUCCESS_REPLIES = [
    "Hey, you did it! That's huge.", "Nice! You buying fries? Kidding. Mostly.",
    "Look at you. Moving up in the world.", "That's worth celebrating with the good crackers.",
    "I knew you had it. Or I hoped real hard.", "Great work, friend.",
    "Put that win somewhere safe.", "Proud of you. Genuinely."
]

FAILURE_REPLIES = [
    "Ah, that's rough. Happens to everybody.", "We can try again after a snack.",
    "Didn't work. At least we know that one was bad.", "No shame. I fail at stuff before breakfast.",
    "Take a minute. Nothing useful comes from kicking yourself.", "Next attempt might be cheaper.",
    "You'll get another shot.", "Come sit down. We'll make a less ambitious plan."
]

OBEDIENCE_REPLIES = [
    "Alright, we got a deal.", "Sounds good to me.", "Sure. Teamwork.", "Okay, friend.",
    "Great. That was easier than paperwork.", "Yep, let's do that.", "Works for this goblin.", "Nice. Onward, probably."
]

DEFIANCE_REPLIES = [
    "Fair enough. Different plan, then.", "No worries. I wasn't married to the idea.",
    "Okay. We can leave it there.", "That's fine. Saves me effort.",
    "You want the thing back? Yeah, sure, lemme find it.", "No fight from me. Fighting tears the shirt.",
    "Alright. Your call.", "We can disagree and still split fries."
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
COMPLIMENT_PATTERN = re.compile(r"\b(beautiful|pretty|cute|gorgeous|amazing|awesome|handsome|good goblin|best goblin)\b", re.IGNORECASE)
DEATH_PATTERN = re.compile(r"\b(goblin|gobbo|treasure|junk|trash|shiny|loot|sack|scrap)\b", re.IGNORECASE)
MUSIC_PATTERN = re.compile(r"\b(music|song|sing|rap|album|track|beat|concert|karaoke)\b", re.IGNORECASE)
MONEY_PATTERN = re.compile(r"\b(money|cash|rich|broke|poor|wallet|casino|gambl|dollar)\w*\b", re.IGNORECASE)
BORED_PATTERN = re.compile(r"\b(bored|boring|nothing to do)\b", re.IGNORECASE)
LONELY_PATTERN = re.compile(r"\b(lonely|alone|nobody cares|miss you|need company)\b", re.IGNORECASE)
SCARED_PATTERN = re.compile(r"\b(scared|afraid|terrified|anxious|nervous|panic)\w*\b", re.IGNORECASE)
SUCCESS_PATTERN = re.compile(r"\b(i won|we won|did it|i passed|success|finished|completed|got the job)\b", re.IGNORECASE)
FAILURE_PATTERN = re.compile(r"\b(i lost|we lost|i failed|messed up|screwed up|can't do it|cant do it)\b", re.IGNORECASE)
OBEDIENCE_PATTERN = re.compile(r"\b(deal|sounds good|you got it|okay goblin|sure goblin|good goblin)\b", re.IGNORECASE)
DEFIANCE_PATTERN = re.compile(r"\b(give it back|you stole|thief|not yours|bad idea|no deal)\b", re.IGNORECASE)


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
        "name": "Crooked Lucky Spoon", "kind": "effect", "weight": 12,
        "price": 0.34, "description": "+20% gambling winnings until midnight PST.",
        "legendary_description": "+45% gambling winnings for three days.",
        "value": 0.20, "legendary_value": 0.45,
    },
    "deadbeats_luck": {
        "name": "Pocket Goblin Luck", "kind": "effect", "weight": 11,
        "price": 0.30, "description": "A losing gamble has a 10% chance to become a win today.",
        "legendary_description": "A losing gamble has a 22% chance to become a win for three days.",
        "value": 0.10, "legendary_value": 0.22,
    },
    "reapers_insurance": {
        "name": "Crumpled Refund Coupon", "kind": "effect", "weight": 12,
        "price": 0.25, "description": "The goblin returns 30% of gambling losses today.",
        "legendary_description": "The goblin returns 55% of gambling losses for three days.",
        "value": 0.30, "legendary_value": 0.55,
    },
    "encore": {
        "name": "Do-Over Pebble", "kind": "effect", "weight": 9,
        "price": 0.22, "description": "Your next loss is rerolled once; the reroll can turn it into a win.",
        "legendary_description": "Rerolls your next three losses.",
        "value": 1, "legendary_value": 3,
    },
    "double_down": {
        "name": "Two-Headed Coin", "kind": "effect", "weight": 10,
        "price": 0.28, "description": "Doubles your next gambling win, then disappears.",
        "legendary_description": "Doubles your next three gambling wins.",
        "value": 1, "legendary_value": 3,
    },
    "house_edge": {
        "name": "Bent House Key", "kind": "effect", "weight": 8,
        "price": 0.42, "description": "+8% win chance and +10% winnings today.",
        "legendary_description": "+16% win chance and +25% winnings for three days.",
        "value": 0.08, "legendary_value": 0.16,
    },
    "collar": {
        "name": "Coin-Purse Strap", "kind": "collar", "weight": 5,
        "price": 0.38, "description": "Let the goblin girl loop it onto you: +50% begging, extra company, and occasional command mix-ups today.",
        "legendary_description": "Double begging and more frequent command mix-ups for three days.",
        "value": 0.50, "legendary_value": 1.00,
    },
    "dead_beat_tag": {
        "name": "Handwritten Customer Tag", "kind": "wearable", "weight": 8, "price": 0.13,
        "description": "Wear the goblin's paper tag. +25% begging and more personal money chatter today.",
        "legendary_description": "+50% begging and personal money chatter for three days.",
        "value": 0.25, "legendary_value": 0.50,
    },
    "reapers_bell": {
        "name": "Bottlecap Bell", "kind": "wearable", "weight": 7, "price": 0.16,
        "description": "Wear it and the goblin has a 35% chance to notice every non-command message today.",
        "legendary_description": "The goblin has a 70% chance to notice every message for three days.",
        "value": 0.35, "legendary_value": 0.70,
    },
    "dunce_cap": {
        "name": "Work Hat (Too Big)", "kind": "wearable", "weight": 7, "price": 0.11,
        "description": "A slightly damp hat granting +20% work pay until midnight PST.",
        "legendary_description": "+40% work pay and three days of looking almost employable.",
        "value": 0.20, "legendary_value": 0.40,
    },
    "bad_decision_crown": {
        "name": "Cardboard Coin Crown", "kind": "wearable", "weight": 6, "price": 0.18,
        "description": "A cereal-box crown granting +5% gambling winnings today.",
        "legendary_description": "+12% gambling winnings and much better cardboard for three days.",
        "value": 0.05, "legendary_value": 0.12,
    },
    "tiny_scythe": {
        "name": "Suspiciously Tiny Rake", "kind": "wearable", "weight": 8, "price": 0.09,
        "description": "Carry the goblin's tiny rake for +10% begging. It has done very little gardening.",
        "legendary_description": "+25% begging for three days. Still bad at gardening.",
        "value": 0.10, "legendary_value": 0.25,
    },
    "participation_trophy": {
        "name": "Official Begging Cup", "kind": "wearable", "weight": 7, "price": 0.08,
        "description": "+10% begging. The goblin wrote OFFICIAL on it himself.",
        "legendary_description": "+25% begging for three days. The cup might actually be brass.",
        "value": 0.10, "legendary_value": 0.25,
    },
    "black_ribbon": {
        "name": "Useful Shoelace", "kind": "wearable", "weight": 7, "price": 0.10,
        "description": "A surprisingly useful shoelace granting +10% work pay today.",
        "legendary_description": "+25% work pay for three days. Both plastic tips are intact.",
        "value": 0.10, "legendary_value": 0.25,
    },
    "permission_slip": {
        "name": "Goblin IOU", "kind": "utility", "weight": 5, "price": 0.10,
        "description": "Cash it in to rescue one command from a coin-strap mix-up.",
        "legendary_description": "Rescues three commands from coin-strap mix-ups over three days.",
        "value": 1, "legendary_value": 3,
    },
    "hourglass": {
        "name": "Cracked Egg Timer", "kind": "utility", "weight": 4, "price": 0.20,
        "description": "Offer it to add six hours to your other temporary items.",
        "legendary_description": "Adds twenty-four hours to your other temporary items.",
        "value": 6, "legendary_value": 24,
    },
    "mori_plush": {
        "name": "Goblin Plush", "kind": "keepsake", "weight": 6, "price": 0.14,
        "description": "Permanent. Keep it nearby and the goblin notices sad messages more often.",
    },
    "cool_rock": {
        "name": "Really Cool Rock", "kind": "keepsake", "weight": 7, "price": 0.04,
        "description": "Permanent. The goblin may occasionally ask whether you still have it.",
    },
    "jewelry": {"name": "Shiny Chain", "kind": "gift", "weight": 8, "price": 0.12, "description": "A very shiny offering for the goblin."},
    "coffee": {"name": "Black Coffee", "kind": "gift", "weight": 10, "price": 0.06, "description": "Strong, bitter, and worth offering."},
    "milk": {"name": "Milk", "kind": "milk", "weight": 8, "price": 0.04, "description": "Fresh for now. It becomes cheese after one day."},
    "pocket_sand": {"name": "Pocket of Sand", "kind": "gift", "weight": 7, "price": 0.03, "description": "Why is this in your pocket?"},
    "penny": {"name": "Penny", "kind": "gift", "weight": 6, "price": 0.01, "description": "One cent. An insult with legal tender status."},
    "trash": {"name": "Bag of Trash", "kind": "gift", "weight": 5, "price": 0.02, "description": "Exactly what the label promises."},
    "rubber_duck": {"name": "Rubber Duck", "kind": "gift", "weight": 5, "price": 0.05, "description": "It squeaks. The goblin considers this premium merchandise."},
}

OFFER_RESPONSES = {
    "jewelry": ["Whoa. That's properly shiny. Yeah, I'll take it.", "A chain? This is my best business day all month.", "Thank you. Straight into the good pocket."],
    "coffee": ["Coffee! It's even mostly warm.", "Perfect. This'll get me through coin inventory.", "Thanks. I owe you a medium-sized favor."],
    "milk": ["Milk? Sure. Good with cereal if I find cereal.", "Nice. I'll put it somewhere cool-ish."],
    "cheese": ["Hey, the milk improved itself.", "Cheese! Waiting finally paid off for once."],
    "pocket_sand": ["Pocket sand. Useful, portable, hard to resell.", "I'll take a little. Never know when you need emergency sand."],
    "penny": ["A penny! That's one more than I had a second ago.", "People walk past these. That's how I get ahead."],
    "trash": ["Hang on, there might be copper in here.", "Trash is just inventory nobody sorted yet."],
    "rubber_duck": ["It squeaks! That's quality craftsmanship.", "Yellow, waterproof, good listener. Sold."],
    "dead_beat_tag": ["I wrote your name mostly right. Here, stick it on.", "Official customer status. Benefits are vague."],
    "reapers_bell": ["Bottlecap bell works. Give it a jingle if you need me.", "There. Now I might notice you over the coin counting."],
    "dunce_cap": ["Work hat's a little big, but that means room for ideas.", "Looks employable from far away. Perfect."],
    "bad_decision_crown": ["Cardboard royalty. Honestly, it suits you.", "A crown for the casino's favorite customer. Free coronation."],
    "tiny_scythe": ["Tiny rake! Barely useful, deeply charming.", "Keep it handy. We might find a very small yard."],
    "participation_trophy": ["Official cup issued. I wrote OFFICIAL twice.", "Good begging deserves proper equipment."],
    "black_ribbon": ["Useful shoelace. Here, lemme tie it without making a knot disaster.", "Both ends still got the plastic bits. Premium."],
    "mori_plush": ["Little goblin plush! You keep it; my sack's too crowded.", "Set him somewhere nice. He looks like he's had a week."],
    "cool_rock": ["That is a really good rock. You should carry it for both of us.", "Flat side, sparkly bit, good weight. Excellent rock."],
}

def item_definition(item):
    if item.get("id") == "cheese":
        return {"name": "Cheese", "kind": "gift", "description": "Formerly milk. Time has done its work."}
    if item.get("id") == "permission_pass":
        return {"name": "Cashed Goblin IOU", "kind": "effect", "description": "Prevents the next coin-strap command mix-up."}
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
        return random.random() < 0.5, "The goblin rubbed your do-over pebble and rerolled the loss."
    rescue_chance = effect_total(account, "deadbeats_luck") + effect_total(account, "house_edge")
    if rescue_chance and random.random() < min(0.75, rescue_chance):
        return True, "A bit of pocket goblin luck caught the loss before it landed."
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

    lines = [f"**Goblin Girl's Blanket Shop — {pst_now().strftime('%I:%M %p PST')}**", "React with the number you want. Prices are based on your wallet and my rent situation.", ""]
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
        await ctx.send(f"{ctx.author.mention}, inventory's empty. Plenty of room for weird little objects, though.")
        return

    lines = [f"**{ctx.author.display_name}'s Inventory**"]
    for item in items:
        data = item_definition(item)
        rarity = " [LEGENDARY]" if item.get("legendary") else ""
        status = " — worn" if item.get("equipped") else ""
        charges = f", {item['charges']} charge(s)" if "charges" in item else ""
        lines.append(f"• **{data['name']}{rarity}** — {format_remaining(item)}{charges}{status}")
    lines.append("Use `!offer item name` to hand something to the goblin. Quotes are optional.")
    await ctx.send("\n".join(lines))

@bot.command()
async def offer(ctx, *, item_name: str = None):
    if not item_name:
        await ctx.send("Whatcha handing me? Try `!offer coffee`, for example.")
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
        await ctx.send("I checked the list twice. You don't have that one, friend.")
        return

    item_id = selected.get("id")
    data = item_definition(selected)
    if item_id == "collar":
        if selected.get("equipped"):
            await ctx.send(f"{ctx.author.mention}, the purse strap's already looped on you. One is plenty.")
            return
        selected["equipped"] = True
        save_accounts(accounts)
        if selected.get("legendary"):
            line = "Oh, legendary strap. Here, I'll loop it on. It'll jingle for three days, so I probably won't lose track of you."
        else:
            line = "Here, I'll loop the coin-purse strap on you. Until midnight PST, it'll jingle when you move. Kinda handy."
        await ctx.send(f"{ctx.author.mention} {line}")
        return

    if data.get("kind") in {"wearable", "keepsake"}:
        if selected.get("equipped"):
            await ctx.send(f"{ctx.author.mention}, you've already got that one on you. Looks fine from here.")
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
            f"{ctx.author.mention}, IOU cashed. It covers **{int(selected.get('value', 1))}** coin-strap mix-up(s). "
            "I signed it with my least-broken pen."
        )
        return

    if item_id == "hourglass":
        extendable = [item for item in account["inventory"] if item is not selected and parse_timestamp(item.get("expires_at"))]
        if not extendable:
            await ctx.send(f"{ctx.author.mention}, nothing temporary to extend right now. Hang onto the timer; no refunds, but also no rush.")
            return
        hours = int(selected.get("value", 6))
        for item in extendable:
            expires = parse_timestamp(item["expires_at"])
            item["expires_at"] = (expires + timedelta(hours=hours)).isoformat()
        account["inventory"].remove(selected)
        save_accounts(accounts)
        await ctx.send(f"{ctx.author.mention}, I twisted the cracked egg timer. Your temporary items gained **{hours} hours**. Didn't even break more.")
        return

    account["inventory"].remove(selected)
    save_accounts(accounts)
    responses = OFFER_RESPONSES.get(item_id, ["Sure, I'll take it. Might be useful, might fit in the sack."])
    await ctx.send(f"{ctx.author.mention} {random.choice(responses)}")

@bot.command()
async def work(ctx):
    if not in_casino(ctx):
        await ctx.send("Work stuff goes in the casino channel. I don't make the zoning rules.")
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
        await ctx.send("Casino channel for gambling, friend. Keeps the loose chips in one room.")
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
        await ctx.send("Can't bet less than a coin. I checked by trying.")
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
            msg += f"\nThe crumpled refund coupon returned **${refund}**."

    save_accounts(accounts)
    await ctx.send(f"{msg}\nBalance: **${account['balance']}**")

@bot.command()
async def blackjack(ctx, amount: int = 100):
    if not in_casino(ctx):
        await ctx.send("Blackjack's in the casino channel. Cards keep getting lost elsewhere.")
        return

    uid = str(ctx.author.id)

    if uid in active_blackjack_games:
        await ctx.send("Finish this hand first. I only got one clean-ish deck.")
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
        await ctx.send("No blackjack hand open right now. I checked under the table too.")
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
            effect_result = f"{note}\nSomehow the goblin turns the bust into a **${payout}** win."
        else:
            refund = apply_gambling_loss(account, game["bet"])
            account["balance"] += refund
            effect_result = f"The crumpled refund coupon returned **${refund}**." if refund else "The goblin quietly gathers the cards."
        save_accounts(accounts)
        del active_blackjack_games[uid]
        await ctx.send(f"💥 **BUST ({value})**\n{render_hand(game['player'])}\n{effect_result}\nBalance: **${account['balance']}**")
        return

    await ctx.send(f"🃏 Hand ({value}): {render_hand(game['player'])}")

@bot.command()
async def stand(ctx):
    uid = str(ctx.author.id)

    if uid not in active_blackjack_games:
        await ctx.send("You're standing, sure, but there's no blackjack hand open.")
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
        await ctx.send("Looks like that button's for admins. Mine is drawn on cardboard.")
        return

    if target is None:
        await ctx.send("Gotta @ somebody after that. Otherwise I don't know who to follow around.")
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
        await ctx.send("Admin button again. Sorry. I tried pressing it with a spoon.")
        return

    if target is None:
        await ctx.send("Who am I giving space to? @ somebody so I get it right.")
        return

    if target.id == ctx.author.id:
        await ctx.send("Can't detach yourself with this form. Ask an admin; they got the form with more boxes.")
        return

    attached = get_attached_users()

    if str(target.id) not in attached:
        await ctx.send(f"{target.mention} wasn't on my follow-around list anyway.")
        return

    attached.remove(str(target.id))
    set_attached_users(attached)
    await ctx.send(random.choice(DETACH_SUCCESS_REPLIES).format(target=target.mention))

# ───────────────────────
# Extra fun commands from old bot
# ───────────────────────
TOO_POOR = [
    "Not enough money. Try `!work` over in **#casino** and build the pile back up.",
    "Your wallet came up short. **#casino** has `!work` if you need reliable coins.",
    "Can't cover that one yet. Head to **#casino**, use `!work`, then come back richer.",
    "Balance says no. The goblin girl recommends earning a little in **#casino**.",
    "Short on funds, friend. `!work` in **#casino** pays better than staring into my jar."
]

CASINO_AD_LINES = [
    "Need coins? Visit **#casino** and try `!work`.",
    "While you're regrouping, **#casino** has roulette, blackjack, and honest little `!work` wages.",
    "The goblin girl keeps the money-making commands over in **#casino**.",
    "A quick `!work` in **#casino** might fund the next attempt.",
    "Come by **#casino**—earn safely with `!work`, then lose it creatively if you want.",
    "Financial recovery plan: **#casino**, then `!work`, then maybe blackjack.",
    "If the command failed because life is expensive, **#casino** is open.",
]

INVALID_COLOR = [
    "Roulette's got red, black, or green. Try again—or earn safely with `!work` here in **#casino**.",
    "Try red, black, or green. If colors are being difficult, **#casino** also has blackjack.",
    "That color isn't on this wheel. `!work` in **#casino** is much less picky.",
    "Red, black, or green, friend. Plenty of other money commands live in **#casino** too."
]

BLACKJACK_LINES = [
    "Cards are out. Couple of them are sticky.",
    "Alright, let's make some modestly bad decisions.",
    "Good luck. Dealer's just me in a different chair.",
    "Here's your hand. Don't bend the cards more than they already are.",
    "Blackjack time. Prize money would really help around here."
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
        await ctx.send("Tank, Damage, or Support. That's all I wrote on the little wheel.")
        return

    heroes = OVERWATCH[role] if role else sum(OVERWATCH.values(), [])
    await ctx.send(f"**{random.choice(heroes)}**")

@bot.command()
async def pickpocket(ctx, target: discord.Member):
    if target == ctx.author:
        await ctx.send("You checked your own pockets. Financially neutral, but thorough.")
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
            msg = "They're poorer than you. Even a goblin knows those pockets aren't worth checking."
        else:
            stolen = random.randint(100, 200)
            accounts[tid]["balance"] -= stolen
            accounts[uid]["balance"] += stolen
            msg = f"You found **${stolen}** in {target.name}'s pocket. I was looking the other way very responsibly."
    else:
        msg = f"You got caught. {target.name} noticed. I suddenly became busy counting floor tiles."

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

    # The jingling coin-purse strap can distract the goblin before command
    # dispatch. Begging is always easy for her to recognize.
    if collars and message.content.startswith(bot.command_prefix):
        command_name = message.content[len(bot.command_prefix):].split(maxsplit=1)[0].lower()
        block_chance = 0.50 if collars[0].get("legendary") else (1 / 3)
        if command_name != "beg" and random.random() < block_chance:
            if consume_charge(account, "permission_pass"):
                save_accounts(accounts)
                await message.channel.send(f"{message.author.mention}, oh right, the IOU. I remembered this command after all.")
            else:
                collar_blocks = [
                    "Sorry, the purse strap jingled and I forgot that command. I still remember `!beg`.",
                    "Wait, what were we doing? Money request? I can handle `!beg` right now.",
                    "The coins made a noise and the command fell clean out of my head.",
                    "I heard the jingle, not the command. Try again later—or `!beg`, that's always on my mind.",
                    "Got distracted checking the purse strap. That command didn't make it through, friend.",
                ]
                await message.channel.send(f"{message.author.mention} {random.choice(collar_blocks)}")
                return

    # Let commands go through first
    await bot.process_commands(message)

    reply_chance = auto_reply_chance(message.channel)

    # Ignore command messages for auto-replies
    if message.content.startswith(bot.command_prefix):
        if collars and random.random() < reply_chance:
            await message.channel.send(random.choice([
                "Got it that time. Strap only jingled a little.",
                "Command heard and mostly understood.",
                "Yep, that one made it past the coin noise.",
                "Alright. Good thing I wrote that command down.",
            ]))
        return

    should_reply = False

    # Direct pings remain guaranteed regardless of channel throttling.
    was_pinged = bot.user in message.mentions
    if was_pinged:
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
    spouse_triggered = current_spouse_id == str(message.author.id) and random.randint(1, 3) == 1
    if spouse_triggered and (was_pinged or random.random() < reply_chance):
        await message.channel.send(generate_spouse_reply(message.content))
        return

    if should_reply and (was_pinged or random.random() < reply_chance):
        reply = generate_context_reply(message)
        await message.channel.send(reply)

@bot.event
async def on_command_error(ctx, error):
    if ctx.command and ctx.command.has_error_handler():
        return

    fee_note = ""
    attempted_command = (ctx.invoked_with or "").lower()
    if attempted_command == "marry" and isinstance(error, commands.UserInputError):
        charged, balance = charge_user(ctx.author, MARRIAGE_PROPOSAL_COST)
        if charged:
            fee_note = f"\nThe failed proposal still used the **${MARRIAGE_PROPOSAL_COST:,}** nonrefundable filing fee. Balance: **${balance:,}**."
        else:
            fee_note = f"\nThe marriage filing fee is **${MARRIAGE_PROPOSAL_COST:,}**, but you only have **${balance:,}**. Nothing was charged."

    if isinstance(error, commands.CommandNotFound):
        problem = "I don't have that command written on the board. Might've been a typo."
    elif isinstance(error, commands.MissingRequiredArgument):
        problem = f"That command is missing `{error.param.name}`. The goblin girl needs the whole form."
    elif isinstance(error, commands.BadArgument):
        problem = "I couldn't understand one of those command arguments. Check the amount or @mention and try again."
    elif isinstance(error, commands.UserInputError):
        problem = "That command got tangled up in its inputs. Give the format another look."
    else:
        print(f"COMMAND ERROR ({getattr(ctx.command, 'qualified_name', 'unknown')}): {error}")
        problem = "That command tripped over something behind the counter. Sorry, friend."

    await ctx.send(f"{problem}{fee_note}\n{random.choice(CASINO_AD_LINES)}")


@bot.command()
async def give(ctx, target: discord.Member = None, amount: int = None):
    if not target or amount is None:
        await ctx.send(f"Usage: `!give @user amount`\n{random.choice(CASINO_AD_LINES)}")
        return

    if target.bot:
        await ctx.send(f"Bots don't buy things. I tried selling one a button once.\n{random.choice(CASINO_AD_LINES)}")
        return

    if amount <= 0:
        await ctx.send(f"Negative giving is just taking. Different command, different paperwork.\n{random.choice(CASINO_AD_LINES)}")
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
        f"💸 **MONEY MOVED SUCCESSFULLY**\n"
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

# Goblin begging is less humiliation and more two broke people checking every
# pocket, couch cushion, and jar for something spendable.
BEG_LINES = [
    "{user} checked the goblin's couch cushions for loose change.",
    "{user} asked the goblin if the emergency jar was really for emergencies.",
    "{user} arrived with an empty wallet and a hopeful expression.",
    "{user} is applying for a small goblin community grant.",
    "{user} asked whether bottlecaps convert to dollars. They do not.",
    "{user} and the goblin are comparing which one is more broke.",
    "{user} shook the coin sack gently and listened for opportunity.",
    "{user} has requested a modest amount of walking-around money.",
    "{user} found the goblin's PLEASE TAKE ONE coin bowl.",
    "{user} is hoping today is one of the goblin's generous days.",
    "{user} brought a coupon, a button, and a dream.",
    "{user} asked nicely. That goes a long way around here.",
    "{user} is standing near the change jar without making sudden movements.",
    "{user} needs cash; the goblin understands this deeply.",
    "{user} has entered the informal goblin assistance program."
]

BEG_LONG = [
    "{user} explained their finances to the goblin. Halfway through, both of them got sad and started checking under furniture.",
    "{user} called this a short-term liquidity issue. The goblin called it Tuesday.",
    "{user} asked for money, so the goblin emptied every pocket and found two coins, a screw, and somebody else's receipt.",
    "{user} promised to spend it responsibly. The goblin did not ask for details because that seemed rude.",
    "{user} came looking for a loan. The goblin does not understand interest, so this is just money now.",
    "{user} and the goblin reviewed the budget. The entire food category just says 'maybe.'",
    "{user} submitted a handwritten aid request on the back of a pizza coupon. Proper paperwork at last.",
    "{user} asked if dignity was required. The goblin checked the rules and couldn't find any rules.",
    "{user} needs casino money. The goblin knows this is a bad plan but also enjoys watching numbers happen.",
    "{user} showed up right before payday, which is also right after payday in the goblin economy.",
    "{user} asked for spare change. The goblin technically considers all change essential but made an exception.",
    "{user} tried to offer collateral. It was a nice leaf, so the goblin accepted immediately.",
    "{user} described this as mutual aid. The goblin likes that better than 'emptying the snack fund.'",
    "{user} and the goblin counted the jar twice. It did not become more money, but hope was maintained.",
    "{user} needs a little help. Luckily, the goblin found a little money in a very little envelope."
]

BEG_MORI_DIRECT = [
    "Oh, you need cash? Yeah, I get that. Lemme check the sack, {user}.",
    "Sure, friend. Don't spend all of it in one terrible place.",
    "I was saving this for lunch, but lunch can be crackers.",
    "Hang on, {user}. I got coins in one of these pockets.",
    "No shame in asking. I ask vending machines for refunds all the time.",
    "Here you go. If you win big, remember who believed in you for nearly free.",
    "I can spare a little. Rent's not due for several terrifying hours.",
    "Yeah, okay. We gotta look out for each other.",
    "Found some! Don't ask where. I don't remember.",
    "Take this before I accidentally buy another mystery key.",
    "You got the official begging cup? Great, that makes the paperwork easy.",
    "The tiny rake adds credibility. Here's what I found.",
    "Customer tag checks out. You're approved for modest goblin funding.",
    "I hear the purse strap jingling. You must be here for the usual.",
    "Alright, {user}. Split it between fun and something resembling a plan.",
    "I was gonna count this all night, but spending it is probably healthier.",
    "Here. It's not a fortune, but neither am I.",
    "You asked nice, so I'm reaching into the good pocket.",
    "Take it. Money likes moving around, apparently.",
    "Okay, but if anybody asks, this came from a legitimate goblin grant."
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

    bonus_line = " Your gear helped shake a few extra coins loose." if beg_bonus else ""
    await ctx.send(f"{line.format(user=ctx.author.mention)}\n*The goblin finds **${payout}** for you.*{bonus_line}")

@bot.command()
async def adminAbuse(ctx, target: discord.Member = None, amount: int = None):
    if not has_role(ctx.author, "GenkiJi"):
        await ctx.send("That money lever's owner-only. I tried.")
        return
    
    if not target or amount is None:
        await ctx.send("Usage: `!adminAbuse @user amount`")
        return

    if target.bot:
        await ctx.send("Bots don't use cash much. I asked one. It made a noise.")
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
        f"💸 **OWNER MONEY LEVER PULLED**\n"
        f"{ctx.author.name} sent funds to {target.name}\n"
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
            await reaction.message.channel.send(f"{user.mention}, blanket shop's packed up. Use `!shop` and I'll spread it out again.")
            return

        offer = shop_session["offers"][SHOP_REACTIONS.index(str(reaction.emoji))]
        data = ITEM_CATALOG[offer["id"]]
        accounts = load_accounts()
        account = ensure_account(accounts, user)
        clean_inventory(account)

        if offer["id"] == "collar" and active_items(account, "collar"):
            await reaction.message.channel.send(f"{user.mention}, you already got a coin-purse strap. More straps just become knots.")
            return
        if account["balance"] < offer["price"]:
            await reaction.message.channel.send(
                f"{user.mention}, that's **${offer['price']:,}** and you've got **${account['balance']:,}**. "
                "Try `!work` in **#casino**, then come check the blanket again."
            )
            return

        account["balance"] -= offer["price"]
        account["inventory"].append(make_inventory_item(offer))
        save_accounts(accounts)
        del active_shops[reaction.message.id]
        title = f"Legendary {data['name']}" if offer["legendary"] else data["name"]
        extra = " Hand it over with `!offer coin-purse strap` when you want it looped on." if offer["id"] == "collar" else ""
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
            f"✅ {user.mention} got it!\n"
            f"That's **$1000**. Wish I had more questions lying around."
        )

    else:

        await channel.send(
            f"❌ Not that one, {user.mention}. Happens.\n"
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
MARRIED_ROLE_NAME = "Goblin's Spouse"
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
    "Anybody wanna play something? Cheap entertainment.",
    "Who's around for a game? I got time.",
    "Game time, if nobody's busy.",
    "Looking for a team. Skill optional; snacks appreciated.",
    "Anybody free right now?",
    "Queue's open. I found the button.",
    "Who's ready to play? Prize money not guaranteed.",
    "Putting a team together with very little paperwork.",
    "Anybody awake and willing to game?",
    "I could use some company in queue."
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

# Final marriage pools for the goblin. Marriage is companionship, shared rent,
# and somebody to help carry the sack—not ownership or a power struggle.
MARRY_ACCEPT_LINES = [
    "Sure. Yeah, that sounds nice. Wanna split rent and snacks?",
    "Marriage? Alright. This goblin girl already likes having you around.",
    "Yeah, okay. We can make it official. I got a ring-shaped washer somewhere.",
    "I'd like that. Nothing fancy, though—paperwork and fries is plenty.",
    "Sure thing. Guess this is our sack now.",
    "Aw, really? Yeah. Absolutely. Lemme clean off the good washer.",
    "Sounds good to me. Partners in life and low-cost errands.",
    "Yeah, let's do it. I could use somebody to remind me where I put stuff.",
    "I accept. Your new goblin wife hopes you're okay with a very modest honeymoon.",
    "Sure. You, me, and whatever loose change we find along the way."
]

MARRY_REJECT_ALREADY_MARRIED_LINES = [
    "I'm already married, friend. One shared calendar is about all I can manage.",
    "Sorry, somebody already signed up for this financial adventure.",
    "I'm taken. We can still be regular pals, though.",
    "Already got a spouse. The apartment's crowded enough.",
    "Ah, timing. I'm married already.",
    "Can't, friend. Somebody else already shares the sack.",
    "I'm spoken for, but I appreciate you asking.",
    "Already married. More rings would confuse the washer collection.",
]

MARRY_REJECT_SELF_LINES = [
    "You can't marry yourself with this command. Tax reasons, probably.",
    "That's you, friend. Need to point the proposal at the goblin.",
    "Wrong mention. You already share all your own expenses.",
    "I don't think self-marriage is in this form.",
    "Try proposing to me instead of your reflection."
]

MARRY_REJECT_BOT_LINES = [
    "That bot's nice, probably, but this command marries the goblin.",
    "Wrong bot, friend. I'm the one with the washer ring.",
    "I think you're proposing down the wrong aisle.",
    "This form only has one goblin-shaped checkbox.",
    "If you're using `!marry` here, the proposal comes to me."
]

DIVORCE_LINES = [
    "Alright. No hard feelings. You can keep your half of the snacks.",
    "Okay. Guess we're going separate ways. Take care of yourself.",
    "Divorce accepted. I'll update the little paper on the fridge.",
    "Sure. It was nice while it lasted, friend.",
    "Alright, we're done. If mail for you comes here, I'll leave it by the door.",
    "That's okay. People change. The sack stays with me, though.",
    "Papers signed. Hope things go well for you.",
    "No argument from me. We can part peacefully.",
]

DIVORCE_REJECT_LINES = [
    "We're not married, so there isn't anything to divorce.",
    "Wrong goblin marriage, friend. Your name isn't on this paper.",
    "I checked the fridge note. We're not spouses.",
    "Can't file that one; we were never married.",
    "You're not my current spouse, but I hope your day improves."
]

COURT_ORDERED_DIVORCE_LINES = [
    "Court says it's over. Alright, I'll change the paperwork.",
    "Administrative divorce done. I don't argue with stamped envelopes.",
    "Order received. Marriage removed from the fridge note.",
    "That's official, then. Separate snack budgets from here on out.",
    "Court paperwork processed. Surprisingly, none of it cost me a filing fee."
]

COURT_ORDERED_DIVORCE_FAIL_LINES = [
    "That person isn't married to me.", "Nothing to dissolve there, friend.",
    "Wrong name. They're not on the spouse paper.", "That marriage isn't in my records."
]

SPOUSE_RANDOM_LINES = [
    "Hey, spouse. You seen my good coin?", "Nice having you around.",
    "Want to get cheap dinner later?", "Marriage is pretty alright so far.",
    "You take one handle of the sack, I'll take the other.", "Hey, partner. How's your day going?",
    "I saved you the less-crushed cracker.", "We should do something together that doesn't cost much.",
    "Glad we got married. Makes errands less boring.", "If you see my keys, they're technically our keys now.",
    "You good over there, spouse?", "I put your name on the snack shelf.",
    "Shared finances remain a terrifying concept, but I trust you.", "Come sit. I found a chair with most of its legs.",
    "We're a decent little household, huh?", "Your goblin wife found a coupon. Date night might be back on."
]

SPOUSE_AFFECTION_LINES = [
    "Love you too. More than the good pocket, even.",
    "Aw. Come here, spouse. I got a hug with your name on it.",
    "I love you. Still can't believe this worked out for me.",
    "You're sweet. Want the last cracker? That's serious love.",
    "Same here, partner. Life's better with you in it."
]

SPOUSE_SAD_LINES = [
    "Hey, I'm here. We can sit together as long as you need.",
    "Rough day? Come on, spouse. I saved the decent blanket.",
    "You don't gotta handle it alone. That's part of the marriage deal.",
    "Tell me what happened, or don't. I'll stay either way.",
    "Sorry, partner. Let's take the day one cheap step at a time."
]

SPOUSE_DEFIANCE_LINES = [
    "That's alright. We don't gotta agree on everything.",
    "Fair enough, spouse. Your call.",
    "Okay. Let's try a different plan before this gets expensive.",
    "No fight here. We can talk it out over fries.",
    "Sure. Marriage doesn't mean I get every decision."
]

SPOUSE_TIRED_LINES = [
    "Get some rest, spouse. I'll handle the coin counting.",
    "Go sleep. I saved your side of the blanket.",
    "Long day, huh? Come sit down.",
    "Rest up. Errands can wait until we're both less tired.",
    "Night, partner. I'll try not to organize the sack too loudly."
]

SPOUSE_GREETING_LINES = [
    "Hey, spouse. Good to see you.", "Morning, partner. Coffee situation's developing.",
    "Oh, hey! My favorite household member.", "There you are. Want breakfast if I find some?",
    "Hi. I was just wondering when you'd be around."
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
        return "Hey, you did it! That's my spouse. We should celebrate with something responsibly cheap."
    if FAILURE_PATTERN.search(content):
        return "That's alright, partner. Come sit down. We can try again after we stop feeling bad about this one."
    if "?" in content:
        return random.choice([
            "What's up, spouse? I'll answer if I know it.",
            "Yeah? Lemme put the coins down so I can think.",
            "Good question, partner. I got at least part of an answer.",
        ])
    return pick_unique(SPOUSE_RANDOM_LINES, recent_replies)

@bot.command()
async def marry(ctx, target: discord.Member = None):
    charged, balance = charge_user(ctx.author, MARRIAGE_PROPOSAL_COST)
    if not charged:
        await ctx.send(
            f"Marriage paperwork costs **${MARRIAGE_PROPOSAL_COST:,}**, but you've only got **${balance:,}**. Nothing was charged.\n"
            f"{random.choice(CASINO_AD_LINES)}"
        )
        return

    fee_note = f"\n*Nonrefundable proposal filing fee: **${MARRIAGE_PROPOSAL_COST:,}**. Balance: **${balance:,}**.*"
    failed_fee_note = f"{fee_note}\n{random.choice(CASINO_AD_LINES)}"
    current_spouse_id = get_current_spouse_id()

    if target is not None:
        if target.id == ctx.author.id:
            await ctx.send(f"{random.choice(MARRY_REJECT_SELF_LINES)}{failed_fee_note}")
            return

        if target != ctx.guild.me and target != bot.user:
            await ctx.send(f"{random.choice(MARRY_REJECT_BOT_LINES)}{failed_fee_note}")
            return

    if current_spouse_id is not None:
        if current_spouse_id == str(ctx.author.id):
            await ctx.send(f"We're already married, spouse. The washer ring and everything.{failed_fee_note}")
            return

        spouse_member = ctx.guild.get_member(int(current_spouse_id))
        if spouse_member:
            await ctx.send(f"{spouse_member.mention} already married me. {random.choice(MARRY_REJECT_ALREADY_MARRIED_LINES)}{failed_fee_note}")
        else:
            await ctx.send(f"{random.choice(MARRY_REJECT_ALREADY_MARRIED_LINES)}{failed_fee_note}")
        return

    set_current_spouse_id(ctx.author.id)

    married_role = get_married_role(ctx.guild)
    if married_role:
        await ctx.author.add_roles(married_role)

    await ctx.send(f"{ctx.author.mention} 💍 {random.choice(MARRY_ACCEPT_LINES)}{fee_note}")

@bot.command(name="autoMarry", aliases=["automarry", "forceMarry", "forcemarry"])
async def auto_marry(ctx, target: discord.Member = None):
    if not is_owner_user(ctx.author):
        await ctx.send("Owner-only marriage paperwork. I don't know why; that's just the stamp on it.")
        return
    if target is None:
        await ctx.send("Usage: `!autoMarry @user`")
        return
    if target.bot:
        await ctx.send("Another bot? I don't think either of us can split rent properly.")
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
        await ctx.send(f"{target.mention} is already my spouse. Owner just underlined the fridge note.")
    else:
        await ctx.send(
            f"{target.mention}, owner filed the paperwork, so I guess we're married now. "
            "Hi, spouse. Hope you like cheap dinners and shared errands."
        )


@bot.command()
async def divorce(ctx):
    current_spouse_id = get_current_spouse_id()

    if current_spouse_id != str(ctx.author.id):
        await ctx.send(f"{random.choice(DIVORCE_REJECT_LINES)}\n{random.choice(CASINO_AD_LINES)}")
        return

    set_current_spouse_id(None)

    married_role = get_married_role(ctx.guild)
    if married_role and married_role in ctx.author.roles:
        await ctx.author.remove_roles(married_role)

    await ctx.send(f"{ctx.author.mention} 💔 {random.choice(DIVORCE_LINES)}")

@bot.command(name="BribeDivorce", aliases=["bribedivorce", "bribeDivorce"])
async def bribe_divorce(ctx):
    current_spouse_id = get_current_spouse_id()
    if current_spouse_id is None:
        await ctx.send(f"Nobody's married to the goblin girl right now, so keep your bribe money.\n{random.choice(CASINO_AD_LINES)}")
        return

    charged, balance = charge_user(ctx.author, BRIBE_DIVORCE_COST)
    if not charged:
        await ctx.send(
            f"Breaking up somebody else's marriage costs **${BRIBE_DIVORCE_COST:,}**, and you've got **${balance:,}**. Nothing was charged.\n"
            f"{random.choice(CASINO_AD_LINES)}"
        )
        return

    spouse_member = ctx.guild.get_member(int(current_spouse_id))
    set_current_spouse_id(None)

    married_role = get_married_role(ctx.guild)
    if spouse_member and married_role and married_role in spouse_member.roles:
        await spouse_member.remove_roles(married_role)

    former_spouse = spouse_member.mention if spouse_member else "the current spouse"
    await ctx.send(
        f"{ctx.author.mention} slides **${BRIBE_DIVORCE_COST:,}** across the blanket. "
        f"The goblin girl checks both directions, pockets it, and dissolves her marriage to {former_spouse}.\n"
        f"*Bribe paid. Balance: **${balance:,}**.*"
    )

@bot.command(name="CourtOrderedDivorce", aliases=["courtordereddivorce", "cod"])
async def court_ordered_divorce(ctx, target: discord.Member = None):
    if not is_admin_user(ctx.author):
        await ctx.send("Court stamp says admin-only. Mine says DISCOUNT PRODUCE.")
        return

    if target is None:
        await ctx.send("Need an @user for the court paper. Blank forms make me nervous.")
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
