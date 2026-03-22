# Telegram Bot Integration for OpenClaw

This guide explains how to connect your OpenClaw AI assistant to Telegram
so you can send messages and get fitness coaching responses via Telegram.

## Prerequisites
- Home Assistant with OpenClaw addon running
- Telegram account

## Step 1: Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Choose a name: e.g., "GarminCoach Bot"
4. Choose a username: e.g., `garmincoach_yourname_bot`
5. Copy the **bot token** (format: `1234567890:ABCDefGhIJKlmNoPQRsTUVwxyZ`)

## Step 2: Get Your Chat ID

1. Start a chat with your new bot (send any message)
2. Open: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `"chat":{"id":` — copy that number (your chat ID)

## Step 3: Configure Home Assistant

Add to your `configuration.yaml`:

```yaml
telegram_bot:
  - platform: polling
    api_key: "YOUR_BOT_TOKEN"
    allowed_chat_ids:
      - YOUR_CHAT_ID

notify:
  - name: telegram_garmin
    platform: telegram
    chat_id: YOUR_CHAT_ID
```

## Step 4: Wire to OpenClaw

Add to your `automations.yaml`:

```yaml
- alias: "Telegram → OpenClaw"
  trigger:
    - platform: event
      event_type: telegram_text
      event_data:
        chat_id: YOUR_CHAT_ID
  action:
    - service: conversation.process
      data:
        agent_id: conversation.openclaw_assistant
        text: "{{ trigger.event.data.text }}"
      response_variable: ai_response
    - service: telegram_bot.send_message
      data:
        target: YOUR_CHAT_ID
        message: "{{ ai_response.response.speech.plain.speech }}"

- alias: "Daily Garmin Briefing → Telegram"
  trigger:
    - platform: time
      at: "07:00:00"
  action:
    - service: notify.telegram_garmin
      data:
        message: >
          🏃 Morning Fitness Briefing
          Body Battery: {{ states('sensor.garmin_body_battery') }}%
          HRV: {{ states('sensor.garmin_hrv') }} ms
          ACWR: {{ states('sensor.garmincoach_acwr') }}
          Risk: {{ states('sensor.garmincoach_injury_risk') }}
```

## Step 5: Test

Send "What is my training status today?" to your Telegram bot.
OpenClaw will respond with a personalized coaching analysis.

## Example Queries
- "What's my readiness today?"
- "Should I train hard or recover?"
- "What's my injury risk?"
- "How's my sleep debt this week?"
