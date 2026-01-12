import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import json
import random

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
GENERAL_CHANNEL_NAME = "casino"
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
            "balance": 1000
        }
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
    "tank": ["Reinhardt", "D.Va", "WINTON", "Sigma", "Orisa", "Zarya", "Wrecking Ball..... or whoever you reroll next", "Roadhog", "Mauga", "Junker Queen", "Hazard", "Doomfist"],
    "damage": ["Vendetta", "Ashe", "Bastion", "Cassidy", "Echo", "The awesome Genji", "Freja", "Hanzo", "Junkrat", "Sata- I mean Mei", "Pharah in the sky", "Reaper", "Sojourn", "Soldier", "...Sombra", "Symmetra", "TORB TIMEEE", "Tracer", "Venture", "Widowmaker"],
    "support": ["Ana", "Mercy", "Kiriko", "Lucio", "Baptiste", "Brigitte", "Illiari", "Juno", "Wife Leaver", "Lucio", "Moira", "Zenyatta"],
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

    if random.random() < 0.3 and accounts[tid]["balance"] >= 100:
        stolen = random.randint(100, 200)
        accounts[tid]["balance"] -= stolen
        accounts[uid]["balance"] += stolen
        msg = f"You stole **${stolen}** from {target.name}."
    else:
        msg = "You got caught. Everyone judges you."

    await ctx.send(msg)
@bot.event
async def on_message(message):
    # Ignore bot messages
    if message.author.bot:
        return

    # If message is a DM
    if isinstance(message.channel, discord.DMChannel):
        for guild in bot.guilds:
            if GUILD_ID and guild.id != GUILD_ID:
                continue

            channel = discord.utils.get(guild.text_channels, name=GENERAL_CHANNEL_NAME)
            if channel:
                content = message.content if message.content else "*[No text]*"

                await channel.send(
                    f"{content}"
                )

                # Forward attachments
                for attachment in message.attachments:
                    await channel.send(attachment.url)

                break

    # IMPORTANT: allows commands to keep working
    await bot.process_commands(message)

# ───────────────────────
bot.run(TOKEN, log_handler=handler)
