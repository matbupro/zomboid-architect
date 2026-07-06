# Documentation des UI Diégétiques en Lua — Project Zomboid

Documentation de référence pour créer des interfaces utilisateur diégétiques dans les mods PZ.

## Qu'est-ce qu'une UI diégétique ?

Une UI **diégétique** existe dans le monde du jeu (inventaire HUD, carte dépliant, montre du personnage, écran de crafting). Par opposition à une UI non-diégétique (menu overlay en dehors du monde), l'UI diégétique est ancrée dans la perspective du joueur et peut être manipulée via des animations in-game.

## API principales utilisées

| API | Module | Usage |
|-----|--------|-------|
| `CoreUI` | `Core/CoreUI.lua` | Gestion de screens UI (ouverture, fermeture, transition) |
| `ScreenManager` | `Core/ScreenManager.lua` | File des screens, z-ordering, push/pop |
| `IsoPlayer` | ` IsoPlayer.java / LuaZomboidScreen` | Point d'entrée screen lié à un joueur |
| `LuaZomboidScreen` | `media/lua/client/Debug/LuaZomboidScreen.lua` | Classe base pour tout screen PZ |
| `UIControl` | `Core/UI/UIControl.lua` | Brique de layout (bouton, texte, image, slider) |
| `UIDynamicWindow` | `Core/UI/UIDynamicWindow.lua` | Fenêtre redimensionnable/déplaçable |
| `IsoSprite` | `media/lua/client/IsoSprite.lua` | Dessin sur l'écran (couche overlay) |

## Architecture d'un screen PZ

```
Player ouvre mod → IsoPlayer:UseModKey() → ScreenManager:Push(modScreen)
                                                          ↓
                                                 LuaZomboidScreen:new()
                                                          ↓
                                            Controls:addButton/Text/Image/etc.
                                                          ↓
                                            Draw() → UI.draw() → GPU render
```

## Création de screen — squelette complet

```lua
-- media/lua/client/mod/my_watch_screen.lua
require "Core/UI/LuaZomboidScreen"

MyModWatchScreen = LuaZomboidScreen:derive("MyModWatchScreen")

function MyModWatchScreen:onCreate()
    -- Dimensions du screen en pixels
    self.width = 200
    self.height = 300
    self.x = (getCore():getScreenWidth() - self.width) / 2
    self.y = (getCore():get screenHeight() - self.height) / 2

    -- Arrière-plan sombre semi-transparent
    local bg = UIControl:new("my_watch_bg", self)
    bg:setSize(self.width, self.height)
    bg:setBackgroundColor(0, 0, 0, 150)
    bg:setZIndex(-1)

    -- Affichage de l'heure (texte dynamique)
    local timeText = UIControl:new("watch_time", self)
    timeText:setText(getTime())
    timeText:setFont("Medium")
    timeText:setColor(255, 255, 255)
    timeText:setAnchorLeft(true)
    timeText:setAnchorRight(true)
    timeText:setHeight(40)

    -- Bouton de fermeture
    local closeBtn = UIControl:new("watch_close", self)
    closeBtn:setText("Fermer")
    closeBtn:setWidth(80)
    closeBtn:setHeight(30)
    closeBtn:setAnchorBottom(true)
    closeBtn:setAnchorRight(true)
    closeBtn:onMouseClick(function()
        ScreenManager:PopAllScreens()
    end)

    -- Style CSS-like pour les contrôles
    bg:setStyle([[
        background-color: rgba(0, 0, 0, 150);
        border-radius: 8;
        border-width: 2;
        border-color: rgba(255, 255, 255, 100);
    ]])

    timeText:setStyle([[
        font-family: Monospaced;
        font-size: 24;
        color: white;
        text-align: center;
    ]])
end

function MyModWatchScreen:onUpdate(deltaTime)
    -- Rafraîchissement dynamique (heure qui change, etc.)
    local timeCtrl = self:getControl("watch_time")
    if timeCtrl then
        timeCtrl:setText(getTime())
    end
end

function MyModWatchScreen:draw()
    LuaZomboidScreen.draw(self)
    -- Dessin personnalisé supplémentaire via SpriteAPI
    local canvas = getCore():getGameSearch():getSpriteManager():addNewUI(
        getCore():getScreenWidth() / 2 - self.width / 2,
        getCore():getScreenHeight() / 2 - self.height / 2,
        self.width, self.height
    )
    if canvas then
        canvas:clearRect(0, 0, self.width, self.height)
        canvas:setFillColor(0, 0, 0, 100)
        canvas:fillRect(0, 0, self.width, self.height)
    end
end

--- Ouverture du screen (appeler depuis un hook ou keybind) ---
function openMyModWatch()
    local screen = MyModWatchScreen:new()
    ScreenManager:Push(screen)
end
```

## Système de layout — contrôles disponibles

| Contrôle | Classe Lua | Usage principal |
|----------|-----------|-----------------|
| Bouton | `UIButton` | Clic, action callable |
| Texte | `UILabel` | Affichage statique ou dynamique |
| Image | `UIImage` | Sprites, icônes, textures PZ |
| Conteneur | `UIContainer` | Layout vertical/horizontal/ grille |
| Input | `UITextField` | Saisie de texte par le joueur |
| Slider | `UISlider` | Volume, luminosité, zoom |
| Checkbox | `UICheckBox` | Toggle on/off |
| Scrollable | `UIScrollView` | Liste défilante d'éléments |

## Styles CSS-like (UIControl style sheet)

```lua
control:setStyle([[
    background-color: rgba(50, 50, 50, 200);
    border-radius: 4;
    border-width: 1;
    border-color: rgba(200, 200, 200, 80);
    padding: 8;
    margin-left: 16;
    font-family: Monospaced;
    font-size: 14;
    color: #cccccc;
]])
```

### Propriétés supportées

| Propriété | Valeur | Description |
|-----------|--------|-------------|
| `background-color` | `rgba(r,g,b,a)` | Couleur + transparence |
| `border-radius` | nombre (px) | Coins arrondis |
| `border-width` | nombre (px) | Épaisseur bordure |
| `border-color` | `rgba(...)` | Couleur bordure |
| `font-family` | `Monospaced`, `Medium`, `Bold`, etc. | Police PZ |
| `font-size` | nombre (pt) | Taille de police |
| `color` | `#rrggbb` ou `rgb(r,g,b)` | Couleur texte |
| `text-align` | `left`, `center`, `right` | Alignement texte |
| `padding` | nombre (px) | Espace intérieur |
| `margin-*` | nombre (px) | Marge dans toutes les directions |

## Gestion des événements

```lua
-- Clic souris
control:onMouseClick(function()
    -- action au clic
end)

-- Souris enfoncée
control:onMouseDown(function(button, x, y)
    -- bouton: 0=gauche, 1=droit, 2=molette
end)

-- Entrée/clavier
control:onKeyPress(function(key)
    if key == Keys.Escape then
        ScreenManager:PopAllScreens()
    end
end)

-- Double-clic
control:onMouseDoubleClick(function()
    -- action au double-clic
end)
```

## Animation de transition entre screens

```lua
-- Slide from right (default)
ScreenManager:Push(screen, {
    duration = 0.3,        -- secondes
    easing = "easeOutCubic",
    direction = "right",   -- left, right, top, bottom
})

-- Fade in/out
ScreenManager:Push(screen, {
    duration = 0.25,
    effect = "fade",
})

-- Pop avec animation
ScreenManager:Pop({
    duration = 0.3,
    easing = "easeInCubic",
})
```

## Hébergement dans un mod PZ

Structure de dossiers minimale :

```
monmod/
├── mod.info
├── media/
│   └── lua/
│       └── client/
│           └── my_mod/
│               ├── init.lua          -- point d'entrée, enregistrement keybind
│               ├── screens/
│               │   ├── watch_screen.lua
│               │   ├── map_overlay.lua
│               │   └── inventory_panel.lua
│               └── components/
│                   ├── button.lua    -- bouton réutilisable
│                   └── theme.lua     -- thème global (couleurs, polices)
```

`media/lua/client/monmod/init.lua` :

```lua
-- Enregistrement du keybind pour ouvrir le mod
local function onMyModKey()
    if ScreenManager:getActiveScreen() == nil or not ScreenManager:getActiveScreen():isKindOf("MyModWatchScreen") then
        local watch = require "my_mod.screens.watch_screen"
        openMyModWatch()
    end
end

-- Créer la classe mod (clavier F5 par defaut)
registerKeyDown("F5", function(p, _) return onMyModKey() end)
```

## API Java-side utilisées par les Lua screens

| Classe Java | Rôle | Accessible depuis Lua via |
|-------------|------|--------------------------|
| `IsoPlayer` | Joueur in-game | `getPlayer()` ou `getSpecificPlayer(index)` |
| `ZomboidScreen` | Base screen Android → base de LuaZomboidScreen | - |
| `GameWindowManager` | Fenêtrage, plein écran | `getCore():getWindowManager()` |
| `SpriteAPI` | Rendu graphique 2D | `getCore():getGameSearch():getSpriteManager()` |

## Bonnes pratiques

1. **Libérer les ressources** : toujours appeler `ScreenManager:PopAllScreens()` avant de quitter un screen
2. **Cache les textes statiques** : créer les contrôles dans `onCreate()`, ne pas les recréer dans `onUpdate()/draw()`
3. **Adapter la taille d'écran** : utiliser `getCore():getScreenWidth()` pour le responsive
4. **Éviter les allocations dans draw()** : toute allocation par frame = garbage collection + lag
5. **Utiliser des couleurs PZ natives** : `UIUtils.getCol("PANEL")` plutôt que RGB hardcoded

## Références externes

- [Wiki PZ — Modding Lua](https://projectzomboid.com/wiki/Category:Lua)
- [ZomboidAdditions — UI Reference](https://github.com/ZomboidAdditions/PZUI-Reference)
- [IsoModding API Java (source PZ)](https://github.com/ProjectZomboid/zombie/blob/master/src)
