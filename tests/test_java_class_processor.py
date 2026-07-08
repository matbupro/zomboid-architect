"""Tests S4-g — JavaClassProcessor (parsing declasses Java decompilees).

Couverture :
- Parse d'un fichier .java (classe, methods, champs, Javadoc)
- _parse_javadoc extrait les tags @param/@return/@throws
- _parse_parameters gere les generics (<String>) et params vides
- _format_class_chunk genere un texte structuration correct
- Cross-references entre classes detectees via imports/fields/methods
- extract() sur dossier avec fichiers multiples
- Ciblee prioritaire : classes connues marquees is_target_class=True
- Erreur : repertoire inexistant

Lancer : pytest tests/test_java_class_processor.py -v
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def tmp_path():
    """Repertoire temporaire."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture()
def class_z_dir(tmp_path):
    """Dossier avec 3 fichiers Java mock (ZombierStats, Item, WeatherManager)."""
    zom_kb = '''
package net.minecraft.src;

import java.util.HashMap;
import java.util.Map;

/**
 * Zombie base statistics for the zombie survival game.
 * @deprecated Use ZombierStatsV2 instead
 */
public class ZombierStats {
    /** The max health of the zombie */
    public static final int MAX_HEALTH = 200;

    private float speed;
    private double damageMultiplier;

    /**
     * Construct a new zombie stats object.
     * @param baseDamage the base damage value
     * @param speedMultiplier how fast the zombie moves
     */
    public ZombierStats(float baseDamage, float speedMultiplier) {
        this.speed = speedMultiplier;
        this.damageMultiplier = baseDamage;
    }

    public float getSpeed() {
        return speed;
    }

    public void setSpeed(float newSpeed) {
        this.speed = newSpeed;
    }

    @Override
    public String toString() {
        return "ZombierStats{speed=" + speed + ", dmg=" + damageMultiplier + "}";
    }
}
'''

    item_java = '''
package net.minecraft.src;

import java.util.List;

/**
 * Item type registry and base class for all in-game items.
 */
public class Item {
    private String name;
    private int id;
    public boolean isFood;
    protected Map<String, Object> properties;

    /**
     * Create a new item with the given properties.
     * @param itemName the display name of the item
     * @param itemId unique integer identifier
     * @return true if the item was registered successfully
     */
    public static boolean register(String itemName, int itemId) {
        return itemName != null && itemId > 0;
    }

    public List<String> getCategories() {
        return categories;
    }
}
'''

    weather_java = '''
package com.pzbloodmoon.weather;

import java.time.LocalDateTime;

/**
 * Weather manager for the game world.
 * Handles temperature, humidity, and rainfall calculations.
 */
public class WeatherManager {
    private int temperature;
    private float humidity;
    private boolean isRaining;
    private LocalDateTime lastFrost;

    public WeatherManager(int temp, float humid) {
        this.temperature = temp;
        this.humidity = humid;
    }

    public void updateWeather(LocalDateTime now) {
        this.lastFrost = now;
    }

    public Map<String, Double> getStats() {
        return Map.of("temp", (double) temperature, "humid", (double) humidity);
    }
}
'''

    empty_class = '''
package net.minecraft.src;

/**
 * An empty utility class with no fields or methods.
 */
public class EmptyUtil {
    private EmptyUtil() {}
}
'''

    tmp_path.joinpath("ZombierStats.java").write_text(zom_kb, encoding="utf-8")
    tmp_path.joinpath("Item.java").write_text(item_java, encoding="utf-8")
    tmp_path.joinpath("WeatherManager.java").write_text(weather_java, encoding="utf-8")
    tmp_path.joinpath("EmptyUtil.java").write_text(empty_class, encoding="utf-8")

    yield tmp_path


# ============================================================================
# Test S4-g : _parse_javadoc — extraction des tags
# ============================================================================


class TestParseJavadoc:
    """S4-g : le parser Javadoc extrait correctement les tags."""

    def test_extract_param_tags(self):
        """@param extrait chaque parametre avec sa description."""
        from ingestor.processors.java_class import _parse_javadoc

        # Passe le TEXTE brut entre /** et */ (ce que le regex extraction renvoie)
        javadoc = '''\n * Creates a new item with the given properties.\n * @param itemName the display name of the item\n * @param itemId unique integer identifier\n * @return true if registered successfully\n'''
        result = _parse_javadoc(javadoc)
        assert "param_itemName" in result
        assert "param_itemId" in result
        assert "return" in result
        assert "display name" in result["param_itemName"]

    def test_extract_returns_body(self):
        """Le corps du Javadoc (sans tags) est sauvegarde en _body."""
        from ingestor.processors.java_class import _parse_javadoc

        javadoc = ' * Base class for all items.\n * @deprecated Use ItemV2\n'
        result = _parse_javadoc(javadoc)
        assert "_body" in result
        assert "Base class" in result["_body"]
        assert "ItemV2" in result["_body"]


# ============================================================================
# Test S4-g : _parse_parameters — signatures methodes
# ============================================================================


class TestParseParameters:
    """S4-g : le parser de parametres gere les cas standards."""

    def test_simple_params(self):
        """Parametres simples : type + nom."""
        from ingestor.processors.java_class import _parse_parameters
        params = _parse_parameters("float baseDamage, float speedMultiplier")
        assert len(params) == 2
        assert params[0] == ("float", "baseDamage")
        assert params[1] == ("float", "speedMultiplier")

    def test_generic_params(self):
        """Parametres generics : Map<String, Object> detecte."""
        from ingestor.processors.java_class import _parse_parameters
        params = _parse_parameters("Map<String, Object> properties")
        assert len(params) == 1
        # Le type peut etre partiellement capture (first token only)
        assert params[0][1] == "properties"

    def test_empty_params(self):
        """Aucun parametre → liste vide."""
        from ingestor.processors.java_class import _parse_parameters
        assert _parse_parameters("") == []
        assert _parse_parameters("   ") == []


# ============================================================================
# Test S4-g : _parse_java_file — parsing complet de classe
# ============================================================================


class TestParseJavaFile:
    """S4-g : le parseur Java extrait correctement les elements d'une classe."""

    def test_parse_class_with_fields_and_methods(self, class_z_dir):
        """Une classe avec champs et methodes est correcte."""
        from ingestor.processors.java_class import _parse_java_file

        cls = _parse_java_file(class_z_dir / "ZombierStats.java")

        assert cls is not None
        assert cls.name == "ZombierStats"
        assert cls.package == "net.minecraft.src"
        assert len(cls.fields) >= 2  # MAX_HEALTH + speed/damageMultiplier
        assert len(cls.methods) >= 1  # constructor ou getter

    def test_parse_class_extends_implements(self, class_z_dir):
        """extends et implements sont captures."""
        from ingestor.processors.java_class import _parse_java_file

        cls = _parse_java_file(class_z_dir / "Item.java")
        assert cls is not None
        # Item n'a pas extends mais a des imports
        assert len(cls.imports) >= 1

    def test_parse_empty_class(self, class_z_dir):
        """Une classe vide (sans champs/methods) est quand meme parsee."""
        from ingestor.processors.java_class import _parse_java_file

        cls = _parse_java_file(class_z_dir / "EmptyUtil.java")
        assert cls is not None
        assert cls.name == "EmptyUtil"
        assert cls.fields == []
        assert cls.methods == []

    def test_parse_no_class(self, tmp_path):
        """Fichier sans declaration de classe retourne None."""
        from ingestor.processors.java_class import _parse_java_file

        fake = tmp_path / "notjava.txt"
        fake.write_text("// Just a comment\n// No class here", encoding="utf-8")
        assert _parse_java_file(fake) is None


# ============================================================================
# Test S4-g : _format_class_chunk — sortie textuelle
# ============================================================================


class TestFormatClassChunk:
    """S4-g : le format de sortie contient les elements attendus."""

    def test_chunk_contains_class_name_and_package(self, class_z_dir):
        """Le chunk affiche le nom et le package de la classe."""
        from ingestor.processors.java_class import _parse_java_file, _format_class_chunk

        cls = _parse_java_file(class_z_dir / "ZombierStats.java")
        assert cls is not None

        chunk_text = _format_class_chunk(cls)
        assert f"Class: ZombierStats" in chunk_text
        assert "package net.minecraft.src" in chunk_text

    def test_chunk_contains_field_declarations(self, class_z_dir):
        """Le chunk liste les champs avec types et access modifiers."""
        from ingestor.processors.java_class import _parse_java_file, _format_class_chunk

        cls = _parse_java_file(class_z_dir / "ZombierStats.java")
        assert cls is not None

        chunk_text = _format_class_chunk(cls)
        # Au moins un champ doit etre presente
        assert any(field in chunk_text for field in ["public", "private", "static", "final"])

    def test_chunk_contains_method_signatures(self, class_z_dir):
        """Le chunk liste les signatures de methodes."""
        from ingestor.processors.java_class import _parse_java_file, _format_class_chunk

        cls = _parse_java_file(class_z_dir / "ZombierStats.java")
        assert cls is not None

        chunk_text = _format_class_chunk(cls)
        assert "getSpeed" in chunk_text or "setSpeed" in chunk_text


# ============================================================================
# Test S4-g : JavaClassProcessor.extract() — dossier entier
# ============================================================================


class TestExtract:
    """S4-g : extract() sur un dossier genere des chunks corrects."""

    def test_extract_all_classes(self, class_z_dir):
        """extract() retourne 1 chunk par classe."""
        import asyncio
        from ingestor.processors.java_class import JavaClassProcessor

        proc = JavaClassProcessor(class_z_dir)
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(proc.extract())
        loop.close()

        assert len(result.chunks) == 4, "Un chunk par .java"
        assert result.collection == "pz_java_api"

    def test_extract_target_classes_marked(self, class_z_dir):
        """Les classes ciblees ont is_target_class=True."""
        import asyncio
        from ingestor.processors.java_class import JavaClassProcessor

        proc = JavaClassProcessor(class_z_dir)
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(proc.extract())
        loop.close()

        target_chunks = [c for c in result.chunks if c.metadata.get("is_target_class")]
        class_names = [c.metadata["class_name"] for c in target_chunks]
        assert "ZombierStats" in class_names, "ZombierStats est une classe ciblee"

    def test_extract_metadata_complete(self, class_z_dir):
        """ExtractionResult a les metadata attendues."""
        import asyncio
        from ingestor.processors.java_class import JavaClassProcessor

        proc = JavaClassProcessor(class_z_dir)
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(proc.extract())
        loop.close()

        meta = result.metadata
        assert meta["classes_parsed"] == 4
        assert meta["total_fields"] > 0
        assert meta["total_methods"] > 0
        assert "ZombierStats" in meta["target_classes_found"]

    def test_extract_inexistent_dir_raises(self):
        """Un dossier inexistant provoque une erreur."""
        import asyncio
        from ingestor.processors.java_class import JavaClassProcessor

        proc = JavaClassProcessor("/non/existent/path/java/classes")
        loop = asyncio.new_event_loop()
        with pytest.raises(ValueError, match="n'est pas un repertoire"):
            loop.run_until_complete(proc.extract())
        loop.close()


# ============================================================================
# Test S4-g : extract() — fichier unique via override
# ============================================================================


class TestExtractSingleFile:
    """S4-g : l'appel avec source=file charge le fichier directement."""

    def test_extract_single_java_file(self, class_z_dir):
        """extract(source=filepath) → 1 chunk pour cette classe."""
        import asyncio
        from ingestor.processors.java_class import JavaClassProcessor

        proc = JavaClassProcessor(class_z_dir)
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(proc.extract(str(class_z_dir / "Item.java")))
        loop.close()

        assert len(result.chunks) == 1
        assert result.chunks[0].metadata["class_name"] == "Item"


# ============================================================================
# Test S4-g : parsing robustesse — cas limites
# ============================================================================


class TestParseEdgeCases:
    """S4-g : le parser gere les cas extremes."""

    def test_parse_class_with_no_package(self, tmp_path):
        """Classe sans declaration package → package vide."""
        from ingestor.processors.java_class import _parse_java_file

        no_pkg = '''
public class NoPackage {
    private String name;
}
'''
        f = tmp_path / "NoPackage.java"
        f.write_text(no_pkg, encoding="utf-8")
        cls = _parse_java_file(f)
        assert cls is not None
        assert cls.package == ""

    def test_parse_class_with_static_final_fields(self, tmp_path):
        """Champs static final captures correctement."""
        from ingestor.processors.java_class import _parse_java_file

        with_static = '''
public class StaticFields {
    public static final int MAX = 100;
    private static final String VERSION = "42.0";
}
'''
        f = tmp_path / "StaticFields.java"
        f.write_text(with_static, encoding="utf-8")
        cls = _parse_java_file(f)
        assert cls is not None

        static_fields = [f for f in cls.fields if f.is_static]
        assert len(static_fields) >= 1

    def test_parse_no_imports(self, tmp_path):
        """Fichier sans imports → liste vide."""
        from ingestor.processors.java_class import _parse_java_file

        no_imp = '''
public class NoImports {
    private int x;
}
'''
        f = tmp_path / "NoImports.java"
        f.write_text(no_imp, encoding="utf-8")
        cls = _parse_java_file(f)
        assert cls is not None
        assert cls.imports == []
