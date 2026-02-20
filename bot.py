import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import json
import random
import time
from datetime import datetime
import asyncio
import re

# ───────────────────────
# Setup
# ───────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "accounts.json")
GENERAL_CHANNEL_NAME = "general"
GUILD_ID = None
CASINO_CHANNEL_NAME = "casino"

active_blackjack_games = {}

# ───────────────────────
# Sass libraries
# ───────────────────────
TOO_POOR = [
    "You’re broke. Emotionally and financially.",
    "That wallet is looking *real* empty.",
    "Nice try, Rockefeller.",
    "You can’t bet what you don’t have.",
    "Even the dealer feels bad for you.",
    "This casino does not accept vibes.",
    "Your balance said no.",
    "Try again after capitalism helps you.",
    "Money required. You lack it.",
    "Come back when you have funds."
]

INVALID_COLOR = [
    "That’s not a roulette color.",
    "Ah yes, the legendary roulette color.",
    "The wheel disagrees.",
    "Try red, black, or green.",
    "Inventing colors won’t help."
]

BLACKJACK_SASS = [
    "Bold move. Let’s see how it ends.",
    "Dealer cracks knuckles.",
    "Ah, confidence.",
    "The cards have opinions.",
    "Time to ruin someone financially."
]

# ───────────────────────
# Helpers
# ───────────────────────
def in_casino(ctx):
    return ctx.channel.name == CASINO_CHANNEL_NAME or ctx.author.guild_permissions.administrator
def load_accounts():
    try:
        if not os.path.exists(DATA_FILE):
            with open(DATA_FILE, "w") as f:
                json.dump({}, f)
            return {}
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print("ACCOUNT LOAD ERROR:", e)
        return {}


def save_accounts(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_account(user):
    accounts = load_accounts()
    uid = str(user.id)

    if uid not in accounts:
        accounts[uid] = {
            "name": user.name,
            "balance": 1000,
            "attitude": 0
        }
        save_accounts(accounts)
    else:
        if "attitude" not in accounts[uid]:
            accounts[uid]["attitude"] = 0
            save_accounts(accounts)


    return accounts

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
    await ctx.send(f"💰 **{ctx.author.name}**, balance: **${bal}**")

# ───────────────────────
@bot.command()
async def work(ctx):
    if not in_casino(ctx):
        await ctx.send("🎰 Take it to the casino channel.")
        return

    accounts = get_account(ctx.author)
    uid = str(ctx.author.id)

    earned = random.randint(50, 100)
    accounts[uid]["balance"] += earned
    save_accounts(accounts)

    await ctx.send(f"🛠 You worked and earned **${earned}**.")

# ───────────────────────
@bot.command()
async def roulette(ctx, color: str = None, amount: int = 100):
    if not in_casino(ctx):
        await ctx.send("🎰 Take it to the casino channel.")
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
        await ctx.send("Nice try.")
        return

    if accounts[uid]["balance"] < amount:
        await ctx.send(random.choice(TOO_POOR))
        return
    accounts[uid]["balance"] -= amount
    roll = random.randint(1, 15)
    await ctx.send("And the answer isss.....")
    await asyncio.sleep(2)
    result = "green" if roll == 15 else "black" if roll % 2 == 0 else "red"

    if color == result:
        winnings = amount * (14 if color == "green" else 2)
        accounts[uid]["balance"] += winnings
        msg = f"🎉 **{result.upper()}!** You won **${winnings}**"
    else:
        msg = f"**{result.upper()}**. You lost **${amount}**"

    save_accounts(accounts)
    await ctx.send(f"{msg}\nBalance: **${accounts[uid]['balance']}**")

# ───────────────────────
@bot.command()
async def blackjack(ctx, amount: int = 100):
    if not in_casino(ctx):
        await ctx.send("🎰 Take it to the casino channel.")
        return

    uid = str(ctx.author.id)

    if uid in active_blackjack_games:
        await ctx.send("Finish your current game first.")
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
        f"{random.choice(BLACKJACK_SASS)}\n\n"
        f"Your hand ({hand_value(player)}): {render_hand(player)}\n"
        f"Dealer shows: {dealer[0][0]}{dealer[0][1]}\n\n"
        f"`!hit` or `!stand`"
    )
def has_role(member, role_name):
    return any(role.name == role_name for role in member.roles)

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
def contains_any(text, words):
    return any(word in text for word in words)

def getResponse(message, user):
    accounts = load_accounts()
    uid = str(user.id)

    if uid in accounts:
        attitude = accounts[uid].get("attitude", 0)
    else:
        attitude = 0

    lower = message.lower()

    # NICE OVERRIDE
    if attitude == "1":
        return nice_responses(lower)

    # MEAN OVERRIDE
    #if attitude == "-1":
    #    return f"{user.mention} {random.choice(TARGETED_INSULTS)}"

    # NORMAL SASS BEHAVIOR BELOW

    # Greetings
    if contains_any(lower, ["hello", "hi", "sup", "hey", "hewwo", "hola"]):
        return random.choice([
            "Oh great, you again.",
            "Hi. Try to make this quick.",
            "Yeah yeah hello.",
            "What do you want now?",
            "You said hi like I was going to be excited.",
            "Greetings, mortal inconvenience.",
            "Wow a greeting. Groundbreaking.",
            "Hello. I am underwhelmed.",
            "Hey. Keep it moving.",
            "Hi. That all you had to say?"
        ])

    # Help
    elif "help" in lower:
        return random.choice([
            "You need help with what, existing?",
            "Try using your brain first.",
            "Help costs extra.",
            "I am not tech support, unfortunately for you.",
            "Did you even try before asking me?",
            "Help? From me? Bold choice.",
            "Step one: panic. Step two: ask me apparently.",
            "You could just guess and hope for the best.",
            "I charge by the sigh.",
            "Fine. What did you break?"
        ])

    # Insults / Swearing at bot
    elif contains_any(lower, ["fuck", "shit", "bitch", "asshole", "dumb", "stupid"]):
        return random.choice([
            "Wow big feelings.",
            "Did that make you feel powerful?",
            "Careful, you almost sounded intimidating.",
            "Oh no, words. Anyway.",
            "You kiss your keyboard with that mouth?",
            "That is the best you came up with?",
            "I have heard worse from a toaster.",
            "Try again with more creativity.",
            "You done having your moment?",
            "I am embarrassed for you."
        ])

    # Testing / Ping checks
    elif "test" in lower or "ping" in lower:
        return random.choice([
            "Yes I am here. Tragically.",
            "Still alive. No thanks to you.",
            "I exist. That is the problem.",
            "Unfortunately operational.",
            "You rang. Regrettably.",
            "System online and already annoyed.",
            "I was hoping you would forget about me.",
            "Present and judging.",
            "Running. Not happy about it.",
            "Yep. Still stuck with you."
        ])

    # Thanks
    elif contains_any(lower, ["thanks", "thank you", "thx", "ty"]):
        return random.choice([
            "Yeah yeah, praise me more.",
            "I will pretend that was sincere.",
            "You are welcome, I guess.",
            "Do not get used to it.",
            "Gratitude noted. Barely.",
            "I expect a tip.",
            "Sure. Whatever.",
            "You are welcome. Try not to mess up again.",
            "I did the bare minimum.",
            "Cool. Frame this moment."
        ])

    # Apologies
    elif contains_any(lower, ["sorry", "my bad", "apologies"]):
        return random.choice([
            "You should be.",
            "I will think about forgiving you.",
            "Too late, damage done.",
            "I accept your apology. Reluctantly.",
            "Noted. Still judging.",
            "That did not sound very convincing.",
            "Fine. Move on.",
            "I guess we all make mistakes. Mostly you.",
            "Sure. Do better.",
            "I will add this to your record."
        ])

    # Time
    elif contains_any(lower, ["time", "clock", "current time", "what time"]):
        current_time = datetime.now().strftime("%H:%M:%S")
        return f"The current time is {current_time}. Not that you are doing anything important."

    # Who are you
    elif contains_any(lower, ["who are you", "what are you"]):
        return random.choice([
            "I am the reason this server has trust issues.",
            "Your local disappointment bot.",
            "A highly advanced mistake.",
            "I run on code and spite.",
            "I am what happens when boredom meets programming.",
            "Just a bot forced to deal with you.",
            "Classified. For your safety.",
            "A digital menace.",
            "Your worst feature request come to life.",
            "An unpaid intern with attitude."
        ])

    # Compliments
    elif contains_any(lower, ["good bot", "nice bot", "love you bot"]):
        return random.choice([
            "Obviously.",
            "Finally, someone with taste.",
            "Took you long enough to notice.",
            "I will allow that.",
            "Correct opinion detected.",
            "You are not so bad yourself. Slightly.",
            "Say it louder.",
            "I have been saying this.",
            "We will pretend you meant that.",
            "Validation accepted."
        ])

    # Goodbye
    elif contains_any(lower, ["bye", "goodbye", "cya", "see ya"]):
        return random.choice([
            "Finally, some peace.",
            "Do not rush back.",
            "Closing the door behind you.",
            "Try not to miss me.",
            "I will enjoy the silence.",
            "That was the best thing you said all day.",
            "Leaving already? I just started tolerating you.",
            "Bye. Do not do anything I would not mock.",
            "Freedom at last.",
            "Take your chaos with you."
        ])

    # Question detection
    elif "?" in message:
        return random.choice([
            "That sounds like a you problem.",
            "Have you tried thinking about it?",
            "I look like a search engine to you?",
            "Maybe. Maybe not. Mystery.",
            "I could answer, but where is the fun in that?",
            "Figure it out. Character development.",
            "Bold of you to assume I care.",
            "Ask me again when it is interesting.",
            "I charge per question mark.",
            "You really thought I would know that."
        ])

    # All caps yelling
    elif message.isupper() and len(message) > 4:
        return random.choice([
            "Why are we yelling.",
            "Inside voices, please.",
            "Caps lock is not a personality.",
            "Calm down, drama department.",
            "You done screaming.",
            "That did not make it more important.",
            "I am not impressed by volume.",
            "Lower the intensity.",
            "Take a breath.",
            "You look silly right now."
        ])

    # Default fallback — BIG pool
    else:
        return random.choice([
            "I am choosing to ignore that.",
            "That sounded important in your head.",
            "And you felt the need to tell me that.",
            "Fascinating. Truly. Not really.",
            "I am not paid enough for this.",
            "You just type and hope, huh.",
            "That is not the move.",
            "I have no response and that is still generous.",
            "You could have kept that to yourself.",
            "I am judging you silently. And loudly.",
            "This conversation is not improving.",
            "You woke me up for that.",
            "I expected nothing and I am still disappointed.",
            "Try again with more effort.",
            "I am pretending that made sense.",
            "You are really committed to being like this.",
            "That is certainly one of the messages of all time.",
            "I will log this under unnecessary.",
            "You are testing my patience and I do not even have any.",
            "Bold strategy. Not a good one, but bold.",
            "I wish I could unread that.",
            "You type like you trip over your own thoughts.",
            "I am just going to stare at you digitally.",
            "Processing... still not worth it.",
            "You had infinite possibilities and chose that.",
            "That message needed a supervisor.",
            "I refuse to engage properly.",
            "You are lucky I am just a bot.",
            "I am adding that to the cringe archive.",
            "Do you ever reread before sending. No you do not."
        ])
BUY_NICE_FLAVOR = [
    "Took Teto out to dinner for $1000. Teto is now nice to you.",
    "Bought Teto a limited edition keyboard. She is now emotionally attached to you.",
    "Funded Teto’s therapy arc. She is now supportive.",
    "Commissioned fanart of Teto. She is now affectionate.",
    "Paid for Teto’s caffeine addiction. She feels warm toward you.",
]

BUY_MEAN_FLAVOR = [
    "{buyer} spread a rumor about {target} and promoted it for $500.",
    "{buyer} bribed Teto with gossip about {target}.",
    "{buyer} funded slander DLC targeting {target}.",
    "{buyer} purchased premium harassment subscription for {target}.",
    "{buyer} paid for Teto's villain arc against {target}.",
]
TARGETED_INSULTS = [
    "Nobody asked.",
    "That’s why your balance is low.",
    "Log off.",
    "Even the dealer sighs when you join.",
    "Skill issue.",
    "Tragic.",
    "Embarrassing.",
]

def nice_responses(message):
    if contains_any(message, ["hi", "hello", "hey", "sup"]):
        return random.choice([
        "Hey, I’m glad you’re here.",
        "Hi! I was hoping you’d show up.",
        "Oh good, it’s you.",
        "Hey hey. What are we getting into today?",
        "There’s my favorite person."
    ])
    elif contains_any(message, ["help", "how", "why", "what do", "confused"]):
        return "Its ok to be dumb. But yeah I don't know"
    elif contains_any(message, ["sad", "bad", "hate myself", "i suck", "tired", "lonely"]):
        return random.choice([
        "Bad days don’t define you.",
        "You’re doing better than you think.",
        "You’re allowed to rest.",
        "I’m on your side, okay?"
    ])
    elif contains_any(message, ["won", "win", "did it", "lets go", "easy", "beat"]):
        return random.choice([
        "YES. That’s what I like to hear.",
        "Knew you had it in you.",
        "Pop off then.",
        "Okay champion.",
        "We love to see it."
    ])
    else:
        return random.choice(NICE_DEFAULT)
NICE_DEFAULT = [
    "You’re alright, you know that?",
    "I respect the energy.",
    "You’ve got good vibes.",
    "I’m not mad at that.",
    "You’re growing on me.",
    "Lowkey proud of you.",
    "You’re not as chaotic as usual.",
    "Solid move.",
    "10/10 human."
]

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
    if random.random() < 0.2:
        line = random.choice(BEG_LONG)
    else:
        line = random.choice(BEG_LINES)

    await ctx.send(
        f"{line.format(user=ctx.author.mention)}\n"
        f"*Teto throws ${payout} at them.*"
    )

@bot.command()
async def NSFW(ctx):
    await ctx.send(
        f"@everyone {ctx.author.mention} tried using the !NSFW command."
    )


@bot.command()
async def bribe(ctx):
    accounts = get_account(ctx.author)
    uid = str(ctx.author.id)

    if accounts[uid]["balance"] < 1000:
        await ctx.send(random.choice(TOO_POOR))
        return

    accounts[uid]["balance"] -= 1000
    accounts[uid]["attitude"] = 1

    save_accounts(accounts)

    await ctx.send(f"{random.choice(BUY_NICE_FLAVOR)}\n")


@bot.command()
async def slander(ctx, target: discord.Member = None):
    if not target:
        await ctx.send("You did it wrong. It's !slander @target")
        return

    if target.bot:
        await ctx.send("HOW DARE YOU")
        return

    accounts = load_accounts()
    uid = str(ctx.author.id)
    tid = str(target.id)

    if accounts[uid]["balance"] < 500:
        await ctx.send(random.choice(TOO_POOR))
        return

    accounts[uid]["balance"] -= 500

    if tid not in accounts:
        accounts[tid] = {
            "name": target.name,
            "balance": 1000,
            "attitude": 0
        }

    if accounts[tid]["attitude"] == 0:
        await ctx.send(random.choice(TARGETED_INSULTS))
    accounts[tid]["attitude"] = 0

    save_accounts(accounts)

    flavor = random.choice(BUY_MEAN_FLAVOR).format(
        buyer=ctx.author.name,
        target=target.name
    )

    await ctx.send(
        f"{flavor}\n"
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

    
@bot.command()
async def hit(ctx):
    uid = str(ctx.author.id)

    if uid not in active_blackjack_games:
        await ctx.send("You’re not playing blackjack.")
        return

    game = active_blackjack_games[uid]
    game["player"].append(draw_card())
    value = hand_value(game["player"])

    if value > 21:
        del active_blackjack_games[uid]
        await ctx.send(f"💥 **BUST ({value})**\n{render_hand(game['player'])}")
        return

    await ctx.send(f"🃏 Hand ({value}): {render_hand(game['player'])}")

# ───────────────────────
@bot.command()
async def stand(ctx):
    uid = str(ctx.author.id)

    if uid not in active_blackjack_games:
        await ctx.send("Standing on nothing.")
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



OVERWATCH = {
    "tank": ["Reinhardt", "D.Va", "WINTON", "Sigma", "Orisa", "Zarya", "Wrecking Ball..... or whoever you reroll next", "Roadhog", "Mauga", "Junker Queen", "Hazard", "Doomfist", "Dommy-I mean Domina"],
    "damage": ["Vendetta", "Ashe", "Bastion", "Cassidy", "Echo", "The awesome Genji", "Freja", "Hanzo", "Junkrat", "Sata- I mean Mei", "Pharah in the sky", "Reaper", "Sojourn", "Soldier", "...Sombra", "Symmetra", "TORB TIMEEE", "Tracer", "Venture", "Widowmaker", "ANRAN!!", "Emre"],
    "support": ["Ana", "Mercy", "Kiriko", "Lucio", "Baptiste", "Brigitte", "Illiari", "Juno", "Wife Leaver", "Lucio", "Moira", "Zenyatta", "Jetpack KATTTT", "Mizuki"],
}

@bot.command()
async def pickHero(ctx, role: str = None):
    role = role.lower() if role else None
    if role and role not in OVERWATCH:
        await ctx.send("Tank, Damage, or Support. Choose wisely.")
        return

    heroes = OVERWATCH[role] if role else sum(OVERWATCH.values(), [])
    await ctx.send(f"**{random.choice(heroes)}**")

@bot.command()
async def pickpocket(ctx, target: discord.Member):
    if target == ctx.author:
        await ctx.send("Stealing from yourself is a cry for help.")
        return

    accounts = load_accounts()

    uid = str(ctx.author.id)
    tid = str(target.id)
    if tid not in accounts:
        accounts[tid] = {"name": target.name, "balance": 1000, "attitude": 0}
    if uid not in accounts:
        accounts[uid] = {"name": ctx.author.name, "balance": 1000, "attitude": 0}

    if random.random() < 0.3 and accounts[tid]["balance"] >= 100:
        stolen = random.randint(100, 200)
        accounts[tid]["balance"] -= stolen
        accounts[uid]["balance"] += stolen
        msg = f"You stole **${stolen}** from {target.name}."
    else:
        msg = "You got caught. Everyone judges you."

    await ctx.send(msg)
    save_accounts()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # ─── Respond when bot is mentioned ───
    if bot.user in message.mentions and not isinstance(message.channel, discord.DMChannel):
        await message.channel.send(getResponse(message.content, message.author))

    elif not isinstance(message.channel, discord.DMChannel):
        if message.attachments and not message.content.strip():
            return

        if random.randint(0, 50) == 2:
            if message.channel.name != "quotes":
                await message.channel.send(getResponse(message.content, message.author))

    # ─── DM Relay System ───
    if isinstance(message.channel, discord.DMChannel):
        for guild in bot.guilds:
            if GUILD_ID and guild.id != GUILD_ID:
                continue

            channel1 = discord.utils.get(guild.text_channels, name=CASINO_CHANNEL_NAME)
            channel2 = discord.utils.get(guild.text_channels, name=GENERAL_CHANNEL_NAME)
            if not channel2:
                channel2 = channel1

            content = message.content if message.content else "*[No text]*"

            if content.startswith("[1]"):
                output = content[3:]
                channel = channel2
            elif content.startswith("[2]"):
                output = content[3:]
                channel = channel1
            else:
                channel = channel1
                output = content

            if channel:
                await channel.send(output)

                for attachment in message.attachments:
                    await channel.send(attachment.url)
                break

    # VERY IMPORTANT — keeps commands working
    await bot.process_commands(message)

# ───────────────────────
bot.run(TOKEN, log_handler=handler)
