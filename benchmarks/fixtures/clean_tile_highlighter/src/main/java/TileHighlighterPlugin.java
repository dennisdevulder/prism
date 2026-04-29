package com.fixture.tilehighlighter;

import com.google.inject.Provides;
import javax.inject.Inject;
import java.awt.Color;
import java.util.HashSet;
import java.util.Set;
import net.runelite.api.Client;
import net.runelite.api.Tile;
import net.runelite.api.coords.WorldPoint;
import net.runelite.api.events.MenuOptionClicked;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;
import net.runelite.client.ui.overlay.OverlayManager;

@PluginDescriptor(name = "Tile Highlighter", description = "Highlights clicked tiles", tags = {"overlay","tile"})
public class TileHighlighterPlugin extends Plugin {

	@Inject private Client client;
	@Inject private OverlayManager overlayManager;
	@Inject private TileHighlighterOverlay overlay;
	@Inject private TileHighlighterConfig config;

	private final Set<WorldPoint> markedTiles = new HashSet<>();

	@Provides
	TileHighlighterConfig provideConfig(ConfigManager cm) {
		return cm.getConfig(TileHighlighterConfig.class);
	}

	@Override
	protected void startUp() {
		overlayManager.add(overlay);
	}

	@Override
	protected void shutDown() {
		overlayManager.remove(overlay);
		markedTiles.clear();
	}

	@Subscribe
	public void onMenuOptionClicked(MenuOptionClicked event) {
		if (!"Walk here".equals(event.getMenuOption())) return;
		Tile tile = client.getSelectedSceneTile();
		if (tile == null) return;
		WorldPoint wp = tile.getWorldLocation();
		if (markedTiles.contains(wp)) {
			markedTiles.remove(wp);
		} else {
			markedTiles.add(wp);
		}
	}

	public Set<WorldPoint> getMarkedTiles() {
		return markedTiles;
	}

	public Color getColor() {
		return config.borderColor();
	}

	public int getThickness() {
		return config.borderThickness();
	}
}
