# GarminCoach HA Automation Templates

After GarminCoach sensors are pushed to HA (via `ha-notify.py`), use these automations.
Copy into your `automations.yaml` or import via the HA UI.

Available sensors:
- `sensor.garmincoach_acwr` — Acute:Chronic Workload Ratio
- `sensor.garmincoach_form` — Training Stress Balance (TSB)
- `sensor.garmincoach_injury_risk` — Risk level: low/moderate/elevated/high
- `sensor.garmincoach_ctl` — Chronic Training Load (Fitness)
- `sensor.garmincoach_atl` — Acute Training Load (Fatigue)
- `sensor.garmincoach_body_battery` — Body Battery %
- `sensor.garmincoach_sleep_debt` — Sleep debt in hours

---

## 1. Low Body Battery — Dim Lights & Enable DND

```yaml
- alias: "GarminCoach — Low Body Battery Recovery Mode"
  description: "Dim lights and enable DND when body battery is critically low"
  trigger:
    - platform: numeric_state
      entity_id: sensor.garmincoach_body_battery
      below: 40
  condition:
    - condition: time
      after: "06:00:00"
      before: "22:00:00"
  action:
    - service: light.turn_on
      target:
        area_id: living_room
      data:
        brightness_pct: 30
        color_temp: 500   # warm light for recovery
    - service: notify.mobile_app
      data:
        title: "🔋 Recovery Mode Active"
        message: >
          Body Battery {{ states('sensor.garmincoach_body_battery') }}% — lights dimmed.
          Consider rest or gentle movement today.
```

## 2. Morning Training Briefing (TTS / Mobile)

```yaml
- alias: "GarminCoach — Morning Training Briefing"
  description: "Daily AI coaching briefing at 7 AM"
  trigger:
    - platform: time
      at: "07:00:00"
  action:
    - service: tts.cloud_say
      target:
        entity_id: media_player.kitchen_speaker
      data:
        message: >
          Good morning! Your GarminCoach readiness summary:
          Body Battery {{ states('sensor.garmincoach_body_battery') }} percent.
          Training form is {{ states('sensor.garmincoach_form') }} points.
          {% if states('sensor.garmincoach_injury_risk') == 'high' %}
            Warning: injury risk is high today. Consider rest or easy training.
          {% elif states('sensor.garmincoach_injury_risk') == 'elevated' %}
            Injury risk is elevated. Keep intensity moderate.
          {% else %}
            Risk level is low. Have a great workout!
          {% endif %}
    - service: notify.mobile_app
      data:
        title: "🏃 Morning Briefing"
        message: >
          Body Battery: {{ states('sensor.garmincoach_body_battery') }}% |
          Form: {{ states('sensor.garmincoach_form') }} |
          ACWR: {{ states('sensor.garmincoach_acwr') }} |
          Risk: {{ states('sensor.garmincoach_injury_risk') }}
```

## 3. High Injury Risk Alert

```yaml
- alias: "GarminCoach — High Injury Risk Alert"
  trigger:
    - platform: state
      entity_id: sensor.garmincoach_injury_risk
      to: "high"
  action:
    - service: notify.mobile_app
      data:
        title: "⚠️ High Injury Risk"
        message: >
          ACWR {{ states('sensor.garmincoach_acwr') }} — training load has spiked.
          Recommended: reduce volume by 30% for 2-3 days.
    - service: light.turn_on
      target:
        entity_id: light.office_led_strip  # adjust to your entity
      data:
        rgb_color: [255, 60, 0]  # orange alert
        brightness_pct: 80
```

## 4. Training Reminder When Fresh (High Form)

```yaml
- alias: "GarminCoach — Training Reminder (Fresh)"
  description: "Suggest training when TSB is positive (fresh/rested)"
  trigger:
    - platform: numeric_state
      entity_id: sensor.garmincoach_form
      above: 5
  condition:
    - condition: time
      at: "08:00:00"
    - condition: numeric_state
      entity_id: sensor.garmincoach_body_battery
      above: 60
  action:
    - service: notify.mobile_app
      data:
        title: "💪 Great Day to Train!"
        message: >
          Form is +{{ states('sensor.garmincoach_form') }} (fresh).
          Body Battery {{ states('sensor.garmincoach_body_battery') }}%.
          Consider a quality session today — your body is ready.
```

## 5. Sleep Debt — Auto DND & Earlier Bedtime Reminder

```yaml
- alias: "GarminCoach — Sleep Debt Management"
  trigger:
    - platform: numeric_state
      entity_id: sensor.garmincoach_sleep_debt
      above: 1.5   # more than 1.5 hours debt
  action:
    - service: notify.mobile_app
      data:
        title: "💤 Sleep Debt Alert"
        message: >
          Sleep debt: {{ states('sensor.garmincoach_sleep_debt') }}h.
          Aim for {{ (8 + states('sensor.garmincoach_sleep_debt') | float) | round(1) }}h tonight.
    - service: input_boolean.turn_on
      target:
        entity_id: input_boolean.dnd_mode   # if you have DND helper
```

## 6. Weekly Summary (Sunday Evening)

```yaml
- alias: "GarminCoach — Weekly Summary"
  trigger:
    - platform: time
      at: "19:00:00"
    - platform: template
      value_template: "{{ now().weekday() == 6 }}"  # Sunday
  action:
    - service: notify.mobile_app
      data:
        title: "📊 Weekly Training Summary"
        message: >
          This week:
          Fitness (CTL): {{ states('sensor.garmincoach_ctl') }}
          Fatigue (ATL): {{ states('sensor.garmincoach_atl') }}
          Form (TSB): {{ states('sensor.garmincoach_form') }}
          ACWR: {{ states('sensor.garmincoach_acwr') }}
          Risk: {{ states('sensor.garmincoach_injury_risk') }}
```

## 7. Voice Query via Google/Alexa

Add to your conversation agent triggers (OpenClaw/Google Home):

```yaml
- alias: "Voice — ACWR Query"
  trigger:
    - platform: conversation
      command:
        - "What is my ACWR"
        - "What is my training ratio"
        - "Am I overtraining"
  action:
    - service: tts.cloud_say
      target:
        entity_id: media_player.living_room
      data:
        message: >
          Your current ACWR is {{ states('sensor.garmincoach_acwr') }}.
          {% if states('sensor.garmincoach_acwr') | float > 1.5 %}
            This is in the high risk zone. Consider reducing load.
          {% elif states('sensor.garmincoach_acwr') | float > 1.3 %}
            This is in the caution zone. Monitor closely.
          {% else %}
            This is in the optimal training zone. Keep it up!
          {% endif %}
```
