# Benchmark lap times

`gt3.json` holds quick GT3 lap times collected from sim racing leaderboards and race results. They are lap
*times* only (no telemetry), so they can't be reference laps by themselves. SimCoach uses them two ways:

* `tracks` (starter-lap track id → seconds): the calculated starter lap for that circuit is tuned so its GT3 lap
  time matches, which moves its braking points and corner speeds towards a real quick lap. Other car classes at
  that circuit get the same correction.
* `other`: tracks SimCoach has no starter lap for, matched by name and length. The coach tells GT3 drivers the
  target time at the start of the session.

The times come from different sims, so treat them as "about this quick", not as a record for your sim. SimCoach
downloads this file with its library check; edit it here and every SimCoach picks the change up.
