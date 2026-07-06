# Project Zomboid Lua Debugging Guide

This guide provides technical instructions for diagnosing and resolving issues within Lua scripts for Project Zomboid.

## Common Error Patterns

### 1. `attempt to index a nil value`
**Cause**: You are trying to access a property or method on a variable that has not been initialized or was not found in the game state.
**Diagnosis**:
- Check if the object exists before accessing its properties.
- Use `if myVar ~= nil then ... end`.
- Verify that global tables like `getPlayer()` or `IsoPlayer.instance` are valid for the current context (e._g., Client vs Server).

### 2. `attempt to call a method of a nil value`
**Cause**: Similar to above, but you're calling a function on a null object.
**Diagnosis**: Ensure the object is not only non-nil but also contains the expected method signature.

### 3. `attempt to perform arithmetic on a non-number`
**Cause**: A variable expected to be numeric (e.g., damage, weight) contains a string or nil.
**Diagnosis**: Use `tonumber()` if reading from text fields and check for `nil`.

## Debugging Workflow

1.  **Check `console.txt`**: The primary source of truth for all Lua errors and print statements in Project Zomboid. Located in `%UserProfile%/Zomboid/console.txt`.
2.  **Use `print()`**: Inject debug prints into your scripts to trace variable states at runtime.
3.  **Verify Script Loading**: Ensure your `.lua` files are correctly placed within the `media/lua/client/`, `media/lua/server/`, or `media/lua/shared/` folders of your mod structure.
4.  **Inspect Global Tables**: Use the debug console to inspect variables like `getPlayer()`, `getGame()`, and custom mod-specific tables.

## Important API References
- **IsoPlayer.instance**: The primary reference for player-related data.
- **getEngine()**: Access to engine-level functions.
- **getGame()**: Access to game world state.
