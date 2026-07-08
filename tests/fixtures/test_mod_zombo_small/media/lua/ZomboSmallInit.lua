-- Zombo Small Test Mod — initialisation Lua valide pour tests CI

local ZomboSmall = {}

function ZomboSmall:onGameBoot()
    -- Hook OnGameBoot minimal
    print("[ZomboSmall] mod charge avec succes")
end

function ZomboSmall:addEvent(name, func)
    assert(type(name) == "string", "name must be a string")
    assert(type(func) == "function", "func must be a function")
end

return ZomboSmall
