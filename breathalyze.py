import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import re
import os
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
MIXTRAL_ENDPOINT = os.getenv("MIXTRAL_ENDPOINT")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Per-user language profiles
user_baselines = defaultdict(lambda: {
    "avg_len": 0,
    "typo_rate": 0,
    "caps_rate": 0,
    "aggression": 0,
    "coherence": 0,
    "msg_count": 0
})

async def query_mixtral(prompt):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            MIXTRAL_ENDPOINT,
            json={
                "model": "mixtral",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a savage, sarcastic Discord bot with no filter. Respond as if you're publicly roasting someone who's clearly intoxicated online."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["message"]["content"]
            else:
                return f"[Mixtral error: {resp.status}]"

def analyze_message(msg):
    text = msg.content
    if not text.strip(): return None

    words = text.split()
    typo_score = sum(1 for word in words if not re.fullmatch(r"[a-zA-Z]{2,}", word)) / max(len(words), 1)
    caps_score = sum(1 for c in text if c.isupper()) / max(len(text), 1)
    aggression_score = sum(text.count(w) for w in ["fuck", "shit", "bitch", "asshole", "cunt", "kill", "die", "hate"])
    coherence_score = 1 if re.search(r"([a-zA-Z]{5,}){5,}", text) else 0  # loose nonsense detector

    return {
        "length": len(text),
        "typo_rate": typo_score,
        "caps_rate": caps_score,
        "aggression": aggression_score,
        "coherence": coherence_score
    }

def update_baseline(user_id, analysis):
    baseline = user_baselines[user_id]
    count = baseline["msg_count"]

    for key in ["avg_len", "typo_rate", "caps_rate", "aggression", "coherence"]:
        baseline[key] = (baseline[key] * count + analysis[key if key != "avg_len" else "length"]) / (count + 1)

    baseline["msg_count"] += 1

def get_intox_score(user_id, analysis):
    baseline = user_baselines[user_id]
    if baseline["msg_count"] < 10:
        return 0  # Not enough data to compare

    diff = (
        abs(analysis["length"] - baseline["avg_len"]) / (baseline["avg_len"] + 1) +
        abs(analysis["typo_rate"] - baseline["typo_rate"]) +
        abs(analysis["caps_rate"] - baseline["caps_rate"]) +
        abs(analysis["aggression"] - baseline["aggression"]) +
        abs(analysis["coherence"] - baseline["coherence"])
    )
    return min(round(diff * 25), 100)  # Normalize to 0–100

async def handle_fucked_up(user, message, intox_score):
    prompt = f"""You're a savage Discord bot detecting intoxication. User {user.display_name} just sent a message that scored {intox_score} on the fuck-up scale. Message: "{message.content}" Roast them hard, using Discord slang, emojis, references. You can also suggest a reaction GIF or sticker."""
    roast = await query_mixtral(prompt)
    await message.channel.send(f"{user.mention} {roast}")

@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    analysis = analyze_message(message)
    if not analysis:
        return

    update_baseline(message.author.id, analysis)
    intox_score = get_intox_score(message.author.id, analysis)

    if intox_score >= 75:
        await handle_fucked_up(message.author, message, intox_score)

    await bot.process_commands(message)

@bot.tree.command(name="breathalyze", description="Check how fucked up someone is.")
@app_commands.describe(user="The user to breathalyze")
async def breathalyze(interaction: discord.Interaction, user: discord.Member):
    recent_msgs = [m async for m in interaction.channel.history(limit=50) if m.author.id == user.id and m.content]
    if not recent_msgs:
        await interaction.response.send_message("I haven't seen them say anything yet.")
        return

    combined = " ".join(m.content for m in recent_msgs[:10])
    fake_msg = discord.Object(id=0)
    fake_msg.content = combined
    analysis = analyze_message(fake_msg)
    intox_score = get_intox_score(user.id, analysis)

    if intox_score < 25:
        reaction = "🫡 Sober soldier. For now."
    elif intox_score < 50:
        reaction = "🍷 Tipsy and tragic, but holding on."
    elif intox_score < 75:
        reaction = "🥴 You're swaying, my friend."
    else:
        reaction = "🚨 Fuckin’ plastered."

    await interaction.response.send_message(
        f"**Breathalyzer Score for {user.display_name}:** {intox_score}/100\n{reaction}"
    )

    if intox_score >= 75:
        prompt = f"""You're a Discord bot that just ran a breathalyzer on user {user.display_name}. Their fuck-up score is {intox_score}. Roast them mercilessly in a funny and mean way. Their recent messages were: {combined}"""
        roast = await query_mixtral(prompt)
        await interaction.channel.send(f"{user.mention} {roast}")

if __name__ == "__main__":
    bot.run(TOKEN)
