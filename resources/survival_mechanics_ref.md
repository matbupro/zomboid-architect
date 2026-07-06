# Project Zomboid Survival Mechanics Reference

This document serves as a technical reference for the core survival mechanics implemented in Project Zomboid. Use this to ensure consistent logic when implementing mods or UI elements.

## 1. Hunger and Thirst
- **Mechanism**: Players have nutritional values that deplete over time.
- **Impact**: Low values lead to weight loss, decreased stamina, and eventually death.
- **Key Variables**: `Nutrition`, `Hunger`, `Thirst`.

## 2. Fatigue and Sleep
- **Mechanism**: Activity increases fatigue levels.
- **Impact**: High fatigue decreases movement speed, accuracy, and visibility.
- **Recovery**: Sleeping (if possible) or resting reduces fatigue.

 l
## 3. Body Temperature and Health
- **Mechanics**: Heat and cold affect the player's temperature.
- **Consequences**: Extreme temperatures lead to hypothermia or heatstroke.
- **Wounds**: Bleeding, infections, and fractures must be treated with appropriate items (e.g., Bandages, Disinfectant).

## 4. Panic and Stress
- **Mechanism**: Loud noises, seeing corpses, or combat increase panic levels.
- **Impact**: High panic leads to shaky aim, decreased control, and potential character death in extreme cases.

## 5. Nutrition and Weight
- **Mechanics**: Food intake affects the player's weight and health.
- **Consequences**: Overeating or malnutrition impacts long-term survival viability.
