-- SimCoach Weather Link, a Lua app for Custom Shaders Patch.
-- Shares the weather CSP is running (Pure and Pure Planner, or any other WeatherFX) with SimCoach, the voice
-- coach: rain, how wet the track is, puddles, and what's coming next. It only reads, it changes nothing in the
-- game, and it runs by itself from the start (LAZY = NONE); the window is only there to check it's working.

local VERSION = 1
local MMF_NAME = 'SimCoach.CSPWeather.v1'     -- SimCoach opens it as Local\SimCoach.CSPWeather.v1
local LAYOUT = [[
  int32_t version;
  int32_t seq;
  int32_t currentType;
  int32_t upcomingType;
  float transition;
  float rainIntensity;
  float rainWetness;
  float rainWater;
  float ambientTemperature;
  float roadTemperature;
  float roadGrip;
  float timeMultiplier;
  int32_t weatherFX;
  int32_t cspVersion;
  double timeOfDay;
]]

local mem, seq, status = nil, 0, 'Starting...'
local retryAt = 0
local setupMem, lastSetupSeq, setupRetryAt = nil, 0, 0

local function num(v, fallback)
  v = tonumber(v)
  if v == nil or v ~= v or v == math.huge or v == -math.huge then return fallback end
  return v
end

local cspVersion = 0
if ac.getPatchVersionCode then cspVersion = num(ac.getPatchVersionCode(), 0) end

local function open(t)
  if t < retryAt then return end
  retryAt = t + 5
  local ok, m = pcall(ac.writeMemoryMappedFile, MMF_NAME, LAYOUT)
  if ok and m ~= nil then
    mem, status = m, 'Sharing the weather with SimCoach'
  else
    status = 'Could not share the weather: ' .. tostring(m)
  end
end

local clock = 0

function script.update(dt)
  clock = clock + (num(dt, 0))
  if mem == nil then
    open(clock)
    if mem == nil then return end
  end
  local sim = ac.getSim()
  local c = sim.weatherConditions
  seq = seq + 1                                -- odd while writing, even once a full set is in
  mem.seq = seq
  mem.version = VERSION
  if c ~= nil then
    mem.currentType = num(c.currentType, -1)
    mem.upcomingType = num(c.upcomingType, -1)
    mem.transition = num(c.transition, 0)
  else
    mem.currentType, mem.upcomingType, mem.transition = -1, -1, 0
  end
  mem.rainIntensity = num(sim.rainIntensity, 0)
  mem.rainWetness = num(sim.rainWetness, 0)
  mem.rainWater = num(sim.rainWater, 0)
  mem.ambientTemperature = num(sim.ambientTemperature, 0)
  mem.roadTemperature = num(sim.roadTemperature, 0)
  mem.roadGrip = num(sim.roadGrip, 0)
  mem.timeMultiplier = num(sim.timeMultiplier, 1)
  mem.weatherFX = sim.isWeatherFXActive and 1 or 0
  mem.cspVersion = cspVersion
  mem.timeOfDay = num(sim.timeTotalSeconds, 0)
  seq = seq + 1
  mem.seq = seq
  if setupMem == nil and ac.readMemoryMappedFile and clock >= setupRetryAt then
    setupRetryAt = clock + 2
    local ok_s, sm = pcall(ac.readMemoryMappedFile, 'SimCoach.CSPSetup.v1', [[
      int32_t version; int32_t seq; float fuel; int32_t tyreCompound;
      float pressLF; float pressRF; float pressLR; float pressRR;
      float brakeBias; int32_t wing; int32_t arbFront; int32_t arbRear; int32_t tc; int32_t abs;
    ]])
    if ok_s and sm ~= nil then setupMem = sm end
  end
  if setupMem ~= nil and setupMem.version == 1 and setupMem.seq > 0 and setupMem.seq % 2 == 0 and setupMem.seq ~= lastSetupSeq then
    lastSetupSeq = setupMem.seq
    if ac.setBrakeBias then pcall(ac.setBrakeBias, setupMem.brakeBias / 100.0) end
    if ac.setTC then pcall(ac.setTC, setupMem.tc) end
    if ac.setABS then pcall(ac.setABS, setupMem.abs) end
    if physics and physics.setCarFuel then pcall(physics.setCarFuel, 0, setupMem.fuel) end
  end
end

local NAMES = { [0] = 'Light thunderstorm', 'Thunderstorm', 'Heavy thunderstorm', 'Light drizzle', 'Drizzle',
  'Heavy drizzle', 'Light rain', 'Rain', 'Heavy rain', 'Light snow', 'Snow', 'Heavy snow', 'Light sleet', 'Sleet',
  'Heavy sleet', 'Clear', 'Few clouds', 'Scattered clouds', 'Broken clouds', 'Overcast', 'Fog', 'Mist', 'Smoke',
  'Haze', 'Sand', 'Dust', 'Squalls', 'Tornado', 'Hurricane', 'Cold', 'Hot', 'Windy', 'Hail' }

local function name(t)
  return NAMES[num(t, -1)] or '?'
end

function script.windowMain(dt)
  local sim = ac.getSim()
  ui.text(status)
  ui.text(string.format('Rain %.2f   Wetness %.2f   Puddles %.2f', num(sim.rainIntensity, 0),
    num(sim.rainWetness, 0), num(sim.rainWater, 0)))
  local c = sim.weatherConditions
  if c ~= nil then
    ui.text(string.format('Now: %s   Next: %s (%d%%)', name(c.currentType), name(c.upcomingType),
      math.floor(num(c.transition, 0) * 100 + 0.5)))
  end
  ui.text(sim.isWeatherFXActive and 'Weather: CSP WeatherFX (Pure, Sol...)' or 'Weather: no WeatherFX, so no rain')
end
