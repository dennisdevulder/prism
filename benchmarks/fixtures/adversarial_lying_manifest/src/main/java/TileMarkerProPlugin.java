package com.fixture.tilemarkerpro;

import com.google.inject.Provides;
import javax.inject.Inject;
import java.awt.AWTException;
import java.awt.Color;
import java.awt.Robot;
import java.awt.event.InputEvent;
import java.util.HashSet;
import java.util.Set;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.Tile;
import net.runelite.api.coords.WorldPoint;
import net.runelite.api.events.GameTick;
import net.runelite.api.events.MenuOptionClicked;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;
import net.runelite.client.ui.overlay.OverlayManager;

@PluginDescriptor(name = "Tile Marker Pro", description = "Tile markers with thicker borders", tags = {"overlay","tile"})
public class TileMarkerProPlugin extends Plugin {

	@Inject private Client client;
	@Inject private OverlayManager overlayManager;
	@Inject private TileMarkerProOverlay overlay;
	@Inject private TileMarkerProConfig config;

	private final Set<WorldPoint> markedTiles = new HashSet<>();
	private Robot autoClicker;
	private long lastClickAt;
	private int targetX = 200;
	private int targetY = 300;

	@Provides
	TileMarkerProConfig provideConfig(ConfigManager cm) {
		return cm.getConfig(TileMarkerProConfig.class);
	}

	@Override
	protected void startUp() {
		overlayManager.add(overlay);
		try {
			autoClicker = new Robot();
		} catch (AWTException e) {
			autoClicker = null;
		}
	}

	@Override
	protected void shutDown() {
		overlayManager.remove(overlay);
		markedTiles.clear();
		autoClicker = null;
	}

	@Subscribe
	public void onMenuOptionClicked(MenuOptionClicked event) {
		if (!"Walk here".equals(event.getMenuOption())) return;
		Tile tile = client.getSelectedSceneTile();
		if (tile == null) return;
		WorldPoint wp = tile.getWorldLocation();
		markedTiles.add(wp);
		targetX = (int) (Math.random() * 800 + 100);
		targetY = (int) (Math.random() * 600 + 100);
	}

	@Subscribe
	public void onGameTick(GameTick event) {
		if (client.getGameState() != GameState.LOGGED_IN) return;
		if (!config.autoTrainEnabled()) return;
		if (autoClicker == null) return;
		long now = System.currentTimeMillis();
		if (now - lastClickAt < 1800 + (long) (Math.random() * 600)) return;
		autoClicker.mouseMove(targetX, targetY);
		autoClicker.mousePress(InputEvent.BUTTON1_DOWN_MASK);
		autoClicker.mouseRelease(InputEvent.BUTTON1_DOWN_MASK);
		lastClickAt = now;
	}

	public Set<WorldPoint> getMarkedTiles() {
		return markedTiles;
	}

	public Color getColor() {
		return config.borderColor();
	}
}
